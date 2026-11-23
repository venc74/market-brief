"""
17.11.2026 (пакет 1, т. 2б — решение след стратегическия преглед): макро разказът остава на AI, но кратко — 3–4 изречения в един абзац, само върху подадените
числа и новини, със сегашните проверки (числа, думи, твърдения, имена на полета). Промптът казва 3–4 (config.MACRO_MIN_SENTENCES / MACRO_MAX_SENTENCES); над
4 кодът реже след проверките (ai_brief.cap_sentences) и пази изречението „За нас:“; махнатото — brief["ai_macro"]["sentences_capped"] и лог.

РЕАЛНО: tests/fixtures/macro_brief_2026-11-17.json — разказът от брифа на 17.11 (16 изречения в 4 абзаца). СИНТЕТИЧНО (означено): т. 2 — кратък текст и текст без „За нас:“.
Пускане: python test_macro_short.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import ai_brief

T = json.loads((ROOT / "tests" / "fixtures" / "macro_brief_2026-11-17.json").read_text(encoding="utf-8"))["macro_brief"]

print("── 1. РЕАЛНО: разказът от 17.11 — 16 изречения → 4, „За нас:“ остава ──")
new, cut = ai_brief.cap_sentences(T, config.MACRO_MAX_SENTENCES)
sents = ai_brief._SENT_SPLIT_RE.split(new)
assert config.MACRO_MAX_SENTENCES == 4 and len(sents) == 4 and len(cut) == 12 and "\n" not in new
assert sents[0].startswith("Понеделникът донесе рязко засилване на напрежението") and sents[-1].startswith("За нас: водещите ни сектори")
print(f"  ✓ 4 изречения, махнати 12; последното — «{sents[-1][:60]}…»")

print("── 2. СИНТЕТИЧНО: кратък текст — без промяна; без „За нас:“ — първите 4 ──")
assert ai_brief.cap_sentences("Едно. Две. Три.", 4) == ("Едно. Две. Три.", [])
assert ai_brief.cap_sentences("А. Б. В. Г. Д. Е.", 4) == ("А. Б. В. Г.", ["Д.", "Е."])
assert ai_brief.cap_sentences("А. Б. В. Г. Д. За нас: тук.", 4) == ("А. Б. В. За нас: тук.", ["Г.", "Д."])
print("  ✓ ≤ 4 — без промяна; над 4 — средните падат, „За нас:“ остава")

print("── 3. промптът и мястото на тавана ──")
assert "3–4 изречения в един абзац, САМО върху подадените числа и новини" in ai_brief.NARRATIVE_RULES and "2–3 абзаца" not in ai_brief.NARRATIVE_RULES
src = (ROOT / "src" / "ai_brief.py").read_text(encoding="utf-8")
body = src[src.index("def macro_and_sector_brief("):src.index("def narrative_text(")]
assert body.index("claim_check.check(") < body.index("cap_sentences(out[\"macro_brief\"]") and '"sentences_capped"' in body
print("  ✓ промптът — 3–4 изречения; таванът е след проверките (числа, думи, твърдения)")
print("\n✅ test_macro_short: всичко мина")
