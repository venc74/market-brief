"""
Qullamaggie (06.10.2026) · src/qm_breakout.py — механичният скенер на кандидати за пробив (без AI): лидери (горните 10% по ръст за 1/3/6 месеца), предходен ръст, консолидация 8–45 сесии
с higher lows и стягане, растящи 10/20 MA с цена около тях, спадащ обем, ADR ≥ 3%; най-много 8 карти по стягане; нива на картата (ниво на пробива, очакван стоп 0.55×ADR, максимален
стоп 1×ADR, размер при половин риск).

РЕАЛНО: tests/fixtures/qm_frames_2026-10-02.json — дневните данни на 8 тикъра (DOCN, CORT, CRL, PVH, AAPL, NVDA, MSFT, TSLA) към 02.10.2026 и РЕАЛНИТЕ лидерски перцентили от пълния скан на универса
(903 тикъра): 3 кандидата — DOCN, CORT, CRL; PVH е отхвърлен само заради лидерския праг (перцентил 0.84 < 0.90). СИНТЕТИЧНО: серията "учебникарски" кандидат и всички нейни мутации (по един критерий),
перцентилите на малките универси, подмененото yf.download.
Пускане: python test_qm_breakout.py
"""
import sys, json, math, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import config
from src import qm_breakout as q

FIX = json.loads((ROOT / "tests" / "fixtures" / "qm_frames_2026-10-02.json").read_text(encoding="utf-8"))
assert (config.QM_LEAD_PCT, config.QM_ADR_MIN, config.QM_MAX_CARDS, config.QM_RUN_MIN) == (0.90, 3.0, 8, 0.20)


def frame_of(t):
    d = FIX["frames"][t]
    return pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))


REAL = {t: frame_of(t) for t in FIX["frames"]}


# ── СИНТЕТИЧЕН "учебникарски" кандидат ──
def textbook(n=200, **kw):
    """Лека възходяща основа → ръст +50% (бари 120–160, пик 160) → пулбек ~9% → тясна консолидация с higher lows, спадащ обем, растящи SMA10/SMA20. Мутации чрез kw."""
    runup, peak_i = kw.get("runup", 0.5), kw.get("peak_i", 160)
    close = np.empty(n)
    close[:120] = np.linspace(58, 60, 120)
    close[120:peak_i + 1] = np.linspace(60, 60 * (1 + runup), peak_i - 120 + 1)
    top = close[peak_i]
    tail = n - 1 - peak_i
    dd = kw.get("depth", 0.09)
    low_i = peak_i + max(3, int(tail * 0.4))
    close[peak_i + 1:low_i + 1] = np.linspace(top, top * (1 - dd), low_i - peak_i)
    close[low_i + 1:] = np.linspace(top * (1 - dd), top * (1 - dd * 0.35), n - 1 - low_i)
    rng = np.full(n, 0.038)                                                                   # дневен диапазон H/L − 1 ≈ 3.8% → ADR ≈ 3.5%
    rng[-5:] = kw.get("tight_rng", 0.026)                                                     # стягане в последните 5 бара
    rng *= kw.get("adr_scale", 1.0)
    o = close * (1 + 0.001)
    h = close * (1 + rng * 0.5)
    l = close * (1 - rng * 0.5)
    if "lows_last5" in kw:                                                                     # последните 5 ниски — по-ниски от предишните 5
        l[-5:] = l[-5:] * kw["lows_last5"]
    v = np.full(n, 1_000_000.0)
    v[120:peak_i + 1] = 2_000_000.0
    v[-30:] = np.linspace(900_000, 600_000, 30)
    v[-5:] *= kw.get("vol_last5", 1.0)
    if "spike_high" in kw:                                                                     # високо преди 6 бара → нивото на пробива е далеч над цената
        h[-7] = close[-1] * kw["spike_high"]
    price_scale = kw.get("price_scale", 1.0)
    idx = pd.bdate_range(end="2026-10-02", periods=n)
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": close, "Volume": v}, index=idx)
    df[["Open", "High", "Low", "Close"]] *= price_scale
    return df


