"""
Броенето на термометъра и причината за режима като ГОТОВИ низове от кода + проверка на числовите твърдения на модела (08.10.2026). Чисти функции, без мрежа и без AI.

Реален дефект (макро текстът на 08.10): моделът изброи Fed Net Liquidity сред 3-те жълти ("… Fed Net Liquidity — последният само информативен и не влиза в броенето"), докато кодът
брои като жълти Put/Call, MOVE и Market Breadth; и твърдеше, че Market Breadth "само по себе си дава Defensive" — не дава (режимът по броенето иска ≥ 2 червени за Defensive по правило
или недостатъчно потвърждение за Offensive; единични индикатори форсират режим само през override-ите VIX, MOVE, IEI/HYG и през червените distribution days).

  • facts(thermo) — {groups, counts_text, rule_text}: кои индикатори са зелени/жълти/червени/скрити/информативни (по имена) и готовите изречения; влизат в промпта, моделът ги копира, не преброява.
  • check(text, facts) — открива в прозата (а) брой "N зелени/жълти/червени", който не съвпада с кода, или посочен в скоби индикатор от друг цвят/информативен; (б) твърдение, че индикатор,
    който НЕ може да форсира режим, го определя "сам по себе си".
  • clean(text, facts) — маха изреченията с такива твърдения; връща (нов текст, [{sentence, code, why}]).

15.10.2026 · твърдения за ПРАВИЛОТО (код "rule"): макро текстът на 15.10 написа "ако един зелен стане червен при 0 червени сега, системата пак остава Offensive; нужни са 2 червени за Defensive",
а по thermometer._count_regime Offensive иска 0 червени — един червен → Defensive. Хващат се: (а) "нужни са N червени за Defensive/Cash/Offensive" с N, различно от правилото (1 / 3 / 0);
(б) "един … стане червен … остава Offensive"; (в) праг на зелените за Offensive, различен от 4 ("изисква повече от 7/9 зелени", "8/8 зелени за Offensive"); (г) "би дало Offensive" при посочен
в изречението червен. Изречението се заменя с rule_text. Мерено върху 173 реални текста (13.06–15.10): 5 флага — 23.07, 20.08, 10.09 и двата на 15.10 (едно изречение); 0 фалшиви.
26.10.2026 (етап 4б, т. 4) · твърдения за КРЕДИТЕН стрес (код "credit"): "кредитният пазар потвърждава стреса" (23.10), "ключовият стрес идва от кредитните спредове" (19.10), "credit risk
premium се разширява" (20.10) при HYG част на 10-дневната RoC над config.CREDIT_CLAIM_HYG_CONFIRM_PCT (−0.2%) — скокът на IEI/HYG е от IEI (лихвите), HYG почти не мърда. Първото такова
изречение се заменя с разлагането от кода (credit_text), следващите се махат — както при правилото. Отрицание / контраст преди фразата ("не от класическо кредитно влошаване", "повече от
реален credit stress", "ниско ниво на credit stress"), условие ("ако … задвижи credit spreads") и описание на индикатора ("credit stress gauge") не са твърдение. Без разлагане (HYG
липсва в индикатора — брифовете преди 19.10) проверката не се прави.
  • margin(thermo, distribution_days) — "Запас до смяна на режима" от кода: колко червени сменят режима по правилото, distribution days спрямо прага, IEI/HYG RoC спрямо прага за override
    (с посоката), и близките прагове на VIX / MOVE / VIX term structure (само когато са близо).
"""
from __future__ import annotations

import re

import config

# Индикаторите, които могат да ФОРСИРАТ режима сами (override-и): VIX, MOVE, IEI/HYG. Останалите влияят само през броенето.
FORCING = ("VIX", "MOVE", "IEI/HYG")

