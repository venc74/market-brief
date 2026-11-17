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
from collections import Counter
from functools import lru_cache
import requests
import yfinance as yf
import json_repair

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import backtest
from src import net_utils
from src import names
from src import regime_claims
from src import sector_claims           # 13.10.2026: "единственият сектор с положителна RS" — факт от кода + проверка

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
# 16.11.2026 (пакет 16.11, т. 3): махнатите изречения с имена на полета (_FIELD_RE) — [{section, fields, sentence}]; main → brief["ai_field_drops"] (данни и лог, без банер:
# в историята средно ~19 на бриф до 16.11)
FIELD_DROPS: list[dict] = []
# правилото към всяко извикване (системата) — по-малко изречения за махане
FIELD_NAMES_RULE = ("\n\nНе пиши имена на полета от входните данни (напр. rs_4w, near_high, volume_ratio, insider_cluster = true, setup_reason, laggard persistence) — "
                    "кажи го с думи на български („обем 0.81× от средния“, „близо до върха“, „RS за 4 седмици“).")      # 17.11.2026 (пакет 1, т. 3а): с примери; познатите се подменят от кода
# 17.11.2026 (пакет 1, т. 3б): подменените познати имена на полета — [{section, field, sentence}]; main → brief["ai_field_subs"]
FIELD_SUBS: list[dict] = []
AI_USAGE: list[dict] = []
# 29.10.2026: последното извикване (отговорът, етикетът, аргументите) — за ЕДИНИЯ повторен опит в _parse_json, когато json_repair е изрязал текст.
# Повтаря се само ако текстът за парсване е точно този отговор (иначе — подменено извикване в тест или чужд текст — няма повторение).
_LAST_CALL: dict = {}

# Име на извикващата функция → четим етикет за лога и брифа. Извличат се от
# стека, за да не се пипат шестте call site-а само заради етикет.
_SECTION_LABELS = {
    "macro_and_sector_brief": "Макро разказ",                          # 30.10.2026: до т. 7 „Макро бриф и секторна карта“ — веригите на секторите отпаднаха
    "_macro_and_sector_brief_ai": "Макро разказ",      # 08.10: същото тяло под ново име (обвивка с проверка на твърденията за режима)
    "_narratives_for_batch": "Тикър наративи",
    "watch_ticker_digest": "Наблюдавани тикъри",
    "_watch_digest_batch": "Наблюдавани тикъри",               # 30.10.2026: на групи по 4
    "significant_news": "Значими новини",
    "_probe": "Проверка на модела",
    "ep_catalyst_call": "EP катализатор",                    # 09.10: qm_ep.ep_catalyst_call (преди — lambda → "<lambda>")
    "crypto_news_call": "Крипто новини",                     # 22.10.2026: src/crypto_news.py
    "_parse_json": "Повторен опит (изрязан JSON)",            # 29.10.2026: само резерва — повторният опит подава етикета на първото извикване (_section)
}


def _call_claude(system: str, user: str, max_tokens: int = 4000,
                 extra_messages: list[dict] | None = None,
                 allow_truncation: bool = False, _section: str | None = None) -> str:
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
        "system": system + FIELD_NAMES_RULE,                                    # 16.11.2026 (т. 3)
        "messages": messages,
    }, timeout=180)
    r.raise_for_status()
    resp = r.json()

    # FIX 2026-09-23: stop_reason и usage се четат при ВСЯКО извикване.
    caller = sys._getframe(1).f_code.co_name
    section = _section or _SECTION_LABELS.get(caller, caller)               # 29.10.2026: повторният опит от _parse_json носи етикета на първото извикване
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

    text = "".join(b.get("text", "") for b in resp["content"]
                   if b.get("type") == "text")
    _LAST_CALL.clear()
    _LAST_CALL.update(text=text, section=section, args={"system": system, "user": user, "max_tokens": max_tokens,
                                                        "extra_messages": extra_messages, "allow_truncation": allow_truncation})
    return text


def _parse_json(text: str, _retried: bool = False):
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
    last = dict(_LAST_CALL)
    own = last.get("text") == text
    caller = sys._getframe(1).f_code.co_name
    section = last.get("section") if own else _SECTION_LABELS.get(caller, caller)
    try:
        return _fix_text(json.loads(clean), section)
    except json.JSONDecodeError as e:
        repaired = json_repair.loads(clean)
        if isinstance(repaired, (dict, list)) and repaired:
            print(f"[ai] _parse_json: json_repair поправи malformed JSON ({e})")
            cuts = repair_cuts(clean, repaired, extra_data=e.msg == "Extra data")
            if cuts:
                print(f"[ai] ⚠ json_repair изряза текст — {section}: " + "; ".join(f"{c['field'] or 'отговорът'} свършва на «…{c['tail']}», изпуснато «{c['lost']}…»"
                                                                                  for c in cuts))
                if own and not _retried:
                    print(f"[ai] {section}: един повторен опит на извикването")
                    try:
                        return _parse_json(_call_claude(**last["args"], _section=section), _retried=True)
                    except Exception as e2:
                        print(f"[ai] {section}: повторният опит не мина ({type(e2).__name__}: {e2}) — остава поправеният отговор")
                TRUNCATIONS.append({"section": section, "kind": "json_repair", "model": config.CLAUDE_MODEL,
                                    "fields": [c["field"] for c in cuts if c["field"]], "tail": cuts[0]["tail"], "retried": own})
                for c in cuts:
                    if c["ref"]:
                        parent, key = c["ref"]
                        parent[key] = parent[key].rstrip() + CUT_MARK                 # видимо там, където е изрязано (страницата и имейлът)
                print(f"[ai] ⚠ {section}: текстът е непълен днес (json_repair — и след повторния опит)" if own else
                      f"[ai] ⚠ {section}: текстът е непълен днес (json_repair)")
            return _fix_text(repaired, section)
        raise


# 29.10.2026: json_repair поправя счупения JSON, като РЕЖЕ: ASCII кавичка в текста, последвана от запетая, затваря низа — останалото се губи без грешка. Макро текстът на 29.10
# свърши на «…ново покачване „не би било грешка» (329 знака; stop_reason end_turn) — моделът е затворил българския цитат с ASCII ". Проверката: низ от поправения JSON, който в
# суровия отговор продължава след кавичката с текст, а не с JSON синтаксис (, } ] :) — изрязан; низ с отворена „ без затваряща; или поправеният JSON е с ≥ REPAIR_LOSS_CHARS знака
# (без интервалите) по-къс от суровия отговор. Измерено върху историята (13.06–29.10, 3322 текстови полета): 1 изрязано поле — 29.10.
REPAIR_LOSS_CHARS = 40
_JSON_AFTER_COMMA = re.compile(r'\s*(?:["{\[\]}\-\d]|true\b|false\b|null\b)')


CUT_MARK = " … ✂ текстът е непълен днес"


def _strings(o, path: str = ""):
    """(път, родител, ключ, низ) за всеки низ в JSON-а."""
    items = o.items() if isinstance(o, dict) else enumerate(o) if isinstance(o, list) else ()
    for k, v in items:
        p = (f"{path}.{k}" if path else str(k)) if isinstance(o, dict) else f"{path}[{k}]"
        if isinstance(v, str):
            yield p, o, k, v
        else:
            yield from _strings(v, p)


def repair_cuts(raw: str, repaired, extra_data: bool = False) -> list[dict]:
    """Изрязаните от json_repair низове: [{field, tail, lost, ref}] (field None — загуба само по дължината; ref = (родител, ключ) за маркера). Не пипа repaired."""
    cuts = []
    for path, parent, key, s in _strings(repaired):
        if len(s) < 10:
            continue
        enc = json.dumps(s, ensure_ascii=False)[1:-1]
        i = raw.find(enc)
        j = i + len(enc)
        cut = False
        if i >= 0 and raw[j:j + 1] == '"':
            rest = raw[j + 1:].lstrip()
            cut = bool(rest) and not (rest[0] in '}]:"' or (rest[0] == "," and _JSON_AFTER_COMMA.match(rest[1:])))      # '"' — липсваща запетая преди следващия низ
        if cut or s.count("„") > s.count("“") + s.count("”") + s.count('"'):
            lost = raw[j + 1:j + 61].strip() if cut else ""
            cuts.append({"field": path, "tail": s[-60:], "lost": lost, "ref": (parent, key)})
    if not cuts and not extra_data:
        n_raw = len(re.sub(r"\s", "", re.sub(r"\\u[0-9a-fA-F]{4}", "u", raw)))
        n_rep = len(re.sub(r"\s", "", json.dumps(repaired, ensure_ascii=False)))
        if n_raw - n_rep >= REPAIR_LOSS_CHARS:
            cuts.append({"field": None, "tail": "", "lost": f"{n_raw - n_rep} знака", "ref": None})
    return cuts


