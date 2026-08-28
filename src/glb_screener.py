"""
GLB (Green Line Breakout) скрийнър — Classic + Momentum варианти, ПАРАЛЕЛНО
(не се избира един за сметка на другия, виж config.py секцията за пълния
design rationale). Вдъхновено от Eric Wish (wishingwealthblog.com), но
преработено след backtest диагностика в experiments/glb_backtest.py и
experiments/glb_monthly_check.py (2026-08-12/13 discussion).

Универсален гейт (и за трите изхода по-долу): месечен duration-only критерий
— ATH close unpenetrated >= GLB_MIN_MONTHS_UNPENETRATED последователни
месеца, после close над него. glb_type има ТРИ, не два, изхода:
  "classic"              — дневният tightness overlay СЪЩО минава на same
                            breakout момент (тесен, удържан base).
  "momentum"              — overlay-ът е ИЗЧИСЛЕН, но НЕ минава прага
                            (реално потвърден бърз/волатилен пробив).
  "insufficient_history"  — overlay-ът НЕ е могъл да се изчисли изобщо
                            (< GLB_MIN_CONSOLIDATION_DAYS дневни бара
                            налични) — explicit различно от "momentum",
                            за да не се бърка "не проверихме" с "проверихме
                            и няма база" (виж _evaluate_ticker).
Класификацията е ПО SETUP, не по възраст на тикъра — виж config.py защо
(WDC's 47г история не спаси overlay-а от провал на собствения ѝ 2025
breakout; age-based gating би скрил точно този случай).

Screening и AI синтез остават разделени, same принцип като screener.py —
този модул е чисто механичен, нула AI извиквания.

Универс: reuse-ва src.screener.build_universe() — САМО дефиниционния
Wikipedia S&P500/Nasdaq100/MidCap400 списък, НЕ технически изчислени
резултати (никаква coupling на screener.py's 2y OHLCV данни или Stage2/RS
преценка). OHLCV fetch-ът тук е напълно независим: собствени yf.download
batch извиквания с GLB_HISTORY_PERIOD (default "max") — screener.py тегли
само 2г, структурно недостатъчно за multi-decade ATH detection (WDC
сигналът изисква данни чак до 2014 г.).

Graceful degradation: провал на batch fetch или единичен тикър -> пропусни,
print диагностика, продължи с останалите (Секция 7).
"""
from __future__ import annotations
import time

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src.screener import build_universe
from src.ai_brief import _verified_company_name

import yfinance as yf

RISK_NOTES = {
    "classic": (
        "Тесен, добре удържан base преди пробива "
        f"(band_hold>={config.GLB_MIN_BAND_HOLD_PCT:.0f}% от последните "
        f"{config.GLB_MIN_CONSOLIDATION_DAYS} дни) — по-нисък очакван "
        "volatility профил, най-близък до класически Stage 2 setup."
    ),
    "momentum": (
        "Дълъг ATH unpenetrated период, но БЕЗ тесен daily base преди "
        "пробива — бърз/волатилен момentum move, не тиха консолидация. "
        "По-висок очакван drawdown риск спрямо стандартните Action "
        "кандидати — обмисли намален size."
    ),
    "insufficient_history": (
        "Недостатъчна дневна история (< GLB_MIN_CONSOLIDATION_DAYS дни "
        "налични) за оценка на консолидационното качество — НЕ е "
        "потвърдено нито тесен base, нито momentum move, просто не сме "
        "проверили. Третирай предпазливо като непроверен случай, не като "
        "'без база'."
    ),
}


def _monthly_duration_check(monthly_close) -> dict | None:
    """
    Буквален Wish критерий, приложен на месечно orязана Close серия
    (последният елемент = текущият/последният наличен месец). Връща None
    ако текущият месец НЕ е валиден GLB breakout момент.
    """
    if len(monthly_close) < config.GLB_MIN_MONTHS_UNPENETRATED + 2:
        return None
    i = len(monthly_close) - 1
    window_before = monthly_close.iloc[:i]
    prior_high = float(window_before.max())
    prior_high_pos = int(window_before.values.argmax())
    months_unpenetrated = i - prior_high_pos - 1
    this_close = float(monthly_close.iloc[i])
    breakout = this_close > prior_high
    if not (breakout and months_unpenetrated >= config.GLB_MIN_MONTHS_UNPENETRATED):
        return None
    return {
        "prior_high": round(prior_high, 2),
        "prior_high_month": monthly_close.index[prior_high_pos].strftime("%Y-%m"),
        "months_unpenetrated": months_unpenetrated,
    }


