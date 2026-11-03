"""
03.11.2026 · поправки след брифа, т. 1: наблюдаваните — без Yahoo .info и без short interest. На 02.11 и 03.11 .info върна HTTP 401 („Invalid Crumb“) за 14 от 14 в стъпката
„watch“ (на 02.11 без ред и банер, на 03.11 — с тях). Сега заявката я няма: името е записано веднъж в data/watch_list.json ("names"), а на мястото на колоната short interest —
ADR% за 20 дни и „под 52-седм. връх −X%“ от дневните цени, които и досега се теглеха (watch_monitor.range_facts; без нови заявки). Следата за .info (LAST_INFO, банерът,
„частично“ за стъпката, brief["watch_info"]) отпада заедно със заявката.

РЕАЛНО: tests/fixtures/watch_ohlc_2026-11-03.json.gz — дневни OHLC за 1 година на 14-те наблюдавани и SPY, свалени на 03.11.2026 (последният бар — 02.11);
tests/fixtures/watch_brief_2026-10-30.json — имената (Yahoo longName на 30.10, записани в data/watch_list.json); tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): подмененото теглене (връща РЕАЛНИТЕ OHLC), отчетите, временният watch_list.json, „гърмящият“ yf.Ticker (доказва, че .info не се вика).
Пускане: python test_watch_no_info.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_watch_noinfo_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import watch_monitor as wm, data_warnings, render

FXD = ROOT / "tests" / "fixtures"
OHLC = json.loads(gzip.decompress((FXD / "watch_ohlc_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
W30 = json.loads((FXD / "watch_brief_2026-10-30.json").read_text(encoding="utf-8"))
W30 = W30.get("watch") if isinstance(W30, dict) and "watch" in W30 else W30
NAMES = {w["ticker"]: w["name"] for w in W30}
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
T = list(NAMES)
q = lambda: contextlib.redirect_stdout(io.StringIO())
idx = pd.to_datetime(OHLC["dates"])
frame = pd.concat({t: pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"]}, index=idx) for t, b in OHLC["bars"].items()}, axis=1)

print("── 1. range_facts — ADR% (20 дни) и 52-седмичният връх от РЕАЛНИТЕ цени ──")
want = {"TDOC": (5.5, 9.89, -12.7), "SAP": (2.1, 265.88, -12.1), "BLSH": (7.0, 51.94, -56.6), "SN": (3.4, 216.11, -1.3), "ACN": (4.1, 291.09, -10.4)}
for t, (a, hi, off) in want.items():
    got = wm.range_facts(frame[t]["High"], frame[t]["Low"], frame[t]["Close"])
    assert (got["adr_pct"], got["high_52w"], got["off_high_pct"]) == (a, hi, off), (t, got)
assert wm.range_facts(frame["TDOC"]["High"].iloc[-10:], frame["TDOC"]["Low"].iloc[-10:], frame["TDOC"]["Close"].iloc[-10:]).get("adr_pct") is None    # под 20 бара → без ADR
print("  ✓ TDOC ADR 5.5% · под 52-седм. връх −12.7% ($9.89) · SAP 2.1% / −12.1% · BLSH 7.0% / −56.6% · SN 3.4% / −1.3% · ACN 4.1% / −10.4%")

print()
print("── 2. facts() — без Yahoo .info; името от watch_list.json (СИНТЕТИЧНО: тегленето връща РЕАЛНИТЕ OHLC; yf.Ticker гърми) ──")
(config.DATA_DIR / "watch_list.json").write_text(json.dumps({"tickers": T, "names": NAMES}, ensure_ascii=False), encoding="utf-8")
wm._LIST_PATH = config.DATA_DIR / "watch_list.json"
wm.yf.Ticker = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Yahoo .info / Ticker не бива да се вика"))
with q() as log:
    fx = wm.facts(T, download=lambda ts: frame, earnings_fn=lambda t: {"next_earnings": None})
assert set(fx["TDOC"]) == {"name", "price", "earnings"} and fx["TDOC"]["name"] == "Teladoc Health, Inc." and fx["ACN"]["name"] == "Accenture plc"
assert all(fx[t]["name"] == NAMES[t] for t in T) and all("adr_pct" in fx[t]["price"] and "off_high_pct" in fx[t]["price"] for t in T)
assert fx["TDOC"]["price"]["close"] == 8.63 and fx["TDOC"]["price"]["date"] == "2026-11-02"
assert ".info" not in log.getvalue() and not hasattr(wm, "LAST_INFO") and not hasattr(wm, "short_facts")
assert wm.load_watch_names() == NAMES
wm._LIST_PATH = config.DATA_DIR / "липсва.json"
assert wm.load_watch_names() == {}                                                                                   # липсващ файл → без имена, редът — само тикърът
print("  ✓ 14 от 14 с име от watch_list.json, ADR и 52-седм. връх; нито едно извикване към Yahoo .info; без LAST_INFO / short_facts")

print()
print("── 3. страницата и следата за .info ──")
rows = [{"ticker": t, "name": fx[t]["name"], "facts": {"price": fx[t]["price"], "earnings": {}}, "news": [], "insider": [], "insider_cluster": False, "quiet": True} for t in T]
b = copy.deepcopy(B19); b["watch"] = rows
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "Тикър Цена · ден 50 / 200DMA RS спрямо S&P 4 / 12 седм. Отчет ADR · 52-седм. връх В брифа · събития" in page and "Short interest" not in page
assert "TDOC Teladoc Health, Inc. $8.63" in page and "ADR 5.5% под 52-седм. връх -12.7%" in page and "ADR 3.4% под 52-седм. връх -1.3%" in page
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8") + (ROOT / "src" / "data_warnings.py").read_text(encoding="utf-8")
assert "watch_info" not in src and "LAST_INFO" not in src and "_watch_info_warning" not in src
assert data_warnings.collect({}, {}) == []
print("  ✓ колоната „ADR · 52-седм. връх“ (TDOC: ADR 5.5% · под 52-седм. връх −12.7%); без „Short interest“; без brief[\"watch_info\"], банера и „частично“ за .info")
print("\n✅ test_watch_no_info: всичко мина")
