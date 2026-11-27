"""
27.11.2026 (уикенд пакет, т. 14): buy-stop книгата — статистиката по нивото на картата при записа (CANSLIM / Тренд без ръст; полето е от 17.11 — по-старите „без ниво“).

РЕАЛНО: tests/fixtures/buystop_book_2026-11-27.json — всичките 24 записа на книгата към 27.11. СИНТЕТИЧНО: нищо.
Пускане: python run_tests.py test_buystop_tiers
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, re, io, contextlib, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_bstier_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import backtest, render
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"

REC = json.loads((ROOT / "tests" / "fixtures" / "buystop_book_2026-11-27.json").read_text(encoding="utf-8"))["records"]

print("── 1. РЕАЛНО: групите по ниво ──")
g = backtest.tier_groups(list(REC.values()))
assert list(g) == ["CANSLIM", "Тренд без ръст", "без ниво (записи отпреди 17.11)"], list(g)
assert g["CANSLIM"] == {"records": 5, "triggered": 1, "closed": 0, "avg_r": None, "wins": 0}
assert g["Тренд без ръст"] == {"records": 4, "triggered": 1, "closed": 0, "avg_r": None, "wins": 0}
assert g["без ниво (записи отпреди 17.11)"]["closed"] == 7 and g["без ниво (записи отпреди 17.11)"]["avg_r"] == -1.0
assert sum(x["records"] for x in g.values()) == 23                                                       # 24 − приключилата сделка
print("  ✓ CANSLIM 5 / 1 / 0 · Тренд без ръст 4 / 1 / 0 · без ниво 14 / 10 / 7 (−1.00R)")

print("── 2. обобщението и страницата ──")
backtest._TRACKER_PATH.write_text(json.dumps(REC), encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    s = backtest.get_buystop_summary()
assert s["by_tier"] == g
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B); b.setdefault("backtest", {})["buystop"] = s
with contextlib.redirect_stdout(io.StringIO()):
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False)))
assert "По ниво (записи / с вход / затворени, среден R на затворените): CANSLIM 5 / 1 / 0 · Тренд без ръст 4 / 1 / 0 · без ниво (записи отпреди 17.11) 14 / 10 / 7 (-1.00R, печеливши 0)." in t, t[t.find("По ниво"):t.find("По ниво") + 220]
print("  ✓ редът на страницата")
print("\n✅ test_buystop_tiers: всичко мина")