def _tightness_overlay(daily_close, daily_high, daily_low, prior_high: float) -> dict | None:
    """
    Дневен overlay — мажоритарен rolling критерий, изчислен ВИНАГИ (когато
    има достатъчно дневна история), независимо дали ще мине Classic прага.
    Trailing прозорец = последните GLB_MIN_CONSOLIDATION_DAYS дни ПРЕДИ
    последния ред (= "днес", breakout деня). None само при недостатъчна
    дневна история — ЯВНО РАЗЛИЧНО от "проверихме и не мина" (виж
    _evaluate_ticker: None -> "insufficient_history" label, не мълчаливо
    "momentum" — "не знаем" не бива тихо да се превръща в "знаем, и е X").
    """
    n = config.GLB_MIN_CONSOLIDATION_DAYS
    if len(daily_close) < n + 1:
        return None
    recent_close = daily_close.iloc[-(n + 1):-1]
    recent_high = daily_high.iloc[-(n + 1):-1]
    recent_low = daily_low.iloc[-(n + 1):-1]
    band_floor = prior_high * (1 - config.GLB_APPROACH_PCT / 100)
    band_hold_pct = float((recent_close >= band_floor).sum()) / n * 100
    tightness_range_pct = float((recent_high.max() - recent_low.min()) / prior_high * 100)
    return {
        "band_hold_pct": round(band_hold_pct, 1),
        "tightness_range_pct": round(tightness_range_pct, 2),
        "meets_tightness": band_hold_pct >= config.GLB_MIN_BAND_HOLD_PCT,
    }


def _split_only_adjust(close, high, low, splits):
    """
    FIX 2026-08-24 (GLB dividend-drift одит, Venci): auto_adjust=True
    ретроактивно dividend-adjust-ва ЦЯЛАТА историческа Close/High/Low серия
    при всяко ex-div събитие — потвърдено на живо (NWE ex-div 17.08.2026,
    prior_high $71.66→$70.99 в СЪЩИЯ ден, нулева промяна в реалната пазарна
    цена). Скалата е широка: за 44г-стар high-yield платец (SO/Southern Co)
    auto_adjust=True показва 1981 close $0.27 срещу реалните $3.67
    (auto_adjust=False) — 13.6× изкривяване. За price-breakout детекция
    (Weinstein/Wish методология) искаме SPLIT-adjusted, НЕ dividend-adjusted
    цени — total-return adjustment е грешен инструмент тук, price-level
    пробив трябва да е спрямо реално търгуваната цена.

    Ръчна split-only корекция върху auto_adjust=False суровите данни:
    за всяка split дата, всички редове ПРЕДИ нея се делят на ratio-то.
    Множество splits се композират коректно (всеки следващ split дели
    и по-старите редове отново — ред на итерация няма значение, маските
    са независими по абсолютна дата).
    """
    if splits is None or splits.empty:
        return close, high, low
    close, high, low = close.copy(), high.copy(), low.copy()
    for split_date, ratio in splits.items():
        if not ratio or ratio == 1:
            continue
        mask = close.index < split_date
        close.loc[mask] = close.loc[mask] / ratio
        high.loc[mask] = high.loc[mask] / ratio
        low.loc[mask] = low.loc[mask] / ratio
    return close, high, low