def _fix_text(obj, section: str | None = None):
    """_fix_translit + един обобщен лог ред за хибридните думи в отговора; махнатите изречения с чужди символи → ai_truncations (kind "cjk")."""
    _HYBRIDS.clear()
    _HYBRID_CTX.clear()
    _CJK_DROPPED.clear()
    _FIELD_DROPPED.clear()
    _FIELD_SUBBED.clear()
    out = _fix_translit(obj)
    for d in _FIELD_SUBBED:                                                    # 17.11.2026 (т. 3б): подменените познати имена — данни и лог
        FIELD_SUBS.append({"section": section or "AI текст", **d})
    for d in _FIELD_DROPPED:                                                   # 16.11.2026 (т. 3): имена на полета — данни и лог, без банер
        FIELD_DROPS.append({"section": section or "AI текст", **d})
    if _CJK_DROPPED:
        TRUNCATIONS.append({"section": section or "AI текст", "kind": "cjk", "model": config.CLAUDE_MODEL,
                            "chars": "".join(d["chars"] for d in _CJK_DROPPED), "removed": [d["sentence"][:200] for d in _CJK_DROPPED]})
    if _HYBRIDS:
        print(f"[ai] смесено писмо (само лог, {len(_HYBRIDS)}): "
              f"{', '.join(dict.fromkeys(_HYBRIDS))}")
        _log_mixed_words()
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
# 29.10.2026: махането САМО на символите оставя счупено изречение — WSM на 29.10: „технически cataly за momentum“ (моделът е продължил „cataly…“ с китайски, както на 21.09
# „потенциален催化剂“ = catalyst). В историята CJK е винаги дума насред изречението (6 появи 06.07–28.09, преди филтъра: 損害, 底, 升级, 映射, 催化剂, 純) → маха се ЦЯЛОТО изречение;
# низ, който е само това изречение, става празен (в списък — елементът пада). Махнатите изречения → ai_truncations (kind "cjk", _fix_text) и ред в банера.
_CJK_DROPPED: list[dict] = []
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
# 16.11.2026 (пакет 16.11, т. 3): сурово име на поле в български AI текст на публичната страница — „sells_25pct_of_stake“ (13.11, наблюдаваните), „Съгласно setup_reason кодът
# определя“ (13.11, NDAQ), „rs_status: near_high“ (16.11), „insider_cluster = true“, „laggard persistence от 85%“ (16.11, разказът). Изречението пада цяло (както при CJK).
# Измерено върху 109 брифа (51 605 български низа): 2 070 низа с такова име, 56 различни имена, всичките полета от входа (най-често near_high, new_high, sizing_factor, rs_status,
# laggard_persistence, rs_4w, rs_12w, pct_of_holdings, insider_cluster); стойностите-кодове без кирилица („existing_position“) не се пипат.
_FIELD_RE = re.compile(r"(?<![\w/.\-@])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w/\-])|\b[a-z][a-z0-9_]*\s*=\s*(?:true|false|null)\b|(?i:\blaggard\s+persistence\b)")
_FIELD_DROPPED: list[dict] = []
_FIELD_SUBBED: list[dict] = []
# 17.11.2026 (пакет 1, т. 3б — решение след стратегическия преглед): ПОЗНАТИТЕ имена на полета → български термин (до 17.11 изречението падаше цяло — 1 464 в историята,
# с полезните факти: ръст на EPS, дата на отчета); изречението пада само при НЕПОЗНАТО име (т. 3в). Речникът — от имената, които моделът е писал в 104-те брифа
# (13.06–16.11): 46 имена, всичките полета от входа. По-дългите / със стойност — първи. Границите — като в _FIELD_RE (URL, тикър с точка, код без кирилица — не се пипат).
_FB, _FA = r"(?<![\w/.\-@])", r"(?![\w/\-])"
_NUM = r"(\d+(?:[.,]\d+)?)"
_FIELD_TERMS = [(re.compile(p, re.I), r) for p, r in (
    (r"\s*\(\s*(?:rs_status\s*[:=]\s*(?:near|new)_high|rs_at_6m_high(?:\s*[:=]\s*true)?)\s*\)", ""),     # скоба, която само повтаря казаното с думи
    (_FB + r"rs_status\s*[:=]\s*near_high" + _FA, "RS линията близо до върха"),
    (_FB + r"rs_status\s*[:=]\s*new_high" + _FA, "RS линията на нов връх"),
    (_FB + r"rs_at_6m_high(?:\s*[:=]\s*true)?" + _FA, "RS на 6-месечен връх"),
    (_FB + r"rs_status" + _FA, "RS линията"),
    (r"\bbreakout[_ ]volume\s*[:=]\s*false\b", "без пробивен обем"),
    (_FB + r"volume_ratio\s*(?:[:=]\s*)?" + _NUM + r"\s*[×xX]?" + r"(?![\w])", r"обем \1× от средния"),
    (_FB + r"volume_ratio" + _FA, "обемът спрямо средния"),
    (_FB + r"breakout_volume(?:\s*[:=]\s*true)?" + _FA, "пробивен обем"),
    (_FB + r"days_to_earnings\s*(?:[:=]\s*)" + _NUM + r"(?![\w])", r"\1 дни до отчета"),
    (_FB + r"days_to_earnings" + _FA, "дните до отчета"),
    (_FB + r"next_earnings" + _FA, "следващият отчет"),
    (_FB + r"in_blackout\s*[:=]\s*true" + _FA, "в прозореца преди отчета"),
    (_FB + r"in_blackout" + _FA, "прозорецът преди отчета"),
    (_FB + r"laggard[_ ]persistence(?:_pct)?\s*(?:[:=]\s*)?" + _NUM + r"\s*%", r"устойчиво изоставане \1%"),
    (_FB + r"laggard[_ ]persistence(?:_pct)?" + _FA, "устойчивото изоставане"),
    (_FB + r"confirmed_laggard" + _FA, "потвърдено изоставащ"),
    (_FB + r"sizing_factor\s*[:=]\s*" + _NUM + r"(?![\w])", r"режимен фактор \1"),
    (_FB + r"sizing_factor" + _FA, "режимният фактор"),
    (_FB + r"base_depth(?:_pct)?\s*(?:[:=]\s*)?" + _NUM + r"\s*%", r"дълбочина на базата \1%"),
    (_FB + r"base_depth(?:_pct)?" + _FA, "дълбочината на базата"),
    (_FB + r"base_type" + _FA, "видът на базата"),
    (_FB + r"level_percentile" + _FA, "перцентилът на нивото"),
    (_FB + r"roc_percentile" + _FA, "перцентилът на промяната"),
    (_FB + r"(?:rs_chg_4w(?:_pct)?|rs_4w)" + _FA, "RS за 4 седмици"),                  # без точка — „седм.“ чупеше изречението на две
    (_FB + r"(?:rs_chg_12w(?:_pct)?|rs_12w)" + _FA, "RS за 12 седмици"),
    (_FB + r"rs_rating" + _FA, "RS рейтинг"),
    (_FB + r"rs_line_pct" + _FA, "RS линията"),
    (_FB + r"avg_recent" + _FA, "скорошното средно"),
    (_FB + r"avg_prior" + _FA, "предишното средно"),
    (_FB + r"delta_1w" + _FA, "седмичната промяна"),
    (_FB + r"analyst_target" + _FA, "целта на анализаторите"),
    (_FB + r"inst_ownership(?:_pct)?" + _FA, "институционалната собственост"),
    (_FB + r"setup_reason" + _FA, "причината за сетъпа"),
    (_FB + r"exit_rule" + _FA, "правилото за изход"),
    (_FB + r"recent_report" + _FA, "скорошният отчет"),
    (_FB + r"sells_25pct_of_stake" + _FA, "групата „продава ≥25% от дела си“"),
    (r"\bleading\s*=\s*true\b", "водещ"),
    (r"\bleading\s*=\s*false\b", "не е водещ"),
    (_FB + r"near_high" + _FA, "близо до върха"),
    (_FB + r"new_high" + _FA, "на нов връх"),
    (_FB + r"below_pivot" + _FA, "под pivot"),
    (_FB + r"too_wide" + _FA, "твърде широк стоп"),
)]


def _sub_known_fields(s: str) -> str:
    """17.11.2026 (т. 3б): познатите имена на полета → българският термин; записва всяка подмяна (_FIELD_SUBBED, лог). Чиста освен записа."""
    for rx, rep in _FIELD_TERMS:
        def _one(m, rep=rep):
            new = m.expand(rep)
            _FIELD_SUBBED.append({"field": m.group(0), "to": new, "sentence": s[max(0, m.start() - 60):m.end() + 60]})
            print(f"[ai] име на поле „{m.group(0)}“ → „{new}“")
            return new
        s = rx.sub(_one, s)
    return s


def fix_field_names(s: str) -> str:
    """17.11.2026 (т. 3б–в): познатите имена на полета → български термин; останалото непознато име → изречението пада. (До 17.11 — само _drop_field_sentences.)"""
    if not _FIELD_RE.search(s or ""):
        return s
    s = _sub_known_fields(s)
    return _drop_field_sentences(s) if _FIELD_RE.search(s) else s


def _drop_field_sentences(s: str) -> str:
    """Изреченията с име на поле падат; абзаците (празен ред) се пазят."""
    paras = []
    for para in re.split(r"\n\s*\n", s):
        kept = []
        for x in _SENT_SPLIT_RE.split(para.strip()):
            names = list(dict.fromkeys(m.group(0) for m in _FIELD_RE.finditer(x)))
            if names:
                print(f"[ai] ⚠ име на поле ({', '.join(names)}) — махнато цялото изречение: «{x[:160]}»")
                _FIELD_DROPPED.append({"fields": names, "sentence": x})
            else:
                kept.append(x)
        if kept:
            paras.append(" ".join(kept))
    return "\n\n".join(paras)


def _drop_cjk_sentences(s: str) -> str:
    kept = []
    for x in _SENT_SPLIT_RE.split(s):
        if _CJK_RE.search(x):
            chars = "".join(_CJK_RE.findall(x))
            print(f"[ai] ⚠ чужди символи '{chars}' — махнато цялото изречение: «{x[:160]}»")
            _CJK_DROPPED.append({"sentence": x, "chars": chars})
        else:
            kept.append(x)
    return " ".join(kept)
# FIX 2026-09-29: руски букви, които ги няма в българския (ы, э, ё) — "по-высоката"
# (Lean Hogs), "по-высоки" (5Y) на 29.09. Измерено върху 74 дни (123 745 низа):
# 10 появи, 8 различни думи (высок-×6, события×2, это, экспанзия), всичките
# руски, 0 фалшиви. Само лог — автоматична замяна не е безопасна ("события").
_RU_ONLY_RE = re.compile(r"[\w\-]*[ЫыЭэЁё][\w\-]*")
# FIX 2026-09-29: несъществуващи кирилски думи с потвърдена замяна. "ускелетира"
# — 2 появи на 29.09 (новините за RTX и AMD), 0 преди това в 74 дни. Списъкът
# расте само с потвърдени случаи, както _TRANSLIT_FIX.
_CYR_WORD_FIX = {"ускелетира": "ускорява", "ускелетират": "ускоряват",
                 # 09.10.2026: несъществуваща дума в две вериги от макро брифа (07.10 «AI capex нарастива», 09.10 «AI capex нарастив преди»); «нарастване» пасва и като съществително, и като глагол във верига «X → Y → Z».
                 # Измерено върху 83 реални бриф-а: само тези две срещания, нито едно легитимно.
                 "нарастив": "нарастване", "нарастива": "нарастване",
                 # 19.10.2026: «Вериган» вместо «Веригата» в две вериги на sector_logic (XLP «Вериган: рязък кредитен стрес → …», GDX «Вериган е неубедителна …»); измерено върху всички
                 # реални брифове: само тези две срещания, нито едно легитимно (формите в брифовете: верига 479, веригата 57, вериги 30, веригите 10).
                 "вериган": "веригата"}
# 09.10.2026: «мултипликатор» счупено на две (09.10: «AI hardware мулти плиера», «мулти-плиер компресия», «мулти-плиера»). Поправя се като ФРАЗА (две думи, поотделно «мулти» и «плиер» не са грешни думи);
# падежът се пази. Другите форми в брифовете («мултипликатор», «мултипли», «мултиплът») са ЦЕЛИ думи и не се пипат — измерено върху 83 реални бриф-а: 3 срещания, всичките на 09.10.
_PHRASE_FIX_RE = re.compile(r"(?<![А-Яа-яЁё])([Мм])улти[ -]плиер(ът|ите|и|а)?(?![А-Яа-яЁё])")


def _fix_broken_phrases(s: str) -> str:
    def repl(m):
        fixed = m.group(1) + "ултипликатор" + (m.group(2) or "")
        print(f"[ai] несъществуваща дума заменена: '{m.group(0)}' → '{fixed}'")
        return fixed
    return _PHRASE_FIX_RE.sub(repl, s)
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
# дума → контекст (първо срещане) за подробния лог на смесените думи
_HYBRID_CTX: dict[str, str] = {}


def _is_pure_cyrillic(word: str) -> bool:
    return bool(word) and all(("А" <= c <= "я" or c in "Ёё") for c in word)


