"""
22.10.2026 · етап 4 (добавено 22.10): QM карта на тикър с жив запис в книгата qm_breakout отпреди днес носи „📈 OPEN — вече отворена в книгата qm_breakout от ДД.ММ @ $X —
новото ниво не е нов вход“ (както OPEN✓ при CANSLIM). Реално на 22.10: RVTY с ново ниво $159.48, а книгата държи вход $158.00 от 21.10; втори запис книгата не прави (_is_continuation).

РЕАЛНО: tests/fixtures/qm_rvty_2026-10-22.json — QM картата на RVTY от брифа на 22.10 и записът ѝ от backtest_tracker.json; tests/fixtures/brief_2026-10-19.json — брифът за страницата и имейла.
Пускане: python test_qm_open_mark.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
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
assert backtest.qm_open_marks([c1], "2026-10-22", tracker) == 1
assert {k: c1["book_open"][k] for k in ("since", "price", "status", "filled")} == {"since": "2026-10-21", "price": 158.0, "status": "open", "filled": True}
assert c1["book_open"]["level0_date"] == "2026-10-21"                                                # 20.11.2026 (т. 4): първоначалното ниво и денят му
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
assert "📈 OPEN — вход в книгата qm_breakout от 21.10 @ $158.00 — новото ниво не е нов вход" in page        # 20.11.2026 (т. 4): „OPEN“ — само при реален вход
assert "📈 OPEN — вход в книгата от 21.10 @ $158.00 — новото ниво не е нов вход" in mail
lv0 = c1["book_open"]["level0"]
if abs(lv0 - c1["trigger"]) > 0.005:
    assert f"ниво от 21.10 ${lv0:.2f} → днес ${c1['trigger']:.2f}" in page
print("  ✓ на страницата и в имейла")

print("── 3. СИНТЕТИЧНО: запис без вход — „в книгата · чака пробив“, преместеното ниво (20.11.2026, т. 4) ──")
t2 = {"RVTY_2026-10-20_qm": {**copy.deepcopy(tracker["RVTY_2026-10-21_qm"]), "entry_date": "2026-10-20", "fill_date": None, "fill_price": None, "status": "pending",
                             "buy_stop": 157.1, "window_days": [{"date": "2026-10-20", "buy_stop": 157.1}, {"date": "2026-10-21", "buy_stop": 158.0}]}}
c2 = copy.deepcopy(card)
assert backtest.qm_open_marks([c2], "2026-10-22", t2) == 1 and c2["book_open"]["filled"] is False and c2["book_open"]["level0"] == 157.1
b2 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8")); b2["qm_breakout"] = [c2]
with contextlib.redirect_stdout(io.StringIO()):
    page2, mail2 = render.render_dashboard(copy.deepcopy(b2)), render.render_email(copy.deepcopy(b2))
assert "в книгата · чака пробив (от 20.10)" in page2 and "📈 OPEN" not in page2.split("qm-grid", 1)[1].split("</section>", 1)[0]
assert "ниво от 20.10 $157.10 → днес $159.48" in page2 and "в книгата · чака пробив (от 20.10)" in mail2
print("  ✓ „в книгата · чака пробив (от 20.10)“, „ниво от 20.10 $157.10 → днес $159.48“; без „OPEN“")
print("\n✅ test_qm_open_mark: всичко мина")
