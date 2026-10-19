"""
15.10.2026 · "GLB по Уиш": затворен запис без exec резултат показва "изход по отварянето на ДД.ММ — днес" вместо празното "…" (backtest.gw_exec_note).
exec изходът е по отварянето на СЛЕДВАЩАТА сесия след затварянето под линията (trade_sim.simulate_glb_wish), а брифът е преди нея — числото идва в следващия бриф.
19.10.2026 (етап 2, т. 1): сесията ДНЕС е "днес", не "утре" (до 19.10 тестът твърдеше "утре" за 15.10 в брифа от 15.10); "утре" — само за сесия след деня на брифа.

РЕАЛНО: tests/fixtures/brief_2026-10-15.json — затворените по линията WCC, QLYS (сигнал 09.10) и ADI (сигнал 13.10) с resolution_date 14.10 и return_pct_exec null;
tests/fixtures/brief_2026-10-19.json — PLTR, MSFT, A под линията в петък 16.10 → изход по отварянето в понеделник 19.10 (в брифа: "— утре").
СИНТЕТИЧНО (маркирано): записите с липсващи данни (сесия преди днес без резултат), записът със седмица на Разпети петък, сесия след деня на брифа.
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
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
REC = B15["backtest"]["glb_wish"]["recent"]
assert [(r["ticker"], r["resolution_date"], r["return_pct_exec"]) for r in REC] == [("WCC", "2026-10-14", None), ("QLYS", "2026-10-14", None), ("ADI", "2026-10-14", None)]

print("── 1. РЕАЛНИТЕ затворени записи от 15.10 ──")
notes = [backtest.gw_exec_note(r, "2026-10-15") for r in REC]
assert notes == [{"date": "2026-10-15", "text": "изход по отварянето на 15.10 — днес"}] * 3                     # брифът е ПРЕДИ отварянето на 15.10
print("  ✓ WCC, QLYS, ADI (под линията на 14.10) → 'изход по отварянето на 15.10 — днес' (до 19.10: '— утре')")
R19 = B19["backtest"]["glb_wish"]["recent"]
assert [(r["ticker"], r["resolution_date"], r["exec_note"]["text"]) for r in R19[:3]] == [(t, "2026-10-16", "изход по отварянето на 19.10 — утре") for t in ("PLTR", "MSFT", "A")]   # какво пишеше брифът
assert [backtest.gw_exec_note(r, "2026-10-19") for r in R19[:3]] == [{"date": "2026-10-19", "text": "изход по отварянето на 19.10 — днес"}] * 3
print("  ✓ 19.10: PLTR, MSFT, A (под линията в петък 16.10) → 'изход по отварянето на 19.10 — днес' (в брифа: '— утре')")
assert backtest.gw_exec_note({**REC[0], "resolution_date": "2026-10-15"}, "2026-10-15")["text"] == "изход по отварянето на 16.10 — утре"   # СИНТЕТИЧНО: сесия след деня на брифа
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
assert page.count("изход по отварянето на 15.10 — днес") == 3
old = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(copy.deepcopy(B15)))))
assert "изход по отварянето" not in old                                                                         # стар бриф без полето — "…" както преди
print("  ✓ трите реда показват 'изход по отварянето на 15.10 — днес'; стар бриф без полето — '…' както преди")
src = (ROOT / "src" / "backtest.py").read_text(encoding="utf-8")
assert '"exec_note": gw_exec_note(r, today_iso)' in src
print("\n✅ test_glb_wish_exec_note: всичко мина")
