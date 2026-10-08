"""
Макро текстът · броене на индикаторите и причина за режима като готови низове от кода + проверка на числовите твърдения (08.10.2026, src/regime_claims.py).

Реален дефект (макро текстът на 08.10): "3 жълти (Put/Call, MOVE, Fed Net Liquidity — последният само информативен и не влиза в броенето)" — кодът брои като жълти Put/Call, MOVE и Market
Breadth, а Fed Net Liquidity е информативен и не е в никоя група; и "breadth … само по себе си дава Defensive и при броене по правило" — не дава (режимът по броенето е правилото в
thermometer._count_regime; форсират само override-ите VIX, MOVE, IEI/HYG и червените distribution days).

РЕАЛНО: tests/fixtures/ai_macro_texts_2026-06-13_10-08.json — макро текстовете и индикаторите на термометъра от ВСИЧКИ 82 публикувани брифа с термометър (163 текста), включително 08.10.
СИНТЕТИЧНО (маркирано): граничните изречения, наборите индикатори за правилото, подменените _call_claude и regime_claims.clean (за отказ).
Пускане: python test_regime_claims.py
"""
import sys, json, pathlib, contextlib, io, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import regime_claims as rc, thermometer as th, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "ai_macro_texts_2026-06-13_10-08.json").read_text(encoding="utf-8"))["briefs"]
B = FX["2026-10-08"]
THERMO = {"regime": B["regime"], "indicators": B["indicators"]}

print("── 1. готовите низове за РЕАЛНИЯ термометър от 08.10 ──")
f = rc.facts(THERMO)
assert f["groups"]["green"] == ["SPY тренд", "VIX", "2Y/10Y спред", "VIX Term Structure"]
assert f["groups"]["yellow"] == ["Put/Call (SPY)", "MOVE (Bond Vol)", "Market Breadth (% над 40dMA)"] and f["groups"]["red"] == ["IEI/HYG (Credit Spread)"]
assert f["groups"]["informational"] == ["Fed Net Liquidity"] and f["groups"]["hidden"] == []
assert f["counts_text"] == ("4 зелени (SPY тренд, VIX, 2Y/10Y спред, VIX Term Structure) / 3 жълти (Put/Call (SPY), MOVE (Bond Vol), Market Breadth (% над 40dMA)) / "
                            "1 червен (IEI/HYG (Credit Spread)) от 8 видими; НЕ се броят (информативни): Fed Net Liquidity"), f["counts_text"]
assert B["counts"].startswith("4 зелени / 3 жълти / 1 червени от 8 видими")                                       # съвпада с броенето на самия термометър
print("  ✓ " + f["counts_text"])
print("  ✓ числата съвпадат с thermometer.counts на брифа: '" + B["counts"] + "'")

print()
print("── 2. правилото в текста = thermometer._count_regime (СИНТЕТИЧНИ набори индикатори) ──")
def mk(g, y, r, hidden=0):
    ind = [{"name": f"Z{i}", "status": "green"} for i in range(g)] + [{"name": f"Y{i}", "status": "yellow"} for i in range(y)] + [{"name": f"R{i}", "status": "red"} for i in range(r)]
    return ind + [{"name": f"H{i}", "status": "green", "hide": True} for i in range(hidden)]
assert th._count_regime(mk(4, 4, 0))[0] == "Offensive" and th._count_regime(mk(4, 3, 1))[0] == "Defensive" and th._count_regime(mk(4, 1, 2))[0] == "Defensive"
assert th._count_regime(mk(2, 3, 3))[0] == "Cash" and th._count_regime(mk(4, 1, 0, hidden=3))[0] == "Defensive" and th._count_regime(mk(4, 2, 0, hidden=2))[0] == "Offensive" and th._count_regime(mk(8, 0, 0))[0] == "Offensive"
r = f["rule_text"]
assert "поне 4 зелени, 0 червени и поне 6 видими" in r and "2 червени → Defensive" in r and "3 или повече червени → Cash" in r and "VIX, MOVE, IEI/HYG" in r
assert config.THERMOMETER_MIN_VISIBLE_FOR_OFFENSIVE == 6
print("  ✓ Offensive = 4+ зелени, 0 червени, ≥ 6 видими; 2 червени → Defensive; 3+ → Cash — същото казва rule_text (прагът 6 идва от config)")

