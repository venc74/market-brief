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
from src import net_utils
from src import setup_rules

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
    Прилага: Weinstein Stage 2 + Minervini trend template (+ RS rating ≥ 70 във втория
    проход), RS Line близо до връх, цена ≥ $10,
    наличие на консолидация (proxy за база), близост до pivot (най-много 5% под;
    над pivot — вкл. extended — се пази, класифицира се в setup_rules).
    """
    spy = yf.download("SPY", period="2y", progress=False, auto_adjust=True)["Close"]
    if isinstance(spy, pd.DataFrame):
        spy = spy.iloc[:, 0]

    survivors = []
    rs_scores: dict[str, float] = {}          # ВСИЧКИ тикъри с история — основата на RS перцентила
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
                score = rs_score(df["Close"])
                if score is not None:
                    rs_scores[sym] = score
                row = _evaluate_technicals(sym, df, spy)
                if row:
                    row["rs_score"] = None if score is None else round(score, 4)
                    survivors.append(row)
            except Exception:
                continue
        time.sleep(1)  # не дразним Yahoo

    before = len(survivors)
    survivors = apply_rs_rating(survivors, rs_scores)          # т.9: втори проход — RS перцентил в универса
    print(f"[screener] технически филтър: {before} оцелели, {len(survivors)} с RS rating "
          f">= {config.RS_RATING_MIN:g} ({len(rs_scores)} тикъра в универса за перцентила)")
    return survivors


def trend_template_checks(price: float, ma50: float, ma150: float, ma200: float, *,
                          ma150_prev: float, ma200_prev: float,
                          high52: float, low52: float) -> dict[str, bool]:
    """
    Пакет 1, т.9 (2026-10-03): Weinstein Stage 2 + Minervini trend template — чиста функция
    върху числа. Първите две проверки са старата Stage 2 (цена над покачваща се 30-седмична
    MA); останалите са критериите на Минервини. RS rating-ът (т.8 на шаблона) не е тук —
    изисква целия универс, виж apply_rs_rating().
    """
    return {
        "stage2_price_above_ma150": price > ma150,
        "stage2_ma150_rising": ma150 > ma150_prev,
        "price_above_ma200": price > ma200,
        "ma150_above_ma200": ma150 > ma200,
        "ma200_rising": ma200 > ma200_prev,
        "ma50_above_ma150_ma200": ma50 > ma150 and ma50 > ma200,
        "price_above_ma50": price > ma50,
        "above_52w_low": price >= low52 * (1 + config.TT_MIN_ABOVE_52W_LOW_PCT / 100),
        "near_52w_high": price >= high52 * (1 - config.TT_MAX_BELOW_52W_HIGH_PCT / 100),
    }


def rs_score(close: pd.Series) -> float | None:
    """
    Претеглена 12-месечна доходност: 40% последното тримесечие + по 20% за всяко от трите
    преди него (тримесечие = config.RS_QUARTER_BARS сесии). None при недостатъчна история
    или невалидни цени.
    """
    q = config.RS_QUARTER_BARS
    if close is None or len(close) < 4 * q + 1:
        return None
    c = close.to_numpy(dtype=float)
    pts = [c[-1 - k * q] for k in range(5)]
    if any(x != x or x <= 0 for x in pts):
        return None
    rets = [pts[i] / pts[i + 1] - 1 for i in range(4)]
    return float(sum(w * r for w, r in zip(config.RS_RATING_WEIGHTS, rets)))


def rs_ratings(scores: dict[str, float]) -> dict[str, int]:
    """
    Перцентил (1–100) на rs_score в целия универс: ранг × 100 / N, закръглен НАДОЛУ (рейтинг
    70 = поне 70% от универса са на или под този тикър), със средния ранг при равни
    стойности. Целочислена аритметика — граничните стойности не зависят от float шум.
    """
    s = pd.Series(scores, dtype=float).dropna()
    if s.empty:
        return {}
    n = len(s)
    return {k: max(1, int(v * 100 / n + 1e-9)) for k, v in s.rank(method="average").items()}


def apply_rs_rating(rows: list[dict], scores: dict[str, float]) -> list[dict]:
    """
    Слага row["rs_rating"] (перцентил в универса) и — при TREND_TEMPLATE_ENABLED — маха
    редовете под RS_RATING_MIN. Универс под RS_RATING_MIN_UNIVERSE тикъра с данни →
    рейтингът не е надежден: не се смята, филтърът се пропуска, предупреждение в лога.
    """
    if len(scores) < config.RS_RATING_MIN_UNIVERSE:
        print(f"[screener] ⚠ RS rating: само {len(scores)} тикъра с история "
              f"(< {config.RS_RATING_MIN_UNIVERSE}) — рейтингът не е надежден, филтърът е пропуснат")
        for r in rows:
            r["rs_rating"] = None
        return rows
    ratings = rs_ratings(scores)
    out = []
    for r in rows:
        r["rs_rating"] = ratings.get(r["ticker"])
        if config.TREND_TEMPLATE_ENABLED and (r["rs_rating"] is None or r["rs_rating"] < config.RS_RATING_MIN):
            continue
        out.append(r)
    return out


def compute_pivot(high: pd.Series) -> float:
    """
    FIX 2026-10-02 (пакет 1, т.1): pivot = най-високият High на базата БЕЗ
    последните config.PIVOT_EXCLUDE_LAST_BARS бара. Преди беше max(High[-65:]) —
    включваше сигналния бар, затова close <= pivot винаги и "пробив" не съществуваше.
    Базата е PIVOT_BASE_BARS бара, завършващи на сигналния бар; последните N се
    изключват (N=0 връща старото поведение).
    """
    n = config.PIVOT_EXCLUDE_LAST_BARS
    window = high.iloc[-config.PIVOT_BASE_BARS:(-n if n else None)]
    return float(window.max())


def _evaluate_technicals(sym: str, df: pd.DataFrame, spy: pd.Series) -> dict | None:
    if len(df) < 260:
        return None
    close, volume, high = df["Close"], df["Volume"], df["High"]
    price = float(close.iloc[-1])

    if price < config.MIN_PRICE:
        return None

    # ── Weinstein Stage 2 + Minervini trend template (пакет 1, т.9) ──────
    # Една обща проверка: Stage 2 (цена над покачваща се 30-седмична MA = 150 сесии) е
    # първата част на шаблона, не отделен филтър; шаблонът добавя 200DMA, 50DMA и
    # позицията в 52-седмичния диапазон. RS rating (перцентил в целия универс) се
    # прилага след първия проход — виж technical_screen / apply_rs_rating.
    ma150 = close.rolling(config.WEINSTEIN_MA_WEEKS * 5).mean()
    ma50_s = close.rolling(50).mean()
    ma200_s = close.rolling(200).mean()
    low52 = float(df["Low"].iloc[-252:].min())
    high52 = float(high.iloc[-252:].max())
    tt = trend_template_checks(
        price, float(ma50_s.iloc[-1]), float(ma150.iloc[-1]), float(ma200_s.iloc[-1]),
        ma150_prev=float(ma150.iloc[-21]),
        ma200_prev=float(ma200_s.iloc[-1 - config.TT_MA200_RISING_BARS]),
        high52=high52, low52=low52)
    required = list(tt) if config.TREND_TEMPLATE_ENABLED else [
        "stage2_price_above_ma150", "stage2_ma150_rising"]      # изключен шаблон = само старата Stage 2
    if not all(tt[k] for k in required):
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

    # ── База: pivot = най-високият High на базата БЕЗ последните N бара ──
    # pct_from_pivot вече може да е ПОЛОЖИТЕЛЕН (пробив). Над +BUYABLE_ZONE_MAX_PCT
    # ("extended") кандидатът НЕ се отхвърля — остава за Watchlist ("не гони"),
    # сортиран най-отзад (виж run_screen). Под pivot — най-много MAX_PCT_BELOW_PIVOT.
    pivot = compute_pivot(high)
    pct_from_pivot = (price / pivot - 1) * 100      # <0 = под pivot, >0 = над (пробив)
    if pct_from_pivot < -config.MAX_PCT_BELOW_PIVOT:   # твърде дълбоко под
        return None

    # ── Дълбочина на базата: проста класификация на формацията ──────────
    # спрямо ПЪЛНИЯ 13-седмичен връх (включва последните бара), като досега —
    # филтърът за качество на базата не е част от промяната на pivot-а
    base_high = float(high.iloc[-config.PIVOT_BASE_BARS:].max())
    base_low = float(close.iloc[-config.PIVOT_BASE_BARS:].min())
    depth = (base_high - base_low) / base_high * 100
    if depth > 35:                                      # счупена структура
        return None
    # 2026-10-03 (пакет 4а т.6): кодът мери САМО дълбочина (връх − най-ниско затваряне за 13 седмици),
    # не разпознава форма — затова етикетът е честното "база X% дълбочина", не "cup with handle"/
    # "flat base" (прагове 15/30 нямаха връзка с реалната формация).
    base_type = f"база {depth:.1f}% дълбочина"

    # ── Обем ─────────────────────────────────────────────────────────────
    avg_vol_50 = float(volume.iloc[-50:].mean())
    last_vol = float(volume.iloc[-1])
    vol_ratio = last_vol / avg_vol_50 if avg_vol_50 else 0
    breakout_volume = vol_ratio >= config.BREAKOUT_VOLUME_MULT

    ma50 = float(ma50_s.iloc[-1])
    ma200 = float(ma200_s.iloc[-1])

    # FIX 2026-10-03 (пакет 1, т.3): структурен low = най-ниският Low на последните
    # STOP_STRUCT_LOOKBACK_BARS бара (сигналният бар е включен) — основата на стопа
    # в sizing.position_plan_v2 и на проверката "твърде разтегнато" в setup_rules.
    struct_low = float(df["Low"].iloc[-config.STOP_STRUCT_LOOKBACK_BARS:].min())

    return {
        "ticker": sym, "price": round(price, 2), "pivot": round(pivot, 2),
        "pct_from_pivot": round(pct_from_pivot, 2),
        "pivot_bars_excluded": config.PIVOT_EXCLUDE_LAST_BARS,
        "base_type": base_type, "base_depth_pct": round(depth, 1),
        "weinstein_stage": 2,
        "rs_status": rs_status,
        "ma50": round(ma50, 2), "ma200": round(ma200, 2),
        "above_ma50": price > ma50, "above_ma200": price > ma200,
        "avg_volume_50d": int(avg_vol_50), "last_volume": int(last_vol),
        "volume_ratio": round(vol_ratio, 2), "breakout_volume": breakout_volume,
        "base_low": round(base_low, 2),
        "struct_low": round(struct_low, 2),
        # т.9: позицията в 52-седмичния диапазон (за показване); rs_score/rs_rating се слагат
        # във втория проход на technical_screen
        "pct_above_52w_low": round((price / low52 - 1) * 100, 1),
        "pct_below_52w_high": round((1 - price / high52) * 100, 1),
        "trend_template_applied": config.TREND_TEMPLATE_ENABLED,
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
            info = net_utils.fetch_with_timeout(lambda: tk.info) or {}

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

    # сортиране: потвърдени пробиви → над pivot без обем → под pivot (най-близките) →
    # extended (виж setup_rules.screen_priority); fundamental_screen гледа първите 60
    tech.sort(key=setup_rules.screen_priority)
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
