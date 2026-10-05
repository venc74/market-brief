"""
Пакет 1б (2026-10-05) · точки 1, 3, 4: Watchlist buy-stop кандидатите се записват като отделна книга ("buystop") в tracker-а — независими от Action
(дедупът е в рамките на категорията), прозорец 5 сесии, във ВСИЧКИ режими с таг на режима, със същия модел на изпълнение като Action (trade_sim).

РЕАЛНО: картата на EXPD от брифа на 05.10.2026 (tests/fixtures/brief_2026-10-05.json; под pivot, buy-stop $194.59) с планa, който изчислява
sizing.buy_stop_preview при Defensive ×0.5; реалната FTNT карта (too_wide, без buy-stop); реалните дневни барове на EXEL (tests/fixtures/ohlc_EXEL.csv, SPY).
СИНТЕТИЧНО: другите карти/тикъри (режимите Cash/Offensive, дедуп сценариите), snapshot файловете във временната data/, ХИПОТЕТИЧНИЯТ план на EXEL от 25.09
(тогава EXEL беше Watchlist под pivot — както в test_backtest_v2), подменените yf.download/сплитове/earnings.
Пускане: python test_buystop_ingest.py
"""
import sys, json, pathlib, tempfile, copy, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import backtest, sizing, trade_sim

_tmp = tempfile.TemporaryDirectory(prefix="mb_bsi_")
config.DATA_DIR = pathlib.Path(_tmp.name)
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
config.ENABLE_BACKTEST = True
backtest._unapplied_splits = lambda rec: []
backtest.enrich.earnings_recap = lambda t: None

EXEL = pd.read_csv(ROOT / "tests/fixtures/ohlc_EXEL.csv", index_col=0, parse_dates=True)
SPY = pd.read_csv(ROOT / "tests/fixtures/ohlc_SPY.csv", index_col=0, parse_dates=True)
DATA = {"EXEL": EXEL, "SPY": SPY}


def fake_download(tickers, start=None, progress=False, auto_adjust=False, **kw):
    cols = ["Open", "High", "Low", "Close", "Volume"]
    fr = {t: (DATA[t][DATA[t].index >= pd.Timestamp(start)] if start else DATA[t]) for t in tickers}
    return pd.concat({f: pd.DataFrame({t: fr[t][f] for t in tickers}) for f in cols}, axis=1)


backtest.yf.download = fake_download

BRIEF = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
CARDS = {w["ticker"]: w for w in BRIEF["watchlist"]}
EXPD, FTNT = copy.deepcopy(CARDS["EXPD"]), copy.deepcopy(CARDS["FTNT"])
EXPD["plan_preview"] = sizing.buy_stop_preview(EXPD, 0.5, "2026-10-05")
assert EXPD["plan_preview"]["valid"] and EXPD["setup"]["kind"] == "below_pivot" and FTNT["setup"]["kind"] == "too_wide" and not FTNT["setup"].get("buy_stop")


def card(ticker, buy_stop=100.0, stop=92.0, target=116.0, regime_card=None, kind="below_pivot", valid=True):
    """СИНТЕТИЧНА buy-stop карта с минималния набор полета."""
    plan = {"valid": valid, "method": "v2", "buy_stop": buy_stop, "max_chase": round(buy_stop * 1.05, 2), "stop_loss": stop, "target_1": target,
            "entry_mid": buy_stop, "window_sessions": 5, "valid_through": "2026-10-09", "preview": True}
    return {"ticker": ticker, "setup": {"kind": kind, "buy_stop": buy_stop if kind == "below_pivot" else None, "pct_from_pivot": -1.2}, "plan_preview": plan}


def fresh():
    backtest._save_tracker({})
    return {}


print("── РЕАЛНАТА карта на EXPD (05.10, Defensive ×0.5) ──")
tr = fresh()
backtest._ingest_buystop_list(tr, "2026-10-05", [EXPD, FTNT], "Defensive")
assert list(tr) == ["EXPD_2026-10-05_buystop"], list(tr)                                                         # FTNT (too_wide, без buy-stop) не влиза
r = tr["EXPD_2026-10-05_buystop"]
assert (r["method"], r["category"], r["status"], r["regime"]) == ("v2", "buystop", "pending", "Defensive")
assert (r["buy_stop"], r["stop_loss"], r["target_1"], r["max_chase"]) == (194.59, 181.53, 220.71, round(194.59 * 1.05, 2))
assert r["window_sessions"] == config.BUY_STOP_WINDOW_SESSIONS == 5 and r["valid_through"] == "2026-10-09" and r["pct_from_pivot"] == EXPD["setup"]["pct_from_pivot"]
assert r["entry_date"] == "2026-10-05" and r["fill_date"] is None and r["realized_r"] is None
print("  ✓ запис EXPD_2026-10-05_buystop: pending, buy-stop $194.59, стоп $181.53, цел 1 $220.71, таван $204.32, прозорец 5 сесии до 2026-10-09, режим Defensive;")
print("    реалната FTNT (too_wide, без buy-stop) не влиза")

