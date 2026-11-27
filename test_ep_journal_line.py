"""
27.11.2026 (уикенд пакет, т. 12): дневникът на EP на страницата — САМО един ред: N гапа, колко % отварят ≥ прага, медианата на отварянето — без дните на пазарен гап (по реалното
отваряне на QQQ / SPY); детайлите („Вчерашният дневник …“ по тикъри, общите броеве) остават в данните (qm_ep.log).

РЕАЛНО: tests/fixtures/ep_log_2026-11-27.json — дневникът към 27.11 (84 записа; 59 от разрешените са от 23.11 — карето записа всички гапове в деня на пазарния гап);
tests/fixtures/spy_qqq_daily_2026-11-27.json — дневните бари SPY / QQQ. СИНТЕТИЧНО: нищо.
Пускане: python run_tests.py test_ep_journal_line
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, re, io, contextlib, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_epj_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import qm_ep, market_gap, render

E = json.loads((ROOT / "tests" / "fixtures" / "ep_log_2026-11-27.json").read_text(encoding="utf-8"))["entries"]
D = json.loads((ROOT / "tests" / "fixtures" / "spy_qqq_daily_2026-11-27.json").read_text(encoding="utf-8"))
gaps = market_gap.open_gaps({s: pd.DataFrame({"Open": D[s]["Open"], "Close": D[s]["Close"]}, index=pd.to_datetime(D[s]["index"])) for s in ("SPY", "QQQ")})
gd = {d for d, v in gaps.items() if v["gap"]}

print("── 1. РЕАЛНО: обобщението без дните на пазарен гап ──")
allj = qm_ep.summarize_journal(E, set())
j = qm_ep.summarize_journal(E, gd)
assert (allj["n"], allj["held_pct"], allj["median_open_gap_pct"]) == (83, 90.0, 15.22)
assert (j["n"], j["excluded"], j["excluded_days"], j["held_pct"], j["median_open_gap_pct"], j["since"]) == (24, 59, ["2026-11-23"], 88.0, 12.2, "2026-10-09"), j
print(f"  ✓ с дните на гап: 83 гапа, 90%, медиана +15.2%; без тях: 24 гапа, 88%, медиана +12.2% (без 59 от 23.11)")

print("── 2. страницата — един ред, без „Вчерашният дневник“ ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B)
b["qm_ep"] = {**(b.get("qm_ep") or {}), "ok": True, "rows": [], "log": {**qm_ep.summarize_log(E), "journal": j, "yesterday": [{"ticker": "ANF", "session": "2026-11-23", "gap_session": "2026-11-24",
              "ah_gap_pct": 10.6, "open_gap_pct": 13.13, "close_pct": 19.69, "held": True}], "yesterday_pm": [], "preopen": qm_ep.summarize_preopen(E)}}
with contextlib.redirect_stdout(io.StringIO()):
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False)))
line = "Дневникът на EP (от 09.10): 24 гапа — 88% отварят ≥ 10%, медиана на отварянето +12.2% · без дните на пазарен гап (59 гапа: 23.11)."
assert line in t, t[t.find("Дневникът на EP"):t.find("Дневникът на EP") + 220]
assert "Вчерашният дневник" not in t and "Гаповете от карето в 09:05 Ню Йорк" not in t and "корелация" not in t
print(f"  ✓ «{line}»")
print("\n✅ test_ep_journal_line: всичко мина")
