"""
Тест за т.4 от прегледа на партида 1: _skip_reason() в oi_snapshot.py —
дедуп (вече има снимка за сесията) + cutoff (след 20:00 UTC) guard-ове, за
да не презаписва schedule:-ът (GitHub-native, наблюдавано закъснява с часове)
вече взета от cron-job.org снимка.

Реален пример: закъсненията 19:55 UTC (30.09) и 18:22 UTC (29.09) са реални,
от git log timestamps на commit-ите "oi snapshot: 2026-09-30"/"...-29" —
и двата са ПРЕДИ 20:00 UTC прага, т.е. биха минали успешно с guard-а, стига
да нямаше вече снимка от по-ранен run. Самите тестови сценарии по-долу са
синтетични (измислени часове/дати), маркирани като такива.

Пускане: python test_oi_snapshot_skip.py
"""
import sys, pathlib, datetime as dt
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src.oi_snapshot import _skip_reason

print("── СИНТЕТИЧНИ сценарии (измислени часове/дати) ──")

session = dt.date(2026, 10, 2)

# 1) Няма съществуваща снимка, часът е преди прага (18:00 UTC < 20:00) → продължава
now = dt.datetime(2026, 10, 2, 18, 0, tzinfo=dt.timezone.utc)
reason = _skip_reason(session, {}, now)
assert reason is None, f"трябваше да продължи (преди прага, без съществуваща снимка): {reason!r}"
print("  ✓ 18:00 UTC, без съществуваща снимка → продължава (None)")

# 2) Реален пример за закъснение: 19:55 UTC (30.09, git log) — ВСЕ ОЩЕ преди 20:00
now = dt.datetime(2026, 9, 30, 19, 55, tzinfo=dt.timezone.utc)
reason = _skip_reason(dt.date(2026, 9, 30), {}, now)
assert reason is None, f"19:55 UTC е преди 20:00 прага, трябваше да продължи: {reason!r}"
print("  ✓ 19:55 UTC (реалното закъснение от 30.09), без снимка → продължава (все още преди прага)")

# 3) Вече има снимка за сесията (напр. cron-job.org я е взел по-рано) → пропуска
existing = {session.isoformat(): {"fetched_at_utc": "2026-10-02 14:05"}}
reason = _skip_reason(session, existing, dt.datetime(2026, 10, 2, 15, 0, tzinfo=dt.timezone.utc))
assert reason is not None and "вече съществува" in reason and "14:05" in reason
print(f"  ✓ снимка вече съществува (от 14:05) → пропуска: {reason}")

# 4) Часът е точно на прага (20:00 UTC) → пропуска (>=, не >)
now = dt.datetime(2026, 10, 2, 20, 0, tzinfo=dt.timezone.utc)
reason = _skip_reason(session, {}, now)
assert reason is not None and "след прага" in reason
print(f"  ✓ точно 20:00 UTC (границата, >=) → пропуска: {reason}")

# 5) Часът е след прага (21:30 UTC) → пропуска
now = dt.datetime(2026, 10, 2, 21, 30, tzinfo=dt.timezone.utc)
reason = _skip_reason(session, {}, now)
assert reason is not None and "21:30" in reason
print(f"  ✓ 21:30 UTC (ясно след прага) → пропуска: {reason}")

# 6) Приоритет: ако И двете условия са налице (снимка ВЕЧЕ съществува, И е след
#    прага), съобщението е за дедуп-а първо (по-конкретната/по-честата причина)
now = dt.datetime(2026, 10, 2, 21, 0, tzinfo=dt.timezone.utc)
reason = _skip_reason(session, existing, now)
assert "вече съществува" in reason
print(f"  ✓ дедуп + след прага едновременно → причината е дедуп (проверява се първо)")

print()
print("Всички тестове минаха.")
