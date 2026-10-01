"""
AI синтез чрез Claude API.
Два извиквания на ден:
  1. Макро бриф + секторна верижна логика (Слой 1 → Слой 2 наратив)
  2. Per-ticker карти: "защо сега", катализатори, рискове,
     Action/Watchlist класификация — batch в едно извикване, JSON изход.

Английски за тикъри и данни, български за обясненията (Секция 6.1).
"""
from __future__ import annotations
import datetime as dt
import json
import re
from functools import lru_cache
import requests
import yfinance as yf
import json_repair

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import backtest
from src import net_utils

API_URL = "https://api.anthropic.com/v1/messages"


class TruncatedResponse(RuntimeError):
    """
    FIX 2026-09-23: отговорът е спрял на max_tokens. Хвърля се ВМЕСТО да се
    върне орязаният текст — така той никога не стига до _parse_json/json_repair.

    Причината е 23.09, първият run на claude-sonnet-5: секторната карта излезе
    празна, COT — 6 пазара вместо ~15, XRP текст прекъснат по средата на дума,
    празни JPY и SBUX тези. Всяко отрязано извикване е пристигнало със
    stop_reason="max_tokens", но _call_claude връщаше само текстовите блокове и
    изхвърляше останалото. После json_repair — построен точно за да спасява
    truncated JSON — запушваше дупката, и повредата изглеждаше като успех.
    Две защити работеха срещу нас.

    Подклас на RuntimeError, затова съществуващите try/except на всяко
    извикване го хващат и секцията деградира както при всяка друга грешка —
    но с видимо предупреждение в брифа (виж TRUNCATIONS).
    """


# FIX 2026-09-23: записи за текущия run. main.py ги нулира в началото и ги
# слага в брифа — отрязванията като видимо предупреждение, usage-а като данни.
# AI_USAGE съществува, защото Actions логът не е достъпен без автентикация, а
# без него реалните token числа по секции нямаше откъде да се видят.
TRUNCATIONS: list[dict] = []
AI_USAGE: list[dict] = []

# Име на извикващата функция → четим етикет за лога и брифа. Извличат се от
# стека, за да не се пипат шестте call site-а само заради етикет.
_SECTION_LABELS = {
    "macro_and_sector_brief": "Макро бриф и секторна карта",
    "_narratives_for_batch": "Тикър наративи",
    "_cot_theses_for_batch": "COT тези",
    "thesis_reality_check": "Проверка на тезите срещу новините",
    "watch_ticker_digest": "Наблюдавани тикъри",
    "short_thesis_global_context": "Short контекст",
    "significant_news": "Значими новини",
    "_probe": "Проверка на модела",
}


