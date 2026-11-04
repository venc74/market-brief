"""
04.11.2026 · прегледът, т. 6: AI текстът на картите не тълкува институционална собственост над 100% — обичайно двойно броене в 13F. WST на 04.11: „103.6% — изчерпан buying pool“.
Три нива: моделът не получава числото (при > 100), правилото е в системния промпт, а кодът маха текст, който пак го тълкува. На картата числото остава със знак „двойно броене“.

РЕАЛНО: tests/fixtures/inst_over_100_2026-11-04.json (текстовете от брифовете, бележката — вътре); tests/fixtures/brief_2026-10-19.json — рамката. СИНТЕТИЧНО (означено): отговорът на модела (подменен), стойността 103.6 върху реалната карта от 19.10.
Пускане: python test_inst_over_100.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_inst_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import ai_brief, render

FX = {c["ticker"]: c for c in json.loads((ROOT / "tests" / "fixtures" / "inst_over_100_2026-11-04.json").read_text(encoding="utf-8"))["cards"]}
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. кодът маха тълкуването (РЕАЛНИТЕ текстове) ──")
cards = copy.deepcopy(list(FX.values()))
with q():
    done = ai_brief.strip_inst_over_100(cards)
by = {c["ticker"]: c for c in cards}
assert set(done) == {"WST", "NBIX", "ZBRA", "EXPD"}, done
assert not any("buying pool" in r for r in by["WST"]["ai"]["risks"]) and len(by["WST"]["ai"]["risks"]) == len(FX["WST"]["ai"]["risks"]) - 1
assert "103.9%" not in by["NBIX"]["ai"]["why_now"] and "103.9%" in FX["NBIX"]["ai"]["why_now"] and by["NBIX"]["ai"]["why_now"]                       # останалите изречения остават
assert not any("100.1%" in x for x in by["EXPD"]["ai"]["catalysts"]) and any("100.1%" in x for x in FX["EXPD"]["ai"]["catalysts"])
assert "надхвърля 100%" in FX["ZBRA"]["ai"]["business_bg"] and "надхвърля 100%" not in by["ZBRA"]["ai"]["business_bg"] and by["ZBRA"]["ai"]["business_bg"].startswith("Zebra Technologies")
assert by["BAC"]["ai"] == FX["BAC"]["ai"] and FX["BAC"]["inst_ownership_pct"] == 71.4                                                              # „71.4% … под 100%“ — не се пипа
assert ai_brief.strip_inst_over_100([]) == [] and ai_brief.strip_inst_over_100([{"ticker": "X", "inst_ownership_pct": 120.0}]) == []
print("  ✓ WST („изчерпан buying pool“), NBIX, ZBRA, EXPD — махнато само изречението / реда; BAC (71.4%, „под 100%“) — непокътнат")

print()
print("── 2. моделът не получава числото; правилото е в промпта (СИНТЕТИЧНО: отговорът) ──")
sent = []
real = ai_brief._call_claude
ai_brief._call_claude = lambda system, user, **k: (sent.append((system, user)), '{"tickers": []}')[1]
try:
    with q():
        ai_brief.ticker_narratives([{"ticker": "AAA", "inst_ownership_pct": 103.6, "price": 10, "setup": {}}, {"ticker": "BBB", "inst_ownership_pct": 71.4, "price": 10, "setup": {}}], [], "Defensive")
finally:
    ai_brief._call_claude = real
sysp, user = sent[0]
assert "103.6" not in user and "71.4" in user and "Институционална собственост над 100% не е сигнал" in sysp and "двойно броене в 13F" in sysp
print("  ✓ при 103.6 полето липсва в заявката; при 71.4 — стои; забраната е в системния промпт")

print()
print("── 3. картата: числото остава, със знак ──")
b = copy.deepcopy(B19)
c0 = (b.get("action") or b["watchlist"])[0]
c0["inst_ownership_pct"] = 103.6                                                                  # СИНТЕТИЧНО: стойността
key = "action" if b.get("action") else "watchlist"
with q():
    page = render.render_dashboard(b, publish=False)
main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert main.index("ai_brief.strip_inst_over_100(candidates)") < main.index('sector_claims_fixed = steps.step("prose_checks"')
if key == "action":
    assert "103.6%" in page and "двойно броене" in htmllib.unescape(page)
print("  ✓ проверката е в стъпката за AI текста; при карта с пълен план — „103.6% двойно броене“")
print("\n✅ test_inst_over_100: всичко мина")