def _fix_homoglyphs(s: str) -> str:
    """
    FIX 2026-10-01 (т.4 от прегледа на 01.10): самотен ASCII буква-двойник
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
        _HYBRID_CTX.setdefault(w, s[max(0, m.start() - 35):m.end() + 25])
        return w
    return _WORD_RE.sub(repl, s)


# 15.10.2026: кратка служебна дума на ЛАТИНИЦА между две изцяло кирилски думи ("да se влошава" на 14.10). Само потвърдените случаи и само с малки букви
# ("SE" е тикър). Измерено върху 87 брифа (13.06–15.10): "se" ×3 (25.06, 24.08, 14.10), всичките грешни; самотното "e" вече се поправя от _fix_homoglyphs.
_LATIN_WORD_FIX = {"se": "се"}


def _fix_latin_words(s: str) -> str:
    def repl(m):
        w = m.group(0)
        fixed = _LATIN_WORD_FIX.get(w)
        if fixed is None:
            return w
        prev = list(_WORD_RE.finditer(s[:m.start()]))
        nxt = _WORD_RE.search(s[m.end():])
        gap_before = s[prev[-1].end():m.start()] if prev else ""
        gap_after = s[m.end():m.end() + nxt.start()] if nxt else ""
        if (prev and nxt and _is_pure_cyrillic(prev[-1].group(0)) and _is_pure_cyrillic(nxt.group(0))
                and gap_before.strip() == "" and gap_after.strip() == ""):
            print(f"[ai] латинска дума заменена: '{w}' → '{fixed}' (между '{prev[-1].group(0)}' и '{nxt.group(0)}')")
            return fixed
        return w
    return re.sub(r"(?<![A-Za-zА-Яа-яЁё])[a-z]{2}(?![A-Za-zА-Яа-яЁё])", repl, s)


_SCRIPT_RUN_RE = re.compile(r"[A-Za-z]+|[А-Яа-яЁё]+")


def _log_mixed_words() -> None:
    """
    FIX 2026-10-02 (т.2 от прегледа на 02.10): думи с латиница И кирилица в
    един токен, които нито една поправка не хваща — "directно", "неpubblично"
    (Cotton direct), "пolicymakers" (news) на 02.10. Едно обобщено ред ("смесено
    писмо ... directно, неpubblично") е лесно да се пропусне; тук всяка дума е
    на отделен ред с контекст, формата на смесването и какво би дало
    auto-space. САМО лог — автоматична поправка не е безопасна: "direct но" е безсмислено
    ("directно" = "direct" + "но"), а при кир+лат+кир ("неpubblично") няма
    единствено валидно разделяне.
    Измерено върху историята: ~2.3 различни смесени думи на ден (макс 10).
    """
    for w in dict.fromkeys(_HYBRIDS):
        if len(w) < 2 or w not in _HYBRID_CTX:
            continue  # едносимволните си имат отделен лог/поправка
        runs = [(("лат" if r[0].isascii() else "кир"), r) for r in _SCRIPT_RUN_RE.findall(w)]
        if len(runs) < 2:
            continue
        shape = "+".join(f"{k}«{r}»" for k, r in runs)
        spaced = " ".join(r for _, r in runs)
        print(f"[ai] ⚠ смесена дума '{w}' ({shape}) — auto-space би дал '{spaced}', "
              f"не е безопасен, не се пипа — «…{_HYBRID_CTX[w]}…»")


# FIX 2026-10-01 (т.4 от прегледа на 01.10): "по-ата" (01.10, 2Y Treasury теза)
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


# FIX 2026-10-05: soft hyphen (U+00AD) — невидим символ, който моделът понякога вмъква в дума ("ви­соки" в cross тезата на 05.10); в
# търсене/копиране чупи думата. Премахва се безусловно. Измерено върху историята: 1 поява (05.10) — безопасно, няма легитимна употреба.
_SOFT_HYPHEN = "\u00ad"
# FIX 2026-10-05: дефекти, видени на 05.10, които се ЛОГВАТ поименно (без автоматична замяна — списъкът с замени расте само с потвърдени
# безопасни случаи): "marginalen" (латинска транслитерация на "маргинален", не се хваща от шаблона и не е в речника) и "expозиция" (смесено
# писмо — x→"кс", затова буквената замяна би дала "ехрозиция"; 19 появи в историята, 2 от тях на 05.10). Думата → правилната форма.
_KNOWN_DEFECTS = {"marginalen": "маргинален", "expозиция": "експозиция"}


def _log_known_defects(s: str) -> None:
    for w, good in _KNOWN_DEFECTS.items():
        for m in re.finditer(r"(?<![A-Za-zА-Яа-яЁё])" + re.escape(w) + r"(?![A-Za-zА-Яа-яЁё])", s, re.I):
            print(f"[ai] ⚠ известен езиков дефект '{m.group(0)}' (трябва '{good}') — само лог, текстът не се пипа — "
                  f"«…{s[max(0, m.start() - 35):m.end() + 25]}…»")


# 20.10.2026 (етап 3, т. 4): позоваване на позиция в промпта — "(новина 1)" във веригата на XLE (20.10; новините се подават като JSON без номера, моделът ги брои сам).
# За читателя няма "новина 1" → скобата се маха. В историята (90 брифа, всички AI текстове): 1 случай.
_PROMPT_REF_RE = re.compile(r"\s*\((?:новина|новини|news)\s*№?\s*\d+(?:\s*(?:,|и|-|–)\s*\d+)*\)", re.I)


def _strip_prompt_refs(s: str) -> str:
    if not _PROMPT_REF_RE.search(s):
        return s
    for m in _PROMPT_REF_RE.finditer(s):
        print(f"[ai] махнато позоваване на промпта '{m.group(0).strip()}' — «…{s[max(0, m.start() - 40):m.end() + 10]}…»")
    return _PROMPT_REF_RE.sub("", s)


def _fix_translit(obj):
    """
    Обхожда всички низове в парснатия JSON (всички AI отговори минават през
    _parse_json): премахва CJK символи и soft hyphen, заменя букви-двойници и
    познатите транслитерации, логва новите, хибридите и известните дефекти.
    """
    if isinstance(obj, dict):
        return {k: _fix_translit(v) for k, v in obj.items()}
    if isinstance(obj, list):
        out = [_fix_translit(v) for v in obj]
        return [x for v, x in zip(obj, out) if not (x == "" and isinstance(v, str) and (_CJK_RE.search(v) or _FIELD_RE.search(v)))]      # 29.10.2026: елемент само от изречение с CJK (16.11 — или с име на поле) пада
    if not isinstance(obj, str):
        return obj
    if _SOFT_HYPHEN in obj:
        n = obj.count(_SOFT_HYPHEN)
        i = obj.index(_SOFT_HYPHEN)
        print(f"[ai] премахнат soft hyphen (U+00AD) ×{n} — «…{obj[max(0, i - 25):i + 25].replace(_SOFT_HYPHEN, '·')}…»")
        obj = obj.replace(_SOFT_HYPHEN, "")
    obj = _strip_prompt_refs(obj)                 # 20.10.2026 (етап 3, т. 4): "(новина 1)"
    obj = _fix_latin_prefix(obj)                  # 08.10: ПРЕДИ лога на известните дефекти и буквите-двойници — иначе поправена дума ("expозиция") пак се води като неподправена хибридна
    _log_known_defects(obj)
    if _CJK_RE.search(obj):
        obj = _drop_cjk_sentences(obj)                # 29.10.2026: цялото изречение, не само символите
        if not obj:
            return obj
    for m in _RU_ONLY_RE.finditer(obj):
        print(f"[ai] ⚠ руска буква (ы/э/ё) в '{m.group(0)}' — "
              f"«…{obj[max(0, m.start() - 40):m.end() + 20]}…»")
    if not re.search(r"[А-Яа-я]", obj):
        return obj  # чисто латински низ (тикър, английско заглавие) — не е наш случай
    if _FIELD_RE.search(obj):                     # 16.11.2026 (т. 3): име на поле в български текст; 17.11.2026 (т. 3б–в): познатото — подменено, непознатото — изречението пада
        obj = fix_field_names(obj)
        if not obj:
            return obj
    _check_po_suffix(obj)
    obj = _fix_homoglyphs(obj)
    obj = _fix_latin_words(obj)                   # 15.10: "да se влошава" → "да се влошава"
    obj = _fix_glued(obj)
    obj = _fix_broken_phrases(obj)                # 09.10: «мулти плиер» → «мултипликатор» (фраза от две думи — преди проверката по отделни думи)
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
    obj = _TRANSLIT_RE.sub(repl, obj)
    return _fix_mixed_script(obj)                 # 17.11.2026 (пакет 1, т. 7): смесени букви в една дума — поправка или изречението пада


# 17.11.2026 (пакет 1, т. 7): дума със смесени латински и кирилски букви („Zад цифрите“, разказът от 17.11). Латинските букви → кирилица буква по буква; ако така
# се получава позната дума от корпуса (_bg_vocab, ≥ 2 срещания) — поправка („Zад“ → „Зад“, „секторa“ → „сектора“, „Fед“ → „Фед“); иначе изречението пада (хибрид
# като „benefitва“, „Setupът“). Измерено върху AI текстовете на брифовете 13.06–17.11: 92 смесени думи (67 различни) — 33 различни се поправят, 34 — изречението пада;
# след 10.10 — 5 (последната е „Zад“ на 17.11). Махнатите — MIXED_DROPS → brief["ai_mixed_drops"].
_MIXED_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё]+")
MIXED_DROPS: list[dict] = []


def _fix_mixed_script(s: str) -> str:
    if not (re.search(r"[A-Za-z]", s) and re.search(r"[А-Яа-яЁё]", s)):
        return s
    cyr = _bg_vocab()[0]
    if not cyr:                                   # без речник от историята — не може да се прецени; само логът за смесени думи (както до 17.11)
        return s
    bad: list[str] = []

    def repl(m):
        w = m.group(0)
        if not (re.search(r"[A-Za-z]", w) and re.search(r"[А-Яа-яЁё]", w)):
            return w
        parts = [(_translit_prefix(ch) if "a" <= ch.lower() <= "z" else ch) for ch in w]
        t = "".join(p for p in parts if p) if all(parts) else None
        if t and cyr.get(t.lower(), 0) >= 2:
            print(f"[ai] смесени букви в дума поправени: '{w}' → '{t}'")
            return t
        bad.append(w)
        return w
    s = _MIXED_TOKEN.sub(repl, s)
    if not bad:
        return s
    paras = []
    for para in re.split(r"\n\s*\n", s):
        kept = []
        for x in _SENT_SPLIT_RE.split(para.strip()):
            hit = [b for b in bad if re.search(rf"(?<![A-Za-zА-Яа-яЁё]){re.escape(b)}(?![A-Za-zА-Яа-яЁё])", x)]
            if hit:
                print(f"[ai] ⚠ смесени букви ({', '.join(hit)}) — махнато цялото изречение: «{x[:160]}»")
                MIXED_DROPS.append({"words": hit, "sentence": x})
            else:
                kept.append(x)
        if kept:
            paras.append(" ".join(kept))
    return "\n\n".join(paras)


# FIX 2026-09-30: речник от предишните брифове (docs/data/*.json, вече в
# checkout-а на Actions) — за слепените думи и за латиница вместо кирилица.
# Липсва/гръмне ли → празен речник и двете проверки просто не правят нищо.
_GLUED_RE = re.compile(r"(?<![A-Za-zА-Яа-я])([A-Za-z]{4,})([а-я]{5,})(?![A-Za-zА-Яа-я])")
_BG_TRANSLIT = ([("sht", "щ"), ("zh", "ж"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"),
                 ("yu", "ю"), ("ya", "я")]
                + list(zip("abvgdeziyklmnoprstufhc", "абвгдезийклмнопрстуфхк")))


@lru_cache(maxsize=1)
def _bg_vocab() -> tuple[dict, dict]:
    """(кирилска дума → брой, латинска дума → брой) в българските текстове. config.BG_VOCAB_FILE (тестовете) — готовият речник от файл вместо docs/data/."""
    from collections import Counter
    cyr, lat = Counter(), Counter()
    try:
        if getattr(config, "BG_VOCAB_FILE", ""):
            d = json.loads(pathlib.Path(config.BG_VOCAB_FILE).read_text(encoding="utf-8"))
            return dict(d["cyr"]), dict(d["lat"])
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


# 08.10.2026 (език): латинска ПРИСТАВКА (1–3 букви) пред кирилска дума — "Verижната" (= "Верижната"), "natиск", "rotацията", "katализатор", "sedмичен", "umерено", "verига". Моделът започва думата с
# латиница и продължава с кирилица. Безопасно е само ако транслитерираната приставка + кирилската част дава ЦЯЛА дума, която е в речника на историята поне 3 пъти (като _fix_glued). Мерено
# върху цялата история (107 различни хибридни думи, 322 появи): 17 думи отговарят на условието и всичките 17 са правилни поправки; думите с английска основа ("benefitват" — приставка 7 букви,
# "момentum" — кирилицата е отпред) не отговарят на шаблона и остават само в лога.
_LAT_PREFIX_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё])([A-Za-z]{1,3})([А-Яа-я]{3,})(?![A-Za-zА-Яа-яЁё])")
_LAT_TO_CYR = {**dict(zip("abvgdeziyklmnoprstufhc", "абвгдезийклмнопрстуфхц")), "c": "к", "j": "й", "w": "в", "q": "к"}


def _translit_prefix(lat: str) -> str | None:
    """Латинска приставка → кирилица буква по буква (x → "кс"); None, ако има буква без съответствие."""
    out = ""
    for ch in lat:
        low = ch.lower()
        c = "кс" if low == "x" else _LAT_TO_CYR.get(low)
        if c is None:
            return None
        out += c.upper() if (ch.isupper() and not out) else c
    return out


def _fix_latin_prefix(s: str) -> str:
    cyr = _bg_vocab()[0]
    if not cyr:
        return s

    def repl(m):
        t = _translit_prefix(m.group(1))
        if t is None:
            return m.group(0)
        whole = t + m.group(2)
        if cyr.get(whole.lower(), 0) < 3:
            return m.group(0)
        fixed = whole if m.group(1)[0].isupper() else whole.lower()
        print(f"[ai] латинска приставка пред кирилица заменена: '{m.group(0)}' → '{fixed}'")
        return fixed
    return _LAT_PREFIX_RE.sub(repl, s)


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


# 29.10.2026: цитат в текста, затворен с ASCII кавичка („не би било грешка" в макро текста на 29.10), чупи JSON-а и json_repair реже низа там — правилото е в двата промпта
# с най-много проза; проверката и повторният опит са в _parse_json (repair_cuts).
QUOTES_RULE = (" Цитат в текста — само с български кавички „…“ (затварящата е “); ASCII кавичка \" вътре в JSON низ затваря низа и чупи JSON-а.")

SYSTEM_MACRO = """Ти си макро аналитик, който пише за опитен суинг търговец \
(8+ години, познава Weinstein, CANSLIM, GMMA, RS Line, GLB). Системата е \
оперативна, не образователна — без дефиниции на базови понятия, без hedging \
фрази. Пишеш на български, тикерите и техническите термини остават на английски. \
Връщаш САМО валиден JSON, без markdown огради, без преамбюл.""" + QUOTES_RULE


def _macro_brief_fallback(thermometer: dict) -> dict:
    """
    Ниво 2 (FIX 2026-08-17) — минимален fallback, ако и Ниво 0 (json_repair),
    и Ниво 1 (smart retry) се провалят. Суровите данни (термометър режим) без
    AI наратив, explicit label в самия macro_brief текст (директно видим в
    dashboard-ната "Макро бриф" секция, без нужда от template промяна) — за
    да продължи останалата част от брифа (screening, sizing, render) напълно
    нормално, вместо целият pipeline да се събори заради един AI hiccup.
    """
    return {
        "macro_brief": ("⚠ AI синтез неуспешен днес — Claude върна невалиден JSON "
                        "и след автоматична поправка, и след retry. Показваме "
                        "суровите данни от термометъра/скрийнъра без AI наратив."),
        "sector_logic": [],
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
месечна серия, излиза с ~6 седмици закъснение — в края на следващия месец, НЕ днешни данни; \
информативна): {json.dumps(ci, ensure_ascii=False, default=str)}

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
инфлация. 30.10.2026: за инфлацията пиши САМО заедно с базовия PCE ("pce_core" в МАКРО — \
годишно изменение, месец, "direction" up = ускорява / down = забавя спрямо предишния месец): \
двете мерки заедно, всяка с месеца си, или изобщо не.
"""


def _credit_roc_note(thermometer: dict) -> str:
    """12.10.2026: посоката на IEI/HYG RoC е от кода (thermometer._evaluate_credit_spread → roc_trend_text). Потвърден случай 12.10: веригата за XLV казваше
    "ускоряваща се RoC (84.3-ти percentile)", а RoC беше +0.41% срещу +1.03% преди 5 сесии — percentile-ът е ниво, не посока."""
    for ind in (thermometer or {}).get("indicators") or []:
        if str(ind.get("name", "")).startswith("IEI/HYG") and ind.get("roc_trend_text"):
            return ("\nВАЖНО за IEI/HYG: посоката на RoC е от кода — " + ind["roc_trend_text"] + ". Ако пишеш за посоката на RoC (ускорява се / забавя се), "
                    "ползвай САМО това; \"roc_percentile\" е колко висока е RoC спрямо историята си, не дали расте.")
    return ""


def _rotation_unavailable_note(rotation: list[dict] | None) -> str:
    """Пакет 2 т.6: празна ротация = данните не са изтеглени (паднал Yahoo), не "няма водещи сектори"."""
    if rotation:
        return ""
    return ('\nСЕКТОРНИТЕ ДАННИ НЕ СА НАЛИЧНИ днес (Yahoo Finance не върна ценови данни) — НЕ измисляй водещи сектори, '
            'RS стойности или ETF-и; кажи в macro_brief, че ротацията не е изчислена.')                # 30.10.2026 (т. 7): без веригите (sector_logic)


def _news_block(news: list[dict] | None) -> str:
    """Блок за макро промпта: курираните значими новини със "защо са значими" (пакет 2 т.4)."""
    items = [{"headline": n.get("headline", ""), "why": n.get("why", "")} for n in (news or []) if n.get("headline")]
    if not items:
        return ('ЗНАЧИМИ НОВИНИ ЗА ДЕНЯ: няма подбрани новини — не твърди нищо за новинарския фон и не '
                'измисляй новини.\n')
    return (f"ЗНАЧИМИ НОВИНИ ЗА ДЕНЯ (подбрани от кода: заглавие и защо е значима): "
            f"{json.dumps(items, ensure_ascii=False)}\n"
            "Свържи макро брифа с тези новини там, където реално са свързани с данните по-горе (термометър, "
            "доходности, суровини, сектори); цитирай същността им, но НЕ измисляй други новини и не твърди "
            "факти, които не са в заглавието или в \"why\".\n")


def market_day_block(day: dict | None) -> str:
    """06.11.2026 (пакет 05–06.11, т. 8): денят на пазара от кода за промпта — индексите, всичките 11 сектора и спадът от върха. Без данни → "". Чиста функция."""
    d = day or {}
    ix, sec = d.get("indexes") or {}, d.get("sectors") or []
    if not (ix or sec):
        return ""
    names = config.MARKET_DAY_INDEXES
    lines = [f"ДЕНЯТ НА ПАЗАРА (от кода, последната сесия{' — ' + d['as_of'] if d.get('as_of') else ''}):"]
    if ix:
        lines.append("Индексите за деня: " + " · ".join(f"{names.get(k, k)} {v['chg_1d_pct']:+.2f}%" for k, v in ix.items()))
        lines.append("Спад от 52-седмичния връх (по затварянията): " + " · ".join(f"{k} {v['from_high_pct']:+.2f}%" for k, v in ix.items()))
    if sec:
        lines.append(f"Секторите за деня (надолу {d.get('down')} от {d.get('total')}): " + " · ".join(f"{x['etf']} {x['sector']} {x['chg_1d_pct']:+.2f}%" for x in sec))
    return "\n".join(lines) + "\n"


# 06.11.2026 (пакет 05–06.11, т. 8): думите без опора в числата. Реално, 06.11: „Nikkei 225 влезе в мечи пазар“ — без нито едно число във входа (идваше от „why“ на новина, писано от модела).
# Твърдение е само утвърденото: „не е нормална корекция“, „риск от корекция“, „следващата корекция“ не твърдят състояние и не се пипат.
_TERM_BEAR = re.compile(r"меч\w*\s+(?:пазар|тренд|територи)\w*|bear\s+market", re.I)
_TERM_CORR = re.compile(r"корекци\w*|correction", re.I)
_TERM_REC = re.compile(r"рекорд\w*|record[- ]high|all[- ]time\s+high|\bATH\b|историческ\w+\s+(?:връх|максимум|дъно|минимум)", re.I)
_TERM_NOT_CLAIM = re.compile(r"(?:\b(?:не|без|няма)\s+(?:(?:е|са|в|е\s+в)\s+)?(?:\w+\s+){0,2}|\b(?:риск\w*\s+от|следващ\w*|евентуал\w*|възможн\w*|потенциал\w*|бъдещ\w*)\s+(?:\w+\s+){0,3})$", re.I)
_TERM_INDEX = {"SPY": re.compile(r"\bSPY\b|S&P|\bпазар(?:ът|а)\b", re.I), "QQQ": re.compile(r"\bQQQ\b|Nasdaq|Насдак|\bNDX\b", re.I), "IWM": re.compile(r"\bIWM\b|Russell|Ръсел", re.I), "RSP": re.compile(r"\bRSP\b")}
_TERM_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
# думата „рекорд“ в дословен източник: „Copper jumps to its highest level ever“ е рекорд, „highest since March 2021“ и „biggest since 2010“ — не (реално: „Рекордният дефицит“ 13.08, „Рекордното IPO“ 27.07)
_TERM_REC_SRC = re.compile(r"\brecord|all[- ]time|highest\s+(?:\w+\s+){0,3}(?:ever|for\s+any)|рекорд", re.I)
_TERM_NARROW = re.compile(r"концентрир\w*|(?:\bне\s+(?:е\s+)?|\bа\s+не\s+|\bне)системн\w*", re.I)
# 16.11.2026 (пакет 16.11, т. 2): Put/Call — изречението е от кода (thermometer.put_call_sentence, под разказа); AI изречение за P/C пада. В историята: 14 изречения в 109 разказа,
# част с обърнат смисъл (16.11 „7-ми перцентил … ниско самодоволство“; 18.09 „P/C 0.87 е жълт (леко повишена предпазливост)“).
_TERM_PC = re.compile(r"put\s*/\s*call|\bP/C\b|пут\s*/\s*кол", re.I)


def _term_support(sent: str, kind: str, vals: list[float], day: dict | None, headlines: str) -> bool:
    """Има ли опора думата в изречението: индекс от изречението със спад от върха до прага, процент до прага в самото изречение (подкрепен от входа); за „рекорд“ — и заглавие с думата или число от входа в изречението."""
    from src import news_aggregator as na
    ix = (day or {}).get("indexes") or {}
    named = [v for k, v in ix.items() if _TERM_INDEX[k].search(sent)]
    if kind == "rec":
        if any(abs(v["from_high_pct"]) <= config.TERM_RECORD_NEAR_PCT for v in named) or _TERM_REC_SRC.search(headlines):
            return True
        toks = na._NUM_RE.findall(na._WHY_NAME.sub(" ", _THOUSANDS.sub("", sent)))
        return any(_supported(t, vals) for t in toks)
    limit = config.TERM_BEAR_MARKET_PCT if kind == "bear" else config.TERM_CORRECTION_PCT
    if any(abs(v["from_high_pct"]) >= limit for v in named):
        return True
    for tok in _TERM_PCT.findall(sent):
        v = _num_value(tok)
        if v and v[0] >= limit and _supported(tok, vals):
            return True
    return False


def check_market_terms(text: str, vals: list[float], day: dict | None = None, news: list | None = None, narrow: bool = True) -> tuple[str, list[dict]]:
    """
    06.11.2026 (т. 8): разказът → (поправеният текст, [{sentence, term, why}]). „Мечи пазар“ / „корекция“ / „рекорд“ без опора в числата и „концентрирано / не системно“ при широка разпродажба — цялото изречение пада,
    както при числата без опора (check_narrative_numbers минава първа). narrow=False — без проверката за „концентрирано“ (в „защо“ на новините думата е за друго: „портфолиата с концентрирана tech експозиция“). Чиста функция.
    """
    from src import news_aggregator as na
    fixed = []
    headlines = " ".join(str(n.get("headline") or "") for n in news or [] if isinstance(n, dict))

    def problem(sent: str) -> dict | None:
        if _TERM_PC.search(sent):                                               # 16.11.2026 (т. 2): Put/Call — от кода
            return {"term": _TERM_PC.search(sent).group(0), "why": "Put/Call се пише от кода (плочката и редът под разказа), не от AI"}
        if narrow and (day or {}).get("selloff") and _TERM_NARROW.search(sent):
            return {"term": _TERM_NARROW.search(sent).group(0), "why": f"широка разпродажба: надолу {(day or {}).get('down')} от {(day or {}).get('total')} сектора"}
        for kind, rx, label in (("bear", _TERM_BEAR, f"спад от върха ≥ {config.TERM_BEAR_MARKET_PCT:g}%"), ("corr", _TERM_CORR, f"спад от върха ≥ {config.TERM_CORRECTION_PCT:g}%"), ("rec", _TERM_REC, "число или заглавие")):
            for m in rx.finditer(sent):
                if _TERM_NOT_CLAIM.search(sent[:m.start()]):
                    continue
                if not _term_support(sent, kind, vals, day, headlines):
                    return {"term": m.group(0), "why": f"няма опора във входа ({label})"}
        return None

    def one(para: str):
        kept = []
        for sent in na._WHY_SENT.split(para):
            pr = problem(sent)
            if pr:
                fixed.append({"sentence": sent, **pr})
            else:
                kept.append(sent)
        return " ".join(kept), []
    out, _ = _per_paragraph(text, one)
    return out, fixed


def check_news_why_terms(news: list[dict] | None, day: dict | None = None) -> list[dict]:
    """
    06.11.2026 (пакет 05–06.11, т. 8, решение след прегледа): същата проверка за думите и в „защо“ на значимите новини — оттам „Nikkei 225 влезе в мечи пазар“ стигна и до разказа, затова минава ПРЕДИ макро брифа.
    Опора: индекс от изречението със спад от върха до прага; процент до прага в изречението (числата в „защо“ вече са сверени с източника — news_aggregator._why_numbers); „рекорд“ — и думата в заглавието или резюмето на самата новина.
    Без опора — изречението пада; празно „защо“ остава празно, заглавието стои. Мутира news; връща [{headline, sentence, term, why}]. Graceful: грешка на ред не пипа реда.
    """
    from src import news_aggregator as na
    fixed = []
    for n in news or []:
        why = n.get("why") if isinstance(n, dict) else None
        if not isinstance(why, str) or not why:
            continue
        try:
            titles = [n] + [x for x in n.get("also") or [] if isinstance(x, dict)]
            source = str(n.pop("source_text", "") or "")                       # заглавията и резюметата от пула — само за тази проверка, не влизат в брифа
            own = " ".join([str(x.get("headline") or x.get("title") or "") for x in titles] + [source, why])
            vals = [abs(v[0]) for v in (_num_value(t) for t in na._NUM_RE.findall(_THOUSANDS.sub("", own))) if v]
            new, f = check_market_terms(why, vals, day, [{"headline": str(x.get("headline") or x.get("title") or "")} for x in titles] + [{"headline": source}], narrow=False)
        except Exception as e:
            print(f"[ai] „защо“ на новина: проверката на думите пропусната: {type(e).__name__}: {e}")
            continue
        if f:
            n["why"] = new
            fixed += [{"headline": n.get("headline"), **x} for x in f]
            for x in f:
                print(f"[ai] „защо“ на новина: „{x['term']}“ — {x['why']}; махнато: «{x['sentence'][:120]}»")
    return fixed


def cap_sentences(text: str, n: int) -> tuple[str, list[str]]:
    """
    17.11.2026 (пакет 1, т. 2б): разказът — най-много n изречения; над тях се махат средните, а изречението „За нас:“ (последното по правило) остава. Връща (текст, махнатите).
    При рязане абзаците се сливат в един (разказът е един абзац). Чиста функция.
    """
    sents = [x for x in _SENT_SPLIT_RE.split(re.sub(r"\s*\n\s*\n\s*", " ", text or "").strip()) if x]
    if len(sents) <= n:
        return text, []                                                       # до n изречения — непроменено (и абзаците)
    us = next((k for k in range(len(sents) - 1, -1, -1) if sents[k].startswith("За нас:")), None)
    keep = sents[:n - 1] + [sents[us]] if us is not None and us >= n - 1 else sents[:n]
    return " ".join(keep), [x for x in sents if x not in keep]


def macro_and_sector_brief(macro: dict, rotation: list[dict],
                           thermometer: dict, news: list[dict] | None = None, crypto: dict | None = None, social: dict | None = None, day: dict | None = None) -> dict:
    """
    AI макро бриф. 29.10.2026 (разходката, т. 5): "macro_brief" е разказ в 2–3 абзаца (разделени с празен ред) — какво стана през нощта и как се свързват нещата; абзацът
    за режима (regime_comment) и проверките, които бяха само за него (regime_claims.clean: броене, правило, distribution days, кредитен стрес), са махнати — режимът е в
    термометъра, от кода. Остават общите: изтеклите клаузи-проверки (regime_claims.strip_meta) — по абзаци, за да не се слеят; 30.10.2026 (т. 7): без веригите по сектори
    и без проверките на секторните твърдения (sector_claims — в историята са сработвали 4 пъти, всичките във веригите);
    отрязването + повторният опит и чуждите символи са в _parse_json / _fix_text. Graceful: грешка в проверка връща отговора на модела непроменен.
    """
    out = _macro_and_sector_brief_ai(macro, rotation, thermometer, news, crypto, social, day)
    try:
        out = _apply_meta_check(out)
    except Exception as e:
        print(f"[ai] проверката за изтекли клаузи пропусната: {type(e).__name__}: {e}")
    try:                                                                         # 30.10.2026 (поправки от брифа, т. 4): числата в разказа — срещу входовете
        if isinstance(out, dict) and not out.get("ai_synthesis_failed") and isinstance(out.get("macro_brief"), str) and out["macro_brief"]:
            vals = narrative_sources(macro, rotation, thermometer, news, crypto, social, day=day)
            new, fixed = check_narrative_numbers(out["macro_brief"], vals, narrative_dates(macro, rotation, thermometer, news, crypto, social, day=day))         # 04.11.2026 (С4): датите от входа
            if fixed:
                out = {**out, "macro_brief": new, "numbers_fixed": fixed}
                for f in fixed:
                    print(f"[ai] разказ: число без опора във входовете — махнато {f['removed']}: «{f['sentence'][:120]}»")
    except Exception as e:
        print(f"[ai] проверката на числата в разказа пропусната: {type(e).__name__}: {e}")
    try:                                                                         # 06.11.2026 (пакет 05–06.11, т. 8): думите „мечи пазар“, „корекция“, „рекорд“, „концентрирано“
        if isinstance(out, dict) and not out.get("ai_synthesis_failed") and isinstance(out.get("macro_brief"), str) and out["macro_brief"]:
            new, tf = check_market_terms(out["macro_brief"], narrative_sources(macro, rotation, thermometer, news, crypto, social, day=day), day, news)
            if tf:
                out = {**out, "macro_brief": new, "terms_fixed": tf}
                for f in tf:
                    print(f"[ai] разказ: „{f['term']}“ — {f['why']}; махнато: «{f['sentence'][:120]}»")
    except Exception as e:
        print(f"[ai] проверката на думите в разказа пропусната: {type(e).__name__}: {e}")
    try:                                                                         # 16.11.2026 (пакет 16.11, т. 1): твърдение (институция, държава, мярка) без опора във входа
        if isinstance(out, dict) and not out.get("ai_synthesis_failed") and isinstance(out.get("macro_brief"), str) and out["macro_brief"]:
            from src import claim_check
            new, cf = claim_check.check(out["macro_brief"], narrative_text(macro, rotation, thermometer, news, crypto, social, day=day))
            if cf:
                out = {**out, "macro_brief": new, "claims_fixed": cf}
                for f in cf:
                    print(f"[ai] разказ: твърдение без опора във входа ({', '.join(f['claims'])}) — махнато: «{f['sentence'][:120]}»")
    except Exception as e:
        print(f"[ai] проверката на твърденията в разказа пропусната: {type(e).__name__}: {e}")
    try:                                                                         # 17.11.2026 (пакет 1, т. 2б): най-много MACRO_MAX_SENTENCES изречения — след проверките
        if isinstance(out, dict) and not out.get("ai_synthesis_failed") and isinstance(out.get("macro_brief"), str) and out["macro_brief"]:
            new, cut = cap_sentences(out["macro_brief"], config.MACRO_MAX_SENTENCES)
            out = {**out, "macro_brief": new}
            if cut:
                out["sentences_capped"] = cut
                print(f"[ai] разказ: над {config.MACRO_MAX_SENTENCES} изречения — махнати {len(cut)}: «{cut[0][:100]}»…")
    except Exception as e:
        print(f"[ai] таванът на изреченията в разказа пропуснат: {type(e).__name__}: {e}")
    return out


def narrative_text(macro: dict | None, rotation: list | None, thermometer: dict | None, news: list | None = None, crypto: dict | None = None,
                   social: dict | None = None, day: dict | None = None) -> str:
    """
    16.11.2026 (т. 1): ТЕКСТЪТ на входовете на разказа — опората за claim_check: стойностите от данните, новините (заглавие, „защо“, „също“), крипто. Без инструкциите на промпта.
    Чиста функция.
    """
    parts: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            parts.append(o)
    for x in (macro or {}, rotation or [], _thermo_context(thermometer), social or {}, day or {}):
        walk(x)
    for n in news or []:
        if isinstance(n, dict):
            parts += [str(n.get(k) or "") for k in ("headline", "headline_bg", "why", "summary")] + [str(a.get("headline") or "") for a in n.get("also") or [] if isinstance(a, dict)]
    for x in (crypto or {}).get("items") or []:
        if isinstance(x, dict):
            parts += [str(x.get(k) or "") for k in ("headline", "why")]
    return " ".join(parts)


# ──────────────────────────────────────────────────────────────────────────
# 30.10.2026 (поправки от брифа, т. 4): всяко число в разказа трябва да го има във входовете на деня (новини, уреди, макро / фючърси, ротация, крипто) с разумна точност —
# иначе частта с него се маха (news_aggregator._why_trim_sentence — същата машинария като за "why" в новините), а при нечетим остатък — цялото изречение; запис в
# ai_macro["numbers_fixed"]. „Разумна точност“: числото в текста съвпада с входно число, закръглено до толкова знака, колкото има в текста (17.2 ← 17.21; 13 ← 12.9),
# без знак (−13 пункта ↔ "падна с 13 пункта"); "1,016" с три цифри след запетаята е хиляди.
# ──────────────────────────────────────────────────────────────────────────
def _num_value(tok: str) -> tuple[float, int] | None:
    """Число от текста → (стойност, брой знаци след десетичния разделител); "1,016" → (1016, 0); "2,26" → (2.26, 2)."""
    t = tok.strip()
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", t):
        return float(t.replace(",", "")), 0
    t = t.replace(",", ".")
    try:
        return float(t), (len(t.split(".")[1]) if "." in t else 0)
    except ValueError:
        return None


_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_ISO_DATE = re.compile(r"\b(\d{4})-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)?)?\b")


def narrative_sources(macro: dict | None, rotation: list | None, thermometer: dict | None, news: list | None = None, crypto: dict | None = None,
                      social: dict | None = None, thermo_full: bool = False, day: dict | None = None) -> list[float]:
    """
    Всички числа във входовете на разказа (данните, не инструкциите на промпта) — стойности без знак. thermo_full — целият JSON на термометъра (така, както го виждаше
    промптът до 29.10 — за мерене върху старите текстове); по подразбиране — контекстът на новия промпт (_thermo_context).
    """
    from src import news_aggregator as na
    th = thermometer or {} if thermo_full else _thermo_context(thermometer)
    parts = []

    def walk(o):                                                                 # само стойностите — имената на полетата ("rs_chg_12w_pct") не са числа от данните
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, bool) or o is None:
            return
        elif isinstance(o, (int, float)):
            parts.append(repr(o))
        else:
            parts.append(_ISO_DATE.sub(lambda m: m.group(1), str(o)))            # от датата остава годината: денят и месецът не са твърдения
    for x in (macro or {}, rotation or [], th, social or {}, day or {}):        # 06.11.2026 (т. 8): + денят на пазара
        walk(x)
    parts += [" ".join(str(n.get(k) or "") for k in ("headline", "why", "summary")) for n in news or [] if isinstance(n, dict)]
    c = crypto or {}
    parts += [" ".join(str(x.get(k) or "") for k in ("headline", "why")) for x in c.get("items") or [] if isinstance(x, dict)]
    parts.append(json.dumps(c.get("tickers") or [], ensure_ascii=False))
    vals = []
    for tok in na._NUM_RE.findall(_THOUSANDS.sub("", " ".join(parts))):
        v = _num_value(tok)
        if v:
            vals.append(abs(v[0]))
    return vals


