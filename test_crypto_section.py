"""
22.10.2026 · етап 4 (решения от 21–22.10): крипто секцията. Новини от RSS на Cointelegraph (https://cointelegraph.com/rss — „?format=rss“ връща HTML) през AI подбор по индекс:
заглавието и източникът са ДОСЛОВНИ (news_aggregator.pick_verbatim + ехо на първите 6 думи), AI дава категория от затворения списък и „защо“; най-много 4 новини, от тях най-много 1
за ETF потоци; без значими — един ред. Под тях COIN / HOOD / CRCL / BLSH (последен цял бар) и COT за Bitcoin само в първия бриф след нов отчет. Тезата „Крипто регулация (CLARITY Act)“
отпадна със секцията. Измерено 21.10: 50 от 304 реални заглавия минават по критериите (моя преценка); истинският филтър се проверява на живо.

РЕАЛНО: tests/fixtures/cointelegraph_rss_2026-10-21.xml — фийдът https://cointelegraph.com/rss, свален на 21.10.2026 в ~20:00 Берлин (30 заглавия, 20.10 16:14 → 21.10 17:57 UTC;
SHA-256 89ae44f0e1177d21…); tests/fixtures/brief_2026-10-19.json — брифът за страницата.
СИНТЕТИЧНО (означено): отговорите на AI, цените на тикърите и COT серията за Bitcoin.
Пускане: python test_crypto_section.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_crypto_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import feedparser
from src import crypto_news as cn, render

feed = feedparser.parse((ROOT / "tests" / "fixtures" / "cointelegraph_rss_2026-10-21.xml").read_bytes())
POOL = [{"source": "Cointelegraph", "title": e.title.strip(), "summary": (e.get("summary") or "")[:300]} for e in feed.entries]
assert len(POOL) == 30 and "Крипто регулация (CLARITY Act)" not in [b["name"] for b in config.THESIS_BASKETS]
idx = {k: next(i for i, r in enumerate(POOL) if r["title"].startswith(k)) for k in ("OCC finalizes GENIUS", "Ether ETF outflows", "Drift exploiter", "Standard Chartered signs", "Treasury Secretary Bessent")}
h6 = lambda i: " ".join(POOL[i]["title"].split()[:6])

print("── 1. подборът върху РЕАЛНИЯ фийд (СИНТЕТИЧЕН отговор на AI) ──")
ans = {"news": [{"i": idx["OCC finalizes GENIUS"], "h": h6(idx["OCC finalizes GENIUS"]), "cat": "regulation", "why": "Правилата по GENIUS Act засягат емитентите на стейбълкойни като Circle (CRCL)."},
                {"i": idx["Ether ETF outflows"], "h": h6(idx["Ether ETF outflows"]), "cat": "etf_flows", "why": "Отливът от ETF-ите на Ether продължава."},
                {"i": idx["Drift exploiter"], "h": h6(idx["Drift exploiter"]), "cat": "hack", "why": "Голям хак — откраднатото минава през миксер."},
                {"i": idx["Standard Chartered signs"], "h": h6(idx["Standard Chartered signs"]), "cat": "etf_flows", "why": "Втори за потоци — отпада."},
                {"i": idx["Treasury Secretary Bessent"], "h": h6(idx["Treasury Secretary Bessent"]), "cat": "opinion", "why": "Категория извън списъка — отпада."},
                {"i": 99, "h": "x", "cat": "regulation", "why": "лош индекс"},
                {"i": idx["Drift exploiter"], "h": "Bitcoin price tags new high today", "cat": "hack", "why": "повторен"}]}
items, dropped = cn.select(ans, POOL)
assert [(x["headline"], x["cat"]) for x in items] == [(POOL[idx["OCC finalizes GENIUS"]]["title"], "regulation"), (POOL[idx["Ether ETF outflows"]]["title"], "etf_flows"),
                                                    (POOL[idx["Drift exploiter"]]["title"], "hack")]
assert all(x["source"] == "Cointelegraph" for x in items) and items[0]["cat_label"] == "регулация"
reasons = " | ".join(str(d.get("reason")) for d in dropped)
assert "второ заглавие за ETF потоци" in reasons and "категория извън списъка (opinion)" in reasons and "няма валиден индекс" in reasons
print(f"  ✓ минават 3 дословни заглавия: «{items[0]['headline']}» (регулация), ETF потоци, хак; отпадат вторият за ETF потоци, категория извън списъка, лош и повторен индекс")

print()
print("── 2. build(): кеш по ден, цени, COT само при нов отчет ──")
calls = []
ai = lambda s, u: (calls.append(u), json.dumps(ans))[1]
idx_d = pd.date_range("2026-10-08", "2026-10-21", freq="B")
px = pd.concat({t: pd.DataFrame({"Close": [100 + k for k in range(len(idx_d))]}, index=idx_d) for t in config.CRYPTO_TICKERS}, axis=1)     # СИНТЕТИЧНИ цени
btc = [{"date": f"2026-{m:02d}-{d:02d}", "net": n} for (m, d), n in zip([(7, x) for x in range(1, 29, 7)] + [(8, x) for x in range(1, 29, 7)] + [(9, x) for x in range(1, 29, 7)], range(-5000, 7000, 1000))]   # СИНТЕТИЧНА серия
out = cn.build("2026-10-22", cot_fresh=False, cot_series={config.CRYPTO_COT_MARKET: btc}, fetch=lambda: POOL, ai_call=ai, download=lambda t: px)
assert out["ok"] and len(out["items"]) == 3 and out["pool"] == 30 and out["cot_btc"] is None and len(calls) == 1
assert [t["ticker"] for t in out["tickers"]] == config.CRYPTO_TICKERS and out["tickers"][0]["date"] == "2026-10-21" and out["tickers"][0]["chg_1d_pct"] == round((109 / 108 - 1) * 100, 1)
again = cn.build("2026-10-22", cot_fresh=True, cot_series={config.CRYPTO_COT_MARKET: btc}, fetch=lambda: POOL, ai_call=ai, download=lambda t: px)
assert len(calls) == 1 and again["items"] == out["items"]                                    # кешът за деня — без второ извикване
assert again["cot_btc"] == {"as_of": btc[-1]["date"], "net": btc[-1]["net"], "percentile": 100.0, "weeks": len(btc)}
none = cn.build("2026-10-23", fetch=lambda: POOL, ai_call=lambda s, u: json.dumps({"news": []}), download=lambda t: px)
fail = cn.build("2026-10-24", fetch=lambda: [], ai_call=ai, download=lambda t: (_ for _ in ()).throw(RuntimeError("Yahoo")))
assert none["ok"] and none["items"] == [] and not fail["ok"] and fail["reason"] == "фийдът на Cointelegraph не върна заглавия" and fail["tickers"] == []
print("  ✓ 3 новини, цените — от последния цял бар преди деня; втори run същия ден — от кеша; COT за Bitcoin — само при нов отчет; празен фийд → причина, без грешка")

print()
print("── 3. страницата (РЕАЛНИЯТ бриф от 19.10) ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
page = lambda c: (b.__setitem__("crypto", c), render.render_dashboard(copy.deepcopy(b)))[1]
with contextlib.redirect_stdout(io.StringIO()):
    p1, p2, p3 = page(again), page(none), page(fail)
sec = p1[p1.index("Крипто · последните 24ч"):]; sec = sec[:sec.index("</section>")]
assert POOL[idx["OCC finalizes GENIUS"]]["title"] in sec and "· Cointelegraph" in sec and "· регулация" in sec and "<b>COIN</b>" in sec and "COT Bitcoin (CME, managed money)" in sec
assert "Няма значими крипто новини (проверени 30 заглавия от Cointelegraph)." in p2 and "празното НЕ значи, че няма новини" in p3
print("  ✓ новините, цените и COT; „няма значими“ с броя проверени; провал — не изглежда като „няма“")
print("\n✅ test_crypto_section: всичко мина")
