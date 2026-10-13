"""
Твърдения на модела за секторите по RS (13.10.2026) — готов факт от кода + проверка на "единствен" в прозата. Чисти функции, без мрежа и без AI (по модела на regime_claims).

Реален дефект (брифът от 13.10): веригата за XLK казваше "…е единственият сектор с положителна RS на двата хоризонта", а в ротацията на същия ден XLV (+0.39 / +5.54) и XLE (+0.38 / +13.73)
също бяха положителни и на двата; изречението беше преписано и в наратива на ANET (моделът за тикърите получава веригите). Измерено върху 55 брифа с ротация: проверимите твърдения
"единствен … положителна RS" бяха грешни в повечето случаи (31.07 XLF при XLF+XLV, 13.08 XLE при 5 сектора, 17–18.08 ITA при 3–4, 09.10 и 13.10 XLK).

  • facts(rotation) — секторите с положителна RS за 4 седмици, за 12 седмици и на двата (rs_chg_4w_pct / rs_chg_12w_pct > 0) и готовото изречение за промпта.
  • check(text, f, default_etf) — твърдения "единствен(ият) сектор/ETF с положителна RS {на двата хоризонта | 4W | 12W}", които противоречат на таблицата. Квалифицирани ("извън XLK",
    "освен XLV", "defensive", "non-…") и такива без определим хоризонт не се пипат — не могат да се проверят.
  • clean(text, f, default_etf) — замества фразата: подлогът е сред секторите → "е сред секторите с положителна RS … (списък)"; иначе — "по таблицата положителна RS … имат …".
"""
from __future__ import annotations

import re

_ETF = r"\b(XL[A-Z]{1,2}|SMH|XBI|ITA|TAN|GDX|URA)\b"
_CLAIM = re.compile(r"(?P<pre>\bе\s+)?(?P<word>единствени(?:ят|я)|единственото|единствената|единствен)\s+(?P<adj>(?:[\w-]+\s+){0,2}?)(?:сектор|ETF)\s+с\s+"
                    r"(?:потвърдена\s+|устойчива\s+)?(?:положителна|позитивна)\s+(?P<mid>[^;→(),:]{0,40}?)\bRS\b(?P<tail>(?:\s+(?:и\s+)?(?:на|за|по)\s+[^;→(),:.—]{1,40})?)", re.I)
# продължение на твърдението с ВТОРИЯ хоризонт: "… и на 4w (+4.62%), и на 12w (+6.04%)", "… 12W RS + положителна 4W RS", "… (4W и 12W)" → и двата; поглъща се със замяната
_MORE = re.compile(r"^\s*(?:\([^)]{0,30}\))?\s*,?\s*(?:(?:и|И|\+)\s+(?:на\s+)?(?:положителна\s+)?(?:4|12)\s*[wW]\w*(?:\s+RS)?\s*(?:\([^)]{0,30}\))?"
                   r"|\(\s*(?:4|12)\s*[wW]\w*\s*(?:и|,|/|И)\s*(?:4|12)\s*[wW]\w*\s*\))")
_QUAL = re.compile(r"извън|освен", re.I)                                     # "единственият сектор извън XLK …" — квалифицирано, не се проверява
_BOTH = re.compile(r"двата|двете|4\s*[wWсs]\w*\s*(?:и|И|AND|and|\+)\s*(?:на\s+)?12|4\s*и\s*12|краткосрочна\s+и\s+средносрочна", re.I)
_4W = re.compile(r"\b4\s*[wW]\b|4-седм|4\s+седм|краткосроч", re.I)
_12W = re.compile(r"\b12\s*[wW]\b|12-седм|12\s+седм|средносроч", re.I)
_SCOPE_BG = {"both": "на двата хоризонта (4 и 12 седмици)", "4w": "за 4 седмици", "12w": "за 12 седмици"}


def facts(rotation: list[dict] | None) -> dict:
    rows = [r for r in (rotation or []) if isinstance(r, dict) and r.get("etf")]
    pos = lambda k: [r["etf"] for r in rows if isinstance(r.get(k), (int, float)) and r[k] > 0]
    p4, p12 = pos("rs_chg_4w_pct"), pos("rs_chg_12w_pct")
    both = [e for e in p4 if e in p12]
    lst = lambda xs: ", ".join(xs) if xs else "нито един"
    return {"pos_4w": p4, "pos_12w": p12, "both": both,
            "text": (f"Сектори с положителна RS и на 4, и на 12 седмици: {lst(both)}; само за 4 седмици: {lst([e for e in p4 if e not in both])}; "
                     f"само за 12 седмици: {lst([e for e in p12 if e not in both])}.")}


def _scope(s: str) -> str | None:
    if _BOTH.search(s):
        return "both"
    a, b = bool(_4W.search(s)), bool(_12W.search(s))
    return "4w" if a and not b else "12w" if b and not a else None


def _segments(text: str) -> list[tuple[int, int]]:
    """Граници на сегментите: изречение (. ! ? последвани от интервал — не десетична точка), "; " и "→"."""
    out, start = [], 0
    for m in re.finditer(r"(?<=[.!?;])\s+|\s*→\s*", text):
        out.append((start, m.start()))
        start = m.end()
    out.append((start, len(text)))
    return [(a, b) for a, b in out if b > a]


def check(text: str, f: dict, default_etf: str | None = None) -> list[dict]:
    """[{start, end, subject, scope, listed, replacement, sentence}] за всяко противоречащо твърдение; позициите са в `text`."""
    out = []
    for a, b in _segments(text or ""):
        seg = text[a:b]
        for m in _CLAIM.finditer(seg):
            claim = m.group(0)
            if m.group("adj").strip() or _QUAL.search(seg[m.start():m.end() + 30]):       # "единственият defensive / leading / clean energy сектор", "… извън XLK" — друго твърдение
                continue
            scope = _scope(m.group("mid") + "RS" + m.group("tail"))
            end = m.end()
            more = _MORE.match(seg[end:])
            if more and more.group(0).strip():
                scope, end = "both", end + more.end()
            if not scope:
                continue
            listed = f[{"both": "both", "4w": "pos_4w", "12w": "pos_12w"}[scope]]
            before = re.findall(_ETF, seg[:m.start()])
            subject = before[-1] if before else default_etf
            if len(listed) == 1 and (subject is None or subject == listed[0]):
                continue                                                     # вярно (или подлогът не е известен при единствен в таблицата)
            names = ", ".join(listed) if listed else "нито един сектор"
            if subject and subject in listed:
                rep = f"{m.group('pre') or ''}сред секторите с положителна RS {_SCOPE_BG[scope]} ({names})"
            else:
                rep = f"{m.group('pre') or ''}— по таблицата положителна RS {_SCOPE_BG[scope]} имат: {names}"
            if end < len(seg) and not seg[end].isspace() and seg[end] not in ".,;:)":
                rep += " "
            out.append({"start": a + m.start(), "end": a + end, "subject": subject, "scope": scope, "listed": listed, "replacement": rep, "sentence": seg.strip()})
    return out


def clean(text: str, f: dict, default_etf: str | None = None) -> tuple[str, list[dict]]:
    """Замества противоречащите твърдения (от края към началото, за да не се местят позициите); връща (нов текст, проблеми)."""
    probs = check(text, f, default_etf)
    new = text
    for p in sorted(probs, key=lambda x: x["start"], reverse=True):
        new = new[:p["start"]] + p["replacement"] + new[p["end"]:]
    return new, probs
