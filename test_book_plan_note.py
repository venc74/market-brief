"""
19.10.2026 · етап 2, т. 18б (дребните от 16.10, "ZBRA бележка"): buy-stop карта с ЧАКАЩ запис в книгата показва плана на книгата, когато стопът или целта на картата се
различават. Картата смята стопа наново всеки ден (15-баровото дъно −1%), записът пази плана от първия ден — ZBRA 16.10: картата стоп $360.30 / цел $451.80, книгата (от 14.10)
$359.54 / $453.32; нивото е същото ($390.80), затова бележката "книгата следи ниво $X" не се появи. Сега — ред на картата и в имейла:
"Книгата пази плана от 14.10: стоп $359.54, цел 2R $453.32 (картата днес: стоп $360.30, цел $451.80) — резултатът в книгата е по нейния план."

РЕАЛНО: картата на ZBRA от брифа на 16.10 (tests/fixtures/brief_2026-10-16.json) и от 14.10 (brief_2026-10-14.json); записът ZBRA_2026-10-14_buystop
(tests/fixtures/zbra_buystop_record_2026-10-14.json). СИНТЕТИЧНО (означено): временните docs/ и data/.
Пускане: python test_book_plan_note.py
"""
import sys, json, pathlib, tempfile, io, contextlib, copy, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_bpn_")
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DATA_DIR.mkdir()
from src import setup_rules, render

FX = ROOT / "tests" / "fixtures"
REC = json.loads((FX / "zbra_buystop_record_2026-10-14.json").read_text(encoding="utf-8"))["record"]
B16 = json.loads((FX / "brief_2026-10-16.json").read_text(encoding="utf-8"))
B14 = json.loads((FX / "brief_2026-10-14.json").read_text(encoding="utf-8"))
card16 = copy.deepcopy(next(c for c in B16["watchlist"] if c["ticker"] == "ZBRA"))
card14 = copy.deepcopy(next(c for c in B14["watchlist"] if c["ticker"] == "ZBRA"))
assert (REC["status"], REC["buy_stop"], REC["stop_loss"], REC["target_1"]) == ("pending", 390.8, 359.54, 453.32)
assert (card16["plan_preview"]["stop_loss"], card16["plan_preview"]["target_1"], card16["levels"]["stop"]) == (360.3, 451.8, 360.3)
WANT = "Книгата пази плана от 14.10: стоп $359.54, цел 2R $453.32 (картата днес: стоп $360.30, цел $451.80) — резултатът в книгата е по нейния план."

print("── 1. РЕАЛНАТА карта от 16.10 срещу записа от 14.10 ──")
st = setup_rules.apply_book_window(copy.deepcopy(card16["setup"]), REC, "2026-10-16")
assert st["book_plan"] == {"from": "2026-10-14", "level": 390.8, "stop": 359.54, "target": 453.32} and "book_level" not in st     # нивото е същото
assert setup_rules.book_plan_note(st, card16["plan_preview"], card16["levels"]) == WANT
print("  ✓", WANT)

print()
print("── 2. същият план (РЕАЛНАТА карта от 14.10 — първият ден) → без ред ──")
st14 = setup_rules.apply_book_window(copy.deepcopy(card14["setup"]), {**REC}, "2026-10-14")
assert setup_rules.book_plan_note(st14, card14["plan_preview"], card14.get("levels")) is None
assert setup_rules.book_plan_note({}, card16["plan_preview"]) is None and setup_rules.book_plan_note(st, None) is None
print("  ✓ на 14.10 картата и книгата са с един план — без ред; без запис / без план — без ред")

print()
print("── 3. страницата и имейлът ──")
b = copy.deepcopy(B16)
z = next(c for c in b["watchlist"] if c["ticker"] == "ZBRA"); z["setup"] = st
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
with contextlib.redirect_stdout(io.StringIO()):
    page = flat(render.render_dashboard(copy.deepcopy(b), publish=False))
    mail = flat(render.render_email(copy.deepcopy(b)))
assert WANT in page and WANT in mail
print("  ✓ редът е на картата (под 'Ако се задейства') и в имейла (под Buy-stop / Stop)")
print("\n✅ test_book_plan_note: всичко мина")
