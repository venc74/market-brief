"""
Qullamaggie (07.10.2026) · две секции веднага след Watchlist и преди GLB — "Пробиви по Kullamägi (Breakout)" (банер "Измерване, не препоръка…", до 8 компактни карти по стягане: тикър, компания, вход, стоп и %,
ADR, акции при риск $500, предходен ръст, дни консолидация, QM✓ ако е и в Watchlist) и "Епизодични пивоти (EP) · гапове след новина" (таблица: тикър, AH гап, заглавие на новината, ръст за 3 месеца, стоп и
размер; ред, че проверката е отварянето, и вчерашният дневник AH срещу отваряне); книгата qm_breakout е свита под картите. Същото в имейла (веднага след реда Watchlist). Банери при провал, стар бриф → без секциите.

РЕАЛНО: картите DOCN/CORT/CRL от скана към 02.10.2026 (tests/fixtures/qm_frames_2026-10-02.json); SYNA +15.0% after-hours на 01.10 (5-минутни барове, дневни данни и заглавия от Yahoo, tests/fixtures/qm_ep_2026-10-02.json);
базовият бриф е РЕАЛНИЯТ от 05.10.2026 (tests/fixtures/brief_2026-10-05.json). Диагностиката на скана (903 тикъра, 892 с история, 167 лидери) е РЕАЛНАТА от скана на целия универс към 02.10. СИНТЕТИЧНО: отговорът на AI за катализатора на SYNA (резюме), записите на книгата с резултати (25 затворени за проверка на прага;
реалните записи са 3 чакащи карти без резултат), провалените диагностики и злонамереният текст за escape проверката.
Пускане: python test_qm_render.py
"""
import sys, json, pathlib, tempfile, copy, datetime as dt, html as htmllib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import qm_breakout as q, qm_ep as ep, render, backtest

tmp = tempfile.TemporaryDirectory(prefix="mb_qmr_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(tmp.name) / "docs", pathlib.Path(tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
config.QM_TRACK_FROM = ""                                                                           # guard-ът по дата има собствен тест (test_qm_start_guard.py)

FIX = json.loads((ROOT / "tests" / "fixtures" / "qm_frames_2026-10-02.json").read_text(encoding="utf-8"))
EPF = json.loads((ROOT / "tests" / "fixtures" / "qm_ep_2026-10-02.json").read_text(encoding="utf-8"))
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
frames = {t: pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"])) for t, d in FIX["frames"].items()}
ROWS, DIAG = q.scan_frames(frames, lead=FIX["lead"], max_dist_adr=2.0)  # РЕАЛНАТА карта DOCN от 02.10 е на 1.17 ADR от нивото; с правилото ≤1 ADR (08.10) не е карта — тук пазим и трите реални карти (старото определение ≤2 ADR) за рендера/книгата
CARDS = q.cards(ROWS)
assert [c["ticker"] for c in CARDS] == ["DOCN", "CORT", "CRL"] or sorted(c["ticker"] for c in CARDS) == ["CORT", "CRL", "DOCN"]
US = FIX["universe_scan"]                                                                                         # РЕАЛНИЯТ скан на целия универс към 02.10 (903 тикъра, 892 с история; 167 лидери; кандидати DOCN, CORT, CRL)
assert US["candidates"] == ["DOCN", "CORT", "CRL"] and (US["leaders"], US["with_history"]) == (167, 892)
DIAG = {"universe": 903, "with_history": US["with_history"], "leaders": US["leaders"], "candidates": 3, "shown": 3, "as_of": FIX["as_of"], "lead_pct": config.QM_LEAD_PCT, "ok": True, "batches": 10, "batches_failed": 0}


def m5(t):
    m = EPF["m5"][t]
    df = pd.DataFrame({"Open": m["o"], "High": m["h"], "Low": m["l"], "Close": m["c"], "Volume": m["v"]}, index=pd.DatetimeIndex(pd.to_datetime(m["ts"], utc=True)))
    return df[df.index.tz_convert("America/New_York").date <= dt.date(2026, 10, 1)]


def daily(t):
    d = EPF["daily"][t]
    return pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))


