"""
17.11.2026 (пакет 2, т. 1 — А5): CANSLIM на две нива. Сегашният филтър (2 от 3: нетна печалба г/г ≥ 25% по Yahoo, приходи ≥ 20%, ROE ≥ 17%; нетната печалба не спада) остава
вратата; в него „CANSLIM“ е само при C — EPS ОТ ОТЧЕТА (последното тримесечие срещу същото преди година) ≥ 25%; останалите — „Тренд без ръст“ (отделна подсекция);
без EPS от отчета — „EPS: няма данни“ (не е 0 и не минава тихо). Всеки нов запис в книгите пази нивото ("tier").

РЕАЛНО: tests/fixtures/canslim_tiers_2026-11-17.json — EPS от отчета на 19-те карти от 17.11 (14 ≥ 25%; NDAQ 18.2, LLY 6.6, GWW 22.8, BBY 14.8, USFD 17.8 — под);
brief_2026-10-19.json — рамката на страницата. СИНТЕТИЧНО (означено): т. 3 — нивата, сложени на картите от 19.10; т. 4 — картата за книгата.
Пускане: python test_canslim_tiers.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, re, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_tiers_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import setup_rules, render, backtest

FX = json.loads((ROOT / "tests" / "fixtures" / "canslim_tiers_2026-11-17.json").read_text(encoding="utf-8"))["cards"]
tier = lambda c: setup_rules.canslim_tier({"earnings": {"eps_report_yoy": c["eps_report_yoy"]}})

print("── 1. РЕАЛНО: 17.11 — 14 CANSLIM, 5 тренд без ръст ──")
got = {c["ticker"]: tier(c) for c in FX}
assert sum(t["tier"] == "canslim" for t in got.values()) == 14
assert sorted(t for t, v in got.items() if v["tier"] == "trend") == ["BBY", "GWW", "LLY", "NDAQ", "USFD"]
assert got["NDAQ"]["label"] == "EPS от отчета +18% г/г — под 25%"
print(f"  ✓ NDAQ: «{got['NDAQ']['label']}»")

print("── 2. „EPS: няма данни“ — не е 0, не е CANSLIM ──")
assert setup_rules.canslim_tier({"earnings": {}}) == {"tier": "trend", "label": "EPS: няма данни"}
assert setup_rules.canslim_tier({"earnings": {"eps_report_yoy": {"pct": 25.0}}})["tier"] == "canslim"
print("  ✓ без EPS от отчета — „Тренд без ръст“ с етикета; 25.0% — CANSLIM")

print("── 3. страницата и имейлът (СИНТЕТИЧНО: нивата върху картите от 19.10) ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B)
for i, c in enumerate(b["watchlist"]):
    c["tier"] = {"tier": "trend", "label": "EPS: няма данни"} if i == 0 else {"tier": "canslim", "label": "EPS от отчета +40% г/г"}
t0 = b["watchlist"][0]["ticker"]
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
    mail = render.render_email(b)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
sec = txt[txt.index("Тренд без ръст (1)"):]
assert sec.split("Тикър Състояние EPS Защо е тук")[1].strip().startswith(t0) and "EPS: няма данни" in sec
radar_block = txt[txt.index("На радара ("):txt.index("Тренд без ръст (1)")]
assert f" {t0} " not in radar_block[:60]
src_r = (ROOT / "src" / "render.py").read_text(encoding="utf-8")
assert src_r.count('Тренд без ръст — {_e(st["tier"].get("label"))} (не е CANSLIM)') == 2              # имейлът: Action и „Чака пробив“
print(f"  ✓ {t0} — в „Тренд без ръст“ с „EPS: няма данни“; не е в радара на CANSLIM")

print("── 4. книгите пазят нивото (СИНТЕТИЧНА карта) ──")
config.BUYSTOP_TRACK_FROM = None
plan = {"valid": True, "method": "v2", "entry_mid": 100.0, "buy_stop": 100.0, "max_chase": 105.0, "stop_loss": 92.0, "target_1": 116.0}
card = {"ticker": "ZZZ", "setup": {"kind": "below_pivot", "buy_stop": 100.0}, "plan_preview": plan, "tier": {"tier": "trend", "label": "EPS: няма данни"}}
tr = {}
backtest._ingest_buystop_list(tr, "2026-11-18", [card], "Offensive")
assert list(tr.values())[0]["tier"] == "trend"
src = (ROOT / "src" / "backtest.py").read_text(encoding="utf-8")
assert 'tracker[key]["tier"] = (c["tier"] or {}).get("tier")' in src
assert 'c["tier"] = setup_rules.canslim_tier(c)' in (ROOT / "src" / "main.py").read_text(encoding="utf-8")
print("  ✓ buy-stop записът — tier „trend“; Action записите — същото поле")
# 19.11.2026 (пакет 19.11, т. 7): нивото и на реда в книгата (РЕАЛНО: записът на LLY от 19.11 — tier „trend“, EPS от отчета +7% г/г; полетата — дословно)
LLY = {"method": "v2", "ticker": "LLY", "entry_date": "2026-11-19", "status": "pending", "signal_price": 1453.0, "entry_price": 1453.0, "buy_stop": 1453.0, "max_chase": 1525.65,
       "stop_loss": 1336.76, "target_1": 1685.48, "valid_through": "2026-11-25", "category": "buystop", "regime": "Defensive", "pct_from_pivot": -4.83,
       "regime_rule": "2026-11-18", "tier": "trend"}
_orig_load = backtest._load_tracker
backtest._load_tracker = lambda *a, **k: {"LLY_2026-11-19_buystop": dict(LLY)}
try:
    row = next(x for x in backtest.get_buystop_summary()["live"] if x["ticker"] == "LLY")
finally:
    backtest._load_tracker = _orig_load
assert row["tier"] == "trend", row
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "{{ 'Тренд без ръст' if p.tier == 'trend' else 'CANSLIM' }}" in tpl
print("  ✓ редът в buy-stop книгата — „· Тренд без ръст“ / „· CANSLIM“ (LLY 19.11 — „Тренд без ръст“)")
print("\n✅ test_canslim_tiers: всичко мина")
