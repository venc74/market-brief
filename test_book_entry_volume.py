"""
20.10.2026 · етап 3, част А, т. 1: buy-stop и обемът.

Buy-stop поръчката се изпълнява при ДОКОСВАНЕ — обемът на деня се знае чак при затварянето (AAPL 19.10: High 346.00 > $345.34, затваряне $342.94, обем 0.86×).
Картата казваше "купува се само ако … обем ≥ 1.5×", което buy-stop не може да изпълни.
  (а) текстът на картата казва истината: изпълнение при докосване, обемът — при затварянето, книгата го отбелязва;
  (б) всеки Action / buy-stop запис с вход носи entry_volume_ratio (обемът на деня на входа ÷ средния за 50 бара до него вкл. — както volume_ratio в скрийнъра) и
      entry_volume_ok (≥ BREAKOUT_VOLUME_MULT); обобщенията дават двете групи поотделно (среден R на затворените — чак при stats_visible).
Реално (книгата от 07.10): 4 входа, всички под 1.5× — EXPD 09.10 1.25×, ANET 09.10 0.73×, Action EXPD 16.10 1.32×, AAPL 19.10 0.86×; в брифовете от 03.10
(и преди старта на книгата) — 7 сигнала, 4 входа: 1 с ≥ 1.5× (EXPD 05.10, 1.58×), 3 под.

РЕАЛНО: tests/fixtures/ohlc_EXEL.csv (дневни барове с обем до 02.10; записът EXEL от 25.09 се задейства на 30.09 — test_backtest_v2), ohlc_SPY.csv.
СИНТЕТИЧНО (означено): подмененото теглене, записите за групите, късата история.
Пускане: python test_book_entry_volume.py
"""
import sys, json, pathlib, tempfile, io, contextlib, copy, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_evol_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DATA_DIR.mkdir()
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
from src import backtest, setup_rules
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"

EXEL = pd.read_csv(ROOT / "tests/fixtures/ohlc_EXEL.csv", index_col=0, parse_dates=True)
SPY = pd.read_csv(ROOT / "tests/fixtures/ohlc_SPY.csv", index_col=0, parse_dates=True)
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. обемът на деня на входа (РЕАЛНИ барове на EXEL) ──")
v = EXEL["Volume"][EXEL.index <= pd.Timestamp("2026-09-30")]
want = round(float(v.iloc[-1]) / float(v.iloc[-50:].mean()), 2)
assert backtest.entry_volume("2026-09-30", EXEL) == {"entry_volume_ratio": want, "entry_volume_ok": want >= 1.5} and want == 1.3
assert backtest.entry_volume("2026-09-27", EXEL) == {"entry_volume_ratio": None, "entry_volume_ok": None}          # събота — няма бар
assert backtest.entry_volume("2026-09-30", EXEL.iloc[-40:]) == {"entry_volume_ratio": None, "entry_volume_ok": None}  # СИНТЕТИЧНО: под 50 бара
assert backtest.entry_volume(None, EXEL)["entry_volume_ratio"] is None and backtest.entry_volume("2026-09-30", EXEL[["Close"]])["entry_volume_ratio"] is None
print(f"  ✓ EXEL 30.09: обем {want}× от средния за 50 бара → под 1.5×; без бар / под 50 бара / без обем → None")

print()
print("── 2. през резолюцията: записът получава отметката; затворен стар запис — еднократно (СИНТЕТИЧНО теглене с РЕАЛНИТЕ барове) ──")
seen = {}


def fake_download(tickers, start=None, progress=False, auto_adjust=False, **kw):
    seen["start"] = start
    frames = {t: {"EXEL": EXEL, "SPY": SPY}[t] for t in tickers}
    frames = {t: f[f.index >= pd.Timestamp(start)] if start else f for t, f in frames.items()}
    return pd.concat(frames, axis=1).swaplevel(0, 1, axis=1)


