"""
15.10.2026 · езиковият филтър: латинско "se" между две кирилски думи → "се" (ai_brief._fix_latin_words, вика се от _fix_translit — всички AI отговори).

Реален дефект (regime_comment на 14.10): "Ако breadth продължи да se влошава, докато SPY удържа…". Измерено върху всички низове на 87 брифа (13.06–15.10, 156 305 низа): поправката
сменя точно 3 — 25.06 ("да se прехвърли"), 24.08 ("ще se върнат") и 14.10; самотното латинско "e" вече се поправяше от _fix_homoglyphs.
РЕАЛНО: tests/fixtures/ai_macro_texts_2026-06-13_10-15.json (regime_comment от 14.10 и 25.06); изречението от 24.08 е дословен цитат от data/2026-08-24.json (news[].why).
СИНТЕТИЧНО (маркирано): граничните низове (тикър SE, пунктуация, английски контекст).
Пускане: python test_latin_se.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import ai_brief as ab

FX = json.loads((ROOT / "tests" / "fixtures" / "ai_macro_texts_2026-06-13_10-15.json").read_text(encoding="utf-8"))["briefs"]
REAL = [FX["2026-10-14"]["regime_comment"], FX["2026-06-25"]["regime_comment"],
        "Пазарите на петрол са в режим на изчакване — детайлите на санкциите ще определят дали цените ще se върнат нагоре или ще продължат да падат."]   # РЕАЛНО: 24.08 news.why

print("── 1. РЕАЛНИТЕ три случая ──")
for s, want in zip(REAL, ("да се влошава", "да се прехвърли", "ще се върнат")):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        r = ab._fix_translit(s)
    assert want in r and " se " not in r and r.replace(want, "") == s.replace(want.replace("се", "se"), ""), (want, r)
    assert "латинска дума заменена: 'se' → 'се'" in out.getvalue()
print("  ✓ 14.10 'да se влошава', 25.06 'да se прехвърли', 24.08 'ще se върнат' → 'се'; останалият текст — непроменен; ред в лога")

print()
print("── 2. граници (СИНТЕТИЧНИ низове) ──")
same = lambda s: ab._fix_latin_words(s) == s
with contextlib.redirect_stdout(io.StringIO()):
    assert same("SE се търгува над pivot.") and same("Sea Ltd (SE) пада.") and same("la se de") and same("да se, влошава") and same("breadth se влошава")
    assert ab._fix_latin_words("ще se върнат") == "ще се върнат"
print("  ✓ тикърът SE (главни), английски/латински контекст, пунктуация до думата, латинска дума отляво — не се пипат")
print("\n✅ test_latin_se: всичко мина")