_BG_MONTH = {"януари": 1, "февруари": 2, "март": 3, "април": 4, "май": 5, "юни": 6, "юли": 7, "август": 8, "септември": 9, "октомври": 10, "ноември": 11, "декември": 12}
# 04.11.2026 (четвърти преглед, С4): дата с името на месеца в разказа („към 28 октомври“, „на 3 ноември 2026 г.“) — с предлога пред нея
_DATE_BG = re.compile(r"(?P<prep>\s*\b(?:към|на|от|до|след|преди|около)\s+)?\b(?P<d>\d{1,2})\s+(?P<m>" + "|".join(_BG_MONTH) + r")\b(?:\s+(?P<y>\d{4})(?:\s*г\.)?)?", re.I)


def narrative_dates(macro: dict | None, rotation: list | None, thermometer: dict | None, news: list | None = None, crypto: dict | None = None,
                    social: dict | None = None, day: dict | None = None) -> set[tuple[int, int]]:
    """
    04.11.2026 (четвърти преглед, С4): датите (ден, месец) от ISO датите във входовете на разказа (as_of на уредите, макрото, ротацията …). narrative_sources оставя от датата само
    годината — затова на 03.11 „към 28 октомври“ (Net Liquidity, as_of 2026-10-28 — вярно) беше махнато като число без опора и остана „към —“. Чиста функция.
    """
    out: set[tuple[int, int]] = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            for m in re.finditer(r"\b\d{4}-(\d{2})-(\d{2})\b", o):
                out.add((int(m.group(2)), int(m.group(1))))
    for x in (macro or {}, rotation or [], _thermo_context(thermometer), thermometer or {}, social or {}, news or [], (crypto or {}).get("items") or [], day or {}):
        walk(x)
    return out


