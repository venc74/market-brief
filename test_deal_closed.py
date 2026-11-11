"""
09.11.2026 (спешна поправка, ROKU): Fox приключи придобиването на ROKU на 06.11 след затварянето (8-K 1.02,2.01,3.01,3.03,5.01,… и 25-NSE), а брифът от 09.11 даде ROKU като единствения „Купува се днес“.
Защо: маркерът „цел на придобиване“ се махаше при приключването (merger_state → "closed"), а тикърът оставаше — в Wikipedia (S&P 400) и с реален последен бар (06.11: 11.5 млн акции, 4.6× обем),
затова и bar_freshness го прие (бар от очакваната сесия 06.11). Поправката: висящата цел остава „deal“ до приключването (и при провал на EDGAR, и извън прозореца от 540 дни); приключила сделка /
делистване → вън от универса (всички модули, лидерите на секторите), от кандидатите и от живите записи в книгите („приключила сделка“, извън статистиката); последен бар без търговия → не е кандидат.

РЕАЛНО: tests/fixtures/roku_submissions_2026-11-09.json (подаванията в EDGAR), tests/fixtures/roku_deal_2026-11-09.json (картата, записите, 8-K документът, заглавията), tests/fixtures/wiki_*_2026-10-30.html.gz
(таблиците на универса — ROKU е в S&P 400), tests/fixtures/brief_2026-10-19.json (рамката).
СИНТЕТИЧНО (означено): подаванията, отрязани преди приключването (т. 2), бъдещото заглавие (т. 3), подаването само с Form 25 (т. 1), барите в т. 6.
Пускане: python test_deal_closed.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, types, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_dealclosed_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
config.BACKTEST_FILE = config.DATA_DIR / "backtest_tracker.json"
from src import spinoff_watch as sw, screener, backtest, render

FXD = ROOT / "tests" / "fixtures"
SUB = json.loads((FXD / "roku_submissions_2026-11-09.json").read_text(encoding="utf-8"))["sub"]
FX = json.loads((FXD / "roku_deal_2026-11-09.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
D = dt.date(2026, 11, 9)
CIK = {"ROKU": "0001428439"}
q = lambda: contextlib.redirect_stdout(io.StringIO())


def cut(sub, until):                                                                  # СИНТЕТИЧНО: подаванията до дата (реалните редове)
    r = sub["filings"]["recent"]
    keep = [i for i, d in enumerate(r["filingDate"]) if d < until]
    return {**sub, "filings": {"recent": {k: [v[i] for i in keep] for k, v in r.items()}}}


def seed_cache():
    (config.DATA_DIR / config.SPINOFF_CACHE_NAME).write_text(json.dumps({"version": 1, "docs": {}, "merger_docs": FX["merger_docs"]}), encoding="utf-8")


def getter(sub):
    def get(url):
        if "submissions" in url:
            return json.dumps(sub)
        raise AssertionError(f"неочаквано теглене: {url}")                           # документът е в кеша (РЕАЛНИЯТ)
    return get


print("── 1. следата в EDGAR (РЕАЛНИТЕ подавания на ROKU) ──")
ev = sw.closing_evidence(SUB, "2026-06-15", D)
assert ev == {"date": "2026-11-06", "how": "8-K т. 1.02,2.01,3.01,3.03,5.01,5.02,5.03,9.01"}, ev
assert sw.closing_evidence(cut(SUB, "2026-11-06"), "2026-06-15", D) is None                     # до 06.11 — висяща
assert sw.closing_evidence(SUB, None, D)["date"] == "2026-11-06"                                 # и без известна сделка: 2.01 + 3.01 в последните 30 дни
only25 = {"filings": {"recent": {"form": ["25-NSE"], "filingDate": ["2026-11-06"], "items": [""]}}}        # СИНТЕТИЧНО: само Form 25 (както при облигациите на C, DHR, CMCSA)
assert sw.closing_evidence(only25, None, D) is None and sw.closing_evidence(only25, "2026-06-15", D) is None
both = {"filings": {"recent": {"form": ["8-K", "25"], "filingDate": ["2026-10-29", "2026-11-09"], "items": ["3.01,9.01", ""]}}}      # СИНТЕТИЧНО по РЕАЛНИТЕ дати на CFR (се търгува)
assert sw.closing_evidence(both, None, D) is None
c501 = {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-10-21"], "items": ["5.01,8.01,9.01"]}}}                   # СИНТЕТИЧНО по РЕАЛНИЯ 8-K на UFPI (се търгува)
assert sw.closing_evidence(c501, None, D) is None and sw.closing_evidence(c501, "2026-06-15", D) == {"date": "2026-10-21", "how": "8-K т. 5.01,8.01,9.01"}   # при известна цел 5.01 стига
assert sw.merger_state(SUB, "2026-06-15") == "closed" and sw.merger_state(cut(SUB, "2026-11-06"), "2026-06-15") is None
print(f"  ✓ ROKU: {ev['how']} на 06.11; Form 25 сам, 3.01 с Form 25 и 5.01 без известна сделка — не стигат (CFR, HLT, UFPI, 27 тикъра с Form 25)")

print("── 2. check(): приключила → вън, висяща → „deal“ и при провал на EDGAR и извън прозореца ──")
seed_cache()
with q():
    sw.check(["ROKU"], D, get=getter(SUB), cik_map=CIK, merger_tickers=["ROKU"])
assert "ROKU" in sw.LAST_CLOSED and "ROKU" not in sw.LAST_MERGERS
st = sw.load_state()
assert st["closed"]["ROKU"]["date"] == "2026-11-06" and st["closed"]["ROKU"]["buyer"] == "Fox Corporation" and "ROKU" not in st["pending"]
assert sw.closed_text(st["closed"]["ROKU"]) == "сделката с Fox Corporation е приключила на 06.11 (8-K т. 1.02,2.01,3.01,3.03,5.01,5.02,5.03,9.01)"
sw.save_state({"version": 1, "pending": {}, "closed": {}}); seed_cache()
with q():
    sw.check(["ROKU"], dt.date(2026, 11, 5), get=getter(cut(SUB, "2026-11-06")), cik_map=CIK, merger_tickers=["ROKU"])
assert sw.LAST_MERGERS["ROKU"]["buyer"] == "Fox Corporation" and sw.load_state()["pending"]["ROKU"]["announced"] == "2026-06-14"   # 05.11: висяща → в състоянието
with q():
    sw.check(["ROKU"], dt.date(2026, 11, 5), get=lambda u: (_ for _ in ()).throw(TimeoutError("EDGAR")), cik_map=CIK, merger_tickers=["ROKU"])
assert sw.LAST_MERGERS["ROKU"]["buyer"] == "Fox Corporation"                                   # провал на EDGAR — етикетът остава
with q():
    sw.check(["ROKU"], dt.date(2028, 6, 1), get=getter(cut(SUB, "2026-11-06")), cik_map=CIK, merger_tickers=["ROKU"])
assert "ROKU" in sw.LAST_MERGERS                                                                 # 8-K 1.01 е извън 540-те дни — етикетът остава от състоянието
print("  ✓ на 06.11 вечерта — „приключила“; преди това — „deal“, и при провал на EDGAR, и след 540 дни")

print("── 3. преди скрийнинга: известните цели от кеша; резервата — новините ──")
sw.save_state({"version": 1, "pending": {}, "closed": {}}); seed_cache()
with q():
    r = sw.refresh_deals(D, get=getter(SUB), cik_map=CIK, news_fn=lambda t, n: [])
assert r["checked"] == ["ROKU"] and [x["ticker"] for x in r["closed"]] == ["ROKU"] and sw.closed_tickers()["ROKU"]["how"].startswith("8-K")
sw.save_state({"version": 1, "pending": {}, "closed": {}}); seed_cache()
# 11.11.2026 (т. 1): по подразбиране приключване САМО по 8-K — реалните заглавия от 06.11 НЕ затварят ROKU, когато EDGAR още няма следа
assert config.DEAL_CLOSE_BY_NEWS is False
with q():
    r = sw.refresh_deals(D, get=getter(cut(SUB, "2026-11-06")), cik_map=CIK, news_fn=lambda t, n: FX["news"], name_lookup=lambda t: "Roku, Inc.")      # EDGAR без следа, новините — РЕАЛНИТЕ
assert r["closed"] == [] and "ROKU" not in sw.closed_tickers() and "ROKU" in sw.pending_tickers()
sw.save_state({"version": 1, "pending": {}, "closed": {"ROKU": {"ticker": "ROKU", "how": "новина: Fox completes …", "seen": "2026-11-12"}}}); seed_cache()
with q():
    r = sw.refresh_deals(D, get=getter(cut(SUB, "2026-11-06")), cik_map=CIK, news_fn=lambda t, n: FX["news"], name_lookup=lambda t: "Roku, Inc.")
assert r.get("reopened") == ["ROKU"] and "ROKU" not in sw.closed_tickers()                       # затваряне по новина в състоянието (и след 11.11) → обратно във „висящи“
config.DEAL_CLOSE_BY_NEWS = True                                                                 # резервата по новини — само ако изрично се включи
try:
    sw.save_state({"version": 1, "pending": {}, "closed": {}}); seed_cache()
    with q():
        r = sw.refresh_deals(D, get=getter(cut(SUB, "2026-11-06")), cik_map=CIK, news_fn=lambda t, n: FX["news"], name_lookup=lambda t: "Roku, Inc.")
    assert [x["ticker"] for x in r["closed"]] == ["ROKU"] and sw.closed_tickers()["ROKU"]["how"].startswith("новина:")
finally:
    config.DEAL_CLOSE_BY_NEWS = False
hit = {"buyer": "Fox Corporation", "announced": "2026-06-14"}
N = "Roku, Inc."
TWO = [{"title": "Fox completes $22 billion Roku deal to expand digital reach - Reuters", "published": "2026-11-06T16:09Z"},
       {"title": "Fox Completes $22 Billion Roku Acquisition - TheWrap", "published": "2026-11-06T14:30Z"}]                                        # РЕАЛНИ, два източника (10.11.2026: едно не стига)
assert sw.news_closed("ROKU", hit, TWO, D, N) and sw.news_closed("ROKU", hit, TWO[:1], D, N) is None
assert sw.news_closed("ROKU", hit, TWO, D) is None    # без името — „Roku“ не е тикърът ROKU
for t in ("Fox expected to complete Roku acquisition next week", "Fox closes in on Roku deal", "Regulators approve Fox's Roku takeover", "Roku Stock Rises: What's Going On?"):   # СИНТЕТИЧНИ / РЕАЛНИ, без приключване
    assert sw.news_closed("ROKU", hit, [{"title": t, "published": "2026-11-06T10:00Z"}], D, N) is None, t
assert sw.news_closed("ROKU", hit, [{"title": "Fox completes acquisition of Roku", "published": "2026-10-01T10:00Z"}], D, N) is None      # старо заглавие
assert sw.news_closed("CART", {"buyer": "DoorDash, Inc.", "announced": "2026-10-28"}, [{"title": "DoorDash completes deal to add a cart button", "published": "2026-11-06T10:00Z"}], D, "Maplebear Inc.") is None   # СИНТЕТИЧНО: „cart“ не е CART
print("  ✓ ROKU — от EDGAR; без следа там — от заглавията („FOX CORPORATION COMPLETES ACQUISITION OF ROKU“); „expected to complete“, „closes in on“, „approve“ — не")

print("── 4. универсът: ROKU излиза (РЕАЛНИТЕ таблици; ROKU е в S&P 400) ──")
sw.save_state({"version": 1, "pending": {}, "closed": {"ROKU": {"ticker": "ROKU", "date": "2026-11-06", "how": "8-K", "buyer": "Fox Corporation", "seen": "2026-11-09"}}})
HTML = {u["url"]: gzip.decompress((FXD / f).read_bytes()).decode("utf-8") for u, f in zip(config.UNIVERSE_SOURCES, ("wiki_sp500_2026-10-30.html.gz", "wiki_ndx100_list_2026-10-30.html.gz", "wiki_sp400_2026-10-30.html.gz"))}
screener.requests.get = lambda url, **k: types.SimpleNamespace(text=HTML[url])
with q():
    u = screener.build_universe()
assert "ROKU" not in u and set(screener.LAST_UNIVERSE_EXCLUDED) == {"ROKU"} and "ROKU" in screener.LAST_UNIVERSE_SECTOR      # в таблицата е, в универса — не
sw.save_state({"version": 1, "pending": {}, "closed": {"OLD": {"ticker": "OLD", "date": "2025-01-02"}}})
with q():
    sw._update_state(sw.load_state(), {}, {}, D)
assert sw.closed_tickers() == {}                                                                 # след 180 дни тикърът може да е нов листинг
print("  ✓ ROKU е в таблицата на S&P 400 (Wikipedia не е обновена), но не и в универса — нито в скрийнъра, лидерите, QM, GLB, EP")

print("── 5. книгите: ROKU — „приключила сделка“, извън статистиката (РЕАЛНИТЕ записи) ──")
backtest._save_tracker(copy.deepcopy(FX["records"]))
rows = {"ROKU": {"ticker": "ROKU", "date": "2026-11-06", "how": "8-K т. 2.01,3.01", "buyer": "Fox Corporation"}}
with q():
    done = backtest.close_deal_records(rows, D)
    assert backtest.close_deal_records(rows, D) == []                                            # веднъж
trk = backtest._load_tracker()
bs, act = trk["ROKU_2026-10-20_buystop"], trk["ROKU_2026-11-09"]
assert sorted(done) == ["ROKU_2026-10-20_buystop", "ROKU_2026-11-09"]
assert (bs["status"], bs["realized_r"], bs["exit_price"], bs["exit_date"], bs["resolution_date"]) == ("deal_closed", None, 160.52, "2026-11-06", "2026-11-06")
assert bs["deal_closed"]["had_position"] and bs["deal_closed"]["r"] == FX["records"]["ROKU_2026-10-20_buystop"]["current_r"] and bs["deal_closed"]["previous_status"] == "open"
assert act["status"] == "deal_closed" and act["deal_closed"]["had_position"] is False and act["exit_price"] is None
with q():
    S, A = backtest.get_buystop_summary(), backtest.get_backtest_summary()
assert S["closed"] == 0 and S["open"] == 0 and S["pending"] == 0 and [x["ticker"] for x in S["deal_closed"]] == ["ROKU"] and A["deal_closed"][0]["had_position"] is False
assert not any(p["ticker"] == "ROKU" for p in A.get("open_positions") or []) and not A.get("pending_positions")
assert "ROKU" not in backtest.live_deal_tickers()
b = copy.deepcopy(B19); b.setdefault("backtest", {}).update(A); b["backtest"]["buystop"] = S; b["deals_closed"] = [rows["ROKU"]]
with q():
    page = render.render_dashboard(b, publish=False)
assert "Приключила сделка — извън статистиката: <b>ROKU</b> (Fox Corporation, 06.11; вход 22.10 по $159.89, последна цена $160.52, +0.06R)" in page
assert "Приключила сделка — извън статистиката: <b>ROKU</b> (Fox Corporation, 06.11; без вход)" in page
assert "Извън универса</b> (приключила сделка / делистване): ROKU — сделката с Fox Corporation е приключила на 06.11 (8-K т. 2.01,3.01)" in page
print("  ✓ buy-stop от 22.10: изход по $160.52 (06.11), извън статистиката; Action от 09.11: без вход; редът под книгите и „Извън универса“")

print("── 6. последен бар без търговия → не е кандидат (СИНТЕТИЧНИ бари) ──")
idx = pd.bdate_range("2025-06-02", periods=300)
px = pd.Series(np.linspace(50, 120, 300), index=idx)
frame = lambda vol: pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99, "Close": px, "Adj Close": px, "Volume": vol}, index=idx)
v = np.full(300, 1e6); v0 = v.copy(); v0[-1] = 0
data = pd.concat({"AAA": frame(v), "ZZZ": frame(v0)}, axis=1)
screener.yf.download = lambda tickers, **k: data["AAA"][["Close"]] if tickers == "SPY" else data
screener.time.sleep = lambda s: None
with q():
    screener.technical_screen(["AAA", "ZZZ"])
assert screener.LAST_NO_TRADE == ["ZZZ"] and screener.LAST_STATUS["no_trade"] == ["ZZZ"]
print("  ✓ ZZZ (обем 0 на последния бар) — в LAST_NO_TRADE, не е кандидат")

print("── 7. редът в main ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.index('steps.step("deals_closed"') < src.index('candidates = steps.step("screener"')
assert src.index("backtest.close_deal_records(_closed_bt") < src.index("backtest.resolve_positions_only()") < src.index("backtest.close_deal_records(spinoff_watch.closed_tickers()")     # 10.11.2026: и преди резолюцията
assert src.index('steps.step("merger_pre"') < src.index("candidates = [c for c in candidates if c.get(\"ticker\") not in _closed_now]") < src.index("setup_rules.annotate(candidates")
print("  ✓ сделките — преди скрийнинга; книгите — преди резолюцията (и след нея за засечените при картите); кандидатите — преди класификацията")
print("\n✅ test_deal_closed: всичко мина")
