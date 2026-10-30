"""
30.10.2026 · поправки от брифа, т. 6: нов информативен уред — базов PCE (PCE без храни и енергия, FRED PCEPILFE): годишно изменение, за кой месец, ускорява / забавя спрямо
предишния месец; в блока „Информативни — не влизат в режима“, до основната инфлация (Dallas Fed); подава се и на разказа (в macro["pce_core"]).

РЕАЛНО: tests/fixtures/pce_core_pcepilfe_2026-10-30.json — индексът PCEPILFE (BEA NIPA Table 2.8.4, ред 25) 1959-01 → 2026-09, свален на 30.10.2026 от DBnomics
(fred.stlouisfed.org не отговаряше оттук); tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): датата „днес“ за застоялия случай, кратката редица в т. 3.
Пускане: python test_pce_core.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_pce_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import macro_layer as ml, render, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "pce_core_pcepilfe_2026-10-30.json").read_text(encoding="utf-8"))
OBS = [tuple(o) for o in FX["observations"]]
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))

print("── 1. РЕАЛНАТА серия: септември 2026 ──")
pc = ml.pce_core_signal(OBS, dt.date(2026, 10, 30))
assert pc == {"value": 3.12, "date": "2026-09-01", "month": "септември", "year": 2026, "age_days": 30, "prev_value": 3.03, "prev_month": "август", "direction": "up",
              "series": "PCEPILFE"}, pc
aug = ml.pce_core_signal([o for o in OBS if o[0] <= "2026-08-01"], dt.date(2026, 10, 1))
assert (aug["month"], aug["value"], aug["prev_value"], aug["direction"]) == ("август", 3.03, 3.0, "flat")                      # 3.0 → 3.0 при 0.1 точност — без промяна
print("  ✓ септември 2026: 3.12% г/г, август 3.03% → ↑ ускорява; август спрямо юли (3.0 / 3.0) → без промяна")

print()
print("── 2. картата в „Информативни“ — до основната инфлация ──")
b = copy.deepcopy(B19); b["macro"]["pce_core"] = pc
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
info = page[page.index('<div class="thermo-info">'):]; info = info[:info.index("Скрити днес") if "Скрити днес" in info else len(info)]
t = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", info)))
assert "Базов PCE 3.1% данни за септември 2026 · г/г · ↑ ускорява спрямо август (3.0%) · излизат с ~6 седмици закъснение (в края на следващия месец) · информативно, не влиза в режима" in t, t[-500:]
assert t.index("Основна инфлация") < t.index("Базов PCE")
print("  ✓ „Базов PCE 3.1% · данни за септември 2026 · г/г · ↑ ускорява спрямо август (3.0%)“ — след основната инфлация")

print()
print("── 3. застояла, къса серия; разказът го вижда (СИНТЕТИЧНО) ──")
assert ml.pce_core_signal(OBS, dt.date(2027, 3, 1))["stale"] and ml.pce_core_signal(OBS[-5:], dt.date(2026, 10, 30)) == {"value": None}
prompt = ai_brief.macro_user_prompt({"pce_core": pc}, [], {"indicators": []}, [], {})
assert '"pce_core": {"value": 3.12' in prompt
print("  ✓ застояла → stale; под 14 месеца → без стойност; macro_user_prompt носи pce_core")
print("\n✅ test_pce_core: всичко мина")