# Ключови думи за разпознаване на индикатор в прозата (по нормализиран ключ) → име на индикатора започва с…
_ALIASES = (
    ("net liquidity", "Fed Net Liquidity"), ("нет ликвидност", "Fed Net Liquidity"), ("fed nl", "Fed Net Liquidity"),
    ("sofr", "SOFR − IORB"), ("iorb", "SOFR − IORB"),                                     # 16.10.2026: информативен
    ("put/call", "Put/Call"), ("put call", "Put/Call"), ("p/c", "Put/Call"),
    ("term structure", "VIX Term Structure"), ("term-structure", "VIX Term Structure"), ("contango", "VIX Term Structure"),
    ("iei/hyg", "IEI/HYG"), ("credit spread", "IEI/HYG"), ("кредитен спред", "IEI/HYG"),
    ("breadth", "Market Breadth"), ("ширина", "Market Breadth"), ("широчина", "Market Breadth"),
    ("2s10s", "2Y/10Y"), ("2y/10y", "2Y/10Y"), ("2/10", "2Y/10Y"),
    ("spy", "SPY тренд"), ("move", "MOVE"), ("vix", "VIX"),
)
_COLOR_WORD = {"зелен": "green", "жълт": "yellow", "червен": "red"}
_COLOR_BG = {"green": "зелени", "yellow": "жълти", "red": "червени"}
_COUNT = re.compile(r"(?<![\d.,/])(\d+)(?:\s*/\s*\d+)?\s+(зелен|жълт|червен)\w*", re.I)               # "7/8 зелени" = 7 зелени (от 8)
# изречения, които описват ПРАВИЛО/условие, а не днешното броене ("Offensive иска 4 зелени и 0 червени")
_RULE_WORDS = re.compile(r"изисква|иска|нужн|необходим|поне|най-малко|минимум|≥|праг|правило|за да|би |ако |когато|условие", re.I)
_SOLO = re.compile(r"само\s+по\s+себе\s+си|сам(?:а|о)?\s+по\s+себе\s+си|сам(?:а|о)?\s+(?:е\s+достатъчн|определя|дава|води|форсира|задейства)"
                   r"|единствен(?:о|ият|ата)\s+(?:причин|довод|фактор)|е\s+достатъчн\w*\s+сам", re.I)
_REGIME_WORD = re.compile(r"Defensive|Offensive|Cash|режим", re.I)
# 26.10.2026 (етап 4б, т. 4): твърдение за кредитен стрес / разширяване на кредитния риск; отрицание, контраст или условие в 40–60 знака преди фразата — не е твърдение
_C = r"(?:кредит\w*|credit)"
_CREDIT = re.compile(
    rf"{_C}\s+(?:\w+\s+){{0,1}}?(?:стрес\w*|stress|криза|срив\w*|влошаване|напрежение|distress)(?!\s+(?:gauge|индикатор\w*|мярка|измерител\w*|proxy|прокси))"
    rf"|(?:стрес\w*|stress|напрежение\w*)\s+(?:\w+\s+){{0,2}}?(?:в|на|от)\s+(?:\w+\s+){{0,1}}?{_C}"
    rf"|{_C}\s+пазар\w*\s+(?:[\w-]+\s+){{0,3}}?(?:потвържд\w*|сигнализ\w*|регистрир\w*)\s+(?:[\w-]+,?\s+){{0,3}}?(?:стрес\w*|влошаване|разширяване)"
    rf"|(?:credit\s+risk\s+premium|кредитн\w+\s+риск\w*(?:\s+premium)?)\s+(?:\w+\s+){{0,1}}?(?:се\s+)?разширява"
    rf"|разширяване\s+на\s+(?:кредитн\w+\s+риск\w*|credit\s+risk\s+premium)|spike\s+в\s+credit\s+risk\s+premium"
    rf"|(?:излиза|бяга|бягство)\w*\s+от\s+кредит\w*\s+риск", re.I)
