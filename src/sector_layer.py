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


def _laggard_persistence(rs) -> tuple[float | None, bool]:
    """
    FIX 2026-08-2x (Short/Stage 4 screener): наивен single-day "chg_4w<0 AND
    chg_12w<0" дава false positives от еднодневен шум — потвърдено на живо
    (ITA/Индустрия both-negative само 1-2 от последните 20 дни, докато
    XLU/TAN устойчиво 16-20/20). Проверява последните
    config.SECTOR_PERSISTENCE_WINDOW_DAYS дни: колко от тях СЪЩО показват
    both-negative (не само днешния ред) — устойчивост, не snapshot.

    Връща (persistence_pct, confirmed_laggard). None ако rs серията е
    твърде къса за пълния прозорец (graceful — не гърми, просто не гейтва).
    """
    window = config.SECTOR_PERSISTENCE_WINDOW_DAYS
    min_needed = window + 63  # всеки тестван ден сам нуждае от 63-дневна RS история назад
    if len(rs) < min_needed:
        return None, False

    # FIX 2026-08-28 (production crash — json.dumps(rotation) в ai_brief.py
    # без default= fallback гръмна "TypeError: Object of type bool is not
    # JSON serializable"): rs.iloc[idx] тук НЕ беше float()-кастнато (за
    # разлика от останалата част на sector_rotation(), която explicit го
    # прави навсякъде другаде) — сравнения върху суров numpy/pandas scalar
    # произвеждат numpy.bool_, не native bool. NumPy 2.x показва
    # numpy.bool_.__class__.__name__ буквално като "bool" (старите версии —
    # "bool_"), затова грешката подвеждащо изглеждаше като нормален Python
    # bool. float() каст тук, same стил като rs_now/rs_4w/rs_12w по-горе.
    both_neg_flags = []
    for lag in range(window):
        idx = -1 - lag
        r_now = float(rs.iloc[idx])
        r_4w = float(rs.iloc[idx - 21])
        r_12w = float(rs.iloc[idx - 63])
        both_neg_flags.append(r_now / r_4w - 1 < 0 and r_now / r_12w - 1 < 0)

    persistence_pct = round(sum(both_neg_flags) / window * 100, 1)
    # Explicit bool() каст — defensive, дори след float()-a по-горе, за да
    # не разчитаме мълчаливо, че sum()/>= винаги връща native bool.
    confirmed_laggard = bool(sum(both_neg_flags) >= config.SECTOR_PERSISTENCE_MIN_DAYS)
    return persistence_pct, confirmed_laggard


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
        persistence_pct, confirmed_laggard = _laggard_persistence(rs)

        results.append({
            "etf": sym, "sector": name,
            "rs_chg_4w_pct": round(chg_4w, 2),
            "rs_chg_12w_pct": round(chg_12w, 2),
            "rs_at_6m_high": at_high,
            "abs_chg_4w_pct": round((float(series.iloc[-1]) / float(series.iloc[-21]) - 1) * 100, 2),
            "leading": chg_4w > 0 and chg_12w > 0,
            "laggard_persistence_pct": persistence_pct,
            "confirmed_laggard": confirmed_laggard,
        })

    results.sort(key=lambda x: x["rs_chg_4w_pct"], reverse=True)
    return results


def leading_sectors(rotation: list[dict], top_n: int = 6) -> list[dict]:
    """Секторите с положителна RS динамика — входът за скрининга (Слой 3)."""
    leaders = [s for s in rotation if s["leading"] or s["rs_at_6m_high"]]
    return leaders[:top_n] if leaders else rotation[:3]


def laggard_sectors(rotation: list[dict], top_n: int = 6) -> list[dict]:
    """
    Огледало на leading_sectors() — входът за Short/Stage 4 screener-а
    (short_screener.py). Филтрира по confirmed_laggard (persistence-gated,
    виж _laggard_persistence), НЕ по еднодневен snapshot. Сортирано по
    severity (rs_chg_12w_pct възходящо — най-отрицателните first), same
    "малко, но значимо" принцип като MAX_ACTION_TICKERS/COT whitelist-а.
    """
    laggards = sorted(
        (s for s in rotation if s.get("confirmed_laggard")),
        key=lambda x: x["rs_chg_12w_pct"],
    )
    return laggards[:top_n]


if __name__ == "__main__":
    import json
    rot = sector_rotation()
    print(json.dumps({"rotation": rot, "leaders": leading_sectors(rot)},
                     indent=2, ensure_ascii=False, default=str))
