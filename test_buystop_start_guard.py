"""
Пакет 1б (06.10.2026) · чист старт: buy-stop записи само от config.BUYSTOP_TRACK_FROM (по подразбиране 2026-10-07, първият бриф с кода на 1б) нататък — без ретроактивни записи от
понеделник/вторник (след качването на пакет 2 snapshot-ите на тези дни вече носят plan_preview и иначе биха влезли при първото пускане).

РЕАЛНО: само значението на guard-а — РЕАЛНИЯТ snapshot от 05.10 (tests/fixtures/brief_2026-10-05.json) няма plan_preview в Watchlist картите, затова не дава записи и без guard.
СИНТЕТИЧНО: картите, snapshot файловете за 05.10, 06.10, 07.10, 08.10 във временната data/ (така ще изглеждат снапшотите на дните след качването на пакет 2), режимите. (Датата по подразбиране е 2026-10-07 от 06.10; преди това беше 08.10.)
Пускане: python test_buystop_start_guard.py
"""
import sys, json, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import backtest

assert config.BUYSTOP_TRACK_FROM == "2026-10-07"                          # стойността по подразбиране (без env)
_tmp = tempfile.TemporaryDirectory(prefix="mb_bsg_")
config.DATA_DIR = pathlib.Path(_tmp.name)
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
backtest._resolve_open_positions = lambda tracker, today=None: None       # без мрежа — тества се само ingest-ът


def card(ticker):
    plan = {"valid": True, "method": "v2", "buy_stop": 100.0, "max_chase": 105.0, "stop_loss": 92.0, "target_1": 116.0, "entry_mid": 100.0,
            "window_sessions": 5, "valid_through": None, "preview": True}
    return {"ticker": ticker, "setup": {"kind": "below_pivot", "buy_stop": 100.0, "pct_from_pivot": -1.0}, "plan_preview": plan}


print("── граничните дати ──")
tr = {}
for d in ("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"):
    backtest._ingest_buystop_list(tr, d, [card("T" + d[-2:])], "Defensive")
assert sorted(tr) == ["T07_2026-10-07_buystop", "T08_2026-10-08_buystop"]
print("  ✓ карти от 05.10 и 06.10 (понеделник/вторник) не се записват; 07.10 (първият бриф с кода на 1б) и 08.10 — да")

print()
print("── snapshot файловете и днешният Watchlist (update_backtest_tracker) ──")
for d in ("2026-10-05", "2026-10-06", "2026-10-07"):
    snap = {"date": d, "action": [], "thermometer": {"regime": "Defensive"}, "watchlist": [card("S" + d[-2:])]}
    (config.DATA_DIR / f"{d}.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
backtest._save_tracker({})
backtest.update_backtest_tracker([], "2026-10-08", [card("TOD")], "Offensive")
T = backtest._load_tracker()
assert sorted(T) == ["S07_2026-10-07_buystop", "TOD_2026-10-08_buystop"], sorted(T)
backtest._save_tracker({})
backtest.update_backtest_tracker([], "2026-10-06", [card("OLD")], "Offensive")                             # днешен Watchlist ПРЕДИ датата (напр. ръчно пускане преди качването)
assert [k for k in backtest._load_tracker() if k.startswith("OLD")] == []
print("  ✓ snapshot-ите от 05.10 и 06.10 не дават записи, този от 07.10 — да; днешният Watchlist преди датата се пропуска")

print()
print("── изключване на guard-а ──")
config.BUYSTOP_TRACK_FROM = ""
tr = {}
backtest._ingest_buystop_list(tr, "2026-10-05", [card("OLD")], "Defensive")
assert list(tr) == ["OLD_2026-10-05_buystop"]
print("  ✓ BUYSTOP_TRACK_FROM='' връща записа за всички дати")
print()
print("Всички тестове минаха.")
