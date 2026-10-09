"""
Книга qm_breakout · записите "преди правилото" (09.10.2026). Правилото "нивото най-много QM_MAX_DIST_ADR (1) × ADR над затварянето" влезе вечерта на 08.10, след скана, който записа SANM (1.27 ADR) и SITM (1.81 ADR). Те се
пазят в tracker-а, но са извън статистиката на книгата (броят, процентите, средните) и се показват в отделен ред с причина. Не се трие нищо и не се променя запис.

РЕАЛНО: tests/fixtures/qm_book_records_2026-10-09.json — седемте записа на книгата от data/backtest_tracker.json на origin/main след брифа от 09.10 (четири от 08.10: SN, SANM, SITM, CORT — всичките приключили "не се
задействаха"; три от 09.10: SN, ELF, CORT — чакащи). СИНТЕТИЧНО (маркирано): граничните стойности на разстоянието и датата, записи с липсващи полета.
Пускане: python test_qm_before_rule.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import backtest, render

tmp = tempfile.TemporaryDirectory(prefix="mb_qmrule_")
config.DATA_DIR = pathlib.Path(tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
config.ENABLE_BACKTEST = True
config.QM_TRACK_FROM = ""

REAL = json.loads((ROOT / "tests" / "fixtures" / "qm_book_records_2026-10-09.json").read_text(encoding="utf-8"))["records"]
assert config.QM_MAX_DIST_ADR == 1.0 and config.QM_MAX_DIST_RULE_FROM == "2026-10-09"
assert sorted(REAL) == ["CORT_2026-10-08_qm", "CORT_2026-10-09_qm", "ELF_2026-10-09_qm", "SANM_2026-10-08_qm", "SITM_2026-10-08_qm", "SN_2026-10-08_qm", "SN_2026-10-09_qm"]

print("── 1. разстоянието до нивото, смятано от съхранените полета (РЕАЛНИ записи) ──")
def dist(r):
    return round((r["buy_stop"] / r["signal_price"] - 1) * 100 / r["adr"], 2)                  # независимо от кода: същата формула като на картата («до нивото: X ADR»)
exp = {k: dist(r) for k, r in REAL.items()}
print("  разстояния до нивото (ADR):", ", ".join(f"{k.split('_')[0]} {k.split('_')[1][8:10]}.{k.split('_')[1][5:7]} = {v}" for k, v in sorted(exp.items(), key=lambda x: (x[0].split("_")[1], x[0]))))
for k, r in REAL.items():
    got = backtest.qm_before_rule(r)
    if r["entry_date"] < "2026-10-09" and exp[k] > 1.0:
        assert got == exp[k], (k, got, exp[k])
    else:
        assert got is None, (k, got)
assert {k for k, r in REAL.items() if backtest.qm_before_rule(r) is not None} == {"SANM_2026-10-08_qm", "SITM_2026-10-08_qm"} and exp["SANM_2026-10-08_qm"] == 1.27 and exp["SITM_2026-10-08_qm"] == 1.81
print("  ✓ «преди правилото» са точно SANM (1.27 ADR) и SITM (1.81 ADR); SN (0.17), CORT (0.54) от 08.10 и записите от 09.10 (0.22, 0.25, 0.73) са в границата")

print()
print("── 2. обобщението: извън статистиката, но не изтрити ──")
backtest._save_tracker(copy.deepcopy(REAL))
S = backtest.get_qm_summary()
assert S["records"] == 5 and S["pending"] == 3 and S["not_triggered"] == 2 and S["open"] == 0 and S["closed"] == 0, S
assert S["not_triggered_pct"] == 100.0 and S["by_regime"] == {"Defensive": {"records": 5, "closed": 0, "avg_r": None}}
assert S["before_rule"] == 2 and [(r["ticker"], r["entry_date"], r["status"], r["dist_adr"]) for r in S["before_rule_rows"]] == [("SANM", "2026-10-08", "not_triggered", 1.27), ("SITM", "2026-10-08", "not_triggered", 1.81)]
assert S["max_dist_adr"] == 1.0 and S["rule_from"] == "2026-10-09"
assert json.loads(backtest._TRACKER_PATH.read_text(encoding="utf-8")) == REAL                    # нищо не е изтрито или променено в tracker-а
print("  ✓ 7 записа в tracker-а → в статистиката 5 (SN ×2, CORT ×2, ELF): чакащи 3, не се задействаха 2 (SN, CORT от 08.10), 100% от приключилите прозорци; SANM и SITM — отделен ред; файлът е непроменен")
config.QM_MAX_DIST_RULE_FROM = ""
S_all = backtest.get_qm_summary()
assert S_all["records"] == 7 and S_all["not_triggered"] == 4 and S_all["before_rule"] == 0
config.QM_MAX_DIST_RULE_FROM = "2026-10-09"
print("  ✓ QM_MAX_DIST_RULE_FROM='' връща всичките 7 в статистиката (4 не се задействаха)")

print()
print("── 3. граници (СИНТЕТИЧНИ) ──")
base = copy.deepcopy(REAL["SANM_2026-10-08_qm"])
assert backtest.qm_before_rule({**base, "entry_date": "2026-10-09"}) is None                     # от датата на правилото нататък не се изключва
assert backtest.qm_before_rule({**base, "entry_date": "2026-10-08"}) == 1.27
edge = {**base, "buy_stop": base["signal_price"] * (1 + base["adr"] / 100)}                       # точно 1.00 ADR → в границата
assert backtest.qm_before_rule(edge) is None
assert backtest.qm_before_rule({**base, "buy_stop": base["signal_price"] * (1 + 1.01 * base["adr"] / 100)}) == 1.01
for bad in ({**base, "signal_price": None}, {**base, "adr": 0}, {**base, "buy_stop": "x"}, {k: v for k, v in base.items() if k != "adr"}, {**base, "entry_date": None}):
    assert backtest.qm_before_rule(bad) is None
print("  ✓ на датата на правилото и след нея — не; точно 1.00 ADR — в границата, 1.01 — навън; липсващо/невалидно поле → не се изключва нищо по догадка")

print()
print("── 4. страницата ──")
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B05); b.setdefault("backtest", {})["qm_breakout"] = S
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b)
i = page.index("Извън статистиката:"); seg = page[i:i + 700]
txt = " ".join(__import__("re").sub(r"<[^>]+>", "", seg).split())
assert "2 запис(а) от преди правилото" in txt and "SANM (08.10, 1.27 ADR до нивото, не се задейства)" in txt and "SITM (08.10, 1.81 ADR до нивото, не се задейства)" in txt and "не влизат в броя, процентите и средните" in txt
print("  ✓ " + txt[:330] + "…")
old_summary = {k: v for k, v in S.items() if k not in ("before_rule", "before_rule_rows", "max_dist_adr", "rule_from")}
b2 = copy.deepcopy(B05); b2.setdefault("backtest", {})["qm_breakout"] = old_summary
with contextlib.redirect_stdout(io.StringIO()):
    page2 = render.render_dashboard(b2)
assert "Извън статистиката:" not in page2
print("  ✓ обобщение без новите ключове (стар бриф) се рендерира без реда")
print("\n✅ test_qm_before_rule: всичко мина")