def check(df, lead=0.95):
    f = q.compute_features(df)
    return q.check_candidate(f, f["n"] - 1, lead)


print("── учебникарският кандидат (СИНТЕТИЧЕН) ──")
base = textbook()
r = check(base)
assert r is not None, "базовият кандидат трябва да минава"
assert 3.0 <= r["adr"] < 4.5 and 40 <= r["runup_pct"] <= 60 and 30 <= r["base_days"] <= 45 and r["depth_pct"] < 15 and r["tight"] <= 1.0 and r["vol_ratio"] <= 1.1 and r["pct_to_trigger"] < 4
assert r["trigger"] == float(base["High"].iloc[-10:].max()) and r["signal_date"] == "2026-10-02" and r["vs_sma10_pct"] > -2 and r["vs_sma20_pct"] > 0
print(f"  ✓ кандидат: ADR {r['adr']:.1f}%, ръст +{r['runup_pct']:.0f}%, база {r['base_days']} сесии, дълбочина {r['depth_pct']:.0f}%, tight {r['tight']:.2f}, обем {r['vol_ratio']:.2f}×, ниво ${r['trigger']:.2f} (+{r['pct_to_trigger']:.1f}% над затварянето)")

print()
print("── всеки критерий поотделно (СИНТЕТИЧНИ мутации на кандидата — всяка води до отхвърляне) ──")
cases = [
    ("лидер: перцентил 0.89 < 0.90", lambda: check(base, lead=0.89)),
    ("лидер: без перцентил (NaN)", lambda: check(base, lead=float("nan"))),
    ("ADR под 3%", lambda: check(textbook(adr_scale=0.7, tight_rng=0.018))),
    ("предходен ръст +10% < 20%", lambda: check(textbook(runup=0.10))),
    ("базата е твърде кратка (пик преди 5 сесии)", lambda: check(textbook(peak_i=194))),
    ("базата е твърде дълга (пик преди 55 сесии)", lambda: check(textbook(peak_i=144))),
    ("пулбек 35% > 30%", lambda: check(textbook(depth=0.35))),
    ("higher lows: ниските на последните 5 бара −4%", lambda: check(textbook(lows_last5=0.96))),
    ("не е стегнато: диапазон на последните 5 бара ×2", lambda: check(textbook(tight_rng=0.09))),
    ("обемът не спада (последните 5 бара ×2.5)", lambda: check(textbook(vol_last5=2.5))),
    ("нивото е далеч над цената (> 2×ADR)", lambda: check(textbook(spike_high=1.20))),
    ("цена под $5", lambda: check(textbook(price_scale=0.05))),
    ("долар обем под $10M", lambda: check(textbook(vol_last5=1.0, price_scale=0.12))),
]
for name, fn in cases:
    assert fn() is None, name
print(f"  ✓ {len(cases)} мутации (лидерски праг, NaN, ADR, ръст, къса/дълга база, дълбочина, higher lows, стягане, обем, далечно ниво, цена, долар обем) — всяка отхвърля кандидата")
# падащи/плоски MA: цената е под SMA20 в низходяща консолидация
down = textbook(depth=0.09)
down.iloc[-25:, :4] = down.iloc[-25:, :4].values * np.linspace(1.0, 0.86, 25)[:, None]
assert check(down) is None
print("  ✓ цената под падаща SMA20 (низходяща консолидация) — отхвърля се")
assert q.check_candidate(q.compute_features(base.iloc[:100]), 99, 0.95) is None
print("  ✓ под 130 бара история — няма сигнал")

