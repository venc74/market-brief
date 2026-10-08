"""
GLB по Уиш (09.10.2026) · отделна книга с БУКВАЛНОТО правило на Eric Wish — вход при затваряне над зелената линия, изход при първото затваряне под нея, без нашите филтри. Измерване, не препоръка.
Покрива: glb_screener.wish_table / wish_signal (сигналът, независим от картите и хистерезиса), trade_sim.simulate_glb_wish (две граници literal / exec, горна граница на държане, сплит без мрежа),
backtest (категория glb_wish, чист старт, дедуп, независимост от другите книги, повторното допълване на изпълнимия изход, обобщението с праг), dashboard-а и snapshot-а на OI.

РЕАЛНО: tests/fixtures/glb_wish_frames_2026-10-07.json — 900 цели дневни бара до 07.10.2026 на AA, ABBV, ADP, AAPL, NVDA и SPY (Yahoo, split-коригирани, без дивиденти). Реалните примери в тях: AA — пробив 28.05.2024 и изход по линията
04.06.2024; ABBV — пробив 23.06.2026, още отворена; ADP — пробив 29.07.2024, изтекла след 252 сесии; AAPL — изход след една сесия на 07.06.2024 и повторен вход на 11.06.2024. Линията, сигналът и доходностите се
смятат в теста НЕЗАВИСИМО (речник по месец и ръчен цикъл), не с кода, който се проверява. СИНТЕТИЧНО (маркирано): записът за сплит (NVDA, реални барове, цени в "старата скала"), сигналите с липсващ бар/под линията,
праговите записи (24 затворени записа), граничните стойности в обобщението и подменените yf.download.
Пускане: python test_glb_wish.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib, datetime as dt, importlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import config
from src import backtest, trade_sim, glb_screener as g, render

_tmp = tempfile.TemporaryDirectory(prefix="mb_glbwish_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
config.ENABLE_BACKTEST = True
config.TRACK_GLB_WISH = True
config.GLB_WISH_TRACK_FROM = ""                                  # тук се тества книгата; чистият старт има свой раздел по-долу
config.GLB_WISH_MAX_HOLD_SESSIONS = 252
backtest.enrich.earnings_recap = lambda t: None

FX = json.loads((ROOT / "tests" / "fixtures" / "glb_wish_frames_2026-10-07.json").read_text(encoding="utf-8"))["frames"]
BARS = {t: pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"]}, index=pd.to_datetime(d["dates"])) for t, d in FX.items()}
assert {t: len(b) for t, b in BARS.items()} == {t: 900 for t in ("AA", "ABBV", "ADP", "AAPL", "NVDA", "SPY")}
STOCKS = ("AA", "ABBV", "ADP", "AAPL", "NVDA")


def indep(sym):
    """НЕЗАВИСИМО смятане на правилото: речник месец → последен close; за всеки ден линията е максимумът на предходните месеци, първата му поява определя 'месеците непробит'."""
    d = FX[sym]
    dates, c = d["dates"], d["c"]
    months = sorted({x[:7] for x in dates})
    last = {}
    for x, v in zip(dates, c):
        last[x[:7]] = v                                          # последният close на месеца (датите са във възходящ ред)
    out = []
    for x, v in zip(dates, c):
        k = months.index(x[:7])
        prior = [last[m] for m in months[:k]]
        if k < config.GLB_MIN_MONTHS_UNPENETRATED + 1:
            out.append((False, None, None))
            continue
        mx = max(prior)
        pos = prior.index(mx)
        out.append((v > mx and (k - pos - 1) >= config.GLB_MIN_MONTHS_UNPENETRATED, mx, k - pos - 1))
    return out


print("── 1. сигналът: wish_table = независимо смятане, ден по ден, върху РЕАЛНИТЕ барове ──")
tot = sig = fresh_n = 0
for sym in STOCKS:
    t = g.wish_table(BARS[sym]["Close"])
    ind = indep(sym)
    assert len(t) == len(ind) == 900
    prev = (False, None)
    for i, (flag, line, unpen) in enumerate(ind):
        row = t.iloc[i]
        assert bool(row["signal"]) == flag, (sym, t.index[i], flag, row.to_dict())
        if flag:
            assert abs(row["line"] - line) < 1e-9 and int(row["months_unpen"]) == unpen, (sym, t.index[i])
        want_fresh = flag and not (prev[0] and prev[1] == line)
        assert bool(row["fresh"]) == want_fresh, (sym, t.index[i])
        prev = (flag, line)
        tot += 1; sig += flag; fresh_n += want_fresh
print(f"  ✓ {tot} реални (тикър, ден) двойки: сигнал {sig}, от тях свежи пробиви {fresh_n} — съвпада с ръчното смятане във всеки ден (линия, месеци непробит, свежест)")
cm = 0
for sym in STOCKS:
    h = BARS[sym]
    mc = h["Close"].resample("ME").last().dropna()
    per = mc.index.to_period("M")
    t = g.wish_table(h["Close"])
    for d in list(t.index[::9]) + list(t.index[t["signal"].to_numpy()][:15]):
        r = g._monthly_duration_check(pd.concat([mc[per < d.to_period("M")], pd.Series([float(h["Close"].loc[d])], index=[d])]), 0.0)
        assert (r is not None) == bool(t.loc[d, "signal"]), (sym, d)
        cm += 1
print(f"  ✓ и срещу производствената проверка _monthly_duration_check (без буфер): {cm} реални дни, нито една разлика — книгата е същото правило като месечния гейт на картите, без +1% буфера")

print()
print("── 2. wish_signal: свежият пробив на последния ЦЯЛ бар ──")
h_aa = BARS["AA"]
cut = h_aa.loc[:"2024-05-28"]
s = g.wish_signal(cut, "2024-05-29")
assert s and s["signal_date"] == "2024-05-28" and s["glb_type"] in ("classic", "momentum", "insufficient_history") and s["close"] > s["line"] > 0 and s["months_unpenetrated"] >= 3
assert abs(s["close"] - float(cut["Close"].iloc[-1])) < 1e-3 and abs(s["line"] - indep("AA")[list(h_aa.index).index(pd.Timestamp("2024-05-28"))][1]) < 1e-3
print(f"  ✓ РЕАЛЕН AA на 28.05.2024: пробив над ${s['line']:.2f} (месец {s['prior_high_month']}, {s['months_unpenetrated']} месеца непробит), close ${s['close']:.2f}, наш етикет «{s['glb_type']}» (само етикет, не филтър)")
assert g.wish_signal(cut, "2024-05-28") is None                  # частичният бар на днешната сесия не е затваряне: отрязва се, а предишният не е бил пробив
nxt = g.wish_signal(h_aa.loc[:"2024-05-29"], "2024-05-30")
assert nxt is None
print("  ✓ бар с дата >= деня на брифа се отрязва (ръчно пускане в хода на деня); денят след пробива НЕ е нов сигнал (продължение)")
with contextlib.redirect_stdout(io.StringIO()):
    assert g.wish_signal(cut.iloc[:50], "2024-05-29") is None and g.wish_signal(None, "2024-05-29") is None
print("  ✓ кратка история / липсваща серия → None (graceful)")

print()
print("── 3. симулацията върху реални примери: две граници, независимо смятане ──")
def sim(sym, signal_date, bars=None):
    h = BARS[sym] if bars is None else bars
    i = list(BARS[sym].index).index(pd.Timestamp(signal_date))
    line = indep(sym)[i][1]
    return trade_sim.simulate_glb_wish({"signal_date": signal_date, "line": line, "signal_close": FX[sym]["c"][i]}, h[["Open", "Close"]], dt.date(2026, 10, 8)), line, i

res, line, i = sim("AA", "2024-05-28")
d = FX["AA"]
assert res["status"] == "line_exit" and res["fill_date"] == "2024-05-28" and res["exit_date"] == "2024-06-04" and res["hold_sessions"] == 5
j = i + 5
assert d["dates"][j] == "2024-06-04" and d["c"][j] < line <= min(d["c"][i + 1:j]) + 1e-9 or all(x >= line for x in d["c"][i + 1:j])    # първото затваряне под линията (ръчно)
assert res["fill_price"] == round(d["c"][i], 4) and res["exit_price"] == round(d["c"][j], 4)
assert res["return_pct"] == round((d["c"][j] / d["c"][i] - 1) * 100, 2) < 0                      # литерално: вход над линията, изход под нея = загуба по построение
assert res["fill_exec_date"] == d["dates"][i + 1] and res["exit_exec_date"] == d["dates"][j + 1]
assert res["return_pct_exec"] == round((d["o"][j + 1] / d["o"][i + 1] - 1) * 100, 2)
print(f"  ✓ AA (реален): вход ${res['fill_price']} на 28.05, първо затваряне под линията ${res['line_used']:.2f} на 04.06 (${res['exit_price']}) → literal {res['return_pct']:+.2f}%, exec (отваряне 29.05 → отваряне 05.06) {res['return_pct_exec']:+.2f}% — съвпада с ръчния цикъл")
# SPY за същите дати
spy = BARS["SPY"]
want_l = round((FX["SPY"]["c"][j] / FX["SPY"]["c"][i] - 1) * 100, 2)
want_e = round((FX["SPY"]["o"][j + 1] / FX["SPY"]["o"][i + 1] - 1) * 100, 2)
assert trade_sim.spy_return_pct_gw(res, spy[["Open", "Close"]], False) == want_l and trade_sim.spy_return_pct_gw(res, spy[["Open", "Close"]], True) == want_e
print(f"  ✓ SPY за същите дати: literal (close → close) {want_l:+.2f}%, exec (отваряне → отваряне) {want_e:+.2f}%")

res, line, i = sim("ABBV", "2026-06-23")
assert res["status"] == "open" and res["resolution_date"] is None and res["exit_date"] is None and res["fill_date"] == "2026-06-23" and res["hold_sessions"] == 899 - i
assert res["last_close_date"] == "2026-10-07" and res["current_return_pct"] == res["return_pct"] == round((FX["ABBV"]["c"][-1] / FX["ABBV"]["c"][i] - 1) * 100, 2) > 0
assert res["dist_to_line_pct"] == round((FX["ABBV"]["c"][-1] / line - 1) * 100, 2) and all(x >= line for x in FX["ABBV"]["c"][i + 1:])
print(f"  ✓ ABBV (реален): още отворена от 23.06.2026 ({res['hold_sessions']} сесии), mark-to-market {res['return_pct']:+.2f}%, {res['dist_to_line_pct']:+.1f}% над линията — нито едно затваряне под нея")

res, line, i = sim("ADP", "2024-07-29")
assert res["status"] == "expired" and res["how"] == "mtm" and res["hold_sessions"] == 252 and res["exit_date"] == FX["ADP"]["dates"][i + 252] == "2025-07-31"
assert all(x >= line for x in FX["ADP"]["c"][i + 1:i + 253]) and res["return_pct"] == round((FX["ADP"]["c"][i + 252] / FX["ADP"]["c"][i] - 1) * 100, 2) > 0
print(f"  ✓ ADP (реален): 252 сесии без затваряне под линията → «изтекла» на 31.07.2025 по затварянето, {res['return_pct']:+.2f}% (граница на държане, наша)")
config.GLB_WISH_MAX_HOLD_SESSIONS = 0
res0, _, _ = sim("ADP", "2024-07-29")
config.GLB_WISH_MAX_HOLD_SESSIONS = 252
assert res0["status"] in ("open", "line_exit") and res0["hold_sessions"] > 252
print(f"  ✓ без граница (0) същият запис не изтича: статус «{res0['status']}», {res0['hold_sessions']} сесии — границата е само конфигурация")

r1, _, _ = sim("AAPL", "2024-06-07")
r2, _, _ = sim("AAPL", "2024-06-11")
assert r1["status"] == "line_exit" and r1["hold_sessions"] == 1 and r2["fill_date"] == "2024-06-11" and r2["fill_date"] > r1["exit_date"]
print(f"  ✓ AAPL (реален): изход след {r1['hold_sessions']} сесия на {r1['exit_date']} ({r1['return_pct']:+.2f}%) и повторен вход на 11.06.2024 — whipsaw-ът се брои като две отделни сделки")

print()
print("── 4. сплит без мрежа (СИНТЕТИЧЕН запис върху РЕАЛНИ барове на NVDA, 10:1 на 10.06.2024) ──")
nv = FX["NVDA"]
k = nv["dates"].index("2024-05-30")
close_new = nv["c"][k]                                           # реалният close в сегашната (split-коригирана) скала
rec_old = {"signal_date": "2024-05-30", "line": 1000.0, "signal_close": round(close_new * 10, 4)}      # СИНТЕТИЧНО: записът е правен преди сплита, в старата скала (×10)
r = trade_sim.simulate_glb_wish(rec_old, BARS["NVDA"][["Open", "Close"]].iloc[:k + 30], dt.date(2024, 7, 10))
assert r["split_scale"] == 10.0 and abs(r["line_used"] - 100.0) < 1e-6 and r["status"] == "open" and r["fill_price"] == round(close_new, 4)
rec_naive = {"signal_date": "2024-05-30", "line": 1000.0}        # същото без съхранения close: линията остава ×10 → фалшив изход още на следващия ден
rn = trade_sim.simulate_glb_wish(rec_naive, BARS["NVDA"][["Open", "Close"]].iloc[:k + 30], dt.date(2024, 7, 10))
assert rn["status"] == "invalid_signal"
rec_naive2 = {"signal_date": "2024-05-30", "line": 100.0, "signal_close": close_new}
assert trade_sim.simulate_glb_wish(rec_naive2, BARS["NVDA"][["Open", "Close"]].iloc[:k + 30], dt.date(2024, 7, 10))["split_scale"] is None
print(f"  ✓ съхранен close ${rec_old['signal_close']} срещу бара ${close_new:.2f} → съотношение 10 → линията $1000 става ${r['line_used']:.0f}; позицията остава отворена (без мрежова заявка); без мащабиране записът би бил невалиден")

print()
print("── 5. невалидни и чакащи сигнали (СИНТЕТИЧНИ записи върху реални барове) ──")
ab = BARS["ABBV"][["Open", "Close"]]
assert trade_sim.simulate_glb_wish({"signal_date": "2027-01-04", "line": 1.0, "signal_close": 2.0}, ab)["status"] == "pending"
inv = trade_sim.simulate_glb_wish({"signal_date": "2026-06-20", "line": 100.0, "signal_close": 100.0}, ab)           # събота — няма бар, а по-късни има
assert inv["status"] == "invalid_signal" and inv["how"] == "no_bar"
hi_line = trade_sim.simulate_glb_wish({"signal_date": "2026-06-23", "line": 1e6, "signal_close": FX["ABBV"]["c"][list(BARS["ABBV"].index).index(pd.Timestamp("2026-06-23"))]}, ab)
assert hi_line["status"] == "invalid_signal" and hi_line["how"] == "not_above_line" and trade_sim.simulate_glb_wish({"signal_date": "2026-06-23", "line": 1.0}, None)["status"] == "pending"
print("  ✓ сигнален бар още липсва → pending; събота (няма бар) → invalid_signal; close не е над линията → invalid_signal; празни барове → pending")

print()
print("── 6. книгата в tracker-а: ingest, чист старт, дедуп, независимост ──")
def card(sym, signal_date):
    i = list(BARS[sym].index).index(pd.Timestamp(signal_date))
    sg = g.wish_signal(BARS[sym].loc[:signal_date], (pd.Timestamp(signal_date) + pd.Timedelta(days=1)).date().isoformat())
    assert sg, (sym, signal_date)
    return {"ticker": sym, **sg}
AA, AAPL1, AAPL2, ADP = card("AA", "2024-05-28"), card("AAPL", "2024-06-07"), card("AAPL", "2024-06-11"), card("ADP", "2024-07-29")
tr = {}
backtest._ingest_glb_wish_list(tr, "2024-05-29", [AA], "Offensive")
rec = tr["AA_2024-05-29_gw"]
assert (rec["method"], rec["category"], rec["status"], rec["regime"], rec["signal_date"], rec["glb_type"]) == ("v2", "glb_wish", "pending", "Offensive", "2024-05-28", AA["glb_type"])
assert rec["line"] == round(AA["line"], 4) and rec["signal_close"] == round(AA["close"], 4) and not backtest.is_action_record(rec) and backtest.record_category(rec) == "glb_wish"
backtest._ingest_glb_wish_list(tr, "2024-05-29", [AA], "Offensive")
backtest._ingest_glb_wish_list(tr, "2024-05-30", [{**AA, "signal_date": "2024-05-29"}], "Offensive")       # продължение (позицията е жива) → не е нов запис
assert len(tr) == 1
for bad in ({**AA, "ticker": None}, {**AA, "line": 0}, {**AA, "close": AA["line"] - 1}, {**AA, "signal_date": None}, {**AA, "close": True}):
    backtest._ingest_glb_wish_list(tr, "2024-06-03", [bad], "Offensive")
assert len(tr) == 1
config.TRACK_GLB_WISH = False
backtest._ingest_glb_wish_list(tr, "2024-06-03", [ADP], "Offensive")
config.TRACK_GLB_WISH = True
assert len(tr) == 1
print("  ✓ запис «AA_2024-05-29_gw» (категория glb_wish, линия и близане от сигнала, етикет, режим); повторение и продължение не правят втори запис; сигнал без тикър/линия/дата, под линията или с булева стойност — пропуска се; TRACK_GLB_WISH=0 изключва")

config.GLB_WISH_TRACK_FROM = "2024-06-01"
t2 = {}
backtest._ingest_glb_wish_list(t2, "2024-05-29", [AA], "Offensive")
assert t2 == {}
backtest._ingest_glb_wish_list(t2, "2024-06-01", [AA], "Offensive")
assert len(t2) == 1
config.GLB_WISH_TRACK_FROM = ""
print("  ✓ чист старт: запис с дата на брифа преди GLB_WISH_TRACK_FROM не влиза (и от snapshot-ите), на самата дата влиза")

# независимост от другите книги и четците
t3 = {}
backtest._ingest_glb_wish_list(t3, "2024-06-12", [AAPL2], "Defensive")
t3["AAPL_2024-06-12_gw"].update(status="open", fill_date="2024-06-11")
backtest._ingest_action_list(t3, "2024-06-12", [{"ticker": "AAPL", "plan": {"method": "v2", "buy_stop": 200.0, "max_chase": 210.0, "stop_loss": 190.0, "target_1": 220.0, "entry_mid": 201.0}}])
assert sorted(backtest.record_category(x) for x in t3.values()) == ["action", "glb_wish"]               # Action за същия тикър в същия ден НЕ е продължение на книгата на Уиш
backtest._save_tracker(t3)
from src import main as brief_main
assert list(brief_main._live_positions()) == [] or all(backtest.is_action_record(v) for v in brief_main._live_positions().values())
t3["AAPL_2024-06-12_gw"]["status"] = "open"
live = {k: v for k, v in t3.items() if backtest.is_action_record(v) and v.get("status") in ("open", "trailing")}
assert "AAPL_2024-06-12_gw" not in live
assert "glb_wish" in (ROOT / "src" / "oi_snapshot.py").read_text(encoding="utf-8")
print("  ✓ Action и glb_wish за един и същи тикър са независими записи; is_action_record е False за книгата → _live_positions / OPEN✓ / обобщението на Action я не броят")

print()
print("── 7. пълният път: snapshot → ingest → резолюция през backtest._resolve_open_positions ──")
CUTD = {"v": None}
def fake_download(tickers, start=None, progress=False, auto_adjust=False, **kw):
    cols = ["Open", "High", "Low", "Close"]
    fr = {t: BARS[t][(BARS[t].index >= pd.Timestamp(start)) & (BARS[t].index <= pd.Timestamp(CUTD["v"]))] if start else BARS[t] for t in tickers}
    return pd.concat({f: pd.DataFrame({t: fr[t][f] for t in tickers}) for f in cols}, axis=1)
backtest.yf.download = fake_download
for f in config.DATA_DIR.glob("*.json"):
    f.unlink()
snap = {"date": "2024-05-29", "action": [], "watchlist": [], "thermometer": {"regime": "Offensive"}, "glb_wish": [AA]}
(config.DATA_DIR / "2024-05-29.json").write_text(json.dumps(snap), encoding="utf-8")
(config.DATA_DIR / "2024-05-28.json").write_text(json.dumps({"date": "2024-05-28", "action": [], "watchlist": [], "thermometer": {"regime": "Offensive"}}), encoding="utf-8")   # стар snapshot без ключа
backtest._save_tracker({})
tr = backtest._load_tracker()
backtest._ingest_new_positions(tr, today_date=None)
assert sorted(tr) == ["AA_2024-05-29_gw"] and tr["AA_2024-05-29_gw"]["regime"] == "Offensive"
print("  ✓ snapshot-ът с 'glb_wish' се възстановява (режимът е от snapshot-а), старият без ключа — не; днешният списък също влиза")

CUTD["v"] = "2024-05-30"                                          # денят след пробива: сигналният бар е в данните, следващата сесия вече е започнала
backtest._resolve_open_positions(tr, dt.date(2024, 5, 30))
r = tr["AA_2024-05-29_gw"]
assert r["status"] == "open" and r["fill_date"] == "2024-05-28" and r["fill_exec_date"] == "2024-05-29" and r["resolution_date"] is None and r["entry_price"] == r["fill_price"]
assert r["spy_return_pct"] is not None and r["alpha_pct"] == round(r["return_pct"] - r["spy_return_pct"], 2)
print(f"  ✓ на 30.05.2024: статус «open», вход ${r['fill_price']} (literal) / ${r['fill_exec_price']} (exec, отваряне 29.05), mark-to-market {r['return_pct']:+.2f}%, SPY {r['spy_return_pct']:+.2f}%")

CUTD["v"] = "2024-06-04"                                          # денят на затварянето под линията: изпълнимият изход (отваряне на 05.06) още не съществува
backtest._resolve_open_positions(tr, dt.date(2024, 6, 5))
r = tr["AA_2024-05-29_gw"]
assert r["status"] == "line_exit" and r["resolution_date"] == "2024-06-04" and r["exit_exec_date"] is None and r["return_pct_exec"] is None and r["return_pct"] < 0 and r["discovered_date"] == "2024-06-05"
assert backtest._gw_needs_exec_fill(r, dt.date(2024, 6, 5)) and not backtest._gw_needs_exec_fill(r, dt.date(2024, 6, 20))
CUTD["v"] = "2024-06-05"
backtest._resolve_open_positions(tr, dt.date(2024, 6, 6))
r = tr["AA_2024-05-29_gw"]
want = trade_sim.simulate_glb_wish({"signal_date": "2024-05-28", "line": r["line"], "signal_close": r["signal_close"]}, BARS["AA"][["Open", "Close"]].loc[:"2024-06-05"], dt.date(2024, 6, 6))
assert r["exit_exec_date"] == "2024-06-05" and r["return_pct_exec"] == want["return_pct_exec"] and r["alpha_pct_exec"] is not None and r["status"] == "line_exit"
assert not backtest._gw_needs_exec_fill(r, dt.date(2024, 6, 6))
CUTD["v"] = "2024-06-10"
before = copy.deepcopy(r)
backtest._resolve_open_positions(tr, dt.date(2024, 6, 10))
assert tr["AA_2024-05-29_gw"] == before                           # приключилият запис вече не се пипа
print(f"  ✓ на 05.06: затворена по линията, exec изходът още липсва ({r['return_pct']:+.2f}% literal) → записът се резолвира още веднъж и на 06.06 получава exec {r['return_pct_exec']:+.2f}% (= директната симулация); после не се пипа")

print()
print("── 8. обобщението: праг, групи, отметки (СИНТЕТИЧНИ записи за праговете) ──")
def mk(i, status, ret, exe=None, spy=1.0, typ="classic", regime="Offensive", entry="2026-08-03"):
    return {"method": "v2", "category": "glb_wish", "ticker": f"T{i}", "entry_date": entry, "signal_date": entry, "status": status, "glb_type": typ, "regime": regime, "line": 10.0, "line_used": 10.0,
            "fill_price": 11.0, "last_close": 11.0, "return_pct": ret, "return_pct_exec": exe if exe is not None else ret, "current_return_pct": ret, "dist_to_line_pct": 5.0, "hold_sessions": 7,
            "resolution_date": None if status in ("open", "pending") else "2026-08-10", "spy_return_pct": spy, "spy_return_pct_exec": spy, "alpha_pct": round(ret - spy, 2), "alpha_pct_exec": round((exe if exe is not None else ret) - spy, 2)}
rows = {}
for i in range(19):
    rows[f"T{i}_gw"] = mk(i, "line_exit", -2.0 - i * 0.1, typ="momentum" if i % 2 else "classic")
rows["T19_gw"] = mk(19, "expired", 30.0, typ="classic")
S19 = (lambda: (backtest._save_tracker({k: v for k, v in rows.items() if k != "T19_gw"}), backtest.get_glb_wish_summary())[1])()
assert S19["with_result"] == 19 and not S19["stats_visible"] and S19["all"]["win_rate_pct"] is None and S19["all"]["median_return_pct"] is None and S19["all"]["avg_alpha_pct"] is None and S19["all"]["avg_return_pct"] is not None
assert all(g_["avg_return_pct"] is None for g_ in S19["by_type"].values())
backtest._save_tracker(rows)
S20 = backtest.get_glb_wish_summary()
rl = sorted(v["return_pct"] for v in rows.values())
assert S20["with_result"] == 20 and S20["stats_visible"] and S20["records"] == 20 and S20["line_exit"] == 19 and S20["expired"] == 1 and S20["open"] == 0
assert S20["all"]["n"] == 20 and S20["all"]["avg_return_pct"] == round(sum(rl) / 20, 2) and S20["all"]["win_rate_pct"] == 5.0 and S20["all"]["win_ci_pct"] is not None
assert S20["all"]["median_return_pct"] == round((rl[9] + rl[10]) / 2, 2) and S20["line_exit_group"]["n"] == 19 and S20["line_exit_group"]["win_rate_pct"] == 0.0 and S20["held_group"]["n"] == 1
assert S20["all"]["avg_alpha_pct"] == round(sum(v["alpha_pct"] for v in rows.values()) / 20, 2) and S20["all"]["beat_spy_pct"] == 5.0
assert S20["by_type"]["classic"]["records"] == 11 and S20["by_type"]["momentum"]["records"] == 9 and S20["by_regime"]["Offensive"]["records"] == 20
print(f"  ✓ при 19 записа с резултат: само броят и средната доходност ({S19['all']['avg_return_pct']:+.2f}%); при 20-я: win rate {S20['all']['win_rate_pct']}%, медиана {S20['all']['median_return_pct']:+.2f}%, алфа {S20['all']['avg_alpha_pct']:+.2f}%, групите (изход по линията n=19 → 0% печеливши; държани n=1) — всичко сверено независимо")
assert S20["line_exit_group"]["win_rate_pct"] == 0.0
live_rows = {f"L{i}_gw": mk(100 + i, "open", 5.0 + i, entry=f"2026-09-{1 + i:02d}") for i in range(17)}
rows.update(live_rows)
backtest._save_tracker(rows)
SL = backtest.get_glb_wish_summary()
assert SL["open"] == 17 and len(SL["live"]) == 15 and SL["live_total"] == 17 and SL["live"][0]["entry_date"] >= SL["live"][-1]["entry_date"] and len(SL["recent"]) == 10
print("  ✓ отворените са най-новите 15 от 17 (с брой на всички), последно затворените — 10")
config.TRACK_GLB_WISH = False
assert backtest.get_glb_wish_summary() == {}
config.TRACK_GLB_WISH = True

print()
print("── 9. страницата ──")
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
with contextlib.redirect_stdout(io.StringIO()):
    page_old = render.render_dashboard(copy.deepcopy(B05))
assert "GLB по Уиш · книга" not in page_old
print("  ✓ стар бриф без ключа 'glb_wish' в backtest → секцията я няма и страницата се рендерира")
b = copy.deepcopy(B05)
b.setdefault("backtest", {})["glb_wish"] = SL
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b)
sec = page[page.index("GLB по Уиш · книга"):]
sec = sec[:sec.index("</section>")]
assert "измерване, не препоръка" in page[page.index("GLB по Уиш · книга"):][:200] and "Буквалното правило на Eric Wish без нашите филтри" in sec and "оцелели" in sec and "тесен" not in sec.lower()
assert "Измерване — книга glb_wish: записани 37" in sec and f"win rate {SL['all']['win_rate_pct']}%" in sec and "по построение загуби" in sec and "тук е цялата печалба" in sec
assert sec.count("<tr><td class=\"sym\">T1") >= 10 and "от 17, най-новите" in sec and "и Action" not in sec
print("  ✓ СИНТЕТИЧНИ записи от точка 8 в РЕАЛНАТА страница от 05.10: секция «GLB по Уиш · книга (измерване, не препоръка)» с честното описание (буквално правило, оцелели, без тесен), реда за 37 записа, win rate от обобщението, обяснението за групите, 15 отворени «от 17, най-новите»")
b2 = copy.deepcopy(B05)
b2.setdefault("backtest", {})["glb_wish"] = {"enabled": True, "track_from": "2026-10-09", "max_hold_sessions": 252, "records": 0, "pending": 0, "open": 0, "line_exit": 0, "expired": 0, "invalid": 0, "with_result": 0,
        "min_entries": 20, "stats_visible": False, "also_action": 0, "also_buystop": 0, "also_qm": 0, "all": {}, "line_exit_group": {}, "held_group": {}, "by_type": {}, "by_regime": {}, "live": [], "live_total": 0, "recent": []}
with contextlib.redirect_stdout(io.StringIO()):
    page_empty = render.render_dashboard(b2)
assert "Още няма записани пробиви" in page_empty and "от 2026-10-09 нататък" in page_empty and "статистика след 20 записа" in page_empty
print("  ✓ празната книга казва, че още няма записи и от коя дата се записва")

print()
print("── 10. свързването: screen() → main → tracker → snapshot; OI снимката не взема позициите на книгата ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "glb_wish_signals = list(glb_screener.LAST_WISH_SIGNALS)" in src and "update_backtest_tracker(action, today, watchlist, thermo.get(\"regime\"), qm_cards, glb_wish_signals)" in src
assert '"glb_wish": glb_wish_signals' in src and 'backtest_summary["glb_wish"] = backtest.get_glb_wish_summary()' in src
print("  ✓ main.run: сигналите от screen() отиват в update_backtest_tracker, snapshot-ът носи 'glb_wish', обобщението е в backtest['glb_wish']")
g._verified_company_name = lambda s: {"name": s, "verified": True}
cutoff = "2024-05-28"
big = pd.concat({t: BARS[t].loc[:cutoff].assign(**{"Stock Splits": 0.0}) for t in STOCKS}, axis=1)
g.yf = type("Y", (), {"download": staticmethod(lambda batch, **kw: big[list(batch)])})
g.time = type("T", (), {"sleep": staticmethod(lambda s: None)})
state = pathlib.Path(_tmp.name) / "glb_state.json"
with contextlib.redirect_stdout(io.StringIO()):
    g.screen(universe=list(STOCKS), batch_size=50, state_path=state, today="2024-05-29")
sig = {w["ticker"]: w for w in g.LAST_WISH_SIGNALS}
def fresh_at(t, day):
    ind, k = indep(t), FX[t]["dates"].index(day)
    return ind[k][0] and not (ind[k - 1][0] and ind[k - 1][1] == ind[k][1])
want = {t: fresh_at(t, cutoff) for t in STOCKS}                                           # свеж пробив на последния бар на отрязаните данни (независимо)
assert set(sig) == {t for t, v in want.items() if v} == {"AA"}, (sig.keys(), want)
assert sig["AA"]["signal_date"] == "2024-05-28" and sig["AA"]["line"] == AA["line"]
print("  ✓ screen() върху реалните барове до 28.05.2024: свеж пробив има само AA (независимото смятане за петте тикъра го потвърждава); LAST_WISH_SIGNALS се нулира при всяко извикване")
g.yf = type("Y", (), {"download": staticmethod(lambda batch, **kw: (_ for _ in ()).throw(RuntimeError("мрежата падна")))})
with contextlib.redirect_stdout(io.StringIO()):
    g.screen(universe=list(STOCKS), batch_size=50, state_path=pathlib.Path(_tmp.name) / "glb_state2.json", today="2024-05-29")
assert g.LAST_WISH_SIGNALS == []
print("  ✓ провал на тегленето → празен списък (книгата просто не получава нови записи, нищо не гърми)")
from src import oi_snapshot
config.UNUSUAL_OPTIONS_SNAPSHOT_BRIEF_DAYS = 0
tk = {"method": "v2", "status": "open", "ticker": "KEEP"}
backtest._save_tracker({"a": tk, "b": {**mk(1, "open", 3.0), "ticker": "GWONLY"}, "c": {"method": "v2", "category": "qm_breakout", "status": "pending", "ticker": "QMT"}})
got = oi_snapshot.snapshot_tickers(0)
assert "KEEP" in got and "QMT" in got and "GWONLY" not in got
print("  ✓ следобедната OI снимка взема позициите на Action / buy-stop / QM, но не и на книгата на Уиш (до стотици тикъри, без опционен маркер)")
print("\n✅ test_glb_wish: всичко мина")
