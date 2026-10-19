"""
Твърдения на модела за секторите по RS (13.10.2026) — готов факт от кода + проверка на "единствен" в прозата. Чисти функции, без мрежа и без AI (по модела на regime_claims).

Реален дефект (брифът от 13.10): веригата за XLK казваше "…е единственият сектор с положителна RS на двата хоризонта", а в ротацията на същия ден XLV (+0.39 / +5.54) и XLE (+0.38 / +13.73)
също бяха положителни и на двата; изречението беше преписано и в наратива на ANET (моделът за тикърите получава веригите). Измерено върху 55 брифа с ротация: проверимите твърдения
"единствен … положителна RS" бяха грешни в повечето случаи (31.07 XLF при XLF+XLV, 13.08 XLE при 5 сектора, 17–18.08 ITA при 3–4, 09.10 и 13.10 XLK).

  • facts(rotation) — секторите с положителна RS за 4 седмици, за 12 седмици и на двата (rs_chg_4w_pct / rs_chg_12w_pct > 0) и готовото изречение за промпта; 15.10.2026: и кои са на
    6-месечен връх по RS (rs_at_6m_high — до 1% под 6-месечния максимум). Веригата за XLE на 15.10: "единственият сектор с потвърдено лидерство на двата времеви хоризонта и на 6m RS
    high" — на двата хоризонта бяха XLE, XLV и XLK, а само 6-месечният връх е на XLE. Измерено върху 87 брифа: 11 твърдения "единствен … лидерство / 6-месечен връх" — тези за
    6-месечния връх 8 от 8 верни; "двойно потвърдено лидерство" на 13.08 — грешно (5 сектора).
  • check(text, f, default_etf) — твърдения "единствен(ият) сектор/ETF с положителна RS {на двата хоризонта | 4W | 12W}", които противоречат на таблицата. Квалифицирани ("извън XLK",
    "освен XLV", "defensive", "non-…") и такива без определим хоризонт не се пипат — не могат да се проверят.
  • clean(text, f, default_etf) — замества фразата: подлогът е сред секторите → "е сред секторите с положителна RS … (списък)"; иначе — "по таблицата положителна RS … имат …".
  • 19.10.2026 (етап 2, т. 5): при противоречие се заменя ЦЯЛОТО изречение с изречение от кода (subject_sentence / table_sentence) — частичната замяна оставяше разбито изречение
    (19.10 XLE: "… е сред секторите с положителна RS за 4 седмици (XLE, XLP, XLV, XLU, XLB, XLY) (+6.52%), и на 12-седмичен хоризонт (+14.76%), и на 6-месечен връх …"); "12-седмичен
    хоризонт" като втори хоризонт; "… положителна 4W RS ПРИ отрицателна 12W RS" е твърдение за "само 4 седмици" (05.08: XLE — вярно, а кодът го "поправяше").
"""
from __future__ import annotations

import re

_ETF = r"\b(XL[A-Z]{1,2}|SMH|XBI|ITA|TAN|GDX|URA)\b"
_CLAIM = re.compile(r"(?P<pre>\bе\s+)?(?P<word>единствени(?:ят|я)|единственото|единствената|единствен)\s+(?P<adj>(?:[\w-]+\s+){0,2}?)(?:сектор|ETF)\s+с\s+"
                    r"(?:потвърдена\s+|устойчива\s+)?(?:положителна|позитивна)\s+(?P<mid>[^;→(),:]{0,40}?)\bRS\b(?P<tail>(?:\s+(?:и\s+)?(?:на|за|по)\s+[^;→(),:.—]{1,40})?)", re.I)
# продължение на твърдението с ВТОРИЯ хоризонт: "… и на 4w (+4.62%), и на 12w (+6.04%)", "… 12W RS + положителна 4W RS", "… (4W и 12W)" → и двата; поглъща се със замяната
_MORE = re.compile(r"^\s*(?:\([^)]{0,30}\))?\s*,?\s*(?:(?:и|И|\+)\s+(?:на\s+)?(?:положителна\s+)?(?:4|12)(?:\s*[wW]\w*|-?\s*седм\w*)(?:\s+хоризонт\w*)?(?:\s+RS)?\s*(?:\([^)]{0,30}\))?"
                   r"|\(\s*(?:4|12)\s*[wW]\w*\s*(?:и|,|/|И)\s*(?:4|12)\s*[wW]\w*\s*\))")
