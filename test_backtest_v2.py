"""
Пакет 1, т.2 (2026-10-03): Track Record v2 записите в backtest.py — ingest на buy-stop план,
резолюция през trade_sim, обобщение, OPEN✓ с датата на входа. Без мрежа и БЕЗ реални data/*.json:
tracker файлът и DATA_DIR са във временна директория, yf.download е подменен с фикстурите.

РЕАЛНИ барове: tests/fixtures/ohlc_EXEL.csv (Yahoo, свалени на 02.10.2026).
Планове: 29.06 — РЕАЛНИЯТ Action план на EXEL; 20.07 / 25.09 / 01.10 — ХИПОТЕТИЧНИ (тогава EXEL
беше Watchlist под pivot), за да са налични всички статуси върху реални барове.
Пускане: python test_backtest_v2.py
"""
import sys, pathlib, tempfile, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import datetime as dt
import pandas as pd
import config
from src import backtest, sizing, main as brief_main

EXEL = pd.read_csv(ROOT / "tests/fixtures/ohlc_EXEL.csv", index_col=0, parse_dates=True)
SPY = pd.read_csv(ROOT / "tests/fixtures/ohlc_SPY.csv", index_col=0, parse_dates=True)
TODAY = dt.date(2026, 10, 2)

_tmp = tempfile.TemporaryDirectory(prefix="market_brief_bt_")
config.DATA_DIR = pathlib.Path(_tmp.name)
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
config.ENABLE_BACKTEST = True

DATA = {"EXEL": EXEL, "SPY": SPY}      # какво "връща" подмененият yf.download (SPY — за сравнението, т.8)
LAST_CUT = {"to": None}                # ограничава барове до дата (за "жива" позиция)


def fake_download(tickers, start=None, progress=False, auto_adjust=False, **kw):
    frames = {}
    for t in tickers:
        df = DATA[t]
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if LAST_CUT["to"]:
            df = df[df.index <= pd.Timestamp(LAST_CUT["to"])]
        frames[t] = df
    cols = ["Open", "High", "Low", "Close", "Volume"]
    out = pd.concat({f: pd.DataFrame({t: frames[t][f] for t in tickers}) for f in cols}, axis=1)
    return out


backtest.yf.download = fake_download
backtest._unapplied_splits = lambda rec: []                     # без мрежа за сплитове
backtest._fetch_current_prices = lambda tickers: {t: float(EXEL["Close"].iloc[-1]) for t in tickers}
backtest.enrich.earnings_recap = lambda t: None


def v2_plan(entry_date, buy_stop, chase, stop, target, signal_price):
    return {"method": "v2", "buy_stop": buy_stop, "max_chase": chase, "stop_loss": stop, "target_1": target,
            "entry_mid": signal_price, "window_sessions": 5, "valid_through": None,
            "entry_range": [buy_stop, chase]}


real_plan = sizing.position_plan_v2({"price": 54.77, "pivot": 53.93, "struct_low": 50.80}, 1.0, "2026-06-29")
PLANS = {
    "2026-06-29": real_plan,                                                       # РЕАЛЕН Action план
    "2026-07-20": v2_plan("2026-07-20", 57.57, 60.45, 52.96, 66.79, 55.92),         # ХИПОТЕТИЧЕН
    "2026-09-25": v2_plan("2026-09-25", 59.72, 62.71, 54.94, 69.28, 57.95),         # ХИПОТЕТИЧЕН
    "2026-10-01": v2_plan("2026-10-01", 59.72, 62.71, 54.94, 69.28, 58.41),         # ХИПОТЕТИЧЕН
}


