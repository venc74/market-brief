"""
Втори преглед (10.10.2026) · 2s10s (macro_layer.treasury_spread_2s10s): "седмица назад" по ДАТА (series_utils.last_and_week_ago), не obs[-6]; застояли данни в NYSE сесии
(допуск config.FRED_DAILY_MAX_LAG_SESSIONS = 2 — облигационни празници като Columbus Day, когато NYSE работи, и закъснението на FRED).

РЕАЛНО: T10Y2Y от FRED 25.08–15.09.2026 (07.09 — празник, празна стойност; _fred_series я пропуска). СИНТЕТИЧНО: подменената "днес", серията след 09.10 в т.2.
Пускане: python test_2s10s_dates.py
"""
import sys, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import macro_layer as ml

REAL = [("2026-08-25", .47), ("2026-08-26", .47), ("2026-08-27", .47), ("2026-08-28", .39), ("2026-08-31", .41), ("2026-09-01", .40), ("2026-09-02", .40),
        ("2026-09-03", .43), ("2026-09-04", .41), ("2026-09-08", .41), ("2026-09-09", .40), ("2026-09-10", .39), ("2026-09-11", .33), ("2026-09-14", .32), ("2026-09-15", .33)]


class FakeDate(dt.date):
    value = None

    @classmethod
    def today(cls):
        return cls.value


def run(series, today):
    ml._fred_series = lambda sid, days=30: list(series)
    FakeDate.value = dt.date.fromisoformat(today)
    orig_ml, orig_sr = ml.dt, None
    ml.dt = type("M", (), {"date": FakeDate, "timedelta": dt.timedelta, "datetime": dt.datetime})
    try:
        return ml.treasury_spread_2s10s()
    finally:
        ml.dt = orig_ml


print("── 1. РЕАЛНИЯТ бриф на 09.09 (последно наблюдение 08.09, 07.09 празник) ──")
upto = [x for x in REAL if x[0] <= "2026-09-08"]
r = run(upto, "2026-09-09")
assert r["value"] == .41 and r["prev_week"] == .40 and r["as_of"] == "2026-09-08" and r["change_1w_bp"] == 1.0 and r["direction"] == "steepening"
assert upto[-6] == ("2026-08-31", .41)                                                # старото obs[-6]: 8 дни назад, 0.41 → "stable", 0.0 б.п.
print("  ✓ по дата: 01.09 (0.40) → +1.0 б.п., steepening; старото obs[-6] беше 31.08 (8 дни назад, 0.41) → 'stable', 0.0 б.п.")

print()
print("── 2. застояли данни (СИНТЕТИЧНА 'днес'; Columbus Day 12.10 — облигациите не работят) ──")
oct_ = [("2026-10-02", .45), ("2026-10-05", .47), ("2026-10-06", .48), ("2026-10-07", .51), ("2026-10-08", .47), ("2026-10-09", .44)]   # РЕАЛНИ
assert run(oct_, "2026-10-14")["value"] == .44                                         # пропуснати 12.10 и 13.10 → допуснато (2)
st = run(oct_, "2026-10-15")
assert st["value"] is None and st["stale"] is True and st["last_date"] == "2026-10-09"   # 3 пропуснати → скрит
assert run([], "2026-10-14") == {"value": None, "status": "unknown"}
print("  ✓ последно 09.10: на 14.10 (2 пропуснати сесии) — валиден; на 15.10 (3) — застоял, value None → индикаторът се скрива; празен FRED → unknown")
print()
print("Всички тестове минаха.")
