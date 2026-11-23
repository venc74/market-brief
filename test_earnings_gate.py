"""
19.11.2026 (пакет 19.11, т. 5): отчет в хоризонта — ЕДНО правило за всички карти (setup_rules.earnings_gate): отчетът е до config.EARNINGS_BLACKOUT_DAYS работни дни от днес
(вкл.) → картата (CANSLIM, Kullamägi, GLB, buy-stop) пише „⚠ отчет на ДД.ММ — вход след отчета“, без размер (data-blocked — браузърът не смята размер); книгите не записват
нов вход от config.EARNINGS_NO_ENTRY_FROM (backtest._earnings_skip → LAST_EARNINGS_SKIPS); датата е неизвестна → „дата на отчета неизвестна“. enrich.in_blackout — по същото
правило (до 19.11 — 0–7 календарни дни).

РЕАЛНО: tests/fixtures/qm_cards_2026-11-19.json — картите по Kullamägi от 19.11 (J — отчет 23.11, DLTR — 24.11; IDXX, BAX, CSL — февруари 2027). СИНТЕТИЧНО (означено):
датите в т. 1, buy-stop / GLB картите в т. 3, страницата в т. 4.
Пускане: python test_earnings_gate.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, pathlib, tempfile, io, contextlib, re, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_egate_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import setup_rules as sr, enrich, backtest, render

QM = json.loads((ROOT / "tests" / "fixtures" / "qm_cards_2026-11-19.json").read_text(encoding="utf-8"))["qm_breakout"]

print("── 1. правилото: 5 работни дни от днес (вкл.), празникът не се брои (СИНТЕТИЧНИ дати) ──")
g = lambda d, t="2026-11-20": sr.earnings_gate({"next_earnings": d}, t)
assert g("2026-11-27")["sessions"] == 5 and g("2026-11-27")["text"] == "⚠ отчет на 27.11 — вход след отчета"       # 20, 23, 24, 25, 27 (26.11 — Thanksgiving)
assert g("2026-11-30") is None and g("2026-11-20")["sessions"] == 1 and g("2026-11-19") is None
assert sr.earnings_gate({}, "2026-11-20") == {"unknown": True, "text": "дата на отчета неизвестна"} and sr.earnings_gate({}, "2026-11-20", unknown_label=False) is None
assert enrich._in_blackout(dt.date(2026, 11, 27), dt.date(2026, 11, 20)) and not enrich._in_blackout(dt.date(2026, 11, 30), dt.date(2026, 11, 20))

print("  ✓ 27.11 → 5-и работен ден (вход след отчета); 30.11 → 6-и (не); днес → 1; минала → нищо; без дата → „дата на отчета неизвестна“")

print("── 2. РЕАЛНО: картите по Kullamägi от 19.11 ──")
cards = copy.deepcopy(QM)
for c in cards:
    c["levels"] = c.get("levels") or {"entry": c.get("trigger"), "stop": 1.0}
n = sr.annotate_earnings_gate(cards, "2026-11-19")
soon = {c["ticker"]: c["earnings_gate"]["text"] for c in cards if (c.get("earnings_gate") or {}).get("soon")}
assert n == 2 and soon == {"J": "⚠ отчет на 23.11 — вход след отчета", "DLTR": "⚠ отчет на 24.11 — вход след отчета"}, soon
assert all(c["levels"].get("earnings_block") for c in cards if c["ticker"] in soon) and not any(c["levels"].get("earnings_block") for c in cards if c["ticker"] not in soon)
print(f"  ✓ {soon}")

print("── 3. книгите не записват нов вход (СИНТЕТИЧНИ карти) ──")
backtest.LAST_EARNINGS_SKIPS.clear()
J = next(c for c in cards if c["ticker"] == "J")
tr = {}
backtest._ingest_qm_list(tr, "2026-11-20", [J], "Defensive")
assert tr == {} and backtest.LAST_EARNINGS_SKIPS[0] == {"ticker": "J", "category": "qm_breakout", "date": "2026-11-20", "earnings": "2026-11-23"}
tr2 = {}
backtest._ingest_qm_list(tr2, "2026-11-19", [J], "Defensive")                                     # преди правилото — както до 19.11
assert "J_2026-11-19_qm" in tr2
plan = {"valid": True, "method": "v2", "entry_mid": 100.0, "buy_stop": 100.0, "max_chase": 105.0, "stop_loss": 92.0, "target_1": 116.0}
bs = {"ticker": "ZZZ", "setup": {"kind": "below_pivot", "buy_stop": 100.0}, "plan_preview": plan, "earnings_gate": {"soon": True, "date": "2026-11-24"}}
config.BUYSTOP_TRACK_FROM = None
t3 = {}
backtest._ingest_buystop_list(t3, "2026-11-20", [bs], "Defensive")
assert t3 == {}
gw = {"ticker": "YYY", "signal_date": "2026-11-19", "line": 50.0, "close": 52.0, "earnings_gate": {"soon": True, "date": "2026-11-23"}}
t4 = {}
backtest._ingest_glb_wish_list(t4, "2026-11-20", [gw], "Defensive", backtest.CATEGORY_GLB_WISH_HIGH)          # „GLB по Уиш“ (High) — живата книга
assert t4 == {} and {x["category"] for x in backtest.LAST_EARNINGS_SKIPS} >= {"qm_breakout", "buystop", backtest.CATEGORY_GLB_WISH_HIGH}
print("  ✓ QM / buy-stop / GLB по Уиш — без запис от 20.11; преди правилото (19.11) — записът е както досега")

print("── 4. страницата: без размер, редът на картата ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B)
from src import trade_levels
qc = copy.deepcopy(next(c for c in cards if c["ticker"] == "J"))
qc["levels"] = trade_levels.kullamagi_levels(qc["trigger"], qc["adr"], stop_adr=1.0, entry_label="ниво на пробива", regime_factor=0.5)
qc["levels"]["earnings_block"] = qc["earnings_gate"]["text"]
b["qm_breakout"] = [qc]
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
assert 'data-blocked="1"' in page and "⚠ отчет на 23.11 — вход след отчета — без размер" in page and "без размер — отчетът е преди входа" in page
assert 'data-factor="0.5"' in page and "отделна стратегия — без режимен фактор" not in page
print("  ✓ J: „⚠ отчет на 23.11 — вход след отчета — без размер“; data-blocked; режимният фактор 0.5")
print("\n✅ test_earnings_gate: всичко мина")
