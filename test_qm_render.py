"""
Qullamaggie (06.10.2026) · т.6: секцията "Qullamaggie сетъпи" в dashboard-а и в имейла — отделна от Action/Watchlist, с надпис "отделна стратегия — измерване, не препоръка", карти на breakout кандидатите
(всички полета от заданието), EP наблюдение (без Track Record), блок за книгата qm_breakout (win rate чак след ≥ 20 затворени), банери при провал, стар бриф без ключовете → без секция.

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
ROWS, DIAG = q.scan_frames(frames, lead=FIX["lead"])
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


print("── dashboard · карти (РЕАЛНИ към 02.10.2026) ──")
page = page_of(brief_with())
sec = section(page)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", sec))
assert page.count("<section") == page.count("</section>")
SURV = "Измерване, не препоръка. Реплеят е с survivorship (днешният универс) и резултатът зависи от малко големи печалби. Алфата не е статистически значима."
assert SURV in txt
assert "отделна стратегия — измерване, не препоръка" in txt.lower() and "Входът е по opening range high в сесията, стопът — low of day; брифът дава нивата, не самия вход." in txt
by = {c["ticker"]: c for c in CARDS}
d = by["DOCN"]
for frag in ("DOCN", f"Ниво на пробива ${d['trigger']:.2f} · +{d['pct_to_trigger']:.1f}% до него", f"ADR {d['adr']:.1f}%", f"ръст преди базата +{d['runup_pct']:.0f}%", f"База {d['base_days']} сесии",
             f"дълбочина {d['depth_pct']:.1f}%", f"Цена спрямо 10 MA {d['vs_sma10_pct']:+.1f}% · 20 MA {d['vs_sma20_pct']:+.1f}%", f"Очакван стоп ≈ ${d['expected_stop']:.2f}", f"максимален ${d['max_stop']:.2f}",
             "0.55×ADR", "1×ADR", "При половин риск ($500)", f"{d['shares']} акции", f"${d['total_investment']:,.0f}", f"{d['shares_at_max_stop']} акции при максималния"):
    assert frag in txt, frag
assert txt.count("Ниво на пробива") == 3 and txt.index("Ниво на пробива") < txt.index("Episodic Pivot")
order = [m.group(1) for m in re.finditer(r'class="qm-sym">(\w+)<', sec)]
assert order == [c["ticker"] for c in CARDS] == [r["ticker"] for r in sorted(ROWS, key=lambda r: (r["tight"], -r["lead"], r["ticker"]))]
print(f"  ✓ 3 карти по реда на стягане {order}; всяка с ниво и % до него, ADR, ръст преди базата, дължина/дълбочина на базата, позиция спрямо 10/20 MA, очакван и максимален стоп, размер при половин риск ($500); DOCN: "
      f"ниво ${d['trigger']:.2f} (+{d['pct_to_trigger']:.1f}%), ADR {d['adr']:.1f}%, стоп ≈ ${d['expected_stop']:.2f} / ${d['max_stop']:.2f}, {d['shares']} акции")
assert page.index('id="qm"') > page.index("Action") and "Watchlist" in page
print("  ✓ собствена секция (id=qm), с банер 'отделна стратегия — измерване, не препоръка' и бележката за opening range high / low of day; HTML-ът е балансиран")

print()
print("── dashboard · EP наблюдение (РЕАЛНО: SYNA 01.10; СИНТЕТИЧНО: резюмето на AI) ──")
assert "Episodic Pivot — наблюдение (без Track Record)" in txt and "Обемът в after-hours не е наличен" in txt
r = EP["rows"][0]
for frag in ("SYNA", "Synaptics Inc", f"+{r['gap_pct']:.1f}%", f"${r['prev_close']:.2f} → ${r['ah_price']:.2f}", f"{r['ret63_pct']:+.0f}%", f"{r['adr']:.1f}%", f"${r['max_stop']:.2f}", f"−{r['max_stop_pct']:.1f}%".replace("−", "-") if False else f"{r['max_stop_pct']:.1f}%",
             "Придобиване (оферта)", "изненада", SUMMARY, "⚠ обем в after-hours: н/д", "≤1×ADR", "сесия 01.10"):
    assert frag in txt, frag
assert sum(1 for h in HL[:2] if h["title"] in txt) == 2
assert "Дневник за решение след 4–6 седмици" in txt and "записи 1, разрешени 0" in txt
print(f"  ✓ SYNA: +{r['gap_pct']:.1f}% (${r['prev_close']:.2f} → ${r['ah_price']:.2f}), ръст 3 м. {r['ret63_pct']:+.0f}%, ADR {r['adr']:.1f}%, стоп лимит ${r['max_stop']:.2f}, катализатор 'Придобиване (оферта)'; "
      "обемът е н/д; 2 заглавия; дневникът: 1 запис")
ep_empty = {**EP, "rows": [], "not_neglected": [{"ticker": "ABCD", "gap_pct": 12.3, "ret63_pct": 55.0, "why": "ръст 55% за 3 месеца > 20%"}]}
txt2 = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", section(page_of(brief_with(ep_out=ep_empty)))))
assert "няма after-hours гапове ≥ 10% при „пренебрегнати“ тикъри" in txt2 and "ABCD +12.3%" in txt2 and "ръст 55% за 3 месеца > 20%" in txt2
ep_fail = {"ok": False, "rows": [], "notes": ["RuntimeError: Yahoo"], "diag": {}, "log": {}, "not_neglected": []}
txt3 = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", section(page_of(brief_with(ep_out=ep_fail)))))
assert "Наблюдението не се изпълни — празният списък НЕ значи, че няма гапове" in txt3 and "няма after-hours гапове" not in txt3
print("  ✓ без 'пренебрегнати' гапове: 'няма …' + другите гапове с причина; провал на наблюдението → 'празният списък НЕ значи, че няма гапове'")

print()
print("── dashboard · книгата qm_breakout ──")
assert "Измерване — книга qm_breakout (отделна от Action и buy-stop)" in txt and "две граници" in txt and "opt" in txt and "pess" in txt
assert "Записани: 3" in txt and "чакат вход 3" in txt and "Win rate се показва след 20 затворени (сега 0)" in txt and "Win rate:" not in txt
assert "Чакащи и отворени (3)" in txt and "$151.83" in txt and "Defensive" in txt
for u in ("qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/", "qullamaggie.com/how-to-master-a-setup-episodic-pivots/", "qullamaggie.com/faq/"):
    assert u in sec
print("  ✓ 3 реални чакащи записа (DOCN, CORT, CRL — режим Defensive): 'Win rate се показва след 20 затворени (сега 0)'; таблица със нивата; линкове към qullamaggie.com")
tr25 = {}
for i in range(25):                                                                                                # СИНТЕТИЧНО: 25 затворени записа, 7 печеливши
    rr = 3.0 if i < 7 else -1.0
    tr25[f"T{i}_2026-09-0{1 + i % 9}_qm"] = {"method": "v2", "category": "qm_breakout", "ticker": f"T{i}", "entry_date": f"2026-08-{1 + i:02d}", "status": "stopped", "regime": "Offensive", "buy_stop": 10.0, "adr": 4.0,
                                              "fill_date": f"2026-08-{1 + i:02d}", "realized_r": rr, "realized_r_pess": rr - (0.3 if rr > 0 else 0), "resolution_date": f"2026-08-{2 + i:02d}",
                                              "return_pct": rr * 3, "spy_return_pct": 0.5, "stop_loss": 9.6}
backtest._save_tracker(tr25)
QB25 = backtest.get_qm_summary()
assert QB25["stats_visible"] and QB25["closed"] == 25
t25 = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", section(page_of(brief_with(qb=QB25)))))
assert "Win rate: 28.0% opt / 28.0% pess (7 win / 18 loss; 95% интервал" in t25 and "медиана R -1.00 / -1.00" in t25 and "Спрямо SPY (същите периоди, 25 затворени)" in t25 and "Win rate се показва след" not in t25
assert "Последни затворени (10)" in t25 and "opt /" in t25
print("  ✓ СИНТЕТИЧНИ 25 затворени: 'Win rate: 28.0% opt / 28.0% pess (7 win / 18 loss; 95% интервал …)', медиана, SPY, последни затворени; при 0 затворени (по-горе) win rate го няма")
QB19 = copy.deepcopy(QB25); QB19.update(closed=19, stats_visible=False, win_rate_pct=None, win_rate_pess_pct=None, win_ci_pct=None, median_realized_r=None, median_realized_r_pess=None, spy_compare=None, wins=None, losses=None, big_winners_5r=None)
for g in QB19["by_regime"].values():
    g["avg_r"] = None
t19 = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", section(page_of(brief_with(qb=QB19)))))
assert "Win rate се показва след 20 затворени (сега 19)" in t19 and "Затворени: 19 · среден R:" in t19 and "Win rate:" not in t19

print()
print("── банери, празни състояния и стар бриф ──")
tf = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", section(page_of(brief_with(cards=[], diag={"ok": False, "error": "RuntimeError: мрежата падна", "candidates": 0, "shown": 0})))))
assert "Скенерът не се изпълни (RuntimeError: мрежата падна) — празният списък НЕ значи, че няма кандидати за пробив" in tf and "Ниво на пробива" not in tf
te = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", section(page_of(brief_with(cards=[], diag={**DIAG, "candidates": 0, "shown": 0})))))
assert "няма кандидати днес (проверени 892 тикъра)" in te
tm = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", section(page_of(brief_with(diag={**DIAG, "candidates": 11, "shown": 8})))))
assert "кандидати: 11, показани най-стегнатите 3" in tm and "(3 от 11)" in tm
assert "Лидери: горните 10% по ръст за 1, 3 и 6 месеца (167 от 892 тикъра с история към 02.10) · кандидати: 3." in txt
old = page_of(copy.deepcopy(B05))
old_body = old.split("</style>", 1)[1]                                                                                # CSS коментарът е в <style>; секцията — в тялото
assert "Qullamaggie" not in old_body and 'id="qm"' not in old_body and "qm-card" not in old_body and old.count("<section") == old.count("</section>")
print("  ✓ провал на скенера → 'празният списък НЕ значи …'; 0 кандидати → 'няма кандидати днес (проверени 892 тикъра)'; повече от показаните → '(3 от 11)'; РЕАЛНИЯТ бриф от 05.10 без ключовете → страницата е без секцията")
mal = brief_with()
mal["watchlist"] = [{**mal["watchlist"][0], "ticker": "DOCN"}] + mal["watchlist"][1:]
page_m = page_of(mal)
assert "✓ и в Action/Watchlist — маркер QM✓" in section(page_m)
print("  ✓ карта, чийто тикър е и на нашата CANSLIM карта → 'и в Action/Watchlist — маркер QM✓' (СИНТЕТИЧНО: DOCN е подменен като Watchlist карта)")
xss = brief_with()
xss["qm_ep"]["rows"][0]["summary_bg"] = '<script>alert(1)</script> "x"'                                           # СИНТЕТИЧНО: злонамерен текст в AI резюме
xss["qm_ep"]["rows"][0]["headlines"] = [{"title": "<img src=x onerror=alert(1)>", "published": "2026-10-01"}]
raw = render.render_dashboard(xss)
assert "<script>alert(1)</script>" not in raw and "<img src=x" not in raw and "&lt;script&gt;" in raw
print("  ✓ escape: <script> и <img onerror> в резюмето/заглавията излизат като текст")

print()
print("── имейл ──")
em = render.render_email(brief_with())
emt = htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", em)))
assert SURV in emt
assert "Qullamaggie сетъпи" in emt and "Отделна стратегия — измерване, не препоръка." in emt and "Входът е по opening range high в сесията, стопът — low of day; брифът дава нивата, не самия вход." in emt
for c in CARDS:
    assert c["ticker"] in emt and f"ниво ${c['trigger']:.2f}" in emt and f"+{c['pct_to_trigger']:.1f}% до него" in emt and f"стоп ≈ ${c['expected_stop']:.2f}, макс. ${c['max_stop']:.2f}" in emt
assert "SYNA +15.0% after-hours (ръст 3 м. -11%, ADR 4.5%, стоп лимит $116.56)" in emt and "Придобиване (оферта)" in emt and SUMMARY in emt and "обемът в after-hours не е наличен" in emt
assert "Измерване: 3 записа · затворени 0 · win rate след 20 затворени" in emt
assert emt.index("Qullamaggie сетъпи") > emt.index("Action ·") and emt.index("Qullamaggie сетъпи") < emt.index("Отвори пълния dashboard")
print("  ✓ блок 'Qullamaggie сетъпи' между Action/Watchlist и бутона: надписът, бележката, 3-те карти с ниво/стоп/размер, EP редът на SYNA, ред за книгата ('win rate след 20 затворени')")
em25 = htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", render.render_email(brief_with(qb=QB25)))))
assert "Измерване: 25 записа · затворени 25 · среден R" in em25 and "win rate 28.0% opt / 28.0% pess" in em25
em_old = render.render_email(copy.deepcopy(B05))
assert "Qullamaggie" not in em_old
bad = brief_with(); bad["qm_breakout"] = [{"ticker": "X"}]                                                          # повреден ред → блокът отпада, имейлът се рендерира
em_bad = render.render_email(bad)
assert "Отвори пълния dashboard" in em_bad and "Qullamaggie сетъпи" not in em_bad
em_fail = htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", render.render_email(brief_with(cards=[], diag={"ok": False, "error": "x"})))))
assert "Скенерът не се изпълни — празният списък НЕ значи, че няма кандидати за пробив." in em_fail
em_xss = render.render_email(xss)
assert "<script>alert(1)</script>" not in em_xss and "&lt;script&gt;" in em_xss
print("  ✓ при 25 затворени се показва win rate; стар бриф → без блока; повреден ред → блокът отпада, имейлът остава цял; провал на скенера → предупреждение; escape на външния текст")

print()
print("Всички тестове минаха.")
