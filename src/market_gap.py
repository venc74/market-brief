"""
23.11.2026 (пакет 23.11, т. 4): ден на пазарен гап. На 23.11 в 08:55 Ню Йорк NQ беше +5.08%, ES +3.40% (спрямо 16:00 на петък) — EP гаповете (CRWV +33%, NVDA +28%, NBIS +26%, …),
„Нови днес“ и записите в книгите бяха пазарен ход, не индивидуални сетъпи. Денят е „ден на пазарен гап“, когато NQ ≥ ±config.MARKET_GAP_NQ_PCT % ИЛИ ES ≥ ±config.MARKET_GAP_ES_PCT %
по фючърсите в карето преди отварянето (data/preopen/<дата>.json → market.futures, 5-минутният бар от 08:55 Ню Йорк). Дни без карето (преди 13.11 няма фючърси) — неизвестни,
без етикет. EP гапът без собствена новина (8-K след затварянето или заглавие за компанията — не общ преглед, не списък с няколко акции, не „защо се движи“) → „пазарен ход“.
Чисти функции освен day() (чете data/preopen).
"""
from __future__ import annotations

import json
import re

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_SYM = {"NQ=F": "NQ", "ES=F": "ES"}


def classify(futures: list | None) -> dict | None:
    """market.futures от карето → {"gap": bool, "nq", "es", "time_ny", "text"}; без NQ и ES → None (неизвестно). Чиста функция."""
    ch = {_SYM[f["symbol"]]: f for f in futures or [] if isinstance(f, dict) and f.get("symbol") in _SYM and isinstance(f.get("chg_pct"), (int, float))}
    if not ch:
        return None
    nq, es = (ch.get("NQ") or {}).get("chg_pct"), (ch.get("ES") or {}).get("chg_pct")
    gap = (nq is not None and abs(nq) >= config.MARKET_GAP_NQ_PCT) or (es is not None and abs(es) >= config.MARKET_GAP_ES_PCT)
    when = next((f.get("last_ny") for f in ch.values() if f.get("last_ny")), None)
    parts = [f"{k} {v['chg_pct']:+.2f}%" for k, v in sorted(ch.items(), key=lambda kv: kv[0] != "NQ")]
    return {"gap": bool(gap), "nq": nq, "es": es, "time_ny": when,
            "text": ("фючърсите сочат ден на пазарен гап: " if gap else "") + ", ".join(parts) + (f" в {when} Ню Йорк" if when else "")
                    + " (спрямо затварянето на предишната сесия; етикетът в книгите и дневника — по отварянето на SPY / QQQ)"}


def day(date_iso: str, folder=None) -> dict | None:
    """Денят по записаното каре (data/preopen/<дата>.json) → classify(...) + "date"; без каре / без фючърси → None. Провал при четене → None."""
    p = pathlib.Path(folder or config.DATA_DIR / "preopen") / f"{str(date_iso)[:10]}.json"
    try:
        if not p.exists():
            return None
        mg = classify(((json.loads(p.read_text(encoding="utf-8")).get("market") or {}).get("futures")))
        return {**mg, "date": str(date_iso)[:10]} if mg else None
    except Exception as e:
        print(f"[market_gap] {p.name}: {type(e).__name__}")
        return None


def open_gaps(daily: dict | None) -> dict[str, dict]:
    """
    27.11.2026 (уикенд пакет, т. 5): денят на пазарен гап по РЕАЛНОТО отваряне — отварянето на QQQ / SPY срещу затварянето на предишната сесия, със същите прагове (QQQ ≥ ±3% като NQ,
    SPY ≥ ±2% като ES). До 27.11 етикетът беше по фючърсите в 08:55 Ню Йорк. daily — {"SPY": df, "QQQ": df} (Open, Close; дневни). → {дата: {"gap", "qqq", "spy", "text"}}.
    Реално: от 01.07 — 23.11 (QQQ +7.81%, SPY +5.00%) и 25.11 (QQQ −3.29%, SPY −2.17% на отварянето; затварянето — −0.65% / −0.29%). Чиста функция.
    """
    import pandas as pd
    per: dict = {}
    for sym in ("SPY", "QQQ"):
        df = (daily or {}).get(sym)
        if df is None or len(df) < 2 or "Open" not in df or "Close" not in df:
            continue
        df = df.dropna(subset=["Open", "Close"]).sort_index()
        g = (df["Open"] / df["Close"].shift(1) - 1) * 100
        for ts, v in g.dropna().items():
            per.setdefault(str(pd.Timestamp(ts).date()), {})[sym] = round(float(v), 2)
    out = {}
    for d, v in per.items():
        q, s = v.get("QQQ"), v.get("SPY")
        gap = (q is not None and abs(q) >= config.MARKET_GAP_NQ_PCT) or (s is not None and abs(s) >= config.MARKET_GAP_ES_PCT)
        out[d] = {"gap": bool(gap), "qqq": q, "spy": s,
                  "text": ("ден на пазарен гап: " if gap else "") + ", ".join(f"{k} {x:+.2f}%" for k, x in (("QQQ", q), ("SPY", s)) if x is not None) + " на отварянето"}
    return out


