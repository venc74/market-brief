"""
Пакет 1б (2026-10-05) · точка 1 (отметката): редът на buy-stop книгата носи "и Action", когато тикърът е и в Action книгата — интервалите
[entry_date, resolution_date | ∞) на двата записа се застъпват. Книгите остават независими: отметката не слива статистиките и не сменя броя.

РЕАЛНО: само причината — реплеят 02.01.2024–01.10.2026 показа, че 65% от Action записите (282 от 432) вече имат по-ранен buy-stop вход на същия тикър,
а 25% от задействаните buy-stop записи по-късно стават Action. СИНТЕТИЧНО: всички записи на tracker-а (тикъри A1…) и датите им, подменената директория data/.
Пускане: python test_buystop_also_action.py
"""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import backtest

_tmp = tempfile.TemporaryDirectory(prefix="mb_bsa_")
config.DATA_DIR = pathlib.Path(_tmp.name)
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
backtest.yf.download = lambda *a, **k: (_ for _ in ()).throw(AssertionError("без мрежа"))


def rec(ticker, entry, status, res=None, category=None):
    d = {"method": "v2", "ticker": ticker, "entry_date": entry, "status": status, "buy_stop": 100.0, "max_chase": 105.0, "stop_loss": 92.0,
         "target_1": 116.0, "valid_through": None, "fill_date": None if status in ("pending", "not_triggered", "skipped_extended") else entry,
         "fill_price": 100.0, "realized_r": -1.0 if status == "stopped" else None, "current_r": None, "resolution_date": res, "regime": "Defensive"}
    if category:
        d["category"] = category
    return f"{ticker}_{entry}_{category or 'a'}", d


# (тикър, buy-stop запис, Action запис, очаквана отметка, защо)
CASES = [
    ("A1", ("2026-09-10", "open", None), ("2026-09-11", "pending", None), True, "Action се появява на другия ден, buy-stop още е жив"),
    ("A2", ("2026-09-10", "stopped", "2026-09-15"), ("2026-09-20", "open", None), False, "Action започва СЛЕД като buy-stop записът е приключил"),
    ("A3", ("2026-09-20", "open", None), ("2026-09-01", "stopped", "2026-09-10"), False, "Action е приключил ПРЕДИ buy-stop записът да започне"),
    ("A4", ("2026-09-20", "open", None), ("2026-09-01", "open", None), True, "Action е жив, когато buy-stop записът започва"),
    ("A5", ("2026-09-10", "open", None), ("2026-09-12", "not_triggered", "2026-09-18"), False, "Action записът никога не е станал позиция"),
    ("A6", ("2026-09-10", "pending", None), ("2026-09-13", "open", None), True, "buy-stop още чака, а Action в същия прозорец вече е позиция"),
    ("A7", ("2026-09-10", "stopped", "2026-09-15"), ("2026-09-15", "open", None), True, "граница: Action започва в деня на резолюцията (включително)"),
    ("A8", ("2026-09-10", "stopped", "2026-09-15"), ("2026-09-16", "open", None), False, "граница: Action започва деня СЛЕД резолюцията"),
    ("A9", ("2026-09-10", "open", None), ("2026-09-11", "skipped_extended", "2026-09-12"), False, "Action над тавана за вход — не е позиция"),
]
items = {}
for t, (be, bs, br), (ae, as_, ar), want, why in CASES:
    k, v = rec(t, be, bs, br, "buystop"); items[k] = v
    k, v = rec(t, ae, as_, ar); items[k] = v
k, v = rec("B1", "2026-09-10", "open", None, "buystop"); items[k] = v                                        # няма Action за този тикър
k, v = rec("Z9", "2026-09-10", "open", None); items[k] = v                                                    # Action без buy-stop — не се появява в книгата
backtest._save_tracker(items)

S = backtest.get_buystop_summary()
rows = {x["ticker"]: x for x in S["live"] + S["recent"]}
print("── отметката по случаи (СИНТЕТИЧНИ интервали) ──")
for t, b, a, want, why in CASES + [("B1", None, None, False, "няма Action за този тикър")]:
    assert rows[t]["also_action"] is want, (t, rows[t]["also_action"], want, why)
    print(f"  ✓ {t}: {'и Action' if want else 'без отметка':<12} — {why}")
assert "Z9" not in rows and S["records"] == len(CASES) + 1
assert S["also_action"] == sum(1 for c in CASES if c[3]) == 4
print()
print("  ✓ обобщението: 4 записа с отметка от общо", S["records"], "— отметката не променя броя; Action записите не влизат в книгата")

print()
print("── книгите си остават независими ──")
import copy
before = {k: v for k, v in S.items() if k not in ("live", "recent", "also_action")}
only_buystop = {k: v for k, v in items.items() if v.get("category") == "buystop"}
backtest._save_tracker(only_buystop)                                                                           # същите buy-stop записи БЕЗ Action книгата
S2 = backtest.get_buystop_summary()
assert S2["also_action"] == 0 and {k: v for k, v in S2.items() if k not in ("live", "recent", "also_action")} == before
print("  ✓ без Action записите броят, среден R, прозорци и режими са същите — отметката е само показване")

print()
print("Всички тестове минаха.")
