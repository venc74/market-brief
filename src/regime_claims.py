"""
Броенето на термометъра и причината за режима като ГОТОВИ низове от кода + проверка на числовите твърдения на модела (08.10.2026). Чисти функции, без мрежа и без AI.

Реален дефект (макро текстът на 08.10): моделът изброи Fed Net Liquidity сред 3-те жълти ("… Fed Net Liquidity — последният само информативен и не влиза в броенето"), докато кодът
брои като жълти Put/Call, MOVE и Market Breadth; и твърдеше, че Market Breadth "само по себе си дава Defensive" — не дава (режимът по броенето иска ≥ 2 червени за Defensive по правило
или недостатъчно потвърждение за Offensive; единични индикатори форсират режим само през override-ите VIX, MOVE, IEI/HYG и през червените distribution days).

  • facts(thermo) — {groups, counts_text, rule_text}: кои индикатори са зелени/жълти/червени/скрити/информативни (по имена) и готовите изречения; влизат в промпта, моделът ги копира, не преброява.
  • check(text, facts) — открива в прозата (а) брой "N зелени/жълти/червени", който не съвпада с кода, или посочен в скоби индикатор от друг цвят/информативен; (б) твърдение, че индикатор,
    който НЕ може да форсира режим, го определя "сам по себе си".
  • clean(text, facts) — маха изреченията с такива твърдения; връща (нов текст, [{sentence, code, why}]).
"""
from __future__ import annotations

import re

import config

# Индикаторите, които могат да ФОРСИРАТ режима сами (override-и): VIX, MOVE, IEI/HYG. Останалите влияят само през броенето.
FORCING = ("VIX", "MOVE", "IEI/HYG")

# Ключови думи за разпознаване на индикатор в прозата (по нормализиран ключ) → име на индикатора започва с…
_ALIASES = (
    ("net liquidity", "Fed Net Liquidity"), ("нет ликвидност", "Fed Net Liquidity"), ("fed nl", "Fed Net Liquidity"),
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
    rule = (f"Правило по броенето: Offensive = поне 4 зелени, 0 червени и поне {config.THERMOMETER_MIN_VISIBLE_FOR_OFFENSIVE} видими индикатора; "
            f"2 червени → Defensive; 3 или повече червени → Cash; всичко друго → Defensive (недостатъчно потвърждение). Нито един единичен индикатор не определя режима сам по броенето; "
            f"режимът се форсира САМО от override-ите ({', '.join(FORCING)}) и се ограничава до Defensive от червените distribution days.")
    return {"groups": groups, "counts_text": counts, "rule_text": rule}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZА-Я0-9«„\"(])", str(text or "").strip())
    return [p for p in parts if p]


def _members(sentence: str, start: int) -> list[str]:
    """Имената в скобите, които следват непосредствено числото ("3 жълти (Put/Call, MOVE, …)"), разделени със запетая/„и“."""
    m = re.match(r"\s*[\w\-]*\s*\(([^)]{0,200})\)", sentence[start:])
    if not m:
        return []
    return [p.strip() for p in re.split(r",|;|\s+и\s+", m.group(1)) if p.strip()]


def check_sentence(sentence: str, f: dict) -> list[dict]:
    """Проблемите в едно изречение (празен списък = чисто)."""
    g = f["groups"]
    problems = []
    if f.get("counts_text") and "не е налично" not in f["counts_text"] and not _RULE_WORDS.search(sentence):
        for m in _COUNT.finditer(sentence):
            n, color = int(m.group(1)), _COLOR_WORD[m.group(2).lower()]
            if n != len(g[color]):
                problems.append({"code": "count", "why": f"твърди {n} {_COLOR_BG[color]}, а кодът брои {len(g[color])}"})
                continue
            for mem in _members(sentence, m.end()):
                key = indicator_key(mem)
                where = _group_of_by_name(g, key) if key else None
                if key and where and where != color:
                    problems.append({"code": "member", "why": f"{key} е посочен сред {_COLOR_BG[color]}, а кодът го води като {_GROUP_BG.get(where, where)}"})
    m = _SOLO.search(sentence)
    if m and _REGIME_WORD.search(sentence) and not _negated(sentence, m):
        named = indicators_in(sentence)
        # само ако в изречението няма индикатор, който МОЖЕ да форсира режима (VIX, MOVE, IEI/HYG), и има поне един, който не може
        if named and not any(n.startswith(FORCING) for n in named):
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
      • solo (индикатор "сам по себе си" определя режима) — изречението се маха.
    Нищо за поправяне → същият текст.
    """
    sents = _sentences(text)
    out, problems, replaced = [], [], False
    for s in sents:
        p = check_sentence(s, f)
        if not p:
            out.append(s)
            continue
        problems += [{"sentence": s, **x} for x in p]
        if any(x["code"] in ("count", "member") for x in p) and not replaced and f.get("counts_text") and "не е налично" not in f["counts_text"]:
            out.append(f"По броенето: {f['counts_text']}.")
            replaced = True
    return (" ".join(out) if problems else str(text or "")), problems
