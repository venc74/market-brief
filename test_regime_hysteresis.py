"""
Тест за т.1 от прегледа на 01.10: _merge_regime() (override severity fix) +
_hysteresis_effective() (2-дневен хистерезис за MOVE/IEI-HYG spike).

Реални примери: overrides/counts са КОПИРАНИ буквално от data/2026-10-01.json
(реалният бриф на 01.10 — regime_by_count=Cash, финален regime преди фикса
беше "Defensive"). Всичко останало по-долу е синтетично (гранични случаи),
изрично маркирано като такова.

Пускане: python test_regime_hysteresis.py
"""
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src import thermometer as th

# ──────────────────────────────────────────────────────────────────────────
# РЕАЛНИ ДАННИ от data/2026-10-01.json (бриф 01.10.2026)
# ──────────────────────────────────────────────────────────────────────────
REAL_01_10_COUNTS = "4 зелени / 2 жълти / 3 червени от 9 видими"
REAL_01_10_COUNT_REASON = f"{REAL_01_10_COUNTS} — капиталът е позиция"
REAL_01_10_OVERRIDES = [
    {'trigger': 'MOVE',
     'text': 'MOVE 110 (рязък седмичен скок, +15.0 пункта) — стрес в колатералната '
             'система (UST), автоматичен Defensive режим, sizing −50%',
     'exit_condition': 'седмичната промяна на MOVE спадне под +15 пункта (сега +15.0 '
                        'пункта) — тоест седмичният ръст се забави под 15 пункта; НЕ се '
                        'изисква спад до конкретно ниво'},
    {'trigger': 'IEI/HYG',
     'text': 'IEI/HYG credit spread spike (+0.9% за 10д, 94. percentile) — рязко '
             'разширяване на credit risk premium, автоматичен Defensive режим, sizing −50%',
     'exit_condition': '10-дневната промяна на IEI/HYG падне под 90. percentile (сега 94.)'},
]

print("── РЕАЛЕН пример (01.10.2026, data/2026-10-01.json) ──")
regime, reason, exit_rule = th._merge_regime(
    "Cash", REAL_01_10_COUNT_REASON, REAL_01_10_COUNTS, REAL_01_10_OVERRIDES)
print(f"  regime={regime!r}")
print(f"  reason={reason!r}")
print(f"  exit_rule={exit_rule!r}")
assert regime == "Cash", f"РЕГРЕСИЯ: 01.10 трябваше да даде Cash (count по-строг от override), получено {regime}"
assert "Cash" in reason and "override" in reason.lower()
assert "броенето" in exit_rule
print("  ✓ 01.10 вече дава Cash (преди фикса: 'Defensive' — по-меко от броенето)")
print()

# ──────────────────────────────────────────────────────────────────────────
# СИНТЕТИЧНИ гранични случаи за _merge_regime (измислени, не от реален бриф)
# ──────────────────────────────────────────────────────────────────────────
print("── СИНТЕТИЧНИ гранични случаи (измислени входове) ──")

# 1) count=Offensive + override → override вдига до Defensive (нормална ескалация)
regime, reason, exit_rule = th._merge_regime(
    "Offensive", "6 зелени / 0 червени", "6 зелени / 0 червени",
    [{"trigger": "VIX", "text": "VIX 35 > 30 ...", "exit_condition": "VIX <= 30"}])
assert regime == "Defensive", f"синтетичен: Offensive+override трябва да escalate до Defensive, получено {regime}"
print(f"  ✓ синт. count=Offensive + VIX override → {regime} (ескалация, очаквано)")

# 2) count=Defensive + override → остава Defensive (override на пода, няма промяна)
regime, reason, exit_rule = th._merge_regime(
    "Defensive", "3 зелени / 1 червен", "3 зелени / 1 червен",
    [{"trigger": "MOVE", "text": "MOVE spike ...", "exit_condition": "delta < 15"}])
assert regime == "Defensive"
print(f"  ✓ синт. count=Defensive + MOVE override → {regime} (без промяна, очаквано)")

# 3) count=Cash + БЕЗ override → чисто броене, без 'override' текст в reason
regime, reason, exit_rule = th._merge_regime("Cash", "0 зелени / 4 червени", "0 зелени / 4 червени", [])
assert regime == "Cash" and "override" not in reason.lower()
print(f"  ✓ синт. count=Cash, без overrides → {regime}, reason чист (без override текст)")

# 4) count=Cash + ДВА override-а (точно 01.10 формата, но синтетично изброени тук)
regime, reason, exit_rule = th._merge_regime(
    "Cash", "x", "x",
    [{"trigger": "A", "text": "...", "exit_condition": "..."},
     {"trigger": "B", "text": "...", "exit_condition": "..."}])
assert regime == "Cash" and "A, B" in reason
print(f"  ✓ синт. count=Cash + 2 override-а → {regime}, и двата trigger-а изредени в reason")
print()

# ──────────────────────────────────────────────────────────────────────────
# Хистерезис: _hysteresis_effective() — СИНТЕТИЧНА 5-дневна симулация
# (данните по държавата на state файла са измислени; monkeypatch към tempdir,
# за да НЕ пипаме истинския data/regime_override_state.json)
# ──────────────────────────────────────────────────────────────────────────
print("── СИНТЕТИЧЕН хистерезис (5-дневна симулация, tempdir state) ──")
with tempfile.TemporaryDirectory() as tmp:
    orig = th._OVERRIDE_STATE_FILE
    th._OVERRIDE_STATE_FILE = pathlib.Path(tmp) / "regime_override_state.json"
    try:
        # Ден 1: spike активен
        eff, streak = th._hysteresis_effective("test_key", True, "2026-01-01")
        assert eff is True and streak == 0, (eff, streak)
        print(f"  ден 1 (raw=True):  effective={eff}, streak={streak} ✓")

        # Ден 2: spike паднал под прага за ПЪРВИ път — хистерезис държи активно
        eff, streak = th._hysteresis_effective("test_key", False, "2026-01-02")
        assert eff is True and streak == 1, (eff, streak)
        print(f"  ден 2 (raw=False): effective={eff}, streak={streak} ✓ (хистерезис hold)")

        # Ден 3: ВТОРИ пореден ден под прага — override-ът пада
        eff, streak = th._hysteresis_effective("test_key", False, "2026-01-03")
        assert eff is False and streak == 2, (eff, streak)
        print(f"  ден 3 (raw=False): effective={eff}, streak={streak} ✓ (пада, 2/2)")

        # Ден 4: нов скок — streak се ресетва веднага
        eff, streak = th._hysteresis_effective("test_key", True, "2026-01-04")
        assert eff is True and streak == 0, (eff, streak)
        print(f"  ден 4 (raw=True):  effective={eff}, streak={streak} ✓ (reset при нов скок)")

        # Идемпотентност: повторен run СЪЩИЯ ден не брои двойно
        eff_a, streak_a = th._hysteresis_effective("test_key", False, "2026-01-05")
        eff_b, streak_b = th._hysteresis_effective("test_key", False, "2026-01-05")
        assert (eff_a, streak_a) == (eff_b, streak_b) == (True, 1), (eff_a, streak_a, eff_b, streak_b)
        print(f"  ден 5 ×2 (same-day повторен run): streak={streak_b} и двата пъти ✓ (без двойно броене)")
    finally:
        th._OVERRIDE_STATE_FILE = orig

print()
print("Всички тестове минаха.")
