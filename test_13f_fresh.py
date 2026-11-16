"""
16.11.2026 (пакет 16.11, т. 11): 13F — (1) редът „следваща вълна около 16.11“ изчезна точно в деня на срока: на 16.11 Baupost и Pabrai са с нов 13F (13.11), секцията е цялата, а
по замисъл от 21.10 редът се пише само в свитите дни. (2) Таблицата загуби двата реда на Baupost (AMZN +20%, GOOG +16%) — те бяха от 13F за Q2; новият (Q3, 13.11) ги сменя и
сравнението е Q3 срещу Q2 — по замисъл. Но новите покупки на Baupost (HONA $175 млн, 3.5%; SITE $112 млн, 2.2%) не влязоха — таблицата е първите DATAROMA_MOVES_DISPLAY_LIMIT (8)
тикъра по стойност от всички мениджъри (Berkshire $28 млрд …): секцията се отвори заради подаването и не показа нищо от него. (3) „63 → 66“ е редът за CUSIP („Тикърите: по CUSIP 64 …
от 66 реда“ — всички суровини редове от 13F, не таблицата): новите подавания добавиха редове — не е грешка.
Сега: редът стои и в деня с ново подаване (кой, срокът, колко са подали), а редовете на новоподалите влизат в таблицата („· ново подаване“) — и извън първите 8.

РЕАЛНО: tests/fixtures/thirteenf_2026-11-13_16.json — 13F полетата от data/2026-11-13.json и 2026-11-16.json (изрязано 16.11.2026); brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): т. 3 — manager_top за Baupost (най-голямото движение — както би го дал dataroma от днешния 13F).
Пускане: python test_13f_fresh.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_13ff_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import data_rhythm as r, dataroma, render

FX = json.loads((ROOT / "tests" / "fixtures" / "thirteenf_2026-11-13_16.json").read_text(encoding="utf-8"))
B16, B13 = FX["b16"], FX["b13"]
BP, PB = "Сет Кларман · Baupost Group", "Мониш Пабрай · Dalal Street (Pabrai Investment Funds)"

print("── 1. РЕАЛНО: редът — и в деня с ново подаване ──")
x = r.thirteenf_rhythm(B16["superinvestor_status"], B13, "2026-11-16")
assert x["fresh"] and not x["compact"] and x["new"] == [PB, BP] and x["filed_for_quarter"] == 3
assert x["text"] == (f"13F: нови подавания — {PB} (13.11), {BP} (13.11); срокът за тримесечието до 30.09 — 16.11 (45 дни след края му), подали са 3 от 15"), x["text"]
assert B13["thirteenf_rhythm"]["text"] == "13F: последни 13F от 20.10 — следваща вълна около 16.11 (срокът е 45 дни след края на тримесечието)"     # свитият ден — както преди
assert r._quarter_end_for_wave("2026-11-16") == "2026-09-30" and r._quarter_end_for_wave("2027-02-16") == "2026-12-31"
print(f"  ✓ {x['text']}")

print("── 2. РЕАЛНО: защо изчезнаха двата реда на Baupost ──")
t13 = render.thirteenf_rows(B13["superinvestor_moves"], B13["superinvestor_exits"], [])
t16 = render.thirteenf_rows(B16["superinvestor_moves"], B16["superinvestor_exits"], [])
assert [(x["ticker"], x["action"], x["period"]) for x in t13 if x["manager"] == BP] == [("AMZN", "увеличена", "13F · 2026-08-13"), ("GOOG", "увеличена", "13F · 2026-08-13")]
assert not [x for x in t16 if x["manager"] == BP]
assert B16["superinvestor_status"]["filings"][BP] == "2026-11-13" and B13["superinvestor_status"]["filings"][BP] == "2026-08-13"
bp_new = [(n["ticker"], round(n["value"] / 1e6), n["pct_of_portfolio"]) for n in B16["superinvestor_new_positions"] if n["manager"] == BP]
assert bp_new == [("HONA", 175, 3.5), ("SITE", 112, 2.2)]
assert len(B16["superinvestor_moves"]) == 8 and min(m["value"] for m in B16["superinvestor_moves"]) > 9e8           # първите 8 — над $900 млн
print(f"  ✓ AMZN / GOOG бяха от Q2 (13.08) → Q3 ги сменя; новите HONA / SITE ($175 / $112 млн) са под първите 8 (> $900 млн)")

print("── 3. редовете на новоподалите влизат в таблицата ──")
top = {BP: [{"ticker": "HONA", "company": "HONEYWELL AEROSPACE INC", "action": "нова позиция", "value": 175426000.0, "pct_of_portfolio": 3.5, "period": "13F · 2026-11-13"}]}   # СИНТЕТИЧНО
fr = dataroma.fresh_rows(x["new"], top, B16["superinvestor_new_positions"])
assert [(f["manager"], f["ticker"], f["action"]) for f in fr] == [(BP, "HONA", "нова позиция"), (BP, "SITE", "нова позиция")]
assert dataroma.fresh_rows([], top, B16["superinvestor_new_positions"]) == []
rows = render.thirteenf_rows(B16["superinvestor_moves"], B16["superinvestor_exits"], [], fr)
bp_rows = [(x["ticker"], x["action"], x.get("fresh")) for x in rows if x["manager"] == BP]
assert bp_rows == [("HONA", "нова", True), ("SITE", "нова", True)] and len(rows) == len(t16) + 2
print("  ✓ Baupost: HONA, SITE — „нова · ново подаване“ (Pabrai — нищо над праговете)")

print("── 4. страницата ──")
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19); b.update(B16); b["thirteenf_rhythm"] = x; b["superinvestor_fresh"] = fr
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
sec = page[page.index("<h2>Superinvestor Positions — Last 13F</h2>"):]
sec = sec[:sec.index("</section>")]
assert x["text"] in sec and '<details class="si-full">' not in sec and "HONA" in sec and "· ново подаване" in sec
print("  ✓ редът над таблицата; HONA и SITE в таблицата; секцията — цялата")
print("\n✅ test_13f_fresh: всичко мина")
