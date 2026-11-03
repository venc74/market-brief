"""
03.11.2026 · разходката, т. 0: всяка сгъната таблица / секция на страницата — ▸ когато е сгъната, ▾ когато е отворена (без триъгълника на браузъра), и броят редове в заглавието;
еднакво навсякъде. Редовете на наблюдаваните и на секторната карта (details.wt-item) са със своята стрелка пред тикъра.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — страницата на брифа от 19.10 (книгите, COT, 13F, Kullamägi).
Пускане: python test_collapsibles.py
"""
import sys, json, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_collapse_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(B19, publish=False)

print("── 1. правилото — едно за всички сгънати секции ──")
css = page[page.index("<style"):page.index("</style>")]
for rule in ('details:not(.wt-item) > summary { list-style: none;', 'details:not(.wt-item) > summary::-webkit-details-marker { display: none; }',
             'details:not(.wt-item) > summary::before { content: "▸ ";', 'details:not(.wt-item)[open] > summary::before { content: "▾ "; }'):
    assert rule in css, rule
assert "list-style-position: inside" not in css                                                        # до 03.11: триъгълникът на браузъра при книгите на CANSLIM
print("  ✓ ▸ / ▾ за всеки <details> (без wt-item — там стрелката е пред тикъра); без триъгълника на браузъра")

print()
print("── 2. броят редове в заглавието на всяка сгъната секция (РЕАЛНИЯТ бриф от 19.10) ──")
sums = [re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        for m in re.finditer(r'<details(?![^>]*wt-item)([^>]*)>\s*<summary[^>]*>(.*?)</summary>', page, re.S)]
assert len(sums) >= 3, sums
no_count = [s for s in sums if not re.search(r"\d", s)]
assert not no_count, no_count
for s in sums:
    print(f"  · {s[:120]}")
print(f"  ✓ {len(sums)} сгънати секции — всяка с брой в заглавието")
print("\n✅ test_collapsibles: всичко мина")
