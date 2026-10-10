"""
Втори преглед (10.10.2026) · чакащ Action план (v2 запис със status pending — buy-stop прозорецът тече) не допуска втори Action план за същия тикър.

До 10.10: main._live_positions брои само open/trailing; ако вчерашният план чака, а днес тикърът пак е Action, картата показва нов вход с нов риск (книгата дедуплицира
записа, но читателят вижда двоен план). Сега apply_hard_rules го връща във Watchlist с маркер "ЧАКА BUY-STOP" и текст за плана в сила. Чакащият план НЕ е позиция —
_live_positions (COT контекст, OPEN✓, "вече в портфейла") не се променя.
РЕАЛНО: картата на EXPD от брифа на 05.10 (buy-stop $194.59, таван $204.32, валиден до 2026-10-09 — tests/fixtures/brief_2026-10-05.json).
СИНТЕТИЧНО: записът в tracker-а (временна директория) с нивата на реалната карта, потвърденият сетъп и AI "Action" днес.
Пускане: python test_pending_plan.py
"""
import sys, json, pathlib, copy, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import backtest, main as brief_main

tmp = pathlib.Path(tempfile.mkdtemp(prefix="mb_pend_"))
backtest._TRACKER_PATH = tmp / "backtest_tracker.json"
config.ENABLE_BACKTEST = True
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
EXPD = next(c for c in B05["watchlist"] if c["ticker"] == "EXPD")
st = EXPD["setup"]
backtest._TRACKER_PATH.write_text(json.dumps({"EXPD_2026-10-05": {
    "ticker": "EXPD", "method": "v2", "status": "pending", "entry_date": "2026-10-05",
    "buy_stop": st["buy_stop"], "max_chase": st.get("max_chase"), "valid_through": st.get("valid_through")}}))

cand = copy.deepcopy(EXPD)
cand["setup"] = {**st, "kind": "confirmed", "eligible": True}
cand.update({"pct_from_pivot": 1.0, "breakout_volume": True, "volume_ratio": 1.8, "ai": {"classification": "Action", "why_now": "x"}})
with contextlib.redirect_stdout(io.StringIO()):
    action, watch = brief_main.apply_hard_rules([cand], 1.0, "Offensive")
assert not action and watch and watch[0]["ticker"] == "EXPD"
w = watch[0]
assert [m["tag"] for m in w["markers"]].count("ЧАКА BUY-STOP") == 1 and w["ai"]["watchlist_reason_type"] == "existing_position"
assert f"buy-stop ${st['buy_stop']}" in w["ai"]["watchlist_trigger"] and f"валиден до {st.get('valid_through')}" in w["ai"]["watchlist_trigger"]
assert "EXPD" not in brief_main._live_positions()                                     # не е позиция
print(f"  ✓ чакащ план (buy-stop ${st['buy_stop']}, до {st.get('valid_through')}) + днешен Action за EXPD → Watchlist «ЧАКА BUY-STOP», без втори план; _live_positions не го брои")

backtest._TRACKER_PATH.write_text(json.dumps({"EXPD_2026-10-05": {"ticker": "EXPD", "method": "v2", "status": "not_triggered", "entry_date": "2026-10-05"}}))
cand2 = copy.deepcopy(cand); cand2["markers"] = []; cand2["ai"] = {"classification": "Action", "why_now": "x"}
with contextlib.redirect_stdout(io.StringIO()):
    action2, watch2 = brief_main.apply_hard_rules([cand2], 1.0, "Offensive")
assert len(action2 + watch2) == 1 and not any(m.get("tag") == "ЧАКА BUY-STOP" for m in (action2 + watch2)[0].get("markers") or [])
print("  ✓ изтекъл прозорец (not_triggered) → правилото не се намесва")
print()
print("Всички тестове минаха.")
