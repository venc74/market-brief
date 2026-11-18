"""
18.11.2026 (спешно, т. 2): блокът „Нощта“ — от кода, без AI, в началото на брифа. На 18.11 брифът в 07:43 не спомена отчета на Nvidia от 17.11 (~22:20 Берлин: EPS $2.68
срещу $2.47 по Nasdaq, приходи $115.84 млрд по Yahoo, акцията +3.9% след затварянето) — новините зависят от подбора; отчетите на големите компании не бива.

  • Компаниите: отчетите СЛЕД ЗАТВАРЯНЕТО (и „неизвестен час“) на предишната сесия от календара на предишния бриф (week_calendar — тегло > 2% в S&P 500, капитализация
    ≥ config.WEEK_CAL_MIN_MARKET_CAP, нашите карти / книги / наблюдавани); без календар — Nasdaq за деня по същия праг. За всяка: EPS факт срещу очаквана (Nasdaq; резерва — Yahoo),
    приходи факт (Yahoo, quoteSummary „earnings“) срещу очакваните, записани СУТРИНТА ПРЕДИ отчета (capture_estimates → week_calendar; след отчета Yahoo вече дава следващото
    тримесечие), прогнозата — само дословно заглавие от източниците на новините (иначе „няма заглавие“), движението след затварянето (5-мин. бари с prepost, qm_ep.extract_ah).
  • Пазарът: ES / NQ и доларът (DX-Y.NYB) спрямо 16:00 Ню Йорк на предишната сесия (preopen.premarket_point); 10Y — затварянето (^TNX няма нощни бари) и фючърсът ZN=F.
Всеки ред — с източника; липсва → „няма данни“ с причината, не тишина. Мрежа само във fetch_*; останалото — чисти функции.
"""
from __future__ import annotations

import datetime as dt
import re

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

NIGHT_WHEN = ("след затварянето", "неизвестен час")
# прогнозата: „forecast / guidance / outlook“ или „sees / expects … revenue“, „raises / cuts … forecast“; „swing lower“ (AP, 17.11 за Nvidia) не е прогноза
_GUIDE = re.compile(r"\b(?:forecast\w*|guidance|outlook)\b|\b(?:sees|expects?|projects?|predicts?)\s+(?:\S+\s+){0,3}(?:revenue|sales|profit|earnings|growth|demand)"
                    r"|\b(?:raises?|lifts?|cuts?|lowers?|boosts?|trims?)\s+(?:\S+\s+){0,2}(?:forecast|outlook|guidance|target|view)", re.I)
_LEGAL = re.compile(r"\s*\((?:the|The)\)|,?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.?|Ltd\.?|Limited|plc|PLC|Group|Holdings?|N\.V\.|S\.A\.|AG|SE)\b\.?", re.I)


