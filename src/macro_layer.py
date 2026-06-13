"""
Слой 1: Глобален макро контекст.
Събира сурови данни от FRED, NewsAPI и yfinance. Синтезът на естествен
език се прави по-късно от ai_brief.py — този модул връща само факти.
"""
from __future__ import annotations
import datetime as dt
import requests
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def _fred_series(series_id: str, days: int = 90) -> list[tuple[str, float]]:
    """Връща (дата, стойност) наблюдения от FRED за последните N дни."""
    if not config.FRED_API_KEY:
        return []
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    try:
        r = requests.get(FRED_BASE, params={
            "series_id": series_id, "api_key": config.FRED_API_KEY,
            "file_type": "json", "observation_start": start,
        }, timeout=20)
        r.raise_for_status()
        out = []
        for obs in r.json().get("observations", []):
            if obs["value"] not in (".", ""):
                out.append((obs["date"], float(obs["value"])))
        return out
    except Exception as e:
        print(f"[macro] FRED {series_id} failed: {e}")
        return []


def fed_net_liquidity() -> dict:
    """
    Net Liquidity = Fed Balance Sheet (WALCL) − Reverse Repo (RRPONTSYD)
                    − Treasury General Account (WTREGEN). В млрд USD.
    """
    walcl = _fred_series("WALCL")        # millions, weekly
    rrp = _fred_series("RRPONTSYD")      # billions, daily
    tga = _fred_series("WTREGEN")        # billions, weekly

    if not (walcl and rrp and tga):
        return {"value": None, "trend": "unknown", "history": []}

    def latest(series): return series[-1][1]
    def prior(series): return series[-5][1] if len(series) >= 5 else series[0][1]

    nl_now = latest(walcl) / 1000 - latest(rrp) - latest(tga)
    nl_prev = prior(walcl) / 1000 - prior(rrp) - prior(tga)
    return {
        "value": round(nl_now, 1),
        "prev": round(nl_prev, 1),
        "trend": "up" if nl_now > nl_prev else "down",
        "components": {
            "fed_balance_bn": round(latest(walcl) / 1000, 1),
            "rrp_bn": round(latest(rrp), 1),
            "tga_bn": round(latest(tga), 1),
        },
    }


def treasury_spread_2s10s() -> dict:
    """T10Y2Y от FRED — директно спредът в %."""
    obs = _fred_series("T10Y2Y", days=30)
    if not obs:
        return {"value": None, "status": "unknown"}
    val = obs[-1][1]
    prev = obs[-6][1] if len(obs) >= 6 else obs[0][1]
    return {
        "value": val,
        "prev_week": prev,
        "status": "inverted" if val < 0 else "normal",
        "direction": "steepening" if val > prev else "flattening",
    }


def global_market_signals() -> dict:
    """DXY, VIX, gold, oil, copper, 10Y yield — снимка + 5-дневна промяна."""
    tickers = {
        "DXY": "DX-Y.NYB", "VIX": "^VIX", "Gold": "GC=F",
        "Oil_WTI": "CL=F", "Copper": "HG=F", "US10Y": "^TNX",
    }
    out = {}
    for name, symbol in tickers.items():
        try:
            hist = yf.Ticker(symbol).history(period="10d")
            if len(hist) >= 2:
                last = float(hist["Close"].iloc[-1])
                wk = float(hist["Close"].iloc[0])
                out[name] = {
                    "value": round(last, 2),
                    "chg_5d_pct": round((last / wk - 1) * 100, 2),
                }
        except Exception as e:
            print(f"[macro] {name} failed: {e}")
    return out


def recent_headlines(max_items: int = 25) -> list[dict]:
    """
    Новини от последните 24ч в категориите от спека: монетарна политика,
    геополитика, макро данни. NewsAPI free tier — ако ключ липсва, празно.
    """
    if not config.NEWS_API_KEY:
        return []
    query = ("Federal Reserve OR FOMC OR inflation OR CPI OR tariffs OR sanctions "
             "OR OPEC OR \"interest rates\" OR geopolitics OR war")
    try:
        r = requests.get("https://newsapi.org/v2/everything", params={
            "q": query, "language": "en", "sortBy": "publishedAt",
            "from": (dt.datetime.utcnow() - dt.timedelta(hours=24)).isoformat(),
            "pageSize": max_items, "apiKey": config.NEWS_API_KEY,
        }, timeout=20)
        r.raise_for_status()
        return [{
            "title": a["title"],
            "source": a["source"]["name"],
            "published": a["publishedAt"],
            "description": (a.get("description") or "")[:300],
        } for a in r.json().get("articles", [])]
    except Exception as e:
        print(f"[macro] NewsAPI failed: {e}")
        return []


def collect_macro_layer() -> dict:
    """Пълният Слой 1 пакет — подава се на AI синтеза и термометъра."""
    return {
        "date": dt.date.today().isoformat(),
        "net_liquidity": fed_net_liquidity(),
        "spread_2s10s": treasury_spread_2s10s(),
        "global_signals": global_market_signals(),
        "headlines": recent_headlines(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(collect_macro_layer(), indent=2, ensure_ascii=False))
