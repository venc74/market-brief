"""
15.10.2026 · "GLB по Уиш": затворен запис без exec резултат показва "изход по отварянето на ДД.ММ — утре" вместо празното "…" (backtest.gw_exec_note).
exec изходът е по отварянето на СЛЕДВАЩАТА сесия след затварянето под линията (trade_sim.simulate_glb_wish), а брифът е преди нея — числото идва в следващия бриф.

РЕАЛНО: tests/fixtures/brief_2026-10-15.json — затворените по линията WCC, QLYS (сигнал 09.10) и ADI (сигнал 13.10) с resolution_date 14.10 и return_pct_exec null.
СИНТЕТИЧНО (маркирано): записите с липсващи данни (сесия преди днес без резултат), записът със седмица на Разпети петък.
Пускане: python test_glb_wish_exec_note.py
"""
import sys, json, pathlib, copy, re, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_gwexec_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import backtest, render

B15 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-15.json").read_text(encoding="utf-8"))
REC = B15["backtest"]["glb_wish"]["recent"]
assert [(r["ticker"], r["resolution_date"], r["return_pct_exec"]) for r in REC] == [("WCC", "2026-10-14", None), ("QLYS", "2026-10-14", None), ("ADI", "2026-10-14", None)]

print("── 1. РЕАЛНИТЕ затворени записи от 15.10 ──")
notes = [backtest.gw_exec_note(r, "2026-10-15") for r in REC]
assert notes == [{"date": "2026-10-15", "text": "изход по отварянето на 15.10 — утре"}] * 3
print("  ✓ WCC, QLYS, ADI (под линията на 14.10) → 'изход по отварянето на 15.10 — утре'")
assert backtest.gw_exec_note({**REC[0], "return_pct_exec": -4.1}, "2026-10-15") is None                       # СИНТЕТИЧНО: вече с exec резултат
assert backtest.gw_exec_note({**REC[0], "resolution_date": "2026-10-09"}, "2026-10-15")["text"] == "изход по отварянето на 12.10 — чака данни"   # СИНТЕТИЧНО
assert backtest.gw_exec_note({**REC[0], "resolution_date": "2026-04-02"}, "2026-04-06")["date"] == "2026-04-06"      # СИНТЕТИЧНО: Разпети петък 03.04 не е сесия
assert backtest.gw_exec_note({**REC[0], "resolution_date": None}, "2026-10-15") is None
print("  ✓ с резултат → нищо; сесия преди днес без резултат → 'чака данни'; Разпети петък се прескача; без дата → нищо")

print()
print("── 2. таблицата (РЕАЛНИЯТ бриф от 15.10) ──")
b = copy.deepcopy(B15)
for r, n in zip(b["backtest"]["glb_wish"]["recent"], notes):
    r["exec_note"] = n
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert page.count("изход по отварянето на 15.10 — утре") == 3
old = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(copy.deepcopy(B15)))))
assert "изход по отварянето" not in old                                                                         # стар бриф без полето — "…" както преди
print("  ✓ трите реда показват 'изход по отварянето на 15.10 — утре'; стар бриф без полето — '…' както преди")
src = (ROOT / "src" / "backtest.py").read_text(encoding="utf-8")
assert '"exec_note": gw_exec_note(r, today_iso)' in src
print("\n✅ test_glb_wish_exec_note: всичко мина")
