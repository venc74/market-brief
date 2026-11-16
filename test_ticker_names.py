"""
16.11.2026 (пакет 16.11, т. 14): навсякъде, където има кандидат / плочка с тикър (Kullamägi, CANSLIM радарът, GLB, EP, buy-stop и другите книги, карето в 15:05) — след тикъра
краткото име на компанията: „R · Ryder“, „SAIC · Science Applications Intl“. Името — от картата (Yahoo), иначе от таблиците на Wikipedia, от които се строи универсът
(колоната „Security“ / „Company“; screener.LAST_UNIVERSE_NAME → brief["names"]); без правните окончания и без „(Class A)“.

РЕАЛНО: tests/fixtures/wiki_sp500_2026-10-30.html.gz, wiki_sp400_2026-10-30.html.gz, wiki_ndx100_list_2026-10-30.html.gz — таблиците на универса (свалени 30.10.2026);
brief_2026-10-19.json — рамката. СИНТЕТИЧНО (означено): кои тикъри са в радара / картите.
Пускане: python test_ticker_names.py
"""
import sys, gzip, copy, json, pathlib, tempfile, io, contextlib, types
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_names_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import screener, render

FXD = ROOT / "tests" / "fixtures"
PAGES = {"sp500": "wiki_sp500_2026-10-30.html.gz", "sp400": "wiki_sp400_2026-10-30.html.gz", "ndx": "wiki_ndx100_list_2026-10-30.html.gz"}
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. РЕАЛНО: имената от таблиците на Wikipedia ──")
screener.LAST_UNIVERSE_NAME.clear()
for key, col in (("sp500", "Symbol"), ("sp400", "Symbol"), ("ndx", "Ticker")):
    html = gzip.decompress((FXD / PAGES[key]).read_bytes()).decode("utf-8", "replace")
    screener.requests.get = lambda url, timeout=None, headers=None, h=html: types.SimpleNamespace(text=h)         # СИНТЕТИЧНО: мрежата — реалната страница
    syms, why = screener._wiki_table("https://example.invalid", col)
    assert why is None and syms
N = screener.LAST_UNIVERSE_NAME
assert (N["R"], N["SAIC"], N["NVDA"], N["GOOGL"], N["KDP"], N["BKH"]) == ("Ryder", "Science Applications Intl Corp", "Nvidia", "Alphabet Inc. (Class A)", "Keurig Dr Pepper", "Black Hills Corporation"), {k: N.get(k) for k in ("R", "SAIC")}
print(f"  ✓ {len(N)} имена; R → „Ryder“, SAIC → „Science Applications Intl Corp“")

print("── 2. краткото име ──")
S = lambda t, c=None: render.short_name(t, c, N)
assert (S("R"), S("SAIC"), S("GOOGL"), S("BKH"), S("NVDA")) == ("Ryder", "Science Applications Intl", "Alphabet", "Black Hills", "Nvidia")
assert S("R", "Ryder System, Inc.") == "Ryder System"                                       # името от картата (Yahoo) — с предимство
assert S("XXXX") == "" and S("KDP", "KDP") == "Keurig Dr Pepper" and S(None) == ""
assert render.short_name("LLY", None, {"LLY": "Lilly (Eli)"}) == "Eli Lilly"                 # РЕАЛНО (S&P 500 на Wikipedia)
# РЕАЛНО — имената от картите / книгите в брифовете 14.10–16.11 (Yahoo / SEC), които реплеят на 16.11 показа като „Merck &“, „Eli Lilly and“, „Berkshire Hathaway Inc.…“:
assert (render.short_name("MRK", "Merck & Company, Inc."), render.short_name("LLY", "Eli Lilly and Company"), render.short_name("LLY", "Eli Lilly & Co")) == ("Merck", "Eli Lilly", "Eli Lilly")
assert render.short_name("BRK-B", "Berkshire Hathaway Inc. New") == "Berkshire Hathaway"
assert render.short_name("BRK-B", "BERKSHIRE HATHAWAY INC DEL", {"BRK-B": "Berkshire Hathaway"}) == "Berkshire Hathaway"
assert render.short_name("BRK-B", "BERKSHIRE HATHAWAY INC DEL") == "BERKSHIRE HATHAWAY"          # без името от Wikipedia — каквото има
assert (S("JNJ"), S("PG"), S("T"), S("SPGI"), S("EL"), S("HIG")) == ("Johnson & Johnson", "Procter & Gamble", "AT&T", "S&P Global", "Estée Lauder Companies", "Hartford")   # РЕАЛНО (Wikipedia; водещото „The“ пада, както в картите)
print("  ✓ „Ryder“, „Science Applications Intl“, „Alphabet“ (без Class A), „Black Hills“; от картата — „Ryder System“")

print("── 3. страницата: радарът, Kullamägi, GLB ──")
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19)
b["names"] = dict(N)
_, radar = render.split_canslim(b["watchlist"])
named = [r["ticker"] for r in radar if S(r["ticker"])]
assert named, [r["ticker"] for r in radar]
with q():
    page = render.render_dashboard(b, publish=False)
for t in named:
    assert f'{t}<span class="tk-name" style="font-family:\'IBM Plex Sans\',sans-serif;font-weight:400;font-size:.85em;color:var(--muted)"> · {S(t)}</span>' in page, t
print(f"  ✓ РЕАЛНИЯТ радар от 19.10: " + ", ".join(f"{t} · {S(t)}" for t in named))
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
for spot in ('{{ r.ticker }}{{ tn(r.ticker, r.company) }}', '<span class="qm-sym">{{ c.ticker }}{{ tn(c.ticker, c.company) }}', '<span class="glb-sym">{{ g.ticker }}</span>{{ tn(g.ticker, g.company) }}',
             '{{ p.ticker }}{{ tn(p.ticker, p.company) }}{{ markers_html(p.markers) }}{{ spinoff_note_html(p) }}</td><td>{{ p.entry_date }}', '{{ x.ticker }}</b>{{ tn(x.ticker) }}'):
    assert spot in tpl, spot
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert '"names": _display_names(),' in src
print("  ✓ радарът, картите по Kullamägi, GLB, книгите, нивата в карето — „ТИКЪР · Име“")
print("\n✅ test_ticker_names: всичко мина")