backtest.yf.download = fake_download
backtest._unapplied_splits = lambda rec: []
backtest.enrich.earnings_recap = lambda sym: None                                     # СИНТЕТИЧНО: отчетите на отворените позиции в обобщението са мрежа (None = провал, graceful)
plan = {"method": "v2", "buy_stop": 59.72, "max_chase": 62.71, "stop_loss": 54.94, "target_1": 69.28, "entry_mid": 59.0, "window_sessions": 5}
tr = {"EXEL_2026-09-25": backtest._new_v2_record("EXEL", "2026-09-25", plan),
      "OLD_closed": {"method": "v2", "category": "buystop", "ticker": "EXEL", "entry_date": "2026-09-08", "fill_date": "2026-09-30", "status": "stopped",
                     "realized_r": -1.0}}                                                                                   # СИНТЕТИЧЕН затворен запис без отметка
with q():
    backtest._resolve_open_positions(tr, dt.date(2026, 10, 2))
r = tr["EXEL_2026-09-25"]
assert r["fill_date"] == "2026-09-30" and r["entry_volume_ratio"] == 1.3 and r["entry_volume_ok"] is False
assert tr["OLD_closed"]["entry_volume_ratio"] == 1.3 and tr["OLD_closed"]["status"] == "stopped"                       # само отметката, без нова резолюция
assert seen["start"] == (dt.date(2026, 9, 25) - dt.timedelta(days=backtest.ENTRY_VOLUME_LOOKBACK_DAYS)).isoformat()   # най-ранното от entry_date (живи) и fill_date (без отметка) − 80 дни
print(f"  ✓ EXEL вход 30.09 → entry_volume_ratio 1.3, ok False; затвореният запис без отметка я получава от същото теглене (start {seen['start']})")

print()
print("── 3. двете групи в обобщенията (СИНТЕТИЧНИ записи) ──")
recs = [{"fill_date": "x", "entry_volume_ok": True, "realized_r": 2.0}, {"fill_date": "x", "entry_volume_ok": False, "realized_r": -1.0},
        {"fill_date": "x", "entry_volume_ok": False}, {"fill_date": "x"}, {"status": "pending"}]
g = backtest.entry_volume_groups(recs, visible=False)
assert (g["high"], g["low"], g["unknown"], g["high_avg_r"], g["low_avg_r"]) == (1, 2, 1, None, None)
g = backtest.entry_volume_groups(recs, visible=True)
assert (g["high_avg_r"], g["low_avg_r"], g["high_closed"], g["low_closed"]) == (2.0, -1.0, 1, 1)
backtest._save_tracker(tr)
with q():
    bs, act = backtest.get_buystop_summary(), backtest.get_backtest_summary()
assert bs["entry_volume"]["low"] == 1 and act["entry_volume"]["low"] == 1
print("  ✓ групи ≥ 1.5× / под / без данни; средният R по група — чак при stats_visible; в обобщенията на buy-stop и Action книгите")

print()
print("── 4. (а) текстът на картата ──")
card = {"ticker": "AAPL", "price": 340.0, "pivot": 345.34, "volume_ratio": 0.9, "atr_pct": 2.0}                       # СИНТЕТИЧНА карта под pivot
st = setup_rules.classify_setup(card, dt.date(2026, 10, 19))
assert st["kind"] == "below_pivot" and "изпълнява при докосване (High ≥ $345.34)" in st["trigger_text"] and "обемът се вижда едва при затварянето" in st["trigger_text"]
assert "Купува се само ако" not in st["trigger_text"]
print("  ✓", st["trigger_text"])

print()
print("── 5. страницата ──")
from src import render
B = json.loads((ROOT / "tests/fixtures/brief_2026-10-19.json").read_text(encoding="utf-8"))
B["backtest"] = {**B["backtest"], "entry_volume": act["entry_volume"], "buystop": {**B["backtest"]["buystop"], "entry_volume": bs["entry_volume"]}}
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
with q():
    page = flat(render.render_dashboard(B, publish=False))
assert "Денят на входа (по затварянето): обем ≥ 1.5× среден — 0 · под 1.5× — 1" in page and "Buy-stop поръчката се изпълнява при докосване; обемът не е условие за входа." in page
print("  ✓ ред 'Денят на входа (по затварянето): обем ≥ 1.5× среден — N · под 1.5× — M' в двете книги")
print("\n✅ test_book_entry_volume: всичко мина")
