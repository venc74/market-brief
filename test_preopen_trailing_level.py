"""
04.11.2026 · четвърти преглед, С2: карето преди отварянето — записът по Kullamägi в „trailing“ се сравнява със стопа break-even (= max(стоп, вход), както trade_sim.simulate_qm след
частичната продажба), не с първоначалния stop_loss; запис под ръчен преглед (сплит / отделяне след входа — нивата са в старата скала) не се сравнява.

РЕАЛНО: нивата на DOCU_2026-10-13_qm (trailing, stop_loss 70.885, вход 72.76) и UTHR_2026-10-20_qm (trailing, 545.58 / 560.00) — data/backtest_tracker.json към брифа от 03.11
(вписани тук: тестовете не четат data/); CLF_2026-11-02_qm (open, стоп 14.06, вход 14.58).
СИНТЕТИЧНО (означено): цените в премаркета (pts), записът с needs_manual_review.
Пускане: python test_preopen_trailing_level.py
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import preopen

recs = [{"ticker": "DOCU", "category": "qm_breakout", "status": "trailing", "stop_loss": 70.885, "fill_price": 72.76, "entry_price": 72.76},
        {"ticker": "UTHR", "category": "qm_breakout", "status": "trailing", "stop_loss": 545.58, "fill_price": 560.0, "entry_price": 560.0},
        {"ticker": "CLF", "category": "qm_breakout", "status": "open", "stop_loss": 14.06, "fill_price": 14.58, "entry_price": 14.58},
        {"ticker": "XYZ", "category": "qm_breakout", "status": "trailing", "stop_loss": 10.0, "fill_price": 12.0, "needs_manual_review": {"reason": "split_after_entry_qm"}}]
pt = lambda px: {"pm_price": px, "pm_volume": None}
pts = {"DOCU": pt(71.50), "UTHR": pt(561.0), "CLF": pt(14.30), "XYZ": pt(5.0)}            # СИНТЕТИЧНО

print("── trailing → break-even; open → стопът; под ръчен преглед — без сравнение ──")
lv = preopen.level_checks(pts, [], [], recs)
got = {(x["ticker"], x["kind"], x["level"]) for x in lv}
assert got == {("DOCU", "под стопа (break-even)", 72.76)}, got
# до 04.11: DOCU 71.50 > 70.885 → нищо; сега — под break-even 72.76 (записът се затваря на отварянето)
assert preopen.level_checks({"CLF": pt(14.0)}, [], [], recs)[0]["level"] == 14.06                       # open — първоначалният стоп, както досега
print("  ✓ DOCU $71.50 — под break-even $72.76 (до 04.11 — нищо: сравнението беше с $70.885); UTHR $561 над $560 — нищо; CLF — първоначалният стоп; XYZ — прескочен")
print("\n✅ test_preopen_trailing_level: всичко мина")
