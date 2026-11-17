"""
17.11.2026 (пакет 2, т. 2 — А4, решение след стратегическия преглед): „Чака пробив“ → аларма с обем. Картата казва „Аларма над $X — вход само с обем“ и колко акции трябва
да са изтъргувани до 10:30 / 12:00 / 14:00 Ню Йорк, за да е денят с обем ≥ BREAKOUT_VOLUME_MULT (1.5×) средния за 50 сесии — по собствения профил на акцията (5-минутните
бари за последните ~20 сесии: средният дял от обема на сесията, натрупан до всеки час); без собствен профил — по общия (config.VOLUME_PROFILE_GENERIC) с етикет.
Измерено 17.11.2026 върху 20 ликвидни акции × 21 сесии: медианата на дяловете — 21.2% до 10:30, 40.0% до 12:00, 60.0% до 14:00; разликите са големи (RGA 10.5%, NVDA 34.1%
до 10:30) — затова собственият профил е основният. Книгата записва както досега (при докосване); етикетът „обемът потвърди / не потвърди“ е там (backtest.entry_volume).
Мрежа само във fetch_profiles; провал → общият профил с етикет (graceful).
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


def profile(volume, days: int | None = None, min_bars: int = 70) -> dict | None:
    """Volume (pandas Series с часовете, tz-aware) → {"10:30": дял, …, "days": N} — средно за последните `days` цели сесии (≥ min_bars 5-мин. бара); под VOLUME_PROFILE_MIN_DAYS → None."""
    import pandas as pd
    days = days or config.VOLUME_PROFILE_DAYS
    try:
        v = volume.dropna()
        v.index = (v.index.tz_localize("UTC") if v.index.tz is None else v.index).tz_convert("America/New_York")
        v = v.between_time("09:30", "15:55")
        rows = []
        for _, g in v.groupby(v.index.date):
            tot = float(g.sum())
            if tot <= 0 or len(g) < min_bars:
                continue
            c = g.cumsum() / tot
            row = {}
            for t in config.VOLUME_ALARM_TIMES:
                hh, mm = map(int, t.split(":"))
                end = (pd.Timestamp(2000, 1, 1, hh, mm) - pd.Timedelta(minutes=5)).time()          # барът, който завършва в t
                x = c[c.index.time <= end]
                row[t] = float(x.iloc[-1]) if len(x) else 0.0
            rows.append(row)
        rows = rows[-days:]
        if len(rows) < config.VOLUME_PROFILE_MIN_DAYS:
            return None
        return {**{t: round(sum(r[t] for r in rows) / len(rows), 3) for t in config.VOLUME_ALARM_TIMES}, "days": len(rows)}
    except Exception as e:
        print(f"[volume_alarm] профилът не се смята: {type(e).__name__}: {e}")
        return None


def fetch_profiles(tickers: list[str], download=None) -> dict[str, dict | None]:
    """{тикър: профил | None} — едно теглене на 5-минутните бари (1 месец). Провал → {} (картите — по общия профил)."""
    tickers = sorted({t for t in tickers if t})
    if not tickers:
        return {}
    try:
        import yfinance as yf
        dl = download or (lambda ts: yf.download(ts, period="1mo", interval="5m", prepost=False, group_by="ticker", auto_adjust=False, progress=False, threads=True))
        df = dl(tickers)
        out = {}
        for t in tickers:
            try:
                out[t] = profile(df[t]["Volume"] if len(tickers) > 1 else df["Volume"])
            except Exception:
                out[t] = None
        return out
    except Exception as e:
        print(f"[volume_alarm] 5-минутните бари не се изтеглиха: {type(e).__name__}: {e}")
        return {}


def _shares(n: float) -> str:
    return f"{n / 1e6:.2f} млн" if n >= 1e6 else f"{n / 1e3:.0f} хил."


def alarm(card: dict, prof: dict | None) -> dict | None:
    """Алармата за картата „Чака пробив“: {"level", "need": [{"time", "shares", "frac"}], "day", "source", "text"}; без buy-stop или среден обем → None. Чиста функция."""
    s = (card or {}).get("setup") or {}
    level, avg = s.get("buy_stop"), (card or {}).get("avg_volume_50d")
    if not level or not avg:
        return None
    day = config.BREAKOUT_VOLUME_MULT * float(avg)
    p, own = (prof, True) if prof else (config.VOLUME_PROFILE_GENERIC, False)
    need = [{"time": t, "frac": p[t], "shares": round(day * p[t])} for t in config.VOLUME_ALARM_TIMES]
    src = (f"собствен профил ({prof['days']} сесии)" if own else
           "общ профил — собственият липсва (медианата на 20 ликвидни акции: 21% до 10:30, 40% до 12:00, 60% до 14:00)")
    text = (f"Аларма над ${level:.2f} — вход само с обем: " + ", ".join(f"до {x['time']} Ню Йорк ≥ {_shares(x['shares'])} акции" for x in need)
            + f"; за деня ≥ {_shares(day)} ({config.BREAKOUT_VOLUME_MULT:g}× средния за 50 сесии) · {src}")
    return {"level": level, "need": need, "day": round(day), "source": "own" if own else "generic", "text": text}


def annotate(watchlist: list[dict], profiles: dict | None) -> int:
    """card["volume_alarm"] върху картите под pivot с buy-stop, незадействани; връща броя."""
    n = 0
    for c in watchlist or []:
        s = c.get("setup") or {}
        if s.get("kind") == "below_pivot" and s.get("buy_stop") and not s.get("triggered"):
            a = alarm(c, (profiles or {}).get(c.get("ticker")))
            if a:
                c["volume_alarm"] = a
                n += 1
    return n
