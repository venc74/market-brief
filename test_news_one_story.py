"""
29.10.2026 · разходката, т. 3–4, решение 2: една история — една новина. Заглавията за СЪЩОТО събитие (от различни източници или от един) се сливат в един ред: заглавието на
най-надеждния източник в групата (config.NEWS_SOURCE_PRIORITY: Reuters, AP, FT, CNBC; при крипто CoinDesk, Cointelegraph), „защо“ — за събитието, „също: FT, CNBC“ (линкове).
Разпознава моделът ("also" — индекси + ехо на първите 6 думи); кодът проверява индексите и ехото (_also_group), избира основното заглавие и пази другите в row["also"].
Повод (РЕАЛНО, брифът от 29.10): „Alphabet sinks 10%…“ (CNBC) и „Google shares tumble 10%…“ (FT); „Fed meeting recap…“ (CNBC) и „Fed holds fire…“ (FT) — 4 от 8 реда за 2 събития.
Измерено на ръка в последните 24 брифа (28.09–29.10, 191 новини): 8 сигурни двойки в 7 дни + 4 гранични.

РЕАЛНО: tests/fixtures/news_rss_cnbc_2026-10-29.xml, news_rss_ft_2026-10-29.xml, news_rss_reuters_gnews_2026-10-29.xml (29.10, 16:18 UTC) — в тях DoorDash–Instacart и Alphabet са и в трите;
tests/fixtures/brief_2026-10-19.json — рамката на страницата и имейла.
СИНТЕТИЧНО (означено): отговорът на модела (групите, why, превод), подмененият requests.get.
Пускане: python test_news_one_story.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
from html import escape as esc
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_story_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import news_aggregator as na, render

FX = ROOT / "tests" / "fixtures"
B19 = json.loads((FX / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())


class _Resp:
    def __init__(self, b): self.content = b


def fetch(fixture, source):
    na.requests.get = lambda url, timeout=None, headers=None: _Resp((FX / fixture).read_bytes())          # СИНТЕТИЧНО: мрежата е подменена с РЕАЛНИЯ фийд
    return na._fetch_rss("https://example.invalid/rss", source, hours=24 * 3650, limit=200)


pool = na._interleave([fetch("news_rss_cnbc_2026-10-29.xml", "CNBC"), fetch("news_rss_ft_2026-10-29.xml", "Financial Times"),
                       fetch("news_rss_reuters_gnews_2026-10-29.xml", "Reuters Business")])
idx = lambda title: next(k for k, r in enumerate(pool) if r["title"] == title)
ref = lambda k: {"i": k, "h": " ".join(pool[k]["title"].split()[:6])}
DD = {s: idx(t) for s, t in (("CNBC", "DoorDash to acquire Instacart for $17 billion"), ("FT", "DoorDash to acquire Instacart for $17bn"),
                             ("Reuters", "DoorDash strikes $17 billion deal for US rival Instacart in mega grocery delivery bet - Reuters"))}
AL = {s: idx(t) for s, t in (("CNBC", "Alphabet falls 13%, putting it on course for its biggest ever post-earnings drop"), ("FT", "Alphabet shares tumble in $500bn rout"),
                             ("Reuters", "Alphabet stock sinks as search woes cause revenue miss, cash burn worsens - Reuters"))}
GDP = idx("Third-quarter U.S. GDP increases a better-than-expected 3.4% as September inflation accelerates")

print("── 1. РЕАЛНИЯТ пул от 29.10: DoorDash–Instacart и Alphabet — и в трите източника ──")
assert {pool[k]["source"] for k in DD.values()} == {pool[k]["source"] for k in AL.values()} == {"CNBC", "Financial Times", "Reuters Business"}
print(f"  ✓ пул {len(pool)} заглавия; DoorDash: {sorted(DD.values())}, Alphabet: {sorted(AL.values())}")

print()
print("── 2. сливане: основното — от най-надеждния източник, „също“ — другите по реда; преводът отпада при смяна (СИНТЕТИЧЕН отговор) ──")
ans = [{**ref(DD["CNBC"]), "why": "Консолидация в доставките — натиск върху конкурентите.", "headline_bg": "DoorDash купува Instacart за $17 млрд.",
        "also": [ref(DD["FT"]), ref(DD["Reuters"])]},
       {**ref(AL["FT"]), "why": "AI разходите тежат на търсачката — натиск върху mega-cap tech.", "also": [ref(AL["CNBC"]), AL["Reuters"]]},          # индекс без ехо — приема се
       {**ref(GDP), "why": "По-силен растеж и по-гореща инфлация — по-малко място за понижение на лихвите.", "headline_bg": "Растежът на БВП на САЩ за третото тримесечие се ускорява до 3.4%"},
       {**ref(DD["FT"]), "why": "Дубъл на сделката."}]                                                                                              # вече в групата → отпада
news, dropped = na.pick_verbatim(ans, pool, 8)
assert len(news) == 3
d, a, g = news
assert d["headline"] == pool[DD["Reuters"]]["title"] and d["source"] == "Reuters Business" and d["link"] == pool[DD["Reuters"]]["link"]
assert [x["source"] for x in d["also"]] == ["Financial Times", "CNBC"] and [x["link"] for x in d["also"]] == [pool[DD["FT"]]["link"], pool[DD["CNBC"]]["link"]]
assert "headline_bg" not in d and d["why"] == "Консолидация в доставките — натиск върху конкурентите."
assert a["source"] == "Reuters Business" and [x["source"] for x in a["also"]] == ["Financial Times", "CNBC"]
assert g["headline"] == pool[GDP]["title"] and "also" not in g and g["headline_bg"].startswith("Растежът на БВП")                                 # без дубли — непроменено
reasons = [x["reason"] for x in dropped]
assert reasons.count("основното заглавие — от по-надеждния източник (Reuters Business), преводът отпада") == 2 and "повторен индекс" in reasons
print(f"  ✓ DoorDash: «{d['headline'][:55]}…» · също: {', '.join(x['source'] for x in d['also'])}; Alphabet — също Reuters; БВП — без „също“; дубълът като отделна новина — отпада")

print()
print("── 3. „also“ с грешно ехо или невалиден индекс не влиза в групата (СИНТЕТИЧНО) ──")
bad = [{**ref(DD["Reuters"]), "why": "Сделка в доставките.", "also": [{"i": DD["FT"], "h": "Alphabet shares tumble in $500bn rout"}, 9999, True, {"i": DD["CNBC"]}]}]
news2, dropped2 = na.pick_verbatim(bad, pool, 8)
assert [x["source"] for x in news2[0]["also"]] == ["CNBC"]                                                                                 # само индексът без ехо (приема се, както при "i")
assert [x["reason"] for x in dropped2] == ["също: ехото не съвпада със заглавието", "също: невалиден или вече използван индекс", "също: невалиден или вече използван индекс"]
print(f"  ✓ причините: {[x['reason'] for x in dropped2]}")

print()
print("── 4. страницата и имейлът: „· +2 източника“ (30.10.2026: само броят, без линкове; основното заглавие — линк) ──")
b = copy.deepcopy(B19); b["news"] = news
with q():
    page = render.render_dashboard(b, publish=False)
    mail = render.render_email(b)
assert '<span class="news-why" style="font-size:12px" title="Financial Times, CNBC">· +2 източника</span>' in page
assert ' · +2 източника</span>' in mail and d["also"][0]["link"] not in page and d["also"][0]["link"] not in mail
assert f'href="{esc(d["link"])}"' in page                                                                                   # основното заглавие остава линк
print("  ✓ страница и имейл")
import inspect
assert "{ALSO_RULE}" in inspect.getsource(na.significant_news) and "Същата тема НЕ е същото събитие" in na.ALSO_RULE and '"also": [{"i": 5' in inspect.getsource(na.significant_news)
print("  ✓ правилото „една история — една новина“ и полето \"also\" — в промпта")
print("\n✅ test_news_one_story: всичко мина")
