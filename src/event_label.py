"""
26.10.2026 (етап 4б, т. 2 — решение от 26.10): етикет „събитие/M&A“ върху записите в книгите — и за СЛУХОВЕ (цел на подписана сделка е етикетът "deal", виж backtest.apply_deal_labels).
Правило: скок ≥ config.EVENT_JUMP_PCT (8%) при обем ≥ config.EVENT_VOL_X (3×) средния за 50 сесии преди деня — в деня на сигнала / сетъпа / входа на записа — И заглавие за продажба,
придобиване или сливане на компанията около този ден (Google News RSS по тикъра и по името, от 2 дни преди до 1 ден след). Записите остават; статистиката на книгите се показва с тях и без тях,
а групите по обем при входа са без "deal" / "event".

Реално: CART, 23.10 (сигнал на първия запис в книгата „GLB по Уиш“) — +9.2% при 4.4× обем, а заглавията от деня са „Instacart Is Exploring a Sale, and Uber and DoorDash Are Circling“,
„Instacart gains on report it's in talks to sell itself“. Измерено 26.10 върху 53-те записа в книгите: условието за цена и обем — 1 (CART); най-близкият друг — R (Ryder) +10.5% при 2.3×.
Продажба на акции от служител („24,060 shares are proposed for sale by … officer“, Form 144) НЕ е новина за продажба на компанията.

Всеки запис се проверява веднъж (rec["event_checked"] = ден), когато дните му са окончателни (чакащ buy-stop — след задействането или изтичането). Всяка грешка → записът остава
непроверен до следващия run (graceful); нищо не вдига.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

import config

LAST_STATUS: dict = {}

# продажба / придобиване / сливане на КОМПАНИЯТА — и като слух ("explores a sale", "talks to sell itself", "takeover interest")
MA_RE = re.compile(
    r"explor\w*\s+(?:a\s+|potential\s+|possible\s+|strategic\s+)?(?:sale|options|alternatives)|sale\s+(?:talks|process|options)|potential\s+sale|possible\s+sale|"
    r"sell(?:s|ing)?\s+itself|(?:talks|discussions)\s+(?:to|about)\s+(?:sell|buy|acquire|merge|be\s+acquired)|in\s+talks\s+(?:with|to)|takeover|buyout|tender\s+offer|"
    r"go(?:es|ing)?[-\s]private|strategic\s+alternatives|merger|\bto\s+(?:acquire|buy)\b|to\s+be\s+(?:acquired|bought)|acquisition\s+(?:of|by|talks|offer|interest)|"
    r"agrees?\s+to\s+(?:be\s+)?(?:acquired|bought|buy|acquire)|approach(?:es|ed)?\s+(?:by|about)|bid\s+for|offer\s+for|deal\s+to\s+(?:buy|acquire|sell)",
    re.I)
# продажба на АКЦИИ (служители, Form 144, вторично предлагане) — не е новина за сделка
NOT_RE = re.compile(r"shares?\s+(?:are\s+)?(?:proposed\s+)?for\s+sale|insider|form\s+144|officer|director\s+sells|stock\s+sale|sale\s+of\s+(?:\d|shares|stock)|secondary\s+offering|"
                    r"proposes\s+another\s+sale|sells\s+\$?[\d,.]+\s*(?:in\s+)?(?:stock|shares)", re.I)


def jump(closes, volumes, day: str) -> tuple[float, float] | None:
    """(промяна %, обем × средния за EVENT_VOL_AVG_SESSIONS сесии преди деня) за деня `day` от дневните серии (pandas Series, индекс = дата); без бар или история → None. Чиста функция."""
    import pandas as pd
    try:
        c, v = closes.dropna(), volumes.dropna()
        for s in (c, v):
            idx = pd.DatetimeIndex(s.index)
            s.index = idx.tz_localize(None) if idx.tz is not None else idx
        ts = pd.Timestamp(day)
        if ts not in c.index or ts not in v.index:
            return None
        i, k = c.index.get_loc(ts), v.index.get_loc(ts)
        n = config.EVENT_VOL_AVG_SESSIONS
        if i < 1 or k < n:
            return None
        avg = float(v.iloc[k - n:k].mean())
        if avg <= 0:
            return None
        return round((float(c.iloc[i]) / float(c.iloc[i - 1]) - 1) * 100, 2), round(float(v.iloc[k]) / avg, 2)
    except Exception:
        return None


def is_jump(j: tuple[float, float] | None) -> bool:
    return bool(j) and abs(j[0]) >= config.EVENT_JUMP_PCT and j[1] >= config.EVENT_VOL_X


def ma_headlines(items: list[dict]) -> list[dict]:
    """Заглавията за продажба / придобиване / сливане (без продажба на акции от служители); чиста функция."""
    out, seen = [], set()
    for it in items or []:
        t = (it.get("title") or "").strip()
        if t and t not in seen and MA_RE.search(t) and not NOT_RE.search(t):
            seen.add(t)
            out.append({"title": t, "source": it.get("source")})
    return out


def _gnews_url(query: str, day: str) -> str:
    d = dt.date.fromisoformat(day)
    after, before = (d - dt.timedelta(days=config.EVENT_NEWS_DAYS_BEFORE + 1)).isoformat(), (d + dt.timedelta(days=config.EVENT_NEWS_DAYS_AFTER + 1)).isoformat()
    q = urllib.parse.quote_plus(f"{query} after:{after} before:{before}")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def news(ticker: str, name: str | None, day: str, fetch=None) -> list[dict]:
    """Заглавията за тикъра около деня (Google News RSS: „"TICKER" stock“ и името на компанията). fetch(url) → [{title, source}] — за тестовете; по подразбиране news_aggregator._fetch_rss."""
    if fetch is None:
        from src import news_aggregator
        fetch = lambda url: news_aggregator._fetch_rss(url, "Google News", 24 * 3650, limit=40)
    items = []
    for q in [f'"{ticker}" stock'] + ([f'"{name}"'] if name and name.upper() != ticker.upper() else []):
        try:
            items += fetch(_gnews_url(q, day)) or []
        except Exception as e:
            print(f"[event] новини за {ticker} ({q}): {type(e).__name__}: {e}")
    return items


def _yf_bars(tickers: list[str]) -> dict:
    """Дневни Close / Volume за година (един batch); липсващ тикър → без него."""
    import yfinance as yf
    ts = sorted(set(tickers))
    d = yf.download(ts, period="1y", auto_adjust=False, group_by="ticker", progress=False, threads=True)
    out = {}
    for t in ts:
        try:
            out[t] = (d[t] if len(ts) > 1 else d)[["Close", "Volume"]].dropna()
        except Exception:
            continue
    return out


def record_days(rec: dict) -> list[str] | None:
    """Дните на записа за проверката (сигнал / сетъп / вход); None — още не са окончателни (чакащ запис без вход)."""
    from src import sessions
    if rec.get("status") == "pending" and rec.get("category") not in ("glb_wish", "glb_wish_high"):
        return None                                                          # чакащ buy-stop / QM — денят на входа още не е известен (при GLB входът е сигналният ден)
    days = set()
    if rec.get("signal_date"):
        days.add(rec["signal_date"])
    elif rec.get("entry_date"):
        days.add(sessions.prev_session(dt.date.fromisoformat(rec["entry_date"][:10])).isoformat())
    if rec.get("fill_date"):
        days.add(rec["fill_date"])
    return sorted(days)


def label_records(tracker: dict, today: str, download=None, fetch=None, name_lookup=None) -> dict:
    """
    Проверява непроверените записи в tracker-а (мутира го): rec["event"] = {day, ret_pct, vol_x, headline, source} при скок + заглавие; rec["event_checked"] = today, когато дните са окончателни
    и баровете ги покриват. download(tickers) → {тикър: DataFrame с Close, Volume}. Връща статуса {"ok", "checked", "jumps", "labelled", "tickers"} (и LAST_STATUS).
    """
    st = {"ok": True, "checked": 0, "jumps": 0, "labelled": [], "reason": None}
    LAST_STATUS.clear(); LAST_STATUS.update(st)
    todo = [(k, r) for k, r in tracker.items() if isinstance(r, dict) and r.get("ticker") and not r.get("event_checked") and record_days(r)]
    if not todo:
        return st
    try:
        bars = (download or _yf_bars)([r["ticker"] for _, r in todo]) or {}
        for k, r in todo:
            b = bars.get(r["ticker"])
            if b is None or not len(b):
                continue
            days = record_days(r)
            js = {d: jump(b["Close"], b["Volume"], d) for d in days}
            if any(j is None for j in js.values()):
                continue                                                         # денят още не е в баровете (или няма история) — следващия run
            st["checked"] += 1
            r["event_checked"] = today
            hit = next(((d, j) for d, j in js.items() if is_jump(j)), None)
            if not hit:
                continue
            st["jumps"] += 1
            d, j = hit
            heads = ma_headlines(news(r["ticker"], name_lookup(r["ticker"]) if name_lookup else None, d, fetch))
            if heads:
                r["event"] = {"day": d, "ret_pct": j[0], "vol_x": j[1], "headline": heads[0]["title"], "source": heads[0]["source"], "headlines": len(heads)}
                st["labelled"].append(r["ticker"])
                print(f"[event] {r['ticker']} ({k}): {d} {j[0]:+.1f}% при {j[1]:.1f}× обем — «{heads[0]['title'][:100]}» → събитие/M&A")
    except Exception as e:
        st.update(ok=False, reason=f"{type(e).__name__}: {e}")
        print(f"[event] проверката пропусната: {st['reason']}")
    LAST_STATUS.clear(); LAST_STATUS.update(st)
    return st
