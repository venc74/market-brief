"""
17.11.2026 (пакет 1, т. 7): езиковата защита пропусна смесена азбука в една дума — „Zад цифрите стоят две новини“ (латинско Z в кирилска дума, разказът от 17.11).
Сега: дума с латински и кирилски букви → латинските → кирилица буква по буква; позната дума от корпуса (_bg_vocab, ≥ 2) — поправка; иначе изречението пада
(brief["ai_mixed_drops"]). Без речник — само логът, както до 17.11. Измерено върху AI текстовете на брифовете 13.06–17.11: 92 смесени думи (67 различни).

РЕАЛНО: tests/fixtures/macro_brief_2026-11-17.json (разказът от 17.11 със „Zад“); „benefitва“ (13.06), „падa“ (26.08), „пolicymakers“ (02.10) — изречения от брифовете (цитирани).
СИНТЕТИЧНО (означено): т. 3 — без речник.
Пускане: python test_mixed_script.py
"""
import sys, json, io, contextlib, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import ai_brief as a

T = json.loads((ROOT / "tests" / "fixtures" / "macro_brief_2026-11-17.json").read_text(encoding="utf-8"))["macro_brief"]

def fix(s):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = a._fix_translit(s)
    return out, buf.getvalue()

print("── 1. РЕАЛНО: „Zад“ от 17.11 → „Зад“ ──")
out, log = fix(T)
assert "Zад" in T and "Zад" not in out and "Зад цифрите стоят две новини" in out and "'Zад' → 'Зад'" in log
print("  ✓ поправено, изречението остава")

print("── 2. РЕАЛНО: поправка или изречението пада ──")
a.MIXED_DROPS.clear()
o1, _ = fix("Паралелно: US10Y падa (реалните лихви намаляват) → opportunity.")                          # 26.08
o2, _ = fix("XLF + Offensive режим: Asset Management директно benefitва от rising equities. Второ изречение остава.")     # 13.06 (+ синтетично второ изречение)
o3, _ = fix("Fed пolicymakers се накланят срещу октомврийско повишение.")                                 # 02.10
assert o1.startswith("Паралелно: US10Y пада (") and o2 == "Второ изречение остава." and o3 == ""
assert [d["words"] for d in a.MIXED_DROPS] == [["benefitва"], ["пolicymakers"]]
print("  ✓ „падa“ → „пада“; „benefitва“, „пolicymakers“ — изречението пада (записано)")

print("── 3. СИНТЕТИЧНО: без речник — само логът ──")
orig = a._bg_vocab
a._bg_vocab = lambda: ({}, {})
try:
    assert fix("Zад цифрите.")[0] == "Zад цифрите."
finally:
    a._bg_vocab = orig
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert '"ai_mixed_drops": list(ai_brief.MIXED_DROPS)' in src and "ai_brief.MIXED_DROPS.clear()" in src
print("  ✓ без речник — непроменено; brief[\"ai_mixed_drops\"]")
print("\n✅ test_mixed_script: всичко мина")
