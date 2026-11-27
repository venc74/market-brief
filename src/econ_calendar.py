"""
16.11.2026 (пакет 16.11, т. 8–9): календарът на седмицата в сутрешния бриф и очакванията към икономическите заглавия в карето преди отварянето.

Източник — публичният календар на Nasdaq (api.nasdaq.com/api/calendar/…, JSON; config.ECON_CAL_URL / EARNINGS_CAL_URL), с ясен етикет „Nasdaq“ на страницата:
  • икономически данни: час (полето "gmt" е по Ню Йорк — 08:30 за CPI / PPI / jobless claims), държава, събитие, факт, консенсус, предишно;
  • отчети: тикър, преди отварянето / след затварянето, очаквана EPS.
ИЗМЕРЕНО 16.11.2026: икономическият календар връща събитията на ДЕНЯ ПРЕДИ подадената дата (date=2026-11-14 → петък 13.11: PPI 0.3% при консенсус 0.4%; date=2026-11-13 →
четвъртък 12.11: Initial Jobless Claims), затова заявката е за деня + 1 (config.ECON_CAL_DAY_SHIFT). Пазачът: Initial Jobless Claims излиза в четвъртък — ако падне в друг ден,
датите на източника не съвпадат и редът е червен (не тишина). Календарът на отчетите не е изместен (date=2026-11-17 → NVDA след затварянето).
Чисти функции (parse_*, week_*, *_text) + мрежа само във fetch_*. Graceful: провал → {"ok": False, "error": …} и червен ред.
"""
from __future__ import annotations

import datetime as dt
import html as _html
import re

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_HDR = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/json", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
_WD = ("понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя")

# основните данни за САЩ — по името на събитието в Nasdaq (двойките m/m и y/y са с едно име)
KEY_EVENTS = [
    ("CPI", r"^(?:Core )?CPI$"), ("PPI", r"^(?:Core )?PPI$"), ("заетост", r"^Nonfarm Payrolls$|^Unemployment Rate$|^Initial Jobless Claims$|^Average Hourly Earnings"),
    ("retail sales", r"^(?:Core )?Retail Sales$"), ("ISM", r"^ISM (?:Manufacturing|Non-Manufacturing|Services) PMI$"), ("JOLTS", r"^JOLTS Job Openings$"),
    ("БВП", r"^GDP(?: \(QoQ\))?$|^GDP Price Index$"), ("PCE", r"^(?:Core )?PCE Price Index"), ("промишленост", r"^Industrial Production$|^Philadelphia Fed Manufacturing Index$|^NY Empire State Manufacturing Index$"),
    ("жилища", r"^Housing Starts$|^Building Permits$|^(?:Existing|New|Pending) Home Sales$"), ("потребители", r"^Michigan Consumer Sentiment$|^CB Consumer Confidence$|^Michigan 1-Year Inflation Expectations$"),
    ("поръчки", r"^Durable Goods Orders$|^Core Durable Goods Orders$"),
]
_KEY = [(k, re.compile(rx)) for k, rx in KEY_EVENTS]
_FED = re.compile(r"(?:\bFed\b|FOMC|Federal Reserve).*(?:Speaks|Testifies|Minutes|Statement|Press Conference|Interest Rate Decision|Projections|Beige Book)"
                  r"|^(?:Fed|FOMC) (?:Interest Rate Decision|Meeting Minutes|Statement|Press Conference)", re.I)


def _clean(v) -> str:
    s = _html.unescape(str(v or "")).replace("\xa0", " ").strip()
    return "" if s in ("", "-") else s


def parse_econ(payload: dict | None, day: dt.date) -> list[dict]:
    """Отговорът на Nasdaq → [{date, time_ny, event, actual, consensus, previous}] само за САЩ, в реда на източника. day — денят на събитията (заявката е за day + отместването)."""
    rows = ((payload or {}).get("data") or {}).get("rows") or []
    out = []
    for r in rows:
        if not isinstance(r, dict) or r.get("country") != "United States":
            continue
        out.append({"date": day.isoformat(), "time_ny": _clean(r.get("gmt")), "event": _clean(r.get("eventName")), "actual": _clean(r.get("actual")),
                    "consensus": _clean(r.get("consensus")), "previous": _clean(r.get("previous"))})
    return out


