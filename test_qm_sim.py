"""
Qullamaggie (06.10.2026) · trade_sim.simulate_qm — общата симулация на реплея и на книгата "qm_breakout": вход на нивото на пробива (1 сесия), стоп = Low на входния ден (≤ 1×ADR), 40% на затварянето на
4-тата сесия, стоп към break-even, остатъкът по първо затваряне под SMA10 (ADR ≥ 5%) или SMA20; две граници за стопа на входния ден (opt / pess).

РЕАЛНО: дневните барове на AMD, TWLO, LNTH, EXEL (tests/fixtures/ohlc_*.csv, Yahoo) — върху тях симулацията се сверява с НЕЗАВИСИМА референтна имплементация (чист Python, без numpy/pandas) за ~100 сетъпа.
СИНТЕТИЧНО: ръчно пресметнатите сценарии (барове с кръгли числа), нивата/ADR на реалните сетъпи (нивото = най-високият High на последните 10 бара, ADR20 по формулата от qullamaggie.com/faq).
Пускане: python test_qm_sim.py
"""
import sys, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import trade_sim as ts

assert (config.QM_PARTIAL_DAYS, config.QM_PARTIAL_FRACTION, config.QM_TRAIL_ADR_SWITCH, config.QM_ENTRY_WINDOW_SESSIONS) == (4, 0.4, 5.0, 1)


def bars(rows, start="2026-03-02"):
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close"])


def rec(entry_date, trig, adr):
    return {"entry_date": entry_date, "buy_stop": trig, "adr": adr}


# 25 "тихи" бара преди входа (за SMA10/SMA20): затваряния 90 → 98
PRE = [(90 + i * 0.3, 90.5 + i * 0.3, 89.5 + i * 0.3, 90 + i * 0.3) for i in range(25)]
D0 = pd.bdate_range("2026-03-02", periods=40)
ENTRY = D0[25].date().isoformat()            # първата сесия след PRE

print("── входът ──")
b = bars(PRE)
assert ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)["status"] == "pending"                                      # още няма бар на входния ден
b = bars(PRE + [(97.5, 99.5, 96.5, 99.0)])
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] == "not_triggered" and r["resolution_date"] == ENTRY and r["fill_price"] is None            # High 99.5 < 100
b = bars(PRE + [(101.0, 103.0, 100.5, 102.5)])
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] == "open" and r["fill_price"] == 101.0 and r["stop_loss"] == 100.5 and r["risk_per_share"] == 0.5     # гап над нивото → по отварянето
b = bars(PRE + [(99.0, 101.0, 98.0, 100.4)])
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["fill_price"] == 100.0 and r["stop_loss"] == 98.0 and r["status"] == "open"                           # пресича вътре в деня → по нивото
b = bars(PRE + [(105.0, 106.0, 104.5, 105.5)])
assert ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)["status"] == "skipped_extended"                               # отваря 5% над нивото > 1×ADR(4%)
b = bars(PRE + [(100.5, 104.0, 93.0, 103.0)])
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] == "skipped_adr" and r["fill_price"] is None                                                # (100.5−93)/100.5 = 7.5% > ADR 4%
assert ts.simulate_qm(rec(ENTRY, 100.0, 8.0), b)["status"] == "open"                                           # при ADR 8% стопът е допустим
print("  ✓ pending (няма бар) / not_triggered (High 99.5 < 100) / гап по отварянето (101, стоп 100.5) / вътрешнодневно по нивото (100, стоп 98) / skipped_extended (гап +5% > 1×ADR) / skipped_adr (7.5% > ADR 4%)")

print()
print("── изход: стоп, гап през стопа, частична продажба, break-even, трейлинг ──")
FILL = [(99.0, 101.0, 98.0, 100.4)]                                                                      # вход 100.0, стоп 98.0, риск 2.0 → 1R = $2.00
b = bars(PRE + FILL + [(100.5, 101.0, 97.5, 98.5)])
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] == "stopped" and r["exit_price"] == 98.0 and r["realized_r"] == -1.0 and r["return_pct"] == -2.0 and r["partial_price"] is None
b = bars(PRE + FILL + [(97.0, 98.0, 96.0, 97.5)])                                                          # отваря под стопа → по отварянето, над −1R
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] == "stopped" and r["exit_price"] == 97.0 and r["realized_r"] == -1.5 and r["how"] == "stop_gap"
print("  ✓ стоп: вътрешнодневно на $98.00 = −1.0R (−2.0%); гап под стопа → по отварянето $97.00 = −1.5R")