print()
print("── перцентили и подредба (СИНТЕТИЧНИ малки универси) ──")
idx = pd.bdate_range(end="2026-10-02", periods=160)
def walk(total_ret21, total_ret63, total_ret126):
    c = np.empty(160); c[-1] = 100.0
    c[-127] = 100 / (1 + total_ret126); c[-64] = 100 / (1 + total_ret63); c[-22] = 100 / (1 + total_ret21)
    c = pd.Series(c).interpolate().bfill().to_numpy()
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)
U = {"A": walk(0.1, 0.1, 0.1), "B": walk(0.2, 0.05, 0.05), "C": walk(0.3, 0.3, 0.02), "D": walk(0.4, 0.0, 0.0), "E": walk(0.5, 0.9, 0.9)}
lp = q.lead_percentiles(U)
assert abs(lp["E"] - 1.0) < 1e-9 and abs(lp["D"] - 0.8) < 1e-9 and abs(lp["C"] - 0.8) < 1e-9 and abs(lp["B"] - 0.6) < 1e-9 and abs(lp["A"] - 0.8) < 1e-9, lp
print("  ✓ най-добрият от трите перцентила (1/3/6 месеца): E 1.0, D 0.8 (1м), C 0.8 (3м), A 0.8 (6м), B 0.6 — по ръчна сметка")
rows, diag = q.scan_frames({"X": base, "Y": textbook(tight_rng=0.020), "Z": textbook(tight_rng=0.030)}, lead={"X": 0.95, "Y": 0.95, "Z": 0.95})
assert [r["ticker"] for r in rows] == ["Y", "X", "Z"] and diag["candidates"] == 3 and diag["with_history"] == 3 and diag["leaders"] == 3                        # по-стегнатият първи
assert [round(r["tight"], 2) for r in rows] == sorted(round(r["tight"], 2) for r in rows)
print("  ✓ подредба по стягане (tight = среден дневен диапазон на последните 5 бара ÷ ADR): най-стегнатият е първи")
many = {f"T{i:02d}": textbook(tight_rng=0.020 + 0.0005 * i) for i in range(12)}
rows, diag = q.scan_frames(many, lead={t: 0.95 for t in many})
cs = q.cards(rows, name_lookup=lambda t: f"Компания {t}" if t != "T03" else (_ for _ in ()).throw(RuntimeError("мрежа")))
assert diag["candidates"] == 12 and diag["shown"] == 8 and len(cs) == 8 and [c["ticker"] for c in cs] == [f"T{i:02d}" for i in range(8)]
assert cs[0]["company"] == "Компания T00" and cs[3]["company"] == "T03"
print("  ✓ 12 кандидата → най-много 8 карти (най-стегнатите); име на компания graceful (провал на lookup → тикърът)")

print()
print("── нивата на картата ──")
row = {"trigger": 151.83, "adr": 7.2}
lv = q.card_levels(row)
exp_stop = 151.83 * (1 - 0.55 * 7.2 / 100); mx = 151.83 * (1 - 7.2 / 100)
assert lv["expected_stop"] == round(exp_stop, 2) == 145.82 and lv["max_stop"] == round(mx, 2) == 140.9 and lv["expected_risk_pct"] == 4.0 and lv["max_risk_pct"] == 7.2
assert not any(k in lv for k in ("risk_usd", "shares", "total_investment", "pct_of_portfolio", "shares_at_max_stop", "capped_by_position_limit"))     # 07.10: размерът е в браузъра
L = lv["levels"]                                                                      # вход = нивото, стоп за оразмеряване = 1×ADR, очакван стоп = 0.55×ADR (втори ред)
assert (L["entry"], L["stop"], L["stop_pct"], L["adr_pct"], L["strategy"]) == (151.83, 140.9, 7.2, 7.2, "kullamagi") and L["stop"] == lv["max_stop"]
assert (L["expected_stop"], L["expected_stop_pct"]) == (145.82, 3.96) and L["stop_source_text"] == "стоп за оразмеряване (макс. 1×ADR)" and L["expected_stop_label"] == "очакван стоп (0.55×ADR)"
assert L["regime_factor"] == 1.0 and L["warnings"] == []
print("  ✓ ниво $151.83, ADR 7.2%: стоп за оразмеряване $140.90 (−7.2%, 1×ADR), очакван стоп $145.82 (−4.0%, 0.55×ADR) като втори ред; без брой акции в картата")

