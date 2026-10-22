"""
22.10.2026 · етап 4 (добавено 22.10): QM карта на тикър с жив запис в книгата qm_breakout отпреди днес носи „📈 OPEN — вече отворена в книгата qm_breakout от ДД.ММ @ $X —
новото ниво не е нов вход“ (както OPEN✓ при CANSLIM). Реално на 22.10: RVTY с ново ниво $159.48, а книгата държи вход $158.00 от 21.10; втори запис книгата не прави (_is_continuation).

РЕАЛНО: tests/fixtures/qm_rvty_2026-10-22.json — QM картата на RVTY от брифа на 22.10 и записът ѝ от backtest_tracker.json; tests/fixtures/brief_2026-10-19.json — брифът за страницата и имейла.
Пускане: python test_qm_open_mark.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_qmopen_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import backtest, render

FX = json.loads((ROOT / "tests" / "fixtures" / "qm_rvty_2026-10-22.json").read_text(encoding="utf-8"))
card, tracker = FX["card"], FX["record"]
assert round(card["trigger"], 2) == 159.48 and tracker["RVTY_2026-10-21_qm"]["fill_price"] == 158.0

print("── 1. маркерът от книгата ──")
c1 = copy.deepcopy(card)
assert backtest.qm_open_marks([c1], "2026-10-22", tracker) == 1 and c1["book_open"] == {"since": "2026-10-21", "price": 158.0, "status": "open"}
c0 = copy.deepcopy(card)
assert backtest.qm_open_marks([c0], "2026-10-21", tracker) == 0 and "book_open" not in c0       # записът е от днес — картата е самият вход
other = {**copy.deepcopy(card), "ticker": "ZZZZ"}
assert backtest.qm_open_marks([other], "2026-10-22", tracker) == 0
with contextlib.redirect_stdout(io.StringIO()):
    assert backtest.qm_open_marks([copy.deepcopy(card)], "2026-10-22", {"x": None}) == 0           # повреден tracker → 0, без грешка
print("  ✓ RVTY 22.10: вече отворена от 21.10 @ $158.00; в деня на входа — без маркер; друг тикър — без; повреден tracker — без грешка")

print()
print("── 2. страницата и имейлът (РЕАЛНИЯТ бриф от 19.10 с картата на RVTY) ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b["qm_breakout"] = [c1]
with contextlib.redirect_stdout(io.StringIO()):
    page, mail = render.render_dashboard(copy.deepcopy(b)), render.render_email(copy.deepcopy(b))
assert "📈 OPEN — вече отворена в книгата qm_breakout от 21.10 @ $158.00 — новото ниво не е нов вход" in page
assert "📈 вече отворена в книгата от 21.10 @ $158.00 — новото ниво не е нов вход" in mail
print("  ✓ на страницата и в имейла")
print("\n✅ test_qm_open_mark: всичко мина")