# 4-ти ден: частична продажба на затварянето, стоп към break-even, остатък по SMA20 (ADR 4% < 5%)
UP = [(100.4, 102.0, 100.0, 101.5), (101.5, 103.0, 101.0, 102.5), (102.5, 104.0, 102.0, 103.0), (103.0, 106.0, 102.5, 105.0)]       # дни 1–4 след входния
b = bars(PRE + FILL + UP)
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] == "trailing" and r["partial_price"] == 105.0 and r["partial_fraction"] == 0.4 and r["target1_hit_date"] == D0[29].date().isoformat() and r["trail_ma"] == 20
cur = 0.4 * (105 - 100) / 2 + 0.6 * (105 - 100) / 2                                                         # затварянето на деня е и частичната, и последната → 2.5R
assert r["current_r"] == round(cur, 2) == 2.5
print("  ✓ ден 4: 40% на затварянето $105.00 (+2.5R), стоп към break-even $100.00, остатъкът се трейлва по SMA20 (ADR 4% < 5%) — статус 'trailing', текущо +2.5R")
b = bars(PRE + FILL + UP + [(104.0, 104.5, 99.5, 100.0)])                                                  # ден 5: ниско 99.5 < 100 → стоп на break-even
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] == "stopped" and r["exit_price"] == 100.0 and r["how"] == "stop" and r["realized_r"] == round(0.4 * 2.5 + 0.6 * 0, 2) == 1.0 and r["return_pct"] == 2.0
print("  ✓ ден 5: стоп на break-even $100.00 → остатъкът 0R; общо 0.4×2.5R = +1.0R (+2.0%)")
# трейлинг: цената пада, но не под входа; затваряне под SMA20
closes = [105, 103, 101.5, 101]
trail = [(104.0, 105.0, 103.0, 103.0), (103.0, 103.5, 101.5, 101.5), (101.5, 102.0, 100.8, 101.0)]
b = bars(PRE + FILL + UP + trail)
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
sma20 = pd.Series(b["Close"].values).rolling(20).mean().values
j = len(b) - 1
assert r["status"] == "trailing_stop_exit" if b["Close"].iloc[j] < sma20[j] else r["status"] in ("trailing", "stopped")
print(f"  ✓ трейлинг: SMA20 в последния бар = {sma20[j]:.2f}, затваряне {b['Close'].iloc[j]:.2f} → статус {r['status']}")
# SMA10 при ADR ≥ 5%
RUN = [(100.4, 102.0, 100.0, 101.5), (101.5, 103.0, 101.0, 102.5), (102.5, 104.0, 102.0, 103.0), (103.0, 106.0, 102.5, 105.0),
       (105.0, 106.0, 104.0, 104.5), (104.5, 105.0, 103.0, 103.8), (103.8, 104.0, 102.4, 102.6), (102.6, 103.0, 101.2, 101.4)]
b = bars(PRE + FILL + RUN)
r10 = ts.simulate_qm(rec(ENTRY, 100.0, 5.0), b)
r20 = ts.simulate_qm(rec(ENTRY, 100.0, 4.9), b)
assert r10["trail_ma"] == 10 and r20["trail_ma"] == 20
c = b["Close"].values; s10 = pd.Series(c).rolling(10).mean().values; s20 = pd.Series(c).rolling(20).mean().values
first_below = lambda s: next((k for k in range(len(PRE) + 1 + 4, len(c)) if c[k] < s[k]), None)
k10, k20 = first_below(s10), first_below(s20)
assert (r10["status"] == "trailing_stop_exit") == (k10 is not None) and (r20["status"] == "trailing_stop_exit") == (k20 is not None)
if k10 is not None:
    assert r10["exit_date"] == b.index[k10].date().isoformat() and r10["exit_price"] == round(c[k10], 4)
print(f"  ✓ ADR 5.0% → SMA10 (първо затваряне под на {b.index[k10].date() if k10 else '—'}), ADR 4.9% → SMA20 ({b.index[k20].date() if k20 else 'още не'})")

print()
print("── граница pess, mark-to-market, maks. държане ──")
b = bars(PRE + [(99.0, 101.0, 98.0, 99.5)] + [(99.6, 103.0, 99.0, 102.0), (102.0, 106.0, 101.5, 105.0)])        # денят на входа затваря под входа (99.5 < 100)
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] == "open" and r["R_pess"] == -1.0 and r["return_pct_pess"] == -2.0 and r["current_r"] == 2.5          # opt: още жива, +2.5R; pess: −1R още в първия ден
print("  ✓ денят на входа затваря под входа ($99.50 < $100.00): opt продължава (+2.5R mtm), pess е −1.0R (−2.0%)")
config.QM_MAX_HOLD_SESSIONS = 6
b = bars(PRE + FILL + [(100.8, 102.0, 100.5, 101.5)] * 10)                                               # ниските над break-even стопа ($100.00), затварянията над SMA20
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] == "expired" and r["how"] == "mtm" and r["exit_date"] == D0[25 + 6].date().isoformat()
r_exp = r
config.QM_MAX_HOLD_SESSIONS = 180
r = ts.simulate_qm(rec(ENTRY, 100.0, 4.0), b)
assert r["status"] in ("open", "trailing", "trailing_stop_exit", "stopped")
print("  ✓ при максимум 6 сесии държане: 'expired' по последния Close (mark-to-market); при 180 — още жива/нормален изход")