print()
print("── РЕАЛНИ данни към 02.10.2026 (8 тикъра, РЕАЛНИ лидерски перцентили от скана на 903 тикъра) ──")
rows_old, diag_old = q.scan_frames(REAL, lead=FIX["lead"], max_dist_adr=2.0)                                            # старото определение (≤2 ADR) — както е в реалния скан от 02.10
assert [r["ticker"] for r in rows_old] == ["DOCN", "CORT", "CRL"] == FIX["universe_scan"]["candidates"], [r["ticker"] for r in rows_old]
rows, diag = q.scan_frames(REAL, lead=FIX["lead"])                                                                       # правилото от 08.10: нивото най-много 1×ADR над затварянето
assert [r["ticker"] for r in rows] == ["CORT", "CRL"] and diag["beyond_adr"] == 1 and diag["beyond_adr_tickers"] == ["DOCN"] and diag["candidates"] == 2 and diag["max_dist_adr"] == 1.0
dd = {r["ticker"]: r["dist_adr"] for r in rows_old}
assert dd == {"DOCN": 1.17, "CORT": 0.78, "CRL": 0.95}, dd                                                              # "до нивото: X ADR" = pct_to_trigger / ADR (8.4/7.2, 3.7/4.7, 3.0/3.2)
print("  ✓ РЕАЛНО 02.10: до нивото DOCN 1.17 ADR (скрит: над 1×ADR), CORT 0.78, CRL 0.95 → карти CORT и CRL; diag.beyond_adr = 1 ['DOCN']; със старото определение (≤2 ADR) пак са трите")
rows = rows_old
by = {r["ticker"]: r for r in rows}
d, c, k = by["DOCN"], by["CORT"], by["CRL"]
assert (d["trigger"], c["trigger"], k["trigger"]) == (151.83, 120.51, 298.98)
assert (round(d["adr"], 1), round(c["adr"], 1), round(k["adr"], 1)) == (7.2, 4.7, 3.2) and (d["base_days"], c["base_days"], k["base_days"]) == (8, 27, 25)
assert (round(d["runup_pct"]), round(c["runup_pct"]), round(k["runup_pct"])) == (49, 49, 42) and (round(d["pct_to_trigger"], 1), round(c["pct_to_trigger"], 1), round(k["pct_to_trigger"], 1)) == (8.4, 3.7, 3.0)
assert [round(x["tight"], 2) for x in (d, c, k)] == [0.79, 0.81, 0.86] and all(x["vol_ratio"] < 0.8 for x in (d, c, k))
assert (d["levels"]["stop"], c["levels"]["stop"], k["levels"]["stop"]) == (140.91, 114.84, 289.48) and all(x["levels"]["stop"] == x["max_stop"] for x in (d, c, k))     # стоп за оразмеряване = вход × (1 − ADR)
assert [x["levels"]["stop_pct"] for x in (d, c, k)] == [7.19, 4.71, 3.18] == [round(x["adr"], 2) for x in (d, c, k)] and not any("shares" in x for x in (d, c, k))
print("  ✓ DOCN (ниво $151.83 +8.4%, ADR 7.2%, ръст +49%, база 8 сесии, tight 0.79), CORT ($120.51 +3.7%, ADR 4.7%, база 27 сесии, 0.81), CRL ($298.98 +3.0%, ADR 3.2%, база 25 сесии, 0.86) — подредени по стягане")
f = q.compute_features(REAL["PVH"])
assert q.check_candidate(f, f["n"] - 1, FIX["lead"]["PVH"]) is None and q.check_candidate(f, f["n"] - 1, 0.95) is not None
print(f"  ✓ PVH е отхвърлен САМО заради лидерския праг (перцентил {FIX['lead']['PVH']:.2f} < 0.90) — с перцентил 0.95 би бил кандидат; AAPL/NVDA/MSFT/TSLA не са кандидати")
assert all(t not in by for t in ("AAPL", "NVDA", "MSFT", "TSLA", "PVH"))