def money(x) -> str | None:
    """$115.84 млрд / $1.20 трлн / $850 млн; не е число → None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return f"${v / 1e12:.2f} трлн" if abs(v) >= 1e12 else f"${v / 1e9:.2f} млрд" if abs(v) >= 1e9 else f"${v / 1e6:.0f} млн"


def _num(s) -> float | None:
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def companies(prev_brief: dict | None, session: str) -> list[dict]:
    """Отчетите след затварянето (и с неизвестен час) на сесията от календара на предишния бриф → редовете му (с очакванията, ако са записани). Чиста функция."""
    for d in ((prev_brief or {}).get("week_calendar") or {}).get("days") or []:
        if d.get("date") == session:
            return [dict(e) for e in d.get("earnings") or [] if e.get("when") in NIGHT_WHEN]
    return []


def name_keys(name: str | None, ticker: str) -> list[str]:
    """За търсенето в заглавията: името без правната форма („NVIDIA Corporation“ → „NVIDIA“; „Walt Disney Company (The)“ → „Walt Disney“, „Disney“) и тикърът. Чиста функция."""
    clean = _LEGAL.sub("", (name or "").split(",")[0]).strip()
    keys = [clean] if len(clean) >= 3 else []
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z&'.-]{3,}", clean)]
    if len(words) > 1:
        keys.append(max(words, key=len))
    return keys + [ticker]


def guidance_headline(name: str | None, ticker: str, pool: list | None) -> dict | None:
    """Първото заглавие в пула (дословно) с името / тикъра И дума за прогноза (forecast, guidance, outlook, sees, expects, raises, cuts …) → {title, source, published}. Чиста функция."""
    keys = name_keys(name, ticker)
    for it in pool or []:
        if isinstance(it, dict):
            t, src, pub = it.get("title") or "", it.get("source"), it.get("published")
        elif isinstance(it, (list, tuple)) and len(it) >= 3:
            src, pub, t = it[0], it[1], it[2] or ""
        else:
            continue
        has_name = any((re.search(r"\b" + re.escape(k) + r"\b", t) if k == ticker else re.search(r"\b" + re.escape(k), t, re.I)) for k in keys)
        if has_name and _GUIDE.search(t):
            return {"title": t, "source": src, "published": pub}
    return None


def yahoo_earnings(qs: dict | None, session: str) -> dict:
    """quoteSummary („earnings“) → {"eps_actual", "eps_estimate", "revenue", "quarter", "period_end"} за тримесечието, отчетено на `session` (earningsChart.reportedDate); иначе {}. Чиста функция."""
    try:
        e = (qs or {}).get("earnings") or {}
        last = ((e.get("earningsChart") or {}).get("quarterly") or [])[-1]
        if ((last.get("reportedDate") or {}).get("fmt")) != session:
            return {}
        q = last.get("date")
        fin = next((x for x in (e.get("financialsChart") or {}).get("quarterly") or [] if x.get("date") == q), {})
        return {"eps_actual": (last.get("actual") or {}).get("raw"), "eps_estimate": (last.get("estimate") or {}).get("raw"),
                "revenue": (fin.get("revenue") or {}).get("raw"), "quarter": q, "period_end": (last.get("periodEndDate") or {}).get("fmt")}
    except Exception:
        return {}


def yahoo_when(qs: dict | None, session: str) -> str | None:
    """
    Часът на отчета по Yahoo (calendarEvents.earningsDate за `session`): ≥ 20:00 UTC → „след затварянето“, < 16:00 UTC → „преди отварянето“; друга дата / няма → None. Реално, 18.11:
    NVDA 17.11 21:00 UTC, HD 17.11 13:30 UTC, LOW / TJX 18.11 13:30 UTC, PANW 18.11 21:00 UTC. Чиста функция.
    """
    try:
        for x in ((((qs or {}).get("calendarEvents") or {}).get("earnings") or {}).get("earningsDate") or []):
            t = dt.datetime.fromtimestamp(int(x["raw"]), dt.timezone.utc)
            if t.date().isoformat() == session:
                return "след затварянето" if t.hour >= 20 else "преди отварянето" if t.hour < 16 else None
    except Exception:
        return None
    return None


def ah_move(df, session: str) -> dict | None:
    """5-мин. бари с prepost → движението след затварянето на `session`: {chg_pct, price, prev_close, last_ny}; няма post-market за сесията → None. Чиста функция."""
    try:
        from src import qm_ep
        a = qm_ep.extract_ah(df)
    except Exception:
        return None
    if not a or a.get("session") != session or not a.get("prev_close"):
        return None
    return {"chg_pct": round((a["ah_price"] / a["prev_close"] - 1) * 100, 2), "price": round(a["ah_price"], 2), "prev_close": round(a["prev_close"], 2), "last_ny": a["ah_last_et"]}


def company_row(c: dict, nasdaq: dict | None, qs: dict | None, frame, pool: list | None, session: str, pool_checked: bool = True) -> dict:
    """Един отчет → {ticker, name, why, eps, revenue, guidance, move, lines}; всеки ред с източника, липсва → „няма данни“ с причината. Чиста функция."""
    t, nd, ye = c.get("ticker"), nasdaq or {}, yahoo_earnings(qs, session)
    out = {"ticker": t, "name": c.get("name"), "why": c.get("why"), "when": c.get("when")}
    eps, fc = _num(nd.get("eps")), _num(nd.get("eps_forecast") or c.get("eps_forecast"))
    if eps is not None:
        out["eps"] = {"actual": eps, "estimate": fc, "source": "Nasdaq", "surprise": _num(nd.get("surprise"))}
        eps_text = f"EPS ${eps:.2f}" + (f" срещу ${fc:.2f} очаквана" if fc is not None else " (очаквана: няма данни)") + " (Nasdaq)"
    elif ye.get("eps_actual") is not None:
        out["eps"] = {"actual": ye["eps_actual"], "estimate": ye.get("eps_estimate"), "source": "Yahoo"}
        eps_text = f"EPS ${ye['eps_actual']:.2f}" + (f" срещу ${ye['eps_estimate']:.2f} очаквана" if ye.get("eps_estimate") is not None else "") + " (Yahoo)"
    else:
        eps_text = "EPS: няма данни (отчетът още не е в Nasdaq / Yahoo)"
    est = c.get("revenue_estimate")
    if ye.get("revenue") is not None:
        out["revenue"] = {"actual": ye["revenue"], "estimate": est, "quarter": ye.get("quarter"), "source": "Yahoo"}
        rev_text = f"приходи {money(ye['revenue'])}" + (f" срещу {money(est)} очаквани (Yahoo, записани {c.get('estimate_as_of', '')[8:10]}.{c.get('estimate_as_of', '')[5:7]} преди отчета)"
                                                        if est else " (Yahoo; очакване: няма данни — не е записано преди отчета)")
    else:
        rev_text = "приходи: няма данни (Yahoo още не дава тримесечието)" + (f"; очаквани {money(est)}" if est else "")
    g = guidance_headline(c.get("name"), t, pool)
    if g:
        out["guidance"] = g
        gtext = f"прогноза — заглавие: „{g['title']}“ ({g['source']}" + (f", {g['published'][8:10]}.{g['published'][5:7]} {g['published'][11:16]} UTC" if g.get("published") else "") + ")"
    else:
        gtext = "прогноза: няма заглавие в източниците на новините" if pool_checked else "прогноза: заглавията не се провериха"
    mv = ah_move(frame, session)
    if mv:
        out["move"] = mv
        mtext = f"след затварянето {mv['chg_pct']:+.1f}% (${mv['price']:.2f} в {mv['last_ny']} Ню Йорк срещу ${mv['prev_close']:.2f}; Yahoo)"
    else:
        mtext = "след затварянето: няма данни (Yahoo без post-market бари)"
    out["lines"] = [eps_text, rev_text, gtext, mtext]
    return out


def market_rows(frames: dict | None, now_utc, session: str) -> list[dict]:
    """ES, NQ, доларът (спрямо 16:00 Ню Йорк на сесията), 10Y (затварянето на ^TNX) и ZN=F → [{label, text, ok}]. Чиста функция."""
    from src import preopen
    import pandas as pd
    frames = frames or {}
    out = []
    for sym, label in (("ES=F", "ES (S&P 500 фючърс)"), ("NQ=F", "NQ (Nasdaq-100 фючърс)"), ("DX-Y.NYB", "долар (DXY)")):
        p = preopen.premarket_point(frames.get(sym), now_utc)
        if p and p["prev_close"]:
            ch = (p["pm_price"] / p["prev_close"] - 1) * 100
            out.append({"label": label, "ok": True, "chg_pct": round(ch, 2), "price": round(p["pm_price"], 2),
                        "text": f"{label} {ch:+.2f}% ({p['pm_price']:,.2f} в {p['pm_last_ny']} Ню Йорк спрямо 16:00 на {session[8:10]}.{session[5:7]}; Yahoo)".replace(",", " ")})
        else:
            out.append({"label": label, "ok": False, "text": f"{label}: няма данни (Yahoo без нощни бари)"})
    tnx = frames.get("^TNX")
    try:
        ix = pd.DatetimeIndex(tnx.index)
        ix = (ix.tz_localize("UTC") if ix.tz is None else ix).tz_convert("America/New_York")
        c = tnx[ix.date == dt.date.fromisoformat(session)]["Close"].dropna()
        y = float(c.iloc[-1])
        out.append({"label": "10Y", "ok": True, "value": round(y, 3), "text": f"10Y {y:.2f}% (затваряне {session[8:10]}.{session[5:7]}, Yahoo ^TNX — нощем няма котировка)"})
    except Exception:
        out.append({"label": "10Y", "ok": False, "text": "10Y: няма данни (Yahoo ^TNX)"})
    p = preopen.premarket_point(frames.get("ZN=F"), now_utc)
    if p and p["prev_close"]:
        ch = (p["pm_price"] / p["prev_close"] - 1) * 100
        out.append({"label": "ZN=F", "ok": True, "chg_pct": round(ch, 2),
                    "text": f"фючърсът на 10-годишните (ZN=F) {ch:+.2f}% спрямо 16:00 — цената е обратна на доходността (Yahoo)"})
    return out


def build(today: str, prev_brief: dict | None, *, frames: dict | None, now_utc, nasdaq_rows: list | None = None, qs: dict | None = None, pool: list | None = None,
          fallback_rows: list | None = None, pool_checked: bool = True, errors: list | None = None) -> dict:
    """
    → {"session", "companies": [...], "market": [...], "notes": [...], "source"}. Компаниите — от календара на предишния бриф (companies) или — без него — fallback_rows
    (Nasdaq за сесията по прага). nasdaq_rows — Nasdaq за сесията (EPS факт); qs — {тикър: quoteSummary}; frames — 5-мин. бари (компаниите, ES=F, NQ=F, DX-Y.NYB, ZN=F, ^TNX). Чиста функция.
    """
    from src import sessions
    session = sessions.prev_session(dt.date.fromisoformat(today)).isoformat()
    rows = companies(prev_brief, session)
    notes = list(errors or [])
    src_note = "календарът на предишния бриф"
    if not rows and fallback_rows is not None:
        rows, src_note = [dict(r) for r in fallback_rows], "Nasdaq за сесията (предишният бриф е без календар)"
    by_nd = {r.get("ticker"): r for r in nasdaq_rows or []}
    out_c = [company_row(c, by_nd.get(c.get("ticker")), (qs or {}).get(c.get("ticker")), (frames or {}).get(c.get("ticker")), pool, session, pool_checked) for c in rows]
    if not rows:
        notes.append(f"отчети след затварянето на {session[8:10]}.{session[5:7]} от следените компании няма ({src_note})")
    notes.append("премаркетът на акциите започва в 04:00 Ню Йорк (10:00 Берлин) — в 07:30 се вижда само движението след затварянето")
    return {"session": session, "companies": out_c, "market": market_rows(frames, now_utc, session), "notes": notes,
            "source": f"компаниите — {src_note} (тегло > 2% в S&P 500, капитализация ≥ ${config.WEEK_CAL_MIN_MARKET_CAP / 1e9:.0f} млрд, нашите); EPS — Nasdaq, приходи — Yahoo, "
                      "цени — Yahoo (5-мин. бари), прогноза — само дословно заглавие"}


# ── мрежа ────────────────────────────────────────────────────────────────
def fetch_quote_summary(ticker: str, modules: str = "earnings,calendarEvents") -> dict:
    """Yahoo quoteSummary за тикъра (през сесията на yfinance — с crumb). Провал → {}."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        j = t._data.get_raw_json(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}", params={"modules": modules})
        return ((j or {}).get("quoteSummary") or {}).get("result", [{}])[0] or {}
    except Exception as e:
        print(f"[overnight] quoteSummary {ticker}: {type(e).__name__}: {e}")
        return {}


