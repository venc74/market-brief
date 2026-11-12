"""
10.11.2026 (т. 3): в карето в 15:05 — заглавия за икономически данни (CPI, PPI, заетост, JOLTS, ISM, retail sales) от нашите фийдове след 08:30 Ню Йорк,
до 3, дословно, с източник и час. Без AI. Реално: 10.11 — CPI за октомври в 08:30 Ню Йорк; в 09:08 (часът на карето) фийдовете имат 5 такива заглавия.

РЕАЛНО: tests/fixtures/econ_rss_{reuters,ap,cnbc,ft}_2026-11-10.xml.gz — четирите фийда от config.NEWS_RSS_FEEDS, изтеглени 10.11.2026 в 16:03 Берлин
(Reuters и AP през Google News, по 100 записа; CNBC 30; FT 12); tests/fixtures/ep_aaon_sanm_2026-11-10.json (карето от 10.11), brief_2026-10-19.json (рамката).
СИНТЕТИЧНО (означено): т. 2 — кратки заглавия за границите на филтъра (истинските заглавия от измерването 01.10–10.11 са в т. 2а).
Пускане: python test_preopen_econ.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, types, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_econ_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import news_aggregator, preopen, render

FXD = ROOT / "tests" / "fixtures"
NAMES = {"Reuters Business": "reuters", "CNBC": "cnbc", "Financial Times": "ft", "AP Business": "ap"}
RAW = {config.NEWS_RSS_FEEDS[s]: gzip.decompress((FXD / f"econ_rss_{n}_2026-11-10.xml.gz").read_bytes()) for s, n in NAMES.items()}
news_aggregator.requests.get = lambda url, **k: types.SimpleNamespace(content=RAW[url])
FX = json.loads((FXD / "ep_aaon_sanm_2026-11-10.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
NOW = dt.datetime(2026, 11, 10, 14, 8, tzinfo=dt.timezone.utc)                     # 09:08 Ню Йорк = 15:08 Берлин — часът на карето от 10.11

print("── 1. РЕАЛНО: 10.11, 09:08 Ню Йорк — първите три заглавия за CPI ──")
with contextlib.redirect_stdout(io.StringIO()):
    got = preopen.fetch_econ(NOW)
assert got["feeds"] == 4 and got["feeds_empty"] == []
rows, err = preopen.econ_block(got, NOW)
assert err is None
L = [preopen.econ_line(x) for x in rows]
assert L == ["„Inflation ran hotter than expected last month, underscoring affordability challenges“ · AP News · 08:41 Ню Йорк (14:41 Берлин)",
             "„US consumer prices rise above expectations in October“ · Reuters · 08:46 Ню Йорк (14:46 Берлин)",
             "„S&P 500 futures fall sharply after October inflation data“ · Reuters · 08:47 Ню Йорк (14:47 Берлин)"], L
assert all(x["kind"] == "CPI" for x in rows) and all(x.get("link") for x in rows)
allr = preopen.econ_headlines(got["items"], NOW, max_n=10)
assert [x["source"] for x in allr] == ["AP News", "Reuters", "Reuters", "Financial Times", "Reuters"]       # FT 08:58 и Reuters 09:07 — след третото
assert "Consumer prices rose 0.4% in October" not in " ".join(x["title"] for x in allr)                    # CNBC 09:50 — след часа на карето
print("  ✓ " + "\n  ✓ ".join(L))

print("── 2. филтърът ──")
# 2а. РЕАЛНИ заглавия от измерването (Reuters / AP, Google News, 01.10–10.11.2026)
yes = {"US jobless claims fell to 194,000 last week, lowest since July": "заетост",
       "Retail sales up 0.8% in September, but a big chunk of spending went to paying gasoline bills": "retail sales",
       "US job postings jumped sharply in September, potentially a good sign for anyone seeking employment": "JOLTS",
       "US hiring slows and unemployment ticks higher with a month remaining before Americans head to polls": "заетост",
       "Monthly US inflation eased less than expected in October": "CPI"}
no = ["UK inflation rises to highest in almost a year as Iran war drives fuel prices higher", "Netflix cuts about 6% of jobs in biggest layoff since 2022",
      "Federal Reserve keeps rates unchanged despite elevated inflation", "China's factory activity shrinks in October, third contraction in four months",
      "Fed to raise rates once more in December as inflation risks stay high: Reuters poll", "Honda to build new $3 billion auto plant in Ohio, adding 2,000 jobs"]
assert all(preopen.econ_kind(t) == k for t, k in yes.items()) and not any(preopen.econ_kind(t) for t in no)
# 2б. СИНТЕТИЧНО: границите
assert preopen.econ_kind("US PPI rises 0.3%") == "PPI" and preopen.econ_kind("ISM services index slips") == "ISM" and preopen.econ_kind("Canada adds 40,000 jobs; jobless rate 6.5%") is None
assert preopen.econ_kind("Canadian dollar slips as US payrolls beat") == "заетост" and preopen.econ_kind(None) is None
print(f"  ✓ {len(yes)} реални „да“, {len(no)} реални „не“ (чужди данни, съкращения, коментари за инфлацията)")

print("── 3. прозорецът и провалът ──")
assert preopen.econ_since(NOW).strftime("%H:%M") == "13:30"                                                 # 08:30 Ню Йорк = 13:30 UTC (14:30 Берлин)
early = dt.datetime(2026, 11, 10, 13, 40, tzinfo=dt.timezone.utc)                                          # 08:40 Ню Йорк — още нищо (първото е AP в 08:41)
assert preopen.econ_headlines(got["items"], early) == []
e2 = preopen.econ_block({"items": [], "feeds": 4, "feeds_empty": list(NAMES)}, NOW)
assert e2 == ([], "нито един от 4 фийда не върна заглавия след 08:30 Ню Йорк")
assert preopen.econ_block({"items": [], "feeds": 4, "feeds_empty": ["CNBC"]}, NOW) == ([], None)           # тих прозорец — без бележка
print("  ✓ от 08:30 Ню Йорк до часа на карето; всички фийдове празни → „не се провериха“")

print("── 4. run(), карето и имейлът ──")
fr = {}
with contextlib.redirect_stdout(io.StringIO()):
    res = preopen.run(NOW, frames5=fr, brief={}, records=[], watched=[], universe=[], econ_fn=preopen.fetch_econ)
    res0 = preopen.run(NOW, frames5=fr, brief={}, records=[], watched=[], universe=[])
    resx = preopen.run(NOW, frames5=fr, brief={}, records=[], watched=[], universe=[], econ_fn=lambda now: 1 / 0)
assert [x["title"] for x in res["econ"]] == [x["title"] for x in rows] and preopen.has_news(res)
assert "econ" not in res0 and resx["econ"] == [] and resx["econ_error"] == "ZeroDivisionError"
src = (ROOT / "src" / "preopen.py").read_text(encoding="utf-8")
assert "universe_note=universe_note, econ_fn=fetch_econ, exclude=_pending_deals()," in src                                           # main() тегли фийдовете (12.11: + market_fn / weights_fn)
day = {**FX["preopen"], "econ": rows}
mail = preopen.email_html(day)
assert "Икономически данни след 08:30 Ню Йорк" in mail and all(l.replace("„", "&quot;") in mail or __import__("html").escape(l) in mail for l in L)
assert mail.index("Икономически данни") < mail.index("EP — гапове")
bb = copy.deepcopy(B19); bb["preopen"] = day
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
assert "Икономически данни след 08:30 Ню Йорк · 3" in page and "„US consumer prices rise above expectations in October“</a>" in page
assert page.index("Икономически данни след") < page.index("EP — гапове")
bb["preopen"] = {**FX["preopen"], "gaps": [], "levels": [], "watch": [], "econ": [], "econ_error": e2[1]}
with contextlib.redirect_stdout(io.StringIO()):
    page2 = render.render_dashboard(bb, publish=False)
assert "Заглавията за икономически данни не се провериха (нито един от 4 фийда" in page2 and "Нищо за отбелязване" not in page2
print("  ✓ run() с fetch_econ / без / с провал; карето (над EP гаповете) и имейлът; провалът — „не се провериха“")
print("\n✅ test_preopen_econ: всичко мина")
