"""
29.10.2026 · разходката, т. 3–4, решение 1: заглавието е линк към статията (без отделен ред за линка) — и при „Значими новини“, и при крипто. До 29.10 тегленето на RSS
(news_aggregator._fetch_rss) не пазеше линка и крипто новините бяха с link: null. Сега: линкът от фийда (само http/https) → пулът → редът в брифа (pick_verbatim по същия индекс) →
<a class="news-head" …> на страницата и <a href> в имейла (крипто не е в имейла). Без линк — заглавието остава текст.

РЕАЛНО: tests/fixtures/news_rss_cnbc_2026-10-29.xml (30 заглавия, SHA-256 5fb55bd0f21df4e5…), news_rss_ft_2026-10-29.xml (11, 94d0a9290bb8faa7…),
news_rss_reuters_gnews_2026-10-29.xml (Google News site:reuters.com, 100, 8cd339cae668cd40…) — фийдовете от config.NEWS_RSS_FEEDS, свалени на 29.10.2026 в 16:18 UTC;
tests/fixtures/cointelegraph_rss_2026-10-29.xml (29.10, 10:27 UTC); tests/fixtures/brief_2026-10-19.json — рамката на страницата и имейла.
СИНТЕТИЧНО (означено): отговорите на модела (индекси, why), подмененият requests.get (връща fixture-а), линкът „javascript:“ в т. 4.
Пускане: python test_news_links.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re
from html import escape as esc
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_links_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import news_aggregator as na, crypto_news as cn, render

FX = ROOT / "tests" / "fixtures"
B19 = json.loads((FX / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())


class _Resp:
    def __init__(self, b): self.content = b


def fetch(fixture, source):
    na.requests.get = lambda url, timeout=None, headers=None: _Resp((FX / fixture).read_bytes())          # СИНТЕТИЧНО: мрежата е подменена с РЕАЛНИЯ фийд
    return na._fetch_rss("https://example.invalid/rss", source, hours=24 * 3650, limit=200)


print("── 1. РЕАЛНИТЕ фийдове от 29.10: всяко заглавие носи линка към статията ──")
pools = {"CNBC": fetch("news_rss_cnbc_2026-10-29.xml", "CNBC"), "Financial Times": fetch("news_rss_ft_2026-10-29.xml", "Financial Times"),
         "Reuters Business": fetch("news_rss_reuters_gnews_2026-10-29.xml", "Reuters Business")}
host = {"CNBC": "https://www.cnbc.com/", "Financial Times": "https://www.ft.com/", "Reuters Business": "https://news.google.com/rss/articles/"}
for s, rows in pools.items():
    assert rows and all(r["link"].startswith(host[s]) for r in rows), s
    print(f"  ✓ {s}: {len(rows)} заглавия, всички с линк ({host[s]}…)")
assert len(pools["CNBC"]) == 30 and len(pools["Financial Times"]) == 11 and len(pools["Reuters Business"]) == 100

print()
print("── 2. pick_verbatim: редът в брифа носи линка на същия индекс; страницата и имейлът — заглавието е линк ──")
pool = na._interleave(list(pools.values()))
ft = next(k for k, r in enumerate(pool) if r["title"] == "Alphabet shares tumble in $500bn rout")
cnbc = next(k for k, r in enumerate(pool) if r["title"].startswith("Third-quarter U.S. GDP increases"))
ans = [{"i": ft, "h": " ".join(pool[ft]["title"].split()[:6]), "why": "Натиск върху технологичния сектор."},                  # СИНТЕТИЧНО
       {"i": cnbc, "h": " ".join(pool[cnbc]["title"].split()[:6]), "why": "По-силен растеж — по-малко място за понижение на лихвите."}]
news, dropped = na.pick_verbatim(ans, pool, 8)
assert [n["link"] for n in news] == [pool[ft]["link"], pool[cnbc]["link"]] and not dropped
b = copy.deepcopy(B19); b["news"] = news
with q():
    page = render.render_dashboard(b, publish=False)
    mail = render.render_email(b)
for n in news:
    tag = f'<a class="news-head" href="{esc(n["link"])}" target="_blank" rel="noopener noreferrer">{esc(n["headline"])}</a>'
    assert tag in page, tag
    assert f'<a href="{esc(n["link"])}" style="color:#111827;font-weight:bold">' in mail
sec = page[page.index("<h2>Значими новини"):]; sec = sec[:sec.index("</section>")]
assert sec.count(esc(news[0]["link"])) == 1 and ">" + esc(news[0]["link"]) + "<" not in sec                                                  # линкът не е отделен видим ред
print(f"  ✓ «{news[0]['headline']}» → {news[0]['link'][:45]}… (страница и имейл); линкът не е отделен ред")

print()
print("── 3. крипто: РЕАЛНИЯТ Cointelegraph от 29.10 — линкът минава до картата (до 29.10 беше null) ──")
cpool = fetch("cointelegraph_rss_2026-10-29.xml", "Cointelegraph")
dtcc = next(k for k, r in enumerate(cpool) if r["title"] == "DTCC unit launches tokenization services")
assert cpool[dtcc]["link"].startswith("https://cointelegraph.com/")
px = pd.concat({t: pd.DataFrame({"Close": [100.0 + k for k in range(10)]}, index=pd.date_range("2026-10-15", periods=10, freq="B")) for t in config.CRYPTO_TICKERS}, axis=1)   # СИНТЕТИЧНИ
ai = {"news": [{"i": dtcc, "h": " ".join(cpool[dtcc]["title"].split()[:6]), "cat": "exchange_bank", "why": "Инфраструктурата на пазара навлиза в токенизацията."}]}  # СИНТЕТИЧНО
with q():
    out = cn.build("2026-10-29", fetch=lambda: cpool, ai_call=lambda s, u: json.dumps(ai), download=lambda t: px)
assert out["items"][0]["link"] == cpool[dtcc]["link"]
b = copy.deepcopy(B19); b["crypto"] = out
with q():
    page = render.render_dashboard(b, publish=False)
assert "&utm_medium=" in cpool[dtcc]["link"]                                                                                     # РЕАЛНО: линкът носи „&“ — в HTML е „&amp;“
assert f'<a class="news-head" href="{esc(cpool[dtcc]["link"])}" target="_blank" rel="noopener noreferrer">DTCC unit launches tokenization services</a>' in page
print(f"  ✓ DTCC → {cpool[dtcc]['link'][:60]}…")

print()
print("── 4. СИНТЕТИЧНО: линк, който не е http(s), не минава; без линк — заглавието е текст ──")
assert na._safe_link("javascript:alert(1)") is None and na._safe_link(" https://x.test/a ") == "https://x.test/a" and na._safe_link(None) is None
b = copy.deepcopy(B19); b["news"] = [{"headline": "Без линк", "source": "CNBC", "why": "—"}, {"headline": "Опасен", "source": "CNBC", "why": "—", "link": "javascript:alert(1)"}]
with q():
    page = render.render_dashboard(b, publish=False)
    mail = render.render_email(b)
assert '<span class="news-head">Без линк</span>' in page and '<span class="news-head">Опасен</span>' in page and "javascript:" not in page
assert "<b>Без линк</b>" in mail and "javascript:" not in mail
print("  ✓ „javascript:“ — отпада още при тегленето, а и шаблонът/имейлът не го рисуват; без линк — <span>/<b>")
print("\n✅ test_news_links: всичко мина")