def _evaluate_ticker(sym: str, hist) -> dict | None:
    """
    hist = пълен OHLCV df за sym (вече изтеглен batch-ово от screen()).
    Прилага универсалния месечен гейт, после класифицира Classic/Momentum
    по дневния overlay. Връща None ако тикърът не е GLB кандидат въобще.
    """
    if hist is None or hist.empty or len(hist) < 60:
        return None

    monthly_close = hist["Close"].resample("ME").last().dropna()
    m_result = _monthly_duration_check(monthly_close)
    if m_result is None:
        return None

    history_years = (hist.index[-1] - hist.index[0]).days / 365.25
    ath_label = ("all_time_high" if history_years >= config.GLB_MIN_ATH_HISTORY_YEARS
                else "new_high_since_listing")

    overlay = _tightness_overlay(hist["Close"], hist["High"], hist["Low"], m_result["prior_high"])
    if overlay is None:
        glb_type = "insufficient_history"     # НЕ проверихме overlay-а — различно от "проверихме, не мина"
    elif overlay["meets_tightness"]:
        glb_type = "classic"
    else:
        glb_type = "momentum"

    company = _verified_company_name(sym)["name"]  # reuse — same lookup като COT секцията (ai_brief.py)

    return {
        "ticker": sym,
        "company": company,
        "glb_type": glb_type,
        "price": round(float(hist["Close"].iloc[-1]), 2),
        "prior_high": m_result["prior_high"],
        "prior_high_month": m_result["prior_high_month"],
        "months_unpenetrated": m_result["months_unpenetrated"],
        "ath_label": ath_label,
        "history_years": round(history_years, 1),
        "tightness": overlay,  # None ако няма достатъчно дневна история за overlay-а
        "risk_note": RISK_NOTES[glb_type],
    }


def screen(universe: list[str] | None = None, batch_size: int = 50) -> list[dict]:
    """
    Главна входна точка. universe=None -> reuse-ва screener.build_universe()
    (само СПИСЪКА от тикъри, виж модул docstring-а). batch_size по-малък от
    screener.py's 100 нарочно — period="max" на тикър е много по-тежък
    payload от screener.py's period="2y".

    Връща списък от dict-ове, ВСЕКИ explicit маркиран с "glb_type"
    ("classic"/"momentum") — Двата типа остават заедно в резултата,
    разделянето/визуализацията е грижа на извикващия код (dashboard).
    """
    if universe is None:
        universe = build_universe()

    results = []
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i + batch_size]
        try:
            # FIX 2026-08-24: auto_adjust=False + actions=True (виж
            # _split_only_adjust docstring-а за пълния rationale) — сурови
            # Close/High/Low, split историята идва БЕЗПЛАТНО в СЪЩИЯ batch
            # call (Stock Splits колона), без нужда от отделна per-ticker
            # yf.Ticker(sym).splits заявка.
            data = yf.download(batch, period=config.GLB_HISTORY_PERIOD, progress=False,
                               auto_adjust=False, actions=True, group_by="ticker",
                               threads=True)
        except Exception as e:
            print(f"[glb_screener] batch {i} fetch грешка: {e}")
            continue

        for sym in batch:
            try:
                df = (data[sym] if len(batch) > 1 else data).dropna(
                    subset=["Close", "High", "Low"])
                splits = df["Stock Splits"]
                close, high, low = _split_only_adjust(
                    df["Close"], df["High"], df["Low"], splits[splits != 0])
                df = df.assign(Close=close, High=high, Low=low)
                r = _evaluate_ticker(sym, df)
            except Exception as e:
                print(f"[glb_screener] {sym}: {e}")
                continue
            if r:
                results.append(r)
        time.sleep(1)  # не дразним Yahoo, same дисциплина като screener.py

    classic = [r for r in results if r["glb_type"] == "classic"]
    momentum = [r for r in results if r["glb_type"] == "momentum"]
    insufficient = [r for r in results if r["glb_type"] == "insufficient_history"]
    print(f"[glb_screener] {len(results)} GLB кандидати ({len(classic)} classic, "
         f"{len(momentum)} momentum, {len(insufficient)} insufficient_history) "
         f"от {len(universe)} тикъра")
    return results


if __name__ == "__main__":
    import json
    # Бърз smoke test само върху познатите 4 тикъра (SNDK/WDC/MU/STX) —
    # пълният universe scan е скъп (500+ тикъра × period="max"), за
    # production run виж screen() без universe= аргумент.
    out = screen(universe=["SNDK", "WDC", "MU", "STX"])
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
