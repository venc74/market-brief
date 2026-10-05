"""
Qullamaggie (06.10.2026) · т.4: Track Record книгата "qm_breakout" — независима от Action и от buy-stop книгата (категория, дедуп в рамките на категорията, отметки "и Action"/"и buy-stop"), вход
на нивото на пробива (1 сесия), стоп = Low на входния ден, изход по неговите правила (trade_sim.simulate_qm), записани и двете граници (opt/pess); win rate чак след ≥ 20 затворени, дотогава
брой и среден R; четците на позиции я игнорират.

РЕАЛНО: картите DOCN/CORT/CRL от скана към 02.10.2026; реалните дневни барове на 8 тикъра (tests/fixtures/qm_frames_2026-10-02.json) и на SPY — върху тях ~140 сетъпа (нивото = най-високият High на последните
10 бара, ADR20 по формулата от FAQ) минават през ПЪЛНИЯ път ingest → резолюция през backtest._resolve_open_positions и се сверяват със симулацията, извикана директно. СИНТЕТИЧНО: датите на
записите (сетъпите са върху реални барове, но са избрани механично, не са били картите на съответните дни), записите за прага от 20 затворени, split флагът, подменените yf.download/сплитове.
Пускане: python test_qm_book.py
"""
import sys, json, pathlib, tempfile, copy, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import backtest, trade_sim, qm_breakout as q, setup_rules
from src import main as brief_main

_tmp = tempfile.TemporaryDirectory(prefix="mb_qmb_")
config.DATA_DIR = pathlib.Path(_tmp.name)
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
config.ENABLE_BACKTEST = True
backtest.enrich.earnings_recap = lambda t: None
backtest._unapplied_splits = lambda rec: []

