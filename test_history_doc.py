"""
20.10.2026 · етап 3: CLAUDE.md → правила + docs/HISTORY.md; етап 3б: docs/.nojekyll. GitHub Pages сглобяваше docs/ с Jekyll — Liquid синтаксис в HISTORY.md (двойни къдрави скоби
или къдрава скоба с процент, напр. цитиран Jinja код от шаблона) би спрял сборката и живата страница нямаше да се обнови. С docs/.nojekyll Pages сервира docs/ както е; страницата не
разчита на Jekyll (20.10: index.html, tax.html, архивът и data/*.json на живо бяха байт по байт същите като в репото, без front matter и без Liquid). Тестът чете статични документи от репото (не данни).

РЕАЛНО: CLAUDE.md, docs/HISTORY.md, docs/.nojekyll в работното дърво.
Пускане: python test_history_doc.py
"""
import re, pathlib
ROOT = pathlib.Path(__file__).parent
hist = (ROOT / "docs" / "HISTORY.md").read_text(encoding="utf-8")
claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

print("── 1. Pages без Jekyll ──")
assert (ROOT / "docs" / ".nojekyll").exists(), "docs/.nojekyll липсва — Pages ще сглоби docs/ с Jekyll"
for f in [ROOT / "docs" / "index.html", ROOT / "docs" / "tax.html"]:
    assert not f.read_text(encoding="utf-8").startswith("---"), f"{f.name}: front matter — Jekyll би го обработил"
print("  ✓ docs/.nojekyll е на място; index.html и tax.html са без front matter")

print()
print("── 2. docs/HISTORY.md без Liquid синтаксис (резерва, ако .nojekyll бъде махнат) ──")
bad = [i for i, l in enumerate(hist.splitlines(), 1) if re.search(r"\{\{|\{%|%\}|\}\}", l)]
assert not bad, f"Liquid синтаксис на редове {bad}"
print(f"  ✓ {len(hist.splitlines())} реда без двойни къдрави скоби и тагове")

print()
print("── 3. CLAUDE.md пази правилата и сочи историята ──")
assert "docs/HISTORY.md" in claude and "## Работни правила" in claude and "## Известни особености" not in claude
assert all(f"\n{n}. " in claude for n in range(1, 11))
assert "## Известни особености / история на решенията" in hist
print("  ✓ десетте правила са в CLAUDE.md; историята на решенията — в docs/HISTORY.md")
print("\n✅ test_history_doc: всичко мина")
