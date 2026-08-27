"""
Short/Stage 4 Screener — Модул 1, Short/Reversal тема. Sector-first подход:
НЕ "огледало на CANSLIM" сред качествени компании (рядко/трудно се
shortват) — вместо това (1) reuse-ва sector_layer.laggard_sectors()
(persistence-gated, потвърдена устойчива слабост, не еднодневен шум), (2)
разширява universe-а в рамките на слабия сектор (small/mid-cap, не
top-tier институционални имена — те трудно падат/трудно се shortват), (3)
прилага Stage 4 технически филтър (огледало на screener.py Stage 2), (4)
прилага survival-risk N-от-M distress филтър.

Пълен feasibility/backtest trail (2026-08-2x дискусия): coal 2014-2016
(persistence gate + Stage 4 technical mirror потвърдени directamente на
реални цени — ARLP/CNX proxy, реалните bankrupt small-caps ANR/WLT/ACI/PCX
нямат данни в yfinance, delisted твърде отдавна) + 2023-2025 smoke test
(TAN/XLRE потвърдени срещу documented real-world events, вкл. SPWR
Chapter 11 05.08.2024, хванат directamente от universe expansion-а).

СТРУКТУРЕН ЛИМИТ (не implementation пропуск, потвърдено directamente):
survival-risk метриките НЕ могат да бъдат ретроактивно тествани отвъд
~2г — yfinance quarterly fundamentals покриват само толкова назад от днес.
Валидацията ще се натрупва prospectively чрез short_tracker.py.

Graceful degradation (Секция 7): провал на universe screen/technical/
survival-risk стъпка за конкретен сектор → празен списък за него,
продължава с останалите лагиращи сектори.
"""
from __future__ import annotations
import time

import pandas as pd
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import net_utils
from src.ai_brief import _verified_company_name
from src.entry_timing import _count_distribution_days  # reuse — вече generic per-ticker, виж модул docstring-а

# ── Сектор ETF -> (yfinance GICS сектор, опционален industry substring) ───
# Широките XL* ETF-и мапват директно 1:1 към yfinance-ния 11-секторен GICS
# списък (потвърдено на живо за XLRE). Тесните "тематични" ETF-и (TAN/GDX/
# URA/SMH/XBI/ITA) нямат собствен GICS сектор — нужен е втори, per-ticker
# industry substring филтър (потвърдено на живо ЗА TAN: sector=Technology +
# "solar" substring → SHLS/CSIQ/ARRY/JKS/SPWR, вкл. реалния SPWR bankruptcy
# case). Останалите mapping-и в таблицата по-долу са reasoned by analogy
# (GICS класификация), НЕ всичките live-verified тази сесия — spot-check
# преди пълно разчитане, ако конкретен сектор излезе като laggard.
_SECTOR_ETF_MAP: dict[str, tuple[str, str | None]] = {
    "XLK": ("Technology", None), "XLE": ("Energy", None),
    "XLF": ("Financial Services", None), "XLV": ("Healthcare", None),
    "XLI": ("Industrials", None), "XLB": ("Basic Materials", None),
    "XLY": ("Consumer Cyclical", None), "XLP": ("Consumer Defensive", None),
    "XLU": ("Utilities", None), "XLRE": ("Real Estate", None),
    "XLC": ("Communication Services", None),
    "ITA": ("Industrials", "aerospace"), "GDX": ("Basic Materials", "gold"),
    "URA": ("Energy", "uranium"), "TAN": ("Technology", "solar"),
    "SMH": ("Technology", "semiconductor"), "XBI": ("Healthcare", "biotechnology"),
}

SURVIVAL_RISK_DISCLOSURE = (
    "Survival-risk метриките (liquidity/leverage/cash burn) не могат да бъдат "
    "ретроактивно тествани — историческите fundamentals данни в yfinance "
    "покриват само ~2г назад от днес (потвърдено директно, 2026-08 одит). "
    "Валидацията ще се натрупва prospectively чрез short_tracker.py, не е "
    "доказана предварително за нито един исторически случай."
)


