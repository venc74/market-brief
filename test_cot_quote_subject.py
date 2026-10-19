"""
19.10.2026 · етап 2, доп. т. 7: цитатът на модела за механизма в COT cross тезата излизаше без подлог ("Закупува оборудване и съставки …") — показва се с името на компанията отпред,
ако в първите 4 думи няма дума от името (≥ 4 букви) или тикъра. Само показване.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — cross тезите на COT пазарите от брифа (YUMC "Закупува оборудване …", MCD "Генерира значителна част от приходите си …"); всички реални
брифове — 106 от 167 различни цитата без подлог (измерено извън теста). СИНТЕТИЧНО (маркирано): граничните цитати.
Пускане: python test_cot_quote_subject.py
"""
import sys, re, json, copy, pathlib, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cotq_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import render

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
T = {t["ticker"]: t for m in B19["cot"] for t in ((m.get("cross_sector_thesis") or {}).get("tickers") or []) if isinstance(t, dict)}
y, mc = T["YUMC"], T["MCD"]
assert y["quote"].startswith("Закупува оборудване и съставки от европейски доставчици") and mc["quote"].startswith("Генерира значителна част от приходите си в евро")
assert render.cot_quote(y) == "Yum China: " + y["quote"] and render.cot_quote(mc) == "McDonald's: " + mc["quote"]
assert render.cot_quote({"ticker": "SCHW", "company": "The Charles Schwab Corporation", "quote": "Schwab реинвестира клиентски парични средства"}).startswith("Schwab реинвестира")   # СИНТЕТИЧНО: има подлог
assert render.cot_quote({"ticker": "TSN", "company": "Tyson Foods, Inc.", "quote": "компанията използва соево брашно"}) == "Tyson Foods: компанията използва соево брашно"   # СИНТЕТИЧНО
assert render.cot_quote({"ticker": "X", "company": "", "quote": ""}) == ""
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(copy.deepcopy(B19)))))
assert "Yum China: Закупува оборудване и съставки от европейски доставчици" in page
print("  ✓ YUMC: 'Yum China: Закупува оборудване …'; MCD: 'McDonald's: Генерира …'; цитат с подлог ('Schwab реинвестира …') — непокътнат")
print("\n✅ test_cot_quote_subject: всичко мина")
