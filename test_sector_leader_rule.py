"""
04.11.2026 · четвърти преглед, Н2, вариант (а): картата показва водещите сектори по is_leader — същото правило като скрийнинга; SECT✓ и входът на скрийнинга (leading_sectors) не се променят.
До 04.11 картата броеше по думата „води пазара“ (мъртва зона ±1), скрийнингът — по is_leader. Думата до RS остава (същата като при наблюдаваните).

РЕАЛНО: tests/fixtures/sector_leaders_2026-11-03.json (картата и ротацията от брифовете на 02.11 и 03.11 — двата дни със записана карта); tests/fixtures/brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): ред с „води пазара“ и потвърдено изоставащ (реалният случай от 21.10 — XLY, XLP — в числата на ротацията от онзи ден няма карта), ред без ротация.
Пускане: python test_sector_leader_rule.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_sectorlead_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import sector_layer as sl, render

FX = json.loads((ROOT / "tests" / "fixtures" / "sector_leaders_2026-11-03.json").read_text(encoding="utf-8"))["days"]
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))

print("── 1. реплей на записаните карти: сменя се само 02.11, XLU ──")
got = {}
for day, d in FX.items():
    old_rows = copy.deepcopy(d["sectors"])
    rows = sl.mark_leaders(copy.deepcopy(d["sectors"]), d["rotation"])
    word = [r["etf"] for r in rows if r["word"] == "води пазара"]
    lead = [r["etf"] for r in rows if r["leader"]]
    got[day] = (sorted(set(word) ^ set(lead)), sl.board_summary(old_rows), sl.board_summary(rows))
assert got["2026-11-02"][0] == ["XLU"] and got["2026-11-03"][0] == []
xlu = next(r for r in FX["2026-11-02"]["sectors"] if r["etf"] == "XLU")
assert (xlu["rs_4w"], xlu["rs_12w"], xlu["word"]) == (11.05, 0.98, "набира сила")
assert got["2026-11-02"][1].startswith("Водят 4 от 11") and got["2026-11-02"][2].startswith("Водят 5 от 11")
assert got["2026-11-03"][1] == got["2026-11-03"][2] and got["2026-11-03"][2].startswith("Водят 7 от 11")
assert got["2026-11-02"][1].split("(първите три")[1] == got["2026-11-02"][2].split("(първите три")[1]       # останалото в изречението — същото
print("  ✓ 02.11: XLU (RS +11.05 / +0.98, „набира сила“) — „Водят 4 от 11“ → „Водят 5 от 11“; 03.11: без промяна („Водят 7 от 11“)")

print()
print("── 2. SECT✓ и входът на скрийнинга — не се променят ──")
for day, d in FX.items():
    rot = d["rotation"]
    before = [s["etf"] for s in sl.leading_sectors(copy.deepcopy(rot))]
    sl.mark_leaders(copy.deepcopy(d["sectors"]), rot)
    assert [s["etf"] for s in sl.leading_sectors(rot)] == before and all("leader" not in r for r in rot)      # ротацията не се пипа
src = (ROOT / "src" / "sector_layer.py").read_text(encoding="utf-8")
assert 'leaders = [s for s in rotation if is_leader(s)]' in src and "mark_leaders(board_rows(data, spy, etfs), rotation)" in src
main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "rotation=rotation), fallback={}," in main and "run_screen([s[\"sector\"] for s in leaders], leaders=leaders)" in main
print("  ✓ leading_sectors дава същото и не получава нови полета; main подава ротацията само на картата")

print()
print("── 3. крайните случаи (СИНТЕТИЧНО) ──")
rows = [{"etf": "AAA", "word": "води пазара"}, {"etf": "BBB", "word": "в крак с пазара"}, {"etf": "CCC", "word": "води пазара"}]
sl.mark_leaders(rows, [{"etf": "AAA", "leading": True, "confirmed_laggard": True}, {"etf": "BBB", "leading": True}])
assert [r["leader"] for r in rows] == [False, True, True] and rows[0]["confirmed_laggard"] is True and rows[2]["confirmed_laggard"] is False     # CCC — без ред в ротацията: по думата
assert all(r["leader"] == (r["word"] == "води пазара") for r in sl.mark_leaders(copy.deepcopy(FX["2026-11-02"]["sectors"]), None))       # ротацията не се изтегли
assert sl.board_summary([{"etf": "AAA", "sector": "Стар", "word": "води пазара"}]).startswith("Водят Стар")                  # стар бриф без полето — по думата
print("  ✓ потвърдено изоставащ не е водещ; без ред в ротацията — по думата; стар бриф без полето — по думата")

print()
print("── 4. страницата (РЕАЛНО 02.11) ──")
b = copy.deepcopy(B19)
rows = sl.mark_leaders(copy.deepcopy(FX["2026-11-02"]["sectors"]), FX["2026-11-02"]["rotation"])
rows[0]["word"], rows[0]["leader"], rows[0]["confirmed_laggard"] = "води пазара", False, True                                # СИНТЕТИЧНО: първият ред — потвърдено изоставащ
b["sector_board"] = {"sectors": rows, "summary": sl.board_summary(rows), "subsectors": [], "as_of": "2026-10-30"}
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
s = page[page.index("Секторна карта"):]; s = s[:s.index("</section>")]
fs = flat(s)
assert "XLU водещ" in fs and s.count(">водещ</span>") == sum(r["leader"] for r in rows) and "потвърдено изоставащ" in fs
assert "„Водещ“ — RS над 0 и на 4, и на 12 седмици" in fs and "същото правило като скрийнинга и SECT✓" in fs
del_b = copy.deepcopy(B19); del_b["sector_board"] = {"sectors": copy.deepcopy(FX["2026-11-02"]["sectors"]), "summary": "x", "subsectors": [], "as_of": "2026-10-30"}
with contextlib.redirect_stdout(io.StringIO()):
    old = render.render_dashboard(del_b, publish=False)
assert ">водещ</span>" not in old and "„Водещ“ — RS над 0" not in old                                                   # стар бриф — без знака и без бележката
print("  ✓ знак „водещ“ при XLU (и при всички по is_leader), бележка под таблицата; стар бриф — както досега")
print("\n✅ test_sector_leader_rule: всичко мина")
