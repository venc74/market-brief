"""
Предупреждение за отчет върху картата (пакет 4б т.д, 06.10.2026). Само информация — решението остава на човека.
17.11.2026 (пакет 1, т. 2в — решение след стратегическия преглед): очакваното движение от опциите (straddle-ите от следобедната OI снимка) — махнато заедно с опционния
стек (oi_snapshot.py, unusual_options.py); остава датата на отчета и броят сесии до него: „⚠ Отчет на ДД.ММ (след N сесии).“ Чисти функции; мрежа само в next_earnings_date.
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
    """Брой търговски сесии d със start < d <= end (NYSE празници от config). 0, ако end <= start (src/sessions.sessions_in, до 400 дни)."""
    from src import sessions
    return sessions.sessions_in(start, end, cap_days=400)


def dates_from_briefs(max_briefs: int | None = None) -> dict[str, str]:
    """Дата на следващия отчет по тикър от Action/Watchlist картите на последните брифове (най-новият печели) — същите дати, които картата показва."""
    n = config.EARNINGS_BRIEF_DAYS if max_briefs is None else max_briefs
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


def yahoo_lookup(today: dt.date):
    """Датата на следващия отчет по календара на Yahoo (next_earnings_date) — за book_marks; yfinance се зарежда при първото извикване."""
    def look(sym: str) -> str | None:
        import yfinance as yf
        return next_earnings_date(sym, yf, today)
    return look


def book_marks(rows: list[dict], today: dt.date, dates: dict | None = None, lookup=None, statuses=("open", "trailing")) -> int:
    """
    26.10.2026 (етап 4б, т. 10): отворена позиция в книга (QM) с отчет в следващите EARNINGS_WARNING_SESSIONS сесии → row["earnings_next"] = {"date", "sessions"} — ред в таблицата
    на книгата (CBOE и UTHR: отворени от 20.10, отчети тази седмица). Датата — от картите на последните брифове (dates_from_briefs), иначе lookup(тикър) (календарът на Yahoo). Връща броя.
    """
    n = 0
    try:
        dates = dates_from_briefs() if dates is None else dates
    except Exception as e:
        print(f"[earnings_move] датите от брифовете: {type(e).__name__}: {e}")
        dates = {}
    for r in rows or []:
        if r.get("status") not in statuses or not r.get("ticker"):
            continue
        try:
            d = dates.get(r["ticker"]) or (lookup(r["ticker"]) if lookup else None)
            if not d:
                continue
            k = sessions_after(today, dt.date.fromisoformat(str(d)[:10]))
            if dt.date.fromisoformat(str(d)[:10]) >= today and k <= config.EARNINGS_WARNING_SESSIONS:
                r["earnings_next"] = {"date": str(d)[:10], "sessions": k}
                n += 1
        except Exception as e:
            print(f"[earnings_move] {r.get('ticker')}: отчетът за книгата: {type(e).__name__}: {e}")
    return n


def _dm(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


def warning_for(earnings_date: str, today: dt.date, estimate: bool | None = None) -> dict | None:
    """
    Предупреждението за карта с отчет на earnings_date; None ако отчетът е минал или е след EARNINGS_WARNING_SESSIONS сесии. 03.11.2026: estimate → „~ДД.ММ (прогноза)“.
    17.11.2026 (т. 2в): без очакваното движение от опциите — опционният стек е махнат.
    """
    d = dt.date.fromisoformat(earnings_date[:10])
    if d < today:
        return None
    n = sessions_after(today, d)
    if n > config.EARNINGS_WARNING_SESSIONS:
        return None
    when = "днес" if d == today else "утре" if n == 1 and (d - today).days == 1 else f"след {n} {'сесия' if n == 1 else 'сесии'}"
    dm = f"~{_dm(d.isoformat())} (прогноза)" if estimate else _dm(d.isoformat())
    return {"date": d.isoformat(), "sessions": n, "estimate": bool(estimate), "text": f"⚠ Отчет на {dm} ({when})."}


def annotate(cards: list[dict], today: dt.date | None = None) -> int:
    """Слага card["earnings_warning"] на картите с отчет в следващите EARNINGS_WARNING_SESSIONS сесии. Връща броя предупреждения. Не променя нищо друго по картата."""
    today = today or dt.date.today()
    n = 0
    for c in cards:
        e = c.get("earnings") or {}
        if not e.get("next_earnings"):
            continue
        try:
            w = warning_for(e["next_earnings"], today, estimate=e.get("earnings_estimate"))
        except Exception as ex:
            print(f"[earnings_move] {c.get('ticker')}: {type(ex).__name__}: {ex}")
            continue
        if w:
            c["earnings_warning"] = w
            n += 1
    return n