def market_cap(v) -> float | None:
    """Nasdaq "marketCap" („$264,078,852,000“) → число; празно / „N/A“ → None. Чиста функция."""
    try:
        x = float(_clean(v).replace("$", "").replace(",", ""))
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def parse_earnings(payload: dict | None, day: dt.date) -> list[dict]:
    """
    Отговорът на Nasdaq за отчетите → [{date, ticker, name, when ("преди отварянето" / "след затварянето" / "неизвестен час"), eps_forecast, market_cap}].
    18.11.2026 (т. 6): + market_cap (за големите компании в календара); от т. 2 — и eps / surprise, когато Nasdaq ги дава (след отчета).
    """
    rows = ((payload or {}).get("data") or {}).get("rows") or []
    when = {"time-pre-market": "преди отварянето", "time-after-hours": "след затварянето"}
    return [{"date": day.isoformat(), "ticker": str(r.get("symbol") or "").upper().replace(".", "-"), "name": _clean(r.get("name")),
             "when": when.get(r.get("time"), "неизвестен час"), "eps_forecast": _clean(r.get("epsForecast")), "market_cap": market_cap(r.get("marketCap")),
             **({"eps": _clean(r.get("eps"))} if _clean(r.get("eps")) else {}), **({"surprise": _clean(r.get("surprise"))} if _clean(r.get("surprise")) else {})}
            for r in rows if isinstance(r, dict) and r.get("symbol")]


def cap_label(cap: float | None, asof: dt.date | None = None) -> str | None:
    """
    18.11.2026 (т. 6): „капитализация $264 млрд“ (≥ $1 трлн — „$4.0 трлн“); под config.WEEK_CAL_MIN_MARKET_CAP / без → None. Чиста функция.
    27.11.2026 (уикенд пакет, т. 7): с датата на данните (Nasdaq, всеки ден наново) — „капитализация $264 млрд (Nasdaq, 27.11)“.
    """
    if not cap or cap < config.WEEK_CAL_MIN_MARKET_CAP:
        return None
    base = f"капитализация ${cap / 1e12:.1f} трлн" if cap >= 1e12 else f"капитализация ${cap / 1e9:.0f} млрд"
    return base + (f" (Nasdaq, {asof:%d.%m})" if asof else "")


def key_kind(event: str) -> str | None:
    for k, rx in _KEY:
        if rx.search(event or ""):
            return k
    return None


def is_fed(event: str) -> bool:
    return bool(_FED.search(event or ""))


def dates_ok(econ_by_day: dict) -> str | None:
    """Пазачът за отместването: Initial Jobless Claims трябва да е в четвъртък; иначе → причината (червен ред). Без такова събитие в седмицата → None."""
    for d, rows in econ_by_day.items():
        if any(r["event"] == "Initial Jobless Claims" for r in rows) and dt.date.fromisoformat(d).weekday() != 3:
            return f"Initial Jobless Claims е на {_WD[dt.date.fromisoformat(d).weekday()]} {d[8:10]}.{d[5:7]} — датите на източника не съвпадат"
    return None


