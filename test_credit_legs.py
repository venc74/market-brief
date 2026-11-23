"""
19.10.2026 · етап 2, доп. т. 3 (IEI/HYG — БЕЗ промяна на правилото): (а) 10д RoC на отношението се разлага на приноса на IEI и на HYG (ln R = ln IEI − ln HYG) — в етикета и в
regime_reason; (б) "рязко разширяване на credit risk premium" → "рязък скок на IEI/HYG (лихви + кредит)". РЕАЛНО 19.10: +1.0% (95. percentile) = IEI +0.95%, HYG −0.07% — скокът е
от лихвите (държавните облигации поскъпват), не от кредита.

РЕАЛНО: tests/fixtures/iei_hyg_2026-10-16.json — дневните Close на IEI и HYG (Yahoo, 01.09.2023–16.10.2026); tests/fixtures/brief_2026-10-19.json — индикаторите и макрото на брифа.
СИНТЕТИЧНО (маркирано): подменените функции на индикаторите (за build_thermometer), временният файл със състоянието.
Пускане: python test_credit_legs.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib, tempfile, datetime as dt, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
from src import thermometer as th

FX = json.loads((ROOT / "tests" / "fixtures" / "iei_hyg_2026-10-16.json").read_text(encoding="utf-8"))["series"]
S = {k: pd.Series(v["close"], index=pd.to_datetime(v["dates"])) for k, v in FX.items()}
start = S["IEI"].index[-1] - pd.DateOffset(years=3)
iei, hyg = S["IEI"][S["IEI"].index >= start], S["HYG"][S["HYG"].index >= start]
common = iei.index.intersection(hyg.index)
ratio = (iei[common] / hyg[common]).sort_index()

print("── (а) разлагането (РЕАЛНИТЕ цени до 16.10) ──")
r = th._evaluate_credit_spread(ratio, {"IEI": iei[common], "HYG": hyg[common]})
assert (r["roc_10d_pct"], r["roc_percentile"], r["spike"], r["iei_10d_pct"], r["hyg_10d_pct"]) == (1.01, 94.6, True, 0.95, -0.07)
assert "10д RoC +1.0% (IEI +0.9%, HYG -0.1%) (95. percentile) ⚠ рязък скок (лихви + кредит)" in r["label"]
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
real = next(i for i in B19["thermometer"]["indicators"] if i["name"].startswith("IEI/HYG"))
assert (real["roc_10d_pct"], round(real["roc_percentile"]), real["value"]) == (r["roc_10d_pct"], round(r["roc_percentile"]), r["value"])   # = брифа от 19.10
assert "iei_10d_pct" not in th._evaluate_credit_spread(ratio) and "(IEI" not in th._evaluate_credit_spread(ratio)["label"]                    # без краката — както преди
print("  ✓ 19.10: RoC +1.01% (94.6) = IEI +0.95% и HYG −0.07% (= стойностите в брифа); етикет '10д RoC +1.0% (IEI +0.9%, HYG -0.1%) (95. percentile) ⚠ рязък скок (лихви + кредит)'")

print()
print("── (б) regime_reason (РЕАЛНИЯТ бриф от 19.10 + краката от цените) ──")
IND = {i["name"]: dict(i) for i in B19["thermometer"]["indicators"]}
IND["IEI/HYG (Credit Spread)"].update(iei_10d_pct=r["iei_10d_pct"], hyg_10d_pct=r["hyg_10d_pct"])
saved = {n: getattr(th, n) for n in ("spy_trend", "vix_level", "market_put_call", "move_index", "vix_term_structure", "credit_spread_proxy", "market_breadth", "_breadth_divergence")}
th.spy_trend = lambda: dict(IND["SPY тренд"]); th.vix_level = lambda: dict(IND["VIX"]); th.market_put_call = lambda: dict(IND["Put/Call (SPY)"])
th.move_index = lambda: dict(IND["MOVE (Bond Vol)"]); th.vix_term_structure = lambda: dict(IND["VIX Term Structure"])
th.credit_spread_proxy = lambda: dict(IND["IEI/HYG (Credit Spread)"]); th.market_breadth = lambda: dict(IND["Market Breadth (% над 40dMA)"]); th._breadth_divergence = lambda _i: None
orig = th._OVERRIDE_STATE_FILE
with tempfile.TemporaryDirectory() as tmp:
    th._OVERRIDE_STATE_FILE = pathlib.Path(tmp) / "s.json"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            t = th.build_thermometer(B19["macro"], today=dt.date(2026, 10, 19))
    finally:
        th._OVERRIDE_STATE_FILE = orig
        for n, f in saved.items():
            setattr(th, n, f)
# 17.11.2026 (пакет 3): IEI/HYG override — само при кредитен натиск; на 19.10 HYG е −0.1% за 10 дни (праг −1%), HY OAS тогава още не се теглеше → override-ът отпада
g = t["credit_gate"]
assert g and g["removed"] and g["hyg_10d_pct"] == -0.07 and g["oas_missing"] and not any(o["trigger"] == "IEI/HYG" for o in t["overrides"])
assert "HYG за 10 дни -0.1% (праг -1%)" in t["credit_pressure"]["text"] and "HY OAS: няма данни" in t["credit_pressure"]["text"]
assert t["regime_reason"].startswith("MOVE 101: спайкът отшумява"), t["regime_reason"]          # остава MOVE в хистерезис
assert "credit risk premium" not in t["regime_reason"] and "credit risk premium" in B19["thermometer"]["regime_reason"]
print(f"  ✓ IEI/HYG скок без кредитен натиск (HYG -0.1%) — не блокира; „{t['credit_pressure']['text']}“")
print("\n✅ test_credit_legs: всичко мина")
