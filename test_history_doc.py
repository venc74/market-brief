"""
20.10.2026 · етап 3: CLAUDE.md → правила + docs/HISTORY.md. HISTORY.md е в docs/, а GitHub Pages сглобява docs/ с Jekyll — Liquid синтаксис в текста (двойни къдрави скоби или
къдрава скоба с процент, напр. цитиран Jinja код от шаблона) би спрял сборката и живата страница нямаше да се обнови. Тестът чете два статични документа от репото (не данни).

РЕАЛНО: CLAUDE.md и docs/HISTORY.md в работното дърво.
Пускане: python test_history_doc.py
"""
import re, pathlib
ROOT = pathlib.Path(__file__).parent
hist = (ROOT / "docs" / "HISTORY.md").read_text(encoding="utf-8")
claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

print("── 1. docs/HISTORY.md без Liquid синтаксис ──")
bad = [i for i, l in enumerate(hist.splitlines(), 1) if re.search(r"\{\{|\{%|%\}|\}\}", l)]
assert not bad, f"Liquid синтаксис на редове {bad} — Jekyll ще спре сборката на Pages"
print(f"  ✓ {len(hist.splitlines())} реда без двойни къдрави скоби и тагове")

print()
print("── 2. CLAUDE.md пази правилата и сочи историята ──")
assert "docs/HISTORY.md" in claude and "## Работни правила" in claude and "## Известни особености" not in claude
assert all(f"\n{n}. **" in claude or f"\n{n}. " in claude for n in range(1, 11))
assert "## Известни особености / история на решенията" in hist
print("  ✓ десетте правила са в CLAUDE.md; историята на решенията — в docs/HISTORY.md")
print("\n✅ test_history_doc: всичко мина")