_CREDIT_NEG = re.compile(r"(?:\bне\b|\bняма\b|\bнито\b|\bбез\b|повече\s+от|отколкото|вместо|\bниск\w*|\bслаб\w*|липс\w*)[^.;,—]{0,40}$", re.I)
_CREDIT_HYPO = re.compile(r"(?:\bако\b|\bби\b|\bще\b|\bкогато\b)[^.;]{0,60}$", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").lower()).strip()


def indicator_key(text: str) -> str | None:
    """Кой индикатор (по префикса на името му) се споменава в текста, или None."""
    t = _norm(text)
    for alias, name in _ALIASES:
        if alias in t:
            return name
    return None


def indicators_in(text: str) -> list[str]:
    """Всички различни индикатори, споменати в текста, в реда на първото им появяване."""
    t = _norm(text)
    found = sorted(((t.find(a), name) for a, name in _ALIASES if a in t), key=lambda x: x[0])
    out = []
    for _, name in found:
        if name not in out:
            out.append(name)
    return out


_NEGATION = re.compile(r"\bне\b|\bняма\b|\bнито\b|\bбез\b", re.I)


def _negated(sentence: str, m: re.Match) -> bool:
    """Има ли отрицание в близост до маркера ("не е достатъчен сам по себе си", "не тревога сама по себе си") — тогава твърдението е обратното."""
    lo, hi = max(0, m.start() - 60), min(len(sentence), m.end() + 60)
    return bool(_NEGATION.search(sentence[lo:hi]))


def facts(thermo: dict) -> dict:
    """
    Готовите факти за режима от термометъра: имената по цвят, изречението с броенето и правилото (числата идват от същите прагове като thermometer._count_regime).
    Празен/липсващ термометър → groups празни, текстовете казват, че броенето не е налично.
    """
    inds = (thermo or {}).get("indicators") or []
    counted = [i for i in inds if not i.get("informational")]
    visible = [i for i in counted if not i.get("hide")]
    groups = {c: [i["name"] for i in visible if i.get("status") == c] for c in ("green", "yellow", "red")}
    groups["hidden"] = [i["name"] for i in counted if i.get("hide")]
    groups["informational"] = [i["name"] for i in inds if i.get("informational")]
    if not visible:
        return {"groups": groups, "counts_text": "броенето не е налично днес (няма видими индикатори)", "rule_text": ""}

    def part(color: str, one: str, many: str) -> str:
        n = len(groups[color])
        names = f" ({', '.join(groups[color])})" if n else ""
        return f"{n} {one if n == 1 else many}{names}"

    counts = " / ".join([part("green", "зелен", "зелени"), part("yellow", "жълт", "жълти"), part("red", "червен", "червени")]) + f" от {len(visible)} видими"
    if groups["hidden"]:
        counts += f"; скрити (невалидни/застояли данни): {', '.join(groups['hidden'])}"
    if groups["informational"]:
        counts += f"; НЕ се броят (информативни): {', '.join(groups['informational'])}"
    # 15.10.2026: "един червен е достатъчен" е изрично — с "2 червени → Defensive" моделът написа, че при един червен режимът остава Offensive
    rule = (f"Правило по броенето: Offensive = поне 4 зелени, 0 червени и поне {config.THERMOMETER_MIN_VISIBLE_FOR_OFFENSIVE} видими индикатора — ЕДИН червен е достатъчен, "
            f"за да не е Offensive (1 или 2 червени → Defensive); 3 или повече червени → Cash; всичко друго → Defensive (недостатъчно потвърждение). "
            f"Единичен индикатор не дава Offensive или Cash сам; режимът се форсира до Defensive от override-ите ({', '.join(FORCING)}) и се ограничава до Defensive "
            f"от червените distribution days.")
    return {"groups": groups, "counts_text": counts, "rule_text": rule, "credit": _credit_legs(inds)}


def _credit_legs(inds: list[dict]) -> dict | None:
    """26.10.2026 (етап 4б, т. 4): разлагането на IEI/HYG от индикатора ({roc, iei, hyg, text}) или None без двата крака / скрит индикатор."""
    cr = next((i for i in inds if str(i.get("name", "")).startswith("IEI/HYG") and not i.get("hide")), None) or {}
    roc, iei, hyg = cr.get("roc_10d_pct"), cr.get("iei_10d_pct"), cr.get("hyg_10d_pct")
    if not all(isinstance(x, (int, float)) for x in (roc, iei, hyg)):
        return None
    thr = config.CREDIT_CLAIM_HYG_CONFIRM_PCT
    return {"roc": roc, "iei": iei, "hyg": hyg,
            "text": (f"Разлагане на IEI/HYG от кода: 10-дневната RoC {roc:+.2f}% — IEI {iei:+.2f}% (лихвеният крак), HYG {hyg:+.2f}% (кредитният крак); "
                     + ("скокът е от лихвите, кредитен стрес не е потвърден (иска HYG " + f"{thr:+.1f}% или по-малко за 10 сесии)." if hyg > thr
                        else "кредитният крак потвърждава движението."))}


_NUMW = {"нула": 0, "един": 1, "една": 1, "едно": 1, "два": 2, "две": 2, "три": 3, "четири": 4, "пет": 5, "шест": 6, "седем": 7, "осем": 8, "девет": 9}
_N = r"(\d+|нула|един|една|едно|два|две|три|четири|пет|шест|седем|осем|девет)"
_NEED = r"(?:нужн\w*|необходим\w*|трябва(?:т)?|изисква\w*|иска)"
_AT_LEAST = r"(?:поне\s+|най-малко\s+|минимум\s+|само\s+)?"
# (а) "нужни са 2 червени за Defensive" / "за Cash са нужни 2 червени"
_RED_FOR = re.compile(_NEED + r"\s+(?:са\s+|е\s+)?" + _AT_LEAST + _N + r"\s+червен\w*\s+(?:индикатор\w*\s+)?(?:,?\s*за(?:\s+да)?\s+(?:\w+\s+){0,2}?)(?:режим\s+)?(Defensive|Cash|Offensive)", re.I)
_FOR_RED = re.compile(r"\bза\s+(Defensive|Cash)\s+(?:са\s+|е\s+)?" + _NEED + r"\s+(?:са\s+)?" + _AT_LEAST + _N + r"\s+червен", re.I)
# (б) "ако един зелен стане червен …, системата пак остава Offensive"
_STAYS = re.compile(r"\b(?:един|една|1)\s+(?:\w+\s+){0,2}?(?:стане|станат|премине|мине|се обърне|е)\s+(?:в\s+)?червен\w*[^.;]{0,120}?"
                    r"(?:остава|запазва|пак|все още|продължава|не се (?:сменя|променя))[^.;]{0,40}?Offensive", re.I)
# (в) прагът на зелените за Offensive
_GREENS_A = re.compile(r"Offensive[^.;]{0,60}?" + _NEED + r"\s+(?:са\s+)?(?:само\s+|например\s+)?(поне\s+|най-малко\s+|минимум\s+|повече от\s+|над\s+)?(\d+)(?:\s*/\s*\d+)?\s+зелен", re.I)
_GREENS_B = re.compile(_NEED + r"[^.;]{0,30}?(поне\s+|най-малко\s+|минимум\s+|повече от\s+|над\s+)?(\d+)(?:\s*/\s*\d+)?\s+зелен\w*\s+за\s+(?:режим\s+)?Offensive", re.I)
# (г) "… 1 червен … нормалното правило би дало Offensive"
_WOULD = re.compile(r"би(?:ха)?\s+(?:\w+\s+){0,2}?(?:дал\w*|довел\w*\s+до|задействал\w*)\s+(?:режим\s+)?Offensive", re.I)
_MIN_RED = {"defensive": 1, "cash": 3, "offensive": 0}


def _num(w: str) -> int:
    w = w.lower()
    return int(w) if w.isdigit() else _NUMW[w]


def rule_problems(sentence: str) -> list[dict]:
    """
    15.10.2026: твърдения за ПРАВИЛОТО по броенето, които му противоречат (thermometer._count_regime: Offensive = ≥ 4 зелени и 0 червени; 1–2 червени → Defensive; ≥ 3 → Cash).
    Не зависи от днешното броене, освен (г), където червеният е посочен в самото изречение. Чиста функция.
    """
    out = []
    for m in _RED_FOR.finditer(sentence):
        n, regime = _num(m.group(1)), m.group(2).lower()
        if n != _MIN_RED[regime]:
            out.append({"code": "rule", "why": f"твърди, че за {m.group(2)} са нужни {n} червени — по правилото {'Offensive иска 0 червени' if regime == 'offensive' else ('един червен вече не е Offensive (→ Defensive)' if regime == 'defensive' else 'Cash е при 3 или повече червени')}"})
    for m in _FOR_RED.finditer(sentence):
        n, regime = _num(m.group(2)), m.group(1).lower()
        if n != _MIN_RED[regime]:
            out.append({"code": "rule", "why": f"твърди, че за {m.group(1)} са нужни {n} червени — по правилото {'един червен вече не е Offensive (→ Defensive)' if regime == 'defensive' else 'Cash е при 3 или повече червени'}"})
    if _STAYS.search(sentence):
        out.append({"code": "rule", "why": "твърди, че при един червен режимът остава Offensive — Offensive иска 0 червени"})
    for rx in (_GREENS_A, _GREENS_B):
        for m in rx.finditer(sentence):
            n = int(m.group(2)) + (1 if (m.group(1) or "").strip().lower() in ("повече от", "над") else 0)
            if n != 4:
                out.append({"code": "rule", "why": f"твърди, че Offensive иска {n} зелени — правилото иска поне 4 зелени и 0 червени"})
    if _WOULD.search(sentence) and any(_COLOR_WORD[c.group(2).lower()] == "red" and int(c.group(1)) >= 1 for c in _COUNT.finditer(sentence)):
        out.append({"code": "rule", "why": "твърди, че правилото би дало Offensive при червен индикатор — Offensive иска 0 червени"})
    return out


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZА-Я0-9«„\"(])", str(text or "").strip())
    return [p for p in parts if p]