TICKERS = ["SYNA", "VICR", "NKE", "AAPL"]
HL = EPF["headlines"]["SYNA"]
SUMMARY = "ON Semi предлага изцяло парична оферта за Synaptics."                                                   # СИНТЕТИЧНО (отговорът на AI)
ai = lambda system, user: json.dumps({"items": [{"ticker": "SYNA", "catalyst": "m_and_a", "summary_bg": SUMMARY, "surprise": "yes"}]})
EP = ep.run(TICKERS, dt.date(2026, 10, 2), fetch_5m_fn=lambda u: ({t: m5(t) for t in TICKERS}, {"batches": 1, "batches_failed": 0}), fetch_daily_fn=lambda ts: {t: daily(t) for t in ts},
            headlines_fn=lambda t, s: HL, ai_call=ai, name_lookup=lambda t: "Synaptics Inc", log_path=pathlib.Path(tmp.name) / "ep_log.json")
assert [r["ticker"] for r in EP["rows"]] == ["SYNA"] and EP["ok"]

# книгата: РЕАЛНИТЕ карти като чакащи записи на 05.10 (без резултат — още няма сесия)
backtest.config.ENABLE_BACKTEST = True
tr = {}
backtest._ingest_qm_list(tr, "2026-10-05", CARDS, "Defensive")
backtest._save_tracker(tr)
QB3 = backtest.get_qm_summary()
assert QB3["records"] == 3 and QB3["pending"] == 3 and not QB3["stats_visible"]


def brief_with(cards=CARDS, diag=DIAG, ep_out=EP, qb=QB3):
    b = copy.deepcopy(B05)
    b["qm_breakout"], b["qm_diag"], b["qm_ep"] = copy.deepcopy(cards), copy.deepcopy(diag), copy.deepcopy(ep_out)
    b.setdefault("backtest", {})["qm_breakout"] = copy.deepcopy(qb)
    return b


def page_of(b):
    return htmllib.unescape(render.render_dashboard(b))


def section(page):
    i = page.index('<section id="qm">')
    return page[i:page.index("</section>", i)]


def txt_of(raw_html):
    """Видимият текст: първо се махат таговете, СЛЕД това се декодират &lt; / &amp; ("< 97%" не бива да се чете като таг)."""
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", raw_html))).strip()


def page_raw(b):
    return render.render_dashboard(b)


def section(raw, sid="qm"):
    i = raw.index(f'<section id="{sid}">')
    return raw[i:raw.index("</section>", i)]


# РЕАЛНО: вторият EP пуск (бриф от 05.10) разрешава записа на SYNA срещу РЕАЛНОТО отваряне на 02.10 → "вчерашният дневник"
EP2 = ep.run(TICKERS, dt.date(2026, 10, 5), fetch_5m_fn=lambda u: ({t: m5(t) for t in TICKERS}, {"batches": 1, "batches_failed": 0}), fetch_daily_fn=lambda ts: {t: daily(t) for t in ts},
             headlines_fn=lambda t, s: [], ai_call=ai, name_lookup=lambda t: t, log_path=pathlib.Path(tmp.name) / "ep_log.json")
YD = EP2["log"]["yesterday"]
assert [(y["ticker"], y["gap_session"], y["ah_gap_pct"], y["open_gap_pct"], y["held"]) for y in YD] == [("SYNA", "2026-10-02", 14.97, 14.65, True)]
EP_Y = {**EP, "log": EP2["log"]}                                                                                       # редовете на сутрешния бриф от 02.10 + дневникът, разрешен на 05.10


