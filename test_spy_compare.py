"""
Пакет 1, т.8 (2026-10-03): Track Record v2 показва доходността спрямо SPY за СЪЩИТЕ периоди на
държане — купува се на Open на деня на входа; частичната продажба и остатъкът се продават на
Close на своите дати (живите — на последния Close).

РЕАЛНИ барове: tests/fixtures/ohlc_EXEL.csv и ohlc_SPY.csv (Yahoo, свалени на 02.10.2026) — реалният
Action план на EXEL от 29.06.2026 (вход $55.00 по отварянето, стоп $50.39 на 12.08).
СИНТЕТИЧНИ: целите/частичните продажби (в реалните данни няма 2R), агрегатните записи, липсващ SPY.
Пускане: python test_spy_compare.py
"""
import sys, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import config
from src import backtest, trade_sim, sizing, thermometer, render

EXEL = pd.read_csv(ROOT / "tests/fixtures/ohlc_EXEL.csv", index_col=0, parse_dates=True)
SPY = pd.read_csv(ROOT / "tests/fixtures/ohlc_SPY.csv", index_col=0, parse_dates=True)
sim, spy_ret = trade_sim.simulate, trade_sim.spy_return_pct


def mk(rows, start="2026-03-02"):
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close"])


PLAN = dict(entry_date="2026-03-02", buy_stop=100.0, max_chase=105.0, stop_loss=92.0, target_1=116.0, window_sessions=5)

print("── СИНТЕТИЧНО: доходност върху входа, претеглена с частичната продажба ──")
rows = [(99, 101, 98, 100)] + [(100 + i, 106 + i, 100 + i, 101 + i) for i in range(1, 12)]
rows += [(112, 113, 111, 112), (111, 112, 110, 111), (108, 109, 100, 101)]
r = sim(PLAN, mk(rows))
assert r["status"] == "trailing_stop_exit" and r["return_pct"] == 8.5, r      # 0.5×(+16%) + 0.5×(+1%)
r = sim(PLAN, mk([(99, 101, 98, 100), (99, 100, 91.5, 95)]))
assert r["status"] == "stopped" and r["return_pct"] == -8.0, r
r = sim(PLAN, mk([(99, 101, 98, 100), (90.0, 91, 89, 90.5)]))                 # гап → по Open $90
assert r["return_pct"] == -10.0, r
r = sim(PLAN, mk([(99, 101, 98, 100), (110, 117, 109, 111)]))                 # жива, частична на $116 + Close $111
assert r["status"] == "trailing" and r["return_pct"] == round(0.5 * 16 + 0.5 * 11, 2) == 13.5, r
r = sim(PLAN, mk([(99, 101, 98, 100), (100, 104, 99, 104)]))
assert r["status"] == "open" and r["return_pct"] == 4.0, r
assert sim(PLAN, mk([(97, 99.5, 96, 98)] * 5))["return_pct"] is None           # без вход — без доходност
print("  ✓ частична $116 + остатък $101 → +8.5%; стоп -8.0%; гап $90 → -10.0%; жива с частична (+13.5%) и без (+4.0%)")
print()

print("── СИНТЕТИЧНО: SPY за същите периоди ──")
spy = mk([(400, 401, 399, 401)] + [(401, 413, 400, 412)] + [(412, 413, 407, 408)] * 3)      # Open 400; Close 412 на ден 2; 408 после
res = {"fill_price": 100.0, "fill_date": "2026-03-02", "exit_date": "2026-03-05", "last_close_date": "2026-03-06",
       "partial_price": None, "partial_fraction": 0.0, "target1_hit_date": None}
assert spy_ret(res, spy) == 2.0                                                         # 408/400 - 1
res_p = {**res, "partial_price": 116.0, "partial_fraction": 0.5, "target1_hit_date": "2026-03-03"}
assert spy_ret(res_p, spy) == 2.5                                                       # 0.5×(412/400-1 = +3%) + 0.5×(+2%)
live = {**res, "exit_date": None}
assert spy_ret(live, spy) == 2.0                                                        # живa → последният Close (06.03)
assert spy_ret({**res, "exit_date": "2026-04-01"}, spy) is None                         # няма SPY бар за датата
assert spy_ret({**res, "fill_price": None}, spy) is None and spy_ret(res, None) is None and spy_ret(res, spy.iloc[0:0]) is None
print("  ✓ без частична: Open 400 → Close 408 = +2.0%; с частична: 0.5×(+3.0%) + 0.5×(+2.0%) = +2.5%; живa → последният Close;")
print("    липсващ бар/SPY/вход → None")
print()

print("── РЕАЛНО: EXEL 29.06.2026 срещу SPY ──")
plan = sizing.position_plan_v2({"price": 54.77, "pivot": 53.93, "struct_low": 50.80}, 1.0, "2026-06-29")
rec = dict(entry_date="2026-06-29", buy_stop=plan["buy_stop"], max_chase=plan["max_chase"],
           stop_loss=plan["stop_loss"], target_1=plan["target_1"])