def _members(sentence: str, start: int) -> list[str]:
    """Имената в скобите, които следват непосредствено числото ("3 жълти (Put/Call, MOVE, …)"), разделени със запетая/„и“."""
    m = re.match(r"\s*[\w\-]*\s*\(([^)]{0,200})\)", sentence[start:])
    if not m:
        return []
    return [p.strip() for p in re.split(r",|;|\s+и\s+", m.group(1)) if p.strip()]


# 16.10.2026 (т. 5, трети преглед): ХИПОТЕТИЧЕН брой не е днешният — "само 1 червен индикатор е достатъчен за преход към Defensive (сега 0 червени)" (16.10) беше заменен като
# "твърди 1 червени, а кодът брои 0". Брой, последван от "е достатъчен / за преход / за смяна / би / ще / стига", или предшестван от "ако / при / още / нов", не се сверява с броенето;
# "(сега 0 червени)" в същото изречение — се сверява.
_HYPO_AFTER = re.compile(r"^\W{0,3}(?:[\w-]+\s+){0,3}?(?:е\s+|са\s+)?(?:достатъч\w*|за\s+(?:преход|смяна|промяна)|би\b|биха\b|ще\b|стига\w*)", re.I)
# 20.10.2026 (етап 3, т. 4): брой, последван от "(сега N" — ЦЕЛ и текущото състояние ("До Offensive по броенето: 0 червени (сега 2) и още 1 зелен", 20.10 — преписано от реда
# "Запас до смяна на режима" на самия код); беше заменено като "твърди 0 червени, а кодът брои 2" и броенето излезе два пъти в коментара. В историята: 1 от 2 замени "count".
_TARGET_AFTER = re.compile(r"^\W{0,3}(?:[\w-]+\s+){0,2}?\(сега\b", re.I)
_HYPO_BEFORE = re.compile(r"(?:\bако|\bпри|\bоще|\bнов\w*|\bвтори|\bпоне)\s+(?:[\w-]+\s+){0,1}$", re.I)


