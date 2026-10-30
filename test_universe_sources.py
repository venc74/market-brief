"""
30.10.2026 · тиха повреда: универсът беше изгубил Nasdaq-100. На 09.07.2026 (ревизия 1363378934, 20:57 UTC, „move to [[List of NASDAQ-100 companies]]“) таблицата на
компонентите беше преместена от статията „Nasdaq-100“ в „List of NASDAQ-100 companies“. screener._wiki_tickers не намираше колоната „Ticker“ и връщаше [] без ред в лога
(изключение нямаше) — от брифа на 10.07 до 30.10 скрийнърът, QM, GLB, breadth и записът на опциите бяха само върху S&P 500 + S&P 400: 903 вместо 918 тикъра. Броят на
универса е в брифа от 08.10 (902, после 903); ревизията от 09.07 18:29 UTC има таблицата (103 реда), тази от 20:57 — не.
  • (б) адресът — „List of NASDAQ-100 companies“ (config.UNIVERSE_SOURCES: име, адрес, колона, минимум);
  • (в) всеки източник — в screener.LAST_UNIVERSE_SOURCES и brief["universe_sources"]; не се зареди / няма таблицата / под минимума → ред „⚠“ в лога и банер;
  • (г) Nasdaq-100 — 101 тикъра; 15 не са в S&P 500 / 400: ALAB, ALNY, ARM, ASML, CCEP, CRWV, FER, MELI, MSTR, NBIS, PDD, RKLB, SHOP, SPCX, TRI.

РЕАЛНО: tests/fixtures/wiki_*_2026-10-30.html.gz (бележката — wiki_universe_2026-10-30.json): страницата „List of NASDAQ-100 companies“ и статията „Nasdaq-100“ — цели;
от S&P 500 и S&P 400 — таблицата с компонентите; tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): подмененият requests.get (връща fixture-а по адрес), статията на мястото на списъка (както кодът я четеше до 30.10), отрязаният S&P 400, мрежовата грешка.
Пускане: python test_universe_sources.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_universe_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import screener, data_warnings, render

FXD = ROOT / "tests" / "fixtures"
NOTE = json.loads((FXD / "wiki_universe_2026-10-30.json").read_text(encoding="utf-8"))
PAGE = {v["url"]: gzip.decompress((FXD / name).read_bytes()).decode("utf-8") for name, v in NOTE["files"].items()}
URL = {s["name"]: s["url"] for s in config.UNIVERSE_SOURCES}
ARTICLE = "https://en.wikipedia.org/wiki/Nasdaq-100"
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())


class _Resp:
    def __init__(self, text): self.text = text


def serve(pages):                                                     # СИНТЕТИЧНО: requests.get → РЕАЛНИЯТ HTML по адрес
    def get(url, **k):
        if url not in pages:
            raise ConnectionError(f"СИНТЕТИЧНО: няма страница за {url}")
        return _Resp(pages[url])
    return get


def fresh():
    screener.LAST_UNIVERSE_SOURCES.clear(); screener.LAST_UNIVERSE_SECTOR.clear()


print("── 0. РЕАЛНИЯТ дефект: статията „Nasdaq-100“ вече е без таблицата — старият код връщаше [] без ред в лога ──")
screener.requests.get = serve(PAGE)
syms, why = screener._wiki_table(ARTICLE, "Ticker")
assert syms == [] and why == "на страницата няма таблица с колона „Ticker“"
print("  ✓ статията (30.10): няма таблица с „Ticker“ → [] и причината (до 30.10 без причина и без ред в лога)")

print()
print("── 1. (б) източниците от config — РЕАЛНИТЕ таблици ──")
assert URL["Nasdaq-100"] == "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
fresh()
with q() as log:
    uni = screener.build_universe()
src = screener.LAST_UNIVERSE_SOURCES
assert {k: (v["n"], v["ok"]) for k, v in src.items()} == {"S&P 500": (503, True), "Nasdaq-100": (101, True), "S&P 400": (400, True)}
assert len(uni) == 918 and "BRK-B" in uni and "[screener] универс: 918 тикъра (S&P 500 503, Nasdaq-100 101, S&P 400 400)" in log.getvalue() and "⚠" not in log.getvalue()
sp500, _ = screener._wiki_table(URL["S&P 500"], "Symbol"); mid, _ = screener._wiki_table(URL["S&P 400"], "Symbol"); ndx, _ = screener._wiki_table(URL["Nasdaq-100"], "Ticker")
only = sorted(set(ndx) - set(sp500) - set(mid))
assert only == ["ALAB", "ALNY", "ARM", "ASML", "CCEP", "CRWV", "FER", "MELI", "MSTR", "NBIS", "PDD", "RKLB", "SHOP", "SPCX", "TRI"]
assert len(set(sp500) | set(mid)) == 903 and len(screener.LAST_UNIVERSE_SECTOR) == 903 and screener.LAST_UNIVERSE_SECTOR["NVDA"] == "Information Technology"
assert not any(t in screener.LAST_UNIVERSE_SECTOR for t in only)                                       # Nasdaq-100 е с ICB, не с GICS — не са сред лидерите на картата
print(f"  ✓ S&P 500 503 · Nasdaq-100 101 · S&P 400 400 → 918 (беше 903); само в Nasdaq-100 — 15: {', '.join(only)}")
print("  ✓ GICS секторът — от S&P таблиците (903); 15-те само от Nasdaq-100 нямат GICS → не са сред лидерите в секторната карта")

print()
print("── 2. (в) източникът липсва — както до 30.10 (СИНТЕТИЧНО: на адреса на списъка — статията) → ред в лога и банер ──")
fresh()
screener.requests.get = serve({**PAGE, URL["Nasdaq-100"]: PAGE[ARTICLE]})
with q() as log:
    uni = screener.build_universe()
s = screener.LAST_UNIVERSE_SOURCES["Nasdaq-100"]
assert len(uni) == 903 and (s["n"], s["ok"], s["reason"]) == (0, False, "на страницата няма таблица с колона „Ticker“")
assert "[screener] ⚠ универс: Nasdaq-100 — на страницата няма таблица с колона „Ticker“" in log.getvalue()
w = data_warnings.collect({}, {}, universe_sources=dict(screener.LAST_UNIVERSE_SOURCES))
assert [x["source"] for x in w] == ["universe"] and w[0]["level"] == "warn"
assert w[0]["message"].startswith("Универс: Nasdaq-100 — на страницата няма таблица с колона „Ticker“ — скрийнърът, QM, GLB и breadth днес са без тези тикъри")
print("  ✓ 903 тикъра; „⚠ универс: Nasdaq-100 — на страницата няма таблица с колона „Ticker““ в лога; банер „Универс: Nasdaq-100 — …“")

print()
print("── 3. под минимума и мрежова грешка (СИНТЕТИЧНО); най-лошото от run-а остава ──")
fresh()
cut = PAGE[URL["S&P 400"]]
rows = re.findall(r"<tr\b.*?</tr>", cut, flags=re.S)
short = cut
for r in rows[51:]:                                                                                 # остават заглавието и първите 50 реда
    short = short.replace(r, "", 1)
screener.requests.get = serve({**PAGE, URL["S&P 400"]: short})
with q():
    screener.build_universe()
assert (screener.LAST_UNIVERSE_SOURCES["S&P 400"]["n"], screener.LAST_UNIVERSE_SOURCES["S&P 400"]["reason"]) == (50, "50 тикъра (очаквани поне 380)")
screener.requests.get = serve(PAGE)
with q():
    screener.build_universe()                                                                       # второ извикване в run-а (напр. QM) — пълно
assert screener.LAST_UNIVERSE_SOURCES["S&P 400"]["n"] == 50 and not screener.LAST_UNIVERSE_SOURCES["S&P 400"]["ok"]
fresh()
screener.requests.get = serve({k: v for k, v in PAGE.items() if k != URL["S&P 500"]})
with q():
    uni = screener.build_universe()
assert screener.LAST_UNIVERSE_SOURCES["S&P 500"]["reason"].startswith("страницата не се зареди (ConnectionError") and len(uni) == 501     # 400 + 101, без общи
print("  ✓ S&P 400 с 50 реда → „50 тикъра (очаквани поне 380)“; второто, пълно извикване не го скрива; без S&P 500 → „страницата не се зареди (ConnectionError …)“, 501 тикъра")

print()
print("── 4. страницата: банерът (РЕАЛНИЯТ бриф от 19.10 като рамка) ──")
b = copy.deepcopy(B19); b["data_warnings"] = w
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "Универс: Nasdaq-100 — на страницата няма таблица с колона „Ticker“" in page
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "universe_sources=dict(screener.LAST_UNIVERSE_SOURCES)" in main_src and '"universe_sources": dict(screener.LAST_UNIVERSE_SOURCES)' in main_src
print("  ✓ банерът е на страницата; main подава източниците на data_warnings и ги записва в brief[\"universe_sources\"]")
print("\n✅ test_universe_sources: всичко мина")
