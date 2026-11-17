"""
17.11.2026 (пакет 1, т. 5): името на компанията след тикъра — навсякъде, и никога тикърът два пъти. Реално 17.11: картата на CSX в CANSLIM — „CSX CSX“ (името „CSX Corporation“
без правното окончание е „CSX“). Сега render.cname_t: име = тикъра или без име → само тикърът и ред в лога. И старата функция за заглавието на картата
(names.strip_legal) вече не оставя „Merck &“: „Merck & Company, Inc.“ → „Merck“.

РЕАЛНО: tests/fixtures/why_here_cards_2026-11-17.json (CSX, RGA … от 17.11); имената „CSX Corporation“, „Merck & Company, Inc.“, „Eli Lilly and Company“ — от картите в брифовете
(Yahoo); brief_2026-10-19.json — рамката. СИНТЕТИЧНО (означено): т. 3 — CSX, сложен в радара и като Watchlist карта.
Пускане: python test_ticker_once.py
"""
import sys, json, copy, re, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_tick1_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render, names

print("── 1. РЕАЛНО: имената ──")
assert [names.display_name(x) for x in ("Merck & Company, Inc.", "Eli Lilly and Company", "Johnson & Johnson", "AT&T Inc.", "Procter & Gamble Company")] == \
    ["Merck", "Eli Lilly", "Johnson & Johnson", "AT&T", "Procter & Gamble"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    assert render.cname_t("CSX Corporation", "CSX") == "" and render.cname_t(None, "ZZZQ") == ""
    assert render.cname_t("Reinsurance Group of America, Incorporated", "RGA") == "Reinsurance Group of America"
assert "[names] CSX: името съвпада с тикъра" in buf.getvalue() and "[names] ZZZQ: без име" in buf.getvalue()
print("  ✓ „Merck“, „Eli Lilly“ (без висящо „&“ / „and“); CSX → само тикърът, ред в лога")

print("── 2. шаблонът: никъде raw cname до тикър ──")
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "|cname(" not in tpl and "|cname }}" not in tpl and tpl.count("|cname_t(") >= 7
print("  ✓ картите (Action, Watchlist), QM, GLB, сплитовете, EP — през cname_t")

print("── 3. страницата и имейлът със CSX като Watchlist карта (СИНТЕТИЧНО поставена; полетата — РЕАЛНИ от 17.11) ──")
FX = {c["ticker"]: c for c in json.loads((ROOT / "tests" / "fixtures" / "why_here_cards_2026-11-17.json").read_text(encoding="utf-8"))["cards"]}
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B)
card = copy.deepcopy(b["watchlist"][0]); card.update(FX["CSX"]); card.update({"ticker": "CSX", "company": "CSX Corporation"})
b["watchlist"] = [card] + b["watchlist"][1:]
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
    mail = render.render_email(b)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
assert "CSX CSX" not in txt and "CSX · CSX" not in txt and "CSX CSX" not in re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", mail))
print("  ✓ „CSX CSX“ — нито на страницата, нито в имейла")
print("\n✅ test_ticker_once: всичко мина")