def _get_json(url: str, get=None) -> dict:
    if get is not None:
        return get(url)
    import requests
    r = requests.get(url, headers=_HDR, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_econ(day: dt.date, get=None) -> list[dict]:
    """Икономическите данни за САЩ на `day` (мрежа; заявката — за day + config.ECON_CAL_DAY_SHIFT). Вдига при провал."""
    q = day + dt.timedelta(days=config.ECON_CAL_DAY_SHIFT)
    return parse_econ(_get_json(config.ECON_CAL_URL.format(date=q.isoformat()), get), day)


def fetch_earnings(day: dt.date, get=None) -> list[dict]:
    """Отчетите на `day` (мрежа). Вдига при провал."""
    return parse_earnings(_get_json(config.EARNINGS_CAL_URL.format(date=day.isoformat()), get), day)


def week_days(today: dt.date, n: int | None = None) -> list[dt.date]:
    """Днес (ако е сесия) и следващите сесии — общо n (config.WEEK_CAL_SESSIONS)."""
    from src import sessions
    n = n or config.WEEK_CAL_SESSIONS
    d = today if sessions.is_session(today) else sessions.next_session(today)
    out = [d]
    while len(out) < n:
        out.append(sessions.next_session(out[-1]))
    return out


def fed_schedule(day: dt.date) -> list[dict]:
    """17.11.2026 (пакет 1, т. 8): събитията на FOMC за деня по config.FOMC_MEETINGS — решение, пресконференция, протоколи (последния ден + FOMC_MINUTES_DAYS). Чиста функция."""
    out = []
    for a, b in config.FOMC_MEETINGS:
        s, e = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
        span = f"{s:%d}–{e:%d.%m}" if s.month == e.month else f"{s:%d.%m}–{e:%d.%m}"
        if e == day:
            out += [{"date": day.isoformat(), "time_ny": "14:00", "event": f"FOMC — решение за лихвите (заседанието {span})", "source": "график на Fed", "kind": "decision"},
                    {"date": day.isoformat(), "time_ny": "14:30", "event": "FOMC — пресконференция", "source": "график на Fed", "kind": "press"}]
        if e + dt.timedelta(days=config.FOMC_MINUTES_DAYS) == day:
            out.append({"date": day.isoformat(), "time_ny": "14:00", "event": f"FOMC — протоколи от заседанието {span}", "source": "график на Fed", "kind": "minutes"})
    return out


_SCHED_IN_NASDAQ = {"decision": re.compile(r"Interest Rate Decision|Rate Statement", re.I), "press": re.compile(r"Press Conference", re.I), "minutes": re.compile(r"Minutes", re.I)}


def add_fed_schedule(day: dict) -> int:
    """Добавя към day["fed"] събитията от графика, които Nasdaq няма (по вида: решение / пресконференция / протоколи). Връща броя добавени."""
    have = [f.get("event") or "" for f in day.get("fed") or []]
    add = [x for x in fed_schedule(dt.date.fromisoformat(day["date"])) if not any("FOMC" in h and _SCHED_IN_NASDAQ[x["kind"]].search(h) for h in have)]
    day["fed"] = sorted((day.get("fed") or []) + add, key=lambda f: f.get("time_ny") or "")
    return len(add)


def reconcile_dates(week: dict, known: dict | None) -> dict:
    """
    17.11.2026 (т. 8): една дата на отчета за цялата страница — датата в календара (Nasdaq) срещу датата на картите / книгите (Yahoo). При разминаване: в календара
    „⚠ Yahoo: ДД.ММ“, а за картите — {тикър: "отчет ДД.ММ (Yahoo) / ДД.ММ (Nasdaq)"}. known — {тикър: дата ISO от Yahoo}. Чиста функция.
    """
    out = {}
    for d in (week or {}).get("days") or []:
        for e in d.get("earnings") or []:
            y = (known or {}).get(e["ticker"])
            if y and str(y)[:10] != e["date"]:
                e["date_note"] = f"⚠ Yahoo: {y[8:10]}.{y[5:7]}"
                out[e["ticker"]] = f"отчет {y[8:10]}.{y[5:7]} (Yahoo) / {e['date'][8:10]}.{e['date'][5:7]} (Nasdaq) — източниците се разминават"
    return out


def monthly_opex(year: int, month: int) -> dt.date:
    """
    20.11.2026 (пакет 20.11, т. 5): месечният опционен падеж — третият петък на месеца; ако е борсов празник — четвъртъкът преди него (Good Friday). Чиста функция.
    """
    from src import sessions
    d = dt.date(year, month, 1)
    first_fri = d + dt.timedelta(days=(4 - d.weekday()) % 7)
    third = first_fri + dt.timedelta(days=14)
    return third if sessions.is_session(third) else third - dt.timedelta(days=1)


def opex_note(day: dt.date) -> str | None:
    """„месечен опционен падеж (трети петък)“ — и „тримесечен: фючърси и опции на индекси“ през март, юни, септември, декември; друг ден → None."""
    if day != monthly_opex(day.year, day.month):
        return None
    return "месечен опционен падеж (трети петък)" + (" — тримесечен: изтичат и фючърсите и опциите на индексите" if day.month in (3, 6, 9, 12) else "")


_WD_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "нд")


