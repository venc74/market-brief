"""
06.11.2026 (пакет 05–06.11, т. 1): таванът за гонене = по-ниското от (pivot × 1.05) и (стоп / 0.92), т.е. рискът при вход до тавана е ≤ 8%. WST 04.11: стоп $374.43 → таван $406.99, а картата
позволяваше $418.60 (вход на отварянето $416.46 = 10.1% риск, цел 1.3R). Зоната pivot +5% остава границата за "extended" — класификацията не се променя. В книгите се пази реалният риск при
изпълнението (fill_risk_pct, fill_target_r); записите отпреди правилото пазят своя таван.

РЕАЛНО: tests/fixtures/chase_cap_2026-11-06.json — картите на WST (04.11) и MNST (06.11), записът на WST, дневните бари на WST от Yahoo. tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): пивотите в т. 4 (закръгляне), записите в т. 3 (без WST).
Пускане: python test_chase_cap.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_chasecap_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import setup_rules, sizing, trade_sim, backtest, render

FX = json.loads((ROOT / "tests" / "fixtures" / "chase_cap_2026-11-06.json").read_text(encoding="utf-8"))
B = FX["bars"]
BARS = pd.DataFrame({"Open": B["o"], "High": B["h"], "Low": B["l"], "Close": B["c"]}, index=pd.to_datetime(B["d"]))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))

print("── 1. WST 04.11 (РЕАЛНО): стоп $374.43 → таван $406.99, не $418.60 ──")
wst = FX["wst_card"]
s = setup_rules.classify_setup(wst, dt.date(2026, 11, 4))
p = sizing.position_plan_v2(wst, 1.0, dt.date(2026, 11, 4))
assert FX["wst_plan"]["max_chase"] == 418.60 == setup_rules.max_chase(wst["pivot"])              # старият таван — зоната
assert p["stop_loss"] == s["stop"] == 374.43 and p["max_chase"] == s["max_chase"] == 406.99 and p["max_chase_by_risk"] and s["max_chase_by_risk"]
assert s["kind"] == "confirmed" and "купува се до $406.99" in s["trigger_text"]                  # класификацията е същата, текстът — новият таван
assert (p["max_chase"] - p["stop_loss"]) / p["max_chase"] * 100 <= 8.001
rec = {**FX["wst_record"]}
old = trade_sim.simulate(rec, BARS, dt.date(2026, 11, 6))
assert (old["status"], old["fill_date"], old["fill_price"]) == ("stopped" if old["status"] == "stopped" else old["status"], "2026-11-04", 416.46)
assert old["fill_risk_pct"] == 10.09 and old["fill_target_r"] == 1.32                            # реалният риск и целта от реалния вход
new = trade_sim.simulate({**rec, "max_chase": p["max_chase"]}, BARS, dt.date(2026, 11, 6))
assert new["status"] == "skipped_extended" and new["fill_price"] is None                         # по новия таван отварянето $416.46 не се гони
print(f"  ✓ таван $406.99 (риск ≤ 8%); старият запис: вход $416.46 — риск {old['fill_risk_pct']}%, цел {old['fill_target_r']}R; по новия таван — skipped_extended; kind остава confirmed")

print("── 2. MNST 06.11 и зоната (РЕАЛНО) ──")
mn = FX["mnst_card"]
sm = setup_rules.classify_setup(mn, dt.date(2026, 11, 6))
assert sm["kind"] == "below_pivot" and FX["mnst_plan"]["max_chase"] == 51.70 and sm["max_chase"] == 49.24 == mn["pivot"]    # стопът е на тавана 8% от pivot → вход само на самото ниво
pv = sizing.buy_stop_preview({**mn, "setup": sm}, 1.0, dt.date(2026, 11, 6))
assert pv["max_chase"] == sm["max_chase"] and pv["stop_loss"] == 45.30                           # картата и записът в книгата — едно и също
assert setup_rules.max_chase(100.0) == 105.0 and setup_rules.max_chase(100.0, 99.0) == 105.0     # СИНТЕТИЧНО: тесен стоп — остава зоната
print(f"  ✓ MNST: стоп $45.30 → таван $49.24 = нивото (при гап над него няма вход); тесен стоп — таванът остава pivot +5%")

print("── 3. книгата: попълване без мрежа, обобщение, страницата ──")
trk = {"WST_2026-11-04": {**FX["wst_record"], "status": "open"},
       "AAA_2026-10-01": {"method": "v2", "ticker": "AAA", "entry_date": "2026-10-01", "status": "stopped", "fill_price": 100.0, "stop_loss": 94.0, "target_1": 112.0},     # СИНТЕТИЧНО: затворен
       "BBB_2026-10-01": {"method": "v2", "ticker": "BBB", "entry_date": "2026-10-01", "status": "pending", "fill_price": None, "stop_loss": 94.0, "target_1": 112.0}}      # СИНТЕТИЧНО: без вход
assert backtest.backfill_fill_risk(trk) == 2 and backtest.backfill_fill_risk(trk) == 0           # идемпотентно
assert trk["AAA_2026-10-01"]["fill_risk_pct"] == 6.0 and trk["AAA_2026-10-01"]["fill_target_r"] == 2.0 and "fill_risk_pct" not in trk["BBB_2026-10-01"]
fr = backtest.fill_risk_block(list(trk.values()))
assert fr["n"] == 2 and abs(fr["avg"] - 8.045) < 0.01 and fr["over"] == [{"ticker": "WST", "pct": 10.09, "target_r": 1.32}]
assert backtest.fill_risk_block([{"ticker": "X"}]) is None
b = copy.deepcopy(B19)
b.setdefault("backtest", {}).update(fill_risk=fr, open_positions=[{"ticker": "WST", "entry_date": "2026-11-04", "entry_price": 416.46, "current_price": 392.0, "unrealized_pct": -5.9, "fill_risk_pct": 10.09, "fill_target_r": 1.32}])
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
assert "(2 входа) · над 8%: <b>WST</b> 10.1% (цел 1.3R)." in page and "Реален риск при входа: средно 8." in page
assert "риск 10.1% · цел 1.3R" in page
print("  ✓ реалният риск се пази и за затворените; ред в книгата „Реален риск при входа … над 8%: WST 10.1% (цел 1.3R)“; в таблицата с отворените — до входа")

print("── 4. закръглянето не сваля тавана под pivot (СИНТЕТИЧНО) ──")
bad = 0
for k in range(1000, 60000, 7):
    pv_ = k / 100
    st = setup_rules.stop_levels(pv_ * 0.5, pv_)                                                  # широк структурен стоп → стопът е на тавана 8%
    cap = setup_rules.max_chase(pv_, st["stop"])
    bad += not (round(pv_, 2) <= cap <= setup_rules.max_chase(pv_))
assert bad == 0
print("  ✓ при стоп на тавана 8%: pivot ≤ таван ≤ pivot +5% за всички проби")
print("\n✅ test_chase_cap: всичко мина")
