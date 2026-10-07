"""
Пакет 1б (допълнение от 07.10) · картата на buy-stop кандидат чете СЪСТОЯНИЕТО на записа в книгата, а ако тикърът излезе от скрийнъра — редът в книгата казва защо.
Случаят EXPD (РЕАЛНО): buy-stop $194.59 от брифа на 05.10; High на 05.10 е $195.32 → задействан на 05.10 по $194.59; картата на 06.10 пак пишеше "чака пробив"; на 07.10 EXPD изчезна изцяло
(RS линията 95.9% от 52-седмичния максимум при праг 97%) — без нито един ред на страницата.

  • запис pending → прозорецът на записа ("валиден до 09.10, от 05.10"; тест test_buystop_window_label.py);
  • запис open / trailing → "✅ Задействан на 05.10 по $194.59 (buy-stop от 05.10) · стоп $181.53 · цел 2R $220.71 · текущо −0.2R — изпълнен сигнал от книгата, не нов вход", без "чака пробив", без
    "🎯 Buy-stop …" и "📐 Ако се задейства …" и без AI "Trigger:";
  • жив запис, чийто тикър липсва в днешния списък → в таблицата на книгата "излезе от скрийнъра: <първият филтър с числата>" (screener.explain_exclusion — в същия ред като _evaluate_technicals).

РЕАЛНО: Watchlist картите на EXPD от 05.10 (tests/fixtures/brief_2026-10-05.json) и 06.10 (expd_card_2026-10-06.json); суровите дневни барове на EXPD и SPY до 06.10 (ohlc_EXPD_SPY_raw_2026-10-06.json);
дневните данни на 6 тикъра и rs_score на всичките 903 към 06.10 (screen_real_2026-10-06.json). Записът в книгата се създава от РЕАЛНИЯ ingest и се резолвира от РЕАЛНАТА резолюция върху реалните барове.
СИНТЕТИЧНО (означено): записът в статус trailing, записите без цена на входа, занижените rs_scores за проверката на RS rating, подменените заявки към Yahoo, временният tracker.
Пускане: python test_buystop_book_state.py
"""
import sys, json, pathlib, tempfile, copy, ast, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import setup_rules, backtest, sizing, screener, render
from src import main as brief_main

