"""
Секция 3.1 — Magic Formula Cross-Check (Джоел Грийнблат).

Greenblatt комбинира два критерия:
  • Earnings Yield = EBIT / Enterprise Value  (евтино ли е?)
  • Return on Capital = EBIT / (Net Working Capital + Net Fixed Assets)  (добро ли е?)

Класира всяка акция поотделно по двата критерия, събира двата ранга и сортира
по сбора. Идеята: добра компания на евтина цена.

Тук НЕ scrape-ваме magicformulainvesting.com (изисква безплатна, но чувствителна
регистрация и чупи се лесно). Вместо това изчисляваме формулата директно от
yfinance върху НЕЗАВИСИМ референтен универс (config.MAGIC_FORMULA_UNIVERSE) —
така cross-check-ът наистина е независим от CANSLIM скринера, а не само пренареждане
на същите тикъри. Резултатът се кешира за деня в data/magic_formula_cache.json,
за да не пресмятаме при всяко извикване.

Convergence signal (redesign 2026-07-15): кандидатите от CANSLIM скринера се
ранкират ЗАЕДНО с референтния универс; попадналите в топ дециала по комбиниран
Greenblatt ранг получават маркер 'MF✓' ("value confirmed") на самата карта.
Самостоятелната дневна топ-10 секция е премахната — тя показваше несвързан
списък, а обещаната конвергенция беше структурно невъзможна (виж
FIXES_2026-07-15.md). Не променя sizing — само визуален индикатор (Секция 3.1).

Graceful degradation (Секция 7): при всяка грешка връщаме празно множество и
системата продължава без маркера.
"""
from __future__ import annotations
import datetime as dt
import json
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_CACHE = config.DATA_DIR / "magic_formula_cache.json"


# ──────────────────────────────────────────────────────────────────────────
# Изчисление на двата компонента за един тикър
# ──────────────────────────────────────────────────────────────────────────
def _metrics(sym: str) -> dict | None:
    """Връща {ticker, earnings_yield, roc} или None при липсващи данни."""
    try:
        info = yf.Ticker(sym).info or {}
        ebit = info.get("ebitda")  # ebit рядко е директно в .info; ebitda е proxy
        # по-точен EBIT: оперативни маржове × приходи, ако са налични
        op_margin = info.get("operatingMargins")
        revenue = info.get("totalRevenue")
        if op_margin and revenue:
            ebit = op_margin * revenue
        ev = info.get("enterpriseValue")
        if not ebit or not ev or ev <= 0:
            return None

        earnings_yield = ebit / ev

        # Return on Capital ≈ EBIT / (Net Working Capital + Net Fixed Assets)
        # Грубо приближение от наличните .info полета:
        total_assets = info.get("totalAssets")
        current_liab = info.get("totalCurrentLiabilities")
        capital = None
        if total_assets and current_liab:
            capital = total_assets - current_liab
        if not capital or capital <= 0:
            # fallback: ROIC от yfinance, ако е наличен
            roic = info.get("returnOnAssets")
            roc = roic if roic else None
        else:
            roc = ebit / capital
        if roc is None:
            return None

        return {"ticker": sym, "earnings_yield": round(earnings_yield, 4),
                "roc": round(roc, 4),
                "name": info.get("shortName") or info.get("longName") or sym}
    except Exception as e:
        print(f"[magic_formula] {sym}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────
# Greenblatt комбиниран ранг върху референтния универс (с дневен кеш)
# ──────────────────────────────────────────────────────────────────────────
def build_ranked(universe: list[str] | None = None, top_n: int | None = None) -> list[dict]:
    """
    Връща сортиран списък [{ticker, earnings_yield, roc, mf_rank}] —
    най-добрите по Magic Formula най-отгоре. Кешира за деня.
    """
    universe = universe or config.MAGIC_FORMULA_UNIVERSE
    top_n = top_n or config.MAGIC_FORMULA_TOP_N
    today = dt.date.today().isoformat()

    # дневен кеш
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today and cached.get("ranked"):
                return cached["ranked"][:top_n]
        except Exception:
            pass

    rows = []
    for sym in universe:
        m = _metrics(sym)
        if m:
            rows.append(m)
    if not rows:
        return []

    # ранг по всеки критерий (1 = най-добър), после сбор
    by_ey = sorted(rows, key=lambda r: r["earnings_yield"], reverse=True)
    for i, r in enumerate(by_ey):
        r["_ey_rank"] = i + 1
    by_roc = sorted(rows, key=lambda r: r["roc"], reverse=True)
    for i, r in enumerate(by_roc):
        r["_roc_rank"] = i + 1
    for r in rows:
        r["mf_rank"] = r["_ey_rank"] + r["_roc_rank"]
        r.pop("_ey_rank", None)
        r.pop("_roc_rank", None)
    ranked = sorted(rows, key=lambda r: r["mf_rank"])

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "ranked": ranked},
                                     ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[magic_formula] cache write: {e}")

    return ranked[:top_n]


def value_confirmed(candidate_tickers: list[str],
                    decile: float | None = None) -> set[str]:
    """
    FIX 2026-07-15 · Redesign на конвергенцията.

    Старият top_set() проверяваше дали кандидат е в топ-50 от статичен
    74-именен универс — CANSLIM кандидатите (mid-caps в бази) структурно
    не бяха там, така че MF✓ никога не се появяваше.

    Новата посока е обратната: изчисляваме EY/ROC за САМИТЕ кандидати,
    вкарваме ги в ранкирания референтен универс и връщаме тези, чийто
    комбиниран Greenblatt ранг попада в топ дециала на общата извадка.
    Празно множество = няма стойностно потвърждение днес (валиден резултат).
    """
    decile = decile or config.MF_CONFIRM_DECILE
    try:
        base = build_ranked(top_n=10 ** 9)          # целият ранкиран универс (дневен кеш)
        if not base:
            return set()
        base_syms = {b["ticker"] for b in base}
        cand = []
        for sym in dict.fromkeys(candidate_tickers):    # уникални, запазен ред
            if sym in base_syms:
                continue                                # вече е в base с метрики
            m = _metrics(sym)
            if m:
                cand.append(m)
        pool = [dict(r) for r in base] + cand           # копия — не мутираме кеша
        for key, rk in (("earnings_yield", "_ey"), ("roc", "_roc")):
            for i, r in enumerate(sorted(pool, key=lambda x: x[key], reverse=True)):
                r[rk] = i + 1
        cutoff = max(1, int(len(pool) * decile))
        top = sorted(pool, key=lambda r: r["_ey"] + r["_roc"])[:cutoff]
        return {r["ticker"] for r in top} & set(candidate_tickers)
    except Exception as e:
        print(f"[magic_formula] value_confirmed: {e}")
        return set()


if __name__ == "__main__":
    ranked = build_ranked()
    print(f"Magic Formula топ {len(ranked)}:")
    for r in ranked[:20]:
        print(f"  {r['ticker']:6} EY={r['earnings_yield']:.1%}  ROC={r['roc']:.1%}  rank={r['mf_rank']}")
