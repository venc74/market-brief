"""
18.11.2026 (спешно, т. 1 — новините от 18.11): брифът не спомена отчета на Nvidia от 17.11. Диагнозата: моделът ИЗБРА „Nvidia’s Kress tells CNBC's Jim Cramer …“ (CNBC),
но кодът го махна — ехото на модела е с права апострофа („Nvidia's“), заглавието във фийда — с типографска („Nvidia’s“), и сверката на първите 6 думи (news_aggregator._echo_index)
казваше „индексът не съвпада със заглавието“. Същото — „China’s Xi …“ на 18.11 и още 5 основни новини от 10.11 насам (+16 „също“ от 30.10). Поправка: кавичките се уеднаквяват
преди сверката (_first_words). Празен / паднал източник — червен ред под новините (render.news_sources_alert); колко стигнаха до подбора и колко паднаха — сив ред (news_pool_note).

РЕАЛНО: tests/fixtures/news_quote_drops_2026-11.json — 7-те отпаднали основни новини от news_diag на брифовете 30.10–18.11 („h“ на модела и заглавието от фийда) и news_window /
news_diag на брифа от 18.11. СИНТЕТИЧНО (означено): пулът около заглавията (резюме, източник), „why“, паднал източник с HTTP 503, „to_model“ / „fetched“ (брифът от 18.11 ги няма).
Пускане: python test_news_quotes.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_quotes_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import news_aggregator as na, render

FX = json.loads((ROOT / "tests" / "fixtures" / "news_quote_drops_2026-11.json").read_text(encoding="utf-8"))
DROPS = FX["drops"]
assert len(DROPS) == 7 and all("'" in d["h"] and "’" in d["pool_title"] for d in DROPS)

print("── 1. РЕАЛНО: седемте отпаднали — ехото вече съвпада ──")
for d in DROPS:
    pool = [{"title": "Unrelated headline about something else", "source": "CNBC", "summary": ""}, {"title": d["pool_title"], "source": "CNBC", "summary": ""}]
    j, note = na._echo_index(d["h"], 1, pool, set())
    assert j == 1 and note == "", (d, j, note)
nv = next(d for d in DROPS if d["date"] == "2026-11-18" and d["h"].startswith("Nvidia"))
pool = [{"title": nv["pool_title"], "source": "CNBC", "summary": ""}]
news, dropped = na.pick_verbatim([{"i": 0, "h": nv["h"], "why": "Сигнал за търсенето на AI чипове."}], pool, 8)      # СИНТЕТИЧНО: why
assert [n["headline"] for n in news] == [nv["pool_title"]] and not dropped
assert na._first_words("Nvidia’s Kress") == na._first_words("Nvidia's Kress") == ["nvidia's", "kress"]
assert na._first_words("“Quoted” headline") == na._first_words('"Quoted" headline')
print(f"  ✓ 7 от 7 (30.10–18.11); 18.11: «{nv['pool_title'][:60]}…» остава")

print("── 2. РЕАЛНО: 18.11 — всички източници с заглавия (няма червен ред) ──")
NW = FX["news_window_2026_11_18"]
assert {k: v["count"] for k, v in NW["sources"].items()} == {"Reuters Business": 50, "CNBC": 29, "Financial Times": 10, "AP Business": 50}
assert render.news_sources_alert(NW) is None and render.news_pool_note(NW, FX["news_diag_2026_11_18"]) is None     # старият бриф — без „to_model“
print("  ✓ Reuters 50, CNBC 29, FT 10, AP 50 — нито един празен")

print("── 3. СИНТЕТИЧНО: паднал източник и редът за подбора ──")
nw = dict(NW, fetched={"Reuters Business": 0, "CNBC": 29, "Financial Times": 10, "AP Business": 50}, dead=[{"source": "Reuters Business", "error": "HTTP 503"}],
          pool_total=89, pool_used=89, to_model={"CNBC": 29, "Financial Times": 10, "AP Business": 50})
a = render.news_sources_alert(nw)
assert a == "⚠ Източници без заглавия днес: Reuters Business — 0 заглавия (HTTP 503) — подборът е без тях; празното НЕ значи, че няма новини.", a
nw2 = dict(NW, fetched={"Reuters Business": 50, "CNBC": 29, "Financial Times": 10, "AP Business": 50}, dead=[], pool_total=139, pool_used=100,
           to_model={"Reuters Business": 31, "CNBC": 29, "Financial Times": 10, "AP Business": 30})
note = render.news_pool_note(nw2, FX["news_diag_2026_11_18"])
assert note == ("Към подбора: 100 от 139 заглавия (Reuters Business 31 от 50, CNBC 29, Financial Times 10, AP Business 30 от 50); подборът избра 8, показани 6 — "
                "2 паднаха при проверката на кода (индексът не съвпада със заглавието)."), note
print(f"  ✓ «{a[:70]}…»\n  ✓ «{note[:90]}…»")

print("── 4. СИНТЕТИЧНО: _fetch_rss записва HTTP грешката, gather_raw — празните ──")
class R:
    status_code, content = 503, b"<html>unavailable</html>"
orig = na.requests.get
na.requests.get = lambda *a, **k: R()
try:
    with contextlib.redirect_stdout(io.StringIO()):
        raw = na.gather_raw(hours=24)
finally:
    na.requests.get = orig
assert all(v == 0 for v in na.LAST_WINDOW["fetched"].values()) and len(na.LAST_WINDOW["dead"]) == len(config.NEWS_RSS_FEEDS)
assert all(d.get("error") == "HTTP 503" for d in na.LAST_WINDOW["dead"])
print("  ✓ HTTP 503 → „dead“ с грешката за всеки фийд")

print("── 5. страницата: червеният ред и при празни новини ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B); b["news"] = []; b["news_window"] = nw
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
assert "⚠ Източници без заглавия днес: Reuters Business — 0 заглавия (HTTP 503)" in txt
print("  ✓ секцията се показва с червения ред")
print("\n✅ test_news_quotes: всичко мина")