D = dt.date.fromisoformat
FX = ROOT / "tests" / "fixtures"
B05 = json.loads((FX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
C05 = next(c for c in B05["watchlist"] if c["ticker"] == "EXPD")
C06 = json.loads((FX / "expd_card_2026-10-06.json").read_text(encoding="utf-8"))["card"]
BARS = json.loads((FX / "ohlc_EXPD_SPY_raw_2026-10-06.json").read_text(encoding="utf-8"))["bars"]
SCR = json.loads((FX / "screen_real_2026-10-06.json").read_text(encoding="utf-8"))

tmp = tempfile.TemporaryDirectory(prefix="mb_bsstate_")
config.DATA_DIR = pathlib.Path(tmp.name)
config.DOCS_DIR = pathlib.Path(tmp.name) / "docs"
config.DOCS_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
config.BUYSTOP_TRACK_FROM = ""                                           # guard-ът по дата има собствен тест
backtest.enrich.earnings_recap = lambda t: None
backtest._unapplied_splits = lambda rec: []


def raw_frame(t):
    b = BARS[t]
    return pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"], "Volume": b["v"]}, index=pd.to_datetime(b["dates"]))


def fake_download(tickers, start=None, progress=False, auto_adjust=False, **kw):
    cols = ["Open", "High", "Low", "Close", "Volume"]
    fr = {t: raw_frame(t) for t in tickers}
    return pd.concat({f: pd.DataFrame({t: fr[t][f] for t in tickers}) for f in cols}, axis=1)


backtest.yf.download = fake_download

print("── РЕАЛНИЯТ EXPD през книгата: запис от 05.10, резолюция върху реалните барове ──")
c = copy.deepcopy(C05)
c["plan_preview"] = sizing.buy_stop_preview(c, 0.5, D("2026-10-05"))                          # планът-преглед от P2 кода върху реалната карта (в самия бриф от 05.10 го няма)
tr = {}
backtest._ingest_buystop_list(tr, "2026-10-05", [c], "Defensive")
backtest._save_tracker(tr)
tr = backtest._load_tracker()
backtest._resolve_open_positions(tr, D("2026-10-06"))
backtest._save_tracker(tr)
rec = backtest._load_tracker()["EXPD_2026-10-05_buystop"]
assert (rec["status"], rec["fill_date"], rec["fill_price"], rec["stop_loss"], rec["target_1"], rec["current_r"]) == ("open", "2026-10-05", 194.59, 181.53, 220.71, -0.21)
live = backtest.live_buystop_by_ticker()
assert list(live) == ["EXPD"] and live["EXPD"]["status"] == "open" and backtest.pending_buystop_by_ticker() == {}
print("  ✓ реален вход: High 195.32 на 05.10 над buy-stop $194.59 (Open 192.36 под него → вход по $194.59), стоп $181.53, цел 2R $220.71, на 06.10 затваряне $191.80 = −0.21R; "
      "live_buystop_by_ticker го връща (pending_buystop_by_ticker — не)")

print()
print("── картата от 06.10 чете състоянието ──")
c0 = copy.deepcopy(C06); c0.pop("setup", None); setup_rules.annotate([c0], D("2026-10-06"))                     # без книга: както преди — "чака пробив"
assert c0["setup"]["kind"] == "below_pivot" and "triggered" not in c0["setup"] and c0["setup"]["trigger_text"].startswith("Чака пробив")
c1 = copy.deepcopy(C06); c1.pop("setup", None); setup_rules.annotate([c1], D("2026-10-06"), live)
s1 = c1["setup"]
WANT = "✅ Задействан на 05.10 по $194.59 (buy-stop от 05.10) · стоп $181.53 · цел 2R $220.71 · текущо -0.2R — изпълнен сигнал от книгата, не нов вход."
assert s1["triggered"] is True and s1["book_status"] == "open" and s1["trigger_text"] == WANT and "Чака пробив" not in s1["trigger_text"]
assert s1["book"] == {"fill_date": "2026-10-05", "fill_price": 194.59, "entry_date": "2026-10-05", "stop_loss": 181.53, "target_1": 220.71, "current_r": -0.21, "status": "open"}
assert s1["buy_stop"] == 194.59 and s1["kind"] == "below_pivot"                                                 # нивата и класификацията не се пипат
print("  ✓", s1["trigger_text"])
trailing = {"EXPD": {**rec, "status": "trailing", "target1_hit_date": "2026-10-09", "trail_ma": 10, "current_r": 1.4}}   # СИНТЕТИЧЕН запис след частична продажба на 2R
c2 = copy.deepcopy(C06); c2.pop("setup", None); setup_rules.annotate([c2], D("2026-10-12"), trailing)
assert "частично продадена на 2R (09.10), остатъкът е в trailing под SMA10" in c2["setup"]["trigger_text"] and "текущо +1.4R" in c2["setup"]["trigger_text"] and c2["setup"]["book_status"] == "trailing"
nofill = {"EXPD": {**rec, "fill_price": None}}                                                                 # СИНТЕТИЧНО: повреден запис без цена на входа → без промяна
c3 = copy.deepcopy(C06); c3.pop("setup", None); setup_rules.annotate([c3], D("2026-10-06"), nofill)
assert "triggered" not in c3["setup"] and c3["setup"]["trigger_text"].startswith("Чака пробив")
c4 = copy.deepcopy(C06); c4.pop("setup", None); c4["price"] = c4["pivot"] * 1.02                                  # СИНТЕТИЧНО: над pivot → не е below_pivot → без промяна
setup_rules.annotate([c4], D("2026-10-06"), live)
assert "triggered" not in c4["setup"]
print("  ✓ trailing (СИНТЕТИЧЕН запис): 'частично продадена на 2R (09.10), остатъкът е в trailing под SMA10 · текущо +1.4R'; запис без цена на входа и карта над pivot — без промяна")

print()
print("── страницата (РЕАЛНИЯТ бриф от 05.10, но с картата на EXPD от 06.10) ──")
def text(raw_html):
    """Видимият текст: първо се махат таговете, СЛЕД това се декодират &lt; / &amp; (иначе "< 97%" се чете като начало на таг)."""
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", raw_html)))


def cards_of(page):
    return re.split(r'<div class="watch-card">', page)[1:]
def page_with(card, summary=None):
    b = copy.deepcopy(B05)
    b["watchlist"] = [card if x["ticker"] == "EXPD" else x for x in b["watchlist"]]
    if summary is not None:
        b.setdefault("backtest", {})["buystop"] = summary
    return render.render_dashboard(b)
p1 = page_with(c1)
exp1 = text(next(x for x in cards_of(p1) if "EXPD" in x[:300]))
assert WANT in exp1 and "Чака пробив" not in exp1 and "Buy-stop $194.59 · валиден" not in exp1 and "Ако се задейства" not in exp1 and "Trigger:" not in exp1
p0 = page_with(c0)
exp0 = text(next(x for x in cards_of(p0) if "EXPD" in x[:300]))
assert "Чака пробив" in exp0 and "Buy-stop $194.59 · валиден" in exp0 and "Trigger:" in exp0 and "✅ Задействан" not in exp0
print("  ✓ с жив запис: '✅ Задействан на 05.10 по $194.59 · стоп $181.53 · цел 2R $220.71 · текущо -0.2R' и НИТО 'Чака пробив', 'Buy-stop … валиден', 'Ако се задейства', 'Trigger:'; без запис — както преди")

print()
print("── излезе от скрийнъра: причина с числата ──")
def frame(t, cut=None):
    f = SCR["frames"][t]
    df = pd.DataFrame({"High": f["h"], "Low": f["l"], "Close": f["c"], "Volume": f["v"]}, index=pd.to_datetime(f["dates"]))
    return df if cut is None else df[df.index <= pd.Timestamp(cut)]
SPY = pd.Series(SCR["spy"]["c"], index=pd.to_datetime(SCR["spy"]["dates"]))
SC = SCR["rs_scores"]
why = screener.explain_exclusion("EXPD", frame("EXPD"), SPY, SC)
assert why == "RS линия 95.9% от 52-седмичния максимум < 97%"
assert screener.explain_exclusion("EXPD", frame("EXPD", "2026-10-05"), SPY[SPY.index <= "2026-10-05"], SC) is None                    # на 06.10 (бар 05.10) беше технически ОК — картата я имаше
expected = {"AMD": None, "AGNC": "цена $8.70 под минимума $10", "A": "trend template: 150DMA не е над 200DMA", "CRWD": "база с дълбочина 37.5% (над 35%)",
            "AAPL": "RS линия 92.2% от 52-седмичния максимум < 97%"}
for t, w in expected.items():
    assert screener.explain_exclusion(t, frame(t), SPY, SC) == w, t
for t in ("EXPD", "AMD", "AGNC", "A", "CRWD", "AAPL"):                                                                              # същият резултат като самия скрийнър, не само сходен текст
    ev = screener._evaluate_technicals(t, frame(t), SPY)
    ex = screener.explain_exclusion(t, frame(t), SPY, SC)
    assert (ev is None) == (ex is not None), (t, ex)
low = {k: 10.0 for k in SC}                                                                                                         # СИНТЕТИЧНО: всички останали с много висок rs_score → AMD е на дъното на универса
assert re.fullmatch(r"RS rating \d+ < 70", screener.explain_exclusion("AMD", frame("AMD"), SPY, low))
assert screener.explain_exclusion("AMD", frame("AMD"), SPY, {"X": 1.0}) is None and "по-малко от 260" in screener.explain_exclusion("X", frame("EXPD").iloc[:100], SPY, SC)
print("  ✓ РЕАЛЕН EXPD към 06.10: 'RS линия 95.9% от 52-седмичния максимум < 97%' (към 05.10 — технически ОК); AGNC, A, CRWD, AAPL — първият филтър с числата; съвпада със screener._evaluate_technicals "
      "(по ВСИЧКИ 903 реални тикъра на 06.10: 0 разминавания — измерено при писането)")

print()
print("── yfinance: един и няколко тикъра, MultiIndex и плоски колони ──")
def stub_download(kind):
    def dl(tickers, **kw):
        if tickers == "SPY":
            return pd.DataFrame({"Close": SPY})
        ts = list(tickers)
        parts = {t: pd.DataFrame({"High": frame(t)["High"], "Low": frame(t)["Low"], "Close": frame(t)["Close"], "Volume": frame(t)["Volume"]}) for t in ts}
        if len(ts) == 1 and kind == "flat":
            return parts[ts[0]]
        return pd.concat(parts, axis=1)                                                                                              # колони (тикър, поле), както group_by="ticker"
    return dl
screener.LAST_RS_SCORES.clear(); screener.LAST_RS_SCORES.update(SC)
for kind in ("multi", "flat"):
    screener.yf.download = stub_download(kind)
    one = screener.explain_exits(["EXPD"])
    assert one == {"EXPD": "RS линия 95.9% от 52-седмичния максимум < 97%"}, (kind, one)
screener.yf.download = stub_download("multi")
many = screener.explain_exits(["EXPD", "AGNC", "AMD"])
assert many["EXPD"].startswith("RS линия 95.9%") and many["AGNC"].startswith("цена $8.70") and many["AMD"].startswith("техническите филтри са преминати")
screener.yf.download = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Yahoo"))
assert screener.explain_exits(["EXPD"]) == {} and screener.explain_exits([]) == {}
print("  ✓ explain_exits: един тикър (MultiIndex или плоско) и няколко; технически ОК → 'отпаднал по-късно (CANSLIM/лимит)'; паднал Yahoo → {} без изключение")

print()
print("── редът в книгата и страницата ──")
screener.yf.download = stub_download("multi")
S = backtest.get_buystop_summary()
assert [r["ticker"] for r in S["live"]] == ["EXPD"] and S["live"][0]["status"] == "open" and S["live"][0]["fill_price"] == 194.59 and "screener_exit" not in S["live"][0]
brief_main._annotate_screener_exits(S, present={"AMD"})                                                              # EXPD липсва в днешния списък
assert S["live"][0]["screener_exit"] == "RS линия 95.9% от 52-седмичния максимум < 97%"
S2 = backtest.get_buystop_summary(); brief_main._annotate_screener_exits(S2, present={"EXPD"})                       # тикърът още е в списъка → без причина
assert "screener_exit" not in S2["live"][0]
def book_page(summary):
    return text(render.render_dashboard({**copy.deepcopy(B05), "backtest": {**B05.get("backtest", {}), "buystop": summary}}))
txt = book_page(S)
assert "излезе от скрийнъра: RS линия 95.9% от 52-седмичния максимум < 97%" in txt and "отворена от 2026-10-05" in txt
assert "излезе от скрийнъра" not in book_page(S2)
print("  ✓ редът на EXPD (отворена от 2026-10-05, −0.2R) остава в таблицата на книгата и носи 'излезе от скрийнъра: RS линия 95.9% от 52-седмичния максимум < 97%'; при тикър, който още е в списъка — без причина")

print()
print("── main (структурно) ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
tree = ast.parse(src)
run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
ann = [n for n in ast.walk(run) if isinstance(n, ast.Call) and ast.unparse(n.func) == "setup_rules.annotate"]
assert len(ann) == 1 and ast.unparse(ann[0].args[2]) == "backtest.live_buystop_by_ticker()"
ex = [n for n in ast.walk(run) if isinstance(n, ast.Call) and ast.unparse(n.func) == "_annotate_screener_exits"]
assert len(ex) == 1 and ast.unparse(ex[0].args[0]) == "backtest_summary['buystop']"
assert src.index('backtest_summary["buystop"] = backtest.get_buystop_summary()') < src.index("_annotate_screener_exits(backtest_summary")
print("  ✓ run(): annotate получава живите записи; причините за излизане се смятат веднага след обобщението на книгата (в try/except)")
print()
print("Всички тестове минаха.")
