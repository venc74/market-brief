"""
16.11.2026 (пакет 16.11, т. 7): брифът от 16.11 казваше „COT: отчетът, публикуван в петък 13.11, още не е в данните“ — такъв няма: заради Veterans Day (11.11) CFTC премести
отчета към 10.11 за понеделник 16.11, 15:30 ET. Датата на следващия отчет вече е по официалния график на CFTC (config.CFTC_COT_RELEASES), с празничните отмествания
(16.11, 30.11, 28.12 — понеделник); извън графика — петъкът, както до 16.11. Здравната проверка „cot_schedule“ напомня, когато графикът свършва.

РЕАЛНО: tests/fixtures/cftc_cot_release_schedule_2026-11-16.html.gz — страницата на CFTC (cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm), свалена 16.11.2026
(48 065 байта, SHA-256 b40f3a95292b3863…; „tentative schedule of releases through 2026“); cot_status на брифовете от 13.11 и 16.11 (отчет към 03.11) — data/, цитирани тук.
СИНТЕТИЧНО (означено): т. 3 — дати извън графика (2027) и „днес“ за здравната проверка.
Пускане: python test_cot_schedule.py
"""
import sys, gzip, re, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cotsch_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from bs4 import BeautifulSoup
from src import data_rhythm as r, health_monitor as hm

print("── 1. РЕАЛНО: графикът в config = страницата на CFTC ──")
text = BeautifulSoup(gzip.decompress((ROOT / "tests" / "fixtures" / "cftc_cot_release_schedule_2026-11-16.html.gz").read_bytes()), "html.parser").get_text("\n", strip=True)
block = text[text.index("2026 Release Schedule"):text.index("*Delayed release date")]
months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
page, starred, cur = [], [], None
for tok in block.split("\n"):
    if tok in months:
        cur = months.index(tok) + 1
    elif cur and re.fullmatch(r"\d{2}\*?", tok):
        d = dt.date(2026, cur, int(tok[:2])).isoformat()
        page.append(d)
        if tok.endswith("*"):
            starred.append(d)
assert tuple(page) == config.CFTC_COT_RELEASES, sorted(set(page) ^ set(config.CFTC_COT_RELEASES))
assert starred == ["2026-01-05", "2026-06-22", "2026-07-06", "2026-11-16", "2026-11-30", "2026-12-28"]
assert all(dt.date.fromisoformat(d).weekday() == 0 for d in starred) and all(dt.date.fromisoformat(d).weekday() == 4 for d in page if d not in starred)
print(f"  ✓ {len(page)} дати; изместени (понеделник): {', '.join(x[8:10] + '.' + x[5:7] for x in starred)}")

print("── 2. РЕАЛНО: брифът от 16.11 (отчет към 03.11) ──")
st = {"as_of": "2026-11-03", "age_days": 13, "stale": False}
g16 = r.cot_rhythm(st, {"cot_status": st}, "2026-11-16")
assert not g16["late"] and g16["release_date"] == "2026-11-16" and g16["delayed"] and g16["source"] == "schedule"
assert g16["text"] == "COT: без нови данни — отчет към 03.11, следващ отчет понеделник 16.11 — изместен заради празник, по графика на CFTC (публикуван 21:30 Берлин)"
g17 = r.cot_rhythm(st, {"cot_status": st}, "2026-11-17")
assert g17["late"] and g17["text"] == "COT: отчетът, публикуван в понеделник 16.11, още не е в данните — показан е отчетът към 03.11"
nxt = [r.cftc_next_release(a)["release_date"] for a in ("2026-11-10", "2026-11-17", "2026-11-24", "2026-12-15")]
assert nxt == ["2026-11-20", "2026-11-30", "2026-12-04", "2026-12-28"], nxt
assert r.release_as_of(dt.date(2026, 11, 16)) == dt.date(2026, 11, 10) and r.release_as_of(dt.date(2026, 11, 20)) == dt.date(2026, 11, 17)
print(f"  ✓ 16.11: „{g16['text']}“; 17.11 без данните — „…публикуван в понеделник 16.11, още не е в данните“; 20.11, 30.11, 04.12, 28.12")

print("── 3. СИНТЕТИЧНО: извън графика — петъкът; здравната проверка ──")
x = r.cftc_next_release("2027-02-02")
assert x["source"] == "rule" and x["release_date"] == "2027-02-12" and x["weekday"] == "петък" and not x["delayed"]
with contextlib.redirect_stdout(io.StringIO()):
    now = hm.check("2026-11-16", resolution={"ok": True, "live": 0}, glb_status={"ok": True})
    late = hm.check("2026-12-15", resolution={"ok": True, "live": 0}, glb_status={"ok": True})
assert "cot_schedule" not in {i["check"] for i in now}
cs = [i for i in late if i["check"] == "cot_schedule"]
assert len(cs) == 1 and "свършва на 28.12.2026 (остават 13 дни)" in cs[0]["message"]
print("  ✓ 2027 — по правилото „петък“; 15.12.2026 → „CFTC_COT_RELEASES … свършва на 28.12.2026 (остават 13 дни)“")
print("\n✅ test_cot_schedule: всичко мина")
