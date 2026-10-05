"""
Предупреждение за отчет върху картата + очаквано движение от опциите (пакет 4б т.д, 06.10.2026). Само информация — размерът на позицията не се променя.

Данните идват от следобедната снимка (oi_snapshot.py, в сесията има валидни bid/ask): за нашите тикъри с отчет в следващите ~32 календарни дни снимката пази
ATM straddle на първия падеж СЛЕД отчета и на последния падеж ПРЕДИ него (сурови котировки, не готово число). Сутрешният бриф (annotate) смята:

    събитие = sqrt(A² − B²·Ta/Tb) / цена,   A, B = straddle (call mid + put mid) след/преди отчета, Ta, Tb = търговски сесии от снимката до падежа

Простият "straddle на падежа след отчета / цената" включва и базовата волатилност до падежа — реално 05.10: FTNT, отчет 28.10, падеж 30.10 — ±13.9%, а само
събитието е ±10.6% (изваждането на базата ползва падежа 23.10). Затова оценката е с два падежа. Ненадеждно (виж event_move) → само датата и
"няма данни за очаквано движение" с причината. Чисти функции; мрежа само в snapshot_* и next_earnings_date (подават се yfinance-подобни обекти).
"""
from __future__ import annotations
import datetime as dt
import json
import math
import re

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import setup_rules

_DAY = dt.timedelta(days=1)


def sessions_after(start: dt.date, end: dt.date) -> int:
    """Брой търговски сесии d със start < d <= end (NYSE празници от config). 0, ако end <= start."""
    n, d = 0, start + _DAY
    while d <= end and (d - start).days < 400:
        if setup_rules.is_session(d):
            n += 1
        d += _DAY
    return n


# ──────────────────────────────────────────────────────────────────────────
# Снимачна част (следобеден job): суровите котировки около ATM
# ──────────────────────────────────────────────────────────────────────────
def _spot(tk) -> float | None:
    """Последната цена: fast_info (в сесията), иначе последният Close."""
    try:
        fi = tk.fast_info
        v = fi["last_price"] if hasattr(fi, "__getitem__") else getattr(fi, "last_price", None)
        if v and float(v) > 0:
            return float(v)
    except Exception:
        pass
    try:
        h = tk.history(period="5d")
        return float(h["Close"].iloc[-1]) if h is not None and not h.empty else None
    except Exception:
        return None


def _leg(tk, expiry: str, spot: float, session: dt.date) -> dict:
    """ATM straddle на падежа: страйкът, най-близък до цената, който го има и за calls, и за puts; mid на двете крачета и bid/ask спредът им."""
    out = {"expiry": expiry, "sessions": sessions_after(session, dt.date.fromisoformat(expiry))}
    ch = tk.option_chain(expiry)
    calls, puts = ch.calls, ch.puts
    if calls is None or puts is None or calls.empty or puts.empty:
        return {**out, "reason": "празна верига"}
    common = sorted(set(calls["strike"]) & set(puts["strike"]))
    if not common:
        return {**out, "reason": "няма общ страйк за calls и puts"}
    k = min(common, key=lambda x: abs(x - spot))
    out["strike"] = float(k)
    for name, df in (("call", calls), ("put", puts)):
        r = df[df["strike"] == k].iloc[0]
        bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
        if bid <= 0 or ask <= 0 or ask < bid:
            return {**out, "reason": f"няма котировка (bid/ask) за {name} на страйк {k:g}"}
        mid = (bid + ask) / 2
        out[f"{name}_mid"] = round(mid, 4)
        out[f"{name}_spread_pct"] = round((ask - bid) / mid * 100, 1)
    return out


def snapshot_straddle(tk, earnings_date: str, session: dt.date, spot: float | None = None) -> dict:
    """Сурови крачета за един тикър: първият падеж СЛЕД отчета (after) и последният ПРЕДИ него (before, след снимката). Без нужен падеж → reason."""
    e = dt.date.fromisoformat(earnings_date)
    spot = spot or _spot(tk)
    res: dict = {"earnings_date": earnings_date, "session": session.isoformat(), "spot": round(spot, 2) if spot else None}
    if not spot:
        return {**res, "reason": "няма цена за тикъра"}
    exps = sorted(str(x) for x in (tk.options or ()))
    after = next((x for x in exps if dt.date.fromisoformat(x) > e), None)
    before = next((x for x in reversed(exps) if session < dt.date.fromisoformat(x) < e), None)
    if after is None:
        return {**res, "reason": "няма падеж след отчета"}
    res["after"] = _leg(tk, after, spot, session)
    if before:
        res["before"] = _leg(tk, before, spot, session)
    return res