def _mask_dates(sent: str, dates: set | None) -> tuple[str, list[str], list[str]]:
    """
    04.11.2026 (С4): датите с името на месеца → (изречението с маски за датите от входа, маските, махнатите дати без опора — заедно с предлога). Чиста функция.
    Дата от входа не е число за проверка; дата без опора пада цялата („ към 27 октомври“), не само числото — иначе остава „към —“.
    """
    if dates is None:
        return sent, [], []
    masks, removed = [], []

    def repl(m):
        d, mo = int(m.group("d")), _BG_MONTH[m.group("m").lower()]
        if (d, mo) in dates:
            masks.append(m.group(0))
            return f"\x01{'abcdefghijklmnopqrstuvwxyz'[(len(masks) - 1) % 26]}\x01"
        removed.append(m.group(0).strip())
        return ""
    return _DATE_BG.sub(repl, sent), masks, removed


def _unmask_dates(s: str, masks: list[str]) -> str:
    for k, txt in enumerate(masks):
        s = s.replace(f"\x01{'abcdefghijklmnopqrstuvwxyz'[k % 26]}\x01", txt, 1)
    return s


def _supported(tok: str, vals: list[float]) -> bool:
    v = _num_value(tok)
    if v is None:
        return True
    x, d = abs(v[0]), v[1]
    eq = lambda y: abs(round(y, d) - x) < 10 ** -(d + 3)
    return any(eq(y) or eq(y * 100) for y in vals)                                 # и % ↔ б.п. (2s10s 0.44 = 44 б.п.)


