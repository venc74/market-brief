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

# Състоянието на последния technical_screen(): {"ok", "kind" (ok/partial/spy_failed/no_history/universe_empty), "reason",
# "universe", "with_history", "batches", "batches_failed"} — main.py го превръща в предупреждение в брифа.
LAST_STATUS: dict = {}


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
LAST_RS_SCORES: dict[str, float] = {}      # rs_score на всички тикъри с история в последния technical_screen

# Праговете на RS линията в _evaluate_technicals ("new_high" ≥ 99.9% от 52-седмичния максимум, "near_high" ≥ 97%, иначе "lagging" → кандидатът отпада). Същите стойности ползва
# explain_exclusion; test_buystop_book_state.py сверява двете върху реални данни, за да не се разминат.
RS_LINE_NEW_HIGH, RS_LINE_NEAR_HIGH = 0.999, 0.97

_TT_TEXT = {
    "stage2_price_above_ma150": "цената е под 30-седмичната MA",
    "stage2_ma150_rising": "30-седмичната MA не расте",
    "price_above_ma200": "цената е под 200DMA",
    "ma150_above_ma200": "150DMA не е над 200DMA",
    "ma200_rising": "200DMA не расте",
    "ma50_above_ma150_ma200": "50DMA не е над 150/200DMA",
    "price_above_ma50": "цената е под 50DMA",
    "above_52w_low": f"цената не е поне {config.TT_MIN_ABOVE_52W_LOW_PCT:g}% над 52-седмичния минимум",
    "near_52w_high": f"цената е повече от {config.TT_MAX_BELOW_52W_HIGH_PCT:g}% под 52-седмичния максимум",
}


def explain_exclusion(sym: str, df: pd.DataFrame, spy: pd.Series, rs_scores: dict[str, float] | None = None) -> str | None:
    """
    Защо тикърът НЕ е в днешния технически списък — първият филтър от _evaluate_technicals (в същия ред), с числата. None = технически филтри преминати (отпадането е по-късно: RS rating,
    CANSLIM фундаментите или лимитът). Само обяснение за показване (книгата показва "излезе от скрийнъра: …" до реда на жив запис); не решава нищо и не вика мрежа. Пакет 1б, 07.10: EXPD,
    изпълнен на 05.10, изчезна на 07.10 без следа — RS линията падна от 97.6% на 95.9% от максимума (праг 97%).
    """
    try:
        if df is None or len(df) < 260:
            return f"по-малко от 260 дневни бара история ({0 if df is None else len(df)})"
        close, high = df["Close"], df["High"]
        price = float(close.iloc[-1])
        if price < config.MIN_PRICE:
            return f"цена ${price:.2f} под минимума ${config.MIN_PRICE:g}"
        ma150 = close.rolling(config.WEINSTEIN_MA_WEEKS * 5).mean(); ma50 = close.rolling(50).mean(); ma200 = close.rolling(200).mean()
        tt = trend_template_checks(price, float(ma50.iloc[-1]), float(ma150.iloc[-1]), float(ma200.iloc[-1]),
                                   ma150_prev=float(ma150.iloc[-21]), ma200_prev=float(ma200.iloc[-1 - config.TT_MA200_RISING_BARS]),
                                   high52=float(high.iloc[-252:].max()), low52=float(df["Low"].iloc[-252:].min()))
        required = list(tt) if config.TREND_TEMPLATE_ENABLED else ["stage2_price_above_ma150", "stage2_ma150_rising"]
        failed = [k for k in required if not tt[k]]
        if failed:
            return "trend template: " + "; ".join(_TT_TEXT[k] for k in failed)
        rs = (close / spy.reindex(close.index).ffill()).dropna().iloc[-252:]
        now, top = float(rs.iloc[-1]), float(rs.max())
        if now < top * RS_LINE_NEAR_HIGH:
            return f"RS линия {now / top * 100:.1f}% от 52-седмичния максимум < {RS_LINE_NEAR_HIGH * 100:.0f}%"
        pivot = compute_pivot(high)
        pct = (price / pivot - 1) * 100
        if pct < -config.MAX_PCT_BELOW_PIVOT:
            return f"цената е {abs(pct):.1f}% под pivot ${pivot:.2f} (над допустимите {config.MAX_PCT_BELOW_PIVOT:g}%)"
        base_high = float(high.iloc[-config.PIVOT_BASE_BARS:].max()); base_low = float(close.iloc[-config.PIVOT_BASE_BARS:].min())
        depth = (base_high - base_low) / base_high * 100
        if depth > 35:
            return f"база с дълбочина {depth:.1f}% (над 35%)"
        if rs_scores and config.TREND_TEMPLATE_ENABLED and len(rs_scores) >= config.RS_RATING_MIN_UNIVERSE:
            own = rs_score(close)
            if own is not None:
                rating = rs_ratings({**rs_scores, sym: own}).get(sym)
                if rating is not None and rating < config.RS_RATING_MIN:
                    return f"RS rating {rating} < {config.RS_RATING_MIN:g}"
        return None
    except Exception as e:
        return f"не може да се обясни ({type(e).__name__})"