print("── Breakout: секция, позиция, банер, компактни карти (РЕАЛНИ към 02.10.2026) ──")
raw = page_raw(brief_with(ep_out=EP_Y))
sec = section(raw)
txt = txt_of(sec)
assert raw.count("<section") == raw.count("</section>")
SURV = "Измерване, не препоръка. Реплеят е с survivorship (днешният универс) и резултатът зависи от малко големи печалби. Алфата не е статистически значима."
assert "Пробиви по Kullamägi (Breakout)" in txt and txt.index(SURV) < txt.index("DOCN") and "Входът е по opening range high в сесията, стопът — low of day; брифът дава нивата, не самия вход." in txt
assert "Qullamaggie сетъпи" not in txt_of(raw.split("</style>", 1)[1])                                                          # старото заглавие го няма
by = {c["ticker"]: c for c in CARDS}
cards_html = re.findall(r'<div class="qm-card[^"]*">.*?(?=<div class="qm-card|</div>\s*<div class="small")', sec, re.S)
assert len(cards_html) == 3
order = [m.group(1) for m in re.finditer(r'class="qm-sym">(\w+)', sec)]
assert order == [c["ticker"] for c in CARDS] == [r["ticker"] for r in sorted(ROWS, key=lambda r: (r["tight"], -r["lead"], r["ticker"]))]
d = by["DOCN"]
doc = txt_of(cards_html[0])
L = d["levels"]
for frag in ("DOCN", f"${d['close']:.2f}", f"Вход над ${d['trigger']:.2f} (+{d['pct_to_trigger']:.1f}%)", f"ADR {d['adr']:.1f}%", f"Предходен ръст +{d['runup_pct']:.0f}%", f"Консолидация {d['base_days']} дни",
             # 07.10 (стоп и размер): стоп за оразмеряване (1×ADR) е главният, очакваният (0.55×ADR) — втори ред; без брой акции
             f"Стоп за оразмеряване (макс. 1×ADR) ${L['stop']:.2f} (−{L['stop_pct']:.1f}%)", f"Очакван стоп (0.55×ADR) ≈ ${L['expected_stop']:.2f} (−{L['expected_stop_pct']:.1f}%)",
             "ориентировъчен — реалният стоп е дъното на деня на влизане", "въведи баланса в настройките, за да видиш размера на позицията", "коригирай"):
    assert frag in doc, (frag, doc)
assert (L["entry"], L["stop"], L["expected_stop"]) == (d["trigger"], d["max_stop"], d["expected_stop"])
assert all(f'data-strategy="kullamagi" data-entry="{c["trigger"]}" data-stop="{c["levels"]["stop"]}"' in cards_html[i] and 'data-factor="1.0"' in cards_html[i] for i, c in enumerate(CARDS))
assert "Ниво на пробива" not in txt and "Акции при" not in txt and "брой акции" not in txt.lower() and "риск $" not in txt                  # старият подробен вид и размерът по сметка ги няма
assert "дълбочина" in cards_html[0] and "от 10 MA" in cards_html[0]                                                                # подробностите за базата са в подсказката (title)
assert "QM✓" not in doc                                                                                                            # DOCN не е в Watchlist на 05.10
assert raw.index("Watchlist ·") < raw.index('<section id="qm">') < raw.index('<section id="qm-ep">')
print(f"  ✓ карти по реда на стягане {order}; DOCN: {doc}")
print("  ✓ банерът 'Измерване, не препоръка…' е НАД картите; стоп за оразмеряване (макс. 1×ADR) + очакван стоп (0.55×ADR) като втори ред, без брой акции; подробности (дълбочина, 10/20 MA) — в подсказката; HTML-ът е балансиран")
glb = copy.deepcopy(B05)
glb["glb_candidates"] = [{"ticker": "ZZZ", "glb_type": "classic", "months_unpenetrated": 40, "price": 10.0, "prior_high": 9.0, "prior_high_month": "2020-01", "tightness": None, "company": "ZZZ", "risk_note": "x"}]   # СИНТЕТИЧНО: GLB кандидат, за да има секция GLB
glb["qm_breakout"], glb["qm_diag"], glb["qm_ep"] = copy.deepcopy(CARDS), copy.deepcopy(DIAG), copy.deepcopy(EP)
gp = page_raw(glb)
assert gp.index("Watchlist ·") < gp.index('<section id="qm">') < gp.index('<section id="qm-ep">') < gp.index("GLB Watchlist")
print("  ✓ позиция: веднага след Watchlist и ПРЕДИ GLB Watchlist (СИНТЕТИЧЕН GLB кандидат върху реалния бриф от 05.10)")
mal = brief_with()
mal["watchlist"] = [{**mal["watchlist"][0], "ticker": "DOCN"}] + mal["watchlist"][1:]                                              # СИНТЕТИЧНО: DOCN е на нашата Watchlist
mp = section(page_raw(mal))
mc = re.findall(r'<div class="qm-card[^"]*">.*?(?=<div class="qm-card|</div>\s*<div class="small")', mp, re.S)
assert "QM✓" in mc[0] and "QM✓" not in mc[1] and "QM✓" not in mc[2]
print("  ✓ QM✓ на картата само за тикъра, който е и в Watchlist/Action (СИНТЕТИЧНО: DOCN подменен като Watchlist карта)")