# "… положителна 4W RS (+3.82%) ПРИ отрицателна 12W RS" — твърдение за "само 4 седмици" (и обратно); проверява се срещу only_4w / only_12w
_ONLY = re.compile(r"^\s*(?:\([^)]{0,30}\))?\s*,?\s*(?:при|и|но|с|а)\s+(?:отрицателна|негативна)\s+(4|12)\s*(?:[wW]|-?\s*седм)", re.I)
_QUAL = re.compile(r"извън|освен", re.I)                                     # "единственият сектор извън XLK …" — квалифицирано, не се проверява
_BOTH = re.compile(r"двата|двете|4\s*[wWсs]\w*\s*(?:и|И|AND|and|\+)\s*(?:на\s+)?12|4\s*и\s*12|краткосрочна\s+и\s+средносрочна", re.I)
_4W = re.compile(r"\b4\s*[wW]\b|4-седм|4\s+седм|краткосроч", re.I)
_12W = re.compile(r"\b12\s*[wW]\b|12-седм|12\s+седм|средносроч", re.I)
_SCOPE_BG = {"both": "на двата хоризонта (4 и 12 седмици)", "4w": "за 4 седмици", "12w": "за 12 седмици",
             "only_4w": "само за 4 седмици (при отрицателна за 12)", "only_12w": "само за 12 седмици (при отрицателна за 4)"}
_SCOPE_KEY = {"both": "both", "4w": "pos_4w", "12w": "pos_12w", "only_4w": "only_4w", "only_12w": "only_12w"}


def facts(rotation: list[dict] | None) -> dict:
    rows = [r for r in (rotation or []) if isinstance(r, dict) and r.get("etf")]
    pos = lambda k: [r["etf"] for r in rows if isinstance(r.get(k), (int, float)) and r[k] > 0]
    p4, p12 = pos("rs_chg_4w_pct"), pos("rs_chg_12w_pct")
    both = [e for e in p4 if e in p12]
    high = [r["etf"] for r in rows if r.get("rs_at_6m_high") is True]
    lst = lambda xs: ", ".join(xs) if xs else "нито един"
    return {"pos_4w": p4, "pos_12w": p12, "both": both, "at_6m_high": high,
            "only_4w": [e for e in p4 if e not in both], "only_12w": [e for e in p12 if e not in both],
            "text": (f"Сектори с положителна RS и на 4, и на 12 седмици: {lst(both)}; само за 4 седмици: {lst([e for e in p4 if e not in both])}; "
                     f"само за 12 седмици: {lst([e for e in p12 if e not in both])}. "
                     f"На 6-месечен връх по RS (до 1% под 6-месечния максимум): {lst(high)}.")}


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


def _lst(xs: list[str]) -> str:
    return ", ".join(xs) if xs else "нито един"


def subject_sentence(subject: str, f: dict) -> str:
    """Изречение от кода за сектора `subject` (без крайна точка): RS на двата хоризонта / само на единия / без, и 6-месечният връх — всичко по таблицата на ротацията."""
    others = lambda xs: [x for x in xs if x != subject]
    if subject in f["both"]:
        rs = "положителна RS и на 4, и на 12 седмици" + (f" — заедно с {', '.join(others(f['both']))}" if others(f["both"]) else " — единственият на двата хоризонта")
    elif subject in f["pos_4w"]:
        rs = f"положителна RS само за 4 седмици (и на двата хоризонта: {_lst(f['both'])})"
    elif subject in f["pos_12w"]:
        rs = f"положителна RS само за 12 седмици (и на двата хоризонта: {_lst(f['both'])})"
    else:
        rs = f"без положителна RS за 4 и 12 седмици (и на двата хоризонта: {_lst(f['both'])})"
    hi = ""
    if subject in f.get("at_6m_high", []):
        hi = "; на 6-месечен връх по RS" + (f" — заедно с {', '.join(others(f['at_6m_high']))}" if others(f["at_6m_high"]) else "")
    return f"{subject}: {rs}{hi} (по таблицата на ротацията)"


