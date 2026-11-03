"""
03.11.2026 · разходката, т. 15 (5–6): книгата „GLB по Уиш“ — обемът на пробива във ВСЕКИ запис и доходността exec (реалистичната — вход по отварянето на следващата сесия).
До 03.11 нито един от 38-те записа на двете книги тип Уиш (11 в glb_wish_high, 27 в архива glb_wish) не пазеше обема на пробива — картата го имаше, записът — не; доходността
5/10/20 сесии след входа беше само literal (от затварянето на сигналния ден). Сега:
  • glb_screener.wish_signal носи breakout_volume_ratio (същото като на картата) → новият запис го пази;
  • записите отпреди 03.11 го получават веднъж от тегленето на резолюцията (backtest.gw_breakout_volume) — и exec доходността на минали срокове (trade_sim.gw_horizons: ret_exec);
  • обобщението носи всички записи (rows), отворените по тип (open_by_type) и exec средните на срок.

РЕАЛНО: tests/fixtures/glb_book_2026-11-03.json.gz — 11-те записа на книгата към 03.11, дневни OHLCV от Yahoo (15.06–03.11) за тикърите им и SPY, GLB картите от брифа на 03.11.
СИНТЕТИЧНО (означено): yf.download, подменен да връща РЕАЛНИТЕ барове; обемът, добавен към баровете на AA в т. 4.
Пускане: python test_glb_book_volume.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_glbvol_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import backtest, glb_screener, trade_sim

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "glb_book_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
BARS = {s: pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"], "Volume": b["v"]}, index=pd.to_datetime(b["d"])) for s, b in FX["bars"].items()}
TODAY = dt.date(2026, 11, 3)
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. обемът на пробива от дневните барове = картата (РЕАЛНО, 03.11) ──")
assert not any("breakout_volume_ratio" in r for r in FX["records"].values())                      # до 03.11 — в нито един запис
same = 0
for r in FX["records"].values():
    v = backtest.gw_breakout_volume(r["signal_date"], BARS[r["ticker"]]["Volume"])
    c = FX["cards"].get(r["ticker"])
    if c and c["since_bar"] == r["signal_date"]:
        assert v == c["breakout_volume_ratio"], (r["ticker"], v, c)
        same += 1
assert same == 9
assert backtest.gw_breakout_volume("2026-10-28", BARS["A"]["Volume"]) == 0.63 and backtest.gw_breakout_volume("2026-10-29", BARS["MTD"]["Volume"]) == 0.63   # без карта (изход по линията)
assert backtest.gw_breakout_volume("2026-11-01", BARS["A"]["Volume"]) is None and backtest.gw_breakout_volume(None, BARS["A"]["Volume"]) is None     # неделя / без дата
assert backtest.gw_breakout_volume("2026-06-20", BARS["A"]["Volume"]) is None                     # под 50 бара история
print("  ✓ 9 от 9 записа с карта: CART 4.38× · GILD 1.06× · AFG 1.26× · ALLE 1.2× · EBAY 1.69× · EHC 2.34× · BRK-B 1.02× · ED 1.46× · MAR 1.75× — същото като на картата; A и MTD (без карта) — 0.63×")

print()
print("── 2. попълването от резолюцията (СИНТЕТИЧНО: yf.download връща РЕАЛНИТЕ барове) ──")
tracker = copy.deepcopy(FX["records"])
assert all(backtest._gw_needs_backfill(r) for r in tracker.values())
ticks = sorted(BARS)
frame = pd.concat({f: pd.DataFrame({t: BARS[t][f] for t in ticks}) for f in ("Open", "High", "Low", "Close", "Volume")}, axis=1)
calls = []
real_dl = backtest.yf.download
backtest.yf.download = lambda tickers, **k: (calls.append(sorted(tickers)), frame[[c for c in frame.columns if c[1] in tickers]])[1]
try:
    with q():
        backtest._resolve_open_positions(tracker, today=TODAY)
finally:
    backtest.yf.download = real_dl
assert len(calls) == 1                                                                            # едно теглене — същото като резолюцията
assert all(isinstance(r.get("breakout_volume_ratio"), float) for r in tracker.values()), {r["ticker"]: r.get("breakout_volume_ratio") for r in tracker.values()}
assert {r["ticker"]: r["breakout_volume_ratio"] for r in tracker.values()}["CART"] == 4.38
hz = {r["ticker"]: r.get("horizons") or {} for r in tracker.values()}
assert all("ret_exec" in x for h in hz.values() for x in h.values()) and set(hz["CART"]) == {"5"}
c5 = hz["CART"]["5"]
o, c = BARS["CART"]["Open"], BARS["CART"]["Close"]
assert c5["ret_exec"] == round((float(c.loc["2026-10-30"]) / float(o.loc["2026-10-26"]) - 1) * 100, 2)   # отварянето на 26.10 → затварянето на 5-ата сесия (30.10)
assert c5["ret"] == FX["records"]["CART_2026-10-26_gwh"]["horizons"]["5"]["ret"] if "CART_2026-10-26_gwh" in FX["records"] else True
assert not any(backtest._gw_needs_backfill(r) for r in tracker.values())                          # веднъж
print(f"  ✓ 11 от 11 записа с обема на пробива след едно теглене; CART 5 сесии: literal {c5['ret']:+.2f}% / exec {c5['ret_exec']:+.2f}% (SPY exec {c5['spy_exec']:+.2f}%); следващият run не тегли наново")

print()
print("── 3. обобщението: всички записи, отворените по тип, exec на срок ──")
real_load = backtest._load_tracker
backtest._load_tracker = lambda: tracker
try:
    with q():
        S = backtest.get_glb_wish_summary(backtest.CATEGORY_GLB_WISH_HIGH)
finally:
    backtest._load_tracker = real_load
assert len(S["rows"]) == 11 and [r["status"] for r in S["rows"]][-2:] == ["line_exit", "line_exit"] and S["rows"][0]["status"] in ("open", "pending")
assert all("breakout_volume_ratio" in r and "return_pct_exec" in r and "fill_exec_price" in r for r in S["rows"])
obt = S["open_by_type"]
assert sum(len(v) for v in obt.values()) == 9 and {r["ticker"] for r in obt["momentum"]} == {"CART", "ALLE", "MAR"}
assert S["horizons"]["5"]["n_exec"] == S["horizons"]["5"]["n"] and S["horizons"]["5"]["avg_ret_exec"] is not None
assert S["closed_group"]["n"] == 2 and S["open_group"]["n"] == 9 and S["open_group"]["n_exec"] == 8      # MAR: вход 02.11 по затварянето; exec (отварянето на 03.11) — още няма цял бар
assert S["closed_group"]["avg_return_pct_exec"] == -1.77 and S["closed_group"]["avg_return_pct"] == -3.09                # реалистичната (exec) и literal — двете в данните
print(f"  ✓ 11 реда (живите първи, затворените A и MTD накрая); отворени и чакащи по тип: Classic {len(obt.get('classic', []))} · Momentum 3 (CART, ALLE, MAR); "
      f"5 сесии exec средно {S['horizons']['5']['avg_ret_exec']:+.2f}% ({S['horizons']['5']['n_exec']} записа)")

print()
print("── 4. новият запис пази обема от сигнала ──")
h = BARS["CART"].copy()
assert backtest.gw_breakout_volume("2026-10-23", h["Volume"]) == glb_screener.breakout_volume_ratio(h.loc[:"2026-10-23"])
trk = {}
with q():
    backtest._ingest_glb_wish_list(trk, "2026-11-04", [{"ticker": "ZZZ", "signal_date": "2026-11-03", "line": 10.0, "close": 11.0, "glb_type": "classic", "breakout_volume_ratio": 2.5}],
                                   "Defensive", backtest.CATEGORY_GLB_WISH_HIGH)
assert next(iter(trk.values()))["breakout_volume_ratio"] == 2.5                                     # СИНТЕТИЧНО: сигналът
src = (ROOT / "src" / "glb_screener.py").read_text(encoding="utf-8")
assert '"breakout_volume_ratio": breakout_volume_ratio(h) if "Volume" in h else None' in src
print("  ✓ сигналът носи обема (wish_signal) → записът го пази; без него — попълва се от резолюцията")
print("\n✅ test_glb_book_volume: всичко мина")
