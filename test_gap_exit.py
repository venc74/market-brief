"""
20.11.2026 (пакет 20.11, т. 3): всички 5 затворени записа в buy-stop книгата са точно −1.0R — проверка дали гап под стопа се реже до стопа. Не: при отваряне под стопа изходът е
по цената на отварянето (R < −1) — trade_sim.simulate (Action / buy-stop, „т.5“ от 05.10), simulate_qm („stop_gap“), GLB по Уиш — изходът е по отварянето на следващата сесия.
Петте са −1.0R, защото нито един не отвори под стопа: WSM на 19.11 (денят на отчета) отвори $243.19 при стоп $234.90 и стигна $217.11 — стопът е ударен в сесията. Преизчислени
с пресни бари на 20.11: 78 записа с вход в четирите книги — 0 различни (освен ръчните „deal_closed“: ROKU, NWE).

РЕАЛНО: tests/fixtures/wsm_buystop_2026-11-19.json — записът на WSM и дневните му бари 20.10–20.11. СИНТЕТИЧНО (означено): отварянето на 19.11 под стопа в т. 2.
Пускане: python test_gap_exit.py
"""
import sys, json, copy, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
from src import trade_sim

FX = json.loads((ROOT / "tests" / "fixtures" / "wsm_buystop_2026-11-19.json").read_text(encoding="utf-8"))
REC = FX["record"]
bars = pd.DataFrame(FX["bars"]).T.sort_index()
bars.index = pd.to_datetime(bars.index)

print("── 1. РЕАЛНО: WSM — отваряне над стопа, стопът ударен в сесията → −1.0R ──")
r = trade_sim.simulate(REC, bars, dt.date(2026, 11, 20))
assert r["status"] == "stopped" and r["exit_date"] == "2026-11-19" and r["exit_price"] == REC["stop_loss"] and r["realized_r"] == -1.0, r
assert FX["bars"]["2026-11-19"]["Open"] > REC["stop_loss"] > FX["bars"]["2026-11-19"]["Low"]
print(f"  ✓ 19.11: отваряне ${FX['bars']['2026-11-19']['Open']} > стоп ${REC['stop_loss']} > дъно ${FX['bars']['2026-11-19']['Low']} → изход по стопа, −1.0R")

print("── 2. СИНТЕТИЧНО: същият ден с отваряне под стопа → изход по отварянето, R < −1 ──")
b2 = bars.copy()
b2.loc["2026-11-19", "Open"] = 228.0
r2 = trade_sim.simulate(REC, b2, dt.date(2026, 11, 20))
risk = REC["fill_price"] - REC["stop_loss"]
assert r2["exit_price"] == 228.0 and r2["realized_r"] == round((228.0 - REC["fill_price"]) / risk, 2) and r2["realized_r"] < -1
print(f"  ✓ отваряне $228.00 под стопа ${REC['stop_loss']} → изход $228.00, {r2['realized_r']}R")
print("\n✅ test_gap_exit: всичко мина")
