"""
19.11.2026 (пакет 19.11, т. 6): книгата на Kullamägi — ЕДИН запис на тикър, докато прозорецът му е отворен. До 19.11 всеки ден с карта (входът е валиден една сесия) правеше нов
запис: CORT 5 поредни дни, IDXX / J / R по 3 … От config.QM_ONE_RECORD_FROM (20.11) новият ден се добавя към прозореца на записа от предишната сесия без вход (window_days, нивото
се обновява), а резолюцията минава ден по ден (backtest._resolve_qm_window). Старите дубликати — отбелязани (duplicate_of), не изтрити, извън статистиката.

РЕАЛНО: tests/fixtures/qm_book_2026-11-19.json — всичките 42 записа на книгата qm_breakout към 19.11 (дословно). СИНТЕТИЧНО (означено): картите в т. 2, дневните бари в т. 3.
Пускане: python test_qm_one_record.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_qm1_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import pandas as pd
from src import backtest

REC = json.loads((ROOT / "tests" / "fixtures" / "qm_book_2026-11-19.json").read_text(encoding="utf-8"))["records"]
assert len(REC) == 42

print("── 1. РЕАЛНО: старите дубликати — 13 в 42, отбелязани, не изтрити ──")
tr = copy.deepcopy(REC)
assert backtest.mark_qm_duplicates(tr, "2026-11-19") == 13 and backtest.mark_qm_duplicates(tr, "2026-11-19") == 0 and len(tr) == 42
dup = {k: r["duplicate_of"] for k, r in tr.items() if r.get("duplicate_of")}
assert dup["CORT_2026-10-08_qm"] == "CORT_2026-10-14_qm" and sum(1 for v in dup.values() if v == "CORT_2026-10-14_qm") == 4
assert dup["SN_2026-10-08_qm"] == "SN_2026-10-09_qm" and "SN_2026-10-12_qm" not in dup                     # SN: входът на 09.10 е каноничният; 12.10 — нова поредица след стопа
assert dup["IDXX_2026-11-18_qm"] == "IDXX_2026-11-19_qm" and "ELF_2026-10-29_qm" not in dup and "ELF_2026-10-09_qm" not in dup
print(f"  ✓ 13: {', '.join(sorted(k.rsplit('_', 1)[0] for k in dup))}")

print("── 2. СИНТЕТИЧНО: картата и на следващия ден — същият запис, новото ниво ──")
config.QM_ONE_RECORD_FROM = "2026-11-19"
t2 = {"IDXX_2026-11-19_qm": dict(copy.deepcopy(REC["IDXX_2026-11-19_qm"]), status="not_triggered")}
card = lambda lvl: {"ticker": "IDXX", "trigger": lvl, "adr": 2.4, "close": 700.0, "expected_stop": 690.0, "max_stop": 680.0}
backtest._ingest_qm_list(t2, "2026-11-20", [card(712.5)], "Defensive")
assert list(t2) == ["IDXX_2026-11-19_qm"]
r = t2["IDXX_2026-11-19_qm"]
assert [d["date"] for d in r["window_days"]] == ["2026-11-19", "2026-11-20"] and r["status"] == "pending" and r["valid_through"] == "2026-11-20"
assert r["buy_stop"] == 713.11 and r["buy_stop_today"] == 712.5                                            # 20.11.2026 (т. 4): записът пази първоначалното ниво
backtest._ingest_qm_list(t2, "2026-11-20", [card(712.5)], "Defensive")                                    # повторно — без промяна
assert len(r["window_days"]) == 2
r.update(status="not_triggered", resolution_date="2026-11-20")                                             # прозорецът се е затворил без вход
backtest._ingest_qm_list(t2, "2026-11-25", [card(711.0)], "Defensive")                                    # прекъсване (23–24.11 без карта) — нов запис
assert "IDXX_2026-11-25_qm" in t2 and t2["IDXX_2026-11-25_qm"]["window_days"] == [{"date": "2026-11-25", "buy_stop": 711.0}]
print("  ✓ 19.11 + 20.11 → един запис (ниво $713.11 пази, днес $712.5); повторно — без промяна; след прекъсване — нов запис")

print("── 3. СИНТЕТИЧНО: резолюцията ден по ден — вход във втория ден ──")
config.QM_FIRST_BAR_RULE_FROM = "2099-01-01"; config.QM_INTRADAY_MAX_DAYS = 0                             # дневната симулация (без 5-минутни бари — без мрежа)
ix = pd.to_datetime(["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24"])
bars = {"Open": [700, 705, 708, 716, 718], "High": [706, 711, 716, 720, 722], "Low": [698, 701, 706, 712, 714], "Close": [704, 709, 715, 718, 720]}
df = lambda k: pd.DataFrame({"IDXX": bars[k]}, index=ix)
rec = {"method": "v2", "category": backtest.CATEGORY_QM, "ticker": "IDXX", "entry_date": "2026-11-19", "status": "pending", "adr": 2.4, "signal_price": 709.0,
       "window_days": [{"date": "2026-11-19", "buy_stop": 713.11}, {"date": "2026-11-20", "buy_stop": 712.5}], "buy_stop": 712.5, "valid_through": "2026-11-20"}
rec.update({k: None for k in backtest._QM_RESULT_KEYS if k != "status"})
backtest._resolve_qm_record(rec, df("Open"), df("High"), df("Low"), df("Close"), None, pd.Timestamp("2026-11-25").date())
assert rec["fill_date"] == "2026-11-20" and rec["fill_price"] == 712.5 and rec["fill_window_day"] == "2026-11-20", {k: rec.get(k) for k in ("status", "fill_date", "fill_price")}
one = dict(rec, window_days=[{"date": "2026-11-19", "buy_stop": 713.11}])
one.update({k: None for k in backtest._QM_RESULT_KEYS if k != "status"}); one["status"] = "pending"
backtest._resolve_qm_record(one, df("Open"), df("High"), df("Low"), df("Close"), None, pd.Timestamp("2026-11-25").date())
assert one["status"] == "not_triggered"                                                                   # само 19.11 (High 711 < 713.11)
print(f"  ✓ 19.11 без вход (High 711 < 713.11), 20.11 — вход по $712.5; статус {rec['status']}")

print("── 4. обобщението — дубликатите извън статистиката ──")
orig = backtest._load_tracker
backtest._load_tracker = lambda *a, **k: tr
try:
    with contextlib.redirect_stdout(io.StringIO()):
        s = backtest.get_qm_summary()
finally:
    backtest._load_tracker = orig
assert s["duplicates"] == 13 and len(s["duplicate_rows"]) == 13 and s["records"] == 42 - 13 - s["before_rule"], (s["records"], s["before_rule"])
print(f"  ✓ записи в статистиката {s['records']} (42 − 13 дубликата − {s['before_rule']} отпреди правилото за 1×ADR)")
print("\n✅ test_qm_one_record: всичко мина")