def _frame_for(data: pd.DataFrame, sym: str, n_tickers: int) -> pd.DataFrame:
    """Колоните на ЕДИН тикър от резултата на yf.download — при няколко тикъра (тикър, поле); при един yfinance връща ту (тикър, поле), ту плоски колони (зависи от версията)."""
    if isinstance(data.columns, pd.MultiIndex):
        if sym in data.columns.get_level_values(0):
            return data[sym]
        if sym in data.columns.get_level_values(1):
            return data.xs(sym, axis=1, level=1)
        raise KeyError(sym)
    if n_tickers == 1:
        return data
    raise KeyError(sym)


def explain_exits(tickers: list[str]) -> dict[str, str]:
    """
    {тикър: причина} за тикъри с жив запис в книгата, които ги няма в днешния списък: един SPY + една партида от Yahoo. Технически филтри преминати → отпадане по-късно
    (CANSLIM фундаменти/лимит); без данни → "няма ценови данни". Graceful: провал на тегленето → {}.
    """
    out: dict[str, str] = {}
    if not tickers:
        return out
    try:
        spy = yf.download("SPY", period="2y", progress=False, auto_adjust=True)["Close"]
        if isinstance(spy, pd.DataFrame):
            spy = spy.iloc[:, 0]
        spy = spy.dropna()
        data = yf.download(list(tickers), period="2y", progress=False, auto_adjust=True, group_by="ticker", threads=True)
        for sym in tickers:
            try:
                df = _frame_for(data, sym, len(tickers)).dropna()
            except Exception:
                df = None
            if df is None or not len(df):
                out[sym] = "няма ценови данни"
                continue
            out[sym] = explain_exclusion(sym, df, spy, LAST_RS_SCORES) or "техническите филтри са преминати — отпаднал по-късно (CANSLIM фундаментите или лимитът на финалистите)"
    except Exception as e:
        print(f"[screener] причините за излизане от списъка не се смятаха: {type(e).__name__}: {e}")
    return out


