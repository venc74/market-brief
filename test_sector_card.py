"""
19.10.2026 · етап 2, т. 18 (дребните от 16.10): секторната карта.

  • Изборът кои сектори са на картата — от КОДА: водещите (RS > 0 и на 4, и на 12 седмици, или RS на 6-месечен връх; правилото на sector_layer.leading_sectors, до 6). Измерено
    върху 394 реда на картата в 89 брифа: 132 бяха сектори, които кодът не смята за водещи (19.10: GDX с RS −8.33% за 4 седмици), 26 пъти водещ липсваше. Веригата е на
    модела; неговите вериги за неводещи сектори → един ред под картата.
  • Хоризонтът — форматиран от кода: на 16.10 моделът върна [4, 12], [4], [12] (прозорците на RS) и страницата показа "Хоризонт: [4, 12] седмици".
  • Сурови имена на полета в прозата → думи (в историята: rs_chg_4w/12w(_pct) 34 пъти, laggard_persistence(_pct) 25, rs_at_6m_high 15, sizing_factor 10, …;
    "leading" се сменя само като поле — "leading=true"; "leading indicator" е английски израз).

РЕАЛНО: tests/fixtures/brief_2026-10-16.json и brief_2026-10-19.json (ротацията от кода, веригите и хоризонтите на модела). СИНТЕТИЧНО (означено): хоризонтите в раздел 3
(освен [4, 12]), фразите с "leading", празната ротация.
Пускане: python test_sector_card.py
"""
import sys, json, pathlib, tempfile, io, contextlib, copy, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_sector_")
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DATA_DIR.mkdir()
from src import sector_claims as sc, render, ai_brief

FX = ROOT / "tests" / "fixtures"
B16 = json.loads((FX / "brief_2026-10-16.json").read_text(encoding="utf-8"))
B19 = json.loads((FX / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))

print("── 1. кои сектори — от кода (РЕАЛНИТЕ брифове) ──")
c19 = sc.sector_card(B19["ai_macro"]["sector_logic"], B19["rotation"])
assert [r["etf"] for r in c19["rows"]] == ["XLE", "XLP", "XLV"] and all(r["chain"] for r in c19["rows"])
assert c19["omitted"] == [{"etf": "GDX", "sector": "Златодобив", "rs_line": "RS спрямо SPY: 4 седмици -8.33%, 12 седмици +15.62%"}]
assert c19["rows"][0]["rs_line"] == "RS спрямо SPY: 4 седмици +6.52%, 12 седмици +14.76% · RS на 6-месечен връх"
c16 = sc.sector_card(B16["ai_macro"]["sector_logic"], B16["rotation"])
assert [r["etf"] for r in c16["rows"]] == [r["etf"] for r in B16["rotation"] if r["leading"] or r["rs_at_6m_high"]][:6]
assert {o["etf"] for o in c16["omitted"]} == {e["etf"] for e in B16["ai_macro"]["sector_logic"]} - {r["etf"] for r in c16["rows"]}
assert sc.sector_card([], []) == {} and sc.sector_card(None, None) == {}
print(f"  ✓ 19.10: картата е {', '.join(r['etf'] for r in c19['rows'])} (водещите), GDX — под картата с RS −8.33% / +15.62%; 16.10: {', '.join(r['etf'] for r in c16['rows'])}, "
      f"под картата {', '.join(o['etf'] for o in c16['omitted'])}")

print()
print("── 2. сурови имена на полета → думи ──")
xlp = next(x["chain"] for x in B16["ai_macro"]["sector_logic"] if x["etf"] == "XLP")
assert "confirmed_laggard: true" in xlp and "laggard_persistence_pct" in xlp
w = sc.field_words(xlp)
assert not re.search(r"\b(?:rs_chg_\w+|laggard_persistence\w*|confirmed_laggard)\b", w) and "потвърдено изоставащ" in w and "дял на изоставането (12 седмици)" in w
for x in B16["ai_macro"]["sector_logic"] + B19["ai_macro"]["sector_logic"]:
    assert not re.search(r"\b(?:rs_chg_\w+|laggard_persistence\w*|rs_at_6m_high|confirmed_laggard|sizing_factor|level_percentile)\b", sc.field_words(x["chain"])), x["etf"]
assert sc.field_words("Copper е leading indicator; XLE leading=true, XLK leading: false") == "Copper е leading indicator; XLE водещ, XLK не е водещ"     # СИНТЕТИЧНО
assert sc.field_words("rs_at_6m_high=false означава") == "RS не е на 6-месечен връх означава"
print("  ✓ XLP 16.10: 'confirmed_laggard: true' → 'потвърдено изоставащ', 'laggard_persistence_pct' → 'дял на изоставането (12 седмици)'; във всичките 8 вериги — без имена на полета; 'leading indicator' остава")

print()
print("── 3. хоризонтът ──")
assert [x["horizon_weeks"] for x in B16["ai_macro"]["sector_logic"]] == [[4, 12], [4, 12], [4], [12]]
assert sc.horizon_text([4, 12]) == "4–12 седмици" and sc.horizon_text([4]) == "4 седмици" and sc.horizon_text(4) == "4 седмици"
assert sc.horizon_text("2-6") == "2–6 седмици" and sc.horizon_text(None) == "" and sc.horizon_text("скоро") == "" and sc.horizon_text(True) == ""
print("  ✓ [4, 12] → '4–12 седмици', [4] → '4 седмици', '2-6' → '2–6 седмици', празно/текст → без ред")

print()
print("── 4. страницата ──")
b = copy.deepcopy(B19); b["sector_card"] = c19
with q():
    page = flat(render.render_dashboard(b, publish=False))
sec = page.split("Секторна карта · следващите 2–6 седмици", 1)[1].split("Геополитически тези", 1)[0]
assert "RS спрямо SPY: 4 седмици +6.52%, 12 седмици +14.76% · RS на 6-месечен връх" in sec and "Не са на картата (AI даде верига, но не са водещи по RS): GDX (4 седмици -8.33%, 12 седмици +15.62%)." in sec
assert "Златодобив" not in sec.split("Не са на картата")[0]
old = copy.deepcopy(B16); old.pop("sector_card", None)                                  # стар бриф: веригите на модела, хоризонтът — форматиран
with q():
    page_old = flat(render.render_dashboard(old, publish=False))
assert "Хоризонт: 4–12 седмици" in page_old and "[4, 12]" not in page_old and "laggard_persistence_pct" not in page_old
print("  ✓ 19.10: водещите с RS реда от кода, GDX в реда под картата; стар бриф (16.10) — веригите на модела с 'Хоризонт: 4–12 седмици' вместо '[4, 12] седмици'")

print()
print("── 5. промптът и main ──")
assert ai_brief._leaders_text(B19["rotation"]) == "XLE, XLP, XLV" and "няма водещ сектор днес" in ai_brief._leaders_text([])
src = (ROOT / "src" / "ai_brief.py").read_text(encoding="utf-8")
assert "{_leaders_text(rotation)}" in src and '"horizon_weeks" е ЕДНО число от 2 до 6' in src
assert "sector_card = steps.step(\"sector_card\", lambda: sector_claims.sector_card((ai_macro or {}).get(\"sector_logic\"), rotation)" in (ROOT / "src" / "main.py").read_text(encoding="utf-8")
print("  ✓ промптът носи водещите по кода (19.10: XLE, XLP, XLV), хоризонт — едно число 2–6, думи вместо имена на полета; main записва sector_card")
print("\n✅ test_sector_card: всичко мина")