def table_sentence(f: dict) -> str:
    """Изречение от кода без подлог (без крайна точка)."""
    return (f"По таблицата на ротацията положителна RS и на 4, и на 12 седмици имат {_lst(f['both'])}; само за 4 седмици — {_lst(f['only_4w'])}; "
            f"само за 12 седмици — {_lst(f['only_12w'])}")


def check(text: str, f: dict, default_etf: str | None = None) -> list[dict]:
    """
    [{start, end, subject, scope, listed, replacement, sentence}] за всяко изречение с противоречащо твърдение; позициите са в `text` и покриват ЦЯЛОТО изречение (сегмент),
    а replacement е изречение от кода със същия завършек (". " / ";").
    """
    out = []
    for a, b in _segments(text or ""):
        seg = text[a:b]
        hit = None
        for m in _CLAIM.finditer(seg):
            claim = m.group(0)
            if m.group("adj").strip() or _QUAL.search(seg[m.start():m.end() + 30]):       # "единственият defensive / leading / clean energy сектор", "… извън XLK" — друго твърдение
                continue
            scope = _scope(m.group("mid") + "RS" + m.group("tail"))
            end = m.end()
            more = _MORE.match(seg[end:])
            if more and more.group(0).strip():
                scope, end = "both", end + more.end()
            only = _ONLY.match(seg[end:])
            if only and scope in ("4w", "12w") and only.group(1) != scope[:-1]:
                scope = "only_" + scope                                       # "положителна 4W … ПРИ отрицателна 12W" — "само 4 седмици"
            if not scope:
                continue
            listed = f[_SCOPE_KEY[scope]]
            before = re.findall(_ETF, seg[:m.start()])
            subject = before[-1] if before else default_etf
            if len(listed) == 1 and (subject is None or subject == listed[0]):
                continue                                                     # вярно (или подлогът не е известен при единствен в таблицата)
            hit = {"subject": subject, "scope": scope, "listed": listed}
            break
        if not hit:
            continue
        body = seg.rstrip()
        term = body[-1] if body[-1:] in ".!?;" else ""
        rep = (subject_sentence(hit["subject"], f) if hit["subject"] else table_sentence(f)) + (term or ".")
        out.append({"start": a, "end": a + len(body), **hit, "replacement": rep, "sentence": seg.strip()})
    return out


def clean(text: str, f: dict, default_etf: str | None = None) -> tuple[str, list[dict]]:
    """Замества противоречащите твърдения (от края към началото, за да не се местят позициите); връща (нов текст, проблеми)."""
    probs = check(text, f, default_etf)
    new = text
    for p in sorted(probs, key=lambda x: x["start"], reverse=True):
        new = new[:p["start"]] + p["replacement"] + new[p["end"]:]
    return new, probs


# ── 19.10.2026 (трети преглед, т. 18): секторната карта от КОДА ─────────────────────────────────────────────────────────────────────────────────────────
# Изборът кои сектори са на картата е на кода (водещите: RS > 0 и на 4, и на 12 седмици, или RS на 6-месечен връх — същото правило като sector_layer.leading_sectors,
# до 6), не на модела: в 394 реда на картата (89 брифа) 132 бяха сектори, които кодът не смята за водещи (19.10: GDX с RS −8.33% за 4 седмици), а 26 пъти водещ липсваше.
# Веригата (chain) е на модела — показва се само за водещ сектор; моделът е върнал верига и за неводещ → един ред под картата. Хоризонтът — форматиран от кода
# (16.10: моделът върна [4, 12], [4], [12] — прозорците на RS, не хоризонт). Сурови имена на полета в прозата (rs_chg_4w_pct, laggard_persistence_pct …) → думи.
_FIELD_WORDS = [
    (re.compile(r"\brs_at_6m_high\s*[=:]\s*false\b", re.I), "RS не е на 6-месечен връх"),
    (re.compile(r"\brs_at_6m_high\s*[=:]\s*true\b", re.I), "RS е на 6-месечен връх"),
    (re.compile(r"\brs_at_6m_high\b", re.I), "6-месечният връх по RS"),
    (re.compile(r"\bconfirmed_laggard\s*[=:]\s*true\b", re.I), "потвърдено изоставащ"),
    (re.compile(r"\bconfirmed_laggard\s*[=:]\s*false\b", re.I), "не е потвърдено изоставащ"),
    (re.compile(r"\bconfirmed_laggard\b", re.I), "потвърденото изоставане"),
    (re.compile(r"\bleading\s*[=:]\s*true\b", re.I), "водещ"),
    (re.compile(r"\bleading\s*[=:]\s*false\b", re.I), "не е водещ"),
    (re.compile(r"\brs_chg_4w(?:_pct)?\b", re.I), "RS за 4 седмици"),
    (re.compile(r"\brs_chg_12w(?:_pct)?\b", re.I), "RS за 12 седмици"),
    (re.compile(r"\babs_chg_4w(?:_pct)?\b", re.I), "абсолютната промяна за 4 седмици"),
    (re.compile(r"\blaggard_persistence(?:_pct)?\b", re.I), "дял на изоставането (12 седмици)"),
    (re.compile(r"\bsizing_factor\b", re.I), "режимният фактор"),
    (re.compile(r"\blevel_percentile\b", re.I), "перцентилът на нивото"),
    (re.compile(r"\broc_percentile\b", re.I), "перцентилът на RoC"),
    (re.compile(r"\bavg_recent\b", re.I), "средното за последните месеци"),
    (re.compile(r"\bavg_prior\b", re.I), "средното за предишните"),
]


