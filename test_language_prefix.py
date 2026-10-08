"""
Език · латинска приставка пред кирилска дума (08.10.2026, "Verижната" от брифа на 08.10). Моделът понякога започва българска дума с 1–3 латински букви и продължава с кирилица — "Verижната" (= "Верижната"),
"natиск", "rotацията", "katализатор", "sedмичен". Филтърът само ги логваше ("смесена дума … не е безопасен, не се пипа"). Сега ai_brief._fix_latin_prefix ги поправя, САМО ако транслитерираната приставка + кирилската част
дава цяла дума, която е в речника на историята поне 3 пъти (като _fix_glued). Думи с английска основа ("benefitват"), с кирилица отпред ("момentum") и с повече от 3 латински букви не отговарят на шаблона и остават в лога.

РЕАЛНО: tests/fixtures/mixed_script_words_2026-10-08.json — всичките 107 различни думи със смесено писмо в публикуваните брифове (docs/data, юни–октомври 2026; 322 появи) с реалния контекст и реалния брой на
транслитерираната дума в речника. Тестът подменя _bg_vocab с тези реални броячи (иначе резултатът зависи от растящата история).
СИНТЕТИЧНО (маркирано): граничните случаи (главна буква, 4-буквена приставка, празен речник, цифри/тирета).
Пускане: python test_language_prefix.py
"""
import sys, json, pathlib, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src import ai_brief as ab

W = json.loads((ROOT / "tests" / "fixtures" / "mixed_script_words_2026-10-08.json").read_text(encoding="utf-8"))["words"]
assert len(W) == 107 and sum(r["count"] for r in W) == 322
ab._bg_vocab = lambda: ({r["candidate"]: r["candidate_vocab_count"] for r in W if r["candidate"] and r["candidate_vocab_count"]}, {})
quiet = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. всичките 107 РЕАЛНИ хибридни думи от историята ──")
fixed, untouched = {}, []
for r in W:
    with quiet():
        out = ab._fix_latin_prefix(r["context"])
    if r["word"] not in out:                                                  # самата дума е заменена (в контекста може да има и друга хибридна дума — гледа се само целевата)
        fixed[r["word"]] = out
    else:
        untouched.append(r["word"])
EXPECT = {"Oперира": "Оперира", "Pesото": "Песото", "Verижната": "Верижната", "bенефициент": "бенефициент", "canадски": "канадски", "demографски": "демографски", "ekстремен": "екстремен", "expозиция": "експозиция",
          "katализатор": "катализатор", "natиск": "натиск", "pesото": "песото", "preработватели": "преработватели", "rotация": "ротация", "rotацията": "ротацията", "rентабилност": "рентабилност",
          "sedмичен": "седмичен", "umерено": "умерено", "verига": "верига"}
assert set(fixed) == set(EXPECT), sorted(set(fixed) ^ set(EXPECT))
for w, good in EXPECT.items():
    ctx = next(r["context"] for r in W if r["word"] == w)
    assert good in fixed[w] and w not in fixed[w], (w, fixed[w])
assert len(fixed) == 18 and len(untouched) == 89
print(f"  ✓ поправени 18 от 107 думи (всички правилни: Verижната → Верижната, natиск → натиск, expозиция → експозиция ×19 появи, canадски → канадски, …); 89 остават непипнати — английски основи (benefitват, "
      f"AIбум), кирилица отпред (момentum), приставка над 3 букви, дума с брояч под 3 (banково, expозиции)")
rest = {r["word"] for r in W if r["word"] not in EXPECT}
assert {"benefitват", "банково", "banково"} & rest
print("    0 фалшиви поправки; поправките покриват 18 различни думи / 39 от 322 появи в историята")
covered = sum(r["count"] for r in W if r["word"] in EXPECT)
assert covered == 39, covered

print()
print("── 2. граници (СИНТЕТИЧНИ) ──")
with quiet():
    assert ab._fix_latin_prefix("Verижната логика") == "Верижната логика" and ab._fix_latin_prefix("verига на стойността") == "верига на стойността"
    assert ab._fix_latin_prefix("Natиск и natиск") == "Натиск и натиск"                                              # главна буква се запазва
    assert ab._fix_latin_prefix("benefitват, момentum, AIбум, ETF-ите, AI-то, 5G-то, USDхор") == "benefitват, момentum, AIбум, ETF-ите, AI-то, 5G-то, USDхор"     # >3 букви / кирилица отпред / няма съвпадение с речника
    assert ab._fix_latin_prefix("чист български текст и pure English text") == "чист български текст и pure English text"
    assert ab._fix_latin_prefix("expозиция") == "експозиция"                                                          # x → «кс»
    assert ab._fix_latin_prefix("zzzдума") == "zzzдума" and ab._fix_latin_prefix("qwяблъко") == "qwяблъко"          # буква без съответствие / няма дума в речника
ab._bg_vocab = lambda: ({}, {})
with quiet():
    assert ab._fix_latin_prefix("Verижната логика") == "Verижната логика"                                              # без речник — не се пипа нищо
print("  ✓ главна буква се запазва; приставка над 3 букви, кирилица отпред, дефисни форми (AI-то, ETF-ите), тикъри и чисти низове не се пипат; x → «кс»; без речник — нищо не се променя")

print()
print("── 3. през _parse_json (РЕАЛНОТО изречение от 08.10) ──")
ab._bg_vocab = lambda: ({r["candidate"]: r["candidate_vocab_count"] for r in W if r["candidate"] and r["candidate_vocab_count"]}, {})
real = next(r for r in W if r["word"] == "Verижната")["context"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out = ab._parse_json(json.dumps({"t": real}, ensure_ascii=False))
assert "Верижната логика" in out["t"] and "Verижната" not in out["t"]
assert "латинска приставка пред кирилица заменена: 'Verижната' → 'Верижната'" in buf.getvalue() and "смесена дума" not in buf.getvalue()
expo = next(r for r in W if r["word"] == "expозиция")["context"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out = ab._parse_json(json.dumps({"t": expo}, ensure_ascii=False))
assert "експозиция" in out["t"] and "известен езиков дефект" not in buf.getvalue() and "смесена дума" not in buf.getvalue()
print("  ✓ «Verижната логика е условна…» → «Верижната логика…» (един ред в лога, без «смесена дума»); «expозиция» също се поправя и не остава в лога като неподправен известен дефект")

print()
print("── 4. първоизточникът в кода: glb_screener.py ──")
g = (ROOT / "src" / "glb_screener.py").read_text(encoding="utf-8")
assert "момentum" not in g and "orязана" not in g and '"momentum":' in g and "месечно орязана Close" in g                  # 09.10: бележките са пренаписани (без «momentum move»); смесени думи пак няма
print("  ✓ «момentum» → «momentum» и «orязана» → «орязана» в самия текст на картите (src/glb_screener.py)")
print("\n✅ test_language_prefix: всичко мина")