def _hypothetical(sentence: str, m: re.Match) -> bool:
    after = sentence[m.end():m.end() + 60]
    return bool(_HYPO_AFTER.search(after) or _TARGET_AFTER.search(after) or _HYPO_BEFORE.search(sentence[max(0, m.start() - 30):m.start()]))


def check_sentence(sentence: str, f: dict) -> list[dict]:
    """Проблемите в едно изречение (празен списък = чисто)."""
    g = f["groups"]
    problems = []
    if f.get("counts_text") and "не е налично" not in f["counts_text"] and not _RULE_WORDS.search(sentence):
        for m in _COUNT.finditer(sentence):
            if _hypothetical(sentence, m):
                continue
            n, color = int(m.group(1)), _COLOR_WORD[m.group(2).lower()]
            if n != len(g[color]):
                problems.append({"code": "count", "why": f"твърди {n} {_COLOR_BG[color]}, а кодът брои {len(g[color])}"})
                continue
            for mem in _members(sentence, m.end()):
                key = indicator_key(mem)
                where = _group_of_by_name(g, key) if key else None
                if key and where and where != color:
                    problems.append({"code": "member", "why": f"{key} е посочен сред {_COLOR_BG[color]}, а кодът го води като {_GROUP_BG.get(where, where)}"})
    problems += rule_problems(sentence)                       # 15.10.2026: твърдения за правилото
    cr = f.get("credit")
    if cr and cr["hyg"] > config.CREDIT_CLAIM_HYG_CONFIRM_PCT:                 # 26.10.2026 (етап 4б, т. 4): кредитен стрес при HYG, който почти не мърда
        for m in _CREDIT.finditer(sentence):
            pre = sentence[:m.start()]
            if _CREDIT_NEG.search(pre) or _CREDIT_HYPO.search(pre):
                continue
            problems.append({"code": "credit", "why": f"твърди кредитен стрес («{m.group(0)}»), а HYG е {cr['hyg']:+.2f}% за 10 сесии (над {config.CREDIT_CLAIM_HYG_CONFIRM_PCT:+.1f}%) — "
                                                      f"скокът на IEI/HYG е от IEI ({cr['iei']:+.2f}%)"})
            break
    m = _SOLO.search(sentence)
    if m and _REGIME_WORD.search(sentence) and not _negated(sentence, m):
        named = indicators_in(sentence)
        # само ако в изречението няма индикатор, който МОЖЕ да форсира режима (VIX, MOVE, IEI/HYG), и има поне един, който не може.
        # 15.10.2026: ЧЕРВЕН индикатор сам по себе си наистина прави режима Defensive (Offensive иска 0 червени) — такова твърдение е вярно
        red_def = bool(re.search(r"Defensive", sentence)) and all(_group_of_by_name(g, n) == "red" for n in named)
        if named and not any(n.startswith(FORCING) for n in named) and not red_def:
            problems.append({"code": "solo", "why": f"твърди, че индикатор ({named[0]}) определя режима сам по себе си — по броенето нито един не го прави (форсират само {', '.join(FORCING)})"})
    return problems


