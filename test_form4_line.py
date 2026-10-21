"""
21.10.2026 · етап 4, ритъм на данните (решение от 21.10): видим ред за Form 4 и при нула покупки (до тогава нулата беше тишина — секцията „Insider Buying“ отпадна на 06.10,
остана само маркерът INS✓): „Form 4: проверени N тикъра от картите и M позиции — X покупки ≥ $100 000 от ключови лица (officers / клъстер) за 30 дни“.
Провал → „нулата не значи, че няма покупки“; непълно (ok_partial) — бележката в скоби.

РЕАЛНО: tests/fixtures/brief_2026-10-12 / 14 / 15 / 16 / 19.json — статусите insider_buying_status / insider_buying_positions_status на истинските брифове (всичките legit_zero).
СИНТЕТИЧНО (означено): статусите с намерена покупка, с провал и с непълно теглене.
Пускане: python test_form4_line.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_f4_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render

FX = ROOT / "tests" / "fixtures"
print("── 1. реалните статуси (нула покупки) ──")
for d in ("2026-10-12", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19"):
    b = json.loads((FX / f"brief_{d}.json").read_text(encoding="utf-8"))
    c, p = b["insider_buying_status"], b["insider_buying_positions_status"]
    line = render.form4_line(c, p)
    assert line == (f"Form 4: проверени {c['requested']} тикъра от картите и {p['requested']} позиции — 0 покупки ≥ $100 000 от ключови лица (officers / клъстер) за 30 дни"), (d, line)
b19 = json.loads((FX / "brief_2026-10-19.json").read_text(encoding="utf-8"))
print(f"  ✓ пет реални брифа: например 19.10 — «{render.form4_line(b19['insider_buying_status'], b19['insider_buying_positions_status'])}»")

print()
print("── 2. намерена покупка, провал, непълно (СИНТЕТИЧНИ статуси) ──")
one = render.form4_line({"kind": "ok", "requested": 11, "found": 1}, {"kind": "legit_zero", "requested": 5, "found": 0})
assert one.startswith("Form 4: проверени 11 тикъра от картите и 5 позиции — 1 покупка ≥ $100 000") and one.endswith("— маркерът INS✓ на картите")
fail = render.form4_line({"kind": "failed", "note": "няма CIK мапинг от SEC"}, None)
assert fail == "Form 4: проверката не мина днес (от картите: няма CIK мапинг от SEC — нулата не значи, че няма покупки)"
part = render.form4_line({"kind": "ok_partial", "requested": 11, "found": 0, "note": "2 от 11 заявки към SEC не успяха"}, {"kind": "legit_zero", "requested": 5, "found": 0})
assert part.endswith("(от картите, непълно: 2 от 11 заявки към SEC не успяха)") and "нулата не значи" not in part
assert render.form4_line(None, None) is None and render.form4_line({}, {}) is None
assert render.form4_line({"kind": "legit_zero", "requested": 0, "found": 0}, {"kind": "legit_zero", "requested": 2, "found": 0}).startswith("Form 4: проверени 2 позиции — 0 покупки")
assert render.form4_line({"kind": "legit_zero", "requested": 0, "found": 0}, None) is None              # нищо за проверка (06–08.10 без карти) — без ред
print("  ✓ „1 покупка … — маркерът INS✓“; провал — „нулата не значи, че няма покупки“; непълно — бележката; без статуси — без ред")

print()
print("── 3. страницата (РЕАЛНИЯТ бриф от 19.10) ──")
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(copy.deepcopy(b19))
assert "Form 4: проверени 9 тикъра от картите и" in page and page.index("Form 4: проверени") < page.index("Исторически архив")
print("  ✓ редът се вижда на страницата")
print("\n✅ test_form4_line: всичко мина")