# ──────────────────────────────────────────────────────────────────────────
# Universe expansion
# ──────────────────────────────────────────────────────────────────────────
def short_universe(sector_etf: str) -> list[str]:
    """
    yf.EquityQuery/yf.screen() — потвърдено на живо, нулева нова dependency.
    Двустъпков филтър за тесните тематични ETF-и (industry_substr): първо
    широкия GICS sector screen (евтино, batch), после per-ticker .info
    substring проверка САМО върху survivors (скъпо, но малък набор).
    """
    mapping = _SECTOR_ETF_MAP.get(sector_etf)
    if not mapping:
        print(f"[short_screener] {sector_etf}: няма GICS sector mapping, пропускам")
        return []
    gics_sector, industry_substr = mapping

    query = yf.EquityQuery("and", [
        yf.EquityQuery("eq", ["sector", gics_sector]),
        yf.EquityQuery("lt", ["intradaymarketcap", config.SHORT_MAX_MARKET_CAP]),
        yf.EquityQuery("gt", ["intradaymarketcap", config.SHORT_MIN_MARKET_CAP]),
        yf.EquityQuery("is-in", ["exchange", *config.SHORT_ALLOWED_EXCHANGES]),
    ])
    try:
        result = yf.screen(query, size=250)
    except Exception as e:
        print(f"[short_screener] universe screen {sector_etf} failed: {e}")
        return []

    tickers = [q["symbol"] for q in result.get("quotes", []) if q.get("symbol")]
    if not industry_substr:
        return tickers

    narrowed = []
    for sym in tickers:
        try:
            info = net_utils.fetch_with_timeout(lambda s=sym: yf.Ticker(s).info) or {}
            if industry_substr in (info.get("industry") or "").lower():
                narrowed.append(sym)
        except Exception:
            continue
    return narrowed


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 1: Технически филтър (Stage 4 mirror, огледало на screener.py)
# ──────────────────────────────────────────────────────────────────────────
def technical_screen_short(universe: list[str], spy: "pd.Series", batch_size: int = 100) -> list[dict]:
    survivors = []
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i + batch_size]
        try:
            data = yf.download(batch, period="2y", progress=False,
                               auto_adjust=True, group_by="ticker", threads=True)
        except Exception as e:
            print(f"[short_screener] technical batch {i} failed: {e}")
            continue

        for sym in batch:
            try:
                df = data[sym].dropna() if len(batch) > 1 else data.dropna()
                row = _evaluate_technicals_short(sym, df, spy)
                if row:
                    survivors.append(row)
            except Exception:
                continue
        time.sleep(1)

    print(f"[short_screener] Stage 4 технически филтър: {len(survivors)} оцелели")
    return survivors