print()
print("── EP: таблица, ред за отварянето и вчерашният дневник (РЕАЛНО: SYNA; СИНТЕТИЧНО: резюмето на AI) ──")
esec = section(raw, "qm-ep")
et = txt_of(esec)
r = EP["rows"][0]
assert "Епизодични пивоти (EP) · гапове след новина" in et
head_row = txt_of(re.search(r"<thead>.*?</thead>", esec, re.S).group(0))
assert head_row == "Тикър AH гап Новина Ръст 3 м. Стоп лимит (1×ADR)", head_row
body_row = txt_of(re.search(r"<tbody>.*?</tbody>", esec, re.S).group(0))
for frag in ("SYNA", "Synaptics", f"+{r['gap_pct']:.1f}%", f"${r['prev_close']:.2f} → ${r['ah_price']:.2f}", HL[0]["title"], "Придобиване (оферта)", "изненада", SUMMARY, "⚠ обем в AH: н/д",
             f"{r['ret63_pct']:+.0f}%", f"${r['max_stop']:.2f} (−{r['max_stop_pct']:.1f}%)",
             f"After-hours цена ${r['ah_price']:.2f}" if False else f"after-hours цена ${r['ah_price']:.2f}", f"Стоп за оразмеряване (макс. 1×ADR) ${r['max_stop']:.2f} (−{r['max_stop_pct']:.1f}%)", "въведи баланса в настройките"):
    assert frag in body_row, (frag, body_row)
assert not any(k in r for k in ("shares", "risk_usd", "total_investment", "pct_of_portfolio")) and "акции при" not in body_row           # 07.10: размерът е в браузъра
assert (r["levels"]["entry"], r["levels"]["stop"], r["levels"]["strategy"]) == (round(r["ah_price"], 2), r["max_stop"], "kullamagi")    # вход = after-hours цената, стоп = 1×ADR под нея
assert "Проверката е отварянето (15:30 CEST / 09:30 ET)" in et
assert "Вчерашният дневник — after-hours срещу отваряне: SYNA AH +15.0% → отваряне +14.7% (издържа ≥ 10%)" in et
assert "Общо в дневника: записи 1, разрешени 1; 1 от тях отварят ≥ 10% (100%)" in et and "решение за второ пускане — след 4–6 седмици" in et
print(f"  ✓ колони: {head_row}; SYNA: AH +{r['gap_pct']:.1f}% (${r['prev_close']:.2f} → ${r['ah_price']:.2f}), реалното заглавие на Yahoo, 'Придобиване (оферта)', ръст 3 м. {r['ret63_pct']:+.0f}%, стоп лимит ${r['max_stop']:.2f} (1×ADR), вход = after-hours цената; без брой акции")
print("  ✓ под таблицата: 'Проверката е отварянето…' и 'Вчерашният дневник — SYNA AH +15.0% → отваряне +14.7% (издържа ≥ 10%)' (РЕАЛНО отваряне на 02.10, 14.65%)")
et0 = txt_of(section(page_raw(brief_with()), "qm-ep"))
assert "Вчера няма гапове за проверка срещу отварянето" in et0 and "Вчерашният дневник" not in et0
ep_empty = {**EP, "rows": [], "not_neglected": [{"ticker": "ABCD", "gap_pct": 12.3, "ret63_pct": 55.0, "why": "ръст 55% за 3 месеца > 20%"}]}
t2 = txt_of(section(page_raw(brief_with(ep_out=ep_empty)), "qm-ep"))
assert "няма after-hours гапове ≥ 10% при „пренебрегнати“ тикъри" in t2 and "ABCD +12.3%" in t2 and "ръст 55% за 3 месеца > 20%" in t2
ep_fail = {"ok": False, "rows": [], "notes": ["RuntimeError: Yahoo"], "diag": {}, "log": {}, "not_neglected": []}
t3 = txt_of(section(page_raw(brief_with(ep_out=ep_fail)), "qm-ep"))
assert "Наблюдението не се изпълни — празният списък НЕ значи, че няма гапове" in t3 and "няма after-hours гапове" not in t3
nohl = copy.deepcopy(EP); nohl["rows"][0]["headlines"] = []
assert "не е намерено заглавие" in txt_of(section(page_raw(brief_with(ep_out=nohl)), "qm-ep"))
print("  ✓ без 'пренебрегнати' гапове: 'няма …' + другите гапове с причина; провал → 'празният списък НЕ значи …'; без заглавие → 'не е намерено заглавие'")
assert 'id="qm-ep"' not in page_raw(brief_with(ep_out={})) and 'id="qm"' in page_raw(brief_with(ep_out={}))
print("  ✓ при ENABLE_QM_EP=0 (празен qm_ep) секцията EP липсва, Breakout остава")

