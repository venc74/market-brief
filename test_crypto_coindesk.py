"""
29.10.2026 · разходката, т. 4, решение (б): втори източник за крипто новините — RSS на CoinDesk (config.CRYPTO_RSS_FEEDS). Проверено 29.10 в 16:16 UTC: достъпен
(https://www.coindesk.com/arc/outboundfeeds/rss/ → 308 към адреса без наклонената черта), 25 заглавия за 12.8 часа (03:21 → 16:11 UTC), без резюме, с директни линкове.
Пулът е на редуване (Cointelegraph, CoinDesk), дубълът по заглавие отпада; brief["crypto"]["pool_sources"] = {източник: {count, oldest}} — дали 25-те заглавия покриват 30-те часа.
Един мъртъв фийд не спира секцията.

РЕАЛНО: tests/fixtures/coindesk_rss_2026-10-29.xml (29.10, 16:16 UTC, SHA-256 c53d886d1d5c0082…) и tests/fixtures/cointelegraph_rss_2026-10-29.xml (29.10, 10:27 UTC).
СИНТЕТИЧНО (означено): подмененият requests.get (връща fixture-а по адреса), прозорецът на тегленето (широк — двата фийда са свалени в различен час), отговорът на модела.
Пускане: python test_crypto_coindesk.py
"""
import sys, json, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cdesk_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import news_aggregator as na, crypto_news as cn

FX = ROOT / "tests" / "fixtures"
FILES = {config.CRYPTO_RSS_FEEDS["Cointelegraph"]: "cointelegraph_rss_2026-10-29.xml", config.CRYPTO_RSS_FEEDS["CoinDesk"]: "coindesk_rss_2026-10-29.xml"}


class _Resp:
    def __init__(self, b): self.content = b


def serve(dead=()):
    na.requests.get = lambda url, timeout=None, headers=None: _Resp(b"" if url in dead else (FX / FILES[url]).read_bytes())   # СИНТЕТИЧНО: мрежата — РЕАЛНИТЕ фийдове


config.CRYPTO_NEWS_HOURS = 24 * 3650                                                                          # СИНТЕТИЧНО: широк прозорец
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. двата РЕАЛНИ фийда → един пул на редуване; покритие по източник ──")
assert config.CRYPTO_RSS_FEEDS["CoinDesk"] == "https://www.coindesk.com/arc/outboundfeeds/rss/"
serve()
pool = cn.fetch_pool()
src = [r["source"] for r in pool]
assert src.count("CoinDesk") == 25 and src.count("Cointelegraph") == 30 and src[:4] == ["Cointelegraph", "CoinDesk", "Cointelegraph", "CoinDesk"]
assert all(r["link"].startswith("https://www.coindesk.com/") and r["summary"] == "" for r in pool if r["source"] == "CoinDesk")
ps = cn.pool_sources(pool)
assert ps["CoinDesk"] == {"count": 25, "oldest": "2026-10-29T03:21Z"} and ps["Cointelegraph"]["count"] == 30
print(f"  ✓ {len(pool)} заглавия: Cointelegraph 30, CoinDesk 25 (най-старото {ps['CoinDesk']['oldest']} — 12.8 часа назад от свалянето); линкове към coindesk.com, без резюме")

print()
print("── 2. build(): pool_sources в брифа и в кеша; един мъртъв фийд не спира секцията ──")
px = pd.concat({t: pd.DataFrame({"Close": [100.0 + k for k in range(10)]}, index=pd.date_range("2026-10-15", periods=10, freq="B")) for t in config.CRYPTO_TICKERS}, axis=1)   # СИНТЕТИЧНИ
k = next(i for i, r in enumerate(pool) if r["title"] == "NYSE owner takes steps to bring Hyperliquid perpetual futures to U.S.")
ans = {"news": [{"i": k, "h": " ".join(pool[k]["title"].split()[:6]), "why": "Операторът на NYSE внася крипто деривати в САЩ."}]}            # СИНТЕТИЧНО
with q():
    out = cn.build("2026-10-29", ai_call=lambda s, u: json.dumps(ans), download=lambda t: px)
    again = cn.build("2026-10-29", fetch=lambda: 1 / 0, ai_call=lambda s, u: 1 / 0, download=lambda t: px)
assert out["items"][0]["source"] == "CoinDesk" and out["items"][0]["link"].startswith("https://www.coindesk.com/markets/2026/10/29/nyse-owner")
assert out["pool"] == 55 and out["pool_sources"] == ps and again["pool_sources"] == ps
serve(dead=(config.CRYPTO_RSS_FEEDS["CoinDesk"],))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    half = cn.build("2026-10-30", ai_call=lambda s, u: json.dumps({"news": []}), download=lambda t: px)
assert half["ok"] and half["pool"] == 30 and half["pool_sources"]["CoinDesk"] == {"count": 0, "oldest": None} and "CoinDesk: фийдът не върна заглавия" in buf.getvalue()
print("  ✓ избраната от CoinDesk — с линка; pool_sources — и от кеша; без CoinDesk — 30 заглавия от Cointelegraph и ред в лога")
print("\n✅ test_crypto_coindesk: всичко мина")