def _wd_dm(d: dt.date) -> str:
    return f"{_WD_SHORT[d.weekday()]} {d:%d.%m}"


def market_note(d: dt.date) -> str | None:
    """
    23.11.2026 (пакет 23.11, т. 6): борсата в деня — празник („NYSE затворена — Thanksgiving (Денят на благодарността)“) или съкратена сесия („NYSE — съкратена сесия,
    затваря в 13:00 Ню Йорк“); обикновен ден → None. Празниците и ранните затваряния — САМО през src/sessions.py (test_sessions го пази). Чиста функция.
    """
    from src import sessions
    if sessions.is_holiday(d):
        return f"NYSE затворена — {sessions.holiday_name(d)}"
    if sessions.early_close(d):
        return f"NYSE — съкратена сесия, затваря в {sessions.early_close(d)} Ню Йорк"
    return None


def market_day_notes(today: dt.date) -> list[str]:
    """
    23.11.2026 (пакет 23.11, т. 6): редовете за „Нощта“ — съкратената сесия днес, затворените дни до следващата сесия („утре“ / ДД.ММ) и съкратената предишна сесия
    („след затварянето“ е от 13:00). Чиста функция.
    """
    from src import sessions
    out = []
    if sessions.early_close(today):
        out.append(f"Днес ({_wd_dm(today)}) NYSE затваря в {sessions.early_close(today)} Ню Йорк — съкратена сесия.")
    nxt = sessions.next_session(today)
    for d in sessions.closed_days(today + dt.timedelta(days=1), nxt - dt.timedelta(days=1)):
        out.append(f"{'Утре' if d == today + dt.timedelta(days=1) else 'На'} ({_wd_dm(d)}) NYSE е затворена — {sessions.holiday_name(d)}; "
                   f"следващата сесия — {_wd_dm(nxt)}" + (f", съкратена до {sessions.early_close(nxt)} Ню Йорк" if sessions.early_close(nxt) else "") + ".")
    prev = sessions.prev_session(today)
    if sessions.early_close(prev):
        out.append(f"Предишната сесия ({_wd_dm(prev)}) беше съкратена — затваряне в {sessions.early_close(prev)} Ню Йорк; „след затварянето“ е от "
                   f"{sessions.early_close(prev)}.")
    return out


def build_week(today: dt.date, big: dict | None, ours: dict | None, econ_fn=None, earnings_fn=None) -> dict:
    """
    → {"ok", "source", "days": [{date, weekday, earnings, fed, econ}], "errors": [...], "big_n", "ours_n"}. big — {тикър: етикет} (компаниите > 2% в S&P 500), ours — {тикър: къде}
    (18.11.2026, т. 6: + капитализация ≥ config.WEEK_CAL_MIN_MARKET_CAP по Nasdaq "marketCap")
    (картите, книгите, наблюдаваните). Отчетите — само за тях; Fed — речи, протоколи, решения; данните — KEY_EVENTS с консенсуса. Провал на ден → в "errors", останалото минава.
    """
    econ_fn, earnings_fn = econ_fn or fetch_econ, earnings_fn or fetch_earnings
    big, ours = big or {}, ours or {}
    out = {"ok": True, "source": "Nasdaq (api.nasdaq.com — календар на икономическите данни и на отчетите)", "days": [], "errors": [], "big_n": len(big), "ours_n": len(ours),
           "cap_min_bn": round(config.WEEK_CAL_MIN_MARKET_CAP / 1e9)}                     # 18.11.2026 (т. 6)
    econ_by_day = {}
    for d in week_days(today):
        day = {"date": d.isoformat(), "weekday": _WD[d.weekday()], "earnings": [], "fed": [], "econ": []}
        try:
            rows = econ_fn(d)
            econ_by_day[d.isoformat()] = rows
            day["fed"] = [r for r in rows if is_fed(r["event"])]
            day["econ"] = [{**r, "kind": key_kind(r["event"])} for r in rows if key_kind(r["event"])]
            if not rows:                                                       # 17.11.2026 (т. 8): празен ден от източника — видимо, не „нищо от следените“
                day["econ_empty"] = True
        except Exception as e:
            out["errors"].append(f"данни {d:%d.%m}: {type(e).__name__}")
            print(f"[calendar] икономически данни {d}: {type(e).__name__}: {e}")
        try:
            for r in earnings_fn(d):
                cap = cap_label(r.get("market_cap"), today)                   # 18.11.2026 (т. 6): и големите компании (≥ $100 млрд); 27.11.2026 (т. 7): с датата
                if r["ticker"] in big or r["ticker"] in ours or cap:
                    day["earnings"].append({**r, "why": big.get(r["ticker"]) or ours.get(r["ticker"]) or cap})
        except Exception as e:
            out["errors"].append(f"отчети {d:%d.%m}: {type(e).__name__}")
            print(f"[calendar] отчети {d}: {type(e).__name__}: {e}")
        add_fed_schedule(day)                                                  # 17.11.2026 (т. 8): FOMC по графика, когато Nasdaq го няма
        if opex_note(d):                                                       # 20.11.2026 (пакет 20.11, т. 5): месечният опционен падеж
            day["opex"] = opex_note(d)
        if market_note(d):                                                     # 23.11.2026 (пакет 23.11, т. 6): съкратена сесия
            day["market"] = market_note(d)
        out["days"].append(day)
    # 23.11.2026 (т. 6): затворените дни между сесиите в календара (празник) — отделен ред; до 23.11 week_days ги прескачаше и 26.11 (Thanksgiving) не се виждаше
    if out["days"]:
        from src import sessions
        for d in sessions.closed_days(out["days"][0]["date"], out["days"][-1]["date"]):
            out["days"].append({"date": d.isoformat(), "weekday": _WD[d.weekday()], "earnings": [], "fed": [], "econ": [], "market": market_note(d), "closed": True})
        out["days"].sort(key=lambda x: x["date"])
    bad = dates_ok(econ_by_day)
    if bad:
        out["errors"].append(bad)
    out["ok"] = not out["errors"]
    return out