print()
print("── теглене на данни (подменено yf.download върху РЕАЛНИТЕ кадри) ──")
def multi(tickers):
    return pd.concat({t: REAL[t].copy() for t in tickers}, axis=1)


calls = []
flat_single = [True]
dl_kwargs = []
def fake_download(batch, **kw):
    dl_kwargs.append(kw)
    calls.append(list(batch))
    if "BOOM" in batch:
        raise RuntimeError("Yahoo недостъпен")
    m = multi([t for t in batch if t in REAL])
    return m[batch[0]] if len(batch) == 1 and flat_single[0] else m                                       # yfinance понякога връща плоски колони за един тикър


q.yf = type("Y", (), {"download": staticmethod(fake_download)})
fr, st = q.fetch_frames(["DOCN", "CORT", "AAPL"], batch_size=2, now_utc=dt.datetime(2026, 10, 5, 6, 0, tzinfo=dt.timezone.utc))
assert sorted(fr) == ["AAPL", "CORT", "DOCN"] and st == {"batches": 2, "batches_failed": 0} and calls == [["DOCN", "CORT"], ["AAPL"]]
assert all(len(fr[t]) == len(REAL[t]) for t in fr) and list(fr["DOCN"].columns) == ["Open", "High", "Low", "Close", "Volume"]
flat_single[0] = False                                                                                      # и с MultiIndex за един тикър
fr2, _ = q.fetch_frames(["AAPL"], batch_size=1)
assert sorted(fr2) == ["AAPL"] and len(fr2["AAPL"]) == len(REAL["AAPL"])
fr, st = q.fetch_frames(["DOCN", "BOOM"], batch_size=1)
assert sorted(fr) == ["DOCN"] and st == {"batches": 2, "batches_failed": 1}
print("  ✓ теглене на партиди: кадрите съвпадат с реалните; провалена партида се брои (batches_failed) и не спира останалите")
# без ръчна split корекция (09.10.2026): Yahoo вече е коригирал сплитовете — виж test_qm_split_not_doubled.py (реални данни)
assert not hasattr(q, "split_adjust") and all("actions" not in kw for kw in dl_kwargs) and all(kw.get("auto_adjust") is False for kw in dl_kwargs)
print("  ✓ няма split_adjust и actions=True: теглене с auto_adjust=False, кадрите са каквито ги връща Yahoo")
# незавършена сесия
df = REAL["CORT"]
last = df.index[-1]
mid_session = dt.datetime.combine(last.date(), dt.time(15, 0), tzinfo=dt.timezone.utc)                                     # 11:00 ET същия ден
after_close = dt.datetime.combine(last.date(), dt.time(21, 0), tzinfo=dt.timezone.utc)                                     # 17:00 ET същия ден
next_morning = dt.datetime.combine(last.date() + dt.timedelta(days=3), dt.time(5, 30), tzinfo=dt.timezone.utc)
assert len(q.drop_incomplete(df, mid_session)) == len(df) - 1 and len(q.drop_incomplete(df, after_close)) == len(df) and len(q.drop_incomplete(df, next_morning)) == len(df)
print("  ✓ частичният бар на днешната сесия се маха по време на сесията (11:00 ET); след затварянето и сутринта преди отварянето — остава")
q.fetch_frames = lambda universe, **kw: (_ for _ in ()).throw(RuntimeError("мрежата падна"))
rows, diag = q.scan(universe=["X"])
assert rows == [] and diag["ok"] is False and "RuntimeError" in diag["error"]
print("  ✓ провал на скана → ([], diag с причината) — не чупи брифа")
print()
print("Всички тестове минаха.")
