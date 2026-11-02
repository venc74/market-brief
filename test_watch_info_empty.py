"""
02.11.2026 · поправки след брифа, т. 1 — тиха повреда: в брифа от 02.11 short interest беше празен и името None за 14 от 14 наблюдавани (30.10: 14 от 14 попълнени), а стъпката
"watch" беше "ok" без банер. Причината (логът на run 41400345849): от 06:42:37 до 06:43:09 UTC, точно в стъпката, Yahoo върна HTTP 401 на всяко .info — "Invalid Crumb"
(quoteSummary) и "User is unable to access this feature" (v7/finance/quote); yfinance 1.7.0 (hide_exceptions=True) опита и с другата cookie стратегия, после само записа грешката
в stderr и върна .info без име — без изключение. watch_monitor.facts прие празното като отговор: без ред в нашия лог, без банер. Картите на кандидатите имаха пазарна стойност
от .info на скрийнъра (06:31–06:38), преди отказа.
Поправката оставя следа: ред "[watch] T .info празно — причина" за всеки тикър (причината — от грешката на yfinance, таймаут или изключение), обобщение в лога,
brief["watch_info"], "частично" за стъпката и банер в data_warnings, когато .info липсва за над половината наблюдавани.

РЕАЛНО: tests/fixtures/yahoo_info_401_2026-11-02.json — телата на двата отговора 401 и редовете от лога на run-а от 02.11 (бележката — вътре);
tests/fixtures/watch_facts_2026-10-29.json — затварянията, .info и отчетите на 14-те наблюдавани от 29.10 (здравият ден); tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): транспортът — сесията на yfinance връща РЕАЛНИТЕ тела с код 401, crumb-ът е подменен (без мрежа), а timeseries адресът (trailingPegRatio) връща празен
резултат; таймаутът и броят празни в т. 3.
Пускане: python test_watch_info_empty.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, logging, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_watch_info_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import yfinance as yf
from yfinance.data import YfData
from yfinance._http import HTTPError
from src import watch_monitor as wm, data_warnings, render

FXD = ROOT / "tests" / "fixtures"
F401 = json.loads((FXD / "yahoo_info_401_2026-11-02.json").read_text(encoding="utf-8"))
FX = json.loads((FXD / "watch_facts_2026-10-29.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
T = ["TDOC", "BHC", "SAP", "BLSH", "CRCL", "AI", "CRBG", "BFLY", "ELF", "DOCU", "SN", "CRM", "BMNR", "ACN"]
q = lambda: contextlib.redirect_stdout(io.StringIO())
cl = {t: pd.Series(list(v.values()), index=pd.to_datetime(list(v.keys()))) for t, v in FX["closes"].items()}
download = lambda ts: pd.concat({t: pd.DataFrame({"Close": cl[t]}) for t in ts}, axis=1)                    # РЕАЛНИТЕ затваряния от 29.10
earnings = lambda t: {"next_earnings": FX["earnings"][t].get("next"), "days_to_earnings": FX["earnings"][t].get("days"), "earnings_status": FX["earnings"][t].get("status")}


class _Resp:                                                                    # СИНТЕТИЧНО: отговорът на Yahoo с РЕАЛНОТО тяло от лога
    def __init__(self, url, code, body):
        self.url, self.status_code, self.text = url, code, body

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(f"HTTP Error {self.status_code}: ", response=self)


calls = []


def yahoo_401(url=None, params=None, timeout=30, **k):
    calls.append(url)
    if "fundamentals-timeseries" in url:                                        # СИНТЕТИЧНО: trailingPegRatio — празен резултат (на 02.11 този адрес не даде грешка в лога)
        return _Resp(url, 200, '{"timeseries":{"result":[],"error":null}}')
    return _Resp(url, 401, F401["bodies"]["v7_quote" if "/v7/finance/quote" in url else "quoteSummary"])


yd = YfData()
yd._session.get = yahoo_401
yd._get_cookie_and_crumb = lambda *a, **k: ("СИНТЕТИЧЕН-crumb", yd._cookie_strategy)                        # без мрежа (fc.yahoo.com / getcrumb)


print("── 0. РЕАЛНИЯТ провал: Yahoo връща 401 (телата от лога) → yfinance 1.7.0 дава .info без име, без изключение, само ред в своя лог ──")
seen = []
h = logging.Handler(); h.emit = lambda r: seen.append(r.getMessage())
logging.getLogger("yfinance").addHandler(h)
info = yf.Ticker("TDOC").info
logging.getLogger("yfinance").removeHandler(h)
assert not (info.get("longName") or info.get("shortName")) and wm.short_facts(info) == {}, info
assert seen == F401["log_lines_first"][2:4], seen                                                          # „C U“ — точно двата реда на тикър от лога (06:42:45)
assert sum("/v10/finance/quoteSummary/TDOC" in u for u in calls) == 2 and sum("/v7/finance/quote" in u for u in calls) == 2      # всяка заявка — и с другата cookie стратегия
assert F401["pattern"] == "CC" + "CUCCU" * 14 and F401["counts"] == {"http_401": 72, "invalid_crumb": 44, "unable_to_access": 28, "watch_tickers": 14}
print(f"  ✓ .info = {info} — без изключение; yfinance логва „HTTP Error 401: …Invalid Crumb…“ и „…unable to access this feature…“ (точно двата реда на тикър от лога)")

print()
print("── 1. facts() по истинския път (yf.Ticker(t).info през fetch_with_timeout) — 14 от 14 празни, както на 02.11; сега с ред за всеки ──")
with q() as log:
    fx = wm.facts(T, download=download, earnings_fn=earnings)
out = log.getvalue()
assert all(fx[t]["name"] is None and fx[t]["short"] == {} for t in T)                                     # брифът от 02.11: name None, short {} за 14 от 14
assert all(fx[t]["price"].get("close") and fx[t]["earnings"]["next"] == FX["earnings"][t].get("next") for t in T)   # цените и отчетите — от други заявки, налице
why = "HTTP 401 · Invalid Crumb / User is unable to access this feature"
assert wm.LAST_INFO == {"checked": 14, "empty": {t: why for t in T}}, wm.LAST_INFO
for t in T:
    assert f"[watch] {t} .info празно — {why} (името и short interest липсват днес)" in out, t
assert f"[watch] ⚠ .info: 14 от 14 празни — {why} ×14" in out
assert "[watch] TDOC .info:" not in out                                                                   # няма изключение — само празният отговор
print(f"  ✓ 14 реда „[watch] T .info празно — {why} …“ + „⚠ .info: 14 от 14 празни“; цените и отчетите остават")

print()
print("── 2. банерът и стъпката ──")
w = data_warnings.collect({}, {}, watch_info=dict(wm.LAST_INFO))
assert [x["source"] for x in w] == ["watch"] and w[0]["level"] == "warn"
assert w[0]["message"] == (f"Наблюдавани тикъри: Yahoo .info не върна данни за 14 от 14 тикъра ({why}) — името и short interest липсват днес; "
                           "цените, отчетите, новините и Form 4 са от други източници."), w[0]["message"]
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "watch_info=dict(watch_monitor.LAST_INFO)" in main_src and '"watch_info": dict(watch_monitor.LAST_INFO)' in main_src
assert 'partial=lambda v: (f"Yahoo .info празно за {len(_wi[\'empty\'])} от {_wi[\'checked\']}", {})' in main_src
b = copy.deepcopy(B19); b["data_warnings"] = w
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "Наблюдавани тикъри: Yahoo .info не върна данни за 14 от 14 тикъра (HTTP 401 · Invalid Crumb / User is unable to access this feature)" in page
print("  ✓ банер „Наблюдавани тикъри: Yahoo .info не върна данни за 14 от 14 …“ на страницата; main: brief[\"watch_info\"], „частично“ за стъпката, банерът от data_warnings")

print()
print("── 3. здравият ден (РЕАЛНОТО .info от 29.10) и прагът „над половината“ (СИНТЕТИЧНО: кои липсват) ──")
real = lambda t: FX["info"][t]
with q() as log:
    fx = wm.facts(T, download=download, info_fn=real, earnings_fn=earnings)
assert wm.LAST_INFO["empty"] == {} and "празно" not in log.getvalue() and fx["TDOC"]["name"] == "Teladoc Health, Inc." and fx["TDOC"]["short"]["pct_float"] == 17.7
assert data_warnings.collect({}, {}, watch_info=dict(wm.LAST_INFO)) == []
with q() as log:
    wm.facts(T, download=download, info_fn=lambda t: None if t == "SAP" else real(t), earnings_fn=earnings)          # СИНТЕТИЧНО: таймаут за SAP
assert wm.LAST_INFO["empty"] == {"SAP": "таймаут (10 s)"} and "[watch] SAP .info празно — таймаут (10 s)" in log.getvalue()
assert data_warnings.collect({}, {}, watch_info=dict(wm.LAST_INFO)) == []                                 # 1 от 14 — само редът в лога
for n, banner in ((7, False), (8, True)):
    miss = set(T[:n])
    with q():
        wm.facts(T, download=download, info_fn=lambda t: {} if t in miss else real(t), earnings_fn=earnings)   # СИНТЕТИЧНО: n празни
    assert len(wm.LAST_INFO["empty"]) == n and set(wm.LAST_INFO["empty"].values()) == {"Yahoo върна отговор без име и short interest"}
    assert bool(data_warnings.collect({}, {}, watch_info=dict(wm.LAST_INFO))) is banner, n
def boom(t):
    raise ConnectionError("СИНТЕТИЧНО: мрежата падна")
with q() as log:
    wm.facts(["TDOC"], download=download, info_fn=boom, earnings_fn=earnings)
assert wm.LAST_INFO["empty"] == {"TDOC": "ConnectionError: СИНТЕТИЧНО: мрежата падна"} and "[watch] TDOC .info: ConnectionError" in log.getvalue()
print("  ✓ 29.10: 0 празни, без банер; таймаут за 1 → ред „таймаут (10 s)“, без банер; 7 от 14 → без банер, 8 от 14 → банер; изключение → причината е изключението")

print()
print("── 4. info_reason — РЕАЛНИТЕ редове от лога ──")
assert wm.info_reason(F401["log_lines_first"][:1]) == "HTTP 401 · Invalid Crumb"
assert wm.info_reason([F401["log_line_404"]]) == "HTTP 404 · Quote not found for symbol: NESN"
assert wm.info_reason(["$SAFM: No data found, symbol may be delisted"]) is None and wm.info_reason([]) is None
print("  ✓ „HTTP 401 · Invalid Crumb“, „HTTP 404 · Quote not found for symbol: NESN“; ред без HTTP код → без причина")
print("\n✅ test_watch_info_empty: всичко мина")
