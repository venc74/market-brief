"""
Слой 3: Скрининг на акции.
Двустепенен процес заради rate limits:
  1. Технически филтър върху целия универс (batch download, евтино)
  2. Фундаментален CANSLIM филтър само върху оцелелите (Ticker.info, скъпо)

Универс: S&P 500 + Nasdaq-100 + S&P MidCap 400 (Wikipedia списъци),
филтрирани по цена ≥ $10 и mcap ≥ $500M (Секция 8).
"""
from __future__ import annotations
import io
import time
import requests
import pandas as pd
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


# ──────────────────────────────────────────────────────────────────────────
# Универс
# ──────────────────────────────────────────────────────────────────────────
def _wiki_tickers(url: str, column: str) -> list[str]:
    try:
        html = requests.get(url, timeout=30, headers=UA).text
        tables = pd.read_html(io.StringIO(html))
        for t in tables:
            if column in t.columns:
                return [str(s).replace(".", "-").strip() for s in t[column].tolist()]
    except Exception as e:
        print(f"[screener] universe fetch failed {url}: {e}")
    return []


def build_universe() -> list[str]:
    sp500 = _wiki_tickers(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol")
    ndx = _wiki_tickers(
        "https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker")
    mid400 = _wiki_tickers(
        "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "Symbol")
    universe = sorted(set(sp500) | set(ndx) | set(mid400))
    print(f"[screener] универс: {len(universe)} тикъра")
    return universe


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 1: Технически филтър (върху целия универс)
# ──────────────────────────────────────────────────────────────────────────
def technical_screen(universe: list[str], batch_size: int = 100) -> list[dict]:
    """
    Прилага: Weinstein Stage 2, RS Line близо до връх, цена ≥ $10,
    наличие на консолидация (proxy за база), близост до pivot.
    """
    spy = yf.download("SPY", period="2y", progress=False, auto_adjust=True)["Close"]
    if isinstance(spy, pd.DataFrame):
        spy = spy.iloc[:, 0]

    survivors = []
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i + batch_size]
        try:
            data = yf.download(batch, period="2y", progress=False,
                               auto_adjust=True, group_by="ticker", threads=True)
        except Exception as e:
            print(f"[screener] batch {i} failed: {e}")
            continue

        for sym in batch:
            try:
                df = data[sym].dropna() if len(batch) > 1 else data.dropna()
                row = _evaluate_technicals(sym, df, spy)
                if row:
                    survivors.append(row)
            except Exception:
                continue
        time.sleep(1)  # не дразним Yahoo

    print(f"[screener] технически филтър: {len(survivors)} оцелели")
    return survivors


def _evaluate_technicals(sym: str, df: pd.DataFrame, spy: pd.Series) -> dict | None:
    if len(df) < 260:
        return None
    close, volume, high = df["Close"], df["Volume"], df["High"]
    price = float(close.iloc[-1])

    if price < config.MIN_PRICE:
        return None

    # ── Weinstein Stage 2: цена над покачваща се 30-седмична MA ──────────
    ma30w = close.rolling(config.WEINSTEIN_MA_WEEKS * 5).mean()
    ma30w_now, ma30w_prev = float(ma30w.iloc[-1]), float(ma30w.iloc[-21])
    if not (price > ma30w_now and ma30w_now > ma30w_prev):
        return None

    # ── RS Line: на или близо до 52-седмичен максимум (рамките 3%) ───────
    aligned_spy = spy.reindex(close.index).ffill()
    rs = (close / aligned_spy).dropna()
    rs_52w = rs.iloc[-252:]
    rs_now, rs_max = float(rs_52w.iloc[-1]), float(rs_52w.max())
    rs_status = ("new_high" if rs_now >= rs_max * 0.999
                 else "near_high" if rs_now >= rs_max * 0.97
                 else "lagging")
    if rs_status == "lagging":
        return None

    # ── База: pivot = 13-седмичен максимум; не extended, не >5% под ─────
    pivot = float(high.iloc[-65:].max())
    pct_from_pivot = (price / pivot - 1) * 100      # отрицателно = под pivot
    if pct_from_pivot < -config.MAX_PCT_BELOW_PIVOT:   # твърде дълбоко под
        return None
    if pct_from_pivot > 5.0:                            # extended над pivot
        return None

    # ── Дълбочина на базата: проста класификация на формацията ──────────
    base_low = float(close.iloc[-65:].min())
    depth = (pivot - base_low) / pivot * 100
    if depth > 35:                                      # счупена структура
        return None
    base_type = ("flat base" if depth <= 15
                 else "cup with handle" if depth <= 30
                 else "deep base")

    # ── Обем ─────────────────────────────────────────────────────────────
    avg_vol_50 = float(volume.iloc[-50:].mean())
    last_vol = float(volume.iloc[-1])
    vol_ratio = last_vol / avg_vol_50 if avg_vol_50 else 0
    breakout_volume = vol_ratio >= config.BREAKOUT_VOLUME_MULT

    ma50 = float(close.rolling(50).mean().iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])

    return {
        "ticker": sym, "price": round(price, 2), "pivot": round(pivot, 2),
        "pct_from_pivot": round(pct_from_pivot, 2),
        "base_type": base_type, "base_depth_pct": round(depth, 1),
        "weinstein_stage": 2,
        "rs_status": rs_status,
        "ma50": round(ma50, 2), "ma200": round(ma200, 2),
        "above_ma50": price > ma50, "above_ma200": price > ma200,
        "avg_volume_50d": int(avg_vol_50), "last_volume": int(last_vol),
        "volume_ratio": round(vol_ratio, 2), "breakout_volume": breakout_volume,
        "base_low": round(base_low, 2),
    }


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 2: Фундаментален CANSLIM филтър (само върху оцелелите)
# ──────────────────────────────────────────────────────────────────────────
def fundamental_screen(candidates: list[dict], max_checks: int = 60) -> list[dict]:
    passed = []
    for row in candidates[:max_checks]:
        sym = row["ticker"]
        try:
            tk = yf.Ticker(sym)
            info = tk.info or {}

            mcap = info.get("marketCap") or 0
            if mcap < config.MIN_MARKET_CAP:
                continue

            eps_g = (info.get("earningsQuarterlyGrowth") or 0) * 100
            rev_g = (info.get("revenueGrowth") or 0) * 100
            roe = (info.get("returnOnEquity") or 0) * 100

            # Минимум 2 от 3 CANSLIM критерия + нито един дълбоко негативен.
            # info полетата на Yahoo са непълни — твърд AND би убил всичко.
            checks = [eps_g >= config.MIN_EPS_GROWTH_YOY,
                      rev_g >= config.MIN_REVENUE_GROWTH_YOY,
                      roe >= config.MIN_ROE]
            if sum(checks) < 2 or eps_g < 0:
                continue

            row.update({
                "company": info.get("longName") or sym,
                "sector": info.get("sector") or "Unknown",
                "industry": info.get("industry") or "",
                "business_summary": (info.get("longBusinessSummary") or "")[:600],
                "market_cap": mcap,
                "eps_growth_yoy": round(eps_g, 1),
                "revenue_growth_yoy": round(rev_g, 1),
                "roe": round(roe, 1),
                "pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "debt_to_equity": info.get("debtToEquity"),
                "inst_ownership_pct": round((info.get("heldPercentInstitutions") or 0) * 100, 1),
                "analyst_target": info.get("targetMeanPrice"),
                # short interest данни (Секция 3.5) — директно от info
                "short_pct_float": round((info.get("shortPercentOfFloat") or 0) * 100, 2),
                "shares_short": info.get("sharesShort"),
                "short_ratio_dtc": info.get("shortRatio"),   # days to cover
            })
            passed.append(row)
            time.sleep(0.5)
        except Exception as e:
            print(f"[screener] fundamentals {sym} failed: {e}")
            continue

    print(f"[screener] CANSLIM филтър: {len(passed)} финалисти")
    return passed


def run_screen(leading_sector_names: list[str] | None = None) -> list[dict]:
    """
    Пълният Слой 3. Ако са подадени водещи сектори от Слой 2,
    кандидатите от тях се приоритизират (макро съответствие),
    но не се изключват силни setup-и извън тях — те отиват към Watchlist.
    """
    universe = build_universe()
    tech = technical_screen(universe)

    # сортиране: близост до pivot + обем сигнал
    tech.sort(key=lambda r: (not r["breakout_volume"], abs(r["pct_from_pivot"])))
    finalists = fundamental_screen(tech)

    if leading_sector_names:
        keys = [s.lower() for s in leading_sector_names]
        for f in finalists:
            f["macro_tailwind"] = any(k in (f.get("sector", "") + f.get("industry", "")).lower()
                                      or (f.get("sector", "").lower() in k) for k in keys)
        finalists.sort(key=lambda r: not r.get("macro_tailwind", False))
    return finalists


if __name__ == "__main__":
    import json
    res = run_screen()
    print(json.dumps(res[:10], indent=2, ensure_ascii=False, default=str))