def field_words(text: str) -> str:
    """Сурови имена на полета от данните в прозата на модела → думи (само показване)."""
    out = text or ""
    for rx, word in _FIELD_WORDS:
        out = rx.sub(word, out)
    return out


def horizon_text(h) -> str:
    """horizon_weeks на модела → текст: 4 → "4 седмици"; [4, 12] → "4–12 седмици"; "2-6" → "2–6 седмици"; друго / празно → ""."""
    try:
        if isinstance(h, bool):
            return ""
        if isinstance(h, (int, float)):
            return f"{int(h)} седмици" if h > 0 else ""
        if isinstance(h, (list, tuple)):
            xs = sorted({int(x) for x in h if isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0})
            return "" if not xs else f"{xs[0]} седмици" if len(xs) == 1 else f"{xs[0]}–{xs[-1]} седмици"
        m = re.fullmatch(r"\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*(?:седм\w*|w\w*)?\s*", str(h))
        if m:
            return f"{m.group(1)} седмици" if not m.group(2) else f"{m.group(1)}–{m.group(2)} седмици"
    except Exception:
        pass
    return ""


def _rs_line(r: dict) -> str:
    f = lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) else "н/д"
    s = f"RS спрямо SPY: 4 седмици {f(r.get('rs_chg_4w_pct'))}, 12 седмици {f(r.get('rs_chg_12w_pct'))}"
    return s + (" · RS на 6-месечен връх" if r.get("rs_at_6m_high") is True else "")


def sector_card(sector_logic: list[dict] | None, rotation: list[dict] | None, top_n: int = 6) -> dict:
    """
    {"rows": [{etf, sector, rs_line, chain, horizon}], "omitted": [{etf, sector, rs_line}]} или {} без ротация (старият бриф — шаблонът показва веригите на модела).
    rows — водещите по кода в реда на ротацията; omitted — сектори с верига от модела, които не са водещи.
    """
    rows = [r for r in (rotation or []) if isinstance(r, dict) and r.get("etf")]
    if not rows:
        return {}
    leaders = [r for r in rows if r.get("leading") or r.get("rs_at_6m_high") is True][:top_n]
    ai = {str(x.get("etf")): x for x in (sector_logic or []) if isinstance(x, dict) and x.get("etf")}
    by_etf = {r["etf"]: r for r in rows}
    out = {"rows": [], "omitted": []}
    for r in leaders:
        x = ai.get(r["etf"]) or {}
        out["rows"].append({"etf": r["etf"], "sector": r.get("sector") or x.get("sector") or r["etf"], "rs_line": _rs_line(r),
                            "chain": field_words(x.get("chain") or ""), "horizon": horizon_text(x.get("horizon_weeks"))})
    lead = {r["etf"] for r in leaders}
    for etf, x in ai.items():
        if etf not in lead:
            r = by_etf.get(etf) or {}
            out["omitted"].append({"etf": etf, "sector": r.get("sector") or x.get("sector") or etf, "rs_line": _rs_line(r) if r else "няма го в ротацията"})
    return out
