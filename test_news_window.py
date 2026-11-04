"""
02.11.2026 · поправки след брифа, т. 4 — прозорците на новините. До 02.11 бяха фиксирани: главните 24 ч (gather_raw), наблюдаваните 24 ч (WATCH_NEWS_WINDOW_HOURS), крипто 30 ч —
в понеделник 02.11 макро разказът и наблюдаваните не видяха петъка (Intel, Amazon). Решение (02.11): от ПРЕДИШНИЯ бриф — 07:30 Берлин в деня на последната NYSE сесия
(sessions.news_window_start): понеделник 72 ч, след празник 48 ч, иначе 24 ч; крипто — не по-малко от 30 ч.
Google News (Reuters, AP) връща най-много 100 заглавия: при Reuters „when:3d“ дава СЪЩИТЕ 100 като „when:24h“ (≈ 22 ч назад) — не стига до петъка; при AP — извадка от трите дни.
Затова при прозорец над 25 ч — по една заявка „after:Д before:Д+1“ за всеки по-ранен ден (news_aggregator.google_day_urls). Бележката под новините казва колко е
прозорецът и изброява само източниците, които не стигат до началото му (прегледът на 02.11; FT държи ~12 заглавия).

РЕАЛНО: tests/fixtures/news_window_*_2026-11-02.xml.gz — фийдовете, свалени на 02.11.2026 ~15:25 UTC (бележката — news_window_2026-11-02.json): Reuters „when:24h“ и „when:3d“,
AP „when:3d“, заявките по дни 30.10 / 31.10 / 01.11 за Reuters и AP, CNBC и FT; tests/fixtures/brief_2026-10-19.json — рамката на страницата; календарът — config.NYSE_HOLIDAYS.
СИНТЕТИЧНО (означено): подмененият requests.get (връща fixture-а по адрес), часът „сега“ (06:37 UTC на 02.11 — фийдовете са от следобеда, заглавията след 06:37 се режат),
отговорът на AI (за промпта), функциите за новини / крипто, подменени в т. 5.
Пускане: python test_news_window.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_newswin_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import sessions, news_aggregator as na, render, watch_monitor as wm, crypto_news, ai_brief

FXD = ROOT / "tests" / "fixtures"
NOTE = json.loads((FXD / "news_window_2026-11-02.json").read_text(encoding="utf-8"))
PAGE = {v["url"]: gzip.decompress((FXD / name).read_bytes()) for name, v in NOTE["files"].items()}
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
UTC = dt.timezone.utc
at = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=UTC)
q = lambda: contextlib.redirect_stdout(io.StringIO())
R, A = config.NEWS_RSS_FEEDS["Reuters Business"], config.NEWS_RSS_FEEDS["AP Business"]
T = at("2026-11-02T06:37")                                                            # СИНТЕТИЧНО: „сега“ = стъпката на новините в run-а на 02.11
SINCE = at("2026-10-30T06:30")


class _Resp:
    def __init__(self, content): self.content = content


def serve(url, timeout=None, headers=None):                                          # СИНТЕТИЧНО: мрежата → РЕАЛНИЯТ фийд по адрес
    if url not in PAGE:
        raise ConnectionError(f"СИНТЕТИЧНО: няма fixture за {url}")
    return _Resp(PAGE[url])


na.requests.get = serve
titles = lambda rows: {r["title"] for r in rows}
before = lambda rows, t: [r for r in rows if r.get("published") and r["published"] <= t.strftime("%Y-%m-%dT%H:%MZ")]

print("── 1. началото на прозореца — предишният бриф (07:30 Берлин в деня на последната сесия; календарът — config.NYSE_HOLIDAYS) ──")
cases = {"2026-11-02T06:38": ("2026-10-30T06:30", 72.13),                          # понеделник → петък
         "2026-11-03T06:38": ("2026-11-02T06:30", 24.13),                          # вторник → понеделник
         "2026-11-27T06:38": ("2026-11-25T06:30", 48.13),                          # петък след Деня на благодарността (26.11) → сряда
         "2026-10-26T06:38": ("2026-10-23T05:30", 73.13)}                          # понеделник след смяната на часа в Европа (25.10): петък 07:30 CEST = 05:30 UTC
for now, (start, h) in cases.items():
    assert sessions.news_window_start(at(now)) == at(start) and sessions.news_window_hours(at(now)) == h, now
assert "2026-11-26" in config.NYSE_HOLIDAYS
assert sessions.news_window_hours(at("2026-11-03T06:38"), min_hours=config.CRYPTO_NEWS_HOURS) == 30 and sessions.news_window_hours(at("2026-11-02T06:38"), min_hours=30) == 72.13
print("  ✓ пн 02.11 → от пт 30.10 06:30 UTC (72 ч); вт 03.11 → 24 ч; пт 27.11 след празника → 48 ч; пн 26.10 (смяна на часа) → 73 ч; крипто — не по-малко от 30 ч")

print()
print("── 2. Google News: „when:3d“ не стига до петъка (РЕАЛНИТЕ отговори от 02.11); заявките по дни стигат ──")
fx = lambda url, since=SINCE: before(na._fetch_rss(url, "Reuters Business", 0, limit=100, since_ts=since.timestamp()), at("2026-11-02T23:59"))
r24, r3d = na._fetch_rss(R, "x", 24 * 365, limit=100), na._fetch_rss(R.replace("when:24h", "when:3d"), "x", 24 * 365, limit=100)
assert len(r24) == len(r3d) == 100 and len(titles(r24) & titles(r3d)) >= 99 and min(r["published"] for r in r24) == min(r["published"] for r in r3d) > "2026-11-01"   # Reuters: същите 100 (свалени през 1 s — 1 ново), нито едно от петък
a3d = na._fetch_rss(A.replace("when:24h", "when:3d"), "x", 24 * 365, limit=100)
fri = lambda rows: [r for r in rows if r["published"].startswith("2026-10-30")]
assert len(fri(a3d)) > 0                                                                                                      # AP: извадка от трите дни
days = na.google_day_urls(R, SINCE, T)
assert [d for d, _ in days] == ["2026-10-30", "2026-10-31", "2026-11-01"] and all("when:" not in u for _, u in days)
assert days[0][1] == "https://news.google.com/rss/search?q=after:2026-10-30+before:2026-10-31+site:reuters.com&hl=en-US&gl=US&ceid=US:en"
assert na.google_day_urls(R, at("2026-11-02T06:30"), at("2026-11-03T06:37")) == [] and na.google_day_urls(config.NEWS_RSS_FEEDS["CNBC"], SINCE, T) == []
rfri = fri(na._fetch_rss(days[0][1], "Reuters Business", 0, limit=config.NEWS_PER_SOURCE_LIMIT, since_ts=SINCE.timestamp()))
assert len(rfri) == 40 and {"Intel on course for worst day ever, triggers global chip rout - Reuters",
                            "October ends with a thud for Intel, Reddit, AI stalwarts - Reuters"} <= titles(rfri)
print(f"  ✓ Reuters „when:3d“ = „when:24h“ (100 заглавия, най-старото {min(r['published'] for r in r3d)}); AP „when:3d“ — {len(fri(a3d))} от петък (извадка)")
print(f"  ✓ заявките по дни: 30.10 / 31.10 / 01.11; Reuters за 30.10 — {len(rfri)} петъчни заглавия в първите {config.NEWS_PER_SOURCE_LIMIT}, вкл. „Intel on course for worst day ever …“")
print("  ✓ вторник (24 ч) и CNBC (не е Google News) — без заявки по дни")

print()
print("── 3. gather_raw(since): основните фийдове + дните, обхватът по източник и бележката под новините ──")
real_now = na.dt.datetime
class _FixedNow(dt.datetime):                                                         # СИНТЕТИЧНО: „сега“ = 06:37 UTC на 02.11
    @classmethod
    def now(cls, tz=None):
        return T if tz else T.replace(tzinfo=None)
na.dt.datetime = _FixedNow
try:
    with q() as log:
        raw = na.gather_raw(hours=24, since=SINCE)
finally:
    na.dt.datetime = real_now
w = na.LAST_WINDOW
assert w["day_queries"] == 6 and w["hours"] == 72.12 and w["since"] == SINCE.isoformat()
assert all(r["published"] >= "2026-10-30T06:30Z" for r in raw if r.get("published"))
src = w["sources"]
assert set(src) == {"Reuters Business", "CNBC", "Financial Times", "AP Business"} and src["Reuters Business"]["oldest"].startswith("2026-10-30")
assert src["Financial Times"]["oldest"] > "2026-11-02"                                                                      # FT държи ~12 заглавия — не стига до началото
assert "[news] прозорец: от 30.10 06:30 UTC (72.12 ч), заявки по дни: 6; обхват — Reuters Business" in log.getvalue()
note = render.news_window_note({**w, "hours": 72.13})
# 02.11.2026 (прегледът): само източниците, които НЕ стигат до началото (над config.NEWS_REACH_TOLERANCE_MIN — от 03.11 60 мин); всички стигат → само „Прозорец: 72 ч (от предишния бриф)“
assert config.NEWS_REACH_TOLERANCE_MIN == 60
assert note == ("Прозорец: 72 ч (от предишния бриф, пт 30.10 06:30 UTC). Не стигат до началото му: Reuters Business — до пт 30.10 08:46 · CNBC — до пт 30.10 20:20 · "
                f"Financial Times — до {render._utc_short(src['Financial Times']['oldest'])}."), note    # Reuters 2 ч 16 мин след началото; AP — 36 мин (под 1 ч) не се изброява
reach = {k: {**v, "oldest": "2026-10-30T06:40Z"} for k, v in src.items()}                                                   # СИНТЕТИЧНО: всички стигат (10 мин след началото)
assert render.news_window_note({**w, "hours": 72.13, "sources": reach}) == "Прозорец: 72 ч (от предишния бриф)"
reach.pop("Financial Times")                                                                                                 # СИНТЕТИЧНО: FT без нито едно заглавие
assert render.news_window_note({**w, "hours": 72.13, "sources": reach}).endswith("Не стигат до началото му: Financial Times — без заглавия в прозореца.")
print(f"  ✓ {len(raw)} заглавия от петък 06:30 нататък, 6 заявки по дни; обхват: " + " · ".join(f"{k} {v['count']} (до {v['oldest']})" for k, v in src.items()))
print(f"  ✓ бележката: „{note[:150]}…“")

print()
print("── 4. significant_news(since): таванът към филтъра — 100 на 24 ч (понеделник 300); без since — както до 02.11 ──")
prompts = []
ai_brief._call_claude = lambda system, user, **k: (prompts.append(user), json.dumps({"news": []}))[1]           # СИНТЕТИЧНО: отговорът на AI
_real_gather = na.gather_raw                                                                                     # 04.11.2026: подмяна на gather_raw вместо мемото
na.gather_raw = lambda hours=24, since=None: [{"source": "Reuters Business", "title": f"СИНТЕТИЧНО заглавие {i}", "summary": "", "published": "2026-10-31T10:00Z"} for i in range(350)]
na.dt.datetime = _FixedNow
try:
    with q():
        na.significant_news(since=SINCE)
finally:
    na.dt.datetime = real_now
compact = json.loads(prompts[-1].split("НОВИНИ:\n", 1)[1].split("\n\n", 1)[0])
assert len(compact) == 300
assert str(na._CACHE).startswith(_tmp.name); na._CACHE.unlink()                                                  # кешът за деня (във временната директория) — иначе вторият път е от кеша
na.gather_raw = lambda hours=24, since=None: [{"source": "CNBC", "title": f"СИНТЕТИЧНО {i}", "summary": ""} for i in range(350)]
with q():
    na.significant_news()
assert len(json.loads(prompts[-1].split("НОВИНИ:\n", 1)[1].split("\n\n", 1)[0])) == config.NEWS_MAX_TO_FILTER == 100
na.gather_raw = _real_gather
print("  ✓ 350 заглавия в 72-часов прозорец → 300 към филтъра; без since → 100 (както до 02.11)")

print()
print("── 5. наблюдаваните и крипто получават прозореца; заглавията на разделите ──")
seen = {}
wm._recent_news = lambda t, h, keys=None: (seen.__setitem__(t, h), [])[1]                                   # СИНТЕТИЧНО
wm.insider_buying.fetch_insider_transactions = lambda ts: {}
with q():
    wm.collect(["TDOC"], facts_fn=lambda ts: {t: {"name": "Teladoc Health, Inc."} for t in ts}, window_hours=72.13)
    wm.collect(["SAP"], facts_fn=lambda ts: {t: {"name": "SAP SE"} for t in ts})
assert seen == {"TDOC": 72.13, "SAP": config.WATCH_NEWS_WINDOW_HOURS}
got = {}
na_fetch = na._fetch_rss
na._fetch_rss = lambda url, src, hours, limit=15, since_ts=None: (got.__setitem__(src, hours), [])[1]                 # СИНТЕТИЧНО
try:
    with q():
        crypto_news.fetch_pool(72.13)
    assert set(got.values()) == {72.13}
    with q():
        crypto_news.fetch_pool()
    assert set(got.values()) == {config.CRYPTO_NEWS_HOURS}
finally:
    na._fetch_rss = na_fetch
up = []
ai_brief._call_claude = lambda system, user, **k: (up.append(user), '{"tickers": []}')[1]                        # СИНТЕТИЧНО
with q():
    ai_brief._watch_digest_batch([{"ticker": "TDOC", "name": "Teladoc", "facts": {}, "news": [], "insider": [], "insider_cluster": False}], {}, 72.13)
assert "НАБЛЮДАВАНИ ТИКЪРИ (данни за последните 72 часа — от предишния бриф):" in up[-1]
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
for s in ("news_aggregator.significant_news(since=news_since)", "crypto_news.build(today, hours=crypto_hours)", "watch_monitor.collect(window_hours=news_hours)",
          "watch_ticker_digest(active, market_context, window_hours=news_hours)", '"news_window": {**dict(news_aggregator.LAST_WINDOW)'):
    assert s in main_src, s
b = copy.deepcopy(B19)
b["news"] = b.get("news") or [{"headline": "СИНТЕТИЧНО заглавие", "source": "Reuters Business", "why": "СИНТЕТИЧНО"}]
b["crypto"] = {"ok": True, "items": [], "pool": 0}
b["watch"] = b.get("watch") or []
txt = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
with q():
    old = txt(render.render_dashboard(copy.deepcopy(b), publish=False))
    b["news_window"] = {**w, "hours": 72.13, "crypto_hours": 72.13}
    new = txt(render.render_dashboard(copy.deepcopy(b), publish=False))
assert "Значими новини · последните 24ч" in old and "Крипто · последните 24ч" in old and "Прозорец:" not in old              # стар бриф — както беше
assert "Значими новини · последните 72ч" in new and "Крипто · последните 72ч" in new and "Прозорец: 72 ч (от предишния бриф, пт 30.10 06:30 UTC). Не стигат до началото му: Reuters Business — до пт 30.10 08:46" in new
b["news_window"] = {**w, "since": "2026-11-02T06:30:00+00:00", "hours": 24.13, "crypto_hours": 30}
with q():
    tue = txt(render.render_dashboard(copy.deepcopy(b), publish=False))
assert "Значими новини · последните 24ч" in tue and "Крипто · последните 30ч" in tue
print("  ✓ наблюдаваните — 72.13 ч от main (без него — config 24); крипто — 72.13 / 30; промптът на наблюдаваните — „последните 72 часа — от предишния бриф“")
print("  ✓ заглавията: понеделник „последните 72ч“, вторник 24ч (крипто 30ч); стар бриф без прозорец — „24ч“, без бележка")
print("\n✅ test_news_window: всичко мина")