def check_narrative_numbers(text: str, vals: list[float], dates: set | None = None) -> tuple[str, list[dict]]:
    """
    Разказът (абзаци) → (поправеният текст, [{sentence, removed}]): число без опора във входовете (vals) — частта с него пада (_why_trim_sentence); при 2+ такива
    числа в изречението — цялото изречение (остатъкът е нечетим). Имената ("S&P 500", "Q3", "40-дневни", "CLZ26") не се броят. Чиста функция.
    04.11.2026 (четвърти преглед, С4): dates — (ден, месец) от входа (narrative_dates): дата с името на месеца, която я има във входа, не е число за проверка; без опора — пада
    заедно с предлога. dates=None — както до 04.11 (датата се проверява като число).
    """
    from src import news_aggregator as na
    fixed = []

    def one(para: str):
        kept = []
        for sent0 in na._WHY_SENT.split(para):
            sent, masks, gone = _mask_dates(sent0, dates)
            toks = na._NUM_RE.findall(na._WHY_NAME.sub(" ", _THOUSANDS.sub("", sent)))
            have = {t.replace(",", ".") for t in toks if _supported(t, vals)}
            if len(have) == len({t.replace(",", ".") for t in toks}):
                if gone:
                    sent = re.sub(r"\s+([,.;:!?)])", r"\1", re.sub(r"\s{2,}", " ", sent)).strip()
                    fixed.append({"sentence": sent0, "removed": gone, "kept": _unmask_dates(sent, masks)})
                kept.append(_unmask_dates(sent, masks))
                continue
            new, removed = na._why_trim_sentence(_THOUSANDS.sub("", sent), have)              # хилядите без запетая — "4,103.9" е едно число
            if new and len(removed) >= 2:                                                       # 2+ махнати числа — остатъкът е нечетим ("(WTI, но )"): пада изречението
                new, removed = "", [sent0]
            new = _unmask_dates(new, masks) if new else new
            fixed.append({"sentence": sent0, "removed": gone + removed, "kept": new or None})
            if new:
                kept.append(new)
        return " ".join(kept), []
    out, _ = _per_paragraph(text, one)
    return out, fixed


def paragraphs(text: str) -> list[str]:
    """29.10.2026: абзаците на разказа — разделени с празен ред; празните отпадат."""
    return [x.strip() for x in re.split(r"\n\s*\n", text or "") if x.strip()]


def _per_paragraph(text: str, fn) -> tuple[str, list]:
    """fn(абзац) → (нов абзац, проблеми) върху всеки абзац; абзаците остават разделени с празен ред."""
    outs, probs = [], []
    for para in paragraphs(text):
        new, pr = fn(para)
        if new:
            outs.append(new)
        probs += pr
    return "\n\n".join(outs), probs


# 17.11.2026 (пакет 1, т. 2а): strip_trigger_echo*, strip_inst_over_100 (проверките на AI текста на картите) — махнати с AI абзаца на картите


def _apply_meta_check(out: dict) -> dict:
    """
    28.10.2026: изтеклите клаузи-проверки от промпта („без null/nan“, „всички индикатори са валидни“) се махат (regime_claims.strip_meta) — запис в "regime_claims_fixed"
    (code "meta"). 29.10.2026: само тази проверка остава за макро текста; броенето / правилото / distribution days / кредитният стрес (regime_claims.clean) бяха за абзаца за
    режима, който е махнат (разходката, т. 5).
    """
    if not isinstance(out, dict) or out.get("ai_synthesis_failed") or not isinstance(out.get("macro_brief"), str) or not out["macro_brief"]:
        return out
    new, meta = _per_paragraph(out["macro_brief"], regime_claims.strip_meta)
    if not meta:
        return out
    out = {**out, "macro_brief": new}
    out["regime_claims_fixed"] = [{"field": "macro_brief", "sentence": m["sentence"], "code": "meta", "why": "проверка на данните от промпта (null/nan, валидни стойности) — махната",
                                   "kept": m["kept"]} for m in meta]
    for x in out["regime_claims_fixed"]:
        print(f"[ai] макро текст: {x['why']}: «{x['sentence'][:140]}»")
    return out


_SIGNAL_LABELS = {"Oil_WTI": "Петрол WTI", "Gold": "Злато", "Copper": "Мед", "DXY": "Долар (DXY)", "VIX": "VIX", "US10Y": "10-годишна доходност", "MOVE": "MOVE"}


def signal_periods_block(macro: dict | None) -> str:
    """
    03.11.2026 (поправки след брифа, т. 4): пазарните сигнали с ИЗРИЧЕН период на всяко число — от кода, за промпта на макро разказа: „Петрол WTI (CLZ26): 97.56 сега · последната сесия
    (понеделник): −7.36% · 5 сесии: −2.34%“ (денят — без дата: „02.11“ проверката на числата чете като 2.11 и маха изречението). На 03.11 текстът каза „петролът завърши петицата с −2.34%“ (5-дневната промяна) и пропусна −7.36% от понеделник — входът нямаше дневната
    промяна, а периодът на −2.34% беше само в името на полето (chg_5d_pct). Без сигнали → "". Чиста функция.
    """
    gs = (macro or {}).get("global_signals") or {}
    lines = []
    for k, label in _SIGNAL_LABELS.items():
        g = gs.get(k) or {}
        if g.get("value") is None:
            continue
        d = g.get("chg_1d_date") or ""
        try:                                                     # денят от седмицата, без дата — „(02.11)“ би се хванало от проверката на числата като 2.11
            dm = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"][dt.date.fromisoformat(d).weekday()]
        except ValueError:
            dm = "?"
        unit, c1, c5 = ("б.п.", g.get("chg_1d_bp"), g.get("chg_5d_bp")) if "chg_5d_bp" in g else ("%", g.get("chg_1d_pct"), g.get("chg_5d_pct"))
        parts = [f"{label}{' (' + g['contract'] + ')' if g.get('contract') else ''}: {g['value']}" + (" сега" if g.get("price_time_utc") else "")]
        if c1 is not None:
            parts.append(f"последната сесия ({dm}): {c1:+.2f}{' ' if unit == 'б.п.' else ''}{unit}")
        if c5 is not None:
            parts.append(f"5 сесии: {c5:+.2f}{' ' if unit == 'б.п.' else ''}{unit}")
        lines.append(" · ".join(parts))
    if not lines:
        return ""
    return ("ПАЗАРНИ СИГНАЛИ С ПЕРИОДА (от кода — същите числа като в МАКРО):\n" + "\n".join(lines) + "\n"
            "ВАЖНО за тези числа: всяко число пиши С ПЕРИОДА си дословно оттук („за последната сесия (понеделник)“, „за 5 сесии“). НЕ пиши „петицата“, „седмицата“, „завърши“ "
            "без периода; не представяй 5-дневната промяна като дневна или обратно. Ход за последната сесия от ±3% или повече — спомени го, ако пишеш за този актив.\n\n")


def macro_user_prompt(macro: dict, rotation: list[dict], thermometer: dict, news: list[dict] | None = None, crypto: dict | None = None,
                      social: dict | None = None, day: dict | None = None) -> str:
    """29.10.2026: промптът на макро брифа (отделно — за tools/macro_preview.py, който го показва и без API)."""
    return f"""Днешни данни:

УРЕДИТЕ НА ТЕРМОМЕТЪРА (контекст за разказа): {json.dumps(_thermo_context(thermometer), ensure_ascii=False, default=str)}{_credit_roc_note(thermometer)}

МАКРО (FRED + пазарни сигнали): {json.dumps(macro, ensure_ascii=False, default=str)[:6000]}

{signal_periods_block(macro)}
{market_day_block(day)}
СЕКТОРНА РОТАЦИЯ (RS vs SPY): {json.dumps(rotation, ensure_ascii=False, default=str)}{_rotation_unavailable_note(rotation)}
ВОДЕЩИТЕ НИ СЕКТОРИ (по кода): {_leaders_names(rotation)}

{_news_block(news)}{_crypto_block(crypto)}{_social_block(social)}
ВАЖНО за числа в текста: когато цитираш конкретна стойност от данните по-горе \
(проценти, percentile, нива, delta-и) — копирай Я ТОЧНО както е \
в JSON-а, никога не я преизчислявай или приблизителствай наум. Специфично за \
percentile полета (напр. IEI/HYG "level_percentile"/"roc_percentile") — те са \
прецизни изчислени стойности, не грубa оценка; върни числото директно от полето, \
не генерирай "правдоподобно звучащо" число от паметта си (потвърден случай \
2026-08-26: level_percentile=0.2 цитирано в текста като "20-ти percentile").

ВАЖНО за SOFR − IORB (16.10.2026): информативен уред — напрежение във финансирането между банките, не предсказание. Цитирай стойността в б.п., \
перцентила и "as_of" точно; не го представяй като сигнал за криза.

ВАЖНО за Fed Net Liquidity: информативен уред. Цитирай "change_4w_pct" и "as_of" точно; промяна в мъртвата зона (±1%) е "без значима промяна", не растеж или спад.

ВАЖНО за единиците на MOVE: седмичната делта е в ПУНКТОВЕ на индекса (напр. "+15.4 пункта"), НЕ в проценти. Процентната промяна \
е отделно поле — "chg_5d_pct" в МАКРО global_signals.MOVE. Пиши винаги с единица ("пункта" или "%"). Потвърден случай 28.09.2026: \
делтата +15.4 пункта беше цитирана като "+15.4%" (реалната % промяна беше +19.05%).

ВАЖНО за доходностите: "US10Y" в МАКРО global_signals е доходност в % годишно \
(5.24 = 5.24%), а "chg_5d_bp" е промяната за 5 дни в БАЗИСНИ ПУНКТОВЕ (напр. \
"+7.5 б.п."). Така и пиши — "базисни пункта" или "б.п.", никога "%". НЕ смятай \
относителен процент върху доходност ("+1.5%" би се чело като 1.5 пункта) и не \
превръщай б.п. наново. Същото за 2s10s: "change_1w_bp" е седмичната промяна на \
спреда в б.п. (value и prev_week са в процентни пунктове: 0.46 = 46 б.п.).
{_core_inflation_block(macro)}
Задача — "macro_brief": {NARRATIVE_RULES}
(30.10.2026, разходката, т. 7: веригите по сектори вече не се пишат — секторната карта е от кода.)

Връщай само JSON с ключ macro_brief."""


# 30.10.2026 (поправки от брифа, т. 4): разказът не цитира нашите проучвания — 30.10: „в нашето проучване … ранен сигнал само в 1 от 3 кризи и 47–72% фалшиви сигнали“ (от надписа
# на SOFR − IORB); надписите в контекста са без тази част и без „само информативен, не влиза в режима“ (думата „режим“ не е за разказа)
_RESEARCH_IN_LABEL = re.compile(r"\s*·\s*термометър, не предсказание:[^·]*")
_INFO_SUFFIX = re.compile(r"\s*·\s*само информативен, не влиза в режима")


def _thermo_context(thermometer: dict | None) -> list[dict]:
    """29.10.2026 (разходката, т. 5): уредите на термометъра като КОНТЕКСТ за разказа — видимите, с име, стойност и надпис; без режима, броенето, override-ите и правилото."""
    out = []
    for i in (thermometer or {}).get("indicators") or []:
        if isinstance(i, dict) and str(i.get("name", "")).startswith("Put/Call"):
            continue                                                         # 16.11.2026 (пакет 16.11, т. 2): Put/Call е от кода (ред под разказа) — не стига до модела
        if isinstance(i, dict) and not i.get("hide") and i.get("value") is not None:
            label = _RESEARCH_IN_LABEL.sub("", _INFO_SUFFIX.sub("", str(i.get("label") or "")))    # 30.10.2026: без цитата от проучването и без „… не влиза в режима“
            row = {"name": i.get("name"), "value": i.get("value"), "label": label}
            if i.get("informational"):
                row["informational"] = True
            if (i.get("bond_closed") or {}).get("text"):                    # 12.11.2026 (т. 3): стойността е от предишен ден — облигационният пазар беше затворен
                row["note"] = i["bond_closed"]["text"]
            out.append(row)
    return out


