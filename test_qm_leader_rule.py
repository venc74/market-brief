"""
16.11.2026 (пакет 16.11, т. 16 — решение на Венци): Kullamägi е за ЛИДЕРИ — кандидатът отпада, ако пикът на базата е повече от QM_PEAK_MAX_BELOW_52W_PCT (15) % под 52-седмичния
връх ИЛИ ръстът за 6 месеца е ≤ QM_RET6M_MIN_PCT (0) %. Отпадналите — ред под картите („Отпаднали по правилото за лидер …“), не тихо. Реално: OLED, картата от 13.11 — „предходен
ръст +35%“ от самото 52-седмично дъно (09.10), пикът 28.8% под върха, 6 мес. −2.8%; R и SAIC (16.11) — пикът на върха, 6 мес. +22.1% / +61.7% — остават.

РЕАЛНО: tests/fixtures/qm_leader_rule_daily_2026-11-13.csv — дневните бари от Yahoo (auto_adjust=False) за OLED, R, SAIC, 01.10.2025–13.11.2026, изтеглени 16.11.2026;
tests/fixtures/qm_leader_rule_cards_2026-11-16.json — lead и signal_date от картите (data/2026-11-13.json, 2026-11-16.json); qm_frames_2026-10-02.json — картите от 02.10;
brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): т. 2 — границите на правилото.
Пускане: python test_qm_leader_rule.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_qmlead_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import pandas as pd
from src import qm_breakout as qb, render

FXD = ROOT / "tests" / "fixtures"
D = pd.read_csv(FXD / "qm_leader_rule_daily_2026-11-13.csv")
C = json.loads((FXD / "qm_leader_rule_cards_2026-11-16.json").read_text(encoding="utf-8"))
frame = lambda t: D[D.ticker == t].set_index(pd.DatetimeIndex(pd.to_datetime(D[D.ticker == t]["date"])))[["Open", "High", "Low", "Close", "Volume"]].loc[:C["signal"][t]]

print("── 1. РЕАЛНО: OLED отпада, R и SAIC остават ──")
rows, diag = qb.scan_frames({t: frame(t) for t in ("OLED", "R", "SAIC")}, lead=C["lead"])
assert sorted(r["ticker"] for r in rows) == ["R", "SAIC"]
assert diag["leader_rejects"] == [{"ticker": "OLED", "why": "пикът 28.8% под 52-седм. връх; 6 мес. -2.8%", "peak_vs_52wh_pct": -28.8, "ret6m_pct": -2.8, "runup_pct": 35.0}], diag["leader_rejects"]
r_ = next(r for r in rows if r["ticker"] == "R")
assert round(r_["peak_vs_52wh_pct"], 1) == 0.0 and round(r_["ret6m_pct"], 1) == 22.1
print("  ✓ OLED — „пикът 28.8% под 52-седм. връх; 6 мес. -2.8%“; R (6 мес. +22.1%) и SAIC — карти")

FIX = json.loads((FXD / "qm_frames_2026-10-02.json").read_text(encoding="utf-8"))           # РЕАЛНО: картите от 02.10 (DOCN, CORT, CRL)
B = {t: pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"])) for t, d in FIX["frames"].items()}
r2, d2 = qb.scan_frames({t: B[t] for t in ("DOCN", "CORT", "CRL")}, lead=FIX["lead"], max_dist_adr=2.0)
assert sorted(r["ticker"] for r in r2) == ["CORT", "CRL"] and [(x["ticker"], x["why"]) for x in d2["leader_rejects"]] == [("DOCN", "пикът 19.0% под 52-седм. връх")]
print("  ✓ 02.10: DOCN (6 мес. +55.6%, но пикът 19.0% под върха) — отпада; CORT, CRL — остават")

print("── 2. СИНТЕТИЧНО: двете условия заедно ──")
assert qb.leader_reject({"peak_vs_52wh_pct": -15.0, "ret6m_pct": 0.1}) is None
assert qb.leader_reject({"peak_vs_52wh_pct": -15.1, "ret6m_pct": 40.0}) == "пикът 15.1% под 52-седм. връх"
assert qb.leader_reject({"peak_vs_52wh_pct": -2.0, "ret6m_pct": 0.0}) == "6 мес. +0.0%"
print("  ✓ −15% и +0.1% — минава; −15.1% или 6 мес. ≤ 0 — отпада")

print("── 3. редът под картите ──")
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19); b["qm_breakout"] = rows; b["qm_diag"] = {**diag, "ok": True, "shown": 2}; b["names"] = {"OLED": "Universal Display"}
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
assert "Отпаднали по правилото за лидер (пикът до 15% под 52-седм. връх и ръст за 6 мес. над 0%): OLED" in page and "пикът 28.8% под 52-седм. връх; 6 мес. -2.8% — не се показват и не се записват." in page
print("  ✓ „Отпаднали по правилото за лидер (…): OLED · Universal Display — пикът 28.8% под 52-седм. връх; 6 мес. -2.8%“")
print("\n✅ test_qm_leader_rule: всичко мина")
