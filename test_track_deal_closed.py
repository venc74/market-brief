"""
10.11.2026 (т. 4): заглавието на Track Record v2 и „Реален риск при входа“ не броят записите „приключила сделка“. Реално, брифът от 10.11: „3 Action сигнала“ и „Реален риск при входа … (3 входа)“ —
третият беше ROKU от 09.11 (картата след приключването на сделката; входът — на бар без търговия). Редът „Приключила сделка — извън статистиката“ остава.

РЕАЛНО: tests/fixtures/track_deal_closed_2026-11-10.json (числата от брифа и записите на Action книгата след run-а на 10.11).
Пускане: python test_track_deal_closed.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_trackdeal_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
config.BACKTEST_FILE = config.DATA_DIR / "backtest_tracker.json"
from src import backtest

FX = json.loads((ROOT / "tests" / "fixtures" / "track_deal_closed_2026-11-10.json").read_text(encoding="utf-8"))
assert FX["action_signals"] == 3 and FX["fill_risk"]["n"] == 3                                      # до поправката
recs = FX["records"]
assert sorted(recs) == ["EXPD_2026-10-16", "ROKU_2026-11-09", "WST_2026-11-04"] and recs["ROKU_2026-11-09"]["status"] == "deal_closed"
backtest._save_tracker(copy.deepcopy(recs))
backtest.enrich.earnings_recap = lambda t: None
backtest._fetch_current_prices = lambda tickers: {}
with contextlib.redirect_stdout(io.StringIO()):
    A = backtest.get_backtest_summary()
assert A["action_signals"] == 2 and A["fill_risk"]["n"] == 2 and {x["ticker"] for x in A["fill_risk"]["over"]} == {"WST", "EXPD"}
assert [x["ticker"] for x in A["deal_closed"]] == ["ROKU"]
assert backtest.fill_risk_block([{"ticker": "X", "status": "deal_closed", "fill_risk_pct": 9.0}]) is None
print(f"  ✓ „{A['action_signals']} Action сигнала“ и „Реален риск при входа … ({A['fill_risk']['n']} входа)“ — без ROKU; ROKU — на реда „Приключила сделка“")
print("\n✅ test_track_deal_closed: всичко мина")
