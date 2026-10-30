"""
29.10.2026 · разходката, т. 6 (Наблюдавани тикъри), решения 1–4:
  1. data/watch_list.json — 14 тикъра, без етикети за позиция (брифът е публичен; тестовете не четат data/ — списъкът е проверен на ръка);
  2. ред с факти от кода (без AI): цена и промяна за деня, над/под 50DMA и 200DMA, RS спрямо SPY за 4 и 12 седмици, следващ отчет, short interest (% от float, дни за
     покриване, промяна спрямо предишното отчитане и ДАТАТА на отчитането), маркер, ако е и в наш скрийнър / книга;
  3. една таблица (ред на тикър); новините, Form 4 и AI резюмето се разгъват с клик под реда (<details>); тикър без събития — само редът; празен списък — един ред;
  4. новините — от RSS на Yahoo по тикър (yfinance .news връща нищо — 0 и за AAPL на 29.10), само за компанията: при "AI" фийдът носи и SoundHound, BigBear.ai, Palantir —
     минават само тези за C3.ai.

РЕАЛНО: tests/fixtures/watch_yahoo_rss_<тикър>_2026-10-29.xml — RSS на Yahoo Finance за 14-те тикъра, свалени на 29.10.2026 в 18:49 UTC;
tests/fixtures/watch_facts_2026-10-29.json — затварянията (1 година, 14 тикъра + SPY), Yahoo .info (short interest, име), следващите отчети, Form 4 и маркерите от брифа на 29.10;
tests/fixtures/brief_2026-10-19.json — рамката на страницата.
30.10.2026 (т. 7): мъртвата зона ±1 пункт в думите (т. 6) — РЕАЛНО: tests/fixtures/watch_brief_2026-10-30.json (14-те реда от 30.10) и XLI +0.18 / −8.51 от 30.10.
СИНТЕТИЧНО (означено): подмененият requests.get (връща fixture-а), часът на прозореца за новините (широк), празният списък в т. 5, стойностите по клетка и TDOC +0.4 в т. 6.
Пускане: python test_watch_table.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_watch_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import watch_monitor as wm, render

FXD = ROOT / "tests" / "fixtures"
FX = json.loads((FXD / "watch_facts_2026-10-29.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
T = ["TDOC", "BHC", "SAP", "BLSH", "CRCL", "AI", "CRBG", "BFLY", "ELF", "DOCU", "SN", "CRM", "BMNR", "ACN"]
q = lambda: contextlib.redirect_stdout(io.StringIO())
rss = lambda t: (FXD / f"watch_yahoo_rss_{t}_2026-10-29.xml").read_bytes()

print("── 1. новините за компанията (РЕАЛНИТЕ фийдове, всички заглавия) — „AI“ е C3.ai, не думата ──")
kept = total = 0
for t in T:
    keys = wm.company_keys(FX["info"][t]["longName"])
    import feedparser
    for e in feedparser.parse(rss(t)).entries:
        total += 1
        kept += bool(wm.about_company(t, keys, e.title, e.get("summary") or ""))
assert (kept, total) == (171, 262), (kept, total)
config.WATCH_MAX_NEWS_PER_TICKER = 50
ai = wm._rss_news("AI", 24 * 3650, wm.company_keys(FX["info"]["AI"]["longName"]), fetch=lambda url: rss("AI"))                  # СИНТЕТИЧНО: широк прозорец
titles = [n["title"] for n in ai]
assert len(ai) == 13 and all("C3.ai" in n["title"] + n["summary"] or "(AI)" in n["title"] + n["summary"] or "NYSE:AI" in n["summary"] for n in ai)
for other in ("How Long Can SoundHound Keep Burning Cash?", "Can BigBear.ai Ride the Next Wave of Defense Technology?", "3 unpopular stocks that concern us",
              "Is Palantir's AIP Platform Fueling Explosive U.S. Commercial Growth?"):
    assert other not in titles
assert "Wall Street Split On Robinhood Ahead Of Earnings – Wells Fargo Cuts HOOD, BLSH Targets" in [n["title"] for n in wm._rss_news("BLSH", 24 * 3650, {"Bullish"}, fetch=lambda u: rss("BLSH"))]
assert all(n["link"].startswith("https://") for n in ai)
print(f"  ✓ {kept} от {total} заглавия минават; „AI“ — 13 от 20, всички за C3.ai (SoundHound, BigBear.ai, Palantir, „3 unpopular stocks“ — отпадат); „BLSH“ като тикър в заглавието — минава")

print()
print("── 2. фактите от кода (РЕАЛНИТЕ затваряния и .info) ──")
cl = {t: pd.Series(list(v.values()), index=pd.to_datetime(list(v.keys()))) for t, v in FX["closes"].items()}
for t in T:
    got = wm.price_facts(cl[t], cl["SPY"])
    assert {k: v for k, v in got.items() if not k.startswith("rs")} == {k: v for k, v in FX["expected_price"][t].items() if not k.startswith("rs")}, t
    for n in (20, 60):                                                                                     # 30.10.2026: RS = ръстът на акцията минус ръстът на SPY (пунктове)
        r = cl[t].iloc[-1] / cl[t].iloc[-1 - n] - 1; rs = cl["SPY"].iloc[-1] / cl["SPY"].iloc[-1 - n] - 1
        assert got[f"rs_{n}"] == round((r - rs) * 100, 1), (t, n)
tdoc = wm.price_facts(cl["TDOC"], cl["SPY"])
assert tdoc["date"] == "2026-10-28" and tdoc["close"] == 6.88 and tdoc["chg_1d_pct"] == 6.67 and tdoc["above_50"] and tdoc["above_200"] and (tdoc["rs_20"], tdoc["rs_60"], tdoc["rs_word"]) == (17.4, 2.4, "води пазара")
sh = wm.short_facts(FX["info"]["TDOC"])
assert sh == {"pct_float": 17.7, "days_to_cover": 8.8, "chg_pct": 16.1, "as_of": "2026-10-15", "prior_as_of": "2026-09-15"}, sh            # Yahoo: предишното е отпреди месец (15.09), не 30.09
assert wm.short_facts({}) == {} and wm.price_facts(cl["TDOC"].iloc[-30:], None).get("above_200") is None                             # кратка история — без 200DMA
print(f"  ✓ TDOC: $6.88 +6.67% (28.10), над 50 и 200DMA, RS спрямо S&P +17.4 / +2.4 пункта — „води пазара“; short 17.7% · 8.8 дни · +16.1% спрямо 15.09 · към 15.10")

print()
print("── 3. collect() → таблицата: ред на тикър, разгъване при събития, маркерите ──")
def facts_fn(tickers):
    out = {}
    for t in tickers:
        out[t] = {"name": FX["info"][t]["longName"], "price": wm.price_facts(cl[t], cl["SPY"]), "short": wm.short_facts(FX["info"][t]), "earnings": FX["earnings"][t]}
    return out
wm.insider_buying.fetch_insider_transactions = lambda ts: {t: [{**x, "date": pd.Timestamp(x["date"]).date()} for x in FX["insider"].get(t, [])] for t in ts}
wm.requests.get = lambda url, timeout=None, headers=None: type("R", (), {"content": rss(re.search(r"s=([A-Z]+)", url).group(1))})()     # СИНТЕТИЧНО: мрежата → РЕАЛНИЯТ фийд
config.WATCH_NEWS_WINDOW_HOURS = 24 * 3650                                                                                          # СИНТЕТИЧНО: широк прозорец
config.WATCH_MAX_NEWS_PER_TICKER = 6
with q():
    rows = wm.collect(T, facts_fn=facts_fn)
books = {"qm_breakout": [{"ticker": "ELF"}, {"ticker": "DOCU"}]}                                                        # РЕАЛНО: отворените записи в книгата QM на 29.10 (сред 14-те)
wm.attach_markers(rows, {"Action": [], "Watchlist": [], "QM": [{"ticker": "ELF"}], "GLB": [], "EP": []}, books=True,                   # РЕАЛНО: QM картите на 29.10 — сред 14-те само ELF
                  book_records=lambda cat, statuses=None: books.get(cat, []))
marks = {r["ticker"]: r["in_brief"] for r in rows}
assert marks["ELF"] == FX["markers"]["ELF"] and marks["DOCU"] == FX["markers"]["DOCU"] and marks["TDOC"] == []
bad = [{"ticker": "X"}]
with q():
    wm.attach_markers(bad, {"QM": None}, books=True, book_records=lambda *a, **k: 1 / 0)                                           # СИНТЕТИЧНО: повреда → без маркери
assert "in_brief" not in bad[0]
b = copy.deepcopy(B19); b["watch"] = rows
with q():
    page = render.render_dashboard(b, publish=False)
sec = page[page.index("<h2>🔎 Наблюдавани тикъри"):]; sec = sec[:sec.index("</section>")]
assert sec.count('<div class="wt-row wt-head">') == 1 and sec.count('<span class="wt-t">') == 14
assert sec.count('<details class="wt-item">') == sum(1 for r in rows if not r["quiet"]) and sec.count('<div class="wt-row wt-plain">') == sum(1 for r in rows if r["quiet"])
t_tdoc = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", sec[sec.index('<span class="wt-t">TDOC'):sec.index("</details>", sec.index('<span class="wt-t">TDOC'))])))
assert "TDOC Teladoc Health, Inc. $6.88 +6.7% над / над +17.4 / +2.4 води пазара 24.02 (след 118 дни) 17.7% от float · 8.8 дни · +16.1% спрямо 15.09 · към 15.10" in t_tdoc, t_tdoc[:300]
assert "Catapano Joseph Ronald" in t_tdoc and "Teladoc" in t_tdoc
elf = sec[sec.index('<span class="wt-t">ELF'):]; elf = elf[:elf.index("</summary>")]
assert '<span class="wt-mark">QM</span><span class="wt-mark">книга QM</span>' in elf
print(f"  ✓ 14 реда; {sum(1 for r in rows if not r['quiet'])} се разгъват (новини / Form 4), {sum(1 for r in rows if r['quiet'])} — само редът; ELF: QM · книга QM; DOCU: книга QM")
config.WATCH_NEWS_WINDOW_HOURS = 1                                                                                                  # СИНТЕТИЧНО: прозорец без новини → тикърите без Form 4 са „тихи“
with q():
    rows1 = wm.collect(T, facts_fn=facts_fn)
quiet = [r["ticker"] for r in rows1 if r["quiet"]]
b = copy.deepcopy(B19); b["watch"] = rows1
with q():
    page1 = render.render_dashboard(b, publish=False)
sec1 = page1[page1.index("<h2>🔎 Наблюдавани тикъри"):]; sec1 = sec1[:sec1.index("</section>")]
assert quiet and sec1.count('<div class="wt-row wt-plain">') == len(quiet) and sec1.count('<details class="wt-item">') == 14 - len(quiet)
assert "Няма значими събития" not in sec1                                                                                            # тих тикър — само редът, без текст под него
print(f"  ✓ тихите ({', '.join(quiet)}) — само редът, без разгъване")

print()
print("── 4. празен списък — един ред, както досега (СИНТЕТИЧНО) ──")
b = copy.deepcopy(B19); b["watch"] = []
with q():
    page = render.render_dashboard(b, publish=False)
assert "Списъкът е празен" in page and 'class="wt-row wt-head"' not in page                                                # без празна таблица — само редът
print("  ✓ „Списъкът е празен …“")

print()
print("── 5. RS: думата от кода и бележката под таблицата (30.10.2026) ──")
assert [wm.rs_word(a, b) for a, b in ((2, 2), (2, -2), (-2, 2), (-2, -2))] == ["води пазара", "набира сила", "отслабва", "изостава"]          # 30.10.2026 (т. 7): извън мъртвата зона
blsh = wm.price_facts(cl["BLSH"], cl["SPY"]); bfly = wm.price_facts(cl["BFLY"], cl["SPY"])
assert (blsh["rs_20"], blsh["rs_60"], blsh["rs_word"]) == (-18.9, 20.6, "отслабва") and bfly["rs_word"] == "изостава"                    # РЕАЛНО (28.10)
assert "RS 4 / 12 седм. — ръстът на акцията минус ръстът на S&amp;P 500 (SPY) за 4 и за 12 седмици" in page1 and "за 4 и за 12 седмици" not in page          # празен списък — без бележката
print("  ✓ BLSH −18.9 / +20.6 → „отслабва“, BFLY → „изостава“; бележката под таблицата")

print()
print("── 6. мъртвата зона ±1 пункт (30.10.2026, т. 7): RS между −1 и +1 е „в крак с пазара“, не плюс / минус ──")
assert config.RS_WORD_DEAD_ZONE == 1.0
table = {(a, b): wm.rs_word(a, b) for a in (3, 0.5, -3) for b in (3, -0.5, -3)}                                                       # СИНТЕТИЧНИ стойности по клетка
assert table == {(3, 3): "води пазара", (3, -0.5): "набира сила", (3, -3): "набира сила",
                 (0.5, 3): "в крак с пазара", (0.5, -0.5): "в крак с пазара", (0.5, -3): "в крак с пазара",
                 (-3, 3): "отслабва", (-3, -0.5): "отслабва", (-3, -3): "изостава"}, table
assert wm.rs_word(1.0, 5) == "в крак с пазара" and wm.rs_word(-1.0, 5) == "в крак с пазара" and wm.rs_word(1.01, 5) == "води пазара"           # границата е в зоната
assert wm.rs_word(0.18, -8.51) == "в крак с пазара"                                                                                     # РЕАЛНО: XLI 30.10 — до т. 7 „набира сила“
assert wm.rs_word(None, 3) is None and [wm.rs_sign(v) for v in (1.5, 1.0, 0, -1.0, -1.5, None)] == [1, 0, 0, 0, -1, None]
print("  ✓ 4 седм. решават посоката, 12 — дали е трайно; ±1 (вкл.) → „в крак с пазара“; XLI +0.2 / −8.5 (РЕАЛНО, 30.10) → „в крак с пазара“")
W30 = json.loads((FXD / "watch_brief_2026-10-30.json").read_text(encoding="utf-8"))["watch"]
old_rule = lambda a, b: {(True, True): "води пазара", (True, False): "набира сила", (False, True): "отслабва", (False, False): "изостава"}[(a > 0, b > 0)]
pr = [r["facts"]["price"] for r in W30]
assert len(pr) == 14 and all(wm.rs_word(x["rs_20"], x["rs_60"]) == old_rule(x["rs_20"], x["rs_60"]) for x in pr)
print("  ✓ РЕАЛНИТЕ 14 наблюдавани тикъра от 30.10 — думата не се сменя при нито един (RS им е далеч от ±1)")
b = copy.deepcopy(B19); rows = copy.deepcopy(W30)
rows[0]["facts"]["price"].update({"rs_20": 0.4, "rs_word": wm.rs_word(0.4, 26.0)})                                                       # СИНТЕТИЧНО: TDOC +0.4 за 4 седм.
b["watch"] = rows
with q():
    page = render.render_dashboard(b, publish=False)
assert '<span class="wt-mu">+0.4</span>' in page and "в крак с пазара" in page and "„в крак с пазара“ — за 4 седмици в рамките на ±1 пункт" in page
print("  ✓ на страницата: +0.4 — сиво, думата „в крак с пазара“; бележката обяснява зоната")
print("\n✅ test_watch_table: всичко мина")