def _crypto_block(crypto: dict | None) -> str:
    """29.10.2026: крипто секцията (т. 4) за разказа — дословните заглавия с „защо“ и акциите от config.CRYPTO_TICKERS за сесията (17.11.2026: COIN, HOOD)."""
    c = crypto or {}
    items = [{"headline": x.get("headline"), "why": x.get("why")} for x in c.get("items") or [] if isinstance(x, dict) and x.get("headline")]
    ticks = [{"ticker": t.get("ticker"), "chg_1d_pct": t.get("chg_1d_pct"), "chg_5d_pct": t.get("chg_5d_pct")} for t in c.get("tickers") or []
             if isinstance(t, dict) and t.get("ticker") in config.CRYPTO_TICKERS]           # 17.11.2026 (т. 9): само текущият списък (и от стар кеш)
    if not items and not ticks:
        return "КРИПТО: няма подбрани крипто новини днес — не пиши за крипто, освен ако е в новините по-горе.\n"
    return (f"КРИПТО (подбрани от кода): новини {json.dumps(items, ensure_ascii=False)}; акции, свързани с крипто, за последната сесия {json.dumps(ticks, ensure_ascii=False)}\n")


def _leaders_names(rotation: list[dict] | None) -> str:
    """29.10.2026: водещите сектори по кода (sector_layer.is_leader) с имената им — за последното изречение на разказа."""
    from src.sector_layer import is_leader
    xs = [f"{r.get('sector')} ({r.get('etf')})" for r in (rotation or []) if isinstance(r, dict) and r.get("etf") and is_leader(r)][:6]
    return ", ".join(xs) if xs else "няма водещ сектор днес"


# 29.10.2026 (разходката, т. 5, решение 3): секцията за социалните мрежи (пакетът след разходката) — споменава се само при ясен случай
SOCIAL_RULE = ("СОЦИАЛНИ МРЕЖИ — спомени ги САМО при ясен случай: рязко изкачване в обсъжданията И новина зад него в данните по-горе; тогава с формулировката "
               "„в социалните мрежи се говори за …“. Иначе не ги споменавай.")


def _social_block(social: dict | None) -> str:
    """29.10.2026: блокът за социалните мрежи — празен, докато секцията я няма (None / празна)."""
    if not social:
        return ""
    return f"\nСОЦИАЛНИ МРЕЖИ (от кода): {json.dumps(social, ensure_ascii=False, default=str)}\n{SOCIAL_RULE}\n"


# 29.10.2026 (разходката, т. 5, решение 2): разказът за нощта — тонът е от примера на Венци за 29.10 (кратки изречения, причина → следствие, числа само когато помагат,
# „под повърхността“ с мярка, последното изречение „За нас: …“). Самият пример НЕ е в промпта: съдържанието му (Alphabet, Microsoft, Бесънт) би изтекло в други дни.
NARRATIVE_RULES = (
    # 17.11.2026 (пакет 1, т. 2б — решение след стратегическия преглед): кратко — 3–4 изречения в един абзац (до 17.11 — „обикновено 2–3 абзаца“); кодът реже над
    # config.MACRO_MAX_SENTENCES (cap_sentences), като пази изречението „За нас:“
    f"Кратко — {config.MACRO_MIN_SENTENCES}–{config.MACRO_MAX_SENTENCES} изречения в един абзац, САМО върху подадените числа и новини; без преразказ на уредите един по един:\n"
    "- Започни с това, което определи нощта, и свържи нещата: кое с кое е свързано и защо (новините, крипто, глобалните сигнали). Уредите на термометъра са контекст — "
    "кажи с думи какво показват („VIX е нисък“, „над половината акции са над средните си нива“), не ги изброявай.\n"
    "- Кратки изречения, причина → следствие („затова…“, „пазарът го чу като…“). Числа само там, където помагат на историята — точно както са в данните.\n"
    # 30.10.2026 (поправки от брифа, т. 4): жаргон само с обяснение; без цитати от проучванията ни; инфлацията — двете мерки заедно или нищо
    "- Жаргон (contango, carry trade, risk-on, spread, breadth…) — само с обяснение на прост език в скоби, напр. „contango (по-далечните фючърси на VIX са по-скъпи — "
    "пазарът не очаква сътресение скоро)“.\n"
    "- Без цитати от нашите проучвания и без бележки за методиката — само какво показват данните днес.\n"
    "- Инфлацията — само с двете мерки ЗАЕДНО: основната инфлация (Dallas Fed Trimmed Mean PCE) и базовият PCE (\"pce_core\"), всяка с месеца си; ако едната липсва — "
    "не пиши за инфлацията изобщо.\n"
    "- Без изброяване на уреди, без броене на зелени / жълти / червени, без думата „режим“ и без Offensive / Defensive / Cash — режимът е горе, в термометъра, от кода.\n"
    "- Нещо „под повърхността“, което си заслужава да се следи, може да се каже — с мярка колко е силно; информативните уреди не са сигнал за криза.\n"
    "- „Мечи пазар“, „корекция“, „рекорд“ — само ако числото е в данните (спад от върха в ДЕНЯТ НА ПАЗАРА или процент в същото изречение); иначе не ги пиши — кодът маха такова изречение. "
    "„Концентрирано“, „не е системно“ — само ако ДЕНЯТ НА ПАЗАРА го показва; при широк спад не го твърди.\n"
    "- САМО от подадените данни: никаква причина, събитие или число, които ги няма тук (кодът маха число без опора в данните). Ако няма новини — разказът е за пазарните сигнали.\n"
    "- Последното изречение започва с „За нас:“ и казва какво значи нощта за водещите ни сектори; без препоръка за покупка или продажба.")


def _macro_and_sector_brief_ai(macro: dict, rotation: list[dict],
                               thermometer: dict, news: list[dict] | None = None, crypto: dict | None = None, social: dict | None = None, day: dict | None = None) -> dict:
    """
    Връща:
    {
      "macro_brief": "разказ в 3–4 изречения (един абзац; 17.11.2026 — до тогава 2–3 абзаца)"
    }
    30.10.2026 (разходката, т. 7): без веригите на секторите ("sector_logic") — секторната карта е от кода (sector_layer.sector_board).
    29.10.2026 (разходката, т. 5): без "regime_comment"; моделът вижда уредите на термометъра само като контекст (_thermo_context), крипто секцията (_crypto_block) и — когато я има —
    секцията за социалните мрежи (_social_block). Махнати от промпта: броенето и правилото за режима, "exit_rule", "Запас до смяна на режима", бележките за блока от
    distribution days и за освободен override — те бяха само за абзаца за режима.

    FIX 2026-08-17 (production crash — json.decoder.JSONDecodeError необхванат
    чак до run(), сборил целия pipeline): 3 нива защита, в ред на разходна
    ефективност — Ниво 0 (json_repair, вътре в _parse_json(), нулева цена),
    Ниво 1 (тук долу — smart retry: подаваме malformed отговора обратно на
    Claude с explicit инструкция да го поправи, ЕДНА допълнителна AI заявка),
    Ниво 2 (_macro_brief_fallback() — суровите данни без AI наратив, graceful,
    никога не позволяваме на изключението да стигне до run()).
    """
    user = macro_user_prompt(macro, rotation, thermometer, news, crypto, social, day)

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


# 17.11.2026 (пакет 1, т. 2а — решение след стратегическия преглед): AI абзацът на картите — махнат: SYSTEM_TICKERS, ticker_narratives, merge_narratives,
# проверките на числата / събитията / цените в него (verify_narrative_*). Редът „Защо е тук“ е от кода (render.why_here).


# ══════════════════════════════════════════════════════════════════════════
# COT (Commitments of Traders) — Секция [нова] — Шапиро тези
# ══════════════════════════════════════════════════════════════════════════

# 30.10.2026 (разходката, т. 8): thesis_news_pick (AI подборът на свързани новини към геополитическите тези), _anchor_match и THESIS_CHECK_DIAG — махнати заедно с тезите.


SYSTEM_WATCH = """Ти си анализатор, който следи конкретни компании за инвеститор, \
който вече държи позиции в тях. Преразказваш кратко само даденото — новините и Form 4 — \
без собствени обяснения на причините и без мотиви на хора. Пишеш на български, тикери и термини на \
английски. Директен си: ако събитието е рутинно, го казваш рутинно. Връщаш \
САМО валиден JSON, без markdown огради, без преамбюл."""


def watch_ticker_digest(rows: list[dict], market_context: dict, window_hours: float = 24) -> list[dict]:
    """
    AI тълкуване за „🔎 Наблюдавани тикъри" (виж watch_monitor.py).

    rows: изходът на watch_monitor.collect(), БЕЗ тихите тикъри — те не стигат
    дотук изобщо (кодът им слага текста сам, виж main.py).
    market_context: {cot_markets, leading_sectors} — вече налични в паметта на run-а, не нов източник (30.10.2026, т. 8: без active_theses — тезите
    са махнати).

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
    29.10.2026 → 30.10.2026 (поправки от брифа): на ГРУПИ по config.WATCH_AI_BATCH_SIZE (4) тикъра — отделни извиквания (_watch_digest_batch), резултатите се
    събират; провалена група → само нейните тикъри са без резюме, с причина в ai["missing"] (секцията го казва с ред). 30.10: 14 тикъра наведнъж → отговорът спря на
    2000 токена (max_tokens) и резюмета нямаше за нито един.
    """
    if not rows:
        return rows
    n = max(1, config.WATCH_AI_BATCH_SIZE)
    out = []
    for k in range(0, len(rows), n):
        group = rows[k:k + n]
        try:
            out += _watch_digest_batch(group, market_context, window_hours)
        except Exception as e:
            why = "отговорът е отрязан (лимитът за изход)" if isinstance(e, TruncatedResponse) else f"грешка ({type(e).__name__})"
            print(f"[ai] watch_ticker_digest: групата {', '.join(r['ticker'] for r in group)} не мина — {why}: {e}")
            out += [{**r, "ai": {"missing": why}} for r in group]
    return out


_CAP_RUN = re.compile(r"[A-Z][A-Za-z'\-]*\.?(?:\s+[A-Z][A-Za-z'\-]*\.?)*")
_ENTITY = re.compile(r"\b(CO|CORP|CORPORATION|INC|LLC|L\.?P|LP|LTD|PLC|FUND|TRUST|HOLDINGS?|GROUP|BANK|INSURANCE|PARTNERS|CAPITAL|MANAGEMENT|ADVISORS?|INVESTMENTS?)\b\.?", re.I)
_ROLE_BEFORE = re.compile(r"(?:\b(?:C[A-Z]{1,3}O|Co-CEO|Chair|Chairman|President|Director|Officer|EVP|SVP|VP)(?:\s+(?:&\s+)?[A-Z][A-Za-z&]+){0,3}|директор\w*|председател\w*|"
                          r"президент\w*|член\w*\s+на\s+борда|счетоводител\w*|юрисконсулт\w*|вицепрезидент\w*|инсайдър\w*)[\s,]*$")


def role_bg(title: str | None, is_director: bool = False) -> str:
    """03.11.2026 (прегледът, т. 5): длъжността на инсайдъра от Form 4 на български (без член) — вместо името му. Чиста функция."""
    t = (title or "").lower()
    rules = (("co-ceo", "съизпълнителен директор"), ("chief executive", "изпълнителен директор"), ("ceo", "изпълнителен директор"),
             ("chief financial", "финансов директор"), ("cfo", "финансов директор"), ("chief operating", "оперативен директор"), ("coo", "оперативен директор"),
             ("chief accounting", "главен счетоводител"), ("principal accounting", "главен счетоводител"), ("general counsel", "главен юрисконсулт"),
             ("chief legal", "главен юрисконсулт"), ("chief technology", "технически директор"), ("cto", "технически директор"), ("president", "президент"),
             ("chair", "председател на борда"), ("chief", "член на ръководството"), ("vice president", "вицепрезидент"), ("evp", "вицепрезидент"), ("svp", "вицепрезидент"))
    for key, bg in rules:
        if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", t):
            return bg
    return "член на борда" if is_director else "инсайдър"