def capture_estimates(week: dict | None, today: str, qs_fn=None) -> int:
    """
    Очакванията СУТРИНТА ПРЕДИ отчета (днешните отчети в календара — след затварянето и с неизвестен час): Yahoo calendarEvents → row["revenue_estimate"], row["eps_estimate_yahoo"],
    row["estimate_as_of"]. Утре блокът „Нощта“ ги сравнява с факта (след отчета Yahoo дава вече следващото тримесечие). → колко са записани. Провал по тикър — пропуснат.
    """
    qs_fn = qs_fn or (lambda t: fetch_quote_summary(t, "calendarEvents"))
    n = 0
    for d in (week or {}).get("days") or []:
        if d.get("date") != today:
            continue
        for e in d.get("earnings") or []:
            if e.get("when") not in NIGHT_WHEN:
                continue
            try:
                ce = ((qs_fn(e["ticker"]) or {}).get("calendarEvents") or {}).get("earnings") or {}
                dates = [x.get("fmt") for x in ce.get("earningsDate") or []]
                if dates and today not in dates:
                    continue                                                     # Yahoo вижда друга дата — очакванията може да са за друго тримесечие
                rev, eps = (ce.get("revenueAverage") or {}).get("raw"), (ce.get("earningsAverage") or {}).get("raw")
                if rev or eps:
                    e.update(revenue_estimate=rev, eps_estimate_yahoo=eps, estimate_as_of=today)
                    n += 1
            except Exception as ex:
                print(f"[overnight] очакванията за {e.get('ticker')}: {type(ex).__name__}: {ex}")
    return n


