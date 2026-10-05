"""
Qullamaggie · чист старт: книгата qm_breakout приема записи само с дата >= config.QM_TRACK_FROM (и от snapshot-ите, и от днешния списък). Плейсхолдърът по подразбиране е 2099-01-01 — книгата не
записва нищо, докато в деня на качването (при rebase-а върху main) не се сложи истинската дата. По модела на test_buystop_start_guard.py.

РЕАЛНО: картите DOCN, CORT, CRL от скана към 02.10.2026 (tests/fixtures/qm_frames_2026-10-02.json). СИНТЕТИЧНО: датите на брифовете и snapshot файловете във временната data/ (избрани да
показват границата; реалният tracker не се пипа), режимите, избраната "дата на качването" 2026-10-15.
Пускане: python test_qm_start_guard.py
"""
import sys, json, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import qm_breakout as q, backtest

assert config.QM_TRACK_FROM == "2099-01-01"                                  # плейсхолдърът по подразбиране (без env)
_tmp = tempfile.TemporaryDirectory(prefix="mb_qmg_")
config.DATA_DIR = pathlib.Path(_tmp.name)
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
backtest._resolve_open_positions = lambda tracker, today=None: None          # без мрежа — тества се само ingest-ът

FIX = json.loads((ROOT / "tests" / "fixtures" / "qm_frames_2026-10-02.json").read_text(encoding="utf-8"))
frames = {t: pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"])) for t, d in FIX["frames"].items()}
ROWS, _ = q.scan_frames(frames, lead=FIX["lead"])
CARDS = {r["ticker"]: r for r in ROWS}
assert sorted(CARDS) == ["CORT", "CRL", "DOCN"]

print("── плейсхолдърът 2099-01-01: книгата не записва нищо ──")
tr = {}
backtest._ingest_qm_list(tr, "2026-10-05", list(CARDS.values()), "Defensive")
backtest._ingest_qm_list(tr, "2030-01-02", list(CARDS.values()), "Defensive")
assert tr == {}
backtest._save_tracker({})
(config.DATA_DIR / "2026-10-05.json").write_text(json.dumps({"date": "2026-10-05", "action": [], "watchlist": [], "thermometer": {"regime": "Defensive"}, "qm_breakout": [CARDS["DOCN"]]}), encoding="utf-8")
backtest.update_backtest_tracker([], "2026-10-06", [], "Defensive", [CARDS["CORT"]])
assert backtest._load_tracker() == {}
assert backtest.get_qm_summary()["track_from"] == "2099-01-01" and backtest.get_qm_summary()["records"] == 0
print("  ✓ реални карти на 05.10.2026 (ingest, snapshot файл, днешен списък) → нула записа; обобщението казва track_from=2099-01-01")

print()
print("── граничните дати (СИНТЕТИЧНА дата на качването 2026-10-15) ──")
config.QM_TRACK_FROM = "2026-10-15"
tr = {}
for d, t in (("2026-10-13", "DOCN"), ("2026-10-14", "CORT"), ("2026-10-15", "CRL"), ("2026-10-16", "DOCN")):
    backtest._ingest_qm_list(tr, d, [CARDS[t]], "Defensive")
assert sorted(tr) == ["CRL_2026-10-15_qm", "DOCN_2026-10-16_qm"]
print("  ✓ карти от 13.10 и 14.10 не се записват; 15.10 (деня на качването) и 16.10 — да")

print()
print("── snapshot файловете и днешният списък (update_backtest_tracker) ──")
for f in config.DATA_DIR.glob("2026-*.json"):
    f.unlink()
for d, t in (("2026-10-13", "DOCN"), ("2026-10-14", "CORT"), ("2026-10-15", "CRL")):
    snap = {"date": d, "action": [], "watchlist": [], "thermometer": {"regime": "Defensive"}, "qm_breakout": [CARDS[t]]}
    (config.DATA_DIR / f"{d}.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
backtest._save_tracker({})
backtest.update_backtest_tracker([], "2026-10-16", [], "Offensive", [CARDS["DOCN"]])
T = backtest._load_tracker()
assert sorted(T) == ["CRL_2026-10-15_qm", "DOCN_2026-10-16_qm"], sorted(T)
backtest._save_tracker({})
backtest.update_backtest_tracker([], "2026-10-14", [], "Offensive", [CARDS["CORT"]])                    # днешен списък ПРЕДИ датата (напр. ръчно пускане преди качването)
assert [k for k in backtest._load_tracker() if k.startswith("CORT_2026-10-14")] == []
S = backtest.get_qm_summary()
assert S["track_from"] == "2026-10-15"
print("  ✓ snapshot-ите от 13.10 и 14.10 не дават записи, този от 15.10 — да; днешният списък преди датата се пропуска; обобщението носи track_from")

print()
print("── изключване на guard-а ──")
config.QM_TRACK_FROM = ""
tr = {}
backtest._ingest_qm_list(tr, "2026-10-05", [CARDS["DOCN"]], "Defensive")
assert list(tr) == ["DOCN_2026-10-05_qm"]
assert backtest.get_qm_summary()["track_from"] is None
config.TRACK_QM = False                                                                                  # TRACK_QM=0 остава по-силният превключвател
tr = {}
backtest._ingest_qm_list(tr, "2026-10-05", [CARDS["DOCN"]], "Defensive")
assert tr == {}
print("  ✓ QM_TRACK_FROM='' връща записа за всички дати; TRACK_QM=0 пак изключва книгата")
print()
print("Всички тестове минаха.")