_GROUP_BG = {"green": "зелен", "yellow": "жълт", "red": "червен", "hidden": "скрит", "informational": "информативен (не се брои)"}


def _group_of_by_name(groups: dict, prefix: str) -> str | None:
    """Към коя група е името: първо точно съвпадение ("VIX"), после начало на името до граница ("MOVE" → "MOVE (Bond Vol)")."""
    for color, names in groups.items():
        if prefix in names:
            return color
    for color, names in groups.items():
        if any(str(n).startswith(prefix) and (len(str(n)) == len(prefix) or str(n)[len(prefix)] in " (/") for n in names):
            return color
    return None


def check(text: str, f: dict) -> list[dict]:
    out = []
    for s in _sentences(text):
        for p in check_sentence(s, f):
            out.append({"sentence": s, **p})
    return out


def clean(text: str, f: dict) -> tuple[str, list[dict]]:
    """
    Поправя изреченията с проблем и връща (нов текст, проблемите):
      • count / member (грешно броене или индикатор в грешна група) — първото такова изречение се ЗАМЕНЯ с броенето от кода ("По броенето: …."), следващите се махат;
      • rule (15.10.2026: твърдение, противоречащо на правилото) — първото такова изречение се ЗАМЕНЯ с rule_text, следващите се махат;
      • credit (26.10.2026: кредитен стрес при HYG над прага) — първото такова изречение се ЗАМЕНЯ с разлагането от кода (credit.text), следващите се махат;
      • solo (индикатор "сам по себе си" определя режима) — изречението се маха.
    Нищо за поправяне → същият текст.
    """
    sents = _sentences(text)
    out, problems, replaced, rule_replaced, credit_replaced = [], [], False, False, False
    for s in sents:
        p = check_sentence(s, f)
        if not p:
            out.append(s)
            continue
        problems += [{"sentence": s, **x} for x in p]
        if any(x["code"] in ("count", "member") for x in p) and not replaced and f.get("counts_text") and "не е налично" not in f["counts_text"]:
            out.append(f"По броенето: {f['counts_text']}.")
            replaced = True
        if any(x["code"] == "rule" for x in p) and not rule_replaced and f.get("rule_text"):
            out.append(f["rule_text"])
            rule_replaced = True
        if any(x["code"] == "credit" for x in p) and not credit_replaced and (f.get("credit") or {}).get("text"):
            out.append(f["credit"]["text"])
            credit_replaced = True
    return (" ".join(out) if problems else str(text or "")), problems


# 28.10.2026: изтекла проверка от промпта — „Никоя от наличните стойности не е null/nan.“ (28.10). Промптът казва: ако индикатори липсват / са скрити / съдържат null/nan — кажи го;
# когато няма такива, моделът пише, че няма. Клауза (разделители „ — “, „; “, „, но “), която твърди, че данните са без null/nan / валидни / пълни, се маха; клаузата за СКРИТ или
# ЛИПСВАЩ индикатор („MOVE е скрит поради null стойности“) е информация и остава. Измерено върху всичките брифове: виж strip_meta и test_meta_sentences.
_META_NULL = re.compile(r"\bnull\b|\bnan\b|невалидни\s+стойност|наличните\s+стойност", re.I)
_META_NEG = re.compile(r"\b(?:няма|нито|никоя|никой|никакви|без|не\s+е|не\s+съдържа|не\s+показва|не\s+компрометират|валидни|пълни|присъстват|попълнени)\b", re.I)   # „невалидни“ не е „валидни“
_META_VALID = re.compile(r"(?:\bвсички(?:те)?\s+(?:\d+\s+)?(?:\w+\s+)?|\b(?:индикаторите|данните|стойностите)\s+)(?:са\s+|имат\s+)(?:с\s+)?(?:присъстващи\s+и\s+)?"
                         r"(?:валидни|налични|попълнени|пълни|присъстващи)\b", re.I)