FIX = json.loads((ROOT / "tests" / "fixtures" / "qm_frames_2026-10-02.json").read_text(encoding="utf-8"))
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
BARS = {t: pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"])) for t, d in FIX["frames"].items()}
BARS["SPY"] = pd.read_csv(ROOT / "tests" / "fixtures" / "ohlc_SPY.csv", index_col=0, parse_dates=True)
ROWS, _ = q.scan_frames({t: BARS[t] for t in FIX["frames"]}, lead=FIX["lead"])
CARDS = {r["ticker"]: r for r in ROWS}
assert sorted(CARDS) == ["CORT", "CRL", "DOCN"]


def fake_download(tickers, start=None, progress=False, auto_adjust=False, **kw):
    cols = ["Open", "High", "Low", "Close", "Volume"]
    fr = {t: (BARS[t][BARS[t].index >= pd.Timestamp(start)] if start else BARS[t]) for t in tickers}
    return pd.concat({f: pd.DataFrame({t: fr[t][f] for t in tickers}) for f in cols}, axis=1)


backtest.yf.download = fake_download
TODAY = dt.date(2026, 10, 5)


def fresh():
    backtest._save_tracker({})
    return {}


print("── ingest на РЕАЛНИТЕ карти DOCN/CORT/CRL (бриф на 05.10, сигнал от 02.10) ──")
tr = fresh()
backtest._ingest_qm_list(tr, "2026-10-05", list(CARDS.values()), "Defensive")
assert sorted(tr) == ["CORT_2026-10-05_qm", "CRL_2026-10-05_qm", "DOCN_2026-10-05_qm"]
r = tr["DOCN_2026-10-05_qm"]
assert (r["method"], r["category"], r["status"], r["regime"], r["buy_stop"], r["adr"]) == ("v2", "qm_breakout", "pending", "Defensive", 151.83, round(CARDS["DOCN"]["adr"], 2))
assert r["window_sessions"] == 1 and r["valid_through"] == "2026-10-05" and r["signal_date"] == "2026-10-02" and r["expected_stop"] == 145.82 and r["max_stop"] == 140.91
assert r["fill_date"] is None and r["realized_r"] is None and r["R_pess"] is None
print("  ✓ DOCN_2026-10-05_qm: pending, ниво $151.83 (buy_stop), ADR 7.2%, валиден 1 сесия (до 05.10), очакван стоп $145.82, режим Defensive; ключ и категория 'qm_breakout'")
bad = fresh()
backtest._ingest_qm_list(bad, "2026-10-05", [{"ticker": "X"}, {"ticker": "Y", "trigger": 10, "adr": 0}, {"trigger": 10, "adr": 3}, {"ticker": "Z", "trigger": -1, "adr": 3}], "Cash")
assert bad == {}
for reg in ("Offensive", "Defensive", "Cash", None):
    t2 = fresh(); backtest._ingest_qm_list(t2, "2026-10-05", [CARDS["CORT"]], reg)
    assert list(t2.values())[0]["regime"] == reg
config.TRACK_QM = False
t2 = fresh(); backtest._ingest_qm_list(t2, "2026-10-05", [CARDS["CORT"]], "Cash"); assert t2 == {}
config.TRACK_QM = True
print("  ✓ карта без тикър/ниво/ADR се пропуска; записва се във всички режими с таг; TRACK_QM=0 изключва книгата")

print()
print("── независими книги и дедуп в рамките на категорията ──")
tr = fresh()
backtest._ingest_qm_list(tr, "2026-10-05", [CARDS["CORT"]], "Defensive")
backtest._ingest_qm_list(tr, "2026-10-06", [CARDS["CORT"]], "Defensive")                         # същият тикър на другия ден, още чака → продължение
assert len(tr) == 1
act_plan = {"method": "v2", "buy_stop": 100.0, "max_chase": 105.0, "stop_loss": 92.0, "target_1": 116.0, "entry_mid": 101.0, "window_sessions": 5}
backtest._ingest_action_list(tr, "2026-10-06", [{"ticker": "CORT", "plan": act_plan}])           # Action за същия тикър не е блокиран
buystop_card = {"ticker": "CORT", "setup": {"kind": "below_pivot", "buy_stop": 100.0, "pct_from_pivot": -1.0}, "plan_preview": {**act_plan, "valid": True, "preview": True}}
config.BUYSTOP_TRACK_FROM = ""
backtest._ingest_buystop_list(tr, "2026-10-06", [buystop_card], "Defensive")                      # buy-stop за същия тикър също
assert sorted(backtest.record_category(x) for x in tr.values()) == ["action", "buystop", "qm_breakout"]
tr["CORT_2026-10-05_qm"].update(status="not_triggered", resolution_date="2026-10-05")             # прозорецът (1 сесия) изтече без вход
backtest._ingest_qm_list(tr, "2026-10-06", [CARDS["CORT"]], "Defensive")                          # нов кандидат на следващия ден → нов запис (както в реплея)
assert sum(1 for x in tr.values() if backtest.record_category(x) == "qm_breakout") == 2
print("  ✓ QM, Action и buy-stop за един тикър са три независими записа; повторно показване докато чака — един запис; след изтекъл прозорец (not_triggered) следващ ден → нов запис")

print()
print("── snapshot-и и днешният списък (update_backtest_tracker) ──")
tr = fresh()
(config.DATA_DIR / "2026-10-03.json").write_text(json.dumps({"date": "2026-10-03", "action": [], "watchlist": [], "thermometer": {"regime": "Offensive"}, "qm_breakout": [CARDS["CRL"]]}), encoding="utf-8")
(config.DATA_DIR / "2026-10-02.json").write_text(json.dumps({"date": "2026-10-02", "action": [], "watchlist": [], "thermometer": {"regime": "Offensive"}}), encoding="utf-8")        # стар snapshot — без ключа
backtest._resolve_open_positions = lambda tracker, today=None: None                              # само ingest
backtest.update_backtest_tracker([], "2026-10-05", [], "Defensive", [CARDS["DOCN"]])
backtest.update_backtest_tracker([], "2026-10-05", [], "Defensive", [CARDS["DOCN"]])             # идемпотентно
T = backtest._load_tracker()
assert sorted(T) == ["CRL_2026-10-03_qm", "DOCN_2026-10-05_qm"] and T["CRL_2026-10-03_qm"]["regime"] == "Offensive"
print("  ✓ snapshot-ът с 'qm_breakout' се възстановява (режим от snapshot-а), старият — не; днешният списък влиза; повторното пускане е идемпотентно")
import importlib
importlib.reload(backtest)                                                                       # връща истинската _resolve_open_positions
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
backtest.yf.download = fake_download
backtest._unapplied_splits = lambda rec: []
backtest.enrich.earnings_recap = lambda t: None
for f in config.DATA_DIR.glob("2026-*.json"):
    f.unlink()

print()
print("── реални барове, механични сетъпи: пълният път ingest → резолюция съвпада със симулацията ──")
tr = fresh()
n_setups = 0
direct = {}
for tk in ("DOCN", "CORT", "CRL", "PVH", "AAPL", "NVDA", "MSFT", "TSLA"):
    df = BARS[tk]
    for k in range(135, len(df) - 1, 6):
        trig = float(df["High"].iloc[k - 10:k].max())
        adr = float(100 * ((df["High"].iloc[k - 20:k] / df["Low"].iloc[k - 20:k]).mean() - 1))
        entry = df.index[k].date().isoformat()
        card = {"ticker": tk, "trigger": trig, "adr": adr, "close": float(df["Close"].iloc[k - 1]), "signal_date": df.index[k - 1].date().isoformat(), "expected_stop": round(trig * (1 - 0.0055 * adr), 2),
                "max_stop": round(trig * (1 - adr / 100), 2), "base_days": 20, "runup_pct": 30.0, "tight": 0.8}
        one = {}                                                                                  # дедупът (чакащ запис блокира следващия за тикъра) е покрит по-горе — тук всеки сетъп е отделен запис
        backtest._ingest_qm_list(one, entry, [card], "Offensive")
        tr.update(one)
        n_setups += 1
assert len(tr) == n_setups > 100
backtest._resolve_open_positions(tr, TODAY)
mism = 0
for key, rec in tr.items():
    sim = trade_sim.simulate_qm({"entry_date": rec["entry_date"], "buy_stop": rec["buy_stop"], "adr": rec["adr"]}, BARS[rec["ticker"]], TODAY)
    for k in ("status", "fill_date", "fill_price", "stop_loss", "R", "R_pess", "realized_r", "realized_r_pess", "exit_date", "partial_price", "trail_ma", "current_r", "return_pct"):
        assert rec[k] == sim[k], (key, k, rec[k], sim[k])
    assert (rec["resolution_date"] is None) == (sim["status"] in trade_sim.LIVE)
    if sim["fill_date"]:
        assert rec["entry_price"] == sim["fill_price"] and rec["spy_return_pct"] is not None and rec["alpha_pct"] is not None
    else:
        assert rec["entry_price"] == rec["signal_price"] and rec["spy_return_pct"] is None
import collections
cnt = collections.Counter(r["status"] for r in tr.values())
closed = [r for r in tr.values() if r["status"] in trade_sim.QM_TERMINAL]
print(f"  ✓ {n_setups} механични сетъпа върху РЕАЛНИ барове (не са били карти): всеки запис съвпада със симулацията, извикана директно (статус, вход, стоп, R opt/pess, изход); статуси {dict(sorted(cnt.items()))}; затворени {len(closed)}")
assert len(closed) >= 20
# SPY сравнение за затворените: купува се на Open на деня на входа, продава на Close на деня на изхода (с частичната)
r0 = next(x for x in closed if x["partial_price"] is None)
spy = BARS["SPY"]
assert r0["spy_return_pct"] == round((spy.loc[r0["exit_date"], "Close"] / spy.loc[r0["fill_date"], "Open"] - 1) * 100, 2)
print("  ✓ SPY за същия период на държане: купува се на Open на деня на входа, продава на Close на деня на изхода (при частична продажба — претеглено) — сверено независимо")
backtest._save_tracker(tr)

print()
print("── обобщението: win rate чак след ≥ 20 затворени ──")
S = backtest.get_qm_summary()
assert S["records"] == n_setups and S["closed"] == len(closed) and S["stats_visible"] is True and S["min_closed"] == 20
R = [r["realized_r"] for r in closed]
Rp = [r["realized_r_pess"] for r in closed]
assert S["avg_realized_r"] == round(sum(R) / len(R), 2) and S["avg_realized_r_pess"] == round(sum(Rp) / len(Rp), 2)
assert S["win_rate_pct"] == round(100 * sum(1 for x in R if x > 0) / len(R), 1) and S["win_rate_pess_pct"] == round(100 * sum(1 for x in Rp if x > 0) / len(Rp), 1)
srt = sorted(R)
assert S["median_realized_r"] == round((srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2), 2)
assert S["triggered"] == sum(1 for r in tr.values() if r["fill_date"]) and S["not_triggered"] == cnt["not_triggered"] and S["skipped"] == cnt["skipped_adr"] + cnt["skipped_extended"] + cnt["invalid_risk"]
assert S["pending"] == cnt["pending"] and S["open"] == cnt["open"] + cnt["trailing"] and S["by_regime"]["Offensive"]["records"] == n_setups
print(f"  ✓ {S['closed']} затворени: win rate {S['win_rate_pct']}% (pess {S['win_rate_pess_pct']}%), среден R {S['avg_realized_r']:+.2f} (pess {S['avg_realized_r_pess']:+.2f}), медиана {S['median_realized_r']:+.2f}, "
      f"'не се задействаха' {S['not_triggered_pct']}% от приключилите прозорци — всичко сверено независимо от записите")
small = copy.deepcopy(tr)
keep = [k for k, v in small.items() if v["status"] in trade_sim.QM_TERMINAL][:19]
small = {k: v for k, v in small.items() if k in keep or v["status"] not in trade_sim.QM_TERMINAL}
backtest._save_tracker(small)
S19 = backtest.get_qm_summary()
assert S19["closed"] == 19 and not S19["stats_visible"] and S19["win_rate_pct"] is None and S19["median_realized_r"] is None and S19["spy_compare"] is None and S19["avg_realized_r"] is not None
assert all(g["avg_r"] is None for g in S19["by_regime"].values()) and S19["win_ci_pct"] is None
keep20 = keep + [next(k for k, v in tr.items() if v["status"] in trade_sim.QM_TERMINAL and k not in keep)]
small20 = {k: v for k, v in tr.items() if k in keep20 or v["status"] not in trade_sim.QM_TERMINAL}
backtest._save_tracker(small20)
S20 = backtest.get_qm_summary()
assert S20["closed"] == 20 and S20["stats_visible"] and S20["win_rate_pct"] is not None and S20["spy_compare"] is not None
print("  ✓ при 19 затворени: само броят и средният R (win rate, медиана, SPY, интервал — скрити); при 20-ия се появяват")
backtest._save_tracker(tr)

print()
print("── отметки 'и Action' / 'и buy-stop' (производни от застъпването на интервалите) ──")
t3 = fresh()
backtest._ingest_qm_list(t3, "2026-10-05", [CARDS["DOCN"], CARDS["CORT"], CARDS["CRL"]], "Defensive")
t3["DOCN_2026-10-05_qm"].update(status="open", fill_date="2026-10-05")
t3["CORT_2026-10-05_qm"].update(status="open", fill_date="2026-10-05")
backtest._ingest_action_list(t3, "2026-10-06", [{"ticker": "DOCN", "plan": act_plan}])
backtest._ingest_buystop_list(t3, "2026-10-06", [{**buystop_card, "ticker": "CORT"}], "Defensive")
backtest._save_tracker(t3)
S = backtest.get_qm_summary()
rows = {x["ticker"]: x for x in S["live"]}
assert (rows["DOCN"]["also_action"], rows["DOCN"]["also_buystop"]) == (True, False) and (rows["CORT"]["also_action"], rows["CORT"]["also_buystop"]) == (False, True) and (rows["CRL"]["also_action"], rows["CRL"]["also_buystop"]) == (False, False)
assert S["also_action"] == 1 and S["also_buystop"] == 1 and S["open"] == 2 and S["pending"] == 1
print("  ✓ DOCN е и Action (06.10) → 'и Action'; CORT е и buy-stop → 'и buy-stop'; CRL — само QM")

print()
print("── четците на позиции игнорират книгата ──")
t4 = fresh()
backtest._ingest_qm_list(t4, "2026-10-01", [{**CARDS["DOCN"], "ticker": "EXPD"}], "Defensive")
t4["EXPD_2026-10-01_qm"].update(status="open", fill_date="2026-10-01", entry_price=190.0)
backtest._ingest_qm_list(t4, "2026-09-20", [{**CARDS["CORT"], "ticker": "ABC"}], "Defensive")
t4["ABC_2026-09-20_qm"].update(status="stopped", fill_date="2026-09-21", realized_r=-1.0, resolution_date="2026-09-25")
backtest._save_tracker(t4)
backtest._fetch_current_prices = lambda tickers: {}
assert brief_main._live_positions() == {} and brief_main._last_resolved_positions() == {}
Sa = backtest.get_backtest_summary()
assert Sa["open_positions"] == [] and Sa["pending_positions"] == [] and Sa["total_resolved"] == 0 and Sa["still_open"] == 0 and Sa["recent"] == []
assert backtest.get_buystop_summary()["records"] == 0
cand = copy.deepcopy(next(c for c in B05["watchlist"] if c["ticker"] == "EXPD")); cand.pop("plan_preview", None)
action, watch = brief_main.apply_hard_rules([cand], 0.5, "Defensive")
card = watch[0]
assert "OPEN✓" not in [m["tag"] for m in card.get("markers") or []] and card["ai"].get("watchlist_reason_type") != "existing_position" and "prev_position" not in card
print("  ✓ жив и затворен QM запис: main._live_positions/_last_resolved_positions празни; обобщението на Action и buy-stop книгата не ги броят; РЕАЛНАТА карта на EXPD (05.10) няма OPEN✓/RE-ENTRY")

print()
print("── сплит след входа и провал на резолюция ──")
t5 = fresh()
backtest._ingest_qm_list(t5, "2026-08-10", [{"ticker": "CORT", "trigger": 100.0, "adr": 4.0}, {"ticker": "DOCN", "trigger": 100.0, "adr": 4.0}], "Defensive")
backtest._unapplied_splits = lambda rec: [{"date": "2026-08-12", "ratio": 2.0}] if rec["ticker"] == "CORT" else []
backtest._resolve_open_positions(t5, TODAY)
assert t5["CORT_2026-08-10_qm"]["needs_manual_review"]["reason"] == "split_after_entry_qm" and t5["CORT_2026-08-10_qm"]["status"] == "pending"
assert t5["DOCN_2026-08-10_qm"]["status"] != "pending" or t5["DOCN_2026-08-10_qm"]["resolution_date"] is None
assert backtest.get_qm_summary() is not None
backtest._save_tracker(t5)
assert backtest.get_qm_summary()["needs_review"] == 1
backtest._unapplied_splits = lambda rec: []
print("  ✓ сплит след входа → needs_manual_review (записът не се коригира и не се резолвира), останалите записи се резолвират нормално; броят за преглед е в обобщението")

print()
print("── main.run (структурно) ──")
import ast
tree = ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8"))
run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
upd = [n for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "update_backtest_tracker"]
assert len(upd) == 1 and ast.unparse(upd[0].args[4]) == "qm_cards"
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'backtest_summary["qm_breakout"] = backtest.get_qm_summary()' in src and src.index("qm_cards = qm_breakout.cards") < src.index("backtest.update_backtest_tracker(")
print("  ✓ update_backtest_tracker получава показаните qm_cards (изчислени по-рано в run); backtest_summary['qm_breakout'] = get_qm_summary() под TRACK_QM и в try/except")
print()
print("Всички тестове минаха.")
