"""
03.11.2026 · прегледът на 02.11, т. 5: кои книги пазят режима в деня на входа? До 03.11: buy-stop, qm_breakout, „GLB по Уиш“ (close и High) — да (в реалната книга на 03.11:
9/9, 20/20, 27/27, 10/10); Action v2 — НЕ (_new_v2_record нямаше поле; единственият жив запис EXPD 16.10 беше без режим). Сега всеки нов запис във всяка книга получава режима
(Action — от общия път, _stamp_entry_context) и HY OAS в деня на входа (backtest.entry_hy_oas — от информативната плочка „HY / IG OAS“ на термометъра, т. 4); старите записи без
режим — от брифа на деня на записа (EXPD 16.10 → Offensive). HY OAS назад не се попълва — старите брифове нямат плочката.

РЕАЛНО: tests/fixtures/brief_2026-10-16.json — Action EXPD (план v2), Watchlist ZBRA с buy-stop, режимът Offensive; tests/fixtures/fred_oas_2026-11-03.json — HY / IG OAS от FRED.
СИНТЕТИЧНО (означено): картите на QM и „GLB по Уиш“, днешната дата на записа, IEI/HYG статусът, записът без режим отпреди.
Пускане: python test_entry_context.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_entryctx_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
config.QM_TRACK_FROM = config.BUYSTOP_TRACK_FROM = ""
from src import backtest, macro_layer as ml, thermometer as th

FXD = ROOT / "tests" / "fixtures"
B16 = json.loads((FXD / "brief_2026-10-16.json").read_text(encoding="utf-8"))
OAS = json.loads((FXD / "fred_oas_2026-11-03.json").read_text(encoding="utf-8"))["series"]
q = lambda: contextlib.redirect_stdout(io.StringIO())
hy = ml.oas_reading([tuple(x) for x in OAS["BAMLH0A0HYM2"]["obs"]], dt.date(2026, 11, 3))
ig = ml.oas_reading([tuple(x) for x in OAS["BAMLC0A0CM"]["obs"]], dt.date(2026, 11, 3))
tile = th._credit_oas_indicator({"hy": hy, "ig": ig}, {"name": "IEI/HYG (Credit Spread)", "value": 1.489, "status": "green"})     # СИНТЕТИЧНО: IEI/HYG

print("── 1. entry_hy_oas — от плочката на термометъра ──")
thermo = {"regime": "Defensive", "indicators": [{"name": "VIX", "value": 18}, tile]}
assert backtest.entry_hy_oas(thermo) == {"value": 3.44, "as_of": "2026-10-30", "chg_bp": 34, "percentile": 87.9}
assert backtest.entry_hy_oas({"indicators": [{**tile, "hide": True}]}) is None and backtest.entry_hy_oas(B16["thermometer"]) is None and backtest.entry_hy_oas(None) is None
print("  ✓ {value 3.44, as_of 30.10, chg_bp +34, percentile 87.9}; скрита плочка / стар бриф без нея → None")

print()
print("── 2. новите записи във всички книги — режимът и HY OAS в деня на входа (РЕАЛНИТЕ карти от 16.10, СИНТЕТИЧНИТЕ QM / GLB) ──")
act = [c for c in B16["action"] if (c.get("plan") or {}).get("method") == "v2"]
wl = [c for c in B16["watchlist"] if (c.get("setup") or {}).get("kind") == "below_pivot" and c.get("plan_preview")]
assert [c["ticker"] for c in act] == ["EXPD"] and [c["ticker"] for c in wl] == ["ZBRA"]
qmc = [{"ticker": "QMT", "trigger": 50.0, "adr": 4.0, "close": 49.0}]                                                 # СИНТЕТИЧНО
gw = [{"ticker": "GWT", "line": 20.0, "signal_date": "2026-11-02", "close": 20.5, "glb_type": "classic"}]                # СИНТЕТИЧНО
tracker = {}
with q():
    backtest._ingest_new_positions(tracker, act, "2026-11-03", wl, "Defensive", qmc, gw, gw, {"nasdaq": None, "hy_oas": backtest.entry_hy_oas(thermo)})
cats = {backtest.record_category(r): r for r in tracker.values()}
assert set(cats) == {"action", "buystop", "qm_breakout", "glb_wish_high"}, set(cats)                                   # „GLB — наш вариант (close)“ е архив от 26.10 — без нови записи
assert not backtest._gw_book_open(backtest.CATEGORY_GLB_WISH, "2026-11-03")
for c, r in cats.items():
    assert r["regime"] == "Defensive" and r["hy_oas"] == {"value": 3.44, "as_of": "2026-10-30", "chg_bp": 34, "percentile": 87.9}, (c, r.get("regime"), r.get("hy_oas"))
print("  ✓ " + ", ".join(sorted(cats)) + " — режим Defensive и HY OAS 3.44% (+34 б.п., 88. percentile) в деня на входа")

print()
print("── 3. записите отпреди: режимът от брифа на деня на записа; HY OAS — не (старите брифове нямат плочката) ──")
(config.DATA_DIR / "2026-10-16.json").write_text(json.dumps(B16, ensure_ascii=False), encoding="utf-8")                 # РЕАЛНИЯТ бриф от 16.10 като snapshot
old = {"EXPD_2026-10-16": {**backtest._new_v2_record("EXPD", "2026-10-16", act[0]["plan"]), "status": "open"}}            # СИНТЕТИЧНО: записът отпреди, без режим
assert "regime" not in old["EXPD_2026-10-16"]
with q() as log:
    backtest._ingest_new_positions(old, today_date="2026-11-03")
r = old["EXPD_2026-10-16"]
assert (r["regime"], r["regime_source"]) == ("Offensive", "брифът на деня (попълнено 03.11.2026)") and B16["thermometer"]["regime"] == "Offensive"
assert "hy_oas" not in r and "EXPD 2026-10-16 (action): режимът в деня на записа — Offensive (от брифа на деня)" in log.getvalue()
with q() as log2:
    backtest._ingest_new_positions(old, today_date="2026-11-03")
assert "режимът в деня на записа" not in log2.getvalue()                                                                 # идемпотентно
new16 = {}
with q():
    backtest._ingest_new_positions(new16, today_date="2026-11-03")                                                       # snapshot-ът на 16.10 → нов запис EXPD
assert new16["EXPD_2026-10-16"]["regime"] == "Offensive" and new16["EXPD_2026-10-16"]["hy_oas"] is None
print("  ✓ EXPD 16.10 (Action, жив) → Offensive от брифа на деня, с бележка за източника; втори run — нищо; от snapshot — режимът и hy_oas = None")
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'today_context={"nasdaq": qm_market, "hy_oas": backtest.entry_hy_oas(thermo)}' in main_src
print("\n✅ test_entry_context: всичко мина")
