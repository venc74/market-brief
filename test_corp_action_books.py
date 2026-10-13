"""
13.10.2026 · книгите при СЪЩЕСТВЕНО отделяне след входа (нецял коефициент ≥ 1.10 или "material" в CORP_ACTIONS_KNOWN): Action и buy-stop → needs_manual_review вместо корекция като сплит;
"GLB по Уиш" → needs_manual_review вместо мащабиране на линията (както QM). Под прага — както досега (корекция като сплит / мащабиране).

Защо (доклад от 13.10): _apply_split_adjustment приемаше 6.665 като сплит — санитарната проверка минава, защото историята на Yahoo е в същата оценка, а стойността на новата компания не се брои;
книгата на Уиш мащабираше линията със същия коефициент.

РЕАЛНО: дневните затваряния на CTVA (6.665 на 01.10.2026), SPGI (1.057 на 01.07.2026) и HON (0.9535 на 29.06.2026) от tests/fixtures/corp_actions_2026-10-13.json и
corp_actions_materiality_2026-10-13.json; коефициентите — реалните от Yahoo. СИНТЕТИЧНО (означено): записите в книгите (дати, нива), Open/High/Low = Close, подмененото теглене, временният tracker.
Пускане: python test_corp_action_books.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_corpbooks_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import backtest, trade_sim

backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
FX = {**json.loads((ROOT / "tests" / "fixtures" / "corp_actions_2026-10-13.json").read_text(encoding="utf-8"))["tickers"],
      **json.loads((ROOT / "tests" / "fixtures" / "corp_actions_materiality_2026-10-13.json").read_text(encoding="utf-8"))["tickers"]}
CLOSE = {t: pd.Series(v["close"], index=pd.to_datetime(v["dates"])) for t, v in FX.items()}
SPLIT = {"CTVA": [{"date": "2026-10-01", "ratio": 6.665}], "SPGI": [{"date": "2026-07-01", "ratio": 1.057}], "HON": [{"date": "2026-06-29", "ratio": 0.9535}]}


def fake_download(tickers, start=None, progress=False, auto_adjust=False, **k):              # СИНТЕТИЧНО: Open/High/Low = Close (РЕАЛНИТЕ затваряния)
    fr = {t: CLOSE[t] for t in tickers if t in CLOSE}
    return pd.concat({f: pd.DataFrame(fr) for f in ("Open", "High", "Low", "Close")}, axis=1)


backtest.yf.download = fake_download
backtest._unapplied_splits = lambda rec: list(SPLIT.get(rec["ticker"], []))
adjusted = []
real_adjust = backtest._apply_split_adjustment_v2
backtest._apply_split_adjustment_v2 = lambda rec, splits, closes, today: adjusted.append((rec["ticker"], [s["ratio"] for s in splits])) or False


def rec(t, cat, entry, price):                                                                # СИНТЕТИЧЕН запис преди събитието
    r = {"method": "v2", "ticker": t, "entry_date": entry, "status": "open", "fill_date": entry, "fill_price": price, "entry_price": price, "signal_price": price,
         "buy_stop": price, "max_chase": round(price * 1.05, 2), "stop_loss": round(price * 0.92, 2), "target_1": round(price * 1.16, 2), "resolution_date": None}
    if cat:
        r["category"] = cat
    return r


print("── 1. Action и buy-stop ──")
tr = {"CTVA_bs": rec("CTVA", "buystop", "2026-09-15", 77.0), "HON_a": rec("HON", None, "2026-06-01", 230.0), "SPGI_a": rec("SPGI", None, "2026-06-10", 520.0)}
before = copy.deepcopy(tr)
with contextlib.redirect_stdout(io.StringIO()) as out:
    backtest._resolve_open_positions(tr, dt.date(2026, 10, 13))
for k in ("CTVA_bs", "HON_a"):
    nm = tr[k]["needs_manual_review"]
    assert nm["reason"] == "spin_off_after_entry" and nm["since"] == "2026-10-13"
    assert all(tr[k][f] == before[k][f] for f in ("stop_loss", "target_1", "entry_price", "status", "buy_stop"))     # нивата и статусът — непокътнати
assert tr["CTVA_bs"]["needs_manual_review"]["split_ratio"] == 6.665 and tr["HON_a"]["needs_manual_review"]["split_date"] == "2026-06-29"
assert adjusted == [("SPGI", [1.057])] and "needs_manual_review" not in tr["SPGI_a"]                        # под прага — корекцията като сплит, както досега
assert "отделяне (коефициент 6.665) на 2026-10-01 след входа" in out.getvalue()
since = tr["CTVA_bs"]["needs_manual_review"]["since"]
with contextlib.redirect_stdout(io.StringIO()):
    backtest._resolve_open_positions(tr, dt.date(2026, 10, 14))
assert tr["CTVA_bs"]["needs_manual_review"]["since"] == since                                               # идемпотентно
print("  ✓ CTVA (buy-stop, 6.665) и HON (Action, 0.9535 по таблицата) → needs_manual_review 'spin_off_after_entry', нивата непокътнати; SPGI (1.057) → корекция като сплит, както досега")

print()
print("── 2. GLB по Уиш ──")
c = CLOSE["CTVA"]
sig = "2026-09-15"
raw = float(c[sig]) * 6.665                                                                                   # затварянето на сигналния ден в старата скала (както се записва при сигнала)
gw = {"method": "v2", "category": "glb_wish", "ticker": "CTVA", "entry_date": "2026-09-16", "signal_date": sig, "line": round(raw * 0.97, 4), "signal_close": round(raw, 4), "status": "open",
      "resolution_date": None}
res = trade_sim.simulate_glb_wish(gw, pd.DataFrame({"Open": c, "Close": c}), dt.date(2026, 10, 13))
assert res["split_scale"] == 6.665                                                                            # без правилото — линията се мащабира с оценката
tr2 = {"CTVA_gw": copy.deepcopy(gw)}
with contextlib.redirect_stdout(io.StringIO()):
    backtest._resolve_open_positions(tr2, dt.date(2026, 10, 13))
g = tr2["CTVA_gw"]
assert g["needs_manual_review"]["reason"] == "spin_off_after_entry" and g["needs_manual_review"]["split_ratio"] == 6.665 and g.get("line_used") is None and g["status"] == "open"
s = CLOSE["SPGI"]
gw2 = {**gw, "ticker": "SPGI", "signal_date": "2026-06-15", "entry_date": "2026-06-16", "signal_close": round(float(s["2026-06-15"]) * 1.057, 4), "line": round(float(s["2026-06-15"]) * 1.057 * 0.97, 4)}
tr3 = {"SPGI_gw": gw2}
with contextlib.redirect_stdout(io.StringIO()):
    backtest._resolve_open_positions(tr3, dt.date(2026, 10, 13))
assert "needs_manual_review" not in tr3["SPGI_gw"] and tr3["SPGI_gw"]["split_scale"] == 1.057                 # под прага — мащабиране, както досега
print("  ✓ CTVA (6.665 след сигнала) → needs_manual_review, линията не се мащабира, резултатът не се записва; SPGI (1.057) → мащабиране, както досега")

print()
print("── 3. обобщенията показват броя ──")
backtest._save_tracker({**tr, **tr2})
bs, gws = backtest.get_buystop_summary(), backtest.get_glb_wish_summary()
assert bs["needs_review"] == 1 and gws["needs_review"] == 1
print("  ✓ buy-stop: 1 за преглед; GLB по Уиш: 1 за преглед")
backtest._apply_split_adjustment_v2 = real_adjust
print()
print("Всички тестове минаха.")