print()
print("── кои карти се записват ──")
tr = fresh()
backtest._ingest_buystop_list(tr, "2026-10-06", [card("AAA"), card("BBB", valid=False), card("CCC", kind="confirmed"), {"ticker": "DDD"},
                                                 {"ticker": "EEE", "setup": {"kind": "below_pivot", "buy_stop": 50.0}},       # без plan_preview
                                                 {**card("FFF"), "plan_preview": {**card("FFF")["plan_preview"], "target_1": None}}], "Offensive")
assert sorted(r["ticker"] for r in tr.values()) == ["AAA"]
print("  ✓ СИНТЕТИЧНО: само валидна below_pivot карта с пълен план; невалиден план, друг вид сетъп, липсващ setup/plan_preview, липсващ ключ на плана — не")
config.TRACK_BUYSTOP = False
tr = fresh(); backtest._ingest_buystop_list(tr, "2026-10-06", [card("AAA")], "Offensive")
assert tr == {}
config.TRACK_BUYSTOP = True
print("  ✓ TRACK_BUYSTOP=0 изключва записа")

print()
print("── във всички режими, с таг ──")
tr = fresh()
for reg, t in (("Offensive", "OFF"), ("Defensive", "DEF"), ("Cash", "CSH"), (None, "NON")):
    backtest._ingest_buystop_list(tr, "2026-10-06", [card(t)], reg)
assert {r["ticker"]: r["regime"] for r in tr.values()} == {"OFF": "Offensive", "DEF": "Defensive", "CSH": "Cash", "NON": None}
print("  ✓ Offensive / Defensive / Cash (и липсващ режим) се записват, режимът е таг на записа")

print()
print("── независими книги: дедупът е в рамките на категорията ──")
tr = fresh()
backtest._ingest_buystop_list(tr, "2026-10-05", [card("AAA")], "Defensive")
backtest._ingest_buystop_list(tr, "2026-10-06", [card("AAA")], "Defensive")                                        # същата карта на другия ден (още чака) → същия запис
assert len(tr) == 1
act_plan = {"method": "v2", "buy_stop": 100.0, "max_chase": 105.0, "stop_loss": 92.0, "target_1": 116.0, "entry_mid": 101.0, "window_sessions": 5}
backtest._ingest_action_list(tr, "2026-10-06", [{"ticker": "AAA", "plan": act_plan}])                                # Action за същия тикър НЕ е блокиран от buy-stop записа
assert sorted((backtest.record_category(r), r["entry_date"]) for r in tr.values()) == [("action", "2026-10-06"), ("buystop", "2026-10-05")]
backtest._ingest_action_list(tr, "2026-10-07", [{"ticker": "AAA", "plan": act_plan}])                              # Action дедупът си работи вътре в Action книгата
assert sum(1 for r in tr.values() if backtest.is_action_record(r)) == 1
backtest._ingest_buystop_list(tr, "2026-10-07", [card("AAA")], "Defensive")                                        # buy-stop дедупът — вътре в buy-stop книгата
assert sum(1 for r in tr.values() if backtest.record_category(r) == "buystop") == 1
tr2 = fresh()
backtest._ingest_action_list(tr2, "2026-10-05", [{"ticker": "BBB", "plan": act_plan}])                             # обратно: жив Action запис не блокира buy-stop на същия тикър
backtest._ingest_buystop_list(tr2, "2026-10-06", [card("BBB")], "Offensive")
assert sorted(backtest.record_category(r) for r in tr2.values()) == ["action", "buystop"]
print("  ✓ AAA: buy-stop (05.10) + Action (06.10) са два записа; повторно показване на същото ниво е един запис в своята книга; обратно — жив Action не блокира buy-stop")

