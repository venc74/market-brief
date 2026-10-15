"""
15.10.2026 · макро текстът · твърдения за ПРАВИЛОТО на режима (src/regime_claims.py: rule_problems) (запасът до смяна на режима е в test_regime_margin.py).

Реален дефект (regime_comment на 15.10): "ако един зелен стане червен при 0 червени сега, системата пак остава Offensive; нужни са 2 червени за Defensive" — по thermometer._count_regime
Offensive иска 0 червени, т.е. един червен → Defensive. Промптът вече носеше rule_text ("2 червени → Defensive"), моделът го прочете като "един червен не стига".

РЕАЛНО: tests/fixtures/ai_macro_texts_2026-06-13_10-15.json — макро текстовете, режимът, броенето и индикаторите от ВСИЧКИ 87 брифа с термометър (173 текста, 13.06–15.10);
tests/fixtures/brief_2026-10-15.json — брифът от 15.10 (термометър, distribution days SPY 8 / QQQ 7, IEI/HYG RoC 87.7 при праг 90); brief_2026-10-09.json (override IEI/HYG над прага).
СИНТЕТИЧНО (маркирано): граничните изречения, подменените термометри в т. 4, подменените _call_claude.
Пускане: python test_regime_rule_claims.py
"""
import sys, json, pathlib, contextlib, io, copy, re, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_rrc_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import regime_claims as rc, ai_brief, render

FX = json.loads((ROOT / "tests" / "fixtures" / "ai_macro_texts_2026-06-13_10-15.json").read_text(encoding="utf-8"))["briefs"]
B15 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-15.json").read_text(encoding="utf-8"))
B09 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-09.json").read_text(encoding="utf-8"))

print("── 1. РЕАЛНИЯТ regime_comment от 15.10 ──")
f15 = rc.facts(B15["thermometer"])
rcm = B15["ai_macro"]["regime_comment"]
bad = "ако един зелен стане червен при 0 червени сега, системата пак остава Offensive; нужни са 2 червени за Defensive"
assert bad in rcm
probs = rc.check(rcm, f15)
assert [p["code"] for p in probs] == ["rule", "rule"] and all(bad in p["sentence"] for p in probs), probs
assert "за Defensive са нужни 2 червени" in probs[0]["why"] and "остава Offensive" in probs[1]["why"]
new, _ = rc.clean(rcm, f15)
assert bad not in new and f15["rule_text"] in new and new.count(f15["rule_text"]) == 1
assert "Режимът Offensive е технически оправдан от броенето" in new and len(rc._sentences(new)) == len(rc._sentences(rcm)) - 1 + len(rc._sentences(f15["rule_text"]))   # едно изречение → rule_text, останалите — непокътнати
assert rc.check(new, f15) == []
assert "ЕДИН червен е достатъчен, за да не е Offensive (1 или 2 червени → Defensive)" in f15["rule_text"]
print("  ✓ двата грешни дяла на изречението → 'rule'; изречението е заменено с rule_text; повторна проверка — чисто")
print("    rule_text:", f15["rule_text"])

print()
print("── 2. историята: всичките 173 РЕАЛНИ текста ──")
hits, n = [], 0
for day, b in FX.items():
    fb = rc.facts({"indicators": b["indicators"]})
    for field in ("macro_brief", "regime_comment"):
        if b.get(field):
            n += 1
            hits += [(day, p["code"]) for p in rc.check(b[field], fb) if p["code"] == "rule"]
assert n == 173 and hits == [("2026-07-23", "rule"), ("2026-08-20", "rule"), ("2026-09-10", "rule"), ("2026-10-15", "rule"), ("2026-10-15", "rule")], hits
print("  ✓ 5 флага в 4 изречения: 23.07 ('1 червен … правилото би дало Offensive'), 20.08 ('8/8 зелени за Offensive'), 10.09 ('изисква повече от 7/9 зелени'), 15.10 (две твърдения)")
print("    верните описания на правилото не се флагват: 'изисква поне 4 зелени и 0 червени' (13.10, 15.10), '1 червен … дава Defensive' (09.10), 'само 1 червен да блокира Offensive' (21.08)")

print()
print("── 3. граници (СИНТЕТИЧНИ изречения) ──")
ok = lambda s, f=f15: [p for p in rc.check_sentence(s, f) if p["code"] == "rule"] == []
assert ok("Offensive изисква поне 4 зелени и 0 червени.") and ok("За Cash са нужни 3 червени.") and ok("Нужни са 3 червени за Cash.")
assert ok("Един червен е достатъчен, за да падне режимът до Defensive.") and ok("Ако един зелен стане червен, режимът става Defensive.")
assert not ok("За Defensive са нужни два червени индикатора.") and not ok("Нужни са 2 червени за Cash.") and not ok("Offensive изисква поне 5 зелени.")
assert not ok("Ако един индикатор стане червен, режимът все още остава Offensive.")
red_f = rc.facts({"indicators": [{"name": "SPY тренд", "status": "green"}] * 4 + [{"name": "Market Breadth (% над 40dMA)", "status": "red"}]})
assert rc.check_sentence("Market Breadth сам по себе си дава Defensive днес.", red_f) == []                     # червен индикатор наистина сам прави режима Defensive
assert [p["code"] for p in rc.check_sentence("Market Breadth сам по себе си дава Defensive днес.", f15)] == ["solo"]   # при жълт Breadth (15.10) — не
print("  ✓ верни правила — без флаг; грешен брой червени за режим, грешен праг на зелените, 'остава Offensive' — флаг; червен индикатор 'сам по себе си → Defensive' е вярно")

print()
print("── 4. през macro_and_sector_brief: РЕАЛНИЯТ текст от 15.10 през подменен модел ──")
prompts = []
def fake_claude(system, user, **k):
    prompts.append(user)
    return json.dumps({"macro_brief": "Кратко.", "sector_logic": [], "regime_comment": rcm}, ensure_ascii=False)
ai_brief._call_claude = fake_claude
with contextlib.redirect_stdout(io.StringIO()):
    res = ai_brief.macro_and_sector_brief({}, [], copy.deepcopy(B15["thermometer"]))
assert f15["rule_text"] in prompts[0] and bad not in res["regime_comment"] and [x["code"] for x in res["regime_claims_fixed"]] == ["rule", "rule"]
print("  ✓ промптът носи правилото; отговорът е поправен, протоколът е в regime_claims_fixed")
print("\n✅ test_regime_rule_claims: всичко мина")
