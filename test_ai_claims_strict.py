"""
19.11.2026 (пакет 19.11, т. 8): проверката на AI текста („защо“ на новините и макро разказа) — групи и организации (хусити, НАТО, МВФ …), валути (рубла, юан, йена …) и
усилващи думи („рязко“, „по-агресивно“, „драматично“): ако ги няма в подаденото заглавие (за „защо“ — заглавията и резюметата на групата; за макро — само заглавията), изречението
пада (claim_check.STRICT). Усилващата дума след отрицание („не очаква рязко сътресение“) и предположението („може рязко да …“) не са твърдения. Правопис: удвоена гласна —
„риисковата“ → „рисковата“ (ai_brief._fix_double_vowels), само когато думата е рядка, а поправената — позната.

РЕАЛНО: tests/fixtures/ai_claims_2026-11-19.json — разказът, новините и входът от брифа на 19.11; речникът — tests/fixtures/bg_vocab_2026-10-20.json („рисковата“ 13 пъти).
СИНТЕТИЧНО (означено): изреченията в т. 3.
Пускане: python test_ai_claims_strict.py
"""
import sys, json, copy, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
config.BG_VOCAB_FILE = str(ROOT / "tests" / "fixtures" / "bg_vocab_2026-10-20.json")
from src import claim_check as cc, causal_check as ca, ai_brief as ab

FX = json.loads((ROOT / "tests" / "fixtures" / "ai_claims_2026-11-19.json").read_text(encoding="utf-8"))
B = FX["b19"]
src_of = lambda n: " ".join([n["headline"]] + [a["headline"] for a in n.get("also") or []])

print("── 1. РЕАЛНО: „защо“ на новините от 19.11 ──")
by = {n["headline"][:30]: n for n in B["news"]}
fed = next(n for n in B["news"] if n["headline"].startswith("Fed officials expect more rate hikes"))
_, r = cc.check(fed["why"], src_of(fed))
assert r and r[0]["claims"] == ["агресивно"], r
tri = next(n for n in B["news"] if n["headline"].startswith("Trump holds talks separately with Putin and Xi"))
_, r = cc.check(tri["why"], src_of(tri))
assert r and set(r[0]["claims"]) == {"рублата", "юана"}, r
oil = next(n for n in B["news"] if n["headline"].startswith("Oil prices steady as Middle East shipping attacks"))
_, r = cc.check(oil["why"], src_of(oil))
assert r and r[0]["claims"] == ["Червено море"], r                                 # хусити — в „също“ (Houthi missile threat towards Riyadh), Червено море — никъде
print("  ✓ „по-агресивно затягане“ (Fed), „рубла“ / „юан“ (Тръмп–Си–Путин), „… Червено море“ (петролът; хусити — в „също“ на групата) — без опора в заглавията → изречението пада")

print("── 2. РЕАЛНО: макро разказът от 19.11 — само заглавията за новите думи ──")
src = ab.narrative_text(B["macro"], B["rotation"], B["thermometer"], B["news"], B["crypto"], day=B["market_day"])
new, rem = cc.check(B["ai_macro"]["macro_brief"], src, strict=" ".join(ca.headlines_of(B["news"], B["crypto"])))
assert len(rem) == 1 and rem[0]["claims"] == ["Червено море", "агресивно"] and rem[0]["sentence"].startswith("VIX скочи с над 40% за 5 сесии")
assert new.startswith("Базовият PCE за септември е 3.12% г/г")
_, rem2 = cc.check(B["ai_macro"]["macro_brief"], src)                                     # без strict — „защо“ (AI) щеше да го подкрепи
assert not any("агресивно" in x["claims"] for x in rem2)
print("  ✓ първото изречение пада („Червено море“ и „по-агресивно“ — само в „защо“ на модела, не в заглавие); без strict щеше да остане")

print("── 3. СИНТЕТИЧНО: отрицание, предположение, подкрепа ──")
assert cc.unsupported("Пазарът не очаква рязко сътресение.", "x", "VIX steady") == []
assert cc.unsupported("Атаката може рязко да обърне спада.", "x", "Attack on pipeline") == []
assert cc.unsupported("Петролът поскъпна рязко.", "x", "Oil prices jump as Houthi attacks mount") == []
assert cc.unsupported("Хусити атакуваха кораби.", "x", "Oil prices jump as Houthi attacks mount") == []
assert cc.unsupported("Йената поскъпна.", "x", "Yen jumps after BOJ minutes") == [] and cc.unsupported("Йената поскъпна.", "x", "BOJ minutes show debate") == ["йената"]
print("  ✓ „не очаква рязко“, „може рязко да“ — не са твърдения; „рязко“ при „jump“, „хусити“ при „Houthi“, „йена“ при „Yen“ — с опора")

print("── 4. РЕАЛНО: правописът — „риисковата“ ──")
with contextlib.redirect_stdout(io.StringIO()):
    fixed = ab._fix_double_vowels(oil["why"])
assert "риисковата" in oil["why"] and "рисковата премия" in fixed and "риисковата" not in fixed
with contextlib.redirect_stdout(io.StringIO()):
    assert ab._fix_double_vowels("деескалацията и координираната политика влияят") == "деескалацията и координираната политика влияят"
    assert ab._fix_double_vowels("застрахователните полиции и компаниите") == "застрахователните полиции и компаниите"           # „-ии“ / „-иите“ — множествено число
print("  ✓ „риисковата“ → „рисковата“; „деескалацията“, „координираната“, „влияят“ — без промяна")
print("\n✅ test_ai_claims_strict: всичко мина")
