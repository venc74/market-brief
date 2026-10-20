"""
20.10.2026 · етап 3, част А, т. 4: макро текстът — "(новина 1)" и повторено "По броенето: …".

Измерено върху всичките 90 брифа (всички AI текстове: макро, коментар за режима, вериги на секторите, наративи на картите):
  • "(новина N)": 1 случай — веригата на XLE на 20.10 ("… към Америките (новина 1) → …"). Новините влизат в промпта като JSON без номера; моделът ги е броил сам.
    → скобата се маха в общия езиков филтър (_fix_translit → _strip_prompt_refs), с ред в лога.
  • "По броенето:" два пъти: 1 случай — коментарът за режима на 20.10. Моделът написа "До Offensive по броенето: 0 червени (сега 2) и още 1 зелен" — ЦЕЛ плюс текущото
    състояние, преписано от реда "Запас до смяна на режима" на кода; regime_claims го взе за твърдение "0 червени" при 2 и го замени с броенето, което моделът вече беше
    написал изречение по-рано. От 2-те замени "count" в историята това е единствената фалшива (16.10 е хипотетичен брой — поправено в етап 1).
    → брой, последван от "(сега N", не се сверява (regime_claims._TARGET_AFTER).

РЕАЛНО: tests/fixtures/macro_texts_2026-10-20.json (термометърът, коментарът за режима, заменената фраза и веригата на XLE от брифа на 20.10).
СИНТЕТИЧНО (означено): грешното твърдение за брой в раздел 2.
Пускане: python test_macro_text_leaks.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import regime_claims as rc, ai_brief

FX = json.loads((ROOT / "tests/fixtures/macro_texts_2026-10-20.json").read_text(encoding="utf-8"))
f = rc.facts(FX["thermometer"])
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. РЕАЛНАТА фраза от 20.10 — цел и текущо състояние, не твърдение ──")
real = FX["regime_claims_fixed"][0]["sentence"]
assert real.startswith("До Offensive по броенето: 0 червени (сега 2)") and FX["regime_claims_fixed"][0]["code"] == "count"
assert rc.check_sentence(real, f) == []
assert FX["regime_comment"].count("По броенето:") == 2                                                          # така излезе на 20.10
print(f"  ✓ «{real}» — без проблем (до 20.10: 'твърди 0 червени, а кодът брои 2' → второ 'По броенето:')")

print()
print("── 2. грешно твърдение за днешния брой пак се хваща (СИНТЕТИЧНО) ──")
bad = "По броенето има само 1 червен индикатор, така че Defensive е на ръба."
assert [p["code"] for p in rc.check_sentence(bad, f)] == ["count"]
assert [p["code"] for p in rc.check_sentence("Само 1 червен индикатор е достатъчен за преход към Defensive (сега 2 червени).", f)] == []   # хипотетичен — етап 1
print("  ✓ '1 червен' при 2 по кода → count; хипотетичният брой — без проблем")

print()
print("── 3. '(новина 1)' — РЕАЛНАТА верига на XLE от 20.10 ──")
chain = FX["xle_chain"]
assert "(новина 1)" in chain
with q() as out:
    fixed = ai_brief._fix_translit({"chain": chain})["chain"]
assert "(новина 1)" not in fixed and fixed == chain.replace(" (новина 1)", "") and "махнато позоваване на промпта" in out.getvalue()
assert ai_brief._strip_prompt_refs("Петролът поскъпва (новини 2 и 3) → енергетика") == "Петролът поскъпва → енергетика"
assert ai_brief._strip_prompt_refs("Ръст (+4.97%) за седмица") == "Ръст (+4.97%) за седмица"                       # други скоби — непокътнати
print("  ✓", fixed[:110] + "…")
print("\n✅ test_macro_text_leaks: всичко мина")
