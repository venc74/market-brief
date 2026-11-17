"""
17.11.2026 (пакет 2, т. 3 — А6): Kullamägi — вход по картата. Пробив на нивото в първия 5-мин. бар → изчакай бара да приключи, вход при пробив над НЕГОВИЯ връх, стоп = дъното
на деня в момента на входа; без пробив над върха → без вход (status not_triggered, how "first_bar_no_break"). За записите от config.QM_FIRST_BAR_RULE_FROM; старите —
„преди правилото“; обобщението на книгата — двете отделно (backtest.qm_entry_rule_split).

РЕАЛНО: tests/fixtures/qm_intraday_2026-11-03.json.gz — 5-минутните бари на входния ден на 6-те задействани записа на книгата (03.11): SN и ELF (09.10) пробиват в
първия бар; DOCU, CBOE, UTHR, RVTY — по-късно. СИНТЕТИЧНО (означено): т. 3 — записите за обобщението; т. 4 — датата на правилото.
Пускане: python test_qm_first_bar.py
"""
import sys, json, gzip, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_qmfb_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DATA_DIR.mkdir()
from src import trade_sim, backtest

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "qm_intraday_2026-11-03.json.gz").read_bytes()).decode("utf-8"))


def b5(key):
    d = FX["bars_5m"][key]
    idx = pd.to_datetime(d["times"], utc=True).tz_convert("America/New_York")
    return pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"]}, index=idx)


REC = {r["ticker"]: r for r in FX["records"].values()}
run = lambda t, rule: trade_sim.qm_intraday_entry(b5(f"{t}_{REC[t]['fill_date']}"), float(REC[t]["buy_stop"]), first_bar_wait=rule)

print("── 1. РЕАЛНО: пробив в първия бар — SN без вход, ELF — вход над върха на първия бар ──")
sn_old, sn_new = run("SN", False), run("SN", True)
assert sn_old["entry_time"] == "09:30" and sn_new["no_entry"] and sn_new["reason"].startswith("нивото е пробито в първия 5-мин. бар")
el_old, el_new = run("ELF", False), run("ELF", True)
assert (el_old["entry_time"], el_old["fill"]) == ("09:30", 107.36) and el_new["rule"] == "first_bar_wait" and el_new["fill"] == el_new["first_bar_high"] == 108.89
assert el_new["entry_time"] == "09:50" and el_new["stop"] == 107.0
print(f"  ✓ SN: «{sn_new['reason']}»; ELF: вход {el_new['entry_time']} по ${el_new['fill']} (до 17.11 — 09:30 по $107.36), стоп ${el_new['stop']}")

print("── 2. РЕАЛНО: пробив по-късно — без промяна ──")
for t in ("DOCU", "CBOE", "UTHR", "RVTY"):
    assert run(t, True) == run(t, False), t
print("  ✓ DOCU, CBOE, UTHR, RVTY — същите вход и стоп")

print("── 3. симулацията и обобщението (СИНТЕТИЧНИ записи) ──")
idx = pd.bdate_range("2026-11-18", periods=3)
bars = pd.DataFrame({"Open": [99.0, 101, 102], "High": [102, 103, 104], "Low": [98, 100, 101], "Close": [101, 102, 103]}, index=idx)
rec = {"entry_date": "2026-11-18", "buy_stop": 100.0, "adr": 4.0, "intraday": {"no_entry": True, "date": "2026-11-18"}}
out = trade_sim.simulate_qm(rec, bars, today=pd.Timestamp("2026-11-21").date())
assert out["status"] == "not_triggered" and out["how"] == "first_bar_no_break"
recs = [{"status": "stopped", "realized_r": -1.0}, {"status": "trailing_stop_exit", "realized_r": 2.0, "entry_rule": "first_bar_wait"},
        {"status": "not_triggered", "how": "first_bar_no_break", "entry_rule": "first_bar_wait"}]
sp = backtest.qm_entry_rule_split(recs, True)
assert sp == {"преди правилото": {"records": 1, "closed": 1, "avg_r": -1.0, "no_entry": 0}, "след правилото": {"records": 2, "closed": 1, "avg_r": 2.0, "no_entry": 1}}
print("  ✓ без вход по правилото → not_triggered; обобщението — отделно преди / след")

print("── 4. новите записи носят правилото ──")
src = (ROOT / "src" / "backtest.py").read_text(encoding="utf-8")
assert '**({"entry_rule": QM_ENTRY_RULE} if entry_date >= config.QM_FIRST_BAR_RULE_FROM else {})' in src and config.QM_FIRST_BAR_RULE_FROM == "2026-11-18"
assert 'first_bar_wait=rec.get("entry_rule") == QM_ENTRY_RULE' in src
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "Пробив в първия 5-мин. бар → изчакай бара да приключи, вход над неговия връх" in tpl and "qb.get(\"entry_rule_split\")" in tpl
print("  ✓ от 18.11 — entry_rule; картата и книгата казват правилото")
print("\n✅ test_qm_first_bar: всичко мина")
