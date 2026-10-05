"""
Пакет 2 (2026-10-05) · GLB: празна група (Momentum или Classic) има ред "няма … кандидати днес", а не липсва.

РЕАЛНО: брифът от 05.10.2026 — 5 GLB кандидата, всички classic (ADI, ETN, …), нито един momentum. СИНТЕТИЧНО: копия на реалния бриф само с momentum / без нито един кандидат.
Пускане: python test_glb_empty_group.py
"""
import sys, json, pathlib, tempfile, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import render

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
G = B05["glb_candidates"]
assert len(G) == 5 and {g["glb_type"] for g in G} == {"classic"}


def text(brief):
    with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
        o1, o2 = config.DOCS_DIR, config.DATA_DIR
        config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
        try:
            return " ".join(re.sub(r"<[^>]+>", "", htmllib.unescape(render.render_dashboard(brief))).split())
        finally:
            config.DOCS_DIR, config.DATA_DIR = o1, o2


print("── РЕАЛНО 05.10: 5 classic, 0 momentum ──")
t = text(B05)
assert "Classic GLB (5)" in t and "Momentum GLB (0) няма Momentum кандидати днес" in t and "Classic кандидати днес" not in t
print("  ✓ 'Momentum GLB (0) — няма Momentum кандидати днес' вместо липсваща група; Classic GLB (5) както преди")

print()
print("── СИНТЕТИЧНО ──")
b = json.loads(json.dumps(B05)); b["glb_candidates"] = [dict(g, glb_type="momentum") for g in G[:2]]
t = text(b)
assert "Momentum GLB (2)" in t and "Classic GLB (0) няма Classic кандидати днес" in t and "няма Momentum кандидати днес" not in t
b["glb_candidates"] = []
t = text(b)
assert "GLB Watchlist" not in t and "кандидати днес" not in t                                        # без кандидати изобщо секцията е скрита, както досега
print("  ✓ само momentum → 'Classic GLB (0) — няма Classic кандидати днес'; без нито един GLB кандидат секцията остава скрита (непроменено)")
print()
print("Всички тестове минаха.")