print()
print("── книгата qm_breakout (свита под картите) ──")
assert '<details class="qm-book"' in sec
sm = txt_of(re.search(r"<summary.*?</summary>", sec, re.S).group(0))
assert sm == "Измерване — книга qm_breakout: записани 3 · затворени 0 · win rate след 20 затворени", sm
assert "Записани: 3" in txt and "чакат вход 3" in txt and "Win rate се показва след 20 затворени (сега 0)" in txt and "Win rate:" not in txt
assert "Чакащи и отворени (3)" in txt and "$151.83" in txt and "Defensive" in txt and "две граници" in txt
for u in ("qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/", "qullamaggie.com/how-to-master-a-setup-episodic-pivots/", "qullamaggie.com/faq/"):
    assert u in sec
print("  ✓ <details> със заглавен ред 'записани 3 · затворени 0 · win rate след 20 затворени'; вътре — таблицата на 3-те реални чакащи записа, двете граници, линковете към qullamaggie.com")
tr25 = {}
for i in range(25):                                                                                                # СИНТЕТИЧНО: 25 затворени записа, 7 печеливши
    rr = 3.0 if i < 7 else -1.0
    tr25[f"T{i}_2026-09-0{1 + i % 9}_qm"] = {"method": "v2", "category": "qm_breakout", "ticker": f"T{i}", "entry_date": f"2026-08-{1 + i:02d}", "status": "stopped", "regime": "Offensive", "buy_stop": 10.0, "adr": 4.0,
                                              "fill_date": f"2026-08-{1 + i:02d}", "realized_r": rr, "realized_r_pess": rr - (0.3 if rr > 0 else 0), "resolution_date": f"2026-08-{2 + i:02d}",
                                              "return_pct": rr * 3, "spy_return_pct": 0.5, "stop_loss": 9.6}
backtest._save_tracker(tr25)
QB25 = backtest.get_qm_summary()
assert QB25["stats_visible"] and QB25["closed"] == 25
s25 = section(page_raw(brief_with(qb=QB25)))
t25 = txt_of(s25)
assert txt_of(re.search(r"<summary.*?</summary>", s25, re.S).group(0)) == "Измерване — книга qm_breakout: записани 25 · затворени 25 · win rate 28.0%"
assert "Win rate: 28.0% opt / 28.0% pess (7 win / 18 loss; 95% интервал" in t25 and "медиана R -1.00 / -1.00" in t25 and "Спрямо SPY (същите периоди, 25 затворени)" in t25 and "Последни затворени (10)" in t25
print("  ✓ СИНТЕТИЧНИ 25 затворени: заглавният ред казва 'win rate 28.0%', вътре — интервал, медиана, SPY, последни затворени")
QB19 = copy.deepcopy(QB25); QB19.update(closed=19, stats_visible=False, win_rate_pct=None, win_rate_pess_pct=None, win_ci_pct=None, median_realized_r=None, median_realized_r_pess=None, spy_compare=None, wins=None, losses=None, big_winners_5r=None)
for g in QB19["by_regime"].values():
    g["avg_r"] = None
