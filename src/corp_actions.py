"""
Корпоративни действия върху картите (09.10.2026). Yahoo записва отделяне (spin-off) като "сплит" с НЕЦЯЛ коефициент и коригира историята с оценъчен коефициент: CTVA на 01.10 (отделянето на Vylor) = 6.665; в деня цената
скача +7.9% при обичайно дневно отклонение 1.9% — историята около датата е приблизителна. Цял коефициент (2:1, 4:1, 10:1, обратен 1:5) е точна корекция. Затова картите на Action, Watchlist, GLB и QM получават МАРКЕР
(не изключване) "⚠ корпоративно действие на ДД.ММ …", ако в последните config.CORP_ACTION_WARN_SESSIONS сесии има събитие с нецял коефициент. Само информация; нищо не се променя в избора на карти.
Данни: една партида yf.download(…, period="6mo", actions=True) за всички тикъри на картите (колоната "Stock Splits"). Graceful: провал → без маркери, diag.ok=False и предупреждение в брифа (липсата на маркер тогава не значи "няма събитие").
"""
from __future__ import annotations
import datetime as dt

import numpy as np

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

try:
    import yfinance as yf
except Exception:                                    # pragma: no cover
    yf = None


def is_whole_ratio(r: float) -> bool:
    """Цял сплит коефициент: r или 1/r е цяло число ≥ 2 (в рамките на config.CORP_ACTION_INTEGER_TOL). 6.665, 1.243, 1.5, 2.39 → не; 2, 4, 10, 0.5, 0.2, 0.3333 → да."""
    try:
        r = float(r)
        if not r > 0 or r == 1:
            return False
        x = r if r > 1 else 1 / r
        return abs(x - round(x)) <= config.CORP_ACTION_INTEGER_TOL * x and round(x) >= 2
    except (TypeError, ValueError):
        return False


def sessions_since(event: dt.date, today: dt.date) -> int:
    """Работни дни (без NYSE празниците от config) от датата на събитието до today; събитие в бъдещето → отрицателно."""
    hol = sorted(config.NYSE_HOLIDAYS)
    if event <= today:
        return int(np.busday_count(event, today, holidays=hol))
    return -int(np.busday_count(today, event, holidays=hol))


def uncertain_events(dates, ratios, today: dt.date, sessions: int | None = None) -> list[dict]:
    """Събитията с нецял коефициент в последните `sessions` сесии: [{date, ratio, sessions_ago}] (най-новото първо). dates/ratios — паралелни редове на колоната "Stock Splits"."""
    sessions = config.CORP_ACTION_WARN_SESSIONS if sessions is None else sessions
    out = []
    for d, r in zip(dates, ratios):
        try:
            if r is None or r != r or float(r) == 0:
                continue
            day = dt.date.fromisoformat(str(d)[:10])
        except (TypeError, ValueError):
            continue
        n = sessions_since(day, today)
        if 0 <= n <= sessions and not is_whole_ratio(r):
            out.append({"date": day.isoformat(), "ratio": round(float(r), 4), "sessions_ago": n})
    return sorted(out, key=lambda e: e["date"], reverse=True)


def warning_text(ev: dict) -> str:
    d = dt.date.fromisoformat(ev["date"])
    return (f"⚠ корпоративно действие на {d.day:02d}.{d.month:02d} (коефициент {ev['ratio']:g} — отделяне или сплит с нецял коефициент) — "
            f"историята около датата е приблизителна")


def fetch_splits(tickers: list[str]) -> dict[str, tuple[list[str], list[float]]]:
    """{тикър: (дати, коефициенти)} от колоната "Stock Splits" на ЕДНА партида от Yahoo. Провал на тегленето → вдига (annotate го хваща); тикър без колона/данни просто липсва."""
    if yf is None:
        raise RuntimeError("yfinance не е наличен")
    data = yf.download(list(tickers), period="6mo", progress=False, auto_adjust=False, actions=True, group_by="ticker", threads=True)
    if data is None or len(data) == 0:
        raise ValueError("празен резултат")
    out = {}
    multi = hasattr(data.columns, "levels") and getattr(data.columns, "nlevels", 1) > 1
    for t in tickers:
        try:
            f = data[t] if multi else data
            col = f["Stock Splits"].dropna()
            out[t] = ([x.date().isoformat() for x in col.index], [float(v) for v in col.to_numpy()])
        except Exception:
            continue
    return out


def annotate(cards_groups: list[list[dict]], today: str | dt.date, fetch=None, sessions: int | None = None) -> dict:
    """
    Слага card["corp_action"] = {date, ratio, sessions_ago, text} върху картите (по тикър, във всички списъци), за които има събитие с нецял коефициент в последните `sessions` сесии. Връща diag
    {ok, checked, flagged: [{ticker, date, ratio}], error}. Не вдига изключения (graceful): провал → ok=False, без маркери.
    """
    fetch = fetch or fetch_splits
    day = today if isinstance(today, dt.date) else dt.date.fromisoformat(str(today)[:10])
    tickers = sorted({c.get("ticker") for g in cards_groups for c in (g or []) if isinstance(c, dict) and c.get("ticker")})
    diag = {"ok": True, "checked": len(tickers), "flagged": [], "error": None}
    if not tickers:
        return diag
    try:
        series = fetch(tickers)
        found = {}
        for t, (dates, ratios) in series.items():
            ev = uncertain_events(dates, ratios, day, sessions)
            if ev:
                found[t] = {**ev[0], "text": warning_text(ev[0])}
        for g in cards_groups:
            for c in g or []:
                if isinstance(c, dict) and c.get("ticker") in found:
                    c["corp_action"] = dict(found[c["ticker"]])
        diag["flagged"] = [{"ticker": t, "date": e["date"], "ratio": e["ratio"]} for t, e in sorted(found.items())]
    except Exception as e:
        diag.update(ok=False, error=f"{type(e).__name__}: {e}")
        print(f"[corp_actions] проверката за корпоративни действия пропусната: {diag['error']}")
    return diag
