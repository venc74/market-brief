"""
Слой 2: Секторна логика и ротация.
RS Line на всеки секторен ETF спрямо SPY — кои сектори печелят
относителна сила в последните 4 и 12 седмици. Верижната логика
(макро събитие → сектор) се извежда от Claude в ai_brief.py;
тук са само измеримите данни.
"""
from __future__ import annotations
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


def sector_rotation() -> list[dict]:
    etfs = {k: v for k, v in config.SECTOR_ETFS.items() if "PROXY" not in k}
    symbols = list(etfs.keys()) + ["SPY"]
    data = yf.download(symbols, period="6mo", progress=False, auto_adjust=True)["Close"]

    spy = data["SPY"]
    results = []
    for sym, name in etfs.items():
        if sym not in data.columns:
            continue
        series = data[sym].dropna()
        if len(series) < 65:
            continue
        rs = (series / spy).dropna()
        rs_now = float(rs.iloc[-1])
        rs_4w = float(rs.iloc[-21])
        rs_12w = float(rs.iloc[-63])
        rs_max_6m = float(rs.max())

        chg_4w = (rs_now / rs_4w - 1) * 100
        chg_12w = (rs_now / rs_12w - 1) * 100
        at_high = rs_now >= rs_max_6m * 0.99

        results.append({
            "etf": sym, "sector": name,
            "rs_chg_4w_pct": round(chg_4w, 2),
            "rs_chg_12w_pct": round(chg_12w, 2),
            "rs_at_6m_high": at_high,
            "abs_chg_4w_pct": round((float(series.iloc[-1]) / float(series.iloc[-21]) - 1) * 100, 2),
            "leading": chg_4w > 0 and chg_12w > 0,
        })

    results.sort(key=lambda x: x["rs_chg_4w_pct"], reverse=True)
    return results


def leading_sectors(rotation: list[dict], top_n: int = 6) -> list[dict]:
    """Секторите с положителна RS динамика — входът за скрининга (Слой 3)."""
    leaders = [s for s in rotation if s["leading"] or s["rs_at_6m_high"]]
    return leaders[:top_n] if leaders else rotation[:3]


if __name__ == "__main__":
    import json
    rot = sector_rotation()
    print(json.dumps({"rotation": rot, "leaders": leading_sectors(rot)},
                     indent=2, ensure_ascii=False))