def carry_forward(week: dict, prev_week: dict | None, prev_date: str | None, today: dt.date) -> dict:
    """
    27.11.2026 (уикенд пакет, т. 7): ден, който в предишния бриф имаше данни, а днес е празен — червен ред и последните известни събития „от ДД.ММ“; отчетите на следените компании
    не изчезват мълчаливо (ако днес ги няма никъде в седмицата — остават с „от ДД.ММ — днес Nasdaq не го показва“). Реално: в брифа от 23.11 25.11 имаше 11 данни (GDP, Core PCE,
    Durable Goods, Claims, New Home Sales …), в брифовете от 24 и 25.11 — празно, без банер; CRWD (отчет 01.12) — в брифа от 24.11, изчезна на 25 и 27.11. Мутира и връща week.
    """
    if not isinstance(week, dict) or not isinstance(prev_week, dict) or not prev_date:
        return week
    prev = {d["date"]: d for d in prev_week.get("days") or [] if isinstance(d, dict) and d.get("date")}
    pd_ = f"{prev_date[8:10]}.{prev_date[5:7]}"
    today_tickers = {e.get("ticker") for d in week.get("days") or [] for e in d.get("earnings") or []}
    carried = []
    for day in week.get("days") or []:
        if day.get("closed") or day["date"] < today.isoformat():
            continue
        p = prev.get(day["date"])
        if not p:
            continue
        if not day.get("econ") and p.get("econ"):
            day["econ"] = [{**e, "stale_from": e.get("stale_from") or prev_date} for e in p["econ"]]      # през няколко брифа — датата остава първоначалната
            src = day["econ"][0]["stale_from"]
            day["stale_note"] = f"Nasdaq днес не върна данните за деня — последните известни от {src[8:10]}.{src[5:7]}"
            day.pop("econ_empty", None)
            carried.append(f"данни {day['date'][8:10]}.{day['date'][5:7]}")
        for e in p.get("earnings") or []:
            if e.get("ticker") and e["ticker"] not in today_tickers:
                day.setdefault("earnings", []).append({**e, "date_note": e.get("date_note") or f"от {pd_} — днес Nasdaq не го показва"})
                today_tickers.add(e["ticker"])
                carried.append(e["ticker"])
    if carried:
        week["carried"] = {"from": prev_date, "items": carried}
        print(f"[calendar] от предишния бриф ({pd_}): {', '.join(carried)}")
    return week


