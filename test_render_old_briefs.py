"""
19.10.2026 · етап 2, т. 20: шаблонът не пада върху стари брифове. До 19.10 dashboard-ът падаше върху брифа от 12.10 (UndefinedError "'dict object' has no attribute
'return_pct'" — редът на живите записи в книгата qm_breakout; на 12.10 те още нямаха return_pct, полето дойде с формулата за R от същия ден). Измерено върху всичките 89 реални
брифа в data/ (dashboard + имейл): падаше само 12.10.

РЕАЛНО: всички tests/fixtures/brief_*.json (реални брифове от 29.06 до 19.10, сред тях brief_2026-10-12.json — копие на data/2026-10-12.json без промяна). Изходът е във временна
директория (config.DOCS_DIR / DATA_DIR), нищо в docs/ и data/.
Пускане: python test_render_old_briefs.py
"""
import sys, json, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import render

_tmp = tempfile.TemporaryDirectory(prefix="mb_old_")
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"
config.DATA_DIR.mkdir()

files = sorted((ROOT / "tests" / "fixtures").glob("brief_*.json"))
assert any(f.name == "brief_2026-10-12.json" for f in files) and len(files) >= 12
print(f"── dashboard + имейл върху {len(files)} РЕАЛНИ брифа ──")
for f in files:
    b = json.loads(f.read_text(encoding="utf-8"))
    day = dt.date.fromisoformat(f.stem.split("_")[1])
    with contextlib.redirect_stdout(io.StringIO()):
        html = render.render_dashboard(b, publish=False, as_of=day)
        mail = render.render_email(b)
    assert "</html>" in html and len(mail) > 1000, f.name
    print(f"  ✓ {f.stem[6:]}: {len(html) // 1024} KB страница, {len(mail) // 1024} KB имейл")

b12 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-12.json").read_text(encoding="utf-8"))
live = b12["backtest"]["qm_breakout"]["live"]
assert live and all("return_pct" not in p for p in live)                     # старият формат — точно случаят, който сваляше шаблона
print(f"  ✓ 12.10: {len(live)} живи записа в книгата qm_breakout без return_pct — редът се показва без процента")
print("\n✅ test_render_old_briefs: всичко мина")
