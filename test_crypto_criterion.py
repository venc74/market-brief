"""
29.10.2026 · разходката, т. 4, решение (а): мерилото на крипто новините — вместо затворения списък с категории въпросът „би ли променила тази новина решението на институционален
инвеститор в крипто след седмица?“ с изрични примери: важно — навлизането на традиционните финанси (токенизация на ценни книжа, DTCC, големи банки, стейбълкойни / регулатори);
не — прогнози за цената, малки монети, мнения. Таван 5 (config.CRYPTO_MAX_ITEMS), дневните потоци в ETF — най-много един ред ("etf_flows": true).
Тестът „DTCC трябва да мине“: истинското решение е на модела — офлайн (без мрежа и без ключ) се проверява, че (1) промптът носи въпроса и примерите, вкл. DTCC и токенизацията,
и вижда DTCC в пула; (2) ако моделът избере DTCC, кодът не я маха — до 29.10 я махаше, щом етикетът е извън списъка („tokenization“). Живата проверка — pool_items в брифа от 30.10.

РЕАЛНО: tests/fixtures/cointelegraph_rss_2026-10-29.xml — фийдът на Cointelegraph, свален на 29.10.2026 в 10:27 UTC (в него „DTCC unit launches tokenization services“, 28.10 13:19 UTC).
СИНТЕТИЧНО (означено): часът на run-а (06:30 UTC), отговорите на модела, цените на тикърите.
Пускане: python test_crypto_criterion.py
"""
import sys, json, pathlib, tempfile, calendar, datetime as dt, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_ccrit_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import feedparser
from src import crypto_news as cn

feed = feedparser.parse((ROOT / "tests" / "fixtures" / "cointelegraph_rss_2026-10-29.xml").read_bytes())
RUN = dt.datetime(2026, 10, 29, 6, 30, tzinfo=dt.timezone.utc).timestamp()                                 # СИНТЕТИЧНО: часът на run-а
POOL = [{"source": "Cointelegraph", "title": e.title.strip(), "summary": (e.get("summary") or "")[:300]} for e in feed.entries
        if RUN - config.CRYPTO_NEWS_HOURS * 3600 <= calendar.timegm(e.published_parsed) <= RUN]
dtcc = next(i for i, r in enumerate(POOL) if r["title"] == "DTCC unit launches tokenization services")
h6 = lambda i: " ".join(POOL[i]["title"].split()[:6])

print("── 1. промптът: въпросът, примерите „да“ и „не“, таванът; DTCC е в пула, който вижда моделът ──")
p = cn._prompt(POOL, config.CRYPTO_MAX_ITEMS)
assert "би ли променила тази новина решението на институционален инвеститор в крипто след седмица?" in p
for w in ("токенизация на ценни книжа", "DTCC", "големи банки", "стейбълкойни", "регулатори", "прогнози и дневни отчети за цената", "малки монети", "мнения"):
    assert w in p, w
assert "Най-много 5 новини" in p and config.CRYPTO_MAX_ITEMS == 5 and '"etf_flows": true' in p and "Една история — една новина" in p
assert '"t": "DTCC unit launches tokenization services"' in p and '"cat"' not in p and '- "regulation"' not in p                 # без стария списък с категории
print(f"  ✓ въпросът и примерите; таван 5; DTCC (№ {dtcc} от {len(POOL)}) — в пула на промпта; старият списък с категории го няма")

print()
print("── 2. „DTCC трябва да мине“: при избор кодът я пази — и със стария етикет „tokenization“ (СИНТЕТИЧЕН отговор) ──")
items, dropped = cn.select({"news": [{"i": dtcc, "h": h6(dtcc), "cat": "tokenization", "why": "Пазарната инфраструктура на САЩ навлиза в токенизацията."}]}, POOL)
assert [x["headline"] for x in items] == ["DTCC unit launches tokenization services"] and not dropped
print("  ✓ DTCC минава (до 29.10: „категория извън списъка (tokenization)“ → махната)")

print()
print("── 3. таванът 5 и един ред за потоци в ETF (СИНТЕТИЧНО) ──")
ks = [k for k in range(len(POOL)) if k != dtcc][:6]
ans = {"news": [{"i": dtcc, "h": h6(dtcc), "why": "Токенизация от DTCC."}] + [{"i": k, "h": h6(k), "why": "Синтетично „защо“ без числа.", "etf_flows": n < 2} for n, k in enumerate(ks)]}
items, dropped = cn.select(ans, POOL)
assert len(items) == 5 and items[0]["headline"].startswith("DTCC")
assert [d["reason"] for d in dropped] == ["второ заглавие за дневни потоци в ETF", "над тавана от 5"]
print(f"  ✓ {len(items)} новини; вторият ред за потоци и шестият — отпадат с причина")

print()
print("── 4. build(): pool_items — DTCC „избрана“ ──")
px = pd.concat({t: pd.DataFrame({"Close": [100.0 + k for k in range(10)]}, index=pd.date_range("2026-10-15", periods=10, freq="B")) for t in config.CRYPTO_TICKERS}, axis=1)   # СИНТЕТИЧНИ
with contextlib.redirect_stdout(io.StringIO()):
    out = cn.build("2026-10-29", fetch=lambda: POOL, ai_call=lambda s, u: json.dumps(ans), download=lambda t: px)
assert out["pool_items"][dtcc]["status"] == "избрана" and [r["status"] for r in out["pool_items"]].count("избрана") == 5
print("  ✓ pool_items: DTCC — избрана")
print("\n✅ test_crypto_criterion: всичко мина")
