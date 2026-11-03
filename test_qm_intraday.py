"""
03.11.2026 · разходката, т. 11 (Kullamägi), 1: книгата qm_breakout — една истина вместо opt / pess. Дневният бар не казва дали дъното на входния ден е преди или след пробива:
до 03.11 се записваха две граници (opt — дъното е преди входа; pess — денят затваря под входа → загуба до стопа). Сега входът и стопът са от 5-минутните бари на входния ден
(trade_sim.qm_intraday_entry): входът — първият бар с High >= нивото; стопът — дъното на деня до този бар включително; по-късен бар под него → стоп в същия ден. yfinance пази
5-минутни бари ~60 дни: тегли ги backtest в първия бриф след входа (и назад за задействаните, докато са в прозореца — config.QM_INTRADAY_MAX_DAYS); по-стари → двете оценки с етикет.

РЕАЛНО: tests/fixtures/qm_intraday_2026-11-03.json.gz (бележката — вътре): 6-те задействани записа на книгата на 03.11 (SN и ELF 09.10, DOCU 13.10, CBOE и UTHR 20.10, RVTY 21.10),
5-минутните бари на входния им ден и дневните OHLC 20.08–02.11; tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): подмененото теглене (_FETCH_5M и yf.download — връщат РЕАЛНИТЕ бари), записът с вход отпреди 60 дни, провалът на тегленето, нивото над всички бари.
Пускане: python test_qm_intraday.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_qm5m_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import trade_sim, backtest, render

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "qm_intraday_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
TODAY = dt.date(2026, 11, 3)
q = lambda: contextlib.redirect_stdout(io.StringIO())


def b5(key):
    d = FX["bars_5m"][key]
    idx = pd.to_datetime(d["times"], utc=True).tz_convert("America/New_York")
    return pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"]}, index=idx)


def daily(t):
    d = FX["daily"][t]
    return pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"]}, index=pd.to_datetime(d["dates"]))


REC = {r["ticker"]: r for r in FX["records"].values()}
assert sorted(REC) == ["CBOE", "DOCU", "ELF", "RVTY", "SN", "UTHR"]

print("── 1. qm_intraday_entry — РЕАЛНИТЕ 5-минутни бари на входния ден ──")
want = {"SN": ("09:30", 185.065, True, "09:40"), "ELF": ("09:30", 107.0, False, None), "DOCU": ("09:40", 70.885, False, None),
        "CBOE": ("09:40", 306.47, False, None), "UTHR": ("10:10", 547.14, True, "11:45"), "RVTY": ("09:40", 152.71, False, None)}
IN = {}
for t, r in REC.items():
    got = trade_sim.qm_intraday_entry(b5(f"{t}_{r['fill_date']}"), r["buy_stop"])
    assert (got["entry_time"], got["stop"], got["stopped"], got["stop_time"]) == want[t], (t, got)
    assert got["bars"] == 78 and got["fill"] >= r["buy_stop"]
    IN[t] = got
assert IN["UTHR"]["low_time"] == "11:50" and IN["UTHR"]["low_of_day"] == min(FX["bars_5m"]["UTHR_2026-10-20"]["l"]) == 545.58                    # дъното на деня — СЛЕД пробива
assert IN["DOCU"]["low_time"] == "09:30"                                                                                                       # дъното — преди пробива (09:40)
assert trade_sim.qm_intraday_entry(None, 100) is None and trade_sim.qm_intraday_entry(b5("SN_2026-10-09"), 10_000) is None                     # СИНТЕТИЧНО: нивото над всички бари
print("  ✓ SN: пробив 09:30, стоп $185.07 (дъното до пробива), стопиран 09:40 · UTHR: пробив 10:10, стоп $547.14, стопиран 11:45 (дъното на деня 11:50)")
print("  ✓ DOCU / CBOE / RVTY / ELF: дъното на деня е преди или в бара на пробива — не са стопирани в деня")

print()
print("── 2. simulate_qm: една стойност с 5-минутните бари; без тях — двете граници (РЕАЛНИТЕ дневни бари до 02.11) ──")
R = lambda x: x["realized_r"] if x.get("realized_r") is not None else x.get("current_r")
exp = {"SN": ("stopped", -0.76, "stop_intraday"), "UTHR": ("stopped", -1.0, "stop_intraday"), "DOCU": ("trailing", 3.68, None),
       "CBOE": ("stopped", 0.87, "stop"), "RVTY": ("stopped", 0.29, "stop"), "ELF": ("stopped", -0.35, "stop")}
old_bounds = {}
for t, r in REC.items():
    old = trade_sim.simulate_qm(r, daily(t), TODAY)
    new = trade_sim.simulate_qm({**r, "intraday": {**IN[t], "date": r["fill_date"]}}, daily(t), TODAY)
    assert old["r_basis"] == "daily" and new["r_basis"] == "5m"
    assert (new["status"], R(new), new["how"]) == exp[t], (t, new["status"], R(new), new["how"])
    assert new["R_pess"] == new["R"] if new.get("R") is not None else True
    old_bounds[t] = (R(old), old.get("realized_r_pess") if old.get("realized_r_pess") is not None else old.get("R_pess"))
assert old_bounds["SN"] == (0.99, -1.0) and old_bounds["UTHR"][0] == 2.41 and old_bounds["UTHR"][1] == -1.0 and old_bounds["DOCU"] == (3.68, -1.0)
assert round(sum(v[0] for v in old_bounds.values()), 2) == 7.89 and round(sum(v[1] for v in old_bounds.values()), 2) == -5.35
assert round(sum(exp[t][1] for t in exp), 2) == 2.73
# стопиран в деня: −0.76R за SN, а не −1R — подът на знаменателя (0.25 × ADR) е по-широк от риска до стопа от 5-минутните ($1.26)
sn = trade_sim.simulate_qm({**REC["SN"], "intraday": {**IN["SN"], "date": "2026-10-09"}}, daily("SN"), TODAY)
assert sn["r_floored"] and sn["exit_date"] == "2026-10-09" and sn["exit_price"] == 185.065 and sn["stop_loss"] == 185.065
# 5-минутни бари за ДРУГ ден (не входния) → не се ползват
other = trade_sim.simulate_qm({**REC["SN"], "intraday": {**IN["SN"], "date": "2026-10-10"}}, daily("SN"), TODAY)
assert other["r_basis"] == "daily" and R(other) == 0.99
print("  ✓ дневно (opt / pess): SN +0.99 / −1.00, UTHR +2.41 / −1.00, DOCU +3.68 / −1.00 … — сума +7.89 / −5.35")
print("  ✓ с 5-минутните: SN −0.76 (стоп 09:40; подът 0.25×ADR), UTHR −1.00 (стоп 11:45), DOCU +3.68 (жива), CBOE +0.87, RVTY +0.29, ELF −0.35 — сума +2.73; R_pess = R")

print()
print("── 3. backtest: теглене веднъж след входа; извън прозореца / провал / нивото не е достигнато → етикет (СИНТЕТИЧНО: подмененото теглене връща РЕАЛНИТЕ бари) ──")
calls = []
backtest._FETCH_5M = lambda t, d: (calls.append((t, d)), b5(f"{t}_{d}"))[1]
rec = copy.deepcopy(REC["UTHR"])
with q() as log:
    assert backtest._qm_intraday(rec, rec["fill_date"], TODAY) is True
assert rec["intraday"]["stop"] == 547.14 and rec["intraday"]["source"] == "yfinance 5m" and rec["intraday"]["fetched"] == "2026-11-03" and calls == [("UTHR", "2026-10-20")]
assert "UTHR: 5-минутни бари 2026-10-20 — пробив в 10:10 по $560.0, стоп $547.14 (дъното до пробива), дъно на деня $545.58 в 11:50, стопиран в 11:45" in log.getvalue()
assert backtest._qm_intraday(rec, rec["fill_date"], TODAY) is False and len(calls) == 1                                                       # вече има — без второ теглене
old_rec = {**copy.deepcopy(REC["SN"]), "fill_date": "2026-09-01"}                                                                              # СИНТЕТИЧНО: вход отпреди 63 дни
assert backtest._qm_intraday(old_rec, "2026-09-01", TODAY) is False and old_rec["intraday_status"] == "expired" and len(calls) == 1
def boom(t, d):
    raise ConnectionError("СИНТЕТИЧНО")
backtest._FETCH_5M = boom
fail = copy.deepcopy(REC["CBOE"])
with q():
    assert backtest._qm_intraday(fail, fail["fill_date"], TODAY) is False
assert fail["intraday_status"] == "тегленето не успя (ConnectionError)" and "intraday" not in fail
backtest._FETCH_5M = lambda t, d: b5(f"{t}_{d}")
high = {**copy.deepcopy(REC["RVTY"]), "buy_stop": 10_000.0}                                                                                   # СИНТЕТИЧНО: нивото над всички бари
with q():
    backtest._qm_intraday(high, high["fill_date"], TODAY)
assert high["intraday_status"] == "5-минутните бари не стигат нивото"
print("  ✓ UTHR — веднъж, пази се в записа (второ извикване не тегли); вход отпреди 63 дни → „expired“ без теглене; провал / нивото не е в барите → етикет с причината")

print()
print("── 4. назад: затворените записи (SN, ELF, CBOE, RVTY) и живите (DOCU, UTHR) получават 5-минутните в един run на _resolve_open_positions ──")
tracker = copy.deepcopy(FX["records"])
frame = pd.concat({f: pd.DataFrame({t: daily(t)[f] for t in REC}) for f in ("Open", "High", "Low", "Close", "Volume") if f != "Volume"}, axis=1)
frame = pd.concat([frame, pd.concat({"Volume": pd.DataFrame({t: [1_000_000.0] * len(frame) for t in REC}, index=frame.index)}, axis=1)], axis=1)   # СИНТЕТИЧНО: обемът (не се ползва от QM)
backtest.yf = type("Y", (), {"download": staticmethod(lambda *a, **k: frame)})                                                                  # СИНТЕТИЧНО: дневните — РЕАЛНИТЕ
calls.clear(); backtest._FETCH_5M = lambda t, d: (calls.append(t), b5(f"{t}_{d}"))[1]
with q() as log:
    backtest._resolve_open_positions(tracker, TODAY)
got = {r["ticker"]: (r["status"], R(r), r.get("r_basis")) for r in tracker.values()}
assert got == {t: (exp[t][0], exp[t][1], "5m") for t in exp}, got
assert sorted(calls) == sorted(REC)
assert "qm_breakout SN 2026-10-09: назад с 5-минутни бари — stopped R 0.99 / -1.0 (opt / pess) → stopped R -0.76" in log.getvalue()
with q():
    backtest._resolve_open_positions(tracker, TODAY)
assert sorted(calls) == sorted(REC)                                                                                                            # втори run — без ново теглене
print("  ✓ " + " · ".join(f"{t} {s} {r:+.2f}" for t, (s, r, _) in sorted(got.items())) + "; вторият run не тегли наново")

print()
print("── 5. обобщението и страницата ──")
backtest._TRACKER_PATH.write_text(json.dumps(tracker), encoding="utf-8")
config.QM_MAX_DIST_RULE_FROM = ""
qs = backtest.get_qm_summary()
assert (qs["closed"], qs["closed_5m"], qs["closed_bounds"], qs["triggered_5m"]) == (5, 5, 0, 6) and qs["avg_realized_r"] == qs["avg_realized_r_pess"] == round((-0.76 - 0.35 + 0.87 + 0.29 - 1.0) / 5, 2)   # UTHR — вече затворен
b = copy.deepcopy(B19); b.setdefault("backtest", {})["qm_breakout"] = qs
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "среден R: -0.19 (5-минутни бари)" in page and "R=-0.76 (5-минутни бари, стоп в деня на входа)" in page and "R=0.87 (5-минутни бари)" in page
assert "Входът и стопът — от 5-минутните бари на входния ден" in page and "$547.14 (5 мин)" not in page                                            # UTHR вече е затворен
assert "$70.885 (5 мин)" in page                                                                                                               # DOCU — жива, стопът с етикета
t2 = copy.deepcopy(tracker); t2["SN_2026-10-09_qm"].update(r_basis="daily", intraday_status="expired", realized_r_pess=-1.0)                    # СИНТЕТИЧНО: изтекли 5-минутни
backtest._TRACKER_PATH.write_text(json.dumps(t2), encoding="utf-8")
qs2 = backtest.get_qm_summary(); b["backtest"]["qm_breakout"] = qs2
with q():
    page2 = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "— 4 от 5 с 5-минутни бари (там opt = pess), 1 с двете граници" in page2 and "· дневни бари (5-минутните са изтекли)" in page2
with q():
    mail = render.render_email(b)
assert "среден R -0.19 opt / -0.24 pess (4 от 5 с 5-минутни бари)" in mail                                                                 # имейлът — СИНТЕТИЧНО изтеклият SN
b["backtest"]["qm_breakout"] = qs
with q():
    mail = render.render_email(b)
assert "среден R -0.19 (5-минутни бари)" in mail
print(f"  ✓ среден R {qs['avg_realized_r']:+.2f} (5-минутни бари), карта „R=-0.76 (5-минутни бари, стоп в деня на входа)“; изтекли → opt / pess с етикет и броя; имейлът — същото")
print("\n✅ test_qm_intraday: всичко мина")