print("── ingest на v2 план ──")
tr = {}
backtest._ingest_action_list(tr, "2026-06-29", [{"ticker": "EXEL", "plan": real_plan}])
rec = tr["EXEL_2026-06-29"]
assert rec["method"] == "v2" and rec["status"] == "pending" and rec["entry_date"] == "2026-06-29"
assert (rec["buy_stop"], rec["max_chase"], rec["stop_loss"], rec["target_1"]) == (53.93, 56.63, 50.39, 63.53)
assert rec["signal_price"] == rec["entry_price"] == 54.77 and rec["fill_price"] is None and rec["window_sessions"] == 5
backtest._ingest_action_list(tr, "2026-06-29", [{"ticker": "EXEL", "plan": real_plan}])      # същият ключ
backtest._ingest_action_list(tr, "2026-06-30", [{"ticker": "EXEL", "plan": real_plan}])      # pending → продължение
assert list(tr) == ["EXEL_2026-06-29"]
backtest._ingest_action_list(tr, "2026-06-30", [{"ticker": "BAD", "plan": {"method": "v2", "buy_stop": 1.0}}])  # непълен
assert list(tr) == ["EXEL_2026-06-29"]
# стар (v1) план без "method" — ingest-ва се както досега (средата на entry_range)
backtest._ingest_action_list(tr, "2026-06-29", [{"ticker": "OLD", "plan": {
    "entry_range": [10.0, 10.4], "target_1": 12.0, "stop_loss": 9.0}}])
assert tr["OLD_2026-06-29"]["entry_price"] == 10.2 and "method" not in tr["OLD_2026-06-29"] and tr["OLD_2026-06-29"]["status"] == "open"
print("  ✓ v2 план → запис 'pending' с buy_stop/таван/стоп/цел; повторен ключ и 'pending' продължение се игнорират;")
print("    непълен план се пропуска; v1 план (без method) се ingest-ва както досега")
print()

print("── резолюция през yf (подменен със фикстурите) ──")
# 1) само първата сесия е налична: вход по отварянето $55.00, жива позиция
LAST_CUT["to"] = "2026-06-30"
tr = {"EXEL_2026-06-29": backtest._new_v2_record("EXEL", "2026-06-29", real_plan)}
backtest._resolve_open_positions(tr, today=dt.date(2026, 7, 1))
r = tr["EXEL_2026-06-29"]
assert (r["status"], r["fill_date"], r["fill_price"], r["entry_price"]) == ("open", "2026-06-29", 55.0, 55.0), r
assert r["resolution_date"] is None and r["realized_r"] is None and r["discovered_date"] is None
# 2) пълните барове: стоп на 12.08
LAST_CUT["to"] = None
backtest._resolve_open_positions(tr, today=TODAY)
r = tr["EXEL_2026-06-29"]
assert (r["status"], r["resolution_date"], r["exit_price"], r["realized_r"]) == ("stopped", "2026-08-12", 50.39, -1.0), r
# Track Record-ът пази сигналния close само за одит; рискът и доходността са от реалния вход $55.00
assert r["signal_price"] == 54.77 and r["entry_price"] == r["fill_price"] == 55.0
assert r["risk_per_share"] == 4.61 and r["return_pct"] == -8.38, r
assert r["discovered_date"] == "2026-10-02" and r["fill_date"] == "2026-06-29"
before = copy.deepcopy(r)
backtest._resolve_open_positions(tr, today=dt.date(2026, 10, 5))        # терминален → не се пипа
assert tr["EXEL_2026-06-29"] == before
print("  ✓ с данни до 30.06: 'open' (вход $55.00 по отварянето); с пълните: 'stopped' на 12.08 → -1.00R;")
print("    терминален запис не се преизчислява")

# 3) всички планове + смес с v1 запис
tr = {}
for d, plan in PLANS.items():
    backtest._ingest_action_list(tr, d, [{"ticker": "EXEL", "plan": plan}]) if d == "2026-06-29" else \
        tr.__setitem__(f"EXEL_{d}", backtest._new_v2_record("EXEL", d, plan))
tr["V1_EXEL"] = {"ticker": "EXEL", "entry_date": "2026-06-29", "status": "open", "entry_price": 54.0, "target_1": 63.53,
                 "stop_loss": 50.39, "target1_hit_date": None, "resolution_date": None, "discovered_date": None,
                 "realized_r": None}