print()
print("── 3. РЕАЛНИЯТ текст от 08.10: двата дефекта се хващат ──")
prob = rc.check(B["regime_comment"], f)
assert [p["code"] for p in prob] == ["member", "solo"], prob
assert "Fed Net Liquidity е посочен сред жълти" in prob[0]["why"] and "информативен" in prob[0]["why"]
assert "Market Breadth" in prob[1]["why"] and "сам по себе си" in prob[1]["why"]
assert rc.check(B["macro_brief"], f) == []
print("  ✓ regime_comment: 'member' (Fed Net Liquidity сред жълтите) и 'solo' (breadth 'само по себе си дава Defensive'); macro_brief — чист")
new, problems = rc.clean(B["regime_comment"], f)
assert "По броенето: " + f["counts_text"] + "." in new and "Fed Net Liquidity — последният" not in new and "само по себе си дава Defensive" not in new
assert "Defensive режимът е оправдан" in new and "Условието за отпадане на override" in new                 # останалите изречения са недокоснати
assert len(rc._sentences(new)) == len(rc._sentences(B["regime_comment"])) - 1                                    # едно изречение заменено с броенето от кода, едно махнато
assert rc.check(new, f) == []
print("  ✓ clean: изречението с грешното броене е заменено с 'По броенето: <от кода>', изречението със 'сам по себе си' е махнато; останалото е недокоснато; повторна проверка — чисто")

print()
print("── 4. фалшиви положителни: всичките 163 РЕАЛНИ текста ──")
hits, n = [], 0
for day, b in FX.items():
    fb = rc.facts({"indicators": b["indicators"]})
    for field in ("macro_brief", "regime_comment"):
        if b.get(field):
            n += 1
            hits += [(day, field, p["code"]) for p in rc.check(b[field], fb)]
assert n == 163 and hits == [("2026-10-08", "regime_comment", "member"), ("2026-10-08", "regime_comment", "solo")], (n, hits)
print(f"  ✓ {n} реални текста от 82 брифа: точно 2 флага — двата реални дефекта от 08.10; 0 фалшиви положителни (дроби '7/8 зелени', отрицания 'не … сам по себе си', правила 'Offensive изисква 4 зелени' не се вземат за твърдения)")

print()
print("── 5. граници (СИНТЕТИЧНИ изречения) ──")
ok = lambda s: rc.check_sentence(s, f) == []
f7 = rc.facts({"indicators": mk(7, 1, 0)})
assert rc.check_sentence("Остават 7/8 зелени при нормален VIX.", f7) == [] and rc.check_sentence("Остават 6/8 зелени при нормален VIX.", f7)[0]["code"] == "count"   # дроб: 7 от 8 (СИНТЕТИЧНО: 7 зелени, 1 жълт)
assert not ok("Кодът брои 5 зелени и 2 жълти.") and rc.check_sentence("Кодът брои 5 зелени и 2 жълти.", f)[0]["code"] == "count"
assert ok("Offensive изисква 4 зелени и 0 червени, затова режимът остава Defensive.")                             # правило, не днешно броене
assert ok("Днес 4 зелени (SPY тренд, VIX, 2s10s, VIX term structure) срещу 3 жълти (Put/Call, MOVE, Market Breadth) и 1 червен.")   # верни групи със свободно именуване
assert ok("IEI/HYG сам по себе си е достатъчен за Defensive чрез override.")                                         # форсиращ индикатор
assert ok("Breadth сам по себе си не е достатъчен за Defensive.") and ok("Не е тревога сама по себе си: breadth остава за наблюдение, режимът е Defensive.")   # отрицание
assert not ok("Market Breadth сам определя режима Defensive.")
assert not ok("Put/Call сам по себе си дава Offensive.")
assert not ok("Днес 3 червени (IEI/HYG, MOVE, VIX) определят Cash.")                                               # брой
assert not ok("Днес 1 червен (Market Breadth) определя режима.")                                                 # броят е верен, но Market Breadth е жълт
r1 = rc.check_sentence("Днес 4 зелени (SPY тренд, VIX, IEI/HYG, VIX term structure).", f)                       # IEI/HYG е червен, не зелен
assert r1 and r1[0]["code"] == "member" and "IEI/HYG" in r1[0]["why"]
print("  ✓ дроби, правила, отрицания, форсиращи индикатори и свободно именуване на верни групи — не се флагват; грешен брой, индикатор в грешна група и 'сам определя' — да")
empty = rc.facts({"indicators": []})
assert empty["groups"]["green"] == [] and "не е налично" in empty["counts_text"] and rc.check("Днес 4 зелени.", empty) == [] and rc.clean(None, f)[0] == ""
hid = rc.facts({"indicators": [{"name": "A", "status": "green"}, {"name": "B", "status": "red", "hide": True}, {"name": "Fed Net Liquidity", "status": "yellow", "informational": True}]})
assert "скрити (невалидни/застояли данни): B" in hid["counts_text"] and "от 1 видими" in hid["counts_text"]
assert rc.facts(None)["groups"]["green"] == []
print("  ✓ празен/липсващ термометър, скрити индикатори, None текст — без изключение; скритите са назовани")