_META_HIDDEN = re.compile(r"(?<!няма )(?<!без )(?<!нито )\bскрит\w*|(?<!няма )\bлипсва\w*|\bотсъств\w*", re.I)
_META_SEP = re.compile(r"( — |; |, но )")


def _meta_clause(c: str) -> bool:
    if _META_HIDDEN.search(c):
        return False                                                             # скрит / липсващ индикатор — информация, не проверка
    return bool((_META_NULL.search(c) and _META_NEG.search(c)) or _META_VALID.search(c))


def strip_meta(text: str) -> tuple[str, list[dict]]:
    """28.10.2026: маха клаузите-проверки на данните („без null/nan“, „всички индикатори са валидни“); изречение само от такива клаузи пада цяло. (нов текст, [{sentence, removed, kept}])."""
    out, probs = [], []
    for s in _sentences(text):
        parts = _META_SEP.split(s)
        clauses, seps = parts[0::2], parts[1::2]
        drop = [_meta_clause(c) for c in clauses]
        if not any(drop):
            out.append(s)
            continue
        kept = ""
        for i, c in enumerate(clauses):
            if drop[i]:
                continue
            kept += (seps[i - 1] if kept and i > 0 else "") + c
        kept = kept.strip()
        if kept and kept[-1] not in ".!?":
            kept += "."
        if kept:
            kept = kept[0].upper() + kept[1:]
            out.append(kept)
        probs.append({"sentence": s, "removed": [c for c, d in zip(clauses, drop) if d], "kept": kept or None})
    return (" ".join(out) if probs else str(text or "")), probs


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def margin(thermo: dict | None, distribution_days: dict | None = None, dd_status: dict | None = None) -> dict:
    """
    15.10.2026 · "Запас до смяна на режима" — готово от кода (за картата на термометъра и за макро промпта): {"text", "parts"}. Части:
      • броенето: колко червени сменят режима по правилото (Offensive → 1 червен → Defensive; Defensive → до Offensive / до Cash; Cash → до Defensive) + зелени/видими спрямо минимума;
        активен override → режимът е Defensive независимо от броенето;
      • distribution days: SPY и QQQ спрямо DISTRIBUTION_DAYS_RED (при прага Offensive се блокира; блокът пада след 2 поредни нечервени дни);
      • IEI/HYG: 10д RoC percentile спрямо прага за override (≥ прага → червен + override Defensive) и посоката (roc_trend_text);
      • близки прагове, само ако са близо (config.REGIME_MARGIN_*): VIX към 30, MOVE към 150 / седмична делта към +15, VIX term structure към 1.0.
    Без индикатори → {"text": "", "parts": []}. Чиста функция, не вдига.
    """
    try:
        t = thermo or {}
        inds = t.get("indicators") or []
        if not inds:
            return {"text": "", "parts": []}
        f = facts(t)
        g = f["groups"]
        G, R = len(g["green"]), len(g["red"])
        V = G + len(g["yellow"]) + R
        mv = config.THERMOMETER_MIN_VISIBLE_FOR_OFFENSIVE
        parts = []
        trig = [o.get("trigger") for o in t.get("overrides") or [] if o.get("trigger")]
        if trig:
            parts.append(f"активен override ({', '.join(trig)}) — режимът е Defensive независимо от броенето")
        reds = f": {', '.join(g['red'])}" if R else ""
        if R == 0 and G >= 4 and V >= mv:
            parts.append(f"по броенето Offensive: 1 червен → Defensive (сега 0 червени; зелени {G}, минимум 4; видими {V}, минимум {mv})")
        elif R == 0:
            need = ([f"още {_plural(4 - G, 'зелен', 'зелени')}"] if G < 4 else []) + ([f"още {_plural(mv - V, 'видим', 'видими')}"] if V < mv else [])
            parts.append(f"по броенето до Offensive: {' и '.join(need)} при 0 червени; до Cash: 3 червени")
        elif R < 3:
            extra = f" и още {_plural(4 - G, 'зелен', 'зелени')}" if G < 4 else ""
            parts.append(f"по броенето до Offensive: 0 червени (сега {R}{reds}){extra}; до Cash: още {_plural(3 - R, 'червен', 'червени')}")
        else:
            parts.append(f"по броенето до Defensive: под 3 червени (сега {R}{reds})")
        dd = distribution_days or {}
        red = config.DISTRIBUTION_DAYS_RED
        sc, qc = dd.get("spy_count"), dd.get("qqq_count")
        if (dd_status or {}).get("status") == "failed" and sc is None and qc is None:          # 16.10.2026 (В8)
            parts.append("distribution days: не се изтеглиха днес (нито SPY, нито QQQ) — блокът на Offensive не е проверен")
        if sc is not None or qc is not None:
            nums = ", ".join(f"{n} {c}/{red}" for n, c in (("SPY", sc), ("QQQ", qc)) if c is not None)
            if dd.get("missing"):                                                             # 16.10.2026 (В8): единият индекс липсва — изрично
                nums += f" ({dd['missing'][0]} не се изтегли днес)"
            top = max(c for c in (sc, qc) if c is not None)
            if top >= red:
                parts.append(f"distribution days {nums} — червени: Offensive е блокиран; блокът пада след {config.DISTRIBUTION_DAYS_RELEASE_NONRED_DAYS} поредни дни под {red}")
            elif t.get("distribution_cap"):
                parts.append(f"distribution days {nums} — под прага, но блокът на Offensive се държи по хистерезис")
            else:
                parts.append(f"distribution days {nums} — при {red} Offensive се блокира (липсва{'т' if red - top > 1 else ''} {red - top})")
        by = {i.get("name"): i for i in inds if not i.get("hide")}
        cr = next((i for n, i in by.items() if str(n).startswith("IEI/HYG")), None)
        if cr and cr.get("roc_percentile") is not None:
            from src.thermometer import _pct_ord
            thr = config.IEI_HYG_ROC_SPIKE_PERCENTILE
            p = float(cr["roc_percentile"])
            held = next((o for o in t.get("overrides") or [] if o.get("trigger") == "IEI/HYG"), None)
            if p >= thr:
                head = f"IEI/HYG 10д RoC {_pct_ord(p)} percentile — над прага {thr:.0f}: override"
            elif held:
                head = f"IEI/HYG 10д RoC {_pct_ord(p)} percentile — под прага {thr:.0f}, но override-ът се държи по хистерезис (2 поредни дни под прага)"
            else:
                head = f"IEI/HYG 10д RoC {_pct_ord(p)} percentile при праг {thr:.0f} (≥ {thr:.0f} → червен и override Defensive)"
            parts.append(head + (f"; {cr['roc_trend_text']}" if cr.get("roc_trend_text") else ""))
        vix = (by.get("VIX") or {}).get("value")
        if isinstance(vix, (int, float)) and config.REGIME_MARGIN_VIX_NEAR <= vix <= config.VIX_DEFENSIVE_THRESHOLD:
            parts.append(f"VIX {vix:.1f} (override над {config.VIX_DEFENSIVE_THRESHOLD:.0f})")
        mo = next((i for n, i in by.items() if str(n).startswith("MOVE")), None) or {}
        mval, mdel = mo.get("value"), mo.get("delta_1w")
        if isinstance(mval, (int, float)) and config.REGIME_MARGIN_MOVE_NEAR <= mval <= config.MOVE_RED_THRESHOLD:
            parts.append(f"MOVE {mval:.0f} (override над {config.MOVE_RED_THRESHOLD:.0f})")
        if isinstance(mdel, (int, float)) and config.REGIME_MARGIN_MOVE_DELTA_NEAR <= mdel < config.MOVE_SPIKE_WEEKLY_DELTA:
            parts.append(f"MOVE {mdel:+.1f} пункта за седмица (override при +{config.MOVE_SPIKE_WEEKLY_DELTA:.0f})")
        term = (by.get("VIX Term Structure") or {}).get("value")
        if isinstance(term, (int, float)) and config.REGIME_MARGIN_TERM_NEAR <= term < config.VIX_TERM_WARNING_THRESHOLD:
            parts.append(f"VIX term structure {term:.2f} (жълт от {config.VIX_TERM_WARNING_THRESHOLD:.2f}, червен от {config.VIX_TERM_BACKWARDATION_THRESHOLD:.2f})")
        return {"text": "Запас до смяна на режима: " + " · ".join(parts), "parts": parts}
    except Exception as e:
        print(f"[regime_claims] запасът до смяна на режима не се смята: {type(e).__name__}: {e}")
        return {"text": "", "parts": []}
