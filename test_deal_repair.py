"""
10.11.2026: последствията от поправката от 09.11 върху РЕАЛНИТЕ данни на 10.11.
  • CART — затворена като „приключила сделка“ по ЕДНО заглавие „Until DoorDash’s proposed deal closes, Maplebear (CART) will keep operating independently.“ (Stock Titan): сделката виси.
    Резервата от новините иска вече заглавия от поне два източника и без думи за бъдеще / условие (until, proposed, will, keep …); приключванията само по новина отпреди 11.11 се връщат като висящи,
    записът в книгата — в предишния статус (резолюцията го смята наново).
  • ROKU — след делистването Yahoo връща само 06.11 и 09.11 (бар без обем): резолюцията на 10.11 премести входа на buy-stop записа от 22.10 ($159.89) на 06.11 ($160.21), а Action записът от 09.11
    получи вход на бара без търговия. Сега: приключилите тикъри не се резолвират, записите се затварят преди резолюцията, вход / цена след датата на приключването не се броят; двата записа —
    върнати към стойностите преди run-а на 10.11.

РЕАЛНО: tests/fixtures/deal_repair_2026-11-10.json (записите и състоянието след run-а на 10.11, заглавията за CART, барите на ROKU), tests/fixtures/roku_deal_2026-11-09.json (заглавията за ROKU).
СИНТЕТИЧНО (означено): записът в т. 4.
Пускане: python test_deal_repair.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_dealrepair_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
config.BACKTEST_FILE = config.DATA_DIR / "backtest_tracker.json"
from src import spinoff_watch as sw, backtest

FX = json.loads((ROOT / "tests" / "fixtures" / "deal_repair_2026-11-10.json").read_text(encoding="utf-8"))
RK = json.loads((ROOT / "tests" / "fixtures" / "roku_deal_2026-11-09.json").read_text(encoding="utf-8"))
D = dt.date(2026, 11, 10)
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. новините: CART — висяща (РЕАЛНОТО заглавие); ROKU — приключила (РЕАЛНИТЕ заглавия) ──")
cart = {"buyer": "DoorDash, Inc.", "announced": "2026-10-28"}
false_t = next(x for x in FX["cart_news"] if x["title"].startswith("Until DoorDash"))
assert sw.news_closed("CART", cart, [false_t], D, "Maplebear Inc.") is None
assert sw.news_closed("CART", cart, FX["cart_news"], D, "Maplebear Inc.") is None
assert sw.news_closed("ROKU", {"buyer": "Fox Corporation", "announced": "2026-06-14"}, RK["news"], dt.date(2026, 11, 7), "Roku, Inc.")["date"] == "2026-11-06"
one = [x for x in RK["news"] if "Reuters" in x["title"] and "completes" in x["title"]][:1]
assert one and sw.news_closed("ROKU", {"buyer": "Fox Corporation", "announced": "2026-06-14"}, one, dt.date(2026, 11, 7), "Roku, Inc.") is None      # един източник не стига
print("  ✓ „Until DoorDash’s proposed deal closes …“ — не; ROKU — над 20 източника; само едно заглавие — не")

print("── 2. състоянието: приключването на CART само по новина се връща като висящо ──")
st = copy.deepcopy(FX["state"])
assert st["closed"]["CART"]["how"].startswith("новина:") and st["closed"]["ROKU"]["how"].startswith("8-K")
assert sw.undo_news_closures(st, config.DEAL_NEWS_RULE_FROM) == ["CART"]
assert "CART" not in st["closed"] and st["pending"]["CART"]["buyer"] == "DoorDash, Inc." and "ROKU" in st["closed"]
assert sw.undo_news_closures(st, config.DEAL_NEWS_RULE_FROM) == []
print("  ✓ CART — висяща; ROKU (8-K) остава приключила")

print("── 3. книгите: CART обратно, ROKU — поправени ──")
backtest._save_tracker(copy.deepcopy(FX["records"]))
with q():
    assert backtest.reopen_deal_records(["CART"]) == ["CART_2026-10-26_gwh"]
    backtest.close_deal_records({}, D)
trk = backtest._load_tracker()
c = trk["CART_2026-10-26_gwh"]
assert c["status"] == "open" and "deal_closed" not in c and c["resolution_date"] is None and c["exit_price"] is None and c["deal_reopened"]["how"].startswith("новина:")
b, a = trk["ROKU_2026-10-20_buystop"], trk["ROKU_2026-11-09"]
assert (b["status"], b["fill_date"], b["fill_price"], b["exit_date"], b["exit_price"]) == ("deal_closed", "2026-10-22", 159.89, "2026-11-06", 160.52)
assert b["deal_closed"]["r"] == 0.06 and b["deal_closed"]["price_date"] == "2026-11-06" and b["deal_closed"]["how"].startswith("8-K")
assert a["fill_price"] is None and a["deal_closed"]["had_position"] is False and a["exit_price"] is None
with q():
    backtest.close_deal_records({}, D)
assert backtest._load_tracker()["ROKU_2026-10-20_buystop"]["fill_price"] == 159.89                 # идемпотентно
print("  ✓ CART: отворена отново; ROKU buy-stop: вход 22.10 по $159.89, изход 06.11 по $160.52 (+0.06R); Action от 09.11: без вход")

print("── 4. занапред: орязаната история и барът без търговия (РЕАЛНИТЕ бари на ROKU; СИНТЕТИЧЕН запис) ──")
B = FX["roku_bars"]
bars = pd.DataFrame({"Open": B["o"], "High": B["h"], "Low": B["l"], "Close": B["c"]}, index=pd.to_datetime(B["d"]))
assert list(bars.index.strftime("%Y-%m-%d"))[-2:] == ["2026-11-06", "2026-11-09"] and B["v"][-1] == 0 and len(B["d"]) <= 3
rec = {"method": "v2", "ticker": "ROKU", "category": "buystop", "entry_date": "2026-10-20", "status": "open", "buy_stop": 159.89, "max_chase": 167.88, "stop_loss": 148.53,
       "target_1": 182.61, "window_sessions": 5, "fill_date": "2026-10-22", "fill_price": 159.89, "current_r": 0.06, "return_pct": 0.39, "last_close": 160.52, "last_close_date": "2026-11-06"}
backtest._save_tracker({"R": dict(rec), "A": {**rec, "category": None, "entry_date": "2026-11-09", "status": "pending", "fill_date": None, "fill_price": None, "last_close": None, "last_close_date": None}})
with q():
    backtest.close_deal_records({"ROKU": {"date": "2026-11-06", "how": "8-K", "buyer": "Fox Corporation"}}, D, bars={"ROKU": bars})
t2 = backtest._load_tracker()
assert t2["R"]["fill_price"] == 159.89 and t2["R"]["deal_closed"]["price"] == 160.52 and t2["R"]["deal_closed"]["price_date"] == "2026-11-06"   # историята не стига до входа — без симулация
assert t2["A"]["deal_closed"]["had_position"] is False                                               # 09.11 е след приключването — няма вход
src = (ROOT / "src" / "backtest.py").read_text(encoding="utf-8")
assert 'rec.get("ticker") not in _closed_t and (' in src                                              # резолюцията прескача приключилите
print("  ✓ орязаната история не мести входа; бар след приключването не е вход; резолюцията прескача приключилите тикъри")
print("\n✅ test_deal_repair: всичко мина")