tr = fresh()
backtest._ingest_buystop_list(tr, "2026-10-05", [card("AAA")], "Offensive")                                        # след изтекъл прозорец: нов запис разрешен; вътре в прозореца — не
tr["AAA_2026-10-05_buystop"].update(status="not_triggered", resolution_date="2026-10-09")
backtest._ingest_buystop_list(tr, "2026-10-08", [card("AAA")], "Offensive")
assert len(tr) == 1                                                                                                # 08.10 е вътре в [05.10, 09.10] → продължение
backtest._ingest_buystop_list(tr, "2026-10-12", [card("AAA")], "Offensive")
assert sorted(tr) == ["AAA_2026-10-05_buystop", "AAA_2026-10-12_buystop"]
print("  ✓ изтекъл прозорец (not_triggered до 09.10): повторно показване на 08.10 е продължение, на 12.10 — нов запис")

print()
print("── snapshot файловете и update_backtest_tracker ──")
tr = fresh()
(config.DATA_DIR / "2026-10-05.json").write_text(json.dumps(BRIEF, ensure_ascii=False), encoding="utf-8")        # РЕАЛНИЯТ бриф от 05.10: Watchlist картите нямат plan_preview
snap6 = {"date": "2026-10-06", "action": [], "thermometer": {"regime": "Cash"}, "watchlist": [card("SNP")]}      # СИНТЕТИЧЕН snapshot с карта с plan_preview
(config.DATA_DIR / "2026-10-06.json").write_text(json.dumps(snap6, ensure_ascii=False), encoding="utf-8")
assert not any(w.get("plan_preview") for w in BRIEF["watchlist"])
backtest._resolve_open_positions = lambda tracker, today=None: None                                              # без мрежа: тук се тества само ingest
backtest.update_backtest_tracker([], "2026-10-07", [card("TOD")], "Defensive")
backtest.update_backtest_tracker([], "2026-10-07", [card("TOD")], "Defensive")                                    # идемпотентно
T = backtest._load_tracker()
assert sorted(T) == ["SNP_2026-10-06_buystop", "TOD_2026-10-07_buystop"], sorted(T)
assert T["SNP_2026-10-06_buystop"]["regime"] == "Cash" and T["TOD_2026-10-07_buystop"]["regime"] == "Defensive"
print("  ✓ РЕАЛНИЯТ snapshot от 05.10 (карти без plan_preview) не дава нищо; СИНТЕТИЧНИЯТ от 06.10 влиза с режима на snapshot-а (Cash); днешният Watchlist — с режима на деня;")
print("    втори update_backtest_tracker е идемпотентен (2 записа)")

print()
print("── същият модел на изпълнение като Action (РЕАЛНИ барове на EXEL, ХИПОТЕТИЧЕН план от 25.09) ──")
import importlib
importlib.reload(backtest)                                                                                         # връща истинската _resolve_open_positions
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
backtest.yf.download = fake_download
backtest._unapplied_splits = lambda rec: []
plan = {"valid": True, "method": "v2", "buy_stop": 59.72, "max_chase": 62.71, "stop_loss": 54.94, "target_1": 69.28, "entry_mid": 59.72,
        "window_sessions": 5, "valid_through": None, "preview": True}
tr = {}
backtest._ingest_buystop_list(tr, "2026-09-25", [{"ticker": "EXEL", "setup": {"kind": "below_pivot", "buy_stop": 59.72}, "plan_preview": plan}], "Defensive")
backtest._ingest_action_list(tr, "2026-09-25", [{"ticker": "EXEL", "plan": {k: v for k, v in plan.items() if k not in ("valid", "preview")}}])
assert len(tr) == 2
backtest._resolve_open_positions(tr, dt.date(2026, 10, 2))
b, a = tr["EXEL_2026-09-25_buystop"], tr["EXEL_2026-09-25"]
assert b["status"] == a["status"] and b["status"] not in ("pending",), (b["status"], a["status"])
for k in backtest._V2_RESULT_KEYS + ("spy_return_pct", "alpha_pct", "resolution_date", "entry_price"):
    assert b[k] == a[k], (k, b[k], a[k])
bars = EXEL.dropna(subset=["Open", "High", "Low", "Close"])
ref = trade_sim.simulate({**plan, "entry_date": "2026-09-25"}, bars, dt.date(2026, 10, 2))
assert ref["status"] == b["status"] and ref["fill_date"] == b["fill_date"] and ref["fill_price"] == b["fill_price"] and ref["realized_r"] == b["realized_r"]
print(f"  ✓ buy-stop запис и Action запис със СЪЩИЯ план дават идентичен резултат (статус {b['status']}, вход {b['fill_date']} по ${b['fill_price']}, "
      f"R {b['realized_r']}), и двата = trade_sim.simulate")

print()
print("Всички тестове минаха.")