t19 = txt_of(section(page_raw(brief_with(qb=QB19))))
assert "Win rate се показва след 20 затворени (сега 19)" in t19 and "Win rate:" not in t19

print()
print("── банери, празни състояния и стар бриф ──")
tf = txt_of(section(page_raw(brief_with(cards=[], diag={"ok": False, "error": "RuntimeError: мрежата падна", "candidates": 0, "shown": 0}))))
assert "Скенерът не се изпълни (RuntimeError: мрежата падна) — празният списък НЕ значи, че няма кандидати за пробив" in tf and "Вход над" not in tf
te = txt_of(section(page_raw(brief_with(cards=[], diag={**DIAG, "candidates": 0, "shown": 0}))))
assert "няма кандидати днес (проверени 892 тикъра)" in te
tm = txt_of(section(page_raw(brief_with(diag={**DIAG, "candidates": 11, "shown": 8}))))
assert "кандидати 11, показани 3" in tm
assert "Подредени по стягане на базата (най-стегнатите първи); лидери: горните 10% по ръст за 1, 3 и 6 месеца (167 от 892 тикъра към 02.10), кандидати 3." in txt
old = page_raw(copy.deepcopy(B05))
old_body = old.split("</style>", 1)[1]                                                                                # CSS коментарът е в <style>; секциите — в тялото
assert "Kullamägi" not in old_body and 'id="qm"' not in old_body and 'id="qm-ep"' not in old_body and "qm-card" not in old_body and old.count("<section") == old.count("</section>")
print("  ✓ провал на скенера → 'празният списък НЕ значи …'; 0 кандидати → 'няма кандидати днес (проверени 892 тикъра)'; повече от показаните → 'кандидати 11, показани 3'; РЕАЛНИЯТ бриф от 05.10 без ключовете → без секциите")
xss = brief_with(ep_out=EP_Y)
xss["qm_ep"]["rows"][0]["summary_bg"] = '<script>alert(1)</script> "x"'                                           # СИНТЕТИЧНО: злонамерен текст в AI резюме
xss["qm_ep"]["rows"][0]["headlines"] = [{"title": "<img src=x onerror=alert(1)>", "published": "2026-10-01"}]
rawx = page_raw(xss)
assert "<script>alert(1)</script>" not in rawx and "<img src=x" not in rawx and "&lt;script&gt;" in rawx
print("  ✓ escape: <script> и <img onerror> в резюмето/заглавията излизат като текст")

print()
print("── имейл ──")
em = render.render_email(brief_with(ep_out=EP_Y))
emt = htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", em)))
assert SURV in emt and "Пробиви по Kullamägi (Breakout)" in emt and "Епизодични пивоти (EP) · гапове след новина" in emt
assert "Входът е по opening range high в сесията, стопът — low of day; брифът дава нивата, не самия вход." in emt
for c in CARDS:
    assert c["ticker"] in emt and f"вход над ${c['trigger']:.2f}" in emt and f"стоп (макс. 1×ADR) ${c['levels']['stop']:.2f} (−{c['levels']['stop_pct']:.1f}%)" in emt
    assert f"очакван стоп (0.55×ADR) ≈ ${c['expected_stop']:.2f}" in emt and "акции при" not in emt
    assert f"ръст +{c['runup_pct']:.0f}% преди базата · консолидация {c['base_days']} дни" in emt and f"ADR {c['adr']:.1f}%" in emt