def _evaluate_technicals_short(sym: str, df: "pd.DataFrame", spy: "pd.Series") -> dict | None:
    if len(df) < 260:
        return None
    close, volume = df["Close"], df["Volume"]
    price = float(close.iloc[-1])

    if price < config.SHORT_MIN_PRICE:
        return None

    # ── Stage 4: цена под низходяща 30-седмична MA (огледало на Stage 2) ──
    ma30w = close.rolling(config.WEINSTEIN_MA_WEEKS * 5).mean()
    ma30w_now, ma30w_prev = float(ma30w.iloc[-1]), float(ma30w.iloc[-21])
    if not (price < ma30w_now and ma30w_now < ma30w_prev):
        return None

    # ── RS Line: близо до 52-седмичен МИНИМУМ (обратно на screener.py) ────
    aligned_spy = spy.reindex(close.index).ffill()
    rs = (close / aligned_spy).dropna()
    rs_52w = rs.iloc[-252:]
    rs_now, rs_min = float(rs_52w.iloc[-1]), float(rs_52w.min())
    rs_status = ("new_low" if rs_now <= rs_min * 1.001
                 else "near_low" if rs_now <= rs_min * 1.03
                 else "not_lagging_enough")
    if rs_status == "not_lagging_enough":
        return None

    ma50 = float(close.rolling(50).mean().iloc[-1])
    ma200_series = close.rolling(200).mean()
    ma200, ma200_prev = float(ma200_series.iloc[-1]), float(ma200_series.iloc[-21])

    # Distribution volume на червени дни — директен reuse, нулев нов код.
    distribution_days = _count_distribution_days(sym, config.DISTRIBUTION_DAYS_LOOKBACK)

    return {
        "ticker": sym, "price": round(price, 2),
        "weinstein_stage": 4,
        "rs_status": rs_status,
        "ma50": round(ma50, 2), "ma200": round(ma200, 2),
        "below_ma50": price < ma50, "below_ma200": price < ma200,
        "ma200_declining": ma200 < ma200_prev,
        "distribution_days": distribution_days,
        "avg_volume_50d": int(volume.iloc[-50:].mean()),
    }


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 2: Survival-risk филтър (N-от-M distress сигнали)
# ──────────────────────────────────────────────────────────────────────────
def _distress_signals(info: dict) -> dict[str, bool | None]:
    """
    6 възможни distress сигнала. None = данните липсват (graceful — не се
    брои нито за, нито против, same "Yahoo данните са непълни" дух като
    screener.py fundamental_screen()).

    FIX 2026-08-2x: mortgage REITs (потвърдено: TWO currentRatio=0.22,
    ORC=0.12) структурно ВИНАГИ показват нисък liquidity ratio — borrow-
    short-buy-MBS е нормалният им бизнес модел, не distress.

    FIX 2026-08-2x (round 2 — Venci catch): същата структурна причина важи
    и за debtToEquity, не само за liquidity — потвърдено directamente:
    AGNC (717%) и NLY (737%), широко приемани за здрави/blue-chip agency
    mortgage REITs, показват ПО-ВИСОК debt-to-equity от TWO (379%). Първата
    версия на този филтър exempt-на само current/quick ratio (единствените
    сигнали, които реално бях тествал), не и high_leverage — пропуск, не
    съзнателно решение. Реален, не хипотетичен риск: нито един от 5-те
    тествани mortgage REITs (TWO/ORC/AGNC/NLY/STWD) не достига
    SHORT_MIN_DISTRESS_SIGNALS=3 днес, но е случайност на текущата
    сигнална комбинация (AGNC/NLY вече стоят на confirmed=2, едно flip на
    declining_revenue/cash_burn за utре би ги прекарало над прага частично
    заради structurally безсмислен high_leverage=True флаг). Затова и трите
    (не само двата) сигнала се exempt-ват за config.SHORT_LEVERAGE_EXEMPT_
    INDUSTRIES — останалите 3 (revenue/cashflow/estimates) остават активни.
    BDCs показват same проблем за НЯКОИ имена (ARCC), но нямат чист
    industry tag (лепени под "Asset Management" с здрави имена като
    MAIN/PSEC) — не могат чисто да се exclude-нат по same механизъм;
    N-от-M изискването в survival_risk_screen() е основната защита за тях.
    """
    industry = info.get("industry") or ""
    leverage_exempt = industry in config.SHORT_LEVERAGE_EXEMPT_INDUSTRIES

    current_ratio = info.get("currentRatio")
    quick_ratio = info.get("quickRatio")
    debt_equity = info.get("debtToEquity")
    revenue_growth = info.get("revenueGrowth")
    fcf = info.get("freeCashflow")
    eps_fwd = info.get("epsForward")
    eps_ttm = info.get("epsTrailingTwelveMonths")

    return {
        "weak_current_ratio": (None if leverage_exempt or current_ratio is None
                               else current_ratio < config.SHORT_MAX_CURRENT_RATIO),
        "weak_quick_ratio": (None if leverage_exempt or quick_ratio is None
                             else quick_ratio < config.SHORT_MAX_QUICK_RATIO),
        "high_leverage": (None if leverage_exempt or debt_equity is None
                          else debt_equity > config.SHORT_MIN_DEBT_TO_EQUITY),
        "declining_revenue": None if revenue_growth is None else revenue_growth < 0,
        "cash_burn": None if fcf is None else fcf < 0,
        "declining_forward_estimates": (None if eps_fwd is None or eps_ttm is None
                                        else eps_fwd < eps_ttm),
    }


