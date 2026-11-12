"""
12.11.2026 (т. 1): в карето в 15:05 — ред „Пазарът преди отварянето“: фючърсите ES и NQ (промяната спрямо 16:00 Ню Йорк на предишната сесия) и компаниите с тегло > 2%
в S&P 500 с гап ≥ ±3% в премаркета, в двете посоки, с цена и %. Реално 12.11, 09:05 Ню Йорк: NVDA −10.8% ($155.09; затваряне $173.85), ES −0.66%, NQ −1.34%.

РЕАЛНО: tests/fixtures/spy_holdings_ssga_2026-11-12.xlsx — дневните позиции на SPY от SSGA (config.SPY_HOLDINGS_URL), свалени 12.11.2026 в 15:50 Берлин, „As of 11-Nov-2026“
(504 реда, SHA-256 059aea22…f6297); tests/fixtures/preopen_market_5m_2026-11-12.csv — 5-минутните бари с премаркет от Yahoo (yf.download, period 5d, prepost) за ES=F, NQ=F
и седемте компании над 2% (с GOOG), изтеглени 12.11.2026 в 15:48 Берлин, изрязани по време: 11.11 00:00 → 12.11 09:45 Ню Йорк (баровете след 09:05 проверяват, че часът
на карето реже); tests/fixtures/brief_2026-10-19.json и ep_aaon_sanm_2026-11-10.json — рамката на страницата и карето.
СИНТЕТИЧНО (означено): т. 3 — провалите (празен отговор, липсващи бари, тегла от предишен ден), т. 4 — компания под прага с ±3% (преместена цена).
Пускане: python test_preopen_market.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_market_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import pandas as pd
from src import preopen, render

FXD = ROOT / "tests" / "fixtures"
XLSX = (FXD / "spy_holdings_ssga_2026-11-12.xlsx").read_bytes()
_df = pd.read_csv(FXD / "preopen_market_5m_2026-11-12.csv")
FRAMES = {s: g.set_index(pd.DatetimeIndex(pd.to_datetime(g["time_utc"], utc=True)))[["Open", "High", "Low", "Close", "Volume"]] for s, g in _df.groupby("symbol")}
FX = json.loads((FXD / "ep_aaon_sanm_2026-11-10.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
NOW = dt.datetime(2026, 11, 12, 14, 7, tzinfo=dt.timezone.utc)                     # 09:07 Ню Йорк = 15:07 Берлин — часът на карето от 12.11

print("── 1. РЕАЛНО: позициите на SPY (SSGA, към 11.11) → компаниите над 2% ──")
h = preopen.parse_spy_holdings(XLSX)
assert h["as_of"] == "2026-11-11" and len(h["rows"]) == 504, (h["as_of"], len(h["rows"]))
assert abs(sum(r["weight"] for r in h["rows"]) - 99.88) < 0.01                    # паричната част е извън таблицата
by = {r["ticker"]: r for r in h["rows"]}
assert "BRK-B" in by and "BF-B" in by and "BRK.B" not in by                         # тикърът във вида на Yahoo
cw = preopen.company_weights(h["rows"])
assert [(c["ticker"], c["weight"]) for c in cw] == [("AAPL", 7.89), ("NVDA", 6.39), ("MSFT", 5.89), ("GOOGL", 4.72), ("AMZN", 3.97), ("AVGO", 2.5), ("META", 2.11)], cw
assert cw[3]["tickers"] == ["GOOGL", "GOOG"]                                         # Alphabet — двата класа заедно (емитент 02079K в CUSIP)
assert round(by["TSLA"]["weight"], 2) == 1.68 and round(by["BRK-B"]["weight"], 2) == 1.67   # под прага — не влизат
print("  ✓ 504 позиции към 11.11; над 2%: AAPL, NVDA, MSFT, GOOGL+GOOG (4.72%), AMZN, AVGO, META; TSLA 1.68% и BRK-B 1.67% — под")

print("── 2. РЕАЛНО: 12.11, 09:07 Ню Йорк — фючърсите и NVDA −10.8% ──")
W = {"as_of": h["as_of"], "source": "позициите на SPY от SSGA", "companies": cw}
m = preopen.market_block(FRAMES, W, NOW)
assert [(f["label"], f["chg_pct"], f["price"], f["prev_close"], f["last_ny"]) for f in m["futures"]] == [
    ("ES (S&P 500)", -0.66, 7592.0, 7642.5, "09:05"), ("NQ (Nasdaq-100)", -1.34, 28103.5, 28484.25, "09:05")], m["futures"]
assert m["session"] == "2026-11-11"
assert [(x["ticker"], x["gap_pct"], x["pm_price"], x["prev_close"]) for x in m["mega"]] == [("NVDA", -10.79, 155.09, 173.85)], m["mega"]
assert [x["ticker"] for x in m["mega_quiet"]] == ["AAPL", "MSFT", "GOOGL", "AMZN", "AVGO", "META"] and m["mega_missing"] == []
T = m["text"]
assert T == ["Фючърси: ES (S&P 500) -0.66% (7 592.00 в 09:05), NQ (Nasdaq-100) -1.34% (28 103.50 в 09:05) — спрямо 16:00 Ню Йорк на 11.11.",
             "С тегло > 2% в S&P 500 (по позициите на SPY от SSGA, към 11.11) и гап ≥ ±3%: NVDA -10.8% ($155.09; затваряне $173.85; тегло 6.4%).",
             "Под ±3%: AAPL, MSFT, GOOGL (с GOOG), AMZN, AVGO, META."], T
# баровете след 09:05 (до 09:45 във fixture-а) не влизат: в 09:40 NVDA е друга цена
later = preopen.market_block(FRAMES, W, dt.datetime(2026, 11, 12, 14, 45, tzinfo=dt.timezone.utc))
assert later["mega"][0]["pm_last_ny"] == "09:25" and later["futures"][0]["last_ny"] == "09:25"           # премаркетът свършва в 09:30
print("  ✓ " + "\n  ✓ ".join(T))

print("── 3. СИНТЕТИЧНО: провалите — редът казва какво липсва, не изчезва ──")
nofut = preopen.market_block({k: v for k, v in FRAMES.items() if not k.endswith("=F")}, W, NOW)
assert nofut["text"][0] == "Фючърсите (ES (S&P 500), NQ (Nasdaq-100)) — без цена в премаркета (Yahoo)."
now_w = preopen.market_block(FRAMES, {"error": "SSGA: HTTPError"}, NOW)
assert now_w["text"][-1] == "Компаниите с тегло > 2% в S&P 500 не са проверени — теглата не се изтеглиха (SSGA: HTTPError)."
miss = preopen.market_block({k: v for k, v in FRAMES.items() if k != "META"}, W, NOW)
assert miss["mega_missing"] == ["META"] and miss["text"][-1] == "Без цена в премаркета: META."
# тегла от предишен ден (SSGA не отговори днес) — от последния записан data/preopen/<дата>.json
pdir = config.DATA_DIR / "preopen"; pdir.mkdir()
(pdir / "2026-11-11.json").write_text(json.dumps({"market": {"weights": W}}), encoding="utf-8")
(pdir / "2026-11-12.json").write_text(json.dumps({"market": {"weights": {**W, "as_of": "2099-01-01"}}}), encoding="utf-8")      # днешният не се ползва
def boom(url):
    raise ConnectionError("blocked")
with contextlib.redirect_stdout(io.StringIO()):
    st = preopen.fetch_weights("2026-11-12", get=boom)
    ok = preopen.fetch_weights("2026-11-12", get=lambda url: XLSX)
    none = preopen.fetch_weights("2026-11-11", get=boom)
assert st["stale"] and st["as_of"] == "2026-11-11" and st["error"] == "SSGA: ConnectionError" and len(st["companies"]) == 7
assert "днешните не се изтеглиха — SSGA: ConnectionError" in preopen.market_block(FRAMES, st, NOW)["text"][1]
assert ok == W and none == {"error": "SSGA: ConnectionError"}
print("  ✓ без фючърси / без тегла / без бар за компания / теглата от предишния ден")

print("── 4. СИНТЕТИЧНО: гап нагоре и няма гап ──")
up = {**FRAMES, "META": FRAMES["META"].copy()}
up["META"].loc[up["META"].index[-12:], "Close"] *= 1.05                                # последните бари (премаркетът) +5%
mu = preopen.market_block(up, W, NOW)
assert [x["ticker"] for x in mu["mega"]] == ["NVDA", "META"] and mu["mega"][1]["gap_pct"] > 3
calm = preopen.market_block({k: v for k, v in FRAMES.items() if k != "NVDA"}, {**W, "companies": [c for c in cw if c["ticker"] != "NVDA"]}, NOW)
assert calm["text"][1].startswith("С тегло > 2% в S&P 500 (по позициите на SPY от SSGA, към 11.11): няма гап ≥ ±3% (AAPL +0.6%, MSFT +0.3%,"), calm["text"][1]
print("  ✓ и в двете посоки; без гап — с процентите на всички")

print("── 5. run(), карето и имейлът ──")
with contextlib.redirect_stdout(io.StringIO()):
    res = preopen.run(NOW, frames5={}, brief={}, records=[], watched=[], universe=[], market_fn=lambda syms: {s: FRAMES[s] for s in syms if s in FRAMES},
                      weights_fn=lambda day: W)
    res0 = preopen.run(NOW, frames5={}, brief={}, records=[], watched=[], universe=[])
    resx = preopen.run(NOW, frames5={}, brief={}, records=[], watched=[], universe=[], market_fn=lambda syms: 1 / 0, weights_fn=lambda day: W)
assert res["market"]["text"] == T and "market" not in res0
assert resx["market"]["futures_missing"] and "без цена в премаркета (Yahoo: ZeroDivisionError)" in resx["market"]["text"][0]
assert not preopen.has_news(res)                                                      # фючърсите не пращат имейл сами
src = (ROOT / "src" / "preopen.py").read_text(encoding="utf-8")
assert "market_fn=fetch_market, weights_fn=fetch_weights)" in src                   # main() тегли и двете
day = {**FX["preopen"], "market": res["market"]}
mail = preopen.email_html(day)
assert "<b>Пазарът преди отварянето:</b> Фючърси: ES (S&amp;P 500) -0.66%" in mail and "NVDA -10.8% ($155.09; затваряне $173.85; тегло 6.4%)" in mail
assert mail.index("Пазарът преди отварянето") < mail.index("EP — гапове")
bb = copy.deepcopy(B19); bb["preopen"] = day
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
assert "<b>Пазарът преди отварянето:</b> Фючърси: ES (S&amp;P 500) -0.66% (7 592.00 в 09:05)" in page and "GOOGL (с GOOG)" in page
assert page.index("Пазарът преди отварянето:") < page.index("EP — гапове")
print("  ✓ run() с / без / с провал на баровете; карето (над EP гаповете) и имейлът; не е повод за имейл сам")
print("\n✅ test_preopen_market: всичко мина")