def dates_from_briefs(max_briefs: int | None = None) -> dict[str, str]:
    """Дата на следващия отчет по тикър от Action/Watchlist картите на последните брифове (най-новият печели) — същите дати, които картата показва."""
    n = config.UNUSUAL_OPTIONS_SNAPSHOT_BRIEF_DAYS if max_briefs is None else max_briefs
    out: dict[str, str] = {}
    files = sorted((p for p in config.DATA_DIR.glob("*.json") if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", p.name)), reverse=True)[:n]
    for path in files:
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for c in (brief.get("action") or []) + (brief.get("watchlist") or []):
            d = (c.get("earnings") or {}).get("next_earnings")
            if c.get("ticker") and d and c["ticker"] not in out:
                out[c["ticker"]] = str(d)[:10]
    return out


def next_earnings_date(sym: str, yf_mod, today: dt.date) -> str | None:
    """Датата на следващия отчет за тикър без карта (напр. позиция) — календарът на Yahoo, иначе get_earnings_dates(); минала дата се отхвърля."""
    try:
        tk = yf_mod.Ticker(sym)
        cal = tk.calendar
        dates = (cal.get("Earnings Date") or []) if isinstance(cal, dict) else []
        for d in dates:
            d = d.date() if isinstance(d, dt.datetime) else d
            if d >= today:
                return d.isoformat()
        df = tk.get_earnings_dates(limit=8)
        if df is not None and len(df):
            future = [ts.date() for ts in df.index if ts.date() >= today]
            if future:
                return min(future).isoformat()
    except Exception as e:
        print(f"[earnings_move] {sym}: датата на отчета: {type(e).__name__}: {e}")
    return None


def snapshot_straddles(tickers: list[str], session: dt.date, yf_mod, today: dt.date | None = None) -> dict[str, dict]:
    """
    За снимката: straddle-и за тикърите с отчет в (session, session + EARNINGS_SNAPSHOT_WINDOW_DAYS]. Датите са от картите на последните брифове,
    за останалите (позиции) — от календара. Graceful: тикър, който гръмне, се пропуска (в утрешния бриф: "няма данни").
    """
    today = today or session
    dates = dates_from_briefs()
    hi = session + dt.timedelta(days=config.EARNINGS_SNAPSHOT_WINDOW_DAYS)
    out: dict[str, dict] = {}
    for sym in tickers:
        try:
            d = dates.get(sym) or next_earnings_date(sym, yf_mod, today)
            if not d or not (session < dt.date.fromisoformat(d) <= hi):
                continue
            out[sym] = snapshot_straddle(yf_mod.Ticker(sym), d, session)
        except Exception as e:
            print(f"[earnings_move] {sym}: straddle: {type(e).__name__}: {e}")
    return out


# ──────────────────────────────────────────────────────────────────────────
# Сутрешна част: оценка и предупреждение (чисти функции)
# ──────────────────────────────────────────────────────────────────────────
def _leg_problem(leg: dict | None, spot: float, name: str) -> str | None:
    if not leg:
        return f"няма падеж {name} отчета"
    if leg.get("reason"):
        return f"падежът {name} отчета {leg['expiry']}: {leg['reason']}"
    if max(leg["call_spread_pct"], leg["put_spread_pct"]) > config.EARNINGS_MOVE_MAX_SPREAD_PCT:
        return f"спредът bid/ask на падежа {name} отчета ({leg['expiry']}) е твърде широк"
    if abs(leg["strike"] - spot) / spot * 100 > config.EARNINGS_MOVE_MAX_STRIKE_DIST_PCT:
        return f"няма страйк близо до цената на падежа {name} отчета ({leg['expiry']})"
    return None


def event_move(st: dict | None, card_date: str) -> dict:
    """
    Очакваното движение при отчета от снимката st (snapshot_straddle) за отчет на card_date. Връща {"pct": число | None, "reason": причина при None, ...детайли}.
    Ненадеждно е при: липсващ тикър/дата различна от снимката/няма падеж; падеж след отчета по-късно от EARNINGS_MOVE_MAX_EXPIRY_GAP_DAYS; липсваща базова
    линия (падеж преди отчета); широк спред или далечен страйк; събитие, което не се вижда в премията (A² ≤ B²·Ta/Tb); нереалистичен резултат.
    """
    if not st:
        return {"pct": None, "reason": "тикърът не е в опционната снимка"}
    if st.get("earnings_date") != card_date:
        return {"pct": None, "reason": f"датата на отчета е сменена след снимката (при снимката: {st.get('earnings_date')})"}
    if st.get("reason"):
        return {"pct": None, "reason": st["reason"]}
    spot = st.get("spot")
    after, before = st.get("after"), st.get("before")
    e = dt.date.fromisoformat(card_date)
    why = _leg_problem(after, spot, "след")
    if why:
        return {"pct": None, "reason": why}
    gap = (dt.date.fromisoformat(after["expiry"]) - e).days
    if gap > config.EARNINGS_MOVE_MAX_EXPIRY_GAP_DAYS:
        return {"pct": None, "reason": f"първият падеж след отчета е {after['expiry']}, {gap} дни след него — премията е предимно времева стойност"}
    why = _leg_problem(before, spot, "преди")
    if why:
        return {"pct": None, "reason": why + " — базовата волатилност не може да се извади"}
    if before["sessions"] < config.EARNINGS_MOVE_MIN_BASELINE_SESSIONS:
        return {"pct": None, "reason": f"падежът преди отчета ({before['expiry']}) е твърде близо до снимката"}
    if (dt.date.fromisoformat(after["expiry"]) - dt.date.fromisoformat(before["expiry"])).days > config.EARNINGS_MOVE_MAX_BASELINE_GAP_DAYS:
        return {"pct": None, "reason": f"падежите {before['expiry']} и {after['expiry']} са твърде раздалечени за извличане на базата"}
    A = after["call_mid"] + after["put_mid"]
    B = before["call_mid"] + before["put_mid"]
    ev2 = A * A - B * B * after["sessions"] / before["sessions"]
    if ev2 <= 0:
        return {"pct": None, "reason": "премията преди и след отчета е почти еднаква — събитието не се вижда в цените"}
    pct = math.sqrt(ev2) / spot * 100
    if not (config.EARNINGS_MOVE_MIN_PCT <= pct <= config.EARNINGS_MOVE_MAX_PCT):
        return {"pct": None, "reason": f"нереалистична оценка ({pct:.1f}%)"}
    return {"pct": round(pct, 1), "naive_pct": round(A / spot * 100, 1), "spot": spot, "straddle_after": round(A, 2), "straddle_before": round(B, 2),
            "after_expiry": after["expiry"], "before_expiry": before["expiry"], "session": st.get("session")}


def _dm(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


def warning_for(earnings_date: str, today: dt.date, st: dict | None, missing_reason: str = "") -> dict | None:
    """Предупреждението за карта с отчет на earnings_date; None ако отчетът е минал или е след EARNINGS_WARNING_SESSIONS сесии."""
    d = dt.date.fromisoformat(earnings_date[:10])
    if d < today:
        return None
    n = sessions_after(today, d)
    if n > config.EARNINGS_WARNING_SESSIONS:
        return None
    when = "днес" if d == today else "утре" if n == 1 and (d - today).days == 1 else f"след {n} {'сесия' if n == 1 else 'сесии'}"
    res = {"pct": None, "reason": missing_reason} if missing_reason else event_move(st, d.isoformat())
    out = {"date": d.isoformat(), "sessions": n, "implied_move_pct": res["pct"], "reason": res.get("reason")}
    if res["pct"] is not None:
        out.update(spot=res["spot"], straddle_after=res["straddle_after"], straddle_before=res["straddle_before"], after_expiry=res["after_expiry"],
                   before_expiry=res["before_expiry"], naive_pct=res["naive_pct"], snapshot_session=res["session"])
        out["text"] = (f"⚠ Отчет на {_dm(d.isoformat())} ({when}) — пазарът очаква ±{res['pct']}% при отчета (оценка от straddle-ите на "
                       f"{_dm(res['before_expiry'])} и {_dm(res['after_expiry'])} с извадена базова волатилност; цена ${res['spot']:.2f}, опции от {_dm(res['session'])}).")
    else:
        out["text"] = f"⚠ Отчет на {_dm(d.isoformat())} ({when}) — няма данни за очаквано движение ({res['reason']})."
    return out


def annotate(cards: list[dict], today: dt.date | None = None, snapshot_loader=None) -> int:
    """
    Слага card["earnings_warning"] на картите с отчет в следващите EARNINGS_WARNING_SESSIONS сесии. snapshot_loader() → (снимка, сесия, причина при липса)
    — по подразбиране последната снимка (unusual_options._snapshot_for_yesterday). Връща броя предупреждения. Не променя нищо друго по картата.
    """
    today = today or dt.date.today()
    snap, session, snap_why = None, "", ""
    due = [c for c in cards if (c.get("earnings") or {}).get("next_earnings")]
    if not due:
        return 0
    try:
        if snapshot_loader is None:
            from src import unusual_options as uo
            snapshot_loader = lambda: uo._snapshot_for_yesterday(today)
        snap, session, snap_why = snapshot_loader()
    except Exception as e:
        snap_why = f"снимката не се зареди: {type(e).__name__}"
    straddles = (snap or {}).get("straddles")
    missing = ""
    if snap is None:
        missing = snap_why or "опционната снимка липсва"
    elif straddles is None:
        missing = "снимката още няма данни за отчети (стар формат)"
    n = 0
    for c in due:
        try:
            w = warning_for(c["earnings"]["next_earnings"], today, (straddles or {}).get(c["ticker"]), missing)
        except Exception as e:
            print(f"[earnings_move] {c.get('ticker')}: {type(e).__name__}: {e}")
            continue
        if w:
            c["earnings_warning"] = w
            n += 1
    return n
