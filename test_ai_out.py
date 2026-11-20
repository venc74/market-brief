"""
20.11.2026 (пакет 20.11, т. 1): AI текстът излиза от брифа.
  • Макрото — шаблон от кода (src/macro_template.py): SPY / QQQ, секторите нагоре / надолу и водещите / най-слабите по таблицата, VIX, 10Y. ENABLE_AI_MACRO=0.
  • Новините и крипто — без AI „защо“ (NEWS_AI_WHY=0): AI само избира по индекс; всяка новина — оригиналното заглавие, преводът под него, източник, час, наши тикъри.
  • Преводът (src/translate.py) — AI само превежда; кодът проверява числата (900,000 = 900 000), мащаба (trillion → трлн), тикърите и имената; липсва → оригиналът с бележка
    „преводът е пропуснат — несъответствие (липсва: …)“.

РЕАЛНО: tests/fixtures/ai_out_2026-11-20.json — данните, новините и пулът от брифа на 20.11. СИНТЕТИЧНО (означено): преводите (написани за теста — в брифа ги прави API-то),
отговорът на AI за подбора, грешните преводи.
Пускане: python test_ai_out.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_aiout_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
config.NEWS_AI_WHY, config.ENABLE_AI_MACRO, config.NEWS_TRANSLATE = 0, 0, 1
from src import macro_template as mt, translate as tr, top_themes as tt, news_aggregator as na, ai_brief, render

FX = json.loads((ROOT / "tests" / "fixtures" / "ai_out_2026-11-20.json").read_text(encoding="utf-8"))
CAPS = tt._later_caps([p[2] for p in FX["pool"]])
BG = {                                                                                     # СИНТЕТИЧНО: преводите — написани за теста
    "Trump says he and China's Xi want moderate AI rules - Reuters": "Trump: той и Xi от Китай искат умерени правила за AI",
    "California attorney general issues Nvidia subpoena in probe of China chip diversion": "Главният прокурор на Калифорния издаде призовка на Nvidia в разследване за пренасочване на чипове към Китай",
    "US signed off on sales of nearly 900,000 AI chips to China in six months, House committee says - Reuters": "САЩ са одобрили продажбата на близо 900 000 AI чипа на Китай за шест месеца, твърди комисия на Камарата на представителите",
    "Anthropic IPO takeaways: ANT debuts with $1.8 trillion market cap in landmark moment for AI": "Изводи от IPO-то на Anthropic: ANT дебютира с пазарна капитализация от $1,8 трлн в повратен момент за AI",
    "Gold set for worst week in eight months as firm dollar, Fed hike bets weigh - Reuters": "Златото е към най-лошата си седмица от осем месеца при силен долар и залози за повишение от Fed",
    "Oil prices gain as Houthi attacks on Riyadh raise supply concerns - Reuters": "Петролът поскъпва, след като атаки на хусити срещу Рияд засилват опасенията за доставките",
    "US Senate passes bipartisan bill to speed energy, infrastructure projects - Reuters": "Сенатът на САЩ прие двупартиен закон за ускоряване на енергийни и инфраструктурни проекти",
}

print("── 1. РЕАЛНО: шаблонът на макрото от числата на 20.11 ──")
m = mt.macro_brief(FX["market_day"], FX["sector_board"], FX["macro"])
assert m["macro_brief"] == ("На 19.11 SPY -1.96%, QQQ -2.19% за сесията; SPY е 8.1% под 52-седм. връх, QQQ е 15.1% под 52-седм. връх. "
                            "Секторите: нагоре 0 от 11, надолу 11; по таблицата водят XLP (RS 4 седм. +6.6, днес -1.4%) и XLU (RS 4 седм. +7.1, днес -1.2%), "
                            "най-слаби са XLK (-6.0, днес -1.9%) и XLE (-3.8, днес -0.7%). VIX 28.44 (+15.8% за сесията) и 10-годишната доходност 5.05% (-5.1 б.п. за 5 сесии)."), m
assert m["source"] == "code" and m["sentences"] == 3 and mt.macro_brief({}, {}, {})["macro_brief"] == ""
print(f"  ✓ «{m['macro_brief'][:90]}…»")

print("── 2. проверката на превода: заглавията от 20.11 (РЕАЛНИ), преводите (СИНТЕТИЧНИ) ──")
for n in FX["news"]:
    assert tr.problems(n["headline"], BG[n["headline"]], CAPS) == [], (n["headline"], tr.problems(n["headline"], BG[n["headline"]], CAPS))
H900 = "US signed off on sales of nearly 900,000 AI chips to China in six months, House committee says - Reuters"
assert tr.problems(H900, "САЩ са одобрили продажбата на близо 90 000 AI чипа на Китай за шест месеца, твърди комисия на Камарата", CAPS) == ["900000"]
assert tr.problems(H900, "САЩ одобриха продажба на AI чипове на Китай, твърди комисия", CAPS) == ["900000", "HOUSE"]
assert tr.problems("Anthropic IPO takeaways: ANT debuts with $1.8 trillion market cap in landmark moment for AI",
                   "Изводи от IPO-то: дебют с пазарна капитализация от $1,8 в повратен момент за AI", CAPS) == ["trillion", "ANTHROPIC", "ANT"]
print("  ✓ 7 от 7 приети (вкл. „nearly 900,000“ → „близо 900 000“); „90 000“ → липсва 900000; без мащаба / имената → изброени")

print("── 3. новините без AI „защо“: подборът по индекс, преводът, нашите тикъри (СИНТЕТИЧНИ отговори на AI) ──")
pool_titles = [p[2] for p in FX["pool"]]
raw = [{"source": p[0], "published": p[1], "title": p[2], "summary": ""} for p in FX["pool"]]
sel = [{"i": pool_titles.index(n["headline"]), "h": " ".join(n["headline"].split()[:6])} for n in FX["news"] if n["headline"] in pool_titles]
def fake_call(system, user, **k):
    if system == tr.SYSTEM:
        items = json.loads(user.split("ЗАГЛАВИЯ:\n", 1)[1])
        return json.dumps({"bg": [BG.get(next((h for h in BG if tr._SUFFIX.sub("", h) == x["t"]), ""), "") for x in items]}, ensure_ascii=False)
    assert "why" not in user.split("НОВИНИ:", 1)[1][-400:]                                              # JSON форматът е без „why“
    return json.dumps({"news": sel}, ensure_ascii=False)
def fake_gather(hours=24, since=None, **k):
    na.LAST_FRONT.clear(); na.LAST_WINDOW.clear(); na.LAST_WINDOW.update(sources={})
    return list(raw)
orig = (na.gather_raw, ai_brief._call_claude)
na.gather_raw, ai_brief._call_claude = fake_gather, fake_call
try:
    with contextlib.redirect_stdout(io.StringIO()):
        got = na.significant_news(max_items=8, priority=[{"ticker": "NVDA", "name": "NVIDIA Corporation"}])
finally:
    na.gather_raw, ai_brief._call_claude = orig
assert len(got) == len(sel) and all(not r["why"] for r in got) and all(r.get("headline_bg") == BG[r["headline"]] for r in got)
nv = next(r for r in got if r["headline"].startswith("California attorney general issues Nvidia"))
assert nv["ours"] == ["NVDA"] and nv.get("published") and na.LAST_DIAG["translation"]["ok"] == len(sel)
print(f"  ✓ {len(got)} новини, без „защо“, всичките с превод; Nvidia → наши тикъри: NVDA")

print("── 4. страницата и имейлът ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B); b["news"] = got; b["ai_macro"] = m
bad = copy.deepcopy(got[0]); bad.pop("headline_bg"); bad["translation_note"] = "преводът е пропуснат — несъответствие (липсва: 900000)"; b["news"].append(bad)
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False); mail = render.render_email(b)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
assert "САЩ са одобрили продажбата на близо 900 000 AI чипа на Китай" in txt and "наши тикъри: NVDA" in txt and "наши тикъри: няма" in txt
assert "преводът е пропуснат — несъответствие (липсва: 900000)" in txt and "На 19.11 SPY -1.96%, QQQ -2.19% за сесията" in txt
assert "САЩ са одобрили продажбата на близо 900 000 AI чипа" in mail and "наши тикъри: NVDA" in mail
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "if config.ENABLE_AI_MACRO else macro_template.macro_brief(market_day, sector_board, macro)" in src
print("  ✓ преводът под заглавието, бележката при несъответствие, източник · час · наши тикъри; макрото — от кода")
print("\n✅ test_ai_out: всичко мина")
