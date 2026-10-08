"""
Пакет 1б (2026-10-05) · точка 6: четците на позиции игнорират категорията "buystop". Buy-stop кандидатите (Watchlist) са отделна книга в същия tracker
и НЕ са позиции: без OPEN✓, без RE-ENTRY/"ЗАТВОРЕНА ДНЕС", без "вече в портфейла" (AMD/AVT/ANET от 05.10), без COT позиции, без Action обобщението.

РЕАЛНО: картата на EXPD от брифа на 05.10.2026 (tests/fixtures/brief_2026-10-05.json; под pivot, buy-stop $194.59) минава през apply_hard_rules.
СИНТЕТИЧНО: всички записи на tracker-а (тикърове AAA…EEE и контролният Action на EXPD), подменената директория data/ и yf/earnings.
Пускане: python test_buystop_readers.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import backtest, ai_brief
from src import main as brief_main

_tmp = tempfile.TemporaryDirectory(prefix="mb_bsr_")
config.DATA_DIR = pathlib.Path(_tmp.name)
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
config.ENABLE_BACKTEST = True
backtest._fetch_current_prices = lambda tickers: {}
backtest.enrich.earnings_recap = lambda t: None

BRIEF = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
EXPD = next(w for w in BRIEF["watchlist"] if w["ticker"] == "EXPD")
assert EXPD["setup"]["kind"] == "below_pivot" and EXPD["setup"]["buy_stop"] == 194.59


def rec(ticker, status, category=None, **kw):
    r = {"method": "v2", "ticker": ticker, "entry_date": "2026-09-20", "status": status, "entry_price": 100.0, "buy_stop": 100.0,
         "max_chase": 105.0, "stop_loss": 92.0, "target_1": 116.0, "window_sessions": 5, "fill_date": None, "realized_r": None,
         "resolution_date": None, "discovered_date": None}
    if category:
        r["category"] = category
    r.update(kw)
    return r


def write(records):
    backtest._save_tracker({f"{r['ticker']}_{r['entry_date']}{'_' + r['category'] if r.get('category') else ''}": r for r in records})


# Action: AAA отворена, EEE затворена; buy-stop: BBB отворена, CCC затворена, DDD чака, EXPD отворена (контрол за apply_hard_rules)
BASE = [rec("AAA", "open", fill_date="2026-09-21"),
        rec("EEE", "stopped", realized_r=-1.0, resolution_date="2026-09-25", fill_date="2026-09-21"),
        rec("BBB", "open", "buystop", fill_date="2026-09-22"),
        rec("CCC", "stopped", "buystop", realized_r=-1.0, resolution_date="2026-09-28", fill_date="2026-09-22"),
        rec("DDD", "pending", "buystop"),
        rec("EXPD", "open", "buystop", fill_date="2026-09-22")]
write(BASE)

print("── помощната функция ──")
assert backtest.is_action_record({}) and backtest.is_action_record({"category": "action"}) and not backtest.is_action_record({"category": "buystop"})
assert backtest.record_category({}) == "action" and backtest.record_category({"category": "buystop"}) == "buystop"
print("  ✓ запис без category е Action (всичко, записано до пакет 1б), 'buystop' не е")

print()
print("── четци на позиции ──")
assert set(brief_main._live_positions()) == {"AAA"}, brief_main._live_positions()                         # BBB и EXPD (buy-stop, отворени) не са позиции
assert set(brief_main._last_resolved_positions()) == {"EEE"}                                               # CCC (затворен buy-stop) не е "предишна позиция"
assert not hasattr(ai_brief, "_live_v2_positions")                                                         # 08.10 (2б): четецът беше само за вчерашните trigger-и — махнат заедно с тях
print("  ✓ main._live_positions → {AAA}; main._last_resolved_positions → {EEE} (buy-stop BBB/CCC/DDD/EXPD не се броят); ai_brief._live_v2_positions е махнат (08.10, 2б)")

print()
print("── Action обобщението ──")
S = backtest.get_backtest_summary()
assert [p["ticker"] for p in S["open_positions"]] == ["AAA"] and S["pending_positions"] == []
assert S["total_resolved"] == 1 and S["stopped"] == 1 and S["still_open"] == 1 and S["pending"] == 0
assert {r["ticker"] for r in S["recent"]} <= {"EEE"} and S["avg_realized_r"] == -1.0
print("  ✓ open_positions=[AAA], чакащи=[], резолвирани=1 (само EEE), без buy-stop записите; (GLB already_open_position и SI✓ четат тези списъци)")

print()
print("── apply_hard_rules с РЕАЛНАТА карта на EXPD ──")
cand = copy.deepcopy(EXPD); cand.pop("plan_preview", None)
action, watch = brief_main.apply_hard_rules([copy.deepcopy(cand)], 0.5, "Defensive")
card = watch[0]
tags = [m["tag"] for m in card.get("markers") or []]
assert not action and "OPEN✓" not in tags and "RE-ENTRY" not in tags and "ЗАТВОРЕНА ДНЕС" not in tags, tags
assert card["ai"].get("watchlist_reason_type") != "existing_position" and "Вече в портфейла" not in (card["ai"].get("watchlist_trigger") or "")
assert card["plan_preview"]["valid"]
print("  ✓ EXPD със ЖИВ buy-stop запис: без OPEN✓, без 'Вече в портфейла', без RE-ENTRY; нормален Watchlist с план-преглед")
write(BASE[:-1] + [rec("EXPD", "open", fill_date="2026-09-22")])                                           # КОНТРОЛ: СЪЩИЯТ запис като Action → OPEN✓ + "вече в портфейла"
action, watch = brief_main.apply_hard_rules([copy.deepcopy(cand)], 0.5, "Defensive")
assert "OPEN✓" in [m["tag"] for m in watch[0]["markers"]] and watch[0]["ai"]["watchlist_reason_type"] == "existing_position"
print("  ✓ контрол: същият запис като Action → OPEN✓ и 'existing_position' — четецът не е счупен, различава категориите")
write([rec("EXPD", "stopped", "buystop", realized_r=-1.0, resolution_date="2026-10-02", fill_date="2026-09-30")])
action, watch = brief_main.apply_hard_rules([copy.deepcopy(cand)], 0.5, "Defensive")
assert not any(m["tag"] in ("RE-ENTRY", "ЗАТВОРЕНА ДНЕС") for m in watch[0].get("markers") or []) and "prev_position" not in watch[0]
print("  ✓ затворен buy-stop запис на EXPD не дава RE-ENTRY / prev_position")

print()
print("Всички тестове минаха.")
