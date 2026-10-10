"""
С1 (втори преглед, 10.10.2026) · "застояли данни" в NYSE СЕСИИ, не в календарни дни (thermometer._is_stale, macro_layer._is_stale за дневни серии).

До 10.10: застоял = последният бар е > 3 календарни дни назад. Във вторник след празник в понеделник петъчният бар е 4 дни назад → MOVE, VIX Term и IEI/HYG се скриха
едновременно на 08.09 (видими 5) без реална повреда. Сега: застоял = между последния бар и днес има ПОВЕЧЕ от config.STALENESS_MAX_LAG_SESSIONS (=1) NYSE сесии.
Допуск 1 (а не 0): измерено върху брифовете — MOVE е с една сесия назад на 04.09 и 23.09, VIX9D/VIX3M на 23.09 (истински данни, Yahoo закъснява); при 0 щяха да се скрият.

РЕАЛНО: tests/fixtures/brief_2026-09-08.json (трите скрити индикатора); датите на последните барове от измерването (04.09 → петъкът преди Labor Day; 02.09 / 21.09 —
MOVE на 04.09 / 23.09; 02.07 — началото на юлското замръзване на ^MOVE); config.NYSE_HOLIDAYS. СИНТЕТИЧНО: бъдещите дати (28.12.2026 … 29.03.2027) и подменената "днес".
Пускане: python test_stale_sessions.py
"""
import sys, json, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import setup_rules, thermometer, macro_layer

D = dt.date.fromisoformat
B08 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-09-08.json").read_text(encoding="utf-8"))
hidden = [i["name"] for i in B08["thermometer"]["indicators"] if i.get("hide")]
assert {"MOVE (Bond Vol)", "VIX Term Structure", "IEI/HYG (Credit Spread)"} <= set(hidden)
assert config.STALENESS_MAX_LAG_SESSIONS == 1


class FakeDate(dt.date):
    today_value = None

    @classmethod
    def today(cls):
        return cls.today_value


def stale_on(today, last, module):
    """module._is_stale(last) при подменена 'днес' (setup_rules.is_stale_daily ползва dt.date.today())."""
    FakeDate.today_value = D(today)
    orig = setup_rules.dt
    setup_rules.dt = type("M", (), {"date": FakeDate, "timedelta": dt.timedelta, "datetime": dt.datetime})
    try:
        return module._is_stale(D(last))
    finally:
        setup_rules.dt = orig


print("── 1. РЕАЛНИЯТ 08.09: петъчният бар след Labor Day вече не е застоял ──")
assert setup_rules.sessions_between("2026-09-04", "2026-09-08") == 0                # 07.09 е празник
assert (D("2026-09-08") - D("2026-09-04")).days == 4 > 3                          # старото правило: застоял
assert stale_on("2026-09-08", "2026-09-04", thermometer) is False and stale_on("2026-09-08", "2026-09-04", macro_layer) is False
print("  ✓ 08.09 (вторник след празник), последен бар 04.09: 0 пропуснати сесии → не е застоял (до 10.10: 4 календарни дни → скрити MOVE, VIX Term, IEI/HYG)")

print()
print("── 2. реалните дни с една сесия закъснение остават видими; юлското замръзване се хваща ──")
for today, last, why in (("2026-09-04", "2026-09-02", "MOVE на 04.09"), ("2026-09-23", "2026-09-21", "MOVE и VIX9D/VIX3M на 23.09")):
    assert setup_rules.sessions_between(last, today) == 1 and stale_on(today, last, thermometer) is False, why
assert stale_on("2026-07-07", "2026-07-02", thermometer) is False                 # 03.07 празник; пропусната е само 06.07 → допуснато (цената на допуска)
assert stale_on("2026-07-08", "2026-07-02", thermometer) is True                  # 06.07 и 07.07 пропуснати → застоял
print("  ✓ 04.09 и 23.09 (една сесия назад, реални данни) → видими; замръзването на ^MOVE от 02.07: 07.07 още се показва (допуск 1), от 08.07 е застоял")

print()
print("── 3. следващите дати след празник (СИНТЕТИЧНА 'днес') ──")
for today, last in (("2026-12-28", "2026-12-24"), ("2027-01-04", "2026-12-31"), ("2027-01-19", "2027-01-15"),
                    ("2027-02-16", "2027-02-12"), ("2027-03-29", "2027-03-25")):
    assert setup_rules.sessions_between(last, today) == 0 and stale_on(today, last, thermometer) is False, today
    assert (D(today) - D(last)).days > 3                                           # всички щяха да са "застояли" по старото правило
print("  ✓ 28.12.2026, 04.01, 19.01, 16.02, 29.03.2027 с бар от последната сесия: не са застояли (старото правило — всичките застояли)")

print()
print("── 4. реална повреда все още се хваща ──")
assert stale_on("2026-10-14", "2026-10-09", thermometer) is True                   # пропуснати 12.10 и 13.10
assert stale_on("2026-10-13", "2026-10-09", thermometer) is False                  # пропусната само 12.10
assert macro_layer._is_stale(D("2026-01-01"), 12) is True                          # седмичните серии с изричен праг — календарни дни, както преди
print("  ✓ две пропуснати сесии → застоял; една → допусната; седмичните серии с праг в дни (WALCL/WDTGAL) — непроменени")
print()
print("Всички тестове минаха.")
