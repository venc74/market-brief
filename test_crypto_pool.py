"""
29.10.2026 · крипто секцията пази целия пул в данните на брифа: brief["crypto"]["pool_items"] = [{i, title, status, cat?, reason?}], status „избрана“ / „махната от кода“
(AI я избра, проверката я махна — с причината) / „не е избрана от AI“; и в дневния кеш (повторен run го връща).
Повод: на 29.10 не се виждаше дали „DTCC unit launches tokenization services“ (Cointelegraph, 28.10 13:19 UTC) е била в пула — пазеше се само броят (21).
Проверено 29.10 върху фийда, свален в 10:27 UTC: заглавията в прозореца от 30 часа преди run-а (06:30 UTC) са точно 21 (21 и при run между 06:00 и 06:47 UTC) и DTCC е сред тях →
била е в пула и не е избрана (избрани: „Bitcoin ETF inflows climb to $176M…“ и „Google Cloud outlines MPC service…“); дали я е отсял AI или проверката на кода — от 29.10 не се знае.

РЕАЛНО: tests/fixtures/cointelegraph_rss_2026-10-29.xml — фийдът https://cointelegraph.com/rss, свален на 29.10.2026 в 10:27 UTC (30 заглавия, 27.10 15:59 → 29.10 07:32 UTC;
SHA-256 549dc6b86857b560…); двете избрани заглавия и броят 21 — от брифа на 29.10 (data/2026-10-29.json).
СИНТЕТИЧНО (означено): часът на run-а (06:30 UTC — 07:30 Берлин), отговорът на AI (възпроизвежда публикуваното: двете заглавия), махнатото от кода в т. 3, цените.
Пускане: python test_crypto_pool.py
"""
import sys, json, pathlib, tempfile, calendar, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_cpool_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import feedparser
from src import crypto_news as cn

feed = feedparser.parse((ROOT / "tests" / "fixtures" / "cointelegraph_rss_2026-10-29.xml").read_bytes())
RUN = dt.datetime(2026, 10, 29, 6, 30, tzinfo=dt.timezone.utc).timestamp()                                 # СИНТЕТИЧНО: часът на run-а
POOL = [{"source": "Cointelegraph", "title": e.title.strip(), "summary": (e.get("summary") or "")[:300]} for e in feed.entries
        if RUN - config.CRYPTO_NEWS_HOURS * 3600 <= calendar.timegm(e.published_parsed) <= RUN]
assert len(feed.entries) == 30 and len(POOL) == 21                                                          # = brief["crypto"]["pool"] на 29.10
dtcc = next(i for i, r in enumerate(POOL) if r["title"] == "DTCC unit launches tokenization services")
pick = {k: next(i for i, r in enumerate(POOL) if r["title"].startswith(k)) for k in ("Bitcoin ETF inflows climb to $176M", "Google Cloud outlines MPC service")}
h6 = lambda i: " ".join(POOL[i]["title"].split()[:6])
px = pd.concat({t: pd.DataFrame({"Close": [100.0 + k for k in range(10)]}, index=pd.date_range("2026-10-15", periods=10, freq="B")) for t in config.CRYPTO_TICKERS}, axis=1)   # СИНТЕТИЧНИ

print("── 1. пулът на 29.10 (РЕАЛНИЯТ фийд, прозорецът преди run-а) ──")
ans = {"news": [{"i": pick["Bitcoin ETF inflows climb to $176M"], "h": h6(pick["Bitcoin ETF inflows climb to $176M"]), "cat": "etf_flows", "why": "Приток към спот Bitcoin ETF-ите."},
                {"i": pick["Google Cloud outlines MPC service"], "h": h6(pick["Google Cloud outlines MPC service"]), "cat": "exchange_bank", "why": "Google Cloud влиза в съхранението."}]}   # СИНТЕТИЧНО
out = cn.build("2026-10-29", fetch=lambda: POOL, ai_call=lambda s, u: json.dumps(ans), download=lambda t: px)
P = out["pool_items"]
assert out["pool"] == 21 and len(P) == 21 and [r["title"] for r in P] == [r["title"] for r in POOL]
assert [x["headline"] for x in out["items"]] == ["Bitcoin ETF inflows climb to $176M as BTC rebounds above $80K", "Google Cloud outlines MPC service for institutional Bitcoin custody"]
assert P[dtcc] == {"i": dtcc, "title": "DTCC unit launches tokenization services", "status": "не е избрана от AI"}
assert [r["status"] for r in P].count("избрана") == 2 and P[pick["Google Cloud outlines MPC service"]]["cat"] == "exchange_bank"
print(f"  ✓ 21 заглавия в pool_items; DTCC (№ {dtcc}) — «не е избрана от AI»; двете избрани — «избрана»")

print()
print("── 2. кешът за деня връща и пула ──")
again = cn.build("2026-10-29", fetch=lambda: (_ for _ in ()).throw(AssertionError("не се тегли пак")), ai_call=lambda s, u: 1 / 0, download=lambda t: px)
assert again["pool_items"] == P
print("  ✓ повторен run — същият pool_items от кеша, без теглене и без AI")

print()
print("── 3. махнатото от кода — с причината (СИНТЕТИЧЕН отговор: DTCC с категория извън списъка) ──")
ans2 = {"news": ans["news"] + [{"i": dtcc, "h": h6(dtcc), "cat": "tokenization", "why": "Токенизация от DTCC."}]}
out2 = cn.build("2026-10-30", fetch=lambda: POOL, ai_call=lambda s, u: json.dumps(ans2), download=lambda t: px)
assert out2["pool_items"][dtcc] == {"i": dtcc, "title": "DTCC unit launches tokenization services", "status": "махната от кода", "reason": "категория извън списъка (tokenization)",
                                    "cat": "tokenization"}
print(f"  ✓ «{out2['pool_items'][dtcc]['status']}: {out2['pool_items'][dtcc]['reason']}»")
print("\n✅ test_crypto_pool: всичко мина")