print()
print("── 6. през macro_and_sector_brief: подменен модел връща РЕАЛНИТЕ текстове от 08.10 ──")
prompts, answers = [], {}
def fake_claude(system, user, **k):
    prompts.append(user)
    return json.dumps({"macro_brief": B["macro_brief"], "sector_logic": [], "regime_comment": B["regime_comment"]}, ensure_ascii=False)
ai_brief._call_claude = fake_claude
with contextlib.redirect_stdout(io.StringIO()) as out:
    res = ai_brief.macro_and_sector_brief({}, [], THERMO)
assert f["counts_text"] in prompts[0] and "НЕ преброявай" in prompts[0] and f["rule_text"] in prompts[0]
assert res["macro_brief"] == B["macro_brief"] and res["regime_comment"] == new
assert [(x["field"], x["code"]) for x in res["regime_claims_fixed"]] == [("regime_comment", "member"), ("regime_comment", "solo")]
assert "режим: regime_comment" in out.getvalue()
print("  ✓ промптът носи броенето и правилото от кода; отговорът на модела е поправен (regime_comment), с протокол в regime_claims_fixed и ред в лога")
clean_answer = {"macro_brief": "Кратък текст.", "sector_logic": [], "regime_comment": "Defensive е оправдан от override-а."}
ai_brief._call_claude = lambda *a, **k: json.dumps(clean_answer, ensure_ascii=False)
with contextlib.redirect_stdout(io.StringIO()):
    res2 = ai_brief.macro_and_sector_brief({}, [], THERMO)
assert res2 == clean_answer and "regime_claims_fixed" not in res2
print("  ✓ чист отговор — непроменен, без ключ regime_claims_fixed")
orig_clean = rc.clean
rc.clean = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("СИНТЕТИЧНА повреда"))
ai_brief._call_claude = fake_claude
with contextlib.redirect_stdout(io.StringIO()) as out:
    res3 = ai_brief.macro_and_sector_brief({}, [], THERMO)
rc.clean = orig_clean
assert res3["regime_comment"] == B["regime_comment"] and "проверка на твърденията за режима пропусната" in out.getvalue()
print("  ✓ СИНТЕТИЧНО: повреда в проверката → отговорът на модела се връща непроменен (graceful), редът в лога го казва")
ai_brief._call_claude = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("СИНТЕТИЧНО: API недостъпен"))
with contextlib.redirect_stdout(io.StringIO()):
    res4 = ai_brief.macro_and_sector_brief({}, [], THERMO)
assert res4.get("ai_synthesis_failed") and "regime_claims_fixed" not in res4
print("  ✓ СИНТЕТИЧНО: недостъпен модел → старият fallback (ai_synthesis_failed), без проверка")
assert ai_brief._SECTION_LABELS["_macro_and_sector_brief_ai"] == ai_brief._SECTION_LABELS["macro_and_sector_brief"]
print("  ✓ етикетът на секцията в AI_USAGE е същият за новото име на функцията")
print("\n✅ test_regime_claims: всичко мина")
