"""
04.11.2026 · четвърти преглед, Н7: повторен (ръчен) сутрешен бриф след обновяването преди отварянето пази карето „Преди отварянето“ — main чете data/preopen/<днес>.json
(до 04.11 страницата се рендерираше без него, макар файлът да го имаше). В обичайния сутрешен run файлът за деня още не съществува → нищо не се променя.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): съдържанието на data/preopen/<дата>.json, повреденият файл.
Пускане: python test_preopen_rerun.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, inspect
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_prererun_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import main, render

print("── preopen_today ──")
assert main.preopen_today("2026-11-04") is None                                          # обичайната сутрин — файлът още го няма
(config.DATA_DIR / "preopen").mkdir()
PRE = {"date": "2026-11-04", "time_ny": "09:05", "time_berlin": "15:05", "ok": True, "session": "2026-11-03", "diag": {}, "gaps": [], "levels": [], "watch": [], "notes": []}
(config.DATA_DIR / "preopen" / "2026-11-04.json").write_text(json.dumps(PRE), encoding="utf-8")
assert main.preopen_today("2026-11-04") == PRE
(config.DATA_DIR / "preopen" / "2026-11-05.json").write_text("{", encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    assert main.preopen_today("2026-11-05") is None
print("  ✓ няма файл → None; има → карето; повреден → None")

print("── run: карето — преди записа на брифа и рендера ──")
src = inspect.getsource(main.run)
i, j, k = src.index("pre = preopen_today(today)"), src.index('(config.DATA_DIR / f"{today}.json").write_text('), src.index("render_dashboard(brief)")
assert i < j < k
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8")); b["preopen"] = PRE
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
assert "Преди отварянето (15:05 Берлин / 09:05 Ню Йорк)" in page
print("  ✓ main чете файла преди записа и рендера; страницата показва карето")
print("\n✅ test_preopen_rerun: всичко мина")