_OPEN_GAPS: dict = {}


def fetch_daily(start: str) -> dict:
    """Дневните бари на SPY и QQQ (Yahoo, auto_adjust=False — отварянето и затварянето в един мащаб) от start. Провал → {}."""
    import yfinance as yf
    import pandas as pd
    out = {}
    try:
        data = yf.download(["SPY", "QQQ"], start=start, interval="1d", group_by="ticker", progress=False, threads=True, auto_adjust=False)
        for s in ("SPY", "QQQ"):
            df = data[s] if isinstance(data.columns, pd.MultiIndex) else data
            df = df.dropna(subset=["Open", "Close"])
            if len(df):
                out[s] = df[["Open", "Close"]]
    except Exception as e:
        print(f"[market_gap] дневните бари на SPY / QQQ: {type(e).__name__}: {e}")
    return out


def open_gap_days(start: str, fetch=None) -> dict[str, dict]:
    """open_gaps за дните от start — едно теглене на пускане (кеш в модула); провал → {} (неизвестно — етикетите не се пипат)."""
    key = str(start)[:10]
    if key not in _OPEN_GAPS:
        _OPEN_GAPS[key] = open_gaps((fetch or fetch_daily)(key))
    return _OPEN_GAPS[key]


# не са собствена новина за гапа: общ преглед, списък с няколко акции, „защо се движи“ / „в фокус“ (обяснение на хода, не причина)
_NOT_OWN = re.compile(r"\b(\d+ (?:AI |tech |chip |growth |dividend )?stocks?|stocks? to (?:buy|watch)|what (?:moved|sent|is moving)|what does .{0,80}\bmean|can .{0,40}\bconvert|why .{0,40}\b(?:stock|shares)\b|"
                      r"shares? (?:are |is )?in focus|stock looks|worst week|best week|rally after sell-off|sell-off|on the dip)\b", re.I)
_TICKERS_LIST = re.compile(r"^(?:[A-Z]{2,5}, ){2,}")


def own_news(row: dict) -> bool:
    """
    EP ред (сутрешен — "headlines"; карето — "headline") → има ли собствена новина: 8-K след затварянето или заглавие за компанията (тикърът / дума от името ≥ 4 букви), което
    не е общ преглед на пазара (qm_ep.OVERVIEW_RE), списък с няколко акции („CRWV, IREN, NBIS Rally …“) или обяснение на хода („What Moved …“, „5 AI Tech Stocks …“). Чиста функция.
    """
    from src import qm_ep
    if row.get("filings_8k"):
        return True
    t, company = row.get("ticker") or "", row.get("company") or ""
    words = [w for w in re.findall(r"[A-Za-z]{4,}", company) if w.lower() not in ("inc", "corp", "corporation", "company", "holdings", "group", "technologies", "computer", "energy")]
    hs = [h for h in (row.get("headlines") or ([row["headline"]] if row.get("headline") else [])) if isinstance(h, dict) and h.get("source") != "SEC"]
    for h in hs:
        title = h.get("title") or ""
        if qm_ep.OVERVIEW_RE.search(title) or _NOT_OWN.search(title) or _TICKERS_LIST.search(title):
            continue
        if (t and re.search(rf"\b{re.escape(t)}\b", title)) or any(re.search(rf"\b{re.escape(w)}\b", title, re.I) for w in words):
            return True
    return False


def mark_rows(rows: list[dict] | None, mg: dict | None) -> int:
    """В ден на пазарен гап — row["market_move"] = True на гаповете без собствена новина; → броят. Мутира. Не е ден на гап → 0 (нищо не се пипа)."""
    if not (mg and mg.get("gap")):
        return 0
    n = 0
    for r in rows or []:
        if not own_news(r):
            r["market_move"] = True
            n += 1
    return n