def strip_person_names(text: str, insiders: list[dict]) -> tuple[str, list[str]]:
    """
    03.11.2026 (поправки след брифа, т. 5; прегледът 03.11): AI текстът за наблюдаваните — БЕЗ имена на хора, само длъжността (името е в таблицата под реда). EDGAR пише
    инсайдъра „Фамилия Име Презиме“ („Sweet Julie Spellman“); моделът пишеше „Julie Spellman“, „Ryoji Sekido“, „Catapano Joseph Ronald“ (дословно). Последователност от думи с главна
    латинска буква, чиито думи (≥ 2; или 1 — фамилията, първата дума в EDGAR, или дума точно след длъжност) са от името на ЧОВЕК-инсайдър (не фирма — NIPPON LIFE INSURANCE CO остава), → махната, ако точно преди нея стои
    длъжност („CEO Julie Spellman“ → „CEO“), иначе заменена с длъжността му на български (role_bg: „Ryoji Sekido (Co-CEO …)“ → „съизпълнителен директор (Co-CEO …)“). Имена извън
    Form 4 таблицата не се пипат (може да е „Wall Street“) — правилото в промпта ги забранява. → (текст, бележки). Чиста функция.
    """
    notes = []
    if not text:
        return text, notes
    people = []
    for t in insiders or []:
        name = (t.get("owner_name") or "").strip()
        if not name or _ENTITY.search(name):
            continue
        toks = {w.strip(".,").lower() for w in name.split() if len(w.strip(".,")) > 1}
        if toks and name not in [p[0] for p in people]:
            people.append((name, toks, role_bg(t.get("owner_title"), bool(t.get("is_director"))), name.split()[0].strip(".,").lower()))   # EDGAR: фамилията е първа
    if not people:
        return text, notes
    out, pos = [], 0
    for m in _CAP_RUN.finditer(text):
        words = list(re.finditer(r"\S+", m.group(0)))
        i = 0
        while i < len(words):
            best = None
            for name, toks, role, surname in people:
                j = i
                while j < len(words) and (words[j].group(0).strip(".,").lower() in toks or (len(words[j].group(0).strip(".")) == 1 and j > i)):
                    j += 1
                if j > i and (best is None or j > best[0]):
                    best = (j, name, role, surname)
            if best:
                j, name, role, surname = best
                start, end = m.start() + words[i].start(), m.start() + words[j - 1].end()
                before = text[pos:start]
                one = words[i].group(0).strip(".,").lower()
                if j - i >= 2 or one == surname or _ROLE_BEFORE.search(text[:start]):           # две думи от името; сама фамилията (първата дума в EDGAR); дума след длъжност
                    if _ROLE_BEFORE.search(text[:start]):
                        out.append(before.rstrip(" "))
                        notes.append(f"«{text[start:end]}» — махнато (длъжността е преди него)")
                    else:
                        out.append(before + role)
                        notes.append(f"«{text[start:end]}» → «{role}»")
                    pos = end
                    i = j
                    continue
            i += 1
    out.append(text[pos:])
    res = re.sub(r"[ \t]{2,}", " ", "".join(out))
    return res, notes


# 06.11.2026 (пакет 05–06.11, т. 9): коментарите на наблюдаваните — само преразказ на новините / Form 4. Реално: CRCL 05.11 „по-вероятното обяснение е координирано ликвидиране след IPO lock-up изтичане“, SIRI 05.11
# „Buffett продължава да добавя“, CRCL 05.11 „комбинация, която сигнализира фокус върху маржа“. Думата е допустима, ако я има в заглавията от входа. Клауза след „ — “ / „, което“ пада сама; без такава — цялото изречение.
_WATCH_CAUSE = re.compile(r"lock[- ]?up|локъп|обяснени\w*|мотив\w*|(?<!не )сигнализир\w*|\bзнак\s+за\b|по-вероятн\w*|вероятно\s+(?:е|да)\b|\bза\s+да\s+компенсира\w*", re.I)
_WATCH_CLAUSE = re.compile(r"\s+—\s+|,\s+(?:което|който|която|които)\s+")


def strip_watch_causes(text: str, titles: str = "") -> tuple[str, list[dict]]:
    """
    Собствени обяснения на причините и мотивите в коментар за наблюдаван тикър → (текстът без тях, [{term, removed}]). Имената от config.WATCH_BANNED_NAMES (хора извън Form 4) — цялото изречение.
    Думата без опора: я няма в заглавията (titles). Чиста функция.
    """
    if not text:
        return text, []
    from src import news_aggregator as na
    gone, kept = [], []
    low = titles.lower()
    for sent in na._WHY_SENT.split(text):
        name = next((n for n in config.WATCH_BANNED_NAMES if n in sent and n.lower() not in low), None)
        if name:
            gone.append({"term": name, "removed": sent})
            continue
        m = next((x for x in _WATCH_CAUSE.finditer(sent) if x.group(0).lower() not in low), None)
        if not m:
            kept.append(sent)
            continue
        cuts = [c for c in _WATCH_CLAUSE.finditer(sent) if c.start() < m.start()]
        dash = [c for c in cuts if "—" in c.group(0)]                           # „ — комбинация, която сигнализира …“: клаузата започва от тирето
        cut = (dash or cuts or [None])[-1]
        head = sent[:cut.start()].rstrip(" ,;:") if cut else ""
        if len(head) >= 25:                                                     # смислена първа част — остава само тя
            kept.append(head + ".")
            gone.append({"term": m.group(0), "removed": sent[cut.start():].strip(" —,")})
        else:
            gone.append({"term": m.group(0), "removed": sent})
    return " ".join(kept), gone


def strip_routine(text: str) -> tuple[str, list[dict]]:
    """
    10.11.2026 (т. 5): изреченията с „рутин…“ (рутинно, рутинна, рутинни, рутинен) — махнати; за реда, в който кодът е вдигнал „продава ≥25% от дела си“
    (watch_monitor.big_sellers). → (текстът без тях, [{term, removed}]). Чиста функция.
    """
    if not text:
        return text, []
    from src import news_aggregator as na
    kept, gone = [], []
    for sent in na._WHY_SENT.split(text):
        (gone.append({"term": "рутин", "removed": sent}) if re.search(r"рутин", sent, re.I) else kept.append(sent))
    return " ".join(kept), gone


def _watch_digest_batch(rows: list[dict], market_context: dict, window_hours: float = 24) -> list[dict]:
    """Една група наблюдавани тикъри → [{**ред, "ai": {summary, insider_read, cross_reference}}]. Хвърля при провал (watch_ticker_digest го хваща за групата)."""
    compact = [{
        "ticker": r["ticker"],
        "news": [{"title": n["title"], "publisher": n["publisher"]} for n in r["news"]],
        # 10.11.2026 (т. 5, CRCL 10.11: „54 продажби от 4 различни инсайдъра“): Form 4 по човек и ден (watch_monitor.person_days), броят хора отделно от редовете
        "insider": [{"code": t["code"], "date": t["date"],
                     "owner": t["owner_name"], "title": t["owner_title"],
                     "value_usd": round(t["value"]),
                     "pct_of_holdings": t["pct_of_holdings"],
                     "planned_10b5_1": t["planned_10b5_1"], "form4_rows": t.get("n", 1)} for t in (r["insider_days"] if "insider_days" in r else r["insider"])],
        "insider_cluster": r["insider_cluster"],
        "insider_flags": [{"label": f.get("label"), "people": f.get("owners"), "form4_rows": f.get("n"), "cluster": f.get("cluster"), "plan": f.get("plan")}
                          for f in r.get("insider_flags") or []],   # 30.10.2026: по посока, с плана
        "sells_25pct_of_stake": [{"title": b.get("title"), "pct_of_stake": b["pct"], "planned_10b5_1": b.get("planned_10b5_1")} for b in r.get("insider_big_sell") or []],
    } for r in rows]                                                       # 16.11.2026 (пакет 16.11, т. 4): insider_days / flags / ≥25% — само новите Form 4 от предишния бриф

    user = f"""НАБЛЮДАВАНИ ТИКЪРИ (данни за последните {round(window_hours)} часа — от предишния бриф):
{json.dumps(compact, ensure_ascii=False, default=str)}

ТЕМИ, АКТИВНИ ДРУГАДЕ В ДНЕШНИЯ БРИФ:
{json.dumps(market_context, ensure_ascii=False, default=str)}

За всеки тикър върни:

БЕЗ ИМЕНА НА ХОРА — пиши САМО длъжността на български (изпълнителният директор, финансовият директор, член на борда); името е в таблицата под реда. \
Имена на компании и фондове — може.

САМО ПРЕРАЗКАЗ: пиши само онова, което го има в заглавията и Form 4. Без причини и мотиви, които ги няма там (lock-up, „за да…“, „по-вероятното обяснение“, „сигнализира“, какво мислят или целят \
мениджърите) — кодът маха такива изречения.

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
при голяма абсолютна сума — кажи дела; не гадай защо е продажбата.
  • insider_flags.people — броят ХОРА; form4_rows — редовете във Form 4 (един \
човек подава десетки редове за един ден). Казвай броя хора, НЕ броя \
редове/транзакции/продажби. Редовете в "insider" са вече обединени по човек и ден.
  • sells_25pct_of_stake (от кода) — човекът продава ≥25% от дела си. Тогава \
НЕ пиши „рутинно“/„рутинна“ за тези продажби, дори по 10b5-1 — кажи, че \
продава толкова процента от дела си.
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
        ai = {k: (d.get(k) or "").strip() for k in ("summary", "insider_read", "cross_reference")}
        for k in ai:                                                # 03.11.2026 (т. 5, прегледът): без имена на хора — длъжността
            ai[k], notes = strip_person_names(ai[k], r.get("insider") or [])
            for n in notes:
                print(f"[ai] watch {r['ticker']} {k}: {n}")
        removed = []
        for k in ai:                                                # 06.11.2026 (пакет 05–06.11, т. 9): без собствени обяснения на причините
            ai[k], gone = strip_watch_causes(ai[k], " ".join(str(n.get("title") or "") for n in r.get("news") or []))
            removed += [{"field": k, **g} for g in gone]
            for g in gone:
                print(f"[ai] watch {r['ticker']} {k}: „{g['term']}“ без опора — махнато «{g['removed'][:110]}»")
        if r.get("insider_big_sell"):                             # 10.11.2026 (т. 5): ≥25% от дела → без „рутинно“, каквото и да е написал моделът
            ai["insider_read"], gone = strip_routine(ai["insider_read"])
            removed += [{"field": "insider_read", **g} for g in gone]
            for g in gone:
                print(f"[ai] watch {r['ticker']} insider_read: „рутин…“ при продажба ≥{config.INSIDER_BIG_SELL_PCT:g}% от дела — махнато «{g['removed'][:110]}»")
        annotated.append({**r, "ai": ai, **({"ai_removed": removed} if removed else {})})
    linked = sum(1 for a in annotated if a["ai"]["cross_reference"])
    print(f"[ai] watch_ticker_digest: група {', '.join(r['ticker'] for r in rows)} — {len(annotated)} тикъра, {linked} с cross-reference")
    return annotated


# 03.11.2026 (разходката, т. 17): COT тезите (SYSTEM_COT, cot_theses, проверките на тикърите и паметта за наследници) са махнати — COT секцията е таблица от кода, без AI.

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
            # 08.10: Yahoo реже shortName на ~30 знака ("Corcept Therapeutics Incorporat") — при отрязано име се взима longName (виж names.prefer_long)
            if candidate == (short_name or "").strip() and long_name and not _looks_like_exchange_code(long_name.strip()):
                return names.prefer_long(short_name, long_name)
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
        # short_name/financial_currency (08.10.2026): сверяване на твърдението за компанията с ВСИЧКИ имена на Yahoo и валута на отчитане за
        # валутните тези (cot_theses.cross_gate) — същият fetch, нулев допълнителен network call.
        return {"name": name or ticker, "verified": bool(name),
               "quote_type": info.get("quoteType"), "category": info.get("category"),
               "long_name": info.get("longName"), "short_name": info.get("shortName"),
               "sector": info.get("sector"), "industry": info.get("industry"),
               "financial_currency": info.get("financialCurrency")}
    except Exception as e:
        print(f"[ai] company lookup {ticker}: {e}")
        return {"name": ticker, "verified": False,
               "quote_type": None, "category": None, "long_name": None, "short_name": None,
               "sector": None, "industry": None, "financial_currency": None}


# 04.11.2026 (четвърти преглед): SYSTEM_SHORT_CONTEXT / short_thesis_global_context (AI контекстът „глобално срещу регионално“ за short кандидатите) — махнати:
# спрени от 03.10 (без визуализация), short модулът е замразен (SHORT_FROZEN).