assert HL[0]["title"] in emt and "AH +15.0%" in emt and "3 м. -11%" in emt and "стоп $116.56 (−4.5%)" in emt and "91 акции" not in emt and SUMMARY in emt
assert "Проверката е отварянето (15:30 CEST): гапът се доказва едва тогава. Вчера, AH срещу отваряне: SYNA +15.0% → +14.7% (издържа)." in emt
assert "Измерване: 3 записа · затворени 0 · win rate след 20 затворени" in emt
assert emt.index("Watchlist:") < emt.index("Пробиви по Kullamägi (Breakout)") < emt.index("Епизодични пивоти (EP)") < emt.index("Отвори пълния dashboard")
assert "Qullamaggie сетъпи" not in emt
print("  ✓ в имейла: веднага след реда Watchlist — 'Пробиви по Kullamägi (Breakout)' (3-те карти: ниво, стоп за оразмеряване и %, ADR, очакван стоп, ръст, дни консолидация; без брой акции) и 'Епизодични пивоти (EP)' (SYNA: AH гап, заглавие, ръст, стоп и %; ред за отварянето и вчерашния дневник)")
em_q = render.render_email({**brief_with(), "watchlist": [{"ticker": "DOCN"}] + brief_with()["watchlist"]})
assert re.search(r"DOCN</td>|DOCN<span[^>]*>QM✓", em_q) and "QM✓" in em_q
em25 = htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", render.render_email(brief_with(qb=QB25)))))
assert "Измерване: 25 записа · затворени 25 · среден R" in em25 and "win rate 28.0% opt / 28.0% pess" in em25
em_old = render.render_email(copy.deepcopy(B05))
assert "Kullamägi" not in em_old
bad = brief_with(); bad["qm_breakout"] = [{"ticker": "X"}]                                                          # повреден ред → блокът отпада, имейлът се рендерира
em_bad = render.render_email(bad)
assert "Отвори пълния dashboard" in em_bad and "Пробиви по Kullamägi" not in em_bad
em_fail = htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", render.render_email(brief_with(cards=[], diag={"ok": False, "error": "x"})))))
assert "Скенерът не се изпълни — празният списък НЕ значи, че няма кандидати за пробив." in em_fail
em_xss = render.render_email(xss)
assert "<script>alert(1)</script>" not in em_xss and "&lt;script&gt;" in em_xss
print("  ✓ QM✓ в имейла за тикър от Watchlist; при 25 затворени се показва win rate; стар бриф → без блока; повреден ред → блокът отпада, имейлът остава цял; провал на скенера → предупреждение; escape")

print()
print("── 08.10: 'до нивото: X ADR', скрити карти над 1×ADR, предупреждение за отчет ──")
cards2 = copy.deepcopy(CARDS)
cards2[0]["earnings_warning"] = {"text": "⚠ отчет на 12.10 (след 2 сесии) — пазарът очаква ±8%"}                                        # СИНТЕТИЧНО: предупреждение (механизмът е в earnings_move; тук — само показването)
diag2 = {**DIAG, "beyond_adr": 2, "beyond_adr_tickers": ["SANM", "SITM"], "max_dist_adr": 1.0}                                         # СИНТЕТИЧНО: диагностиката на 08.10 (2 скрити карти)
p2 = txt_of(section(page_raw(brief_with(cards=cards2, diag=diag2))))
assert "Вход над $151.83 (+8.4%) · до нивото 1.17 ADR" in p2 and "Вход над $120.51 (+3.7%) · до нивото 0.78 ADR" in p2                    # РЕАЛНИТЕ карти от 02.10
assert "⚠ отчет на 12.10 (след 2 сесии) — пазарът очаква ±8%" in p2
assert "Още 2 кандидат(а) са на повече от 1×ADR от нивото (SANM, SITM) — не се показват и не се записват." in p2
em2 = htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", render.render_email(brief_with(cards=cards2, diag=diag2)))))
assert "вход над $151.83 · до нивото 1.17 ADR" in em2 and "⚠ отчет на 12.10 (след 2 сесии) — пазарът очаква ±8%" in em2
pe = txt_of(section(page_raw(brief_with(cards=[], diag={**DIAG, "candidates": 0, "shown": 0, "beyond_adr": 2, "beyond_adr_tickers": ["SANM", "SITM"], "max_dist_adr": 1.0}))))
assert "няма кандидати днес (проверени 892 тикъра); още 2 са на повече от 1×ADR от нивото (SANM, SITM) — не се показват" in pe
print("  ✓ картите: 'Вход над $151.83 (+8.4%) · до нивото 1.17 ADR'; бележка 'Още 2 кандидат(а) са на повече от 1×ADR от нивото (SANM, SITM) — не се показват и не се записват'; предупреждение за отчет — и в dashboard-а, и в имейла; празен списък помни скритите")

print()
print("Всички тестове минаха.")
