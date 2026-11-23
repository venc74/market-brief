"""
20.11.2026 (пакет 20.11, т. 1): преводът на заглавията — AI САМО превежда (без коментар), кодът проверява. Всяко число, тикър и собствено име от оригинала трябва да е в превода:
числата — по стойност (900,000 = 900 000 = 900000; 1.8 = 1,8), с мащаба (billion → млрд, trillion → трлн, million → млн); тикърите и имената на хора, компании и организации — на
латиница, както са в оригинала (промптът го иска); държави, градове, институции — на латиница или с българското име от _PLACES. Липсва нещо → само оригиналът с бележка
„преводът е пропуснат — несъответствие (липсва: …)“. Мрежа само в translate(); останалото — чисти функции.
"""
from __future__ import annotations

import json
import re

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

SYSTEM = ("Ти си преводач на финансови заглавия от английски на български. Превеждаш дословно и кратко, без коментар, без обяснения и без добавки. "
          "Връщаш САМО валиден JSON.")
RULES = ("Преведи всяко заглавие на български. Правила: (1) всички числа — със същата стойност (може с българско форматиране: 900 000, 1,8); мащабът — млн / млрд / трлн; "
         "(2) имената на хора, компании, продукти, организации и тикърите — на латиница, точно както са в оригинала (Trump, Xi, Nvidia, Anthropic, ANT, Fed, OPEC); "
         "(3) държави и градове — на български (China → Китай, US → САЩ); (4) без коментар, без оценка, без добавени факти; само преводът. "
         'Върни JSON: {"bg": ["превод на заглавие 0", "превод на заглавие 1", ...]} — в същия ред и същия брой.')

_SUFFIX = re.compile(r"\s+-\s+(?:Reuters|AP News|AP|CNBC|Financial Times|FT|Bloomberg)\s*$")
# 20.11.2026 (прегледът на страницата): числото — цяло, с мащаба след него ($6.3B, $81bn, $77.5M); до тази поправка „$6.3B“ се четеше като 6 (regex-ът се връщаше назад до
# „6“), а „$81bn“ — изобщо не: в историята на брифовете 64 от 1366 заглавия (Binance $6.3B, FT „$Xbn“) — верен превод „$6,3 млрд“ щеше да е отхвърлен. Суфиксът брои само след
# валута ($ € £): „3M“ (компанията) и „40M barrels“ (единственият такъв случай в историята) — без проверка на числото.
_SUFFIXES = {"M": "million", "mn": "million", "B": "billion", "bn": "billion", "T": "trillion", "tn": "trillion"}
_NUM_EN = re.compile(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)(M|B|T|bn|mn|tn)?(?![\w]|[.,]\d)")
_NUM_BG = re.compile(r"(?<![\w.,])(\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(M|B|T|bn|mn|tn)?(?![\w]|[.,]\d)")
_SCALE = [(re.compile(r"\b(?:billion|bn)\b", re.I), re.compile(r"млрд|милиард", re.I), "billion"),
          (re.compile(r"\b(?:trillion|tn)\b", re.I), re.compile(r"трлн|трилион", re.I), "trillion"),
          (re.compile(r"\b(?:million|mln)\b", re.I), re.compile(r"млн|милион", re.I), "million")]
