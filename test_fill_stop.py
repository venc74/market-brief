"""
06.11.2026 (пакет 05–06.11, т. 1, решение след прегледа): таванът за гонене остава pivot × 1.05; стопът = по-високото от структурния и 8% под РЕАЛНАТА цена на влизане — правилото на О'Нийл „7–8% под цената, на която си купил“.
На картата: „стоп: $X или 8% под цената на влизане — по-високото“. Книгите ползват реалния вход и реалния стоп; целта е 2R от реалния вход. Записите отпреди правилото пазят стопа и целта си.
Реално, WST 04.11: вход $416.46; до правилото стоп $374.43 = 10.09% риск и цел 1.32R, с правилото стоп $383.14 = 8% и цел $483.10 = 2R.

РЕАЛНО: tests/fixtures/fill_stop_2026-11-06.json (картите, записите, барите), tests/fixtures/ohlc_EXEL.csv, tests/fixtures/brief_2026-10-19.json (рамката на страницата).
СИНТЕТИЧНО (означено): записите в т. 3 и т. 5, цените в т. 2.
Очакваните стопове — сметнати на ръка тук: вход × 0.92 спрямо структурния стоп от плана.
Пускане: python test_fill_stop.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_fillstop_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import setup_rules, sizing, trade_sim, backtest, render, trade_levels

FX = json.loads((ROOT / "tests" / "fixtures" / "fill_stop_2026-11-06.json").read_text(encoding="utf-8"))
BARS = {s: pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"]}, index=pd.to_datetime(b["d"])) for s, b in FX["bars"].items()}
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
TODAY = dt.date(2026, 11, 6)
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. картата: таванът е зоната, текстът на стопа (РЕАЛНО: WST 04.11, MNST 06.11) ──")
wst = FX["wst_card"]
s = setup_rules.classify_setup(wst, dt.date(2026, 11, 4))
p = sizing.position_plan_v2(wst, 1.0, dt.date(2026, 11, 4))
assert p["max_chase"] == s["max_chase"] == 418.60 == FX["wst_plan"]["max_chase"] and "купува се до $418.60" in s["trigger_text"]
assert (p["stop_loss"], p["target_1"], p["struct_stop"], p["stop_rule"]) == (374.43, 472.11, 368.49, "fill")          # нивата при референтния вход — както досега
assert p["stop_basis"] == "стоп: $368.49 или 8% под цената на влизане — по-високото"
lv = trade_levels.for_candidate(p, wst, 1.0, "Вход")
assert lv["stop_source_text"] == p["stop_basis"]
mn = FX["mnst_card"]
sm = setup_rules.classify_setup(mn, dt.date(2026, 11, 6))
pv = sizing.buy_stop_preview({**mn, "setup": sm}, 1.0, dt.date(2026, 11, 6))
assert sm["max_chase"] == pv["max_chase"] == 51.70 and pv["struct_stop"] == 44.47 and pv["stop_basis"] == "стоп: $44.47 или 8% под цената на влизане — по-високото"
print(f"  ✓ WST: таван $418.60; „{p['stop_basis']}“; MNST: таван $51.70")

print("── 2. стопът при входа (сметнато на ръка; СИНТЕТИЧНИ цени) ──")
plan = {"stop_rule": "fill", "struct_stop": 90.0, "stop_loss": 92.0, "target_1": 116.0}
assert trade_sim.fill_stop(plan, 100.0) == (92.0, 116.0)                                    # 8% под входа е над структурния
assert trade_sim.fill_stop(plan, 95.0) == (90.0, 105.0)                                     # структурният е над 8% (87.40)
assert trade_sim.fill_stop(plan, 105.0) == (96.6, 121.8)                                    # вход нагоре — стопът и целта нагоре
assert trade_sim.fill_stop({"stop_loss": 92.0, "target_1": 116.0}, 105.0) == (92.0, 116.0)  # запис отпреди правилото — от плана
assert trade_sim.fill_stop({"stop_rule": "fill", "stop_loss": 92.0, "target_1": 116.0}, 105.0) == (92.0, 116.0)   # без структурен — от плана
print("  ✓ по-високото от структурния и 8% под входа; цел 2R от входа; без правилото — стопът и целта от плана")

print("── 3. реплеят: ANET, EXPD, WST, EXEL 29.06 (РЕАЛНИ бари) ──")
R = FX["records"]


def replay(sym, today=TODAY, bars=None):
    r = {k: v for k, v in R[sym].items() if k in ("entry_date", "buy_stop", "max_chase", "stop_loss", "target_1", "window_sessions")}
    b = BARS[sym] if bars is None else bars
    return trade_sim.simulate(r, b, today), trade_sim.simulate({**r, "stop_rule": "fill", "struct_stop": R[sym]["struct_stop"]}, b, today)


o, n = replay("WST")
assert (o["fill_price"], o["fill_risk_pct"], o["fill_target_r"]) == (416.46, 10.09, 1.32)
assert (n["fill_price"], n["fill_stop"], n["fill_target"], n["fill_risk_pct"], n["fill_target_r"]) == (416.46, 383.14, 483.10, 8.0, 2.0) and n["fill_stop"] == round(416.46 * 0.92, 2)
assert o["status"] == n["status"] == "open"
o, n = replay("EXPD")
assert (o["fill_price"], o["fill_risk_pct"], o["fill_target_r"]) == (199.77, 8.52, 1.8)
assert (n["fill_stop"], n["fill_target"], n["fill_risk_pct"], n["fill_target_r"]) == (183.79, 231.73, 8.0, 2.0) and o["status"] == n["status"] == "open" and n["fill_stop"] == round(199.77 * 0.92, 2)
o, n = replay("ANET")
assert (o["status"], o["exit_date"], o["exit_price"], o["fill_risk_pct"], o["return_pct"]) == ("stopped", "2026-10-13", 197.7, 8.21, -8.21)
assert (n["status"], n["exit_date"], n["exit_price"], n["fill_risk_pct"], n["return_pct"], n["realized_r"]) == ("stopped", "2026-10-13", 198.15, 8.0, -8.0, -1.0) and n["fill_stop"] == round(215.38 * 0.92, 2)
E = pd.read_csv(ROOT / "tests" / "fixtures" / "ohlc_EXEL.csv", index_col=0, parse_dates=True)
pe = sizing.position_plan_v2({"price": 54.77, "pivot": 53.93, "struct_low": 50.80}, 1.0, "2026-06-29")
be = dict(entry_date="2026-06-29", buy_stop=pe["buy_stop"], max_chase=pe["max_chase"], stop_loss=pe["stop_loss"], target_1=pe["target_1"], window_sessions=5)
o, n = trade_sim.simulate(be, E, "2026-10-02"), trade_sim.simulate({**be, "stop_rule": "fill", "struct_stop": pe["struct_stop"]}, E, "2026-10-02")
assert pe["max_chase"] == 56.63 and pe["struct_stop"] == 50.29
assert (o["status"], o["fill_price"], o["exit_date"], o["exit_price"], o["return_pct"]) == ("stopped", 55.0, "2026-08-12", 50.39, -8.38)
assert (n["status"], n["fill_price"], n["exit_date"], n["exit_price"], n["return_pct"], n["fill_target"]) == ("stopped", 55.0, "2026-08-12", 50.6, -8.0, 63.8) and n["fill_stop"] == round(55.0 * 0.92, 2)
print("  ✓ WST $374.43 → $383.14 (10.09% → 8%, цел 2R); EXPD $182.75 → $183.79 (8.52% → 8%); ANET $197.70 → $198.15, същият изход 13.10; EXEL $50.39 → $50.60, същият изход 12.08")

print("── 4. записът в книгата: новият — по правилото, старият — пази своето ──")
new = backtest._new_v2_record("WST", "2026-11-04", p)
assert (new["stop_rule"], new["struct_stop"], new["plan_stop_loss"], new["plan_target_1"]) == ("fill", 368.49, 374.43, 472.11)
backtest._resolve_position_v2(new, BARS["WST"], TODAY)
assert (new["stop_loss"], new["target_1"], new["fill_risk_pct"], new["fill_target_r"], new["plan_stop_loss"]) == (383.14, 483.1, 8.0, 2.0, 374.43)
again = copy.deepcopy(new)
backtest._resolve_position_v2(again, BARS["WST"], TODAY)
assert (again["stop_loss"], again["target_1"]) == (383.14, 483.1)                            # идемпотентно
old = {**R["WST"]}
backtest._resolve_position_v2(old, BARS["WST"], TODAY)
assert (old["stop_loss"], old["target_1"], old["fill_risk_pct"]) == (374.43, 472.11, 10.09) and "stop_rule" not in old
print("  ✓ новият запис: стоп $383.14, цел $483.10; повторната резолюция — същото; планът остава за проследимост; записът отпреди правилото — $374.43, риск 10.09%")

print("── 5. чакащ запис, сплит, обобщението (СИНТЕТИЧНО) ──")
pend = backtest._new_v2_record("MNST", "2026-11-06", pv)
assert pend["stop_loss"] == 45.30 and pend["status"] == "pending"                             # преди входа — стопът от картата
rec = {"method": "v2", "ticker": "X", "entry_date": "2026-06-29", "entry_price": 200.0, "stop_loss": 184.0, "target_1": 232.0, "signal_price": 200.0, "buy_stop": 198.0, "max_chase": 207.9, "struct_stop": 180.0, "plan_stop_loss": 184.0, "plan_target_1": 232.0, "stop_rule": "fill"}
closes = pd.Series([100.0, 101.0, 102.0], index=pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"]))
with q():
    ok = backtest._apply_split_adjustment_v2(rec, [{"date": "2026-06-30", "ratio": 2.0}], closes, dt.date(2026, 7, 3))
if ok:
    assert (rec["struct_stop"], rec["plan_stop_loss"], rec["plan_target_1"]) == (90.0, 92.0, 116.0)
fr = backtest.fill_risk_block([{"ticker": "A", "fill_risk_pct": 8.0, "fill_target_r": 2.0}, {"ticker": "WST", "fill_risk_pct": 10.09, "fill_target_r": 1.32}])
assert fr["n"] == 2 and fr["over"] == [{"ticker": "WST", "pct": 10.09, "target_r": 1.32}] and backtest.fill_risk_block([{"ticker": "X"}]) is None
print("  ✓ чакащ запис — стопът от картата; сплитът мащабира и структурния стоп; „Реален риск при входа“ показва старите записи над 8%")

print("── 6. страницата и имейлът ──")
c = copy.deepcopy(next(x for x in B19["watchlist"] if (x.get("setup") or {}).get("buy_stop") or True))
card = {**copy.deepcopy(c), "ticker": "MNST", "setup": {**sm}, "plan_preview": pv, "levels": trade_levels.for_candidate(pv, mn, 1.0, "Вход (buy-stop)"), "price": mn["price"], "pivot": mn["pivot"], "pct_from_pivot": mn.get("pct_from_pivot") or -2.9}
b = copy.deepcopy(B19); b["watchlist"] = [card]; b["action"] = []
with q():
    page, mail = render.render_dashboard(b, publish=False), render.render_email(b)
T = "Стоп: $44.47 или 8% под цената на влизане — по-високото"
assert T in page and T in mail and "таван за вход $51.70" in page and "таван $51.70" in mail and "източник на стопа: стоп:" not in page
assert "max_chase_by_risk" not in (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
print(f"  ✓ „{T}“ на картата и в имейла; таванът — $51.70")
print("\n✅ test_fill_stop: всичко мина")
