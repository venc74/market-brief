"""
27.11.2026 (уикенд пакет, т. 7): календарът на седмицата — ден, който вчера имаше данни, днес е празен → червен ред и последните известни „от ДД.ММ“; отчетите на следените
компании не изчезват мълчаливо; капитализацията — с датата; карето в 15:05 казва какво очаква календарът, когато заглавия няма; плочките за PCE — кога е следващото публикуване.

РЕАЛНО: tests/fixtures/week_calendar_2026-11-23_25.json — календарите от брифовете на 23, 24 и 25.11 (25.11: 11 данни в брифа от 23.11, празно на 24 и 25.11; CRWD 01.12 — в 24.11,
липсва в 25.11); tests/fixtures/bea_schedule_2026-11-27.txt — графикът на BEA. СИНТЕТИЧНО (означено): карето в т. 3.
Пускане: python run_tests.py test_calendar_carry
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, re, io, contextlib, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_calcarry_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import econ_calendar as ec, render

W = json.loads((ROOT / "tests" / "fixtures" / "week_calendar_2026-11-23_25.json").read_text(encoding="utf-8"))["weeks"]
day = lambda w, d: next(x for x in w["days"] if x["date"] == d)

print("── 1. РЕАЛНО: 25.11 — данните от брифа на 23.11 не изчезват мълчаливо ──")
assert len(day(W["2026-11-23"], "2026-11-25")["econ"]) == 11 and not day(W["2026-11-24"], "2026-11-25")["econ"] and not day(W["2026-11-25"], "2026-11-25")["econ"]
w24 = ec.carry_forward(copy.deepcopy(W["2026-11-24"]), W["2026-11-23"], "2026-11-23", dt.date(2026, 11, 24))
d25 = day(w24, "2026-11-25")
assert len(d25["econ"]) == 11 and d25["stale_note"] == "Nasdaq днес не върна данните за деня — последните известни от 23.11"
w25 = ec.carry_forward(copy.deepcopy(W["2026-11-25"]), w24, "2026-11-24", dt.date(2026, 11, 25))
d25b = day(w25, "2026-11-25")
assert len(d25b["econ"]) == 11 and all(e["stale_from"] == "2026-11-23" for e in d25b["econ"]) and "от 23.11" in d25b["stale_note"]
lines = ec.day_lines(d25b)
assert lines[0] == "⚠ Nasdaq днес не върна данните за деня — последните известни от 23.11" and any("(от 23.11)" in l for l in lines[1:]), lines[:3]
assert any(re.search(r"GDP|PCE|Durable|Claims|Home Sales", l) for l in lines)
print(f"  ✓ 24.11 и 25.11: 11 данни за 25.11 „от 23.11“ с червен ред; напр. «{next(l for l in lines if 'GDP' in l or 'PCE' in l)[:90]}»")

print("── 2. РЕАЛНО: CRWD (01.12) — в брифа от 24.11, липсва в 25.11 → остава с бележка ──")
assert "CRWD" in [e["ticker"] for e in day(W["2026-11-24"], "2026-12-01")["earnings"]] and "CRWD" not in [e["ticker"] for e in day(W["2026-11-25"], "2026-12-01")["earnings"]]
crwd = next(e for e in day(w25, "2026-12-01")["earnings"] if e["ticker"] == "CRWD")
assert crwd["date_note"] == "от 24.11 — днес Nasdaq не го показва" and w25["carried"]["items"].count("CRWD") == 1
assert any("CRWD" in l and "от 24.11 — днес Nasdaq не го показва" in l for l in ec.day_lines(day(w25, "2026-12-01")))
assert "капитализация $264 млрд (Nasdaq, 27.11)" == ec.cap_label(264e9, dt.date(2026, 11, 27))
print("  ✓ CRWD — „от 24.11 — днес Nasdaq не го показва“; капитализацията — с датата")

print("── 3. страницата: червеният ред; карето — очакваните данни при празни заглавия (СИНТЕТИЧНО) ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B); b["week_calendar"] = w25; b["date"] = "2026-11-25"
b["preopen"] = {"date": "2026-11-25", "time_ny": "09:05", "time_berlin": "15:05", "ok": True, "session": "2026-11-24", "diag": {"requested": 900, "with_pm": 700},
                "coverage": {"with_pm": 700, "requested": 900}, "gaps": [], "levels": [], "watch": [], "notes": [], "econ": [],
                "econ_expected": ["GDP (QoQ) (08:30)", "Core PCE Price Index (MoM) (08:30)"], "market": {"futures": [{"x": 1}], "text": []}}
with contextlib.redirect_stdout(io.StringIO()):
    html = render.render_dashboard(b, publish=False)
assert '<li style="color:var(--red)">⚠ Nasdaq днес не върна данните за деня — последните известни от 23.11</li>' in html
t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
assert "заглавия в източниците няма, а календарът очаква днес GDP (QoQ) (08:30), Core PCE Price Index (MoM) (08:30)" in t
print("  ✓ червеният ред; „… календарът очаква днес GDP …, Core PCE …“")

print("── 4. РЕАЛНО: следващото публикуване на PCE — по графика на BEA ──")
bea = (ROOT / "tests" / "fixtures" / "bea_schedule_2026-11-27.txt").read_text(encoding="utf-8")
assert re.search(r"December 23 8:30 AM N ?ews Personal Income and Outlays, November 2026", bea) and config.BEA_PIO_RELEASES == ["2026-12-23"]
assert render.next_pio_release("2026-11-27") == "23.12" and render.next_pio_release("2026-12-23") is None
print("  ✓ 23.12 (BEA, Personal Income and Outlays за ноември)")
print("\n✅ test_calendar_carry: всичко мина")
