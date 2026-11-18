"""
18.11.2026 (поправка към спешния пакет): пулът към подбора на новините е config.NEWS_MAX_TO_FILTER на 24 ч (18.11: 100 от 139) и се режеше по реда във фийдовете (редуването;
Reuters ≈ 31 от 50). Сега преди тавана първи са заглавията за нашите тикъри и компании (news_aggregator.priority_entries: книгите, наблюдаваните, картите, „Нощта“ и отчетите
за деня; priority_matchers — името без правната форма, отличителните думи, тикърът), после останалите в досегашния ред; след тавана на източника (50) се вземат и
приоритетните (до config.NEWS_PRIORITY_EXTRA_PER_SOURCE). Сивият ред под новините казва колко заглавия минаха напред и за кои тикъри.

Измерено върху избраните заглавия 13.06–18.11 (1035, с имената от брифа на 18.11, наблюдаваните и книгите към 18.11): 12 съвпадения, всичките истински (Apple ×7, Honeywell ×2,
Accenture, AMD, Nvidia) — след махането на общите думи („Nasdaq“ — 9 фалшиви за NDAQ, „Companies“ — TRV, „Aerospace“ — GE; в пула от 18.11 и „Manhattan“ — MANH, „West“ — WST).

РЕАЛНО: tests/fixtures/news_priority_2026-11-18.json — заглавията на Reuters и AP в прозореца на брифа от 18.11 (свалени следобед, подредени по час — ТОЧНИЯТ ред към 06:43 UTC
не е пазен), CNBC и FT (5 и 4, останалите — изместени), приоритетните имена за 18.11 и заглавия от историята. СИНТЕТИЧНО (означено): заместителите за CNBC (до 29) и FT (до 10),
RSS отговорът в т. 4, предишният бриф в т. 3.
Пускане: python test_news_priority.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_prio_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import news_aggregator as na, render

FX = json.loads((ROOT / "tests" / "fixtures" / "news_priority_2026-11-18.json").read_text(encoding="utf-8"))
M = na.priority_matchers(FX["priority"])
filler = lambda src, have, n: have + [{"source": src, "title": f"[{src}: заглавие {k}, изместено от фийда — СИНТЕТИЧНО]", "published": "2026-11-18T06:43Z"}
                                      for k in range(n - len(have))]
CNBC, FT = filler("CNBC", FX["cnbc"], FX["counts"]["CNBC"]), filler("Financial Times", FX["ft"], FX["counts"]["Financial Times"])


def pool(prio: bool) -> tuple[list[dict], int]:
    """Като gather_raw + significant_news: по 50 от източник (+ приоритетните след тавана), редуване, без повторения, приоритет, таван 100."""
    def src(xs):
        out = xs[:config.NEWS_PER_SOURCE_LIMIT]
        if prio:
            out += [dict(x, beyond_limit=True) for x in xs[config.NEWS_PER_SOURCE_LIMIT:] if na.priority_hits(x["title"], M)][:config.NEWS_PRIORITY_EXTRA_PER_SOURCE]
        return out
    raw, seen, d = na._interleave([src(FX["reuters"]), CNBC, FT, src(FX["ap"])]), set(), []
    for it in raw:
        k = it["title"].lower()[:90]
        if k not in seen:
            seen.add(k); d.append(it)
    if prio:
        d, _ = na.prioritize(d, M)
    return d[:config.NEWS_MAX_TO_FILTER], len(d)


print("── 1. РЕАЛНО (редът — приблизителен): заглавията за Nvidia на 18.11 — старият и новият пул ──")
old, n_old = pool(False)
new, n_new = pool(True)
NV = [x["title"] for x in FX["reuters"] + FX["ap"] + FX["cnbc"] if "nvidia" in x["title"].lower()]
T_old, T_new = {x["title"] for x in old}, {x["title"] for x in new}
assert (n_old, len(NV)) == (139, 16), (n_old, len(NV))
assert sum(t in T_old for t in NV) == 5 and all(t in T_new for t in NV)
TD = "Trading Day: AI trade unwind continues, but Nvidia beats - Reuters"
SW = "Nvidia shares set for $335 billion swing after earnings, options show - Reuters"
IV = "Instant view: Nvidia earnings beat estimates; attention turns to call - Reuters"
assert IV in T_old and TD not in T_old and SW not in T_old and TD in T_new and SW in T_new
assert next(x for x in new if x["title"] == SW)["beyond_limit"] and [x["title"] for x in new[:len(NV)]] == [x["title"] for x in new if x.get("priority")][:len(NV)]
print(f"  ✓ стар: 5 от 16 (с „Instant view: Nvidia earnings beat…“); нов: 16 от 16, първи; „…$335 billion swing after earnings“ — след тавана на Reuters")

print("── 2. РЕАЛНО: съвпаденията — верни и фалшиви ──")
for t in FX["reuters"] + FX["ap"] + FX["cnbc"] + FX["ft"]:
    h = na.priority_hits(t["title"], M)
    assert set(h) <= {"NVDA", "AAPL", "COST"}, (h, t["title"])                    # Manhattan (MANH), West Bank / East-West (WST) — не
names = [{"ticker": "NDAQ", "name": "Nasdaq, Inc."}, {"ticker": "TRV", "name": "Travelers Companies (The)"}, {"ticker": "MANH", "name": "Manhattan Associates"},
         {"ticker": "AAPL", "name": "Apple Inc."}, {"ticker": "ACN", "name": "Accenture"}, {"ticker": "COST", "name": "Costco"}, {"ticker": "GE", "name": "GE Aerospace"},
         {"ticker": "HONA", "name": "Honeywell Aerospace"}]                                         # имената — от brief["names"] на 18.11
MH = na.priority_matchers(names)
for t in FX["history_titles"]["fp"]:
    assert na.priority_hits(t, MH) == [], (t, na.priority_hits(t, MH))
for t, tk in FX["history_titles"]["tp"]:
    assert na.priority_hits(t, MH) == [tk], (t, na.priority_hits(t, MH))
assert na.priority_hits("We're downgrading Honeywell Aerospace after a shockingly bad earnings debut", MH) == ["HONA"]
print("  ✓ Nasdaq (индексът), Companies, Manhattan — без съвпадение; Apple, Accenture, Costco, Honeywell — да")

print("── 3. СИНТЕТИЧНО: priority_entries — книгите, наблюдаваните, картите, „Нощта“, отчетите днес ──")
prev = {"names": {"NVDA": "Nvidia", "AAPL": "Apple Inc."}, "qm_breakout": [{"ticker": "GKOS", "name": "Glaukos"}],
        "week_calendar": {"days": [{"date": "2026-11-17", "earnings": [{"ticker": "NVDA", "when": "след затварянето", "name": "NVIDIA Corporation"},
                                                                       {"ticker": "HD", "when": "преди отварянето", "name": "Home Depot"}]},
                                   {"date": "2026-11-18", "earnings": [{"ticker": "TJX", "when": "преди отварянето", "name": "TJX Companies"}]}]}}
E = na.priority_entries(prev, "2026-11-18", [{"ticker": "RGA", "name": "Reinsurance Group of America"}], ["DOCU"], ["AAPL", "AAPL"])
assert [(e["ticker"], e["why"]) for e in E] == [("AAPL", "книгите"), ("DOCU", "наблюдаван"), ("RGA", "карта"), ("GKOS", "карта"), ("NVDA", "отчет (Нощта)"), ("TJX", "отчет днес")], E
assert E[0]["name"] == "Apple Inc." and na.priority_entries(None, "не е дата") == []         # провал → [] (пулът — както до 18.11)
print("  ✓ без повторения; HD (преди отварянето на 17.11) — не; провал → []")

print("── 4. СИНТЕТИЧНО: _fetch_rss — след тавана на източника само приоритетните ──")
items = "".join(f"<item><title>{t}</title><link>https://example.com/{k}</link><pubDate>Tue, 17 Nov 2026 2{k % 10}:00:00 GMT</pubDate></item>"
                for k, t in enumerate(["Headline one", "Headline two", "Apple earnings due", "Headline four", "Nvidia forecasts revenue"]))
class R:
    status_code, content = 200, f"<?xml version='1.0'?><rss><channel>{items}</channel></rss>".encode()
orig = na.requests.get
na.requests.get = lambda *a, **k: R()
try:
    plain = na._fetch_rss("u", "Reuters Business", 48, limit=2)
    kept = na._fetch_rss("u", "Reuters Business", 48, limit=2, keep=lambda t: bool(na.priority_hits(t, na.priority_matchers([{"ticker": "NVDA", "name": "Nvidia"}, {"ticker": "AAPL", "name": "Apple"}]))), keep_max=1)
finally:
    na.requests.get = orig
assert [x["title"] for x in plain] == ["Headline one", "Headline two"]
assert [x["title"] for x in kept] == ["Headline one", "Headline two", "Apple earnings due"] and kept[2]["beyond_limit"]        # keep_max=1
print("  ✓ таванът 2 + 1 приоритетно след него (keep_max)")

print("── 5. сивият ред и main ──")
nw = {"to_model": {"Reuters Business": 50, "CNBC": 29, "Financial Times": 10, "AP Business": 11}, "fetched": {"Reuters Business": 55}, "pool_used": 100, "pool_total": 144,
      "priority": {"names": 51, "hits": 16, "in_pool": 16, "beyond_limit": 5, "tickers": ["NVDA"]}}
note = render.news_pool_note(nw, {"returned": 8, "kept": 8, "dropped": []})
assert "; първи — 16 за нашите тикъри и компании (NVDA), от тях 5 след тавана на източника" in note, note
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "news_aggregator.significant_news(since=news_since, priority=news_priority)" in src and "news_aggregator.priority_entries(prev_for_regime, today, candidates," in src
print(f"  ✓ «{note[:120]}…»")
print("\n✅ test_news_priority: всичко мина")