backtest._resolve_open_positions(tr, today=TODAY)
st = {k: v["status"] for k, v in tr.items()}
assert st == {"EXEL_2026-06-29": "stopped", "EXEL_2026-07-20": "not_triggered", "EXEL_2026-09-25": "open",
              "EXEL_2026-10-01": "pending", "V1_EXEL": "stopped"}, st
assert tr["EXEL_2026-07-20"]["resolution_date"] == "2026-07-24" and tr["EXEL_2026-07-20"]["realized_r"] is None
assert tr["EXEL_2026-07-20"]["discovered_date"] == "2026-10-02"
o = tr["EXEL_2026-09-25"]
assert (o["fill_date"], o["fill_price"], o["entry_price"]) == ("2026-09-30", 59.72, 59.72) and o["current_r"] is not None
assert tr["V1_EXEL"]["realized_r"] == -1.0 and "method" not in tr["V1_EXEL"]                # v1 пътят е непокътнат
print("  ✓ една резолюция: 29.06 stopped · 20.07 not_triggered (до 24.07) · 25.09 open (вход $59.72 на 30.09) ·")
print("    01.10 pending · v1 записът се резолвира по старата логика (stopped, -1.0)")
print()

print("── обобщение за dashboard-а ──")
backtest._save_tracker(tr)
sm = backtest.get_backtest_summary()
assert sm["total_resolved"] == 1 and sm["wins"] == 0 and sm["losses"] == 1 and sm["win_rate_pct"] == 0.0   # само v2 (v1 записът е извън статистиката, т.7)
assert sm["stopped"] == 1 and sm["still_open"] == 1 and sm["pending"] == 1 and sm["not_triggered"] == 1
assert sm["skipped_extended"] == 0 and sm["avg_realized_r"] == -1.0
pp = sm["pending_positions"]
assert [(p["ticker"], p["entry_date"], p["buy_stop"], p["stop_loss"]) for p in pp] == [("EXEL", "2026-10-01", 59.72, 54.94)]
op = sm["open_positions"]
assert len(op) == 1 and op[0]["entry_date"] == "2026-09-30" and op[0]["signal_date"] == "2026-09-25" and op[0]["entry_price"] == 59.72
assert op[0]["unrealized_pct"] == round((float(EXEL["Close"].iloc[-1]) - 59.72) / 59.72 * 100, 1)
print("  ✓ резолвирани 1 (v1 записът е извън статистиката; not_triggered/pending не са в win rate), 1 жива с РЕАЛНАТА дата на входа (30.09,")
print("    препоръка 25.09) и цена $59.72, 1 pending в отделен списък")
print()

print("── обобщение: частична продажба (т.4) и изтичане с R (т.5) — СИНТЕТИЧНИ записи ──")
def synth(key, status, r, partial=None, **kw):
    rec = backtest._new_v2_record("EXEL", key, PLANS["2026-09-25"])
    rec.update(status=status, realized_r=r, partial_price=partial, partial_fraction=0.5 if partial else 0.0,
               fill_date=key, fill_price=100.0, resolution_date=None if r is None else key, **kw)
    return rec
backtest._save_tracker({
    "EXEL_2026-01-05": synth("2026-01-05", "stopped", 0.5, 116.0),                   # частична + стоп на остатъка
    "EXEL_2026-02-02": synth("2026-02-02", "trailing_stop_exit", 1.06, 116.0),
    "EXEL_2026-03-02": synth("2026-03-02", "stopped", -1.0),
    "EXEL_2026-05-04": synth("2026-05-04", "expired", 0.24),                          # т.5: изтекла, оценена по Close
    "EXEL_2026-04-06": synth("2026-04-06", "trailing", None, 116.0),                  # жива, след частична
})
sm2 = backtest.get_backtest_summary()
assert sm2["total_resolved"] == 4 and sm2["wins"] == 3 and sm2["losses"] == 1 and sm2["win_rate_pct"] == 75.0
assert sm2["avg_realized_r"] == 0.2 and sm2["stopped"] == 2 and sm2["stopped_after_partial"] == 1 and sm2["expired"] == 1
assert sm2["partial_taken"] == 3 and sm2["trailing"] == 1
print("  ✓ 'stopped' след частична = +0.50R (печалба по R); изтеклата позиция е със своя R (+0.24) и ВЛИЗА в статистиката:")
print("    3 от 4 резолвирани са win (75.0%), среден R +0.20; 1 стоп е след частична, 3 са минали през частична, 1 е жива")
print()