def econ_value_text(rows: list[dict]) -> str:
    """
    Редовете на едно събитие (m/m и y/y са с едно име) — само тези с консенсус, всеки със своите факт и предишно: „факт 0.3%, консенсус 0.4% (предишно 1.4%) · факт 6.5%,
    консенсус 6.6% (предишно 6.3%)“; без нито един консенсус → „очаквания: няма данни“ (+ предишното, ако го има).
    """
    with_c = [r for r in rows if r.get("consensus")]
    if not with_c:
        prev = [r["previous"] for r in rows if r.get("previous")]
        return "очаквания: няма данни" + (f" (предишно {' · '.join(prev)})" if prev else "")
    return " · ".join((f"факт {r['actual']}, " if r.get("actual") else "") + f"консенсус {r['consensus']}" + (f" (предишно {r['previous']})" if r.get("previous") else "")
                      for r in with_c)


def group_events(rows: list[dict]) -> list[dict]:
    """Едно име — един ред (двойките m/m и y/y заедно): [{time_ny, event, kind, rows}] в реда на източника."""
    out, by = [], {}
    for r in rows:
        k = (r["time_ny"], r["event"])
        if k not in by:
            by[k] = {"time_ny": r["time_ny"], "event": r["event"], "kind": r.get("kind"), "rows": []}
            out.append(by[k])
        by[k]["rows"].append(r)
    return out


def day_lines(day: dict) -> list[str]:
    """Редовете за един ден — отчетите, Fed, данните. Чиста функция."""
    lines = []
    if day.get("stale_note"):                                                  # 27.11.2026 (уикенд пакет, т. 7): изчезналите данни — първи, червено (⚠ в началото)
        lines.append(f"⚠ {day['stale_note']}")
    if day.get("market"):                                                      # 23.11.2026 (т. 6): празник / съкратена сесия — първи ред
        lines.append(f"борса: {day['market']}")
    if day.get("opex"):                                                        # 20.11.2026 (т. 5)
        lines.append(f"опции: {day['opex']}")
    for e in day.get("earnings") or []:
        lines.append(f"отчет: {e['ticker']} · {e['name']} — {e['when']}" + (f" (EPS очаквана {e['eps_forecast']}, Nasdaq)" if e.get("eps_forecast") else "")      # 17.11.2026: с източника
                     + (f" · {e['why']}" if e.get("why") else "") + (f" · {e['date_note']}" if e.get("date_note") else ""))
    for f in group_events(day.get("fed") or []):
        lines.append(f"Fed: {f['event']} — {f['time_ny']} Ню Йорк" + (f" ({f['rows'][0]['source']})" if (f.get("rows") or [{}])[0].get("source") else ""))
    if day.get("econ_empty"):
        lines.append("данните на Nasdaq за деня още не са публикувани — Fed е по графика; останалото — в следващия бриф")
    for g in group_events(day.get("econ") or []):
        lines.append(f"{g['event']} — {g['time_ny']} Ню Йорк: {econ_value_text(g['rows'])}" + (f" (от {g['rows'][0]['stale_from'][8:10]}.{g['rows'][0]['stale_from'][5:7]})" if (g.get("rows") or [{}])[0].get("stale_from") else ""))
    return lines


def expectations_for(kind: str, rows: list[dict]) -> str:
    """
    16.11.2026 (т. 9): очакванията към заглавие за икономически данни (preopen.econ_kind → CPI / PPI / заетост / JOLTS / ISM / retail sales) от днешния календар:
    „очаквания (Nasdaq): PPI — факт 0.3% · 6.5%; консенсус 0.4% · 6.6%“; без съвпадение / без консенсус → „очаквания: няма данни“. Чиста функция.
    """
    if not kind:
        return "очаквания: няма данни"
    hits = [g for g in group_events([{**r, "kind": key_kind(r["event"])} for r in rows or []]) if g["kind"] == kind]
    hits = [g for g in hits if any(r.get("consensus") for r in g["rows"])]
    if not hits:
        return "очаквания: няма данни"
    return "очаквания (Nasdaq): " + "; ".join(f"{g['event']} — {econ_value_text(g['rows'])}" for g in hits[:3])
