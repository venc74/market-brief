"""
19.10.2026 · етап 2, т. 19 (решение на Венци): short скрийнърът и tracker-ът са ЗАМРАЗЕНИ — без теглене и без запис; кодът и data/short_tracker.json остават, страницата показва един ред.

Секцията на страницата я нямаше — short кандидатите и книгата отиваха само в JSON-а на брифа. Числата се смятат от tracker-а при ПЪРВИЯ run със SHORT_FROZEN и се пазят
в data/short_frozen.json (датата и числата не мърдат после). Реално: на 16.10 — 23 затворени, win 8.7%, среден R −0.73; на 19.10 — 26, 11.5%, −0.39 (BHR +8.57R на 16.10, открит след 16.10),
12 open + 2 trailing.

РЕАЛНО: tests/fixtures/short_tracker_2026-10-19.json (копие на data/short_tracker.json от 19.10, 40 записа); брифът от 19.10 като рамка за страницата. СИНТЕТИЧНО (означено):
временната data/, подменените скрийнър/tracker (трябва да НЕ се викат), датата на замразяването.
Пускане: python test_short_frozen.py
"""
import sys, json, pathlib, tempfile, shutil, io, contextlib, copy, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_short_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DATA_DIR.mkdir()
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.SHORT_FROZEN_FILE = config.DATA_DIR / "short_frozen.json"
from src import short_tracker, render

FX = ROOT / "tests" / "fixtures"
short_tracker._TRACKER_PATH = config.DATA_DIR / "short_tracker.json"
shutil.copy(FX / "short_tracker_2026-10-19.json", short_tracker._TRACKER_PATH)
assert config.SHORT_FROZEN is True                                                     # по подразбиране — замразен
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. числата при замразяването (РЕАЛНИЯТ tracker от 19.10) ──")
with q():
    st = short_tracker.frozen_summary("2026-10-20")                                   # СИНТЕТИЧНА дата на първия run
assert st == {"frozen_on": "2026-10-20", "closed": 26, "wins": 3, "win_rate_pct": 11.5, "avg_realized_r": -0.39, "open_at_freeze": 14}, st
assert json.loads(config.SHORT_FROZEN_FILE.read_text(encoding="utf-8")) == st
before = short_tracker._TRACKER_PATH.read_bytes()
with q():
    st2 = short_tracker.frozen_summary("2026-10-27")
assert st2 == st and short_tracker._TRACKER_PATH.read_bytes() == before              # следващ run — същите числа и дата; tracker-ът не е пипнат
print(f"  ✓ замразен на 20.10: {st['closed']} затворени, win {st['win_rate_pct']}%, среден R {st['avg_realized_r']}, {st['open_at_freeze']} отворени; на 27.10 — същото от файла")

print()
print("── 2. main: без теглене и без запис ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "if config.ENABLE_SHORT_SCREENER and not config.SHORT_FROZEN:" in src
i_frozen, i_update = src.index('short_tracker_summary = {"frozen": short_tracker.frozen_summary(today)}'), src.index("short_tracker.update_short_tracker(short_candidates, today)")
assert i_frozen < i_update and "elif config.ENABLE_SHORT_SCREENER:" in src[i_frozen:i_update]
print("  ✓ скрийнърът се вика само без SHORT_FROZEN; при замразяване — frozen_summary вместо update_short_tracker / get_short_tracker_summary")

print()
print("── 3. редът на страницата (РЕАЛНИЯТ бриф от 19.10 като рамка) ──")
b = json.loads((FX / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b["short_tracker"] = {"frozen": st}
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
with q():
    page = flat(render.render_dashboard(copy.deepcopy(b), publish=False))
assert "Short скрийнър (Stage 4) и книгата му — замразени на 20.10.2026: 26 затворени, win 11.5%, среден R -0.39; 14 отворени при замразяването — не се следят." in page, page[:200]
b2 = copy.deepcopy(b); b2["short_tracker"] = {}
with q():
    assert "Short скрийнър" not in flat(render.render_dashboard(b2, publish=False))  # без замразяване (или стар бриф) — без ред
print("  ✓ един ред: 'замразени на 20.10.2026: 26 затворени, win 11.5%, среден R -0.39; 14 отворени при замразяването — не се следят'")
print("\n✅ test_short_frozen: всичко мина")
