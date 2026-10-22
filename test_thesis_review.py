"""
21.10.2026 · етап 4, ритъм на данните (решение от 21.10): всяка теза в config.THESIS_BASKETS носи дата на прегледа ("reviewed"); след нея + THESIS_REVIEW_DAYS (90) — или изричното
"review_by" — картата на тезата казва „остаряла, не е преглеждана от ДД.ММ.ГГГГ“. Началните дати са последната промяна на блока в config (git blame към 21.10).

РЕАЛНО: config.THESIS_BASKETS (петте тези — „Крипто регулация (CLARITY Act)“ отпадна на 22.10 с крипто секцията) и tests/fixtures/brief_2026-10-19.json — реалните тези на брифа за страницата.
СИНТЕТИЧНО (означено): датите „днес“ (21.10.2026, 29.12.2026, 07.01.2027) и тезата без дата / с изричен срок.
Пускане: python test_thesis_review.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_thr_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import macro_layer, render

print("── 1. тезите в config ──")
assert all(b.get("reviewed") for b in config.THESIS_BASKETS) and config.THESIS_REVIEW_DAYS == 90
rev = lambda day: {t["name"]: t for t in macro_layer.thesis_monitor({}, dt.date.fromisoformat(day))}
d21, d29, j07 = rev("2026-10-21"), rev("2026-12-29"), rev("2027-01-07")
assert not any(t["overdue"] for t in d21.values())
assert [n for n, t in d29.items() if t["overdue"]] == ["Финанси при стръмна крива"] and d29["Финанси при стръмна крива"]["review_by"] == "2026-12-28"
assert all(t["overdue"] for t in j07.values()) and j07["Ядрена енергия"]["overdue_text"] == "остаряла, не е преглеждана от 08.10.2026"
assert len(j07) == 5 and "Крипто регулация (CLARITY Act)" not in j07
print(f"  ✓ на 21.10 — нито една; на 29.12 — „Финанси при стръмна крива“ (прегледана 29.09, срок 28.12); на 07.01.2027 — всичките {len(j07)} („не е преглеждана от 08.10.2026“)")

print()
print("── 2. без дата и изричен срок (СИНТЕТИЧНИ тези) ──")
assert macro_layer.thesis_review({"name": "x"}, dt.date(2027, 1, 7)) == {"reviewed": None, "review_by": None, "overdue": False, "overdue_text": None}
r = macro_layer.thesis_review({"reviewed": "2026-10-08", "review_by": "2026-11-01"}, dt.date(2026, 11, 2))
assert r["overdue"] and r["review_by"] == "2026-11-01"
assert macro_layer.thesis_review({"reviewed": "08.10.2026"}, dt.date(2027, 1, 7))["overdue"] is False      # лоша дата — без етикет, без грешка
print("  ✓ без дата — без етикет; изричен срок важи пред 90-те дни; нечетима дата — без етикет")

print()
print("── 3. страницата (РЕАЛНИТЕ тези на брифа от 19.10) ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
assert b["theses"]
b2 = copy.deepcopy(b)
for t in b2["theses"]:
    t.update(j07.get(t["name"]) and {k: j07[t["name"]][k] for k in ("reviewed", "review_by", "overdue", "overdue_text")} or {})
with contextlib.redirect_stdout(io.StringIO()):
    page, page_old = render.render_dashboard(b2), render.render_dashboard(copy.deepcopy(b))
sec = page[page.index("Геополитически тези"):]; sec = sec[:sec.index("</section>")]
assert sec.count("⚠ остаряла, не е преглеждана от") == len([t for t in b2["theses"] if t.get("overdue")]) >= 5
assert "остаряла" not in page_old
print(f"  ✓ {sec.count('⚠ остаряла')} карти с етикета; старият бриф — без него")
print("\n✅ test_thesis_review: всичко мина")