r = sim(rec, EXEL, "2026-10-02")
assert (r["status"], r["fill_price"], r["exit_date"], r["exit_price"]) == ("stopped", 55.0, "2026-08-12", 50.39)
assert r["return_pct"] == round((50.39 - 55.0) / 55.0 * 100, 2) == -8.38
spy_open, spy_close = float(SPY.loc["2026-06-29", "Open"]), float(SPY.loc["2026-08-12", "Close"])
want = round((spy_close / spy_open - 1) * 100, 2)
got = spy_ret(r, SPY)
assert got == want, (got, want)
alpha = round(r["return_pct"] - got, 2)
print(f"  ✓ EXEL: вход $55.00 (Open 29.06) → стоп $50.39 (12.08) = {r['return_pct']:+.2f}%; SPY Open ${spy_open:.2f} → "
      f"Close ${spy_close:.2f} = {got:+.2f}%; разлика {alpha:+.2f}%")

bars = EXEL[["Open", "High", "Low", "Close"]]
tr = backtest._new_v2_record("EXEL", "2026-06-29", plan)
backtest._resolve_position_v2(tr, bars, dt.date(2026, 10, 2), SPY[["Open", "High", "Low", "Close"]])
assert (tr["return_pct"], tr["spy_return_pct"], tr["alpha_pct"]) == (-8.38, want, alpha), tr
tr2 = backtest._new_v2_record("EXEL", "2026-06-29", plan)
backtest._resolve_position_v2(tr2, bars, dt.date(2026, 10, 2))                       # без SPY → остава резолвирана
assert tr2["status"] == "stopped" and tr2["spy_return_pct"] is None and tr2["alpha_pct"] is None
print("  ✓ _resolve_position_v2 записва return_pct / spy_return_pct / alpha_pct; без SPY данни позицията пак се резолвира")
print()

print("── обобщение за dashboard-а (СИНТЕТИЧНИ записи) ──")
_tmp = tempfile.TemporaryDirectory(prefix="market_brief_spy_")
config.DATA_DIR = pathlib.Path(_tmp.name)
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
backtest._fetch_current_prices = lambda tickers: {t: 60.0 for t in tickers}
backtest.enrich.earnings_recap = lambda t: None


def synth(key, status, r_, ret, spy_, **kw):
    rec = backtest._new_v2_record("EXEL", key, plan)
    rec.update(status=status, realized_r=r_, return_pct=ret, spy_return_pct=spy_, fill_date=key, fill_price=55.0,
               resolution_date=None if r_ is None else key,
               alpha_pct=None if (ret is None or spy_ is None) else round(ret - spy_, 2), **kw)
    return rec


backtest._save_tracker({
    "A_2026-01-05": synth("2026-01-05", "stopped", -1.0, -8.38, 5.0),
    "A_2026-02-02": synth("2026-02-02", "trailing_stop_exit", 1.5, 10.0, 2.0),
    "A_2026-03-02": synth("2026-03-02", "stopped", -1.0, 1.0, 3.0),
    "A_2026-04-06": synth("2026-04-06", "stopped", -1.0, -7.0, None),                   # без SPY данни → не влиза в сравнението
    "A_2026-05-04": synth("2026-05-04", "trailing", None, 8.5, 2.0, partial_price=116.0, partial_fraction=0.5),   # жива
})
sm = backtest.get_backtest_summary()
sc = sm["spy_compare"]
assert sc["n"] == 3 and sc["avg_return_pct"] == round((-8.38 + 10.0 + 1.0) / 3, 2) == 0.87
assert sc["avg_spy_pct"] == round((5.0 + 2.0 + 3.0) / 3, 2) == 3.33 and sc["avg_alpha_pct"] == round(0.87 - 3.33, 2) == -2.46
assert sc["beat_spy_pct"] == 33.3                                                        # само втората позиция води SPY
lp = sm["open_positions"][0]
assert lp["unrealized_pct"] == 8.5 and lp["spy_return_pct"] == 2.0 and lp["alpha_pct"] == 6.5   # претеглена с частичната, не 60/55-1
assert round((60.0 - 55.0) / 55.0 * 100, 1) == 9.1                                       # наивният % (цена спрямо входа) би бил друг
print("  ✓ 3 затворени със SPY данни (4-тата без SPY е изключена): средно +0.87% срещу SPY +3.33% → -2.46%, 33.3% водят SPY;")
print("    живата позиция показва претеглената доходност (+8.5% с частичната продажба, не наивните +9.1%) и SPY +2.0%")

brief = {"date": "2026-10-05", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")),
         "action": [], "watchlist": [], "backtest": sm,
         "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
with tempfile.TemporaryDirectory() as docs:
    orig_docs = config.DOCS_DIR
    config.DOCS_DIR = pathlib.Path(docs)
    try:
        html = render.render_dashboard(brief)
    finally:
        config.DOCS_DIR = orig_docs
flat = " ".join(html.split())
assert "Спрямо SPY (същите периоди на държане, 3 затворени): средно +0.87% срещу SPY +3.33% → разлика -2.46% · 33.3% от позициите водят SPY" in flat
assert "SPY, същия период" in html and "+2.0%" in html
print("  ✓ dashboard: 'Спрямо SPY (същите периоди на държане, 3 затворени): средно +0.87% срещу SPY +3.33% → разлика -2.46% ·")
print("    33.3% от позициите водят SPY' и колона 'SPY, същия период' в отворените позиции")
_tmp.cleanup()

print()
print("Всички тестове минаха.")