def _call_claude(system: str, user: str, max_tokens: int = 4000,
                 extra_messages: list[dict] | None = None,
                 allow_truncation: bool = False) -> str:
    """
    extra_messages: FIX 2026-08-17 (macro brief crash) — опционални допълнителни
    turns СЛЕД началния user съобщение (напр. [{"role": "assistant", "content":
    <malformed отговор>}, {"role": "user", "content": "поправи JSON-а"}]) — за
    Ниво 1 "smart retry", виж macro_and_sector_brief(). Празно по подразбиране,
    съществуващите извиквания с еднократно user съобщение остават непроменени.
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY липсва")
    messages = [{"role": "user", "content": user}]
    if extra_messages:
        messages += extra_messages
    r = requests.post(API_URL, headers={
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, json={
        "model": config.CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }, timeout=180)
    r.raise_for_status()
    resp = r.json()

    # FIX 2026-09-23: stop_reason и usage се четат при ВСЯКО извикване.
    caller = sys._getframe(1).f_code.co_name
    section = _SECTION_LABELS.get(caller, caller)
    usage = resp.get("usage") or {}
    stop = resp.get("stop_reason")
    out_tok = usage.get("output_tokens")
    AI_USAGE.append({"section": section, "model": config.CLAUDE_MODEL,
                     "input_tokens": usage.get("input_tokens"),
                     "output_tokens": out_tok, "max_tokens": max_tokens,
                     "stop_reason": stop})
    print(f"[ai] {section}: out={out_tok}/{max_tokens} "
          f"in={usage.get('input_tokens')} stop={stop}")

    if stop == "max_tokens" and not allow_truncation:
        TRUNCATIONS.append({"section": section, "max_tokens": max_tokens,
                            "output_tokens": out_tok, "model": config.CLAUDE_MODEL})
        print(f"[ai] ⚠ ОТРЯЗАН ОТГОВОР — {section}: достигнат лимит {max_tokens} "
              f"токена ({config.CLAUDE_MODEL}). Отговорът НЕ се подава на парсера.")
        raise TruncatedResponse(f"{section}: stop_reason=max_tokens при {max_tokens}")

    return "".join(b.get("text", "") for b in resp["content"]
                   if b.get("type") == "text")


def _parse_json(text: str):
    """
    Ниво 0 защита (FIX 2026-08-17 — крашнат production run: macro_and_sector_
    brief() нямаше НИКАКВА защита срещу malformed JSON от Claude, изключението
    стигна необхванато до run() и събори целия pipeline). Споделена helper за
    macro_and_sector_brief/_narratives_for_batch/_cot_theses_for_batch — един
    fix предпазва и трите извиквания, не дублиран по call site.

    json.loads() first (бърз, строг път за нормалния случай); при провал
    json_repair.loads() поправя дребни синтактични грешки (липсваща запетайка/
    кавичка, truncated при token limit) БЕЗ нова AI заявка — нулева допълнителна
    цена. Емпирично тествано на реалистични malformed случаи — възстановява
    коректен dict във всички (виж experiments discussion 2026-08-17).

    ВАЖНО: json_repair НЕ хвърля изключение при напълно неспасяем вход — връща
    '' (empty string), не None/dict (потвърдено емпирично). Затова explicit
    проверяваме isinstance+truthiness на резултата, за да различим "поправено
    успешно" от "нищо не остана за поправяне" — второто продължава да се
    третира като провал (re-raise), за да сработи Ниво 1 retry нагоре по
    веригата (за extend-натите извиквания, виж macro_and_sector_brief).
    """
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()
    try:
        return _fix_text(json.loads(clean))
    except json.JSONDecodeError as e:
        repaired = json_repair.loads(clean)
        if isinstance(repaired, (dict, list)) and repaired:
            print(f"[ai] _parse_json: json_repair поправи malformed JSON ({e})")
            return _fix_text(repaired)
        raise


def _fix_text(obj):
    """_fix_translit + един обобщен лог ред за хибридните думи в отговора."""
    _HYBRIDS.clear()
    out = _fix_translit(obj)
    if _HYBRIDS:
        print(f"[ai] смесено писмо (само лог, {len(_HYBRIDS)}): "
              f"{', '.join(dict.fromkeys(_HYBRIDS))}")
    return out


# FIX 2026-09-25: латински транслитерации на български думи в AI текстовете.
# Сканирана цялата COT история: единствената е "ekspozitsiya" — 7 пъти от 01.09.
# Замяната е в кода, не в промпта: за толкова рядка грешка промпт инструкция е
# ненадеждна, а детерминистичната замяна струва нищо. Нови случаи не се
# поправят автоматично (списъкът не бива да расте на сляпо), а се логват, за да
# се видят.
_TRANSLIT_FIX = {
    "ekspozitsiya": "експозиция", "ekspozitsiyata": "експозицията",
    "ekspozitsii": "експозиции", "ekspozitsiite": "експозициите",
    # FIX 2026-09-28: останалите потвърдени случаи от историята (скан 06–09.2026)
    "natisik": "натиск", "volatilnost": "волатилност", "direktnost": "директност",
    "najsilnite": "най-силните",
}
# FIX 2026-09-28: детекторът от 25.09 хващаше САМО наставките -tsiya/-tsii/
# -iyata/-tsiite (скроен около "ekspozitsiya") — "natisik" (28.09) не пасва на
# нито една. Нов модел, измерен върху цялата история (2587 различни латински
# думи в малки букви в български текст — английските термини са легитимни по
# дизайн): 6 удара, всичките реални транслитерации (ekspozitsiya ×7,
# najsilnite, dedik[ирани], volatilnost, direktnost, natisik), 0 английски
# думи. Нови случаи само се логват — замяна само за потвърдените по-горе.
_TRANSLIT_RE = re.compile(
    r"(?<![A-Za-z\-])[A-Za-z]{4,}(?![A-Za-z\-])")
_TRANSLIT_PAT = re.compile(
    r"^naj|nost$|(?<!n)ik$|tsi(?:ya|i|a|e)|iya|zh|sht|[^aeiou]ya$|yu|ski$|ska$", re.I)
# FIX 2026-09-28: китайски/японски/корейски символи в български текст — 6 появи
# в историята (損害, 底, 升级, 映射, 催化剂 в DXCM 21.09, 純 в Cocoa 28.09).
# Никога не са легитимни тук → премахват се и се логват.
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]+")
# FIX 2026-09-29: руски букви, които ги няма в българския (ы, э, ё) — "по-высоката"
# (Lean Hogs), "по-высоки" (5Y) на 29.09. Измерено върху 74 дни (123 745 низа):
# 10 появи, 8 различни думи (высок-×6, события×2, это, экспанзия), всичките
# руски, 0 фалшиви. Само лог — автоматична замяна не е безопасна ("события").
_RU_ONLY_RE = re.compile(r"[\w\-]*[ЫыЭэЁё][\w\-]*")
# FIX 2026-09-29: несъществуващи кирилски думи с потвърдена замяна. "ускелетира"
# — 2 появи на 29.09 (новините за RTX и AMD), 0 преди това в 74 дни. Списъкът
# расте само с потвърдени случаи, както _TRANSLIT_FIX.
_CYR_WORD_FIX = {"ускелетира": "ускорява", "ускелетират": "ускоряват"}
_CYR_WORD_RE = re.compile(r"[А-Яа-я]+")
# FIX 2026-09-28: латински букви-двойници в иначе кирилска дума ("нямa",
# "секторa", "Oперира") — изглеждат еднакво, но са друг символ. Замяна само
# когато латинските букви са ≤2 и ВСИЧКИ са двойници: иначе е хибрид
# ("момentum", "benefitват", "expозиция" — последната е изцяло от двойници,
# но замяната би дала "ехрозиция", пак грешна дума) → само лог. Измерено върху
# историята: 12 различни замени (24 появи), всичките правилни; 88 хибрида.
_HOMOGLYPHS = dict(zip("aeopcxyAEOPCXTHKMB", "аеорсхуАЕОРСХТНКМВ"))
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+")
# хибридите се събират за един обобщен лог ред на AI отговор (виж _parse_json)
_HYBRIDS: list[str] = []


def _is_pure_cyrillic(word: str) -> bool:
    return bool(word) and all(("А" <= c <= "я" or c in "Ёё") for c in word)


def _fix_homoglyphs(s: str) -> str:
    """
    FIX 2026-10-02 (т.4 от прегледа на 01.10): самотен ASCII буква-двойник
    ("e" вместо "е") преди не стигаше нито до поправката, нито до лога —
    `not lat or len(lat) == len(w)` връщаше w непроменено ПРЕДИ `_HYBRIDS.append`
    за ЦЯЛО-ASCII "дума" (а едносимволен ASCII токен е винаги цяло-ASCII по
    дефиниция). Сега: едносимволен токен, който Е познат двойник (в
    _HOMOGLYPHS), се поправя автоматично САМО ако думите ПРЕДИ и СЛЕД него са
    изцяло кирилски (ниско-рисков контекст — кирилско "е"/"а" между две
    кирилски думи няма легитимно ASCII четене); иначе само лог. Multi-char
    ASCII "думи" (легитимни тикъри/английски термини) остават непипнати, както
    досега.

    КРИТИЧНО изключение, открито при прогон на цялата история (на пробен
    вариант без тази проверка: 355 "поправки", после сведени до 1802 чисти
    лог записа без нея — виж по-долу):
      • "x" директно до цифра ("1.5x", "обем >1.5x среден") Е multiplier
        нотация, не буква — `_WORD_RE` не матчва цифри, затова "обем" /
        "среден" излизат като "съседни кирилски думи" на "x", и без тази
        проверка "1.5x" се чупеше на "1.5х".
      • Едносимволни ASCII абревиатурни букви, допрени до "/", "&", "'" или
        "." (P/E, M&A, O'Neil, J.B. Hunt, J.P. Morgan) доминираха лога
        (726×P + 429×E от "P/E", 110×A + 99×M от "M&A", 74×O от "O'Neil" —
        98% от 1802-те записа), давейки реално полезните случаи.
    Символ непосредствено ДОПРЯН (без интервал) до цифра ИЛИ /&-'. преди ИЛИ
    след самотната буква → изобщо не се третира като дума-кандидат (нито
    поправка, нито лог). След тази проверка: 9 авто-поправки + 43 лог записа
    за ~90 дни история (от които 19 "Coffee C" — легитимно COT пазарно име,
    14 генерирано "e" между нечисто-кирилски думи, останалото разни ситуации
    като "Zone A" — приемлив, нисък шум).
    """
    def repl(m):
        w = m.group(0)
        lat = [c for c in w if c.isascii()]
        if not lat:
            return w
        if len(lat) == len(w):
            if len(w) == 1 and w in _HOMOGLYPHS:
                touches = lambda c: c.isdigit() or c in "/&-'."
                if ((m.start() > 0 and touches(s[m.start() - 1]))
                        or (m.end() < len(s) and touches(s[m.end()]))):
                    return w  # "1.5x"/"P/E"/"M&A"/"O'Neil"/"J.B." и т.н. — не буква-двойник
                prev_matches = list(_WORD_RE.finditer(s[:m.start()]))
                prev_word = prev_matches[-1].group(0) if prev_matches else ""
                next_match = _WORD_RE.search(s[m.end():])
                next_word = next_match.group(0) if next_match else ""
                if _is_pure_cyrillic(prev_word) and _is_pure_cyrillic(next_word):
                    fixed = _HOMOGLYPHS[w]
                    print(f"[ai] самотен буква-двойник заменен: '{w}' → '{fixed}' "
                          f"(между '{prev_word}' и '{next_word}')")
                    return fixed
                _HYBRIDS.append(w)
            return w
        if len(lat) <= 2 and len(w) - len(lat) >= 2 and all(c in _HOMOGLYPHS for c in lat):
            fixed = "".join(_HOMOGLYPHS.get(c, c) for c in w)
            print(f"[ai] буква-двойник заменена: '{w}' → '{fixed}'")
            return fixed
        _HYBRIDS.append(w)
        return w
    return _WORD_RE.sub(repl, s)


# FIX 2026-10-02 (т.4 от прегледа на 01.10): "по-ата" (01.10, 2Y Treasury теза)
# — изпусната дума в кирилска фраза, не max_tokens срязване (ai_truncations
# беше []) и не слепена латиница+кирилица (_fix_glued цели друг дефект).
# Няма безопасна генерична поправка без BG речник — само лог. Ползва СЪЩИЯ
# исторически корпус като _fix_glued (_bg_vocab()), но count==0 (никога
# невиждана дума ДОСЕГА), не count<3: измерено на 01.10 срещу корпуса от
# ВСИЧКИ предходни дни (без самия 01.10, за да симулира реалния момент на
# проверка) — 2/23 "по-XXX" суфикса от брифа флагнати с count==0 ("ата" —
# реалният бъг, и "меките" — легитимна, но за пръв път употребена дума);
# count<3 прагът (като при _fix_glued) даде 62/293 за цялата история —
# твърде шумно за този проблем (повечето рядко срещани "по-" форми са
# напълно легитимни думи, не отрязъци).
_PO_SUFFIX_RE = re.compile(r"по-([а-яА-Я]+)")


def _check_po_suffix(s: str) -> None:
    cyr = _bg_vocab()[0]
    if not cyr:
        return
    seen = set()
    for m in _PO_SUFFIX_RE.finditer(s):
        suf = m.group(1).lower()
        if suf in seen or cyr.get(suf, 0) > 0:
            continue
        seen.add(suf)
        print(f"[ai] ⚠ 'по-{suf}' — суфиксът не е срещан в историята (вероятно "
              f"изпусната дума) — «…{s[max(0, m.start() - 20):m.end() + 20]}…»")


def _fix_translit(obj):
    """
    Обхожда всички низове в парснатия JSON (всички AI отговори минават през
    _parse_json): премахва CJK символи, заменя букви-двойници и познатите
    транслитерации, логва новите и хибридите.
    """
    if isinstance(obj, dict):
        return {k: _fix_translit(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fix_translit(v) for v in obj]
    if not isinstance(obj, str):
        return obj
    if _CJK_RE.search(obj):
        for m in _CJK_RE.finditer(obj):
            print(f"[ai] ⚠ премахнати чужди символи '{m.group(0)}' в "
                  f"«…{obj[max(0, m.start() - 40):m.end() + 20]}…»")
        obj = re.sub(r" {2,}", " ", _CJK_RE.sub("", obj))
    for m in _RU_ONLY_RE.finditer(obj):
        print(f"[ai] ⚠ руска буква (ы/э/ё) в '{m.group(0)}' — "
              f"«…{obj[max(0, m.start() - 40):m.end() + 20]}…»")
    if not re.search(r"[А-Яа-я]", obj):
        return obj  # чисто латински низ (тикър, английско заглавие) — не е наш случай
    _check_po_suffix(obj)
    obj = _fix_homoglyphs(obj)
    obj = _fix_glued(obj)
    def cyr_repl(m):
        w = m.group(0)
        fixed = _CYR_WORD_FIX.get(w.lower())
        if fixed is None:
            return w
        print(f"[ai] несъществуваща дума заменена: '{w}' → '{fixed}'")
        return fixed.capitalize() if w[0].isupper() else fixed
    obj = _CYR_WORD_RE.sub(cyr_repl, obj)
    def repl(m):
        w = m.group(0)
        fixed = _TRANSLIT_FIX.get(w.lower())
        if fixed is not None:
            return fixed.capitalize() if w[0].isupper() else fixed
        if _TRANSLIT_PAT.search(w):
            print(f"[ai] ⚠ латинска транслитерация без замяна: '{w}' — добави в _TRANSLIT_FIX")
        elif (cyr_w := _latin_as_bg(w)):
            print(f"[ai] ⚠ латиница вместо кирилица: '{w}' (= '{cyr_w}') — само лог")
        return w
    return _TRANSLIT_RE.sub(repl, obj)


# FIX 2026-09-30: речник от предишните брифове (docs/data/*.json, вече в
# checkout-а на Actions) — за слепените думи и за латиница вместо кирилица.
# Липсва/гръмне ли → празен речник и двете проверки просто не правят нищо.
_GLUED_RE = re.compile(r"(?<![A-Za-zА-Яа-я])([A-Za-z]{4,})([а-я]{5,})(?![A-Za-zА-Яа-я])")
_BG_TRANSLIT = ([("sht", "щ"), ("zh", "ж"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"),
                 ("yu", "ю"), ("ya", "я")]
                + list(zip("abvgdeziyklmnoprstufhc", "абвгдезийклмнопрстуфхк")))


@lru_cache(maxsize=1)
def _bg_vocab() -> tuple[dict, dict]:
    """(кирилска дума → брой, латинска дума → брой) в българските текстове."""
    from collections import Counter
    cyr, lat = Counter(), Counter()
    try:
        def walk(o):
            if isinstance(o, dict):
                for v in o.values(): yield from walk(v)
            elif isinstance(o, list):
                for v in o: yield from walk(v)
            elif isinstance(o, str) and re.search(r"[а-я]", o):
                yield o
        for f in sorted((config.DOCS_DIR / "data").glob("20*.json")):
            for s in walk(json.loads(f.read_text(encoding="utf-8"))):
                cyr.update(w.lower() for w in re.findall(
                    r"(?<![A-Za-zА-Яа-я])[А-Яа-я]+(?![A-Za-zА-Яа-я])", s))
                lat.update(w.lower() for w in re.findall(
                    r"(?<![A-Za-zА-Яа-я\-])[A-Za-z]{4,}(?![A-Za-zА-Яа-я\-])", s))
    except Exception as e:
        print(f"[ai] речник от историята недостъпен ({type(e).__name__}: {e}) — "
              "проверките за слепени думи и латиница вместо кирилица са изключени")
        return {}, {}
    return dict(cyr), dict(lat)


def _fix_glued(s: str) -> str:
    """
    Латиница ≥4 + кирилица ≥5, слепени без интервал, където кирилската част е
    самостоятелна дума ≥3 пъти в историята → интервал. Цялата история (32 321
    низа, 101 хибрида): точно 2 разделяния, и двете правилни — "longпозиция",
    "Healthcareгенерира" (30.09). "benefitват"/"dedikирани" не се пипат —
    кирилската част е наставка, не дума.
    """
    cyr = _bg_vocab()[0]
    if not cyr:
        return s
    def repl(m):
        if cyr.get(m.group(2), 0) < 3:
            return m.group(0)
        fixed = f"{m.group(1)} {m.group(2)}"
        print(f"[ai] слепени думи разделени: '{m.group(0)}' → '{fixed}'")
        return fixed
    return _GLUED_RE.sub(repl, s)


def _latin_as_bg(w: str) -> str | None:
    """
    "Kakao" (Cocoa 30.09): латинска дума, невиждана досега в историята, чиято
    кирилска транслитерация е дума от корпуса. Само лог: върху историята 27
    сигнала, 17 истински (negativen, bufer, rotira, globalno, kakao…), 10
    английски думи/имена (Africa, region, Panama Canal, model…).
    """
    cyr, lat = _bg_vocab()
    lw = w.lower()
    if not cyr or lat.get(lw, 0) > 0:
        return None
    out, i = "", 0
    while i < len(lw):
        for a, b in _BG_TRANSLIT:
            if lw.startswith(a, i):
                out += b; i += len(a); break
        else:
            return None
    return out if cyr.get(out, 0) >= 2 else None


SYSTEM_MACRO = """Ти си макро аналитик, който пише за опитен суинг търговец \
(8+ години, познава Weinstein, CANSLIM, GMMA, RS Line, GLB). Системата е \
оперативна, не образователна — без дефиниции на базови понятия, без hedging \
фрази. Пишеш на български, тикерите и техническите термини остават на английски. \
Връщаш САМО валиден JSON, без markdown огради, без преамбюл."""


def _macro_brief_fallback(thermometer: dict) -> dict:
    """
    Ниво 2 (FIX 2026-08-17) — минимален fallback, ако и Ниво 0 (json_repair),
    и Ниво 1 (smart retry) се провалят. Суровите данни (термометър режим) без
    AI наратив, explicit label в самия macro_brief текст (директно видим в
    dashboard-ната "Макро бриф" секция, без нужда от template промяна) — за
    да продължи останалата част от брифа (screening, sizing, render) напълно
    нормално, вместо целият pipeline да се събори заради един AI hiccup.
    """
    regime = thermometer.get("regime", "?")
    return {
        "macro_brief": ("⚠ AI синтез неуспешен днес — Claude върна невалиден JSON "
                        "и след автоматична поправка, и след retry. Показваме "
                        "суровите данни от термометъра/скрийнъра без AI наратив."),
        "sector_logic": [],
        "regime_comment": f"Режим: {regime} — виж пазарния термометър по-горе за пълните индикатори.",
        "ai_synthesis_failed": True,
    }


def _core_inflation_block(macro: dict) -> str:
    """
    FIX 2026-09-27: основната инфлация като котва — отделен блок, НЕ само в
    macro JSON-а (той се реже на 6000 знака и полето може да отпадне).
    Изключен модул (None) → празен низ, промптът е като досега.
    """
    ci = macro.get("core_inflation")
    if ci is None:
        return ""
    return f"""
ОСНОВНА ИНФЛАЦИЯ — котва (Dallas Fed Trimmed Mean PCE, 12 месеца, % г/г; \
месечна серия с ~1 месец закъснение, НЕ днешни данни; информативна, НЕ е част \
от термометъра и НЕ влияе на режима): {json.dumps(ci, ensure_ascii=False, default=str)}

ВАЖНО за инфлацията: всяко твърдение за "инфлационен натиск" (засилващ се, \
отслабващ, упорит) сверявай с тази стойност и полето "direction" — посоката е \
изчислена от кода като средно за последните 3 месеца ("avg_recent") срещу \
предходните 3 ("avg_prior"). Ако "direction" е "flat" — основната инфлация е \
СТАБИЛНА: НЕ пиши, че "пада", "расте", "продължава да пада" или "се ускорява", \
и не сравнявай единични месеци, за да изведеш посока. Посока твърди само при \
"up"/"down". Ако пазарни сигнали (петрол, доходности, злато) внушават натиск, \
а основната инфлация не расте — кажи го изрично като разминаване, не го \
представяй като потвърден натиск. Цитирай стойността точно и за кой месец е. \
Ако "value" е null — не прави твърдения за нивото или посоката на основната \
инфлация.
"""


def macro_and_sector_brief(macro: dict, rotation: list[dict],
                           thermometer: dict) -> dict:
    """
    Връща:
    {
      "macro_brief": "4-6 изречения какво се случи и какво значи",
      "sector_logic": [
        {"sector": ..., "etf": ..., "chain": "конкретната верижна логика",
         "horizon_weeks": "2-6"}
      ],
      "regime_comment": "1-2 изречения коментар към режима"
    }

    FIX 2026-08-17 (production crash — json.decoder.JSONDecodeError необхванат
    чак до run(), сборил целия pipeline): 3 нива защита, в ред на разходна
    ефективност — Ниво 0 (json_repair, вътре в _parse_json(), нулева цена),
    Ниво 1 (тук долу — smart retry: подаваме malformed отговора обратно на
    Claude с explicit инструкция да го поправи, ЕДНА допълнителна AI заявка),
    Ниво 2 (_macro_brief_fallback() — суровите данни без AI наратив, graceful,
    никога не позволяваме на изключението да стигне до run()).
    """
    user = f"""Днешни данни:

ТЕРМОМЕТЪР: {json.dumps(thermometer, ensure_ascii=False, default=str)}

МАКРО (FRED + пазарни сигнали): {json.dumps(macro, ensure_ascii=False, default=str)[:6000]}

СЕКТОРНА РОТАЦИЯ (RS vs SPY): {json.dumps(rotation, ensure_ascii=False, default=str)}

ВАЖНО за числа в текста: когато цитираш конкретна стойност от данните по-горе \
(проценти, percentile, нива, delta-и) в prose текста — копирай Я ТОЧНО както е \
в JSON-а, никога не я преизчислявай или приблизителствай наум. Специфично за \
percentile полета (напр. IEI/HYG "level_percentile"/"roc_percentile") — те са \
прецизни изчислени стойности, не грубa оценка; върни числото директно от полето, \
не генерирай "правдоподобно звучащо" число от паметта си (потвърден случай \
2026-08-26: level_percentile=0.2 цитирано в текста като "20-ти percentile").

ВАЖНО за условия за смяна на режима: ако пишеш какво би отменило или сменило \
режима, цитирай САМО полето "exit_rule" от термометъра по-горе (и "overrides" / \
"regime_by_count", ако ти трябват детайли). НЕ формулирай собствени прагове, \
нива или дати, които не са там. Потвърден случай 2026-09-25: текстът твърдеше \
"единственото, което би отменило Defensive, е MOVE под 85" — 85 не е праг никъде \
в системата, а реалното условие дори не изисква MOVE да падне, само да спре да \
расте. Ако exit_rule не казва нещо, ти също не го казвай.

ВАЖНО за единиците на MOVE: "delta_1w" в термометъра и прагът за override са в \
ПУНКТОВЕ на индекса (напр. "+15.4 пункта"), НЕ в проценти. Процентната промяна \
е отделно поле — "chg_5d_pct" в МАКРО global_signals.MOVE. Пиши винаги с единица \
("пункта" или "%") и никога не слагай % на delta_1w. Потвърден случай 28.09.2026: \
делтата +15.4 пункта беше цитирана като "+15.4%" (реалната % промяна беше +19.05%).
{_core_inflation_block(macro)}
Задачи:
1. "macro_brief": 4-6 изречения — какво се случи в света и какво означава за \
днешната сесия. Конкретика, не общи приказки.
2. "sector_logic": за топ 3-5 сектора с положителна динамика — пълната верижна \
логика (макро събитие → механизъм → сектор), както изисква спекът: документирай \
веригата, не само заключението. Поле "chain" за всяка.
3. "regime_comment": провери дали режимът {thermometer.get('regime')} е оправдан \
от данните. Ако индикатори липсват, са скрити или съдържат невалидни стойности \
(null/nan), кажи го изрично и оцени как това променя увереността в режима. НЕ \
оправдавай режима на всяка цена — ако данните му противоречат, напиши го директно.

Връщай само JSON с ключове: macro_brief, sector_logic (списък от обекти със \
sector, etf, chain, horizon_weeks), regime_comment."""

    # Ниво 0 (json_repair, вътре в _parse_json) + първи опит. try/except обхваща
    # И _call_claude, И _parse_json — мрежова/API грешка тук е РАВНОСИЛНА на
    # malformed JSON за целите на graceful degradation (и двете трябва да
    # паднат към Ниво 1 retry, не да пробият необхванати до run()).
    raw = None
    error_msg = ""
    try:
        # FIX 2026-09-23: изричен лимит. Дотук извикването нямаше max_tokens и
        # падаше на default-а 4000 — най-стегнатият бюджет в целия pipeline,
        # при най-големия единичен изход. Виж config.MACRO_MAX_TOKENS.
        raw = _call_claude(SYSTEM_MACRO, user, max_tokens=config.MACRO_MAX_TOKENS)
        return _parse_json(raw)
    except TruncatedResponse as e:
        # FIX 2026-09-23: retry при същия лимит отрязва пак, на двойна цена —
        # направо към Ниво 2 (суровите данни), предупреждението е вече записано.
        print(f"[ai] macro brief: отрязан ({e}) — без retry, Ниво 2 fallback")
        return _macro_brief_fallback(thermometer)
    except Exception as e:
        # ВАЖНО: Python автоматично прави `del e` на изхода от except блока
        # ("as e" гърми UnboundLocalError, ако се ползва по-долу извън него —
        # реален бъг, хванат от изолираните тестове преди push, 2026-08-17).
        # Затова съобщението се копира в отделна променлива ТУК, преди изхода.
        error_msg = f"{type(e).__name__}: {e}"
        print(f"[ai] macro brief: първи опит неуспешен ({error_msg}) "
              f"— пробвам Ниво 1 (retry с explicit поправка)")

    try:
        fix_turns = [
            {"role": "assistant", "content": raw or "(без отговор — предходната заявка се провали изцяло)"},
            {"role": "user", "content": (
                f"Предишният ти отговор имаше JSON синтактична грешка: {error_msg}. "
                f"Върни ЦЕЛИЯ отговор наново — само валиден JSON, без markdown "
                f"огради, без обяснения извън JSON структурата.")},
        ]
        raw_retry = _call_claude(SYSTEM_MACRO, user, extra_messages=fix_turns,
                                 max_tokens=config.MACRO_MAX_TOKENS)
        return _parse_json(raw_retry)
    except Exception as e2:
        print(f"[ai] macro brief: Ниво 1 retry също неуспешен "
              f"({type(e2).__name__}: {e2}) — Ниво 2 fallback (суровите данни, без AI наратив)")
        return _macro_brief_fallback(thermometer)


SYSTEM_TICKERS = """Ти си портфолио стратег за суинг търговия. Потребителят е \
опитен (Weinstein Stage Analysis, CANSLIM, O'Neil bases, RS Line). Пишеш на \
български, тикери и термини на английски. Бъди директен — ако setup-ът е слаб, \
кажи го. Връщаш САМО валиден JSON."""


def _load_prior_watchlist_triggers(today: str | None = None) -> dict[str, str]:
    """
    FIX 2026-08-02 (точка 4 follow-up — cross-day watchlist_trigger честност):
    чете watchlist_trigger текста от НАЙ-СКОРОШНИЯ ПРЕДИШЕН data/YYYY-MM-DD.json
    snapshot и го подава като контекст на днешния AI промпт. Soft механизъм,
    mirroring prior_context в cot_theses() (виж по-долу в модула) — само cross-day
    вместо cross-batch. Потвърдено 5/5 проверени случая при прегледа на точка 4
    (2026-08-02): LLY, IRM, HWM, ROST, WWD — AI-то дава конкретен, измерим
    watchlist_trigger, после на следващия ден промотира тикъра в Action без нито
    едно от условията да е реално изпълнено, без обяснение защо (напр. LLY: trigger
    изискваше затваряне >$1249.45 + обем ≥1.3x + RS new_high; на деня на промоция
    цената беше $1216.95, обемът 0.62x, RS остана near_high — нищо от трите).

    ВАЖНО РАЗГРАНИЧЕНИЕ: този fix прави AI-то ЧЕСТНО за случая (обяснява
    противоречието, вместо мълчаливо да го подмине) — НЕ предотвратява
    преждевременен вход. Structural защита срещу лош entry timing е задача на
    бъдещ отделен Entry Timing модул (code-enforced праг, независим от AI текст,
    mirroring как in_blackout вече force-ва Watchlist класификация независимо от
    AI мнение — виж merge_narratives). Двете остават отделни, допълващи се слоеве
    на same проблем: тук подобряваме прозрачността на разказа; бъдещият модул би
    бил истинската защита срещу самия ранен вход.

    Graceful: липсващ/нечетим/липсващ предишен snapshot → празен dict, промптът
    просто няма prior-trigger секция, не чупи pipeline-а.
    """
    try:
        today = today or dt.date.today().isoformat()
        snaps = sorted(p for p in config.DATA_DIR.glob("*.json")
                       if backtest._SNAPSHOT_RE.match(p.name) and p.stem < today)
        if not snaps:
            return {}
        prior = json.loads(snaps[-1].read_text(encoding="utf-8"))
        out = {}
        for c in prior.get("watchlist", []):
            ticker = c.get("ticker")
            trigger = (c.get("ai") or {}).get("watchlist_trigger")
            if ticker and trigger and trigger != "Изчаква потвърждение.":
                out[ticker] = trigger
        return out
    except Exception as e:
        print(f"[ai] prior watchlist triggers зареждане неуспешно: {e}")
        return {}


def _build_ticker_user_prompt(slim: list[dict], sector_logic: list[dict],
                              regime: str, prior_triggers: dict[str, str] | None = None) -> str:
    """
    Изгражда user prompt-а за един batch кандидати. Логиката е идентична на
    оригинала — само `slim` тук е подмножество (batch), не целият списък.
    Глобалните Action лимити (MAX_ACTION_TICKERS / MAX_PER_SECTOR) остават в
    prompt-а непроменени; реалното им налагане е в main.apply_hard_rules СЛЕД
    merge, така че batch-ването не нарушава глобалния cap (кодът има последната дума).

    prior_triggers: FIX 2026-08-02 (виж _load_prior_watchlist_triggers) — вчерашни
    watchlist_trigger текстове, филтрирани само до тикърите в ТОЗИ batch.
    """
    batch_triggers = {c["ticker"]: prior_triggers[c["ticker"]]
                      for c in slim
                      if prior_triggers and c.get("ticker") in prior_triggers}
    trigger_block = (
        f"""

ВЧЕРАШНИ WATCHLIST TRIGGER-И ЗА ТЕЗИ ТИКЪРИ (за консистентност):
{json.dumps(batch_triggers, ensure_ascii=False, default=str)}

За тикър от списъка по-горе: провери дали вчерашният trigger (цена/обем/RS \
условие) реално се е изпълнил, преди да го класифицираш като Action. Ако го \
промотираш въпреки НЕизпълнено условие, обясни изрично в "why_now" защо \
(нов катализатор, ревизирани фундаментали, друга основателна причина) — не \
просто мълчаливо да го игнорираш."""
        if batch_triggers else ""
    )
    return f"""Пазарен режим: {regime}
Активна секторна логика: {json.dumps(sector_logic, ensure_ascii=False, default=str)}

КАНДИДАТИ: {json.dumps(slim, ensure_ascii=False, default=str)}
{trigger_block}

За ВСЕКИ кандидат върни обект:
- "ticker"
- "why_now": конкретната верига макро → сектор → тази акция. Ако няма реална \
макро връзка, кажи че setup-ът е чисто технически.
- "business_bg": какво прави компанията, 2-3 изречения на български.
- "catalysts": списък от 2-4 катализатора в следващите 4-8 седмици.
- "risks": списък от 2-4 конкретни риска — какво обръща trade-а.
- "earnings_call": "преди earnings" / "след earnings" / "не сега" + защо (1 изр.).
- "classification": "Action" или "Watchlist". Watchlist ако: в earnings blackout, \
без обем при пробив и още под pivot, RS слабее, или секторът противоречи на режима.
- "watchlist_reason_type": ако Watchlist — категория на причината: "regime_gate" \
(чака конкретна промяна в пазарния режим ЗАЕДНО с цена/обем условие), \
"earnings_blackout" (в earnings прозорец), "other" (RS/обем/друга техническа причина, \
без regime зависимост). НЕ пиши "existing_position" — това полето се override-ва от \
кода за вече отворени позиции, не е твоя преценка.
- "watchlist_trigger": ако Watchlist — какво точно трябва да се случи (цена/обем/regime \
промяна). НЕ споменавай конкретна КАЛЕНДАРНА дата на изтичане на тезата — това вече се \
управлява детерминистично от кода (виж watchlist_reason_type="regime_gate"), не от теб.

Правила: максимум {config.MAX_ACTION_TICKERS} Action общо — избери най-силните. \
Максимум {config.MAX_PER_SECTOR} Action от един сектор. Earnings в рамките на 5 \
работни дни (0 ≤ days_to_earnings ≤ 7) = автоматично Watchlist (или Action с \
изрично предупреждение само при изключителен setup, поле "warning"). \
days_to_earnings=0 означава earnings Е ДНЕС — пиши го изрично така, НЕ като \
"неизвестна дата". Само ако days_to_earnings ЛИПСВА (null) или е ОТРИЦАТЕЛЕН, \
датата е неизвестна/невалидна — напиши "earnings дата неизвестна" и НЕ твърди, \
че няма blackout риск.

Връщай само JSON: {{"tickers": [...]}}"""


def _narratives_for_batch(slim: list[dict], sector_logic: list[dict],
                          regime: str, tag: str,
                          prior_triggers: dict[str, str] | None = None) -> list[dict]:
    """
    Един batch → едно Claude извикване → парснат JSON. 1 retry при API/JSON грешка
    (преходни сривове). При провал и на двата опита: логва и връща [] (губим само
    тикърите от ТОЗИ batch), без да чупи останалите batch-ове или pipeline-а.
    """
    user = _build_ticker_user_prompt(slim, sector_logic, regime, prior_triggers)
    for attempt in (1, 2):  # 1 опит + 1 retry
        try:
            out = _parse_json(_call_claude(SYSTEM_TICKERS, user,
                                           max_tokens=config.AI_BATCH_MAX_TOKENS))
            return out.get("tickers", [])
        except TruncatedResponse:
            break  # FIX 2026-09-23: retry при същия лимит отрязва пак, на двойна цена
        except Exception as e:
            label = "опит" if attempt == 1 else "retry"
            print(f"[ai] ticker batch {tag} {label} неуспешен: {type(e).__name__}: {e}")
    print(f"[ai] ticker batch {tag} пропуснат след 2 опита — "
          f"губим {len(slim)} тикъра: {[c.get('ticker') for c in slim]}")
    return []


def ticker_narratives(candidates: list[dict], sector_logic: list[dict],
                      regime: str) -> list[dict]:
    """
    За всеки кандидат Claude връща:
    why_now (верижна логика макро→сектор→акция), business_bg (2-3 изречения),
    catalysts (4-8 седмици), risks, earnings_call (преди/след/не сега),
    classification (Action/Watchlist) + watchlist_trigger ако е Watchlist.

    Извикванията са на batch-ове по config.AI_BATCH_SIZE тикъра — отделно API
    извикване + отделно JSON парсване на batch, после обединяване. Така token
    budget-ът е достатъчен независимо от броя финалисти (9, 14 или 50), и един
    провален batch не сваля останалите (graceful degradation на batch ниво).
    """
    slim = []
    for c in candidates:
        slim.append({k: c.get(k) for k in (
            "ticker", "company", "sector", "industry", "business_summary",
            "price", "pivot", "pct_from_pivot", "base_type", "base_depth_pct",
            "rs_status", "volume_ratio", "breakout_volume",
            "eps_growth_yoy", "revenue_growth_yoy", "roe", "pe", "forward_pe",
            "inst_ownership_pct", "analyst_target")})
        slim[-1]["earnings"] = c.get("earnings")
        slim[-1]["short"] = c.get("short_view", {}).get("interpretation")
        slim[-1]["options"] = {k: c.get("options", {}).get(k)
                               for k in ("iv", "iv_rank", "strategy")}

    if not slim:
        return []

    size = max(1, config.AI_BATCH_SIZE)
    batches = [slim[i:i + size] for i in range(0, len(slim), size)]
    n = len(batches)
    print(f"[ai] ticker_narratives: {len(slim)} финалиста → {n} batch(ове) "
          f"по ≤{size} (max_tokens={config.AI_BATCH_MAX_TOKENS}/batch)")

    # FIX 2026-08-02 (точка 4 follow-up): вчерашни watchlist_trigger текстове,
    # заредени веднъж за целия run — виж _load_prior_watchlist_triggers.
    prior_triggers = _load_prior_watchlist_triggers()

    merged: list[dict] = []
    for idx, batch in enumerate(batches, 1):
        merged += _narratives_for_batch(batch, sector_logic, regime, f"{idx}/{n}", prior_triggers)
    return merged


def merge_narratives(candidates: list[dict], narratives: list[dict]) -> list[dict]:
    by_ticker = {n["ticker"]: n for n in narratives}
    for c in candidates:
        c["ai"] = by_ticker.get(c["ticker"], {})
        # Твърдите правила бият AI преценката (Секция 8):
        if c.get("earnings", {}).get("in_blackout") and not c["ai"].get("warning"):
            c["ai"]["classification"] = "Watchlist"
            c["ai"]["watchlist_reason_type"] = "earnings_blackout"
            c["ai"].setdefault("watchlist_trigger",
                               f"След earnings на {c['earnings'].get('next_earnings')}")
        _check_price_mentions(c.get("ticker", "?"), c["ai"].get("why_now") or "", c.get("price"))
    return candidates


# FIX 2026-10-02 (т.3 от прегледа на 01.10): batch-ов cross-contamination —
# AVT защо_сега (01.10) цитира "Текущата цена $210.08", реалната AVT цена е
# $99.95; $210.08 е точната реална цена на NTAP, друг тикър в СЪЩИЯ batch.
# Пост-хок, САМО лог (не пипа текста — рисковано е сляпо find/replace, защото
# цена в текста може легитимно да е pivot/stop/target, не "текуща цена").
#
# Измерено върху цялата история (data/20*.json, 633 карти с why_now и price):
# 7/633 флагнати с наивна "цена...$X в 30-символен прозорец"; след изключване
# на pivot/stop/target/цел/под/над (с \b, за да не хване "надминава") остават
# 3/633 — AVT/NTAP (потвърден бъг), и две гранични "текуща цена $X" фрази,
# които реално описват друг референтен праг (delta/breakout ниво), не днешната
# цена. 3/633 ≈ 0.5% е приемлив шум за чисто диагностичен лог.
_PRICE_WORD_RE = re.compile(r"цена(?:та)?", re.I)
_PRICE_EXCLUDE_RE = re.compile(r"pivot|stop|target|цел|\bпод\b|\bнад\b", re.I)
_DOLLAR_AMOUNT_RE = re.compile(r"\$([\d,]+\.?\d*)")


def _check_price_mentions(ticker: str, text: str, real_price: float | None,
                          tolerance_pct: float = 2.0) -> None:
    """Лог (не промяна) при '...цена... $X' в текст, разминаващо се с real_price с >tolerance_pct%."""
    if not text or not real_price:
        return
    for pm in _PRICE_WORD_RE.finditer(text):
        before_word = text[max(0, pm.start() - 15):pm.start()]
        window = text[pm.end():pm.end() + 30]
        dm = _DOLLAR_AMOUNT_RE.search(window)
        if not dm:
            continue
        if (_PRICE_EXCLUDE_RE.search(before_word) or _PRICE_EXCLUDE_RE.search(window[:dm.start()])
                or _PRICE_EXCLUDE_RE.search(window[dm.end():dm.end() + 15])):
            continue  # pivot/stop/target/под/над наблизо (преди или след) — друг референтен праг, не текуща цена
        try:
            mentioned = float(dm.group(1).replace(",", ""))
        except ValueError:
            continue
        if mentioned <= 0 or abs(mentioned - real_price) / real_price * 100 <= tolerance_pct:
            continue
        ctx = text[max(0, pm.start() - 15):pm.end() + 30]
        print(f"[ai] ⚠ защо_сега цена разминаване за {ticker}: текстът споменава ${mentioned:.2f}, "
              f"реалната цена е ${real_price:.2f} ({(mentioned / real_price - 1) * 100:+.1f}%) — «…{ctx}…»")


# ══════════════════════════════════════════════════════════════════════════
# COT (Commitments of Traders) — Секция [нова] — Шапиро тези
# ══════════════════════════════════════════════════════════════════════════

SYSTEM_THESIS_CHECK = """Ти си скептичен редактор-факт-чекър. Задачата ти НЕ е \
да намираш връзки, а да намираш ПРОТИВОРЕЧИЯ между дълготрайна теза и това, \
което вече се е случило. По подразбиране отговорът е "unchanged" — отклоняваш \
се от него само при конкретна новина, която материално разрешава или \
опровергава механизма. Пишеш на български, тикери и термини на английски. \
Връщаш САМО валиден JSON, без markdown огради, без преамбюл."""


# FIX 2026-09-30: дневна диагностика на проверката — приети и отхвърлени
# маркирания с правилото (G0–G3) и причината, по модела на COT_DIAG → брифа.
THESIS_CHECK_DIAG: dict = {}
_NEWS_EVENT_TYPES = {"contract", "order", "budget", "legislation", "policy",
                     "macro_data", "price_move", "topic"}


_ARROWS = ("->", "=>", "⟶", "➔", "➜", "⇒")


def _norm_quote(s) -> str:
    """
    FIX 2026-09-30: и двете страни за G3 — моделът цитира почти дословно
    (други кавички, "->" вместо "→", тирета, главни букви, двойни интервали).
    Малки букви, стрелките уеднаквени до "→", кавички/тирета/скоби/пунктуация
    → интервал, един интервал.
    """
    s = str(s or "").lower()
    for a in _ARROWS:
        s = s.replace(a, "→")
    s = re.sub(r"[^\w\s→]", " ", s)
    s = re.sub(r"\s*→\s*", " → ", s)
    return re.sub(r"\s+", " ", s).strip()


def _news_gate(thesis: dict, c: dict, status: str) -> tuple[str | None, str]:
    """
    FIX 2026-09-30: кодови проверки за confirmed/challenged. Първия ден на
    "confirmed" (30.09) 3 от 6 тези бяха "потвърдени" и 1 "опровергана" —
    промптът вече казваше "в типичен ден всички са unchanged". Същият подход
    като COT Release 2: моделът попълва структурни полета, кодът ги проверява.
    Връща (правило, причина) при отказ или (None, "") при приемане.

      G0 — схемата: basis липсва/невалиден.
      G1 — event_type е ценово движение / новина по темата (или невалиден).
      G2 — affected_tickers не са непразно подмножество на тикърите на тезата,
           effect не съвпада със статуса, или при ticker_event subject_ticker
           е ИЗВЪН тезата (Boeing срещу NOC, 30.09; DeepSeek/Huawei/Nvidia).
      G3 — chain_step: chain_quote не е дословно от chain, или тезата има
           макро тригер (config.THESIS_BASKETS "trigger"), който НЕ е сработил
           (status != "active") — кодът вече мери тази стъпка и казва, че не
           се е случила (въглища 30.09 "потвърдена" при несработил oil_shock;
           23 и 24.09 "опровергана" на теза, която и без това не е активна).
           Тези без тригер (ядрена, крипто/CLARITY, полупроводници) минават
           само проверката на цитата.
    """
    basis = c.get("basis")
    if basis not in ("ticker_event", "chain_step"):
        return "G0", f"basis липсва или е невалиден ({basis!r})"
    ev = c.get("event_type")
    if ev not in _NEWS_EVENT_TYPES:
        return "G1", f"event_type липсва или е невалиден ({ev!r})"
    if ev in ("price_move", "topic"):
        return "G1", f"event_type='{ev}' — ценово движение/новина по темата не е {status}"

    tickers = {str(x).upper() for x in (thesis.get("tickers") or [])}
    affected = [str(x).upper() for x in (c.get("affected_tickers") or [])
                if isinstance(x, str) and x.strip()]
    want = "positive" if status == "confirmed" else "negative"
    if not affected:
        return "G2", "affected_tickers е празен"
    outside = [x for x in affected if x not in tickers]
    if outside:
        return "G2", f"affected_tickers извън тезата: {outside}"
    if c.get("effect") != want:
        return "G2", f"effect={c.get('effect')!r}, а {status} изисква '{want}'"
    if basis == "ticker_event":
        subj = str(c.get("subject_ticker") or "").upper()
        if subj not in tickers:
            return "G2", (f"събитието е за {subj or '(не е посочено)'}, а то не е "
                          f"в тезата {sorted(tickers)}")
        return None, ""

    q = _norm_quote(c.get("chain_quote"))
    if len(q) < 12 or q not in _norm_quote(thesis.get("chain")):
        return "G3", f"chain_quote не е дословно от веригата ({c.get('chain_quote')!r})"
    trigger = next((b.get("trigger") for b in config.THESIS_BASKETS
                    if b.get("name") == thesis.get("name")), None)
    if trigger and thesis.get("status") != "active":
        return "G3", (f"макро тригерът '{trigger}' не е сработил (статус "
                      f"'{thesis.get('status')}') — стъпката от веригата не се е случила "
                      f"по собственото ни мерене")
    return None, ""


def thesis_reality_check(theses: list[dict], news: list[dict]) -> list[dict]:
    """
    FIX 2026-09-16: свереност на геополитическите тези срещу днешните новини.

    Потвърденият случай: Senate cloture гласуването за CLARITY Act се провали
    на 15.09.2026 (49-50, под 60-гласовия праг). Брифът на 16.09 продължи да
    показва "Ясна законодателна рамка (CLARITY Act) → институциите получават
    регулаторна сигурност → ...", без нито дума, че гласуването вече се е
    случило и е паднало. Не е неточност — активно подвеждащ текст.

    Защо изобщо е нужна НОВА стъпка: thesis_monitor() е чист код + статичен
    конфиг (config.THESIS_BASKETS). `chain` е hardcoded низ, `status` идва от
    _trigger_fires() върху макро серии. AI-то никога не е виждало тези тези —
    нямаше промпт, към който да се добави инструкция.

    Съзнателно САМО анотация. Не пипа `status` (остава trigger-driven), не
    пипа `chain` (остава конфиг), не изисква нищо от trigger дизайна. Новата
    информация седи ДО тезата, не я замества — "кодът има последната дума"
    остава непокътнат, а промяната е напълно адитивна и обратима. Пълният
    Layer 3 redesign (структуриран trigger за насрочени binary събития) е
    отделна тема, съзнателно извън обхвата тук.

    Предпоставка: config.NEWS_PER_SOURCE_LIMIT / NEWS_MAX_TO_FILTER. Преди тях
    проверката би била инертна — заглавието за провала стоеше на ранг 17 при
    limit=15 и изобщо не влизаше в събраното (виж config.py измерванията).

    Добавя "news_status" (challenged|resolved|evolving|confirmed|unchanged) и "news_note" към
    всяка теза. Graceful: провал навсякъде тук → връща theses непроменени.
    """
    THESIS_CHECK_DIAG.clear()
    if not theses or not news:
        return theses
    try:
        compact_theses = [{"name": t.get("name"), "chain": t.get("chain"),
                           "tickers": t.get("tickers")} for t in theses]
        # FIX 2026-09-18: приема И двете форми — филтрираните новини
        # ({headline, why}) и суровия пул от news_aggregator.raw_pool()
        # ({source, title, summary}). Суровият е реалният вход след тази
        # промяна, но подписът остава съвместим с филтрирания списък.
        compact_news = [
            {"headline": n.get("headline") or n.get("title"),
             "why": n.get("why") or (n.get("summary") or "")[:200]}
            for n in news if (n.get("headline") or n.get("title"))
        ]
        if not compact_news:
            return theses
        user = f"""ТЕЗИ (дълготрайни, от конфигурация — механизмът е описан в "chain"):
{json.dumps(compact_theses, ensure_ascii=False, default=str)}

ДНЕШНИ НОВИНИ:
{json.dumps(compact_news, ensure_ascii=False, default=str)}

За всяка теза прецени дали КОНКРЕТНА днешна новина материално променя \
механизма, описан в "chain":

- "challenged" — новина опровергава, блокира или проваля механизма. Пример: \
теза "законодателна рамка X → регулаторна сигурност → приток на капитал", а \
новина съобщава, че гласуването за X се е провалило. Механизмът не просто \
още не се е случил — конкретно събитие го е спряло. САМО ако новината \
блокира механизма ЗА ТИКЪРИТЕ НА ТЕЗАТА, не за съседна компания. Потвърден \
случай 30.09.2026: "DeepSeek partners with Huawei … reducing reliance on \
Nvidia" беше маркирано като опровержение на теза с AVGO/AMAT/MCHP \
(оборудване и mature-node чипове) — Nvidia не е в тезата и механизмът за \
тези тикъри не е блокиран. Ценово движение (петролът пада) не е challenged.
- "resolved" — механизмът е ИЗЦЯЛО приключил и тезата вече няма какво да \
предложи занапред (напр. законът е приет и в сила, събитието е минало и \
ефектът е изчерпан). Едно потвърждаващо събитие по пътя НЕ е resolved — то е \
"confirmed".
- "confirmed" — конкретно днешно събитие показва, че механизмът от "chain" \
работи както е описан: стъпка от веригата се е случила (напр. договор, \
поръчка, бюджетно решение, законодателна стъпка напред), а тезата остава в \
сила занапред. Потвърден случай 29.09.2026: договор за $20.7 млрд за RTX беше \
маркиран "resolved", а е потвърждение на тезата за отбраната, не неин край. \
Новина само по темата или ценово движение НЕ е confirmed. "confirmed" САМО ако: \
(а) събитието засяга ПРЯКО и ПОЛОЖИТЕЛНО компания от "tickers" на тезата \
(договор, поръчка, бюджет за НЕЯ), или (б) е конкретна макро стъпка, дословно \
описана в "chain" (напр. дългият край на кривата расте при теза за стръмна \
крива). НИКОГА, когато компания ИЗВЪН тезата печели нещо, за което се е \
състезавала компания от тезата — за компанията от тезата това е ЗАГУБА. \
Потвърден случай 30.09.2026: "Boeing wins US Navy's next-generation fighter \
contract" беше маркирано като потвърждение на тезата за отбраната, а Boeing \
не е в тезата и е спечелил срещу Northrop Grumman (NOC), който е в нея. \
Еднодневно ценово движение (петролът поскъпна днес) НИКОГА не е confirmed.
- "evolving" — назованото в тезата СРЕДСТВО е спряно/забавено, но конкретен \
АЛТЕРНАТИВЕН път напредва към СЪЩАТА крайна цел. Използвай го САМО когато \
можеш да назовеш и ДВЕТЕ страни поименно: (1) кой точно оригинален път се е \
провалил или забавил, и (2) кой точно алтернативен път напредва вместо него. \
Ако можеш да посочиш само едното, това не е "evolving" — то е "challenged" \
(ако само оригиналът е спрян) или "unchanged" (ако само има някаква свързана \
новина). Пример за ВАЛИДНО evolving: теза "законодателна рамка X → регулаторна \
сигурност"; гласуването за X се проваля, НО регулаторът подава собствени \
правила към същата цел — оригиналът е спрян, алтернативата е конкретна и \
назована. Пример за НЕВАЛИДНО: "регулаторната среда изглежда по-благоприятна" \
— няма назован провалил се път, няма назована алтернатива, това е unchanged.
- "unchanged" — ВСИЧКО ОСТАНАЛО. Това е отговорът по подразбиране.

КРИТИЧНО — кога НЕ се отклоняваш от "unchanged":
- новината е по същата обща тема, но не казва нищо за механизма \
(теза за ядрена енергия + новина "петролът пада" → unchanged);
- новината движи цените на тикърите от тезата, но не пипа механизма \
(акциите паднали днес → unchanged, това е шум, не разрешаване);
- новината е свързана само косвено, през 2+ стъпки макро верига → unchanged;
- не си сигурен → unchanged.

Тезите са дълготрайни по замисъл. В типичен ден ВСИЧКИ са "unchanged" — това \
е нормалният, очакван резултат, не пропуск от твоя страна. Не търси връзки.

"note": САМО при challenged/resolved/evolving/confirmed — едно изречение, което ЦИТИРА \
конкретното заглавие, задействало преценката. При "evolving" бележката трябва \
да назове И ДВАТА пътя: спрения оригинал и конкретната алтернатива. Ако не \
можеш да посочиш точно заглавие (или при evolving — и двата пътя), върни \
"unchanged" с празен note.

При "confirmed" и "challenged" (и САМО при тях — за останалите не ги пиши) \
добави и полета, които кодът проверява; липсващо или невалидно поле → \
маркирането се отхвърля:
- "basis": "ticker_event" (събитието е за конкретна компания) или "chain_step" \
(макро/законодателна стъпка от веригата);
- "subject_ticker": тикърът на компанията, за която е новината (кой печели \
договора, кой е обект на решението) — или null при chain_step;
- "affected_tickers": тикъри ОТ "tickers" на тезата, засегнати пряко;
- "effect": "positive" (при confirmed) или "negative" (при challenged) — за \
affected_tickers;
- "chain_quote": при chain_step — ДОСЛОВЕН откъс от "chain" на тезата за \
стъпката, която се е случила или е блокирана; иначе null;
- "event_type": "contract" | "order" | "budget" | "legislation" | "policy" | \
"macro_data" | "price_move" | "topic".

Върни JSON за ВСЯКА теза, в същия ред: \
{{"checks": [{{"name": "...", "news_status": "...", "note": "...", \
"basis": "...", "subject_ticker": "...", "affected_tickers": [...], \
"effect": "...", "chain_quote": "...", "event_type": "..."}}]}} — \
последните шест полета само при confirmed/challenged."""

        out = _parse_json(_call_claude(SYSTEM_THESIS_CHECK, user,
                                       max_tokens=config.THESIS_CHECK_MAX_TOKENS))
        by_name = {c.get("name"): c for c in out.get("checks", [])
                   if isinstance(c, dict)}
        annotated = []
        for t in theses:
            c = by_name.get(t.get("name")) or {}
            status = c.get("news_status")
            # FIX 2026-09-29: + "confirmed" (потвърдена от новина) — същото
            # изискване за цитирано заглавие; "resolved" остава само за край.
            if status not in ("challenged", "resolved", "evolving", "confirmed"):
                annotated.append(t)
                continue
            note = (c.get("note") or "").strip()
            if not note:
                # изрично изискване на промпта — без цитирано заглавие не се
                # отклоняваме от unchanged
                print(f"[ai] thesis_reality_check: '{t.get('name')}' върна "
                      f"{status} без note — игнорирам")
                annotated.append(t)
                continue
            # FIX 2026-09-18: "evolving" е по-мек праг от "challenged" и затова
            # по-лесен за злоупотреба. Промптът изисква бележката да назове И
            # ДВАТА пътя (спрян оригинал + конкретна алтернатива), а това по
            # необходимост е по-дълго от едно изречение с едно твърдение.
            # Едноредова бележка при evolving почти сигурно назовава само едната
            # страна → третира се като неизпълнено изискване. Кодът не може да
            # провери семантиката, но може да провери, че изобщо е даден
            # достатъчно материал — същият дух като note-задължителността.
            if status == "evolving" and len(note) < config.THESIS_EVOLVING_MIN_NOTE_CHARS:
                print(f"[ai] thesis_reality_check: '{t.get('name')}' върна evolving "
                      f"с твърде кратка бележка ({len(note)} знака) — вероятно не "
                      "назовава и двата пътя, игнорирам")
                annotated.append(t)
                continue
            # FIX 2026-09-30: G1–G3 — виж _news_gate(). Само confirmed/challenged.
            if status in ("confirmed", "challenged"):
                rule, why = _news_gate(t, c, status)
                if rule:
                    print(f"[ai] thesis_reality_check: '{t.get('name')}' {status} "
                          f"ОТХВЪРЛЕНО ({rule}) — {why}")
                    entry = {"thesis": t.get("name"), "status": status, "rule": rule,
                             "reason": why, "note": note}
                    if rule == "G3":  # цитатът на модела — за да се вижда разликата
                        entry["chain_quote"] = c.get("chain_quote")
                        entry["chain_quote_norm"] = _norm_quote(c.get("chain_quote"))
                    THESIS_CHECK_DIAG.setdefault("rejected", []).append(entry)
                    annotated.append(t)
                    continue
            print(f"[ai] thesis_reality_check: '{t.get('name')}' → {status} — {note}")
            THESIS_CHECK_DIAG.setdefault("accepted", []).append(
                {"thesis": t.get("name"), "status": status})
            annotated.append({**t, "news_status": status, "news_note": note})
        # FIX 2026-09-17: успехът трябва да е ВИДИМ в лога. Дотук функцията
        # логваше само при маркиране или при провал — а "всичко unchanged"
        # (нормалният, очакван изход) мълчеше, което го правеше неразличимо
        # от тихо паднало извикване: и в двата случая нито една теза няма
        # news_status. Същото сляпо петно като мъртвите news източници преди
        # FIX 2026-09-15 — успех и провал изглеждаха еднакво отвън.
        flagged = sum(1 for t in annotated if t.get("news_status"))
        rejected = THESIS_CHECK_DIAG.get("rejected", [])
        print(f"[ai] thesis_reality_check: {len(annotated)} тези проверени "
              f"срещу {len(news)} новини — {flagged} маркирани, "
              f"{len(rejected)} отхвърлени от G0–G3"
              + (f" {[(r['thesis'], r['rule']) for r in rejected]}" if rejected else ""))
        return annotated
    except Exception as e:
        print(f"[ai] thesis_reality_check неуспешен: {type(e).__name__}: {e}")
        return theses


SYSTEM_WATCH = """Ти си анализатор, който следи конкретни компании за инвеститор, \
който вече държи позиции в тях. Обясняваш какво се е случило и какво означава \
то — не преразказваш заглавия. Пишеш на български, тикери и термини на \
английски. Директен си: ако събитието е рутинно, го казваш рутинно. Връщаш \
САМО валиден JSON, без markdown огради, без преамбюл."""


def watch_ticker_digest(rows: list[dict], market_context: dict) -> list[dict]:
    """
    AI тълкуване за „🔎 Наблюдавани тикъри" (виж watch_monitor.py).

    rows: изходът на watch_monitor.collect(), БЕЗ тихите тикъри — те не стигат
    дотук изобщо (кодът им слага текста сам, виж main.py).
    market_context: {active_theses, cot_markets, leading_sectors} — вече
    налични в паметта на run-а, не нов източник.

    Insider продажбите се тълкуват по СТРУКТУРНИ сигнали, не по усещане:
    planned_10b5_1 (SEC aff10b5One флагът), pct_of_holdings
    (sharesOwnedFollowingTransaction), длъжност, и клъстер от няколко
    инсайдъра. Кодът дава сигналите, AI-то дава тълкуването — същото
    разделение като _distress_signals() в short_screener.

    Cross-referencing е с изричен default „няма връзка" — същата
    anti-over-flagging дисциплина като thesis_reality_check. Тикър и активна
    тема по една обща дума не е връзка.

    Graceful: провал → празен dict за всеки тикър, секцията показва суровите
    данни без тълкуване.
    """
    if not rows:
        return rows
    try:
        compact = [{
            "ticker": r["ticker"],
            "news": [{"title": n["title"], "publisher": n["publisher"]} for n in r["news"]],
            "insider": [{"code": t["code"], "date": t["date"],
                         "owner": t["owner_name"], "title": t["owner_title"],
                         "value_usd": round(t["value"]),
                         "pct_of_holdings": t["pct_of_holdings"],
                         "planned_10b5_1": t["planned_10b5_1"]} for t in r["insider"]],
            "insider_cluster": r["insider_cluster"],
        } for r in rows]

        user = f"""НАБЛЮДАВАНИ ТИКЪРИ (данни за последните 24 часа):
{json.dumps(compact, ensure_ascii=False, default=str)}

ТЕМИ, АКТИВНИ ДРУГАДЕ В ДНЕШНИЯ БРИФ:
{json.dumps(market_context, ensure_ascii=False, default=str)}

За всеки тикър върни:

- "summary": 1-2 изречения — какво реално се случи. Не преразказвай заглавията \
едно по едно; кажи какво е същественото. Ако новините са само аналитични \
коментари/рейтинги без ново събитие, кажи точно това.

- "insider_read": САМО ако има Form 4 транзакции. Разграничи рутинно от \
тревожно по ДАДЕНИТЕ сигнали, не по усещане:
  • planned_10b5_1 = true → продажбата е по предварително обявен план. Това е \
рутинно по подразбиране — планът е приет месеци по-рано и не носи информация \
за текущото мнение на инсайдъра. Кажи го така.
  • planned_10b5_1 = false → извънпланова. Значима, ако е голяма спрямо \
holdings (виж pct_of_holdings) или идва от CEO/CFO.
  • planned_10b5_1 = null → флагът липсва в подаването (по-стар filing агент). \
Кажи „неизвестно дали е планирана", НЕ предполагай.
  • insider_cluster = true → няколко различни инсайдъра в една посока за \
кратко. Това е най-силният сигнал в набора; кажи го изрично.
  • малък pct_of_holdings при продажба (под ~10%) отслабва тревожността дори \
при голяма абсолютна сума — ликвидност/данъци, не изход от позицията.
  Ако няма транзакции, върни празен низ.

- "cross_reference": САМО ако тикърът е ПРЯКО свързан с тема от списъка \
по-горе — една стъпка, не макро верига. Едно изречение, което казва защо \
темата има отражение върху тази конкретна компания. Обща дума, споделена между \
тикъра и темата, НЕ е връзка. Ако няма пряка връзка, върни ПРАЗЕН низ — това е \
нормалният случай, не пропуск.

Върни JSON: {{"digests": [{{"ticker": "...", "summary": "...", \
"insider_read": "...", "cross_reference": "..."}}]}}"""

        out = _parse_json(_call_claude(SYSTEM_WATCH, user,
                                       max_tokens=config.WATCH_MAX_TOKENS))
        by_ticker = {d.get("ticker"): d for d in out.get("digests", [])
                     if isinstance(d, dict)}
        annotated = []
        for r in rows:
            d = by_ticker.get(r["ticker"]) or {}
            annotated.append({**r, "ai": {
                "summary": (d.get("summary") or "").strip(),
                "insider_read": (d.get("insider_read") or "").strip(),
                "cross_reference": (d.get("cross_reference") or "").strip(),
            }})
        linked = sum(1 for a in annotated if a["ai"]["cross_reference"])
        print(f"[ai] watch_ticker_digest: {len(annotated)} тикъра обработени, "
              f"{linked} с cross-reference")
        return annotated
    except Exception as e:
        print(f"[ai] watch_ticker_digest неуспешен: {type(e).__name__}: {e}")
        return [{**r, "ai": {}} for r in rows]


SYSTEM_COT = """Ти си макро/позициониращ стратег, специализиран в тълкуване на \
CFTC Commitments of Traders данни по методологията на Jason Shapiro: managed \
money (спекулативни/hedge fund) позиции на екстремни percentile нива са \
contrarian сигнал — екстремно нетно дълги = потенциален bearish обрат, \
екстремно нетно къси = потенциален bullish обрат. Пишеш на български, тикери \
и технически термини на английски. Бъди директен и конкретен — не хеджирай. \
Връщаш САМО валиден JSON, без markdown огради, без преамбюл."""


def _looks_like_exchange_code(name: str) -> bool:
    """
    FIX 2026-09-15: yfinance не винаги връща ИМЕ в полетата за име.

    Два потвърдени класа (7 брифа за една седмица):
      • само цифри — вътрешен fund ID вместо име. SUG -> shortName "499402",
        UB -> "308889" (и двата quoteType "MUTUALFUND", longName=None).
        Старият gate беше verified = bool(name), а "499402" е truthy, значи
        тикърът минаваше като напълно валиден и влизаше в брифа с име-число.
        Сигналът "делистнат" от FIX 2026-08-11 (shortName И longName са None)
        също не се задейства — записът съществува, просто няма име.
      • борсов padding — суров ред от изравнена таблица на борсата.
        CSAN3.SA -> shortName "COSAN       ON      NM" (B3 тикър + клас +
        сегмент), докато longName е чистото "Cosan S.A.".

    Само тези два тесни сигнала. ВСИЧКИ главни букви НЕ е сигнал — реални имена
    се връщат така ("ARCA CONTINENTAL SAB DE CV", "GRUPO MEXICO SAB DE CV").
    """
    return bool(name) and (name.isdigit() or "   " in name)


def _best_company_name(short_name: str | None, long_name: str | None) -> str | None:
    """
    Предпочита shortName (кратко, познато име — както досега), но го прескача,
    ако изглежда като борсов код, и пада към longName. Ако ГОДНО име няма от
    нито едното поле, връща None → verified=False → тикърът отпада изцяло
    (_verify_thesis_tickers), вместо да се покаже "SUG (499402)".
    """
    for candidate in ((short_name or "").strip(), (long_name or "").strip()):
        if candidate and not _looks_like_exchange_code(candidate):
            return candidate
    return None


@lru_cache(maxsize=256)
def _verified_company_name(ticker: str) -> dict:
    """
    FIX 2026-08-01: COT proxy тикъри получаваха различно AI-халюцинирано "company"
    име при всяко извикване — напр. "WH" ту "Wyndham Hotels", ту "World Wrestling",
    ту грешно "Westrock Coffee" (реалният WEST тикър е различен, различна компания).
    AI-то вече не се доверява за company полето — верифицираме през yfinance
    (същия shortName/longName паттърн като magic_formula.py/screener.py).

    FIX 2026-08-11: потвърдени случаи (MRO — придобита от ConocoPhillips
    22.11.2024, делистната; HBI — придобита от Gildan 01.12.2025, делистната;
    COTT-фамилията — вероятно предаденствала до PRMW, самата PRMW също се
    оказа "possibly delisted; no price data found" в реалната yfinance
    проверка) — AI-то продължава уверено да предлага такива тикъри в COT
    тезите (training данните му вероятно предхождат сделките), а старият тих
    fallback ("върни ticker символа") показваше "MRO (MRO)" в dashboard-а без
    никакъв сигнал ЗАЩО lookup-ът е паднал. Потвърдено на живо: делистнати
    тикъри системно връщат shortName=None И longName=None от yfinance
    (докато валидни тикъри — AAPL/JPM/GOOGL — винаги ги връщат коректно) —
    надежден, вече-съществуващ сигнал, нулев допълнителен network call.

    Вместо гол string, сега връща {"name": ..., "verified": bool} —
    извикващият код (_verify_thesis_tickers) премахва цели тикъри при
    verified=False, вместо само да показва грозно "TICKER (TICKER)" име.
    lru_cache пести повторни заявки за един и същ тикър в рамките на процеса.
    """
    try:
        info = net_utils.fetch_with_timeout(lambda: yf.Ticker(ticker).info) or {}
        name = _best_company_name(info.get("shortName"), info.get("longName"))
        # quote_type/category/long_name: reuse на СЪЩИЯ fetch за relevance
        # проверката (_is_mismatched_commodity_etf) — нулев допълнителен
        # network call, виж FIX 2026-09-12 по-долу.
        # sector/industry: same reuse, за identity проверката
        # (_identity_mismatch_gloss), виж FIX 2026-09-14.
        return {"name": name or ticker, "verified": bool(name),
               "quote_type": info.get("quoteType"), "category": info.get("category"),
               "long_name": info.get("longName"),
               "sector": info.get("sector"), "industry": info.get("industry")}
    except Exception as e:
        print(f"[ai] company lookup {ticker}: {e}")
        return {"name": ticker, "verified": False,
               "quote_type": None, "category": None, "long_name": None,
               "sector": None, "industry": None}


def _is_mismatched_commodity_etf(lookup: dict, market_name: str) -> bool:
    """
    FIX 2026-09-12 (findings log 04-11.09, т.6): нужна relevance проверка
    отделно от existence проверката по-горе — потвърдено на 11.09, CANE
    (Teucrium Sugar Fund) се появи и за Cotton, И за RBOB Gasoline
    direct_thesis, реален verified ticker (минава existence проверката),
    но нулева връзка с нито едната суровина. Съзнателно ТЕСЕН, targeted
    check — НЕ generic relevance/keyword engine (риск от прекалено широко
    blocking на легитимни cross-sector връзки, напр. EXPD за RBOB freight
    тезата е легитимна, макар "непряка" — виж дискусията защо generic
    подход е опасен).

    Проверено directamente срещу реални данни: single-commodity ETF-и
    (CANE/BAL/WEAT/CORN/UNG/USO) показват quoteType="ETF",
    category="Commodities Focused", и longName буквално съдържа името на
    суровината ("Teucrium Sugar Fund", "Teucrium Corn Fund"...) —
    надежден, maintenance-free сигнал, не изисква ръчно поддържан mapping.

    Връща True само ако тикърът Е commodity ETF (по category) И неговото
    longName не съдържа никоя ключова дума от market_name — т.е. explicit
    "friendly fire" случай (ETF за ДРУГА суровина), не генерична
    "нерелевантност". Обикновени акции (quoteType != "ETF") никога не се
    третират като mismatch тук.

    FIX 2026-09-12 (хванато в собственото тестване, преди push): наивен
    substring match фалшиво третираше SOYB ("Teucrium Soybean Fund",
    singular) като mismatch за market_name="Soybeans" (plural) — "soybeans"
    не е substring на "soybean". Лек trailing-"s" stem преди сравнение
    (same дух като реалните commodity имена — не пълен NLP stemmer, само
    достатъчен за single/plural разлики в наименования на суровини).
    """
    category = (lookup.get("category") or "").lower()
    if lookup.get("quote_type") != "ETF" or "commodit" not in category:
        return False
    long_name = (lookup.get("long_name") or "").lower()
    stem = lambda w: w[:-1] if w.endswith("s") and len(w) > 3 else w
    market_keywords = [stem(w.lower()) for w in market_name.replace("-", " ").split() if len(w) > 2]
    long_name_stemmed = " ".join(stem(w) for w in long_name.split())
    return not any(kw in long_name_stemmed for kw in market_keywords)


_CYRILLIC = re.compile(r"[Ѐ-ӿ]")

# Правни/структурни суфикси и съюзи — носят нула идентичност, изключват се
# от сравнението (иначе "Inc" в двете страни би бил фалшиво "съвпадение").
_NAME_STOPWORDS = {"inc", "corp", "corporation", "ltd", "plc", "sab", "the",
                   "of", "and", "group", "holdings", "company", "incorporated",
                   "etf", "fund", "trust"}


def _name_tokens(text: str | None) -> set[str]:
    """Думи >2 знака, без правни суфикси — за сравнение на фирмени имена."""
    return {w for w in re.split(r"[^A-Za-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in _NAME_STOPWORDS}


def _identity_mismatch_gloss(lookup: dict, ticker: str, reasoning: str) -> str | None:
    """
    FIX 2026-09-14: трети клас дефект, различен от двата вече покрити.
    Потвърден на 14.09.2026, Sugar No. 11 тезата: header-ът показа
    "ASR (Grupo Aeroportuario del Sureste)" — verified, реален NYSE тикър за
    мексикански airport operator — а reasoning текстът веднага след него
    твърдеше "ASR (Arca Continental) е мексикански bottler". Arca Continental
    е реална компания с реална захарна cost exposure (т.е. тезата логически
    има смисъл), но истинският ѝ тикър е AC.MX, не ASR. Два различни, реални
    бизнеса, объркани под едно тикър символ.

    Защо съществуващите gate-ове не хващат това:
      - _verified_company_name("ASR") -> verified=True (ASR РЕАЛНО съществува,
        existence проверката няма какво да хване);
      - _is_mismatched_commodity_etf() излиза на първия ред — quote_type е
        "EQUITY", не "ETF" (проверката е нарочно тясна за commodity ETF-и).
    Дефектът не е в тикъра и не е в 'company' полето (то е code-verified) — а
    в разминаването МЕЖДУ верифицираното име и свободния AI prose до него.

    Подходът: НЕ "съвпада ли glosa-та с името" (измерено срещу 63 дни реална
    история: 27 от 34 двойки биха гръмнали — скобата след тикър почти никога
    не е фирмено име, а дескриптор/индустрия/бранд: "JPM (large-cap bank)",
    "THG (Property & Casualty)", "PVH (Calvin Klein, Tommy Hilfiger)"), а
    "претендира ли glosa-та изобщо да е ДРУГА фирмена идентичност". Каскада,
    в която всеки филтър изключва по един реален FP клас от историята:
      кирилица       -> BG описание, не име ("NBIX (биотек)")
      запетая/наклон -> списък от брандове/примери, не една идентичност
      lowercase дума -> дескриптор, не собствено име ("RS (inventory ... risk)")
      съвпада с име  -> консистентно ("HWM (Aerospace & Defense)" vs Howmet
                        Aerospace)
      съвпада с industry/sector -> индустриален дескриптор ("THG (Property &
                        Casualty)" vs industry "Insurance - Property & Casualty")
    Измерено срещу всички 34 исторически (ticker, gloss) двойки: 1 сработване
    (реалният ASR случай), 0 false positives.

    Обхватът е съзнателно ограничен: само explicit "TICKER (Име)" конструкция,
    която се среща в ~4% от под-тезите. Останалите 96% не съдържат машинно-
    проверимо твърдение за идентичност изобщо — за тях мярката е промпт
    инструкция (виж _build_cot_user_prompt), mitigation, не guarantee.
    Съзнателно НЕ се прави BG->EN семантично съпоставяне на описанието
    ("мексикански bottler" vs "Airports & Air Services") — това е точно
    генеричният relevance engine, отказан при CANE фикса, виж
    _is_mismatched_commodity_etf() за rationale-а.

    Връща самата glosa при разминаване (за логване), иначе None.
    """
    m = re.search(rf"\b{re.escape(ticker)}\s*\(([^)]{{2,60}})\)", reasoning or "")
    if not m:
        return None
    gloss = m.group(1)

    if _CYRILLIC.search(gloss) or re.search(r"[,;/]", gloss):
        return None
    words = re.findall(r"[A-Za-z][A-Za-z.\-]*", gloss)
    if not words or not all(w[0].isupper() for w in words
                            if len(w) > 2 and w.lower() not in _NAME_STOPWORDS):
        return None

    claimed = _name_tokens(gloss)
    if not claimed:
        return None
    if claimed & (_name_tokens(lookup.get("name")) |
                  _name_tokens(lookup.get("long_name"))):
        return None
    if claimed & (_name_tokens(lookup.get("sector")) |
                  _name_tokens(lookup.get("industry"))):
        return None
    return gloss


def _verify_thesis_tickers(thesis: dict | None, screener_tickers: set[str],
                          market_name: str = "") -> dict | None:
    """
    Заменя AI-generated 'company' с верифицирано yfinance име за всеки тикър в тезата.

    FIX 2026-08-10: 'outside_screener' вече се изчислява ТУК от кода (сравнение
    с реалния screener_tickers set), не се доверяваме на AI self-report. Преди,
    едно top-level 'outside_screener' поле покриваше ЦЯЛАТА теза (direct_thesis
    + cross_sector_thesis заедно) — потвърдено грешно на 10.08.2026, Soybeans
    тезата: direct_thesis тикъри (ADM/BG/MOO) РЕАЛНО бяха извън скрийнъра,
    cross_sector тикъри (ABNB/ROKU) РЕАЛНО бяха в скрийнъра (потвърдено в
    watchlist-а от same ден), но AI-то върна едно 'outside_screener: true' за
    целия обект — footer бележката директно противоречеше на cross_sector
    reasoning текста, който изрично твърдеше "ABNB и ROKU са в скрийнъра".
    Сега всяка под-теза получава СВОЙ собствен, code-computed флаг.

    thesis=None (напр. когато AI-то върне празен cross_sector_thesis при липса
    на директен бенефициент) → връща None непроменено, template-ът вече прави
    {% if c.cross_sector_thesis %} truthiness проверка.

    FIX 2026-08-11: тикъри, за които _verified_company_name() върне
    verified=False (потвърдени случаи MRO/HBI — делистнати, вероятно и
    COTT/PRMW фамилията), се ПРЕМАХВАТ изцяло от финалния tickers списък —
    не просто показват с грозно "TICKER (TICKER)" име. AI-то продължава
    уверено да предлага такива тикъри от training данните си; тих fallback
    не е достатъчен за delisted компания, предложена като реален trade
    кандидат. Ако ВСИЧКИ тикъри в тезата отпаднат по тази причина, цялата
    под-теза се връща като None — reasoning текстът реферира конкретно
    премахнатите тикъри и би бил подвеждащ самичък, без нито един реален
    тикър до него (template-ът вече прави truthiness проверка, скрива блока).
    Частично отпаднали тикъри → останалите се показват нормално, плюс
    "dropped_tickers" бележка (виж dashboard.html.j2).

    FIX 2026-09-12: втора, relevance проверка след existence проверката —
    виж _is_mismatched_commodity_etf() за пълния rationale. Реален verified
    (не delisted) тикър вече не е достатъчно — трябва и да е свързан с
    market_name-а на самата теза, не произволен друг commodity ETF.

    FIX 2026-09-14: трета, identity проверка — виж _identity_mismatch_gloss().
    За разлика от двете по-горе, тук пада ЦЯЛАТА под-теза (return None), не
    само отделният тикър. Причината е различният характер на дефекта: при
    delisted тикър или commodity ETF за друга суровина prose-ът е верен за
    грешен ИНСТРУМЕНТ (описва коректно какво би направил грешният избор), и
    премахването на тикъра е достатъчно. При identity mismatch prose-ът
    съдържа утвърдително НЕВЯРНО фактическо твърдение за реална компания
    ("ASR (Arca Continental) е мексикански bottler") — оставянето му, докато
    само тикърът изчезва, би оставило confidently грешно твърдение на
    дъската, без дори тикър, който да го закотвя визуално. По-лошо, не
    по-добро. Не може да се спаси частично.
    """
    if not thesis:
        return thesis
    tickers = thesis.get("tickers")
    thesis = dict(thesis)
    if not tickers:
        thesis["outside_screener"] = False
        return thesis

    verified, dropped = [], []
    reasoning = thesis.get("reasoning") or ""
    for t in tickers:
        if not (isinstance(t, dict) and t.get("ticker")):
            continue
        lookup = _verified_company_name(t["ticker"])
        if not lookup["verified"]:
            dropped.append(t["ticker"])
        elif market_name and _is_mismatched_commodity_etf(lookup, market_name):
            dropped.append(t["ticker"])
            print(f"[ai] {t['ticker']} премахнат от '{market_name}' теза — "
                 f"commodity ETF за друга суровина ({lookup.get('long_name')})")
        elif (gloss := _identity_mismatch_gloss(lookup, t["ticker"], reasoning)):
            print(f"[ai] '{market_name}' под-теза премахната ИЗЦЯЛО — "
                 f"{t['ticker']}: reasoning текстът я описва като '{gloss}', "
                 f"а верифицираната компания е '{lookup['name']}' "
                 f"({lookup.get('industry')})")
            return None
        else:
            verified.append({**t, "company": lookup["name"]})

    if dropped:
        print(f"[ai] COT тикъри премахнати при верификация "
              f"(вероятно delisted/renamed/грешна суровина): {dropped}")

    if not verified:
        return None

    thesis["tickers"] = verified
    thesis["dropped_tickers"] = dropped or None
    thesis["outside_screener"] = not any(
        t.get("ticker") in screener_tickers for t in thesis["tickers"])
    return thesis


# ──────────────────────────────────────────────────────────────────────────
# FIX 2026-09-28 (Release 2): семантика на посоката в COT тезите.
#
# Старото поле thesis.direction ("bullish"/"bearish") нямаше дефиниция —
# моделът го ползваше ту за посоката на СУРОВИНАТА, ту за ефекта върху
# АКЦИЯТА. 77 обръщания за същия (пазар, тикър, вид) при непроменен
# екстремум до 25.09; на 28.09 BROS "bullish" в директната Coffee теза
# (= кафето нагоре) и "bearish" в cross-sector (= BROS губи от това), а
# HSY/MDLZ едновременно bullish и bearish в Cocoa.
#
# Сега:
#   • посоката на ИНСТРУМЕНТА се изчислява от кода (extreme_long → надолу,
#     extreme_short → нагоре) и се подава на модела като даденост;
#   • моделът връща за всеки тикър само "effect": gains/loses от ТОВА движение,
#     и "assumed_move" — ехо на движението; разминаване = тезата е писана
#     върху обратната предпоставка (30Y на 28.09 прочете -162 052 като "нетно
#     къси") → тезата се отхвърля;
#   • bullish/bearish за всеки тикър се извежда от кода: gains → bullish;
#   • "no_direct_link": true → кодът изпразва tickers (срещу "само като
#     индикативна референция" с тикъра оставен в списъка, 5Y на 28.09).
# ──────────────────────────────────────────────────────────────────────────
_RATE_MARKET = re.compile(r"Treasury|T-Bond|Fed Funds|SOFR", re.I)
_EFFECT_ALIASES = {"gains": "gains", "gain": "gains", "печели": "gains",
                   "loses": "loses", "lose": "loses", "губи": "loses"}
_MOVE_ALIASES = {"up": "up", "нагоре": "up", "down": "down", "надолу": "down"}
_EFFECT_BG = {"gains": "печели", "loses": "губи"}
# само за измерване/лог — отказ в текста при непразен списък (виж Release 2)
_GIVEUP_TEXT = re.compile(
    r"не насилвам|не включвам|твърде разредена|генерична (верига|макро)|"
    r"нито един от (днешните|кандидатите)|няма (реал|пряк|директ)\w* "
    r"(връзк|верига|бенефициент|експозиц)|само като индикатив", re.I)
# FIX 2026-09-29: текстът обявява празен списък с думи, но флагът не е вдигнат
# (Sugar cross 29.09: "no_direct_link е true, tickers е празен", а TSN/CHE
# остават с no_direct_link false). За разлика от _GIVEUP_TEXT (само лог) това
# изпразва списъка. Измерено върху 74 дни (1521 под-тези с текст): 34 появи,
# 30 при вече празен списък, 4 при непразен — и четирите изричен отказ
# (Lean Hogs/WH 04.09, Cotton/FTNT 15.09, Lean Hogs/MNST 16.09, Sugar/TSN,CHE 29.09).
_EXPLICIT_EMPTY_TEXT = re.compile(
    r"no_direct_link\W{0,3}(е\s+|is\s+|=\s*)?true|tickers\W{0,3}(е|остава|оставям)\s+празен|"
    r"оставям\s+tickers\s+празен|връщам\s+(празен|no_direct_link)", re.I)


def _instrument_move(extreme: dict) -> dict:
    """Contrarian движение на инструмента — изчислено от кода, не от модела."""
    up = extreme.get("direction") == "extreme_short"
    text = f"цената на {extreme.get('market')} {'НАГОРЕ' if up else 'НАДОЛУ'}"
    short = f"цена {'↑' if up else '↓'}"
    if _RATE_MARKET.search(extreme.get("market") or ""):
        text += f" (= доходността {'надолу' if up else 'нагоре'})"
        short += f" · доходност {'↓' if up else '↑'}"
    return {"instrument_direction": "bullish" if up else "bearish",
            "move": "up" if up else "down", "move_text": text, "move_short": short}


def _apply_effects(thesis: dict | None, market: str, kind: str) -> dict | None:
    """
    Нормализира под-тезата към новата семантика: no_direct_link → празен
    списък; effect → per-ticker direction. Моделното thesis.direction се маха
    — двусмислено по дефиниция.
    """
    if not thesis:
        return thesis
    thesis = dict(thesis)
    thesis.pop("direction", None)
    tickers = [t for t in (thesis.get("tickers") or [])
               if isinstance(t, dict) and t.get("ticker")]
    if (tickers and thesis.get("no_direct_link") is not True
            and (m := _EXPLICIT_EMPTY_TEXT.search(thesis.get("reasoning") or ""))):
        print(f"[ai] COT '{market}' {kind}: текстът казва '{m.group(0)}', а флагът "
              f"no_direct_link е {thesis.get('no_direct_link')!r} — третира се като true")
        COT_DIAG.setdefault("withdrawn_by_text", []).append(f"{market}/{kind}")
        thesis["no_direct_link"] = True
    if thesis.get("no_direct_link") is True and tickers:
        thesis["withdrawn_tickers"] = [t["ticker"] for t in tickers]
        print(f"[ai] COT '{market}' {kind}: no_direct_link → tickers изпразнени "
              f"{thesis['withdrawn_tickers']}")
        tickers = []
    out = []
    for t in tickers:
        eff = _EFFECT_ALIASES.get(str(t.get("effect") or "").strip().lower())
        t = {**t, "effect": eff,
             "direction": {"gains": "bullish", "loses": "bearish"}.get(eff)}
        if eff is None:
            print(f"[ai] COT '{market}' {kind}: {t['ticker']} без валиден effect "
                  f"({t.get('effect')!r}) — показва се без посока")
            COT_DIAG.setdefault("missing_effect", []).append(f"{market}/{t['ticker']}")
        out.append(t)
    thesis["tickers"] = out
    if out and _GIVEUP_TEXT.search(thesis.get("reasoning") or ""):
        print(f"[ai] COT '{market}' {kind}: текстът звучи като отказ, но tickers "
              f"остават {[t['ticker'] for t in out]} (само лог)")
        COT_DIAG.setdefault("giveup_text_with_tickers", []).append(f"{market}/{kind}")
    return thesis


def _reconcile_same_market(direct: dict | None, cross: dict | None,
                           market: str) -> tuple[dict | None, dict | None]:
    """
    Един тикър в двете под-тези на СЪЩИЯ пазар: същият effect → дубликат,
    маха се от cross-sector; различен effect → моделът си противоречи
    (Cocoa 28.09: HSY/MDLZ) — маркира се conflict в двете, без да гадаем
    коя е вярната.
    """
    if not (direct and cross):
        return direct, cross
    d_eff = {t["ticker"]: t.get("effect") for t in direct.get("tickers") or []}
    keep = []
    for t in cross.get("tickers") or []:
        if t["ticker"] not in d_eff:
            keep.append(t)
        elif d_eff[t["ticker"]] == t.get("effect"):
            print(f"[ai] COT '{market}': {t['ticker']} дублиран в двете под-тези "
                  f"(същия effect) — махнат от cross-sector")
        else:
            print(f"[ai] COT '{market}': {t['ticker']} ПРОТИВОРЕЧИЕ — "
                  f"{d_eff[t['ticker']]} в директната, {t.get('effect')} в cross-sector")
            keep.append({**t, "conflict": True})
            direct = {**direct, "tickers": [
                {**x, "conflict": True} if x["ticker"] == t["ticker"] else x
                for x in direct["tickers"]]}
    return direct, {**cross, "tickers": keep}


# FIX 2026-09-28: дневна диагностика на COT проверките — в лога и в брифа
# ("cot_diag"), за да се мери спазването на новата схема след пускането.
COT_DIAG: dict = {}


def _move_mismatch(t: dict, move: dict) -> str | None:
    """assumed_move срещу изчисленото. Липсващо ехо → само лог, не отхвърляне."""
    got = _MOVE_ALIASES.get(str(t.get("assumed_move") or "").strip().lower())
    if got is None:
        print(f"[ai] COT '{t.get('market')}': липсва assumed_move — не може да се сравни")
        COT_DIAG.setdefault("missing_assumed_move", []).append(t.get("market"))
        return None
    if got != move["move"]:
        return (f"моделът е приел движение '{got}', а изчисленото от позиционирането "
                f"е '{move['move']}' ({move['move_text']})")
    return None


def _build_cot_user_prompt(batch: list[dict], screener_universe: list[dict],
                           regime: str, prior_context: str = "",
                           open_positions: list[dict] | None = None) -> str:
    """
    batch: подмножество от cot.get_extremes() (market, category, net_position,
    percentile, direction, as_of).
    screener_universe: слим списък {ticker, sector, industry} от ТЕКУЩИЯ
    CANSLIM скрийнър — за cross-reference, за да предпочита Claude тикъри,
    които и без друго са в системния универс, вместо произволни имена.
    prior_context: FIX 2026-08-01 (soft cross-batch consistency, т.3 от прегледа
    на 15-31.07) — компактно резюме на тикъри, вече характеризирани в ПО-РАННИ
    batch-ове в СЪЩИЯ run (напр. "HWM: Copper/direct_thesis bearish — ...").
    Batch-овете са изолирани Claude извиквания (виж cot_theses) — без това AI-то
    няма видимост към собствените си по-раншни тези в същия бриф и може да даде
    противоречива характеристика на един и същ тикър (напр. "defensive" в една
    тема, "risk-on beta" в друга, същия ден) без да го отбележи. Празен низ на
    първия batch (няма все още нищо генерирано).
    """
    prior_block = (
        f"""

ВЕЧЕ ХАРАКТЕРИЗИРАНИ ТИКЪРИ ПО-РАНО В ТОЗИ БРИФ (за консистентност; всеки \
ред казва дали компанията ПЕЧЕЛИ или ГУБИ при изчисленото движение на онзи \
инструмент, и изведената посока за самата акция):
{prior_context}

Ако същият тикър тук печели, а там губи (или обратно) — провери дали движенията \
на двата инструмента наистина го обясняват (напр. 30Y надолу и 5Y надолу водят \
до еднакъв ефект за застраховател); ако не — кажи го изрично.

Ако предложиш тикър от списъка по-горе: провери дали новата роля/характеристика \
съвпада с предишната (defensive/cyclical/hedge/core bet и т.н.). Ако тезата тук \
предполага различна роля — кажи го ИЗРИЧНО в reasoning-а (напр. "за разлика от \
ролята му в Copper тезата, тук HWM действа като hedge, не core bet"), не просто \
противоречи мълчаливо на предишната характеристика. Легитимно е тикър да има \
няколко ортогонални роли (различни причини) — проблем е само ПРЯКОТО, необяснено \
противоречие в характера на тикъра."""
        if prior_context else ""
    )
    # FIX 2026-09-15: виж cot_theses() docstring-а — без този блок промптът
    # виждаше САМО днешния скрийнър, значи "извън скрийнъра" и "не фигурира
    # никъде в брифа" бяха неразличими. Имената са ЗАДЪЛЖИТЕЛНИ: реалният
    # случай назова "Valero", не "VLO".
    positions_block = (
        f"""

ОТВОРЕНИ TRACK RECORD ПОЗИЦИИ (реално държани в момента, влезли на посочената \
дата): {json.dumps(open_positions, ensure_ascii=False, default=str)}

Тези компании СА част от брифа — следени са ежедневно, откакто са отворени. \
Ако споменеш някоя от тях (по тикър ИЛИ по име), НЕ твърди, че „не фигурира в \
брифа", „не е разглеждана досега" или подобно — това е фактически невярно. \
Такъв тикър може напълно легитимно да липсва от ДНЕШНИЯ CANSLIM скрийнър — \
скрийнърът е дневен snapshot на нови кандидати, не списък на държаното — но \
двете са различни твърдения и не се смесват. Ако позицията пасва на тезата, \
предложи я нормално и отбележи, че вече е отворена позиция."""
        if open_positions else ""
    )
    return f"""Пазарен режим: {regime}

CFTC ЕКСТРЕМУМИ (managed money net positioning, percentile спрямо до 156-седмична \
история — "weeks_of_history" полето показва точния брой за всеки инструмент, \
виж инструкцията по-долу защо е важно): {json.dumps(batch, ensure_ascii=False, default=str)}

ТЕКУЩ CANSLIM СКРИЙНЪР (за cross-reference — предпочитай тези тикъри, когато \
логически пасват; ако нищо не пасва добре, предложи друг ликвиден тикър — дали \
е извън скрийнъра се засича автоматично от кода, не отбелязвай го сам): \
{json.dumps(screener_universe, ensure_ascii=False, default=str)}
{positions_block}
{prior_block}

ВАЖНО за инструменти с "weeks_of_history" под {config.COT_SHORT_HISTORY_WEEKS} \
(стандартният дизайн е 156 седмици/~3г — по-млад контракт означава по-кратка \
налична история, не грешка в данните): добави explicit изречение В КРАЯ на \
всеки reasoning текст (direct_thesis И cross_sector_thesis, ако имат tickers), \
което flag-ва по-ниската статистическа увереност спрямо стандартните 156-\
седмични инструменти в тезата — напр. "История само {{N}} седмици (под \
стандартните ~156) — percentile-ът тук е по-малко статистически сигурен от \
обичайното." Не пропускай тази бележка мълчаливо — юзърът трябва да я вижда \
directamente в текста, не само да се досеща от суровите данни.

ВАЖНО за имената на компаниите в reasoning текста: когато споменаваш тикър в \
reasoning-а, използвай ТОЧНО името, което си дал в "company" полето за същия \
тикър — не свободна перифраза и не друго име, което смяташ за същата компания. \
Потвърден случай (14.09.2026): reasoning текст твърдеше "ASR (Arca Continental) \
е мексикански bottler", докато ASR реално е Grupo Aeroportuario del Sureste — \
съвсем различен бизнес (оператор на летища), който просто споделя същите букви; \
истинският тикър на Arca Continental е AC.MX. Ако не си сигурен кой е точният \
тикър на компанията, която искаш да опишеш — НЕ я предлагай изобщо, вместо да \
залепиш описанието към чужд тикър.

ДРУГА ТЕЗА НЕ Е ДОКАЗАТЕЛСТВО: всяка верига трябва да стои самостоятелно, върху \
реален икономически механизъм на ТОЗИ инструмент — и между инструментите в \
този отговор, и спрямо по-рано характеризираните тикъри. Не пиши "ролята се \
потвърждава от X тезата", "идентична логика като в X" или подобно — това, че \
тикърът фигурира и другаде, не прави връзката по-вярна. Потвърден случай \
28.09.2026: Soybean Meal тезата твърдеше, че соевото брашно е основен компонент \
в авиационното биогориво (невярно — SAF се прави от масла и мазнини, брашното \
е фураж), а Corn тезата го цитира като потвърждение.

ПОСОКАТА НА ИНСТРУМЕНТА Е ДАДЕНА — НЕ Я ИЗВЕЖДАЙ САМ: полето "expected_move" \
за всеки инструмент е изчислено от кода от позиционирането (contrarian: \
extreme_long → цената надолу, extreme_short → цената нагоре). Позиционирането \
се чете САМО от "direction" и "percentile". Знакът на "net_position" НЕ означава \
"нетно къси": при облигационни и някои финансови фючърси спекулантите са \
структурно на минус, и 100-и percentile с отрицателно net_position означава \
"най-малко къси за 156 седмици" = ЕКСТРЕМНО ДЪЛГИ спрямо историята. Потвърден \
случай 28.09.2026: 30-Year Treasury Bond, 100-и percentile, net -162 052 — \
текстът написа "НЕТНО КЪСИ… максимален short" и обърна цялата теза. Никога не \
пиши "нетно къси/дълги" въз основа на знака.

За ВСЕКИ инструмент в списъка върни обект с:
- "market": точното име както е подадено
- "assumed_move": "up" или "down" — препиши движението от "expected_move" \
(проверява се от кода; разминаване = тезата се отхвърля)
- "direct_thesis": {{
    "tickers": [1-3 обекта {{"ticker": "ADM", "company": "Archer-Daniels-Midland", \
"effect": "gains"/"loses"}} — пряко изложени на инструмента; "company" е кратко, \
познато име, НЕ пълното юридическо наименование; "effect" = дали КОМПАНИЯТА \
печели ("gains") или губи ("loses"), АКО инструментът се движи както казва \
"expected_move". Не посоката на суровината, а ефектът върху акцията — напр. \
какаото нагоре → HSY "loses"; облигациите надолу → TLT "loses"],
    "no_direct_link": true/false — true, ако НЯМА нито един реален, ликвиден, \
публично търгуван тикър с истинска директна експозиция (тогава tickers е []; \
ако все пак оставиш тикър "само за референция" — кодът ще го премахне),
    "reasoning": "2-3 изречения — защо точно тези тикъри и защо сега. Ако НЯМА \
нито един реален, ликвиден, публично търгуван тикър с истинска директна \
експозиция на инструмента (напр. основният производител не е самостоятелно \
публичен), върни ПРАЗЕН tickers списък ([]), no_direct_link: true и кажи го \
изрично тук — не насилвай слаб/индиректен избор само за да запълниш полето."
  }}
- "cross_sector_thesis": {{
    "no_direct_link": true/false — както по-горе,
    "tickers": [1-3 обекта {{"ticker": "...", "company": "...", "effect": \
"gains"/"loses"}} — компании, засегнати ВТОРИЧНО (не същите като в директната \
теза), САМО ако има ДИРЕКТНА икономическа връзка (1-2 стъпки: input \
costs, revenue exposure, конкурентна позиция спрямо самия инструмент) — НЕ \
generic макро верига от типа "цената пада → инфлацията спада → потребителите \
харчат повече → X печели донякъде" (технически вярно, но твърде разредено за \
реална теза — почти всяка discretionary акция "пасва" на почти всяка commodity \
deflation тема по този начин, което го прави безсмислено),
    "reasoning": "2-3 изречения — директната верижна логика инструмент → \
компания. Ако НИКОЙ кандидат няма реална директна връзка, върни ПРАЗЕН \
tickers списък ([]), no_direct_link: true и кажи го изрично тук (напр. 'няма \
пряк бенефициент сред днешните кандидати') — не насилвай генерична връзка само \
за да запълниш полето."
  }}

Тикър, който вече е в "direct_thesis" на СЪЩИЯ инструмент, не се повтаря в \
"cross_sector_thesis". Не пиши думите bullish/bearish за тикърите в текста — \
посоката им се извежда от "effect" от кода.

ФЛАГЪТ И ТЕКСТЪТ ТРЯБВА ДА СЪВПАДАТ: ако в "reasoning" пишеш, че няма реална \
връзка, че тикърът няма материална експозиция или че списъкът е празен — \
"no_direct_link" е true и "tickers" е []. Не оставяй тикър в списъка, който \
самият текст отхвърля. Потвърден случай 29.09.2026: Sugar cross-sector текстът \
написа "no_direct_link е true, tickers е празен", а върна TSN и CHE с \
no_direct_link false.

Ако екстремумът е твърде слаб/неясен за смислена теза (напр. пазар без ликвидни \
свързани акции), пропусни го от отговора — не гадай.

Връщай само JSON: {{"theses": [...]}}"""


def _cot_theses_for_batch(batch: list[dict], screener_universe: list[dict],
                          regime: str, tag: str, prior_context: str = "",
                          open_positions: list[dict] | None = None) -> list[dict]:
    """Един batch → едно Claude извикване. 1 retry, после graceful skip на batch-а."""
    user = _build_cot_user_prompt(batch, screener_universe, regime, prior_context,
                                  open_positions)
    for attempt in (1, 2):
        try:
            out = _parse_json(_call_claude(SYSTEM_COT, user,
                                           max_tokens=config.COT_BATCH_MAX_TOKENS))
            return out.get("theses", [])
        except TruncatedResponse:
            break  # FIX 2026-09-23: retry при същия лимит отрязва пак, на двойна цена
        except Exception as e:
            label = "опит" if attempt == 1 else "retry"
            print(f"[ai] cot batch {tag} {label} неуспешен: {type(e).__name__}: {e}")
    print(f"[ai] cot batch {tag} пропуснат след 2 опита — "
          f"губим {len(batch)} екстремума: {[e.get('market') for e in batch]}")
    return []


def _record_ticker_context(seen: dict[str, str], market: str, thesis_type: str,
                           thesis: dict) -> None:
    """
    FIX 2026-08-01 (т.3): записва компактно резюме на всеки тикър от тази теза в
    running `seen` речника — подава се на СЛЕДВАЩИТЕ batch-ове (виж cot_theses)
    за soft consistency check. Пази само ПОСЛЕДНАТА поява на тикъра (не пълна
    история) — целта е "не противоречи на скорошното", не пълен audit trail.

    FIX 2026-08-02: капнато на config.COT_SEEN_TICKERS_CAP записа (FIFO) — без
    това prior_context би растял неограничено на дни с много batch-ове/тикъри.
    `del` преди презапис премества тикъра в края на dict-а (Python 3.7+ пази ред
    по вмъкване) — така eviction-ът реално маха НАЙ-СТАРО ДОКОСНАТИЯ тикър, не
    просто първия въведен, ако той междувременно е бил обновен отново.
    """
    # FIX 2026-09-28 (Release 2): контекстът носи ЕФЕКТА върху компанията
    # спрямо изчисленото движение, не двусмисления thesis.direction етикет
    # ("TLT: 5Y bearish" не казваше дали облигациите или TLT падат).
    # FIX 2026-09-28 (т.10): БЕЗ откъс от reasoning-а. Точно по този канал
    # невярното "соевото брашно е основен компонент в SAF" (Soybean Meal,
    # batch 1) стигна до Corn (batch 2) и беше цитирано като потвърждение.
    # Само ролята пътува между batch-овете, не фактически твърдения.
    move_text = thesis.get("_move_text") or "?"
    for t in thesis.get("tickers") or []:
        ticker = t.get("ticker") if isinstance(t, dict) else None
        if not ticker:
            continue
        eff = _EFFECT_BG.get(t.get("effect"))
        if eff:
            role = f"{eff} при {move_text} → {t.get('direction')} за {ticker}"
        else:
            role = f"ефект неизвестен при {move_text}"
        seen.pop(ticker, None)
        seen[ticker] = f'{ticker}: {market}/{thesis_type} — {role}'
        while len(seen) > config.COT_SEEN_TICKERS_CAP:
            seen.pop(next(iter(seen)))


def cot_theses(extremes: list[dict], screener_universe: list[dict],
              regime: str, open_positions: list[dict] | None = None) -> list[dict]:
    """
    За всеки COT екстремум (extremes от src.cot.get_extremes()) генерира
    директна + cross-sector теза. Batch-вано по config.COT_BATCH_SIZE заради
    token budget (аналогично на ticker_narratives). Мърджва резултата обратно
    в extremes по "market", запазвайки оригиналните числови полета
    (percentile, net_position, direction, history) — Claude връща само
    тезите, не пипа числата.

    FIX 2026-08-01 (т.3 от прегледа на 15-31.07): тикъри често се появяват в
    2-6+ различни тези същия ден (потвърдено емпирично — JPM до 6 пъти в 1 бриф),
    а batch-овете са изолирани Claude извиквания без взаимна видимост → противоречиви
    характеристики на един и същ тикър (напр. "defensive" в една тема, "risk-on
    beta" в друга) минаваха необяснени. Soft fix: running `seen_tickers` речник се
    строи batch по batch (sequential, вече такъв е потокът) и се подава на ВСЕКИ
    следващ batch като "вече характеризирани тикъри" контекст — AI-то е
    инструктирано да обясни изрично, ако новата роля се различава, не просто да
    противоречи мълчаливо. Не забранява легитимни multi-role тикъри.

    FIX 2026-09-15: open_positions — отворените Track Record позиции {ticker,
    company, entry_date} като ОТДЕЛЕН контекстен блок, симетрично на
    screener_universe. Потвърдено на 15.09.2026, RBOB Gasoline тезата: AI-то
    написа "рафинерии като Valero или PBF Logistics биха пасвали идеално, но
    са характеризирани извън текущия скрийнър и не фигурират в досегашния
    бриф", докато VLO е отворена позиция от 12.08 (+18.1%) — и самото AI я
    предложи по име в СЪЩАТА RBOB теза на 07.09. Първата половина на
    твърдението е вярна (VLO наистина е извън днешния скрийнър), втората е
    невярна; дотогава промптът виждаше САМО скрийнъра, значи "извън скрийнъра"
    и "не фигурира никъде" бяха неразличими от гледната точка на модела.

    Защо контекст на ВХОДА, а не проверка на изхода (за разлика от FIX
    2026-09-14): VLO изобщо не беше в "tickers" (списъкът беше празен) —
    компанията беше спомената само в прозата, и то по ИМЕ ("Valero"), не по
    тикър. Badge като GLB already_open_position няма какво да маркира, а
    ticker-базирана проверка на текста не би я видяла: собственото ми
    сканиране на 50 дни по тикър пропусна точно този случай и го намери едва
    при търсене по фирмено име. Затова: да не се създава грешката, вместо да
    се лови после.

    Цената е пренебрежима — main._live_positions() е чисто локален прочит на
    backtest_tracker.json, без нито една мрежова заявка, за разлика от
    get_backtest_summary(), който fetch-ва текущи цени и затова живее чак в
    края на pipeline-а. Тоест контекстът е наличен ТУК, без никакво
    пренареждане на реда на изпълнение.
    """
    COT_DIAG.clear()
    if not extremes:
        return []

    moves = {e["market"]: _instrument_move(e) for e in extremes}
    slim = [{"market": e["market"], "category": e["category"],
            "percentile": e["percentile"], "direction": e["direction"],
            "expected_move": moves[e["market"]]["move_text"],
            "net_position": e["net_position"], "as_of": e["as_of"],
            "weeks_of_history": e.get("weeks_of_history")}
           for e in extremes]

    size = max(1, config.COT_BATCH_SIZE)
    batches = [slim[i:i + size] for i in range(0, len(slim), size)]
    n = len(batches)
    print(f"[ai] cot_theses: {len(slim)} екстремума → {n} batch(ове) по ≤{size}")

    theses_by_market: dict[str, dict] = {}
    seen_tickers: dict[str, str] = {}
    for idx, batch in enumerate(batches, 1):
        prior_context = "\n".join(seen_tickers.values())
        for t in _cot_theses_for_batch(batch, screener_universe, regime,
                                       f"{idx}/{n}", prior_context, open_positions):
            if t.get("market") in moves:
                t = _normalize_cot_thesis(t, moves[t["market"]])
                theses_by_market[t["market"]] = t
                if t.get("thesis_rejected"):
                    continue  # отхвърлена теза не влиза в контекста на следващите batch-ове
                _record_ticker_context(seen_tickers, t["market"], "direct_thesis",
                                       t.get("direct_thesis") or {})
                _record_ticker_context(seen_tickers, t["market"], "cross_sector_thesis",
                                       t.get("cross_sector_thesis") or {})

    screener_tickers = {c["ticker"] for c in screener_universe if c.get("ticker")}
    merged = []
    for e in extremes:
        t = theses_by_market.get(e["market"])
        if not t:
            continue
        move = {k: moves[e["market"]][k]
                for k in ("instrument_direction", "move_text", "move_short")}
        if t.get("thesis_rejected"):
            merged.append({**e, **move, "direct_thesis": None, "cross_sector_thesis": None,
                           "thesis_rejected": t["thesis_rejected"]})
            continue
        merged.append({**e, **move,
                       "direct_thesis": _empty_sub_reason(
                           t.get("direct_thesis"), _strip_internal(_verify_thesis_tickers(
                               t.get("direct_thesis") or {}, screener_tickers, e["market"])),
                           e["market"], "direct"),
                       "cross_sector_thesis": _empty_sub_reason(
                           t.get("cross_sector_thesis"), _strip_internal(_verify_thesis_tickers(
                               t.get("cross_sector_thesis") or {}, screener_tickers, e["market"])),
                           e["market"], "cross")})

    subs = [(c["market"], c.get(k) or {}) for c in merged
            for k in ("direct_thesis", "cross_sector_thesis")]
    COT_DIAG.update({
        "extremes": len(extremes),
        "theses": len(merged),
        "rejected": [c["market"] for c in merged if c.get("thesis_rejected")],
        "conflicts": sorted({f"{m}/{t['ticker']}" for m, th in subs
                             for t in th.get("tickers") or [] if t.get("conflict")}),
        "withdrawn": [f"{m}/{x}" for m, th in subs for x in th.get("withdrawn_tickers") or []],
    })
    print(f"[ai] cot_theses: {len(merged)}/{len(extremes)} тези · отхвърлени "
          f"{len(COT_DIAG['rejected'])} {COT_DIAG['rejected'] or ''} · противоречия "
          f"{len(COT_DIAG['conflicts'])} · махнати (no_direct_link) {len(COT_DIAG['withdrawn'])} · "
          f"без assumed_move {len(COT_DIAG.get('missing_assumed_move', []))} · "
          f"без effect {len(COT_DIAG.get('missing_effect', []))}")
    return merged


def _empty_sub_reason(raw: dict | None, verified: dict | None,
                      market: str, kind: str) -> dict:
    """
    FIX 2026-09-29: под-теза без нищо за показване изчезваше от страницата
    изцяло (Cotton direct 29.09: без заглавие, без обяснение). Два пътя: всички
    тикъри отпадат при _verify_thesis_tickers (→ None) или моделът изобщо не
    върне под-тезата (→ {}). 7 случая в 74 дни (6 None, 1 {}). Вместо това —
    празна под-теза с причина, която шаблонът показва като ред.
    """
    if verified:
        return verified
    dropped = [t["ticker"] for t in (raw or {}).get("tickers") or []
               if isinstance(t, dict) and t.get("ticker")]
    if dropped:
        why = (f"предложените тикъри ({', '.join(dropped)}) отпаднаха при проверката "
               f"(delisted, грешна суровина или грешно описание на компанията)")
    else:
        why = "моделът не върна тази под-теза"
    print(f"[ai] COT '{market}' {kind}: няма под-теза за показване — {why}")
    COT_DIAG.setdefault("empty_sub", []).append(f"{market}/{kind}")
    return {"tickers": [], "no_direct_link": True, "reasoning": "",
            "empty_reason": why, "outside_screener": False}


def _strip_internal(thesis: dict | None) -> dict | None:
    return {k: v for k, v in thesis.items() if not k.startswith("_")} if thesis else thesis


def _normalize_cot_thesis(t: dict, move: dict) -> dict:
    """
    FIX 2026-09-28 (Release 2): един отговор за пазар → новата семантика.
    Ред: проверка на assumed_move → effect/no_direct_link → същия пазар
    дубликат/противоречие. Резултатът е и това, което отива в prior_context.
    """
    market = t["market"]
    why = _move_mismatch(t, move)
    if why:
        print(f"[ai] COT '{market}': ТЕЗАТА ОТХВЪРЛЕНА — {why}")
        return {"market": market, "thesis_rejected": why}
    direct = _apply_effects(t.get("direct_thesis") or {}, market, "direct")
    cross = _apply_effects(t.get("cross_sector_thesis") or {}, market, "cross")
    direct, cross = _reconcile_same_market(direct, cross, market)
    for th in (direct, cross):
        if th:
            th["_move_text"] = move["move_text"]
    return {**t, "direct_thesis": direct, "cross_sector_thesis": cross}


# ══════════════════════════════════════════════════════════════════════════
# Short/Stage 4 Screener — Аспект 2: global-vs-regional context (2026-08-2x)
# ══════════════════════════════════════════════════════════════════════════

SYSTEM_SHORT_CONTEXT = """Ти си макро анализатор, който преценява дали секторна слабост е \
глобален структурен феномен, или regional/US-специфичен проблем — за да не предложим short \
кандидат, чийто основен бизнес проблем не важи за неговия конкретен пазар (напр. US coal умира \
заради regulation, докато Индия coal расте — индийска coal компания не е валиден short на тази \
теза). Пишеш на български, тикери на английски. Връщаш САМО валиден JSON, без markdown огради."""


def short_thesis_global_context(sector_name: str, recent_news: list[dict]) -> dict:
    """
    Аспект 2 от Short/Stage 4 архитектурата (feasibility дискусия 2026-08-2x):
    AI-synthesis слой за global-vs-regional context проверка, вместо
    структурирани international данни (по-голям technical lift, отделна
    feasibility). Reuse-ва СЪЩЕСТВУВАЩИТЕ headlines (news_aggregator.py),
    без нов data source.

    Explicit honesty gate: ако headlines-ите не покриват достатъчно
    geographic context, AI-то връща "insufficient_data" вместо да гадае —
    same дух като direct_thesis "върни празно, кажи защо" instruction (COT
    секцията по-горе), и директен урок от IEI/HYG numeric fidelity инцидента
    (2026-08-26) — не позволявай правдоподобно звучащ, но неверифициран
    extrapolation да мине като сигурна преценка.

    Graceful: провал на AI извикването → "insufficient_data" fallback, не
    гърми целия short screener run.
    """
    headlines_text = "\n".join(f"- {n.get('title', '')}" for n in (recent_news or [])[:15]) \
        or "(няма скорошни headlines)"
    user = f"""Сектор с потвърдена, устойчива относителна слабост: {sector_name}

СКОРОШНИ НОВИНИ (последните ~24-48ч, може да не покриват темата изобщо):
{headlines_text}

Задача: прецени дали слабостта на "{sector_name}" е ГЛОБАЛЕН структурен феномен (важи навсякъде \
по света), или REGIONAL/US-специфичен проблем (напр. regulation, местна политика, локален \
свръхкапацитет), докато други региони показват противоположна динамика. Ако headlines-ите ПО-ГОРЕ \
не съдържат достатъчно информация за такава преценка — НЕ гадай, НЕ екстраполирай от общи \
познания за темата — върни explicit "insufficient_data" в "scope" полето.

Връщай само JSON: {{"scope": "global"/"regional"/"insufficient_data", \
"reasoning": "2-3 изречения", "confidence": "high"/"medium"/"low"}}"""

    try:
        raw = _call_claude(SYSTEM_SHORT_CONTEXT, user)
        return _parse_json(raw)
    except Exception as e:
        print(f"[ai] short global context '{sector_name}' failed: {e}")
        return {"scope": "insufficient_data",
                "reasoning": f"AI извикване неуспешно: {type(e).__name__}: {e}",
                "confidence": "low"}
