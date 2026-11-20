"""
20.11.2026 (пакет 20.11, т. 2): „Нови днес“ във всеки скрийнър (src/novelty.py, render.novelty_ctx) — ново = първа поява ИЛИ промяна на статуса днес; еднаква плочка (тикър · име ·
скрийнър · ниво / аларма · стоп · цел · разстояние · „Защо е тук“ · отчет ⚠ · ниво); без нови — „Няма нови предложения днес — кешът също е позиция“; старите — сгънати
„Още валидни от предишни дни (N)“ (предложен ДД.ММ · валиден до · разстояние); пълните карти — сгънати отдолу; книгите — както досега. Стар бриф без brief["novelty"] — без промяна.

РЕАЛНО: tests/fixtures/novelty_2026-11-20.json — картите от брифа на 20.11 и статусите от брифовете 23.10–19.11. СИНТЕТИЧНО (означено): т. 3 — промяната на статуса.
Пускане: python test_novelty.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_nov_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import novelty as nv, render

FX = json.loads((ROOT / "tests" / "fixtures" / "novelty_2026-11-20.json").read_text(encoding="utf-8"))
C, H = FX["cards"], [tuple(x) for x in FX["history"]]

print("── 1. РЕАЛНО: 20.11 — кои са нови, кои стари, кои отпаднаха ──")
cards = copy.deepcopy(C)
res = nv.annotate(cards, "2026-11-20", H)
assert res["canslim"] == {"new": ["CROX"], "old": [], "dropped": ["CSX", "LLY"]}, res["canslim"]
assert res["qm"] == {"new": ["GKOS", "R"], "old": ["CSL", "DLTR", "IDXX"], "dropped": ["BAX", "J"]}, res["qm"]
assert res["glb_classic"]["new"] == [] and len(res["glb_classic"]["old"]) == 9 and res["glb_classic"]["dropped"] == ["GHC", "NDAQ"]
assert res["glb_momentum"] == {"new": [], "old": ["ALLE", "MAR"], "dropped": ["COST"]} and res["ep"] == {"new": [], "old": [], "dropped": []}
fs = {c["ticker"]: c["novelty"]["first_seen"] for c in cards["qm_breakout"] + cards["glb_candidates"]}
assert fs["IDXX"] == "2026-11-17" and fs["AFG"] == "2026-10-30" and fs["GKOS"] == "2026-11-20"
print("  ✓ CANSLIM: CROX нов; Kullamägi: GKOS, R нови, IDXX (от 17.11), DLTR, CSL — стари; GLB: 11 стари, отпаднали GHC, NDAQ, COST")

print("── 2. СИНТЕТИЧНО: промяна на статуса — „от ДД.ММ — днес близо до вход“ ──")
c2 = copy.deepcopy(C)
idxx = next(c for c in c2["qm_breakout"] if c["ticker"] == "IDXX")
idxx["pct_to_trigger"] = 1.2
r2 = nv.annotate(c2, "2026-11-20", H)
assert "IDXX" in r2["qm"]["new"] and idxx["novelty"]["changed"] and idxx["novelty"]["label"] == "от 17.11 — днес близо до вход"
print(f"  ✓ IDXX: «{idxx['novelty']['label']}»")

print("── 3. страницата ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B)
b.update(date="2026-11-20", action=cards["action"], watchlist=cards["watchlist"], qm_breakout=cards["qm_breakout"], glb_candidates=cards["glb_candidates"],
         qm_ep=cards["qm_ep"], novelty=res)
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
assert "Нови днес · CANSLIM · 1 CROX · Crocs" in txt and "ниво: CANSLIM" in txt and "аларма над $161.88 — вход само с обем" in txt
assert "Нови днес · Kullamägi · 2" in txt and "GKOS · Glaukos" in txt and "Цел частична на 4-ия ден, после SMA10 / SMA20" in txt
assert txt.count("Няма нови предложения днес — кешът също е позиция.") == 3                                   # GLB Classic, GLB Momentum, EP
assert "Още валидни от предишни дни (9)" in txt and "AFG · American Financial Group · предложен 30.10 · валиден до 27.11 · +3.0% над линията" in txt
assert "Още валидни от предишни дни (3)" in txt and re.search(r"DLTR · Dollar Tree · предложен 19\.11 · валиден до 20\.11 · \+[\d.]+% до нивото · ⚠ отчет на 24\.11 — вход след отчета", txt)
assert "Отпаднаха от вчера: GHC, NDAQ" in txt and "Пълните карти (" in txt and "Пълните таблици (11)" in txt
old = copy.deepcopy(B)
with contextlib.redirect_stdout(io.StringIO()):
    assert "Нови днес" not in render.render_dashboard(old, publish=False)
print("  ✓ плочките, „кешът също е позиция“, сгънатите стари редове и пълните карти; стар бриф — без промяна")
print("\n✅ test_novelty: всичко мина")
