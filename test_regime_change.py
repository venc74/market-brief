"""
04.11.2026 · прегледът, т. 3: термометърът — ред „какво промени режима“ спрямо предишния бриф, от кода, само при смяна. На 04.11: Defensive → Offensive: „MOVE жълто → зелено (100) — 4 зелени = минимумът за Offensive“.

РЕАЛНО: tests/fixtures/regime_change_2026-11-04.json (термометрите на дните със смяна, бележката — вътре); tests/fixtures/brief_2026-10-19.json — рамката. СИНТЕТИЧНО (означено): Cash, видими под минимума, липсващ предишен бриф.
Пускане: python test_regime_change.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_regchange_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import regime_claims as rc, render

D = json.loads((ROOT / "tests" / "fixtures" / "regime_change_2026-11-04.json").read_text(encoding="utf-8"))["days"]
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
ch = lambda a, b: rc.regime_change(D[a], D[b], a)

print("── 1. РЕАЛНИТЕ смени ──")
x = ch("2026-11-03", "2026-11-04")
assert x["text"] == "Defensive → Offensive: MOVE жълто → зелено (100) — 4 зелени = минимумът за Offensive" and x["prev_date"] == "2026-11-03", x
y = ch("2026-10-30", "2026-11-02")
assert y["text"].startswith("Offensive → Defensive: SPY тренд зелено → жълто (755.72), MOVE зелено → жълто (100.2) — distribution days червени") and "Offensive блокиран" in y["why"], y
z = ch("2026-10-28", "2026-10-29")
assert z["changes"] == [] and z["text"] == "Defensive → Offensive: 7 зелени при минимум 4 за Offensive · override-ът отпадна", z
w = ch("2026-10-16", "2026-10-19")
assert "IEI/HYG зелено → червено (1.4863)" in w["text"] and "IEI/HYG credit spread spike" in w["why"]
assert ch("2026-11-02", "2026-11-03") is None                                                         # без смяна — без ред
print(f"  ✓ 04.11: „{x['text']}“; 02.11 — блокът от distribution days; 29.10 — само падналият override; без смяна — без ред")

print()
print("── 2. правилото в причината (СИНТЕТИЧНО: Cash, видими под минимума) ──")
ind = lambda n, s, v=1.0, **k: {"name": n, "status": s, "value": v, **k}
base = [ind(f"I{k}", "yellow") for k in range(5)]
cash = {"regime": "Cash", "indicators": [ind("I0", "red"), ind("I1", "red"), ind("I2", "red"), ind("I3", "yellow"), ind("I4", "yellow")]}
assert rc.regime_change({"regime": "Defensive", "indicators": base}, cash)["why"] == "3 червени — Cash е при поне 3"
assert rc.regime_change(cash, {"regime": "Defensive", "indicators": base})["why"] == "0 червени — под 3 за Cash"
hid = {"regime": "Defensive", "indicators": [ind(f"I{k}", "green") for k in range(5)]}
assert rc.regime_change({"regime": "Offensive", "indicators": [ind(f"I{k}", "green") for k in range(8)]}, hid)["why"] == f"видими 5 — Offensive иска поне {config.THERMOMETER_MIN_VISIBLE_FOR_OFFENSIVE}"
capd = {"regime": "Defensive", "distribution_cap": {"text": "x"}, "indicators": [ind(f"I{k}", "green") for k in range(8)]}
assert rc.regime_change(capd, {"regime": "Offensive", "indicators": [ind(f"I{k}", "green") for k in range(8)]})["why"].endswith("· блокът от distribution days падна")
info = {"regime": "Offensive", "indicators": [ind("I0", "green"), ind("Инф", "red", informational=True)]}
assert rc.regime_change({"regime": "Defensive", "indicators": [ind("I0", "green"), ind("Инф", "green", informational=True)]}, info)["changes"] == []     # информативният не решава
assert rc.regime_change(None, D["2026-11-04"]) is None and rc.regime_change({}, {}) is None and rc.regime_change({"regime": "Cash"}, {"regime": "Cash"}) is None
print("  ✓ Cash, изход от Cash, видими под минимума, падналият блок; информативният не се брои; без предишен бриф — без ред")

print()
print("── 3. страницата и имейлът ──")
b = copy.deepcopy(B19); b["thermometer"]["regime_change"] = x
with contextlib.redirect_stdout(io.StringIO()):
    page = flat(render.render_dashboard(b, publish=False)); mail = flat(render.render_email(b))
s = page[page.index("Пазарен термометър"):]
assert "Какво промени режима от предишния бриф (03.11): Defensive → Offensive: MOVE жълто → зелено (100) — 4 зелени = минимумът за Offensive" in s
assert s.index("Какво промени режима") < s.index("Запас до смяна на режима")
assert "Какво промени режима: Defensive → Offensive: MOVE жълто → зелено (100)" in mail
with contextlib.redirect_stdout(io.StringIO()):
    assert "Какво промени режима" not in flat(render.render_dashboard(copy.deepcopy(B19), publish=False)) and "Какво промени режима" not in flat(render.render_email(copy.deepcopy(B19)))
main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert main.index('thermo["regime_margin"] = regime_claims.margin(') < main.index('thermo["regime_change"] = regime_claims.regime_change(') < main.index('print("[3/7] Слой 2')
print("  ✓ ред над „Запас до смяна на режима“ и в имейла; стар бриф и ден без смяна — без него; смята се след distribution days")
print("\n✅ test_regime_change: всичко мина")