print("── OPEN✓ и COT позиции: датата на входа, не на препоръката; pending не е позиция ──")
backtest._save_tracker(tr)
assert set(brief_main._live_positions()) == {"EXEL"} and brief_main._live_positions()["EXEL"]["fill_date"] == "2026-09-30"
cand = {"ticker": "EXEL", "company": "Exelixis", "sector": "Healthcare", "price": 60.5, "pivot": 59.72, "pct_from_pivot": 1.31,
        "volume_ratio": 2.0, "breakout_volume": True, "struct_low": 57.0,
        "ai": {"classification": "Action", "why_now": "тест", "catalysts": [], "risks": []}}
action, watch = brief_main.apply_hard_rules([cand], 1.0)
assert not action and watch and watch[0]["ticker"] == "EXEL"
mk = watch[0]["markers"][0]
assert mk["tag"] == "OPEN✓" and "2026-09-30" in mk["title"] and "$59.72" in mk["title"] and "2026-09-25" not in mk["title"], mk
assert "от 2026-09-30" in watch[0]["ai"]["watchlist_trigger"]
only_pending = {k: v for k, v in tr.items() if v["status"] == "pending"}
backtest._save_tracker(only_pending)
assert brief_main._live_positions() == {}                       # pending → няма жива позиция
print("  ✓ OPEN✓: 'Отворена позиция от 2026-09-30 @ $59.72' (не от 25.09); при само pending няма жива позиция")
print()

print("── сплит на v2 запис: всички нива на плана се мащабират ──")
rec = backtest._new_v2_record("EXEL", "2026-06-29", real_plan)
closes = pd.Series([27.5, 27.2], index=pd.to_datetime(["2026-06-29", "2026-06-30"]))     # СИНТЕТИЧНО: 2:1 сплит, историята вече е в новата скала
ok = backtest._apply_split_adjustment_v2(rec, [{"date": "2026-06-29", "ratio": 2.0}], closes, dt.date(2026, 7, 1))
assert ok and rec["buy_stop"] == 26.965 and rec["max_chase"] == 28.315 and rec["signal_price"] == 27.385
assert rec["stop_loss"] == 25.195 and rec["target_1"] == 31.765 and rec["entry_price"] == 27.385
assert rec["split_adjusted"]["original"]["buy_stop"] == 53.93 and rec["split_adjusted"]["original"]["max_chase"] == 56.63
print("  ✓ 2:1 (СИНТЕТИЧНО): buy-stop 53.93 → 26.965, таван → 28.315, стоп 50.39 → 25.195, цел → 31.765; оригиналите са в одита")

print()
print("── dashboard: блокът Track Record с v2 обобщение ──")
backtest._save_tracker(tr)
sm = backtest.get_backtest_summary()
from src import render, thermometer
brief = {"date": "2026-10-02", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")),
         "action": [], "watchlist": [], "backtest": sm,
         "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
with tempfile.TemporaryDirectory() as docs:
    orig_docs = config.DOCS_DIR
    config.DOCS_DIR = pathlib.Path(docs)
    try:
        html = render.render_dashboard(brief)
    finally:
        config.DOCS_DIR = orig_docs
assert "Чакат buy-stop: 1 · не се задействаха: 1 (извън статистиката)" in html
assert "Чакат buy-stop (1):" in html and "$59.72" in html and "2026-09-30" in html
print("  ✓ 'Чакат buy-stop: 1 · не се задействаха: 1 (извън статистиката)', таблица с чакащите и отворената позиция с датата на входа")

_tmp.cleanup()
print()
print("Всички тестове минаха.")