def capture_safe(week: dict | None, today: str) -> int:
    """capture_estimates, който не вдига (за main.run — без try там)."""
    try:
        return capture_estimates(week, today)
    except Exception as e:
        print(f"[overnight] очакванията не се записаха: {type(e).__name__}: {e}")
        return 0


def run_for_brief(today: str, prev_brief: dict, *, ours: dict | None = None, pool: list | None = None, now_utc=None) -> dict:
    """
    Сутрешният бриф (main): компаниите от календара на предишния бриф; ако той е отпреди 18.11 (без капитализацията) — + Nasdaq за сесията по прага / нашите, без отчетите
    преди отварянето (Nasdaq губи часа след отчета — yahoo_when го пази). Мрежа: Nasdaq (EPS), Yahoo quoteSummary, 5-мин. бари. Провал на източник → ред в "notes".
    """
    from src import econ_calendar, preopen as _po, sessions
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    session = sessions.prev_session(dt.date.fromisoformat(today))
    errors, nd = [], []
    try:
        nd = econ_calendar.fetch_earnings(session)
    except Exception as e:
        errors.append(f"Nasdaq (EPS) не отговори: {type(e).__name__}")
    cal_rows = companies(prev_brief, session.isoformat())
    old_cal = not ((prev_brief.get("week_calendar") or {}).get("cap_min_bn"))
    ours = ours or {}
    have = {r.get("ticker") for r in cal_rows}
    extra = [dict(r, why=econ_calendar.cap_label(r.get("market_cap")) or ours.get(r["ticker"]))
             for r in nd if r.get("ticker") not in have and r.get("when") in NIGHT_WHEN
             and (econ_calendar.cap_label(r.get("market_cap")) or r.get("ticker") in ours)] if old_cal else []
    qs = {r["ticker"]: fetch_quote_summary(r["ticker"], "earnings,calendarEvents") for r in cal_rows + extra if r.get("ticker")}
    extra = [r for r in extra if yahoo_when(qs.get(r["ticker"]), session.isoformat()) != "преди отварянето"]
    tickers = [r.get("ticker") for r in cal_rows + extra if r.get("ticker")]
    try:
        frames = _po.fetch_market(["ES=F", "NQ=F", "DX-Y.NYB", "ZN=F", "^TNX"] + tickers)
    except Exception as e:
        frames = {}
        errors.append(f"цените от Yahoo не се изтеглиха: {type(e).__name__}")
    res = build(today, {"week_calendar": {"days": [{"date": session.isoformat(), "earnings": cal_rows + extra}]}}, frames=frames, now_utc=now_utc,
                nasdaq_rows=nd, qs=qs, pool=pool, pool_checked=bool(pool), errors=errors)
    if extra:
        res["notes"].append("часът на отчета за " + ", ".join(r["ticker"] for r in extra) + " — по Yahoo (Nasdaq го губи след отчета); календарът на предишния бриф е отпреди 18.11")
    return res
