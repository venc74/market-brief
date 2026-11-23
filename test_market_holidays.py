"""
23.11.2026 (пакет 23.11, т. 6): празниците и съкратените сесии на NYSE — в календара на седмицата и в „Нощта“. До 23.11 календарът изреждаше само сесиите (week_days) и
затвореният ден не се виждаше: на 23.11 26.11 (Thanksgiving) липсваше, а 27.11 (до 13:00 Ню Йорк) изглеждаше като обикновен ден.

РЕАЛНО: tests/fixtures/nyse_hours_calendars_2026-10-16.txt — официалният календар на NYSE (свален на 16.10.2026): празниците 2026–2028 с имената и ранните затваряния.
СИНТЕТИЧНО (означено): празните отговори на Nasdaq в build_week (само за да се види редът за борсата).
Пускане: python run_tests.py test_market_holidays
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, re, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import econ_calendar as ec, overnight

TXT = (ROOT / "tests" / "fixtures" / "nyse_hours_calendars_2026-10-16.txt").read_text(encoding="utf-8")

print("── 1. РЕАЛНО: имената на празниците срещу официалния календар на NYSE ──")
OFFICIAL = [("New Year’s Day", "Нова година"), ("Martin Luther King, Jr. Day", "Martin Luther King"), ("Washington's Birthday", "Washington"), ("Good Friday", "Good Friday"),
            ("Memorial Day", "Memorial"), ("Juneteenth National Independence Day", "Juneteenth"), ("Independence Day", "Independence"), ("Labor Day", "Labor"),
            ("Thanksgiving Day", "Thanksgiving"), ("Christmas Day", "Коледа")]
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}
table = TXT.split("Holiday 2026 2027 2028", 1)[1].split(" * Because", 1)[0]
pos = []
for name, _ in OFFICIAL:
    i = table.index(name, pos[-1][1] + 1 if pos else 0) if name != "Independence Day" else table.index("Independence Day Friday, July 3")
    pos.append((name, i))
found = {}
for k, (name, i) in enumerate(pos):
    seg = table[i + len(name): pos[k + 1][1] if k + 1 < len(pos) else len(table)]
    seg = re.sub(r"\([^)]*\)", "", seg)
    dates = re.findall(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday), (\w+) (\d+)|—", seg)
    for year, d in zip((2026, 2027, 2028), dates):
        if d[0]:
            found[dt.date(year, MONTHS[d[0]], int(d[1])).isoformat()] = dict(OFFICIAL)[name]
assert set(found) == set(config.NYSE_HOLIDAYS), sorted(set(found) ^ set(config.NYSE_HOLIDAYS))
assert set(config.NYSE_HOLIDAY_NAMES) == set(config.NYSE_HOLIDAYS)
for d, key in found.items():
    assert key in config.NYSE_HOLIDAY_NAMES[d], (d, key, config.NYSE_HOLIDAY_NAMES[d])
early = {f"{y}-{MONTHS[m]:02d}-{int(dd):02d}" for m, dd, y in re.findall(r"on (?:Monday|Thursday|Friday), (\w+) (\d+), (\d{4})", TXT)}
early |= {f"{y}-{MONTHS[m]:02d}-{int(dd):02d}" for m, dd, y in re.findall(r"(\w+) (\d+), (\d{4})(?:, and| \(the day| ,)", TXT) if m in MONTHS}
assert set(config.NYSE_EARLY_CLOSES) <= early | {"2026-11-27", "2027-11-26", "2028-11-24"} and "2026-11-27" in config.NYSE_EARLY_CLOSES
print(f"  ✓ {len(found)} празника 2026–2028 — датите и имената съвпадат; ранните затваряния — 13:00")

print("── 2. календарът на седмицата от 23.11 (Nasdaq — СИНТЕТИЧНО празен) ──")
w = ec.build_week(dt.date(2026, 11, 23), {}, {}, econ_fn=lambda d: [], earnings_fn=lambda d: [])
days = {d["date"]: d for d in w["days"]}
assert list(days) == ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27", "2026-11-30"]
assert days["2026-11-26"]["closed"] and ec.day_lines(days["2026-11-26"]) == ["борса: NYSE затворена — Thanksgiving (Денят на благодарността)"]
assert ec.day_lines(days["2026-11-27"])[0] == "борса: NYSE — съкратена сесия, затваря в 13:00 Ню Йорк"
assert "market" not in days["2026-11-24"]
print("  ✓ чт 26.11 — „NYSE затворена — Thanksgiving“; пт 27.11 — „съкратена сесия, затваря в 13:00 Ню Йорк“")

print("── 3. „Нощта“ ──")
assert ec.market_day_notes(dt.date(2026, 11, 23)) == []
assert ec.market_day_notes(dt.date(2026, 11, 25)) == ["Утре (чт 26.11) NYSE е затворена — Thanksgiving (Денят на благодарността); следващата сесия — пт 27.11, съкратена до 13:00 Ню Йорк."]
assert ec.market_day_notes(dt.date(2026, 11, 27)) == ["Днес (пт 27.11) NYSE затваря в 13:00 Ню Йорк — съкратена сесия."]
assert ec.market_day_notes(dt.date(2026, 11, 30)) == ["Предишната сесия (пт 27.11) беше съкратена — затваряне в 13:00 Ню Йорк; „след затварянето“ е от 13:00."]
assert ec.market_day_notes(dt.date(2026, 12, 24))[1] == "Утре (пт 25.12) NYSE е затворена — Коледа; следващата сесия — пн 28.12."
o = overnight.build("2026-11-25", None, frames=None, now_utc=dt.datetime(2026, 11, 25, 6, 30, tzinfo=dt.timezone.utc), fallback_rows=[])
assert o["notes"][0].startswith("Утре (чт 26.11) NYSE е затворена — Thanksgiving")
print(f"  ✓ «{o['notes'][0]}»")
print("\n✅ test_market_holidays: всичко мина")
