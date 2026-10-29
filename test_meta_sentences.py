"""
28.10.2026 · макро текстът: изтекла проверка от промпта — „Никоя от наличните стойности не е null/nan.“ (коментарът за режима на 28.10). Промптът казва: ако индикатори липсват, са скрити
или съдържат null/nan — кажи го; когато няма такива, моделът пише, че няма. regime_claims.strip_meta маха клаузата-проверка (разделители „ — “, „; “, „, но “); изречение само от такива
клаузи пада цяло; клауза за СКРИТ / ЛИПСВАЩ индикатор или невалидни данни е информация и остава.

Измерено върху всичките 191 макро текста (macro_brief + regime_comment, 13.06–28.10): 16 изречения с клауза-проверка — всичките в regime_comment от 21.08 насам, 0 фалшиви
(46-те изречения за скрити индикатори с „null“ — непокътнати; наративите на картите не се пипат).

РЕАЛНО: tests/fixtures/meta_sentences_2026-10-28.json — коментарите за режима и макро текстовете от 03.08, 24.08, 04.09, 30.09, 08.10 и 28.10.
СИНТЕТИЧНО (означено): изреченията в т. 3.
Пускане: python test_meta_sentences.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import regime_claims as rc, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "meta_sentences_2026-10-28.json").read_text(encoding="utf-8"))["briefs"]

print("── 1. РЕАЛНИТЕ коментари ──")
c28 = FX["2026-10-28"]["regime_comment"]
assert "Никоя от наличните стойности не е null/nan." in c28
new28, p28 = rc.strip_meta(c28)
assert "null" not in new28 and len(p28) == 1 and p28[0]["kept"] is None and new28.count(".") == c28.count(".") - 1
_, p08 = rc.strip_meta(FX["2026-10-08"]["regime_comment"])
assert [x["kept"] for x in p08] == ["Увереността в режима е висока — два независими механизма (override + брой) сочат едно и също."]
_, p30 = rc.strip_meta(FX["2026-09-30"]["regime_comment"])
assert [x["kept"] for x in p30] == ["Увереността в режима е висока."] and len(p30[0]["removed"]) == 2
_, p24 = rc.strip_meta(FX["2026-08-24"]["regime_comment"])
assert [x["kept"] for x in p24] == ["Увереност в текущия режим: умерена, но балансът е 7:1 в полза на risk-on сигнали; режимът виси на един индикатор."]
print("  ✓ 28.10 — изречението пада; 08.10, 30.09, 24.08 — маха се само клаузата, останалото остава")
for d in ("2026-08-03", "2026-09-04"):                                                          # информация за скрит индикатор / невалидни данни — остава
    t = FX[d]["regime_comment"]
    assert rc.strip_meta(t) == (t, [])
assert "те са null защото данните са невалидни или застояли" in FX["2026-08-03"]["regime_comment"] and "IEI/HYG данните са невалидни (NaN за level)" in FX["2026-09-04"]["regime_comment"]
for d, b in FX.items():
    assert rc.strip_meta(b["macro_brief"]) == (b["macro_brief"], [])                            # в макро текста — нито едно
print("  ✓ 03.08 („те са null защото данните са невалидни“) и 04.09 („IEI/HYG данните са невалидни (NaN за level)“) — непокътнати; macro_brief — непокътнат")

print()
print("── 2. ai_brief: поправката в _apply_meta_check (протокол в regime_claims_fixed, код meta) — 29.10.2026: върху разказа (macro_brief), по абзаци ──")
res = ai_brief._apply_meta_check({"macro_brief": "Първи абзац без проверки.\n\n" + c28, "sector_logic": []})                  # РЕАЛНИЯТ текст от 28.10 като втори абзац
assert "Никоя от наличните стойности" not in res["macro_brief"] and any(x["code"] == "meta" and x["kept"] is None for x in res["regime_claims_fixed"])
assert res["macro_brief"].startswith("Първи абзац без проверки.\n\n")                                          # абзаците остават разделени
print("  ✓ macro_brief без изречението, абзаците — разделени; regime_claims_fixed: meta")

print()
print("── 3. гранични (СИНТЕТИЧНИ) ──")
assert rc.strip_meta("MOVE е скрит поради null стойности — липсата му е blind spot.")[1] == []
assert rc.strip_meta("Няма скрити null/nan стойности — увереността е висока.")[0] == "Увереността е висока."
assert rc.strip_meta("Всички индикатори са зелени.")[1] == []
print("  ✓ „скрит поради null“ остава; „Няма скрити null/nan“ се маха; „всички индикатори са зелени“ не е проверка")
print("\n✅ test_meta_sentences: всичко мина")
