"""
06.11.2026 (пакет 05–06.11, т. 5): „Консенсус EPS 2.34 / 2.28“ под Track Record v2 — двата реда са последното в прозорците на иконата за отчетите на отворените позиции (EXPD и WST).
Махнати са от прозорците на книгата; прозорецът на картата Action го пази; таблицата с отчетите и „Следващ отчет · Дата“ остават.

РЕАЛНО: tests/fixtures/track_open_positions_2026-11-06.json (отворените позиции от брифа на 06.11), tests/fixtures/brief_2026-10-19.json (рамката).
СИНТЕТИЧНО (означено): картата Action с прозорец в т. 2 (recap-ът е РЕАЛНИЯТ на EXPD, тикърът е в измислена карта).
Пускане: python test_track_modal_consensus.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_trackmodal_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render

FX = json.loads((ROOT / "tests" / "fixtures" / "track_open_positions_2026-11-06.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))


def page(**over):
    b = copy.deepcopy(B19)
    b.setdefault("backtest", {})["open_positions"] = FX["open_positions"]
    b.update(over)
    with contextlib.redirect_stdout(io.StringIO()):
        return render.render_dashboard(b, publish=False)


print("── 1. книгата: без „Консенсус EPS“ в прозорците на EXPD и WST ──")
assert sorted(o["ticker"] for o in FX["open_positions"]) == ["EXPD", "WST"]
assert sorted(o["earnings_recap"]["forward"]["consensus_eps"] for o in FX["open_positions"]) == [2.28, 2.34]         # до 06.11 — двата реда
p = page(action=[])
assert "Консенсус EPS" not in p and p.count('id="earn-modal-track-') == 2
assert "Earnings История" in p and "Следващ отчет" in p and "2027-02-16 (102д)" in p                                  # останалото в прозореца е на място
print("  ✓ прозорците на EXPD и WST са без реда; таблицата с отчетите и датата на следващия отчет остават")

print("── 2. картата Action го пази (СИНТЕТИЧНА карта с РЕАЛНИЯ recap на EXPD) ──")
m = re.search(r"\{% macro earnings_modal\(modal_id, recap, consensus=true\) %\}", (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8"))
assert m and "{{ earnings_modal(earn_modal_id, st.earnings.recap) }}" in (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
print("  ✓ по подразбиране consensus=true — картата Action вика макроса без него")
print("\n✅ test_track_modal_consensus: всичко мина")
