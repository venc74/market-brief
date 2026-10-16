"""
16.10.2026 · В2 (трети преглед): календарът на NYSE. (а) празник / уикенд → брифът НЕ върви (без AI, имейл, записи; страницата — банер върху последния бриф); (б) в деня ПРЕДИ затворена
сесия и при ранно затваряне — ред "утре / в понеделник борсата няма да работи / затваря рано".

РЕАЛНО: tests/fixtures/nyse_hours_calendars_2026-10-16.txt — таблицата с празниците и бележките за ранно затваряне от nyse.com/trade/hours-calendars (16.10.2026); брифовете
tests/fixtures/brief_2026-10-14.json и brief_2026-10-15.json (последният бриф за страницата). До 16.10 брифът вървеше изцяло и в празници (19.06, 03.07, 07.09.2026 — run-ове "success").
СИНТЕТИЧНО (маркирано): датите "днес" за пускането (подменен dt.date в main), подменените AI / имейл / модел (не трябва да се викат).
Пускане: python test_market_calendar.py
"""
import sys, re, json, pathlib, shutil, tempfile, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cal_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import setup_rules as sr, main, render, ai_brief

D = dt.date.fromisoformat
TXT = (ROOT / "tests" / "fixtures" / "nyse_hours_calendars_2026-10-16.txt").read_text(encoding="utf-8")
MON = {m: i for i, m in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}

print("── 1. таблицата в config = официалният календар на NYSE ──")
body = re.sub(r"\([^)]*\)", "", TXT.split("Holiday 2026 2027 2028", 1)[1].split("* Because", 1)[0])          # "(Independence Day observed)" иначе цепи реда
dates = re.findall(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday), (" + "|".join(MON) + r") (\d{1,2})", body)
assert len(dates) == 29, len(dates)                                                           # 10 + 10 + 9 (01.01.2028 е събота — не се отбелязва)
years = [2026, 2027, 2028]
off = []
holidays, k = set(), 0
for row in re.split(r"(?=New Year|Martin Luther|Washington|Good Friday|Memorial|Juneteenth|Independence Day|Labor Day|Thanksgiving|Christmas)", body)[1:]:
    cells = re.findall(r"(—\*|(?:Monday|Tuesday|Wednesday|Thursday|Friday), (?:" + "|".join(MON) + r") \d{1,2})", row)
    for y, c in zip(years, cells):
        if c != "—*":
            m, d = c.split(", ")[1].split()
            holidays.add(dt.date(y, MON[m], int(d)).isoformat())
assert holidays == set(config.NYSE_HOLIDAYS), sorted(holidays ^ set(config.NYSE_HOLIDAYS))
early_txt = " ".join(seg.split("NYSE American", 1)[0] for seg in TXT.split("close early at 1:00 p.m.")[1:])          # само изреченията за ранното затваряне
early = {dt.date(int(y), MON[m], int(d)).isoformat() for m, d, y in re.findall(r"(" + "|".join(MON) + r") (\d{1,2}), (\d{4})", early_txt)}
assert early == set(config.NYSE_EARLY_CLOSES) and set(config.NYSE_EARLY_CLOSES.values()) == {"13:00"} and "close early at 1:00 p.m." in TXT
print(f"  ✓ {len(holidays)} празника 2026–2028 и {len(early)} ранни затваряния (13:00 ET) — точно както в config")

print()
print("── 2. редът за календара ──")
note = sr.market_calendar_note
assert note(D("2026-10-16")) is None and note(D("2026-10-15")) is None
assert note(D("2026-11-25")) == "Утре (26.11) борсата няма да работи — празник в САЩ."
assert note(D("2026-11-27")) == "Днес борсата затваря рано — в 13:00 ET (19:00 CET)."
assert note(D("2026-12-23")) == "Утре (24.12) борсата затваря рано — в 13:00 ET (19:00 CET)."
assert note(D("2026-12-24")) == "Днес борсата затваря рано — в 13:00 ET (19:00 CET). Утре (25.12) борсата няма да работи — празник в САЩ."
assert note(D("2027-01-15")) == "В понеделник (18.01) борсата няма да работи — празник в САЩ."
assert note(D("2026-04-02")) == "Утре (03.04) борсата няма да работи — празник в САЩ." and note(D("2026-09-04")).startswith("В понеделник (07.09)")
print("  ✓ 25.11 'Утре (26.11) … празник'; 27.11 'Днес … рано — в 13:00 ET (19:00 CET)'; 23.12 / 24.12; петък 15.01.2027 'В понеделник (18.01)'; обикновен ден — нищо")

print()
print("── 3. празник: брифът не върви, страницата — банер върху последния бриф ──")
for f in ("brief_2026-10-14.json", "brief_2026-10-15.json"):
    shutil.copy(ROOT / "tests" / "fixtures" / f, config.DATA_DIR / f.replace("brief_", ""))
boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("не трябва да се вика в празник"))
real = (main.dt.date, ai_brief._call_claude, main.send_brief, main.model_selector.resolve_model, main.collect_macro_layer)
class Thanksgiving(dt.date):
    @classmethod
    def today(cls): return cls(2026, 11, 26)                                              # СИНТЕТИЧНО: "днес" е Денят на благодарността
try:
    main.dt.date, ai_brief._call_claude, main.send_brief, main.model_selector.resolve_model, main.collect_macro_layer = Thanksgiving, boom, boom, boom, boom
    res = main.run()
finally:
    main.dt.date, ai_brief._call_claude, main.send_brief, main.model_selector.resolve_model, main.collect_macro_layer = real
assert res == {"date": "2026-11-26", "market_closed": True, "last_brief": "2026-10-15"}
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", (config.DOCS_DIR / "index.html").read_text(encoding="utf-8"))))
assert "🛑 Борсата (NYSE) е затворена днес (26.11) — последният бриф е от 15.10." in page and "15.10.2026" in page
assert not (config.DOCS_DIR / "archive").exists() and not (config.DOCS_DIR / "data").exists() and sorted(p.name for p in config.DATA_DIR.iterdir()) == ["2026-10-14.json", "2026-10-15.json"]
print("  ✓ 26.11: без модел, AI, макро и имейл; docs/index.html = брифът от 15.10 с банера; без архив, без docs/data, нищо ново в data/")
r2 = main._market_closed("2026-11-26", data_dir=pathlib.Path(_tmp.name) / "празно")
assert r2["last_brief"] is None
print("  ✓ без предишен бриф — само ред в лога")

print()
print("── 4. редът в страницата и в имейла (РЕАЛНИЯТ бриф от 15.10) ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-15.json").read_text(encoding="utf-8"))
b["market_calendar_note"] = note(D("2026-11-25"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
assert "📅 Утре (26.11) борсата няма да работи — празник в САЩ." in flat(render.render_dashboard(json.loads(json.dumps(b)))) and "📅 Утре (26.11)" in flat(render.render_email(b))
print("  ✓ '📅 Утре (26.11) борсата няма да работи' — на страницата и в имейла")
print("\n✅ test_market_calendar: всичко мина")