def technical_screen(universe: list[str], batch_size: int = 100) -> list[dict]:
    """
    Прилага: Weinstein Stage 2 + Minervini trend template (+ RS rating ≥ 70 във втория
    проход), RS Line близо до връх, цена ≥ $10,
    наличие на консолидация (proxy за база), близост до pivot (най-много 5% под;
    над pivot — вкл. extended — се пази, класифицира се в setup_rules).
    """
    # FIX 2026-10-03 (пакет 2 т.6): паднал Yahoo не сваля run-а. Празният yf.download("SPY") даваше KeyError на
    # ["Close"] още на първия ред; сега → [] + причина в LAST_STATUS (main.py я показва в брифа като предупреждение,
    # за да не се чете празният списък като "днес няма сетъпи"). Провалените партиди се броят (batches_failed).
    LAST_STATUS.clear()
    LAST_STATUS.update(ok=False, kind="", reason="", universe=len(universe), with_history=0,
                       batches=0, batches_failed=0)
    try:
        spy = yf.download("SPY", period="2y", progress=False, auto_adjust=True)["Close"]
        if isinstance(spy, pd.DataFrame):
            spy = spy.iloc[:, 0]
        spy = spy.dropna()
        if len(spy) == 0:
            raise ValueError("Yahoo върна празна история за SPY")
    except Exception as e:
        LAST_STATUS.update(kind="spy_failed", reason=f"{type(e).__name__}: {e}")
        print(f"[screener] ⚠ няма SPY история — технически филтър пропуснат ({LAST_STATUS['reason']})")
        return []

    survivors = []
    rs_scores: dict[str, float] = {}          # ВСИЧКИ тикъри с история — основата на RS перцентила
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i + batch_size]
        LAST_STATUS["batches"] += 1
        try:
            data = yf.download(batch, period="2y", progress=False,
                               auto_adjust=True, group_by="ticker", threads=True)
        except Exception as e:
            LAST_STATUS["batches_failed"] += 1
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

    LAST_STATUS["with_history"] = len(rs_scores)
    LAST_RS_SCORES.clear(); LAST_RS_SCORES.update(rs_scores)           # за explain_exclusion: перцентилът на RS rating е спрямо СЪЩИЯ универс на този run
    if universe and not rs_scores:
        LAST_STATUS.update(kind="no_history", reason="нито един тикър от универса не върна ценова история")
        print(f"[screener] ⚠ {LAST_STATUS['reason']} ({LAST_STATUS['batches_failed']} от {LAST_STATUS['batches']} партиди с грешка)")
    elif not universe:
        LAST_STATUS.update(kind="universe_empty", reason="списъкът с тикъри (Wikipedia) е празен")
    else:
        LAST_STATUS.update(ok=True, kind="partial" if LAST_STATUS["batches_failed"] else "ok")
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


def run_screen(leading_sector_names: list[str] | None = None, leaders: list[dict] | None = None) -> list[dict]:
    """
    Пълният Слой 3. Ако са подадени водещи сектори от Слой 2,
    кандидатите от тях се приоритизират (макро съответствие),
    но не се изключват силни setup-и извън тях — те отиват към Watchlist.

    FIX 2026-10-03 (пакет 2 т.1): macro_tailwind се смята през ETF → Yahoo сектор/индустрия
    (config.SECTOR_ETF_YAHOO, sector_layer.tailwind_leaders), а не със сравнение на български имена с
    английски Yahoo полета (беше False за всичките 645 карти). Резултатът е САМО подредба и маркер SECT✓
    върху картата — никога филтър. `leaders` = редовете от leading_sectors(); при подадени само имена
    те се превръщат обратно в ETF-и през config.SECTOR_ETFS.
    """
    universe = build_universe()
    tech = technical_screen(universe)

    # сортиране: потвърдени пробиви → над pivot без обем → под pivot (най-близките) →
    # extended (виж setup_rules.screen_priority); fundamental_screen гледа първите 60
    tech.sort(key=setup_rules.screen_priority)
    finalists = fundamental_screen(tech)
    return apply_sector_tailwind(finalists, leaders, leading_sector_names)


def apply_sector_tailwind(finalists: list[dict], leaders: list[dict] | None = None,
                          leading_sector_names: list[str] | None = None) -> list[dict]:
    """macro_tailwind/tailwind_etfs + маркер SECT✓ + стабилна подредба (tailwind първи). Не маха кандидати."""
    from src import sector_layer
    if not leaders and leading_sector_names:
        inverse = {v: k for k, v in config.SECTOR_ETFS.items()}
        leaders = [{"etf": inverse[n], "sector": n} for n in leading_sector_names if n in inverse]
    if not leaders:
        return finalists
    for f in finalists:
        matched = sector_layer.tailwind_leaders(f, leaders)
        f["macro_tailwind"] = bool(matched)
        f["tailwind_etfs"] = [m["etf"] for m in matched]
        marker = sector_layer.tailwind_marker(matched)
        if marker:
            f.setdefault("markers", []).append(marker)
    finalists.sort(key=lambda r: not r.get("macro_tailwind", False))
    return finalists


if __name__ == "__main__":
    import json
    res = run_screen()
    print(json.dumps(res[:10], indent=2, ensure_ascii=False, default=str))
