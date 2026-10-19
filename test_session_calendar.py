"""
19.10.2026 · етап 2, т. 15 (трети преглед, Н1/Н2): сесиите по NYSE календара (setup_rules.is_session — уикенд и NYSE_HOLIDAYS), не по делничните дни / последния бар на SPY.

  • Н1 thesis_context._business_days (флагът "отчет скоро" в карето "Контекст"): до 19.10 — делничните дни. Реално (89 брифа, 71 реда с отчет): броят беше с 1 повече в 3 реда
    (AVGO с отчет 09.12 на 30.09, 06.10 и 07.10 — през Thanksgiving); флагът в историята не се е сменял.
  • Н1 backtest._is_late_discovery ("открито със закъснение"): до 19.10 — първият делничен ден след резолюцията. В реалната книга (80 записа с двете дати) — 0 засегнати; първият
    случай щеше да е Thanksgiving: стоп в сряда 25.11, открит в петък 27.11 (в четвъртък брифът не върви) → погрешно "със закъснение".
  • Н2 unusual_options._snapshot_for_yesterday: сутрешната сесия за OI снимката — bar_freshness.expected_session(днес), без мрежа; до 19.10 — последният дневен бар на SPY,
    който в 5 от 60 брифа (29.07–23.09) в 07:30 беше от D−2 → снимката на D−2 срещу обема на D−1.

РЕАЛНО: tests/fixtures/oi_snapshot_2026-10-16.json (снимката за сесия 16.10 — бот commit-ът 2ac7303); датите на AVGO (брифът от 07.10, data/2026-10-07.json: отчет 09.12).
СИНТЕТИЧНО (означено): датите около Thanksgiving и Labor Day, записите на книгата, подмененото зареждане на снимките.
Пускане: python test_session_calendar.py
"""
import sys, json, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import thesis_context as tc, backtest as bt, unusual_options as uo

D = dt.date.fromisoformat
assert "2026-11-26" in config.NYSE_HOLIDAYS and "2026-09-07" in config.NYSE_HOLIDAYS

print("── 1. Н1: карето 'Контекст' — сесии до отчета ──")
assert tc._business_days(D("2026-10-07"), D("2026-12-09")) == 44                     # РЕАЛНИТЕ дати на AVGO (07.10 → 09.12); делничните дни бяха 45
assert tc._business_days(D("2026-11-20"), D("2026-11-30")) == 5                      # СИНТЕТИЧНО: 23, 24, 25, 27, 30.11 — Thanksgiving не е сесия → "скоро" (делнични: 6)
assert tc._business_days(D("2026-10-16"), D("2026-10-19")) == 1                      # уикендът — както досега
print("  ✓ AVGO 07.10 → 09.12: 44 сесии (беше 45); 20.11 → 30.11: 5 (беше 6 — Thanksgiving); петък → понеделник: 1")

print()
print("── 2. Н1: книгата — 'открито със закъснение' (СИНТЕТИЧНИ записи) ──")
assert bt._is_late_discovery({"resolution_date": "2026-11-25", "discovered_date": "2026-11-27"}) is False      # първата сесия след 25.11 е 27.11
assert bt._is_late_discovery({"resolution_date": "2026-11-25", "discovered_date": "2026-11-30"}) is True
assert bt._is_late_discovery({"resolution_date": "2026-09-04", "discovered_date": "2026-09-08"}) is False      # петък → вторник след Labor Day
assert bt._is_late_discovery({"resolution_date": "2026-10-16", "discovered_date": "2026-10-19"}) is False      # уикендът — както досега
print("  ✓ стоп 25.11 → открит 27.11: навреме (Thanksgiving); 30.11: със закъснение; 04.09 → 08.09: навреме (Labor Day)")

print()
print("── 3. Н2: сутрешната OI снимка — сесията от календара, без мрежа ──")
SNAP = json.loads((ROOT / "tests" / "fixtures" / "oi_snapshot_2026-10-16.json").read_text(encoding="utf-8"))
assert SNAP["session_date"] == "2026-10-16"
orig = (uo.load_oi_snapshots, uo.last_session_date)
uo.load_oi_snapshots = lambda: {"2026-10-16": SNAP}                                  # СИНТЕТИЧНО: зареждането; снимката е РЕАЛНА
uo.last_session_date = lambda: (_ for _ in ()).throw(AssertionError("сутрин сесията не се тегли от SPY"))
try:
    snap, session, why = uo._snapshot_for_yesterday(D("2026-10-19"))
    assert snap is SNAP and session == "2026-10-16" and why == ""
    snap, session, why = uo._snapshot_for_yesterday(D("2026-09-08"))                # СИНТЕТИЧНО: вторник след Labor Day → сесията е петък 04.09
    assert snap is None and session == "2026-09-04" and why == "следобедната OI снимка за сесията 04.09 липсва"
finally:
    uo.load_oi_snapshots, uo.last_session_date = orig
print("  ✓ 19.10 → реалната снимка за 16.10 (петък); 08.09 → сесия 04.09 с ясна причина; SPY не се тегли")
print("\n✅ test_session_calendar: всичко мина")
