"""
26.10.2026 · етап 4б, т. 3 (решение от 26.10): книгите тип Уиш — доходността 5/10/20 сесии след входа (literal: затварянето на сигналния ден) НЕЗАВИСИМО от изхода по линията, и SPY за
същите дати (trade_sim.gw_horizons → rec["horizons"]); затворен запис се резолвира, докато мине последният срок (backtest._gw_needs_horizons, до 45 дни след входа).

РЕАЛНО: tests/fixtures/gw_horizons_2026-10-26.json — записите PLTR_2026-10-12_gw (вход 09.10, изход по линията 16.10) и HLT_2026-10-16_gw (вход 15.10, отворен) от data/backtest_tracker.json
и дневните Open/Close на PLTR, HLT и SPY от Yahoo до 23.10 (свалени на 26.10). СИНТЕТИЧНО (означено): датата "днес" 30.11 за 45-дневния таван.
Пускане: python test_gw_horizons.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_gwh_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import backtest, trade_sim
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"

FX = json.loads((ROOT / "tests" / "fixtures" / "gw_horizons_2026-10-26.json").read_text(encoding="utf-8"))
B = FX["bars"]
idx = {s: pd.to_datetime(v["dates"]) for s, v in B.items()}
opens = pd.DataFrame({s: pd.Series(v["o"], index=idx[s]) for s, v in B.items()})
closes = pd.DataFrame({s: pd.Series(v["c"], index=idx[s]) for s, v in B.items()})
spy = pd.DataFrame({"Open": opens["SPY"], "Close": closes["SPY"]}).dropna()
C = lambda s, d: float(closes[s].loc[pd.Timestamp(d)])
assert config.GLB_WISH_HORIZONS == (5, 10, 20) and config.GLB_WISH_COMPARE_HORIZON == 20

print("── 1. PLTR (изход по линията на 16.10): 5 и 10 сесии след входа 09.10 — независимо от изхода ──")
p = copy.deepcopy(FX["records"]["PLTR_2026-10-12_gw"])
stored = (p["status"], p["return_pct"], p["exit_date"])
with contextlib.redirect_stdout(io.StringIO()):
    backtest._resolve_glb_wish_record(p, opens, closes, spy, dt.date(2026, 10, 26))
assert (p["status"], p["return_pct"], p["exit_date"]) == stored == ("line_exit", stored[1], "2026-10-16")      # резултатът на книгата е същият
h = p["horizons"]
assert set(h) == {"5", "10"} and h["5"]["date"] == "2026-10-16" and h["10"]["date"] == "2026-10-23"
for k, d in (("5", "2026-10-16"), ("10", "2026-10-23")):
    assert h[k]["ret"] == round((C("PLTR", d) / C("PLTR", "2026-10-09") - 1) * 100, 2) and h[k]["spy"] == round((C("SPY", d) / C("SPY", "2026-10-09") - 1) * 100, 2)
    assert h[k]["alpha"] == round(h[k]["ret"] - h[k]["spy"], 2)
assert backtest._gw_needs_horizons(p, dt.date(2026, 10, 26)) and not backtest._gw_needs_horizons(p, dt.date(2026, 11, 30))     # 20 сесии още не; след 45 дни — не се опитва
print(f"  ✓ 5 сесии (16.10): {h['5']['ret']:+.2f}% (SPY {h['5']['spy']:+.2f}%), 10 сесии (23.10): {h['10']['ret']:+.2f}% (SPY {h['10']['spy']:+.2f}%); "
      f"изходът по линията ({stored[1]:+.2f}%) не се мени; 20 сесии още няма → записът се резолвира пак (до 45 дни)")

print()
print("── 2. HLT (отворен, вход 15.10): само 5 сесии ──")
r = copy.deepcopy(FX["records"]["HLT_2026-10-16_gw"])
with contextlib.redirect_stdout(io.StringIO()):
    backtest._resolve_glb_wish_record(r, opens, closes, spy, dt.date(2026, 10, 26))
assert r["status"] == "open" and set(r["horizons"]) == {"5"} and r["horizons"]["5"]["date"] == "2026-10-22"
assert r["horizons"]["5"]["ret"] == round((C("HLT", "2026-10-22") / C("HLT", "2026-10-15") - 1) * 100, 2)
assert not backtest._gw_needs_horizons(r, dt.date(2026, 10, 26))                                                   # отворен — резолвира се така или иначе
assert trade_sim.gw_horizons(pd.DataFrame({"Close": closes["HLT"]}).dropna(), spy, "2026-10-18") == {}             # неделя — няма бар за входа
print(f"  ✓ 5 сесии (22.10): {r['horizons']['5']['ret']:+.2f}%; 10 и 20 — още няма")

print()
print("── 3. обобщението върху двата РЕАЛНИ записа ──")
backtest._save_tracker({"PLTR_2026-10-12_gw": p, "HLT_2026-10-16_gw": r})
config.TRACK_GLB_WISH = True
S = backtest.get_glb_wish_summary()
h5 = S["horizons"]["5"]
assert h5["n"] == 2 and h5["avg_ret"] == round((p["horizons"]["5"]["ret"] + r["horizons"]["5"]["ret"]) / 2, 2) and S["horizons"]["10"]["n"] == 1 and S["horizons"]["20"]["n"] == 0
assert not S["horizons_visible"] and all(g["avg_ret"] is None for g in S["by_regime"].values())
assert not {"win_rate_pct", "median_return_pct", "win_ci_pct"} & set(S["all"])
print(f"  ✓ 5 сесии: средно {h5['avg_ret']:+.2f}% (n=2); 10 сесии: n=1; 20 сесии: n=0 — сравнението по режим чака {config.GLB_WISH_MIN_ENTRIES_FOR_STATS} записа с 20 сесии")

print()
print("── 4. изречението за реплея над книгите (решение по етап 4б, т. 1) ──")
from src import render
import re, html as htmllib
for key, rep in (("glb_wish", config.GLB_WISH_REPLAY_STATS), ("glb_wish_high", config.GLB_WISH_HIGH_REPLAY_STATS)):
    assert not {"win_literal_pct", "win_exec_pct", "median_literal_pct", "median_exec_pct"} & set(rep) and set(rep["horizons"]) == {"5", "10", "20"}
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19); b.setdefault("backtest", {})["glb_wish"] = S
with contextlib.redirect_stdout(io.StringIO()):
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "Реплей върху историята (1962–2026, 26 183 сделки; SPY от 1993): алфа на година позиция +8.8% [6.2; 11.9]; доходност N сесии след входа" in page
assert "20 — +0.69% срещу +0.47% (алфа +0.22% [-0.00; 0.44])" in page and "оцелели" in page and "печеливши 9.3%" not in page and "медиана -1.59%" not in page
print("  ✓ „Реплей … алфа на година позиция +8.8% [6.2; 11.9]; … 20 — +0.69% срещу +0.47% (алфа +0.22% …)“; без % печеливши и медиана; бележката за оцелелите остава")
print("\n✅ test_gw_horizons: всичко мина")