print()
print("── РЕАЛНИ барове: кръстосана проверка с независима референтна имплементация (чист Python) ──")


def ref(rec_, o, h, l, c, dates, cfg):
    """Независима референтна имплементация (цикли, без numpy/pandas). Връща (status, fill, stop, R_opt, R_pess, exit_date)."""
    n = len(o); trig, adr = rec_["buy_stop"], rec_["adr"]
    first = next((k for k, d in enumerate(dates) if d >= rec_["entry_date"]), n)
    if first >= n: return ("pending",)
    j = first
    if h[j] < trig and o[j] < trig:
        return ("not_triggered",) if first + 1 <= n else ("pending",)
    fill = o[j] if o[j] >= trig else trig
    if fill > trig * (1 + cfg["chase"] * adr / 100): return ("skipped_extended",)
    stop0 = l[j]; risk = fill - stop0
    if risk <= 0: return ("invalid_risk",)
    if risk / fill * 100 > cfg["adrstop"] * adr: return ("skipped_adr",)
    tn = 10 if adr >= cfg["switch"] else 20
    def sma(k): return sum(c[k - tn + 1:k + 1]) / tn if k >= tn - 1 else None
    stop, part, rp, pp = stop0, False, 0.0, None
    last = min(n - 1, j + cfg["hold"]); ex = exj = None; how = None
    for k in range(j + 1, last + 1):
        if o[k] <= stop: ex, exj, how = o[k], k, "stop"; break
        if l[k] <= stop: ex, exj, how = stop, k, "stop"; break
        if not part and k == j + cfg["pdays"]:
            part, pp = True, c[k]; rp = (pp - fill) / risk; stop = max(stop, fill); continue
        s = sma(k)
        if part and s is not None and c[k] < s: ex, exj, how = c[k], k, "trail"; break
    if ex is None:
        if last - j < cfg["hold"]:
            px = c[last]; r = (cfg["frac"] * rp + (1 - cfg["frac"]) * (px - fill) / risk) if part else (px - fill) / risk
            st = "trailing" if part else "open"
            return (st, fill, stop0, None, (-1.0 if c[j] < fill else r), None)
        ex, exj = c[last], last
    R = (cfg["frac"] * rp + (1 - cfg["frac"]) * (ex - fill) / risk) if part else (ex - fill) / risk
    st = "trailing_stop_exit" if how == "trail" else "stopped" if how == "stop" else "expired"
    return (st, fill, stop0, R, (-1.0 if c[j] < fill else R), dates[exj])


cfg = dict(chase=config.QM_CHASE_ADR, adrstop=config.QM_ADR_STOP, switch=config.QM_TRAIL_ADR_SWITCH, hold=config.QM_MAX_HOLD_SESSIONS, pdays=config.QM_PARTIAL_DAYS, frac=config.QM_PARTIAL_FRACTION)
stats = {}
total = 0
for tk in ("AMD", "TWLO", "LNTH", "EXEL"):
    df = pd.read_csv(ROOT / "tests" / "fixtures" / f"ohlc_{tk}.csv", index_col=0, parse_dates=True).dropna(subset=["Open", "High", "Low", "Close"])
    o, h, l, c = (df[k].tolist() for k in ("Open", "High", "Low", "Close")); dates = [d.date().isoformat() for d in df.index]
    for k in range(30, len(df) - 1, 3):                                                           # сигнален бар k−1, вход в бар k
        trig = max(h[k - 10:k])
        adr = 100 * (sum(h[i] / l[i] for i in range(k - 20, k)) / 20 - 1)                          # формулата от FAQ: средното H/L − 1 за 20 сесии
        rc = {"entry_date": dates[k], "buy_stop": trig, "adr": adr}
        want = ref(rc, o, h, l, c, dates, cfg)
        got = ts.simulate_qm(rc, df, today=None)
        assert got["status"] == want[0], (tk, dates[k], got["status"], want)
        total += 1; stats[got["status"]] = stats.get(got["status"], 0) + 1
        if want[0] in ("stopped", "trailing_stop_exit", "expired"):
            assert abs(got["R"] - want[3]) < 1e-9 and abs(got["R_pess"] - want[4]) < 1e-9 and got["exit_date"] == want[5], (tk, dates[k], got["R"], want)
            assert abs(got["fill_price"] - want[1]) < 1e-3 and abs(got["stop_loss"] - want[2]) < 1e-3
        elif want[0] in ("open", "trailing"):
            assert abs(got["R_pess"] - want[4]) < 0.011
print(f"  ✓ {total} реални сетъпа (AMD/TWLO/LNTH/EXEL, всеки 3-ти бар): статус, вход, стоп, R (opt и pess) и дата на изхода съвпадат с независимата референтна имплементация; статуси: {dict(sorted(stats.items()))}")
assert sum(stats.get(k, 0) for k in ("stopped", "trailing_stop_exit")) >= 10
print()
print("Всички тестове минаха.")