def survival_risk_screen(candidates: list[dict], max_checks: int = 60) -> list[dict]:
    passed = []
    for row in candidates[:max_checks]:
        sym = row["ticker"]
        try:
            tk = yf.Ticker(sym)
            info = net_utils.fetch_with_timeout(lambda: tk.info) or {}

            mcap = info.get("marketCap") or 0
            if not (config.SHORT_MIN_MARKET_CAP <= mcap <= config.SHORT_MAX_MARKET_CAP):
                continue

            signals = _distress_signals(info)
            confirmed = sum(1 for v in signals.values() if v is True)
            if confirmed < config.SHORT_MIN_DISTRESS_SIGNALS:
                continue

            company = _verified_company_name(sym)  # reuse — same delisted-fix lookup

            row.update({
                "company": company["name"],
                "sector": info.get("sector") or "Unknown",
                "industry": info.get("industry") or "",
                "market_cap": mcap,
                "current_ratio": info.get("currentRatio"),
                "quick_ratio": info.get("quickRatio"),
                "debt_to_equity": info.get("debtToEquity"),
                "revenue_growth_pct": (round(info["revenueGrowth"] * 100, 1)
                                       if info.get("revenueGrowth") is not None else None),
                "free_cashflow": info.get("freeCashflow"),
                "eps_forward": info.get("epsForward"),
                "eps_trailing": info.get("epsTrailingTwelveMonths"),
                "distress_signals": signals,
                "distress_signal_count": confirmed,
                "survival_risk_disclosure": SURVIVAL_RISK_DISCLOSURE,
                "short_pct_float": round((info.get("shortPercentOfFloat") or 0) * 100, 2),
                "shares_short": info.get("sharesShort"),
            })
            passed.append(row)
            time.sleep(0.5)
        except Exception as e:
            print(f"[short_screener] survival-risk {sym} failed: {e}")
            continue

    print(f"[short_screener] survival-risk филтър: {len(passed)} финалисти")
    return passed


# ──────────────────────────────────────────────────────────────────────────
# Оркестрация
# ──────────────────────────────────────────────────────────────────────────
def run_short_screen(laggards: list[dict]) -> list[dict]:
    """
    laggards: sector_layer.laggard_sectors() резултат. За всеки лагиращ
    сектор — universe expansion → Stage 4 технически филтър → survival-risk
    филтър. Финален списък сортиран по distress_signal_count (низходящо),
    ограничен до config.MAX_SHORT_CANDIDATES.
    """
    if not laggards:
        return []

    spy = yf.download("SPY", period="2y", progress=False, auto_adjust=True)["Close"]
    if isinstance(spy, pd.DataFrame):
        spy = spy.iloc[:, 0]

    all_candidates = []
    for sector in laggards:
        try:
            universe = short_universe(sector["etf"])
            if not universe:
                continue
            tech = technical_screen_short(universe, spy)
            for c in tech:
                c["lagging_sector"] = sector["sector"]
                c["sector_etf"] = sector["etf"]
            finalists = survival_risk_screen(tech)
            all_candidates.extend(finalists)
        except Exception as e:
            print(f"[short_screener] сектор {sector.get('etf')} failed: {e}")
            continue
        time.sleep(1)

    all_candidates.sort(key=lambda r: r["distress_signal_count"], reverse=True)
    return all_candidates[:config.MAX_SHORT_CANDIDATES]


if __name__ == "__main__":
    import json
    from src.sector_layer import sector_rotation, laggard_sectors
    laggards = laggard_sectors(sector_rotation())
    res = run_short_screen(laggards)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