# собствени имена, които в превода може да са на български (държави, градове, институции, групи); стойността — regex за българската форма
_PLACES = {
    "US": r"САЩ|американ|Америк", "U.S": r"САЩ|американ|Америк", "USA": r"САЩ", "AMERICA": r"Америк|САЩ", "AMERICAN": r"американ|САЩ", "AMERICANS": r"американ",
    "UK": r"Великобритани|Обединеното кралство|британ", "BRITAIN": r"Великобритани|Британи|британ", "BRITISH": r"британ|Великобритани", "EU": r"ЕС|Европейския съюз|Европейск",
    "CHINA": r"Кита|китайск", "CHINESE": r"китайск|Кита", "RUSSIA": r"Руси|руск", "RUSSIAN": r"руск|Руси", "UKRAINE": r"Украйн|украинск", "IRAN": r"Иран|ирански", "ISRAEL": r"Израел",
    "JAPAN": r"Япони|японск", "JAPANESE": r"японск|Япони", "INDIA": r"Инди|индийск", "EUROPE": r"Европ|европейск", "EUROPEAN": r"европейск|Европ", "GERMANY": r"Германи|германск",
    "GERMAN": r"германск|Германи", "FRANCE": r"Франци|френск", "FRENCH": r"френск|Франци", "ITALY": r"Итали|италианск", "SPAIN": r"Испани|испанск", "CANADA": r"Канад|канадск",
    "MEXICO": r"Мексик|мексиканск", "BRAZIL": r"Бразили|бразилск", "TAIWAN": r"Тайван", "KOREA": r"Коре|корейск", "SOUTH": r"Южн|юг", "NORTH": r"Северн|север",
    "ASIA": r"Ази|азиатск", "ASIAN": r"азиатск|Ази", "ASIA-PACIFIC": r"Азиатско-тихоокеанск|АТР|Ази", "AFRICA": r"Африк", "SAUDI": r"Саудит|саудитск", "ARABIA": r"Араби",
    "GULF": r"Залив", "MIDDLE": r"Близкия|Близкия изток|Близък", "EAST": r"изток|Изток|източн", "WEST": r"запад|Запад|западн", "RED": r"Червено", "SEA": r"море",
    "HORMUZ": r"Хормуз|Ормуз", "CALIFORNIA": r"Калифорни", "TEXAS": r"Тексас", "NEW": r"Ню|нов", "YORK": r"Йорк", "WASHINGTON": r"Вашингтон", "BEIJING": r"Пекин",
    "MOSCOW": r"Москв", "LONDON": r"Лондон", "TOKYO": r"Токио", "PARIS": r"Париж", "BERLIN": r"Берлин", "RIYADH": r"Рияд", "KUWAIT": r"Кувейт", "YEMEN": r"Йемен",
    "WALL": r"Уолстрийт|Уол Стрийт|Wall", "STREET": r"Уолстрийт|Стрийт|Street", "SENATE": r"Сенат", "HOUSE": r"Камара|Конгрес|Белия дом", "CONGRESS": r"Конгрес",
    "WHITE": r"Белия", "TREASURY": r"Министерство на финансите|финанс|Treasury|ДЦК", "PENTAGON": r"Пентагон", "KREMLIN": r"Кремъл", "HOUTHI": r"хусит", "HOUTHIS": r"хусит",
    "DEMOCRATS": r"демократ", "DEMOCRAT": r"демократ", "DEMOCRATIC": r"демократ", "REPUBLICANS": r"републикан", "REPUBLICAN": r"републикан", "SUPREME": r"Върховн",
    "COURT": r"съд", "APEC": r"APEC|АТИС", "NATO": r"НАТО|NATO", "UN": r"ООН|UN", "IMF": r"МВФ|IMF", "ECB": r"ЕЦБ|ECB",
    "MONDAY": r"понеделник", "TUESDAY": r"вторник", "WEDNESDAY": r"сряда", "THURSDAY": r"четвъртък", "FRIDAY": r"петък", "SATURDAY": r"събота", "SUNDAY": r"неделя",
    "JANUARY": r"януари", "FEBRUARY": r"февруари", "MARCH": r"март", "APRIL": r"април", "MAY": r"май", "JUNE": r"юни", "JULY": r"юли", "AUGUST": r"август",
    "SEPTEMBER": r"септември", "OCTOBER": r"октомври", "NOVEMBER": r"ноември", "DECEMBER": r"декември", "EXCLUSIVE": r"ЕКСКЛУЗИВНО|Ексклузивно|EXCLUSIVE|ексклузив",
    "BREAKINGVIEWS": r"Breakingviews", "INSTANT": r"Instant|Мигновен|Бърз", "VIEW": r"View|поглед|коментар", "TRADING": r"Trading|Търгов", "DAY": r"Day|ден", "LIVE": r"на живо|Live",
    "UPDATES": r"актуализ|Updates|новини", "TAKEAWAYS": r"извод|изводи|Takeaways|акцент", "ATTORNEY": r"прокурор|Attorney", "GENERAL": r"главн|General",
}


