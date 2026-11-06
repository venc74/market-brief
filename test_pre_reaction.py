"""
06.11.2026 (пакет 05–06.11, т. 4): етикет „преди реакцията на отчета“ — запис в книгите с нива от затварянето преди реакцията: отчетът е след затварянето на сигналния ден или преди отварянето на
първата сесия на записа. Реално: MNST 06.11 (buy-stop от затварянето на 05.11, отчетът — 05.11 в 16:00 ET). Записите остават; статистиката на книгите е с и без тях.

РЕАЛНО: tests/fixtures/earnings_times_2026-11-06.json — времената от Yahoo за MNST, WST, APP и записът на MNST; tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): останалите записи (датите са спрямо реалните времена), резултатите в т. 3.
Пускане: python test_pre_reaction.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_prereact_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
config.BACKTEST_FILE = config.DATA_DIR / "backtest_tracker.json"
from src import event_label, backtest, render

FX = json.loads((ROOT / "tests" / "fixtures" / "earnings_times_2026-11-06.json").read_text(encoding="utf-8"))
T = {k: [pd.Timestamp(x) for x in v] for k, v in FX["times"].items()}
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))

print("── 1. прозорецът: след затварянето на сигналния ден … преди отварянето на входа ──")
mn = FX["mnst_record"]
assert (mn["entry_date"], mn["category"]) == ("2026-11-06", "buystop")
assert event_label.pre_reaction(mn, T["MNST"]) == {"date": "2026-11-05", "when": "amc"}                        # РЕАЛНО: 05.11 16:00 ET, запис от 06.11
assert event_label.pre_reaction({"entry_date": "2026-11-05"}, T["MNST"]) is None                               # СИНТЕТИЧНО: запис ден по-рано — отчетът е чак след него
assert event_label.pre_reaction({"entry_date": "2026-11-07"}, T["MNST"]) is None                               # събота → понеделник 09.11; сигналът е 06.11 — отчетът е преди него
assert event_label.pre_reaction({"entry_date": "2026-10-29"}, T["WST"]) == {"date": "2026-10-29", "when": "bmo"}     # РЕАЛНО време: WST 29.10 06:00 ET, преди отварянето на 29.10
assert event_label.pre_reaction({"entry_date": "2026-10-30"}, T["WST"]) is None                                # последният бар (29.10) вече носи реакцията
assert event_label.pre_reaction({"entry_date": "2026-10-23", "signal_date": "2026-10-22"}, [pd.Timestamp("2026-10-22T15:59:00-04:00")]) is None     # СИНТЕТИЧНО: преди затварянето
assert event_label.pre_reaction({"entry_date": "2026-10-23", "signal_date": "2026-10-22"}, [pd.Timestamp("2026-10-23T09:30:00-04:00")]) is None     # СИНТЕТИЧНО: на самото отваряне — вече не е преди него
assert event_label.pre_reaction({"entry_date": "2026-10-23"}, [pd.Timestamp("2026-10-22 18:00")]) is None      # СИНТЕТИЧНО: без часова зона — не се преценява
assert event_label.pre_reaction({}, T["MNST"]) is None and event_label.pre_reaction(mn, []) is None
print("  ✓ MNST 06.11 — amc; WST 29.10 — bmo; ден по-рано, ден по-късно, преди затварянето и на самото отваряне — без етикет")

print("── 2. проверката: веднъж, провалът остава за утре, бюджетът спира ──")
trk = {"MNST": copy.deepcopy(mn), "OLD": {"ticker": "WST", "method": "v2", "entry_date": "2026-10-30"},
       "FUT": {"ticker": "WST", "method": "v2", "entry_date": "2026-12-01"}, "BAD": {"ticker": "ERR", "method": "v2", "entry_date": "2026-11-06"},
       "V1": {"ticker": "WST", "entry_date": "2026-10-29"}}                                                    # СИНТЕТИЧНО: v1 запис без категория — не е книга
calls = []


def fetch(sym):
    calls.append(sym)
    if sym == "ERR":
        raise TimeoutError("Yahoo")
    return T[sym]


with contextlib.redirect_stdout(io.StringIO()):
    st = event_label.label_pre_reaction(trk, "2026-11-06", lambda r: r.get("method") == "v2", fetch=fetch)
assert st["ok"] and st["checked"] == 2 and st["labelled"] == ["MNST 2026-11-06"] and st["failed"] == 1
assert trk["MNST"]["pre_reaction"]["when"] == "amc" and trk["MNST"]["pre_reaction_checked"] == "2026-11-06" and "pre_reaction" not in trk["OLD"] and trk["OLD"]["pre_reaction_checked"] == "2026-11-06"
assert "pre_reaction_checked" not in trk["FUT"] and "pre_reaction_checked" not in trk["BAD"] and "pre_reaction_checked" not in trk["V1"]
assert calls.count("WST") == 1                                                                                  # едно теглене на тикър
calls.clear()
with contextlib.redirect_stdout(io.StringIO()):
    event_label.label_pre_reaction(trk, "2026-11-06", lambda r: r.get("method") == "v2", fetch=fetch)
assert calls == ["ERR"]                                                                                         # проверените не се теглят наново; провалът — да
with contextlib.redirect_stdout(io.StringIO()):
    st2 = event_label.label_pre_reaction({"A": {"ticker": "MNST", "method": "v2", "entry_date": "2026-11-06"}}, "2026-11-06", lambda r: True, fetch=fetch, budget_sec=-1)
    st3 = event_label.label_pre_reaction({"A": {"ticker": "ERR", "method": "v2", "entry_date": "2026-11-06"}}, "2026-11-06", lambda r: True, fetch=fetch)
assert st2["left"] == 1 and st2["checked"] == 0 and st3["ok"] is False                                          # бюджет; всички провалени → банерът на стъпката
print("  ✓ всеки запис — веднъж; бъдещ запис и провал на Yahoo — не се отбелязват като проверени; едно теглене на тикър")

print("── 3. книгите: с и без тях; страницата (СИНТЕТИЧНИ резултати) ──")
recs = [{"ticker": "MNST", "entry_date": "2026-11-06", "pre_reaction": {"date": "2026-11-05", "when": "amc"}, "realized_r": -1.0},
        {"ticker": "AAA", "entry_date": "2026-10-20", "realized_r": 2.0}, {"ticker": "BBB", "entry_date": "2026-10-21", "realized_r": None}]
pr = backtest.pre_reaction_block(recs, "realized_r")
assert (pr["n"], pr["n_all"], pr["avg_all"], pr["n_rest"], pr["avg_rest"]) == (1, 2, 0.5, 1, 2.0) and pr["tickers"][0]["ticker"] == "MNST"
assert backtest.pre_reaction_block(recs[1:], "realized_r") is None
backtest._save_tracker({"MNST_2026-11-06_buystop": copy.deepcopy(mn)})
with contextlib.redirect_stdout(io.StringIO()):
    st = backtest.apply_pre_reaction_labels("2026-11-06", fetch=lambda s: T[s])
    S = backtest.get_buystop_summary()
assert st["labelled"] == ["MNST 2026-11-06"] and backtest._load_tracker()["MNST_2026-11-06_buystop"]["pre_reaction"]["when"] == "amc"
assert S["pre_reaction"]["n"] == 1 and S["live"][0]["pre_reaction"]["date"] == "2026-11-05"
b = copy.deepcopy(B19); b.setdefault("backtest", {})["buystop"] = S
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
assert "преди реакцията на отчета (05.11, след затварянето)" in page and "Преди реакцията на отчета (1): <b>MNST</b> 06.11. Още без затворени резултати при тях." in page
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert main_src.index('"pre_reaction_labels"') < main_src.index("backtest_summary = backtest.get_backtest_summary()")
print("  ✓ обобщението пази етикета и средното с и без него; на реда в книгата и в реда над таблицата; стъпката е преди обобщенията")
print("\n✅ test_pre_reaction: всичко мина")
