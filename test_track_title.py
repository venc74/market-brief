"""
Track Record v2 · заглавието казва колко Action сигнала са записани от старта (08.10.2026, code-queue). Преди: «Track Record v2 · 0 резолвирани» — на 08.10 книгата беше без резолвирани сделки, но това не казва
дали системата е дала сигнали (чакащи buy-stop, отворени, незадействани) или е мълчала. Сега: «Track Record v2 · 3 Action сигнала от 05.10 · 0 резолвирани». backtest.get_backtest_summary() връща
"action_signals" = всички v2 Action записи (всички статуси); buy-stop и qm_breakout книгите и v1 архивът не се броят.

РЕАЛНО: брифът от 05.10.2026 (tests/fixtures/brief_2026-10-05.json) — секцията Track Record v2 с methodology.switched_on = 2026-10-05, 0 резолвирани, без ключа action_signals (старият формат).
СИНТЕТИЧНО (маркирано): записите на tracker-а (тикъри AAA…), подменената директория data/.
Пускане: python test_track_title.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import backtest, render

_tmp = tempfile.TemporaryDirectory(prefix="mb_title_")
config.DATA_DIR, config.DOCS_DIR = pathlib.Path(_tmp.name) / "data", pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
config.ENABLE_BACKTEST = True
backtest._fetch_current_prices = lambda tickers: {}
backtest.enrich.earnings_recap = lambda t: None


def rec(ticker, status, category=None, method="v2", **kw):
    r = {"method": method, "ticker": ticker, "entry_date": "2026-10-05", "status": status, "entry_price": 100.0, "buy_stop": 100.0, "max_chase": 105.0, "stop_loss": 92.0,
         "target_1": 116.0, "window_sessions": 5, "fill_date": None, "realized_r": None, "resolution_date": None, "discovered_date": None}
    if category:
        r["category"] = category
    r.update(kw)
    return r


def write(records):
    backtest._save_tracker({f"{r['ticker']}_{r['entry_date']}_{r.get('category', 'action')}_{r['method']}": r for r in records})


print("── action_signals в обобщението (СИНТЕТИЧЕН tracker) ──")
write([rec("AAA", "open", fill_date="2026-10-06"), rec("BBB", "pending"), rec("CCC", "not_triggered"), rec("DDD", "stopped", realized_r=-1.0, resolution_date="2026-10-07", fill_date="2026-10-06"),
       rec("EEE", "skipped_extended"),
       rec("BS1", "open", "buystop", fill_date="2026-10-06"), rec("QM1", "open", "qm_breakout", fill_date="2026-10-06"), rec("OLD", "stopped", method="v1", realized_r=-1.0, resolution_date="2026-10-01")])
with contextlib.redirect_stdout(io.StringIO()):
    S = backtest.get_backtest_summary()
assert S["action_signals"] == 5 and S["total_resolved"] == 1 and S["pending"] == 1 and S["still_open"] == 1, (S["action_signals"], S["total_resolved"])
print("  ✓ 5 = отворена + чакаща + незадействана + затворена + прескочена; buy-stop (BS1), qm_breakout (QM1) и v1 (OLD) не се броят; резолвираните остават 1")
write([])
with contextlib.redirect_stdout(io.StringIO()):
    assert backtest.get_backtest_summary()["action_signals"] == 0

print()
print("── заглавието на страницата (РЕАЛНИЯТ бриф от 05.10) ──")
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
bt = B05["backtest"]
assert bt["methodology"]["switched_on"] == "2026-10-05" and bt["total_resolved"] == 0 and "action_signals" not in bt and bt.get("v1_archive")
h2 = lambda page: next(l for l in page.splitlines() if "Track Record v2 ·" in l and "<h2>" in l).strip()
with contextlib.redirect_stdout(io.StringIO()):
    old = render.render_dashboard(copy.deepcopy(B05))
assert h2(old) == "<h2>Track Record v2 · 0 резолвирани</h2>"
print("  ✓ старият формат (без action_signals) — заглавието е както досега")
for n, want in ((0, "0 Action сигнала от 05.10 · 0 резолвирани"), (1, "1 Action сигнал от 05.10 · 0 резолвирани"), (3, "3 Action сигнала от 05.10 · 0 резолвирани")):
    b = copy.deepcopy(B05)
    b["backtest"]["action_signals"] = n
    with contextlib.redirect_stdout(io.StringIO()):
        page = render.render_dashboard(b)
    assert h2(page) == f"<h2>Track Record v2 · {want}</h2>", h2(page)
print("  ✓ 0 → «0 Action сигнала от 05.10 · 0 резолвирани»; 1 → «1 Action сигнал …»; 3 → «3 Action сигнала …»")
b = copy.deepcopy(B05); b["backtest"].update(action_signals=2, total_resolved=1, wins=0, losses=1, win_rate_pct=0.0, avg_realized_r=-1.0); b["backtest"]["methodology"] = {"version": "v2", "switched_on": None}   # СИНТЕТИЧНО: без дата на старта
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b)
assert h2(page) == "<h2>Track Record v2 · 2 Action сигнала · 1 резолвирани</h2>"
print("  ✓ СИНТЕТИЧНО: без дата на старта — «2 Action сигнала · 1 резолвирани» (без «от …»)")
print("\n✅ test_track_title: всичко мина")