def _num_value(tok: str, bg: bool) -> float | None:
    t = tok.replace(" ", "").replace(" ", "")
    if bg:
        t = t.replace(",", ".")
    else:
        t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _matches(s: str, bg: bool) -> list[tuple[float, str | None]]:
    """[(стойност, мащаб от суфикса | None)]; число със суфикс без валута преди него — пропуснато (3M, 40M barrels)."""
    s = s or ""
    out = []
    for m in (_NUM_BG if bg else _NUM_EN).finditer(s):
        if m.group(2) and not (m.start() > 0 and s[m.start() - 1] in "$€£"):
            continue
        v = _num_value(m.group(1), bg)
        if v is not None:
            out.append((v, _SUFFIXES.get(m.group(2)) if m.group(2) else None))
    return out


def numbers(s: str, bg: bool = False) -> list[float]:
    return [v for v, _ in _matches(s, bg)]


def is_title_case(s: str | None) -> bool:
    """
    23.11.2026 (пакет 23.11, т. 2): заглавие в Title Case („Stock Looks Pricey Following Its New AI Contract Push“) — ≥ 70% от думите с 4+ букви (без съкращенията) с главна.
    Измерено: Yahoo (наблюдаваните) — 224 от 246; основните източници — 2 от 288 (Reuters, AP), крипто — 0 от 87. Чиста функция.
    """
    toks = [w for w in re.findall(r"[A-Za-z][A-Za-z’']+", _SUFFIX.sub("", s or "")) if len(w) >= 4 and not w.isupper()]
    return len(toks) >= 3 and sum(w[0].isupper() for w in toks) / len(toks) >= 0.7


def proper_caps(titles: list[str]) -> set[str]:
    """Думите с главна НЕ в началото — само от заглавията в обикновен регистър (в Title Case всяка дума е с главна и не казва нищо). Чиста функция."""
    from src import top_themes
    return top_themes._later_caps([t for t in titles or [] if not is_title_case(t)])


def names(orig: str, caps: set | None = None) -> list[str]:
    """
    Тикърите и собствените имена в оригинала (нормализирани, главни) — top_themes.tokens без стоп-думите на темите (тук всяко собствено име се брои).
    23.11.2026 (т. 2): в Title Case главната буква не значи име — брои се само съкращението (DOCU, AI, IBM), думата с главна вътре (DocuSign), притежателното („Nvidia's“) и
    думите, които в обикновените заглавия на деня стоят с главна по средата (caps — proper_caps). До 23.11 всяко „Stock“, „Looks“, „Pricey“ искаше да е в превода.
    """
    from src import top_themes
    t = _SUFFIX.sub("", orig or "")
    title_case = is_title_case(t)
    out = []
    for k, m in enumerate(top_themes._TOKEN.finditer(t)):
        raw = m.group(0)
        n = top_themes._norm(raw)
        if not n or len(n) < 2 or n in {"A", "AN", "THE", "I", "OF", "IN", "ON", "TO", "AND", "OR", "AS", "AT", "FOR", "BY", "IS", "IT", "WE", "MY", "HE", "SHE"}:
            continue
        if title_case:
            if not ((raw.isupper() and len(n) >= 2) or re.search(r"[a-z][A-Z]", raw) or re.search(r"['’]s$", raw) or (caps is not None and n in caps)):
                continue
        elif m.start() == 0 and not (raw.isupper() or re.search(r"['’]s$", raw) or (caps is not None and n in caps) or n in _PLACES):
            continue
        if re.fullmatch(r"[A-Z]{2,}s", raw):                # 20.11.2026: съкращение в мн. ч. — ETFs → ETF (преводът „ETF-и“); в историята — ETFs ×14, IPOs, AGs
            n = raw[:-1]
        out.append(n)
    return list(dict.fromkeys(out))


def problems(orig: str, bg: str | None, caps: set | None = None, must: list | None = None) -> list[str]:
    """
    Какво от оригинала липсва в превода: числа, мащаб, тикъри и собствени имена. [] → преводът е приет. Чиста функция.
    23.11.2026 (т. 2): must — имена, които трябва да са в превода, ако са в оригинала (наблюдаваните: името на компанията — и в Title Case).
    """
    if not bg or not bg.strip():
        return ["празен превод"]
    o = _SUFFIX.sub("", orig or "")
    miss = []
    nb = numbers(bg, bg=True)
    for v in numbers(o):
        if not any(abs(v - x) < 1e-9 for x in nb):
            miss.append(f"{v:g}")
    bg_suffix = {sc for _, sc in _matches(bg, True) if sc}
    en_suffix = {sc for _, sc in _matches(o, False) if sc}
    for en, bgx, lab in _SCALE:
        if (en.search(o) or lab in en_suffix) and not (bgx.search(bg) or lab in bg_suffix):
            miss.append(lab)
    low = bg.lower()
    for n in names(o, caps):
        plain = n.replace("'", "").lower()
        if plain and plain in low.replace("'", "").replace("’", ""):
            continue
        rx = _PLACES.get(n)
        if rx and re.search(rx, bg, re.I):
            continue
        miss.append(n)
    for w in must or []:
        if w and w.lower() in (orig or "").lower() and w.lower() not in low and w.upper() not in miss:
            miss.append(w.upper())
    return miss


def translation_call(system: str, user: str) -> str:
    """AI извикването на превода — именувана функция (етикетът в brief["ai_usage"] е по името на извикващия; ai_brief._SECTION_LABELS)."""
    from src import ai_brief
    return ai_brief._call_claude(system, user, max_tokens=2000)


def translate(titles: list[str], call=None, batch: int = 15) -> list[str | None]:
    """AI превод на заглавията (на партиди) → [превод | None] в същия ред. Провал на партида → None за нея (оригиналът остава, с бележка)."""
    out: list[str | None] = [None] * len(titles)
    if not titles:
        return out
    call = call or translation_call
    for b0 in range(0, len(titles), batch):
        part = titles[b0:b0 + batch]
        user = RULES + "\n\nЗАГЛАВИЯ:\n" + json.dumps([{"i": k, "t": _SUFFIX.sub("", t)} for k, t in enumerate(part)], ensure_ascii=False)
        try:
            from src import ai_brief
            data = ai_brief._parse_json(call(SYSTEM, user))
            bg = (data or {}).get("bg") if isinstance(data, dict) else None
            if isinstance(bg, list) and len(bg) == len(part):
                for k, x in enumerate(bg):
                    out[b0 + k] = x.strip() if isinstance(x, str) and x.strip() else None
            else:
                print(f"[translate] партида {b0 // batch + 1}: отговорът е с {len(bg) if isinstance(bg, list) else '?'} превода за {len(part)} заглавия — без превод")
        except Exception as e:
            print(f"[translate] партида {b0 // batch + 1}: {type(e).__name__}: {e} — без превод")
    return out


def apply(rows: list[dict], caps: set | None = None, call=None, key: str = "headline", must=None) -> dict:
    """
    Превежда rows[*][key] → row["headline_bg"] (приет) или row["translation_note"] = „преводът е пропуснат — несъответствие (липсва: …)“; провал на превода — „преводът не се
    получи“. → {"n", "ok", "skipped": [{headline, missing}]}. Мутира rows.
    """
    titles = [r.get(key) or "" for r in rows]
    bgs = translate(titles, call=call) if titles else []
    rep = {"n": len(rows), "ok": 0, "skipped": []}
    for r, bg in zip(rows, bgs):
        r.pop("headline_bg", None)
        r.pop("translation_note", None)
        if bg is None:
            r["translation_note"] = "преводът не се получи"
            continue
        miss = problems(r.get(key) or "", bg, caps, must(r) if must else None)
        if miss:
            r["translation_note"] = f"преводът е пропуснат — несъответствие (липсва: {', '.join(miss[:5])})"
            r["translation_rejected"] = bg
            rep["skipped"].append({"headline": r.get(key), "missing": miss})
        else:
            r["headline_bg"] = bg
            rep["ok"] += 1
    return rep
