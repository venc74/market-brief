"""
Пакет 1, т.9 (2026-10-03): Minervini trend template + RS rating (слети със Weinstein Stage 2).

РЕАЛНИ данни (tests/fixtures/ohlc_*.csv — дневни барове от Yahoo, свалени на 02.10.2026):
  AMD, TWLO 21.09.2026 · LNTH, EXEL 26.06.2026 — минават шаблона;
  AMD 16.04.2026 (50DMA $210.57 под 150DMA $215.04) — цялата стара верига (Stage 2, RS Line,
  разстояние до pivot, дълбочина на базата) го пропуска, шаблонът го отхвърля.
Граничните стойности (30% / 25% / строги неравенства / RS перцентил 70) и универсът за
перцентила (филтърни тикъри) са СИНТЕТИЧНИ — маркирани.
Пускане: python test_trend_template.py
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import config
from src import screener

FIX = ROOT / "tests" / "fixtures"
F = lambda s: pd.read_csv(FIX / f"ohlc_{s}.csv", index_col=0, parse_dates=True)
SPY = F("SPY")["Close"]
tt = screener.trend_template_checks

print("── СИНТЕТИЧНО: граници на шаблона (скаларни входове) ──")
BASE = dict(price=100.0, ma50=95.0, ma150=90.0, ma200=80.0, ma150_prev=89.0, ma200_prev=79.0, high52=110.0, low52=60.0)
def chk(**over):
    a = {**BASE, **over}
    return tt(a.pop("price"), a.pop("ma50"), a.pop("ma150"), a.pop("ma200"), **a)
assert all(chk().values())
# строги неравенства: равенство НЕ минава (всяка проверка поотделно)
assert not chk(price=90.0)["stage2_price_above_ma150"]                      # price == ma150
assert not chk(ma150_prev=90.0)["stage2_ma150_rising"]                      # ma150 == ma150_prev
assert not chk(ma200=90.0)["ma150_above_ma200"]                             # ma150 == ma200
assert not chk(ma200_prev=80.0)["ma200_rising"]                             # ma200 == ma200_prev
assert not chk(ma50=90.0)["ma50_above_ma150_ma200"]                         # ma50 == ma150
assert not chk(ma50=100.0)["price_above_ma50"]                              # price == ma50
assert chk(price=100.0, ma50=99.99)["price_above_ma50"]
print("  ✓ цена == 150DMA, 150DMA == преди 21 сесии, 150 == 200, 200 == преди, 50 == 150, цена == 50DMA → НЕ минават (строго)")

# 52-седмичен диапазон: ≥ +30% над дъното и ≤ 25% под върха — равенството минава
assert chk(price=65.0, ma50=60.0, ma150=55.0, ma200=50.0, ma150_prev=54.0, ma200_prev=49.0, low52=50.0, high52=80.0)["above_52w_low"]
assert not chk(price=64.99, ma50=60.0, ma150=55.0, ma200=50.0, ma150_prev=54.0, ma200_prev=49.0, low52=50.0, high52=80.0)["above_52w_low"]
assert chk(price=75.0, ma50=70.0, ma150=65.0, ma200=60.0, ma150_prev=64.0, ma200_prev=59.0, low52=40.0, high52=100.0)["near_52w_high"]
assert not chk(price=74.99, ma50=70.0, ma150=65.0, ma200=60.0, ma150_prev=64.0, ma200_prev=59.0, low52=40.0, high52=100.0)["near_52w_high"]
orig = (config.TT_MIN_ABOVE_52W_LOW_PCT, config.TT_MAX_BELOW_52W_HIGH_PCT)
config.TT_MIN_ABOVE_52W_LOW_PCT, config.TT_MAX_BELOW_52W_HIGH_PCT = 50.0, 10.0       # праговете са параметри
assert not chk(price=65.0, low52=50.0)["above_52w_low"] and not chk(price=100.0, high52=112.0)["near_52w_high"]
config.TT_MIN_ABOVE_52W_LOW_PCT, config.TT_MAX_BELOW_52W_HIGH_PCT = orig
print("  ✓ +30.00% над дъното / -25.00% под върха минават, +29.99% / -25.01% — не; праговете са параметри")
print()

print("── РЕАЛНИ: четирите брифа минават шаблона; два реални случая го нарушават ──")
for sym, last in (("AMD", "2026-09-21"), ("TWLO", "2026-09-21"), ("LNTH", "2026-06-26"), ("EXEL", "2026-06-26")):
    r = screener._evaluate_technicals(sym, F(sym).loc[:last], SPY.loc[:last])
    assert r is not None and r["trend_template_applied"] is True, (sym, last)
    print(f"  {sym} {last}: +{r['pct_above_52w_low']}% над 52-седм. дъно, -{r['pct_below_52w_high']}% под върха → минава")
amd_apr = F("AMD").loc[:"2026-04-16"]
assert screener._evaluate_technicals("AMD", amd_apr, SPY.loc[:"2026-04-16"]) is None          # 50DMA $210.57 < 150DMA $215.04
config.TREND_TEMPLATE_ENABLED = False                                                          # само старата верига
r_amd = screener._evaluate_technicals("AMD", amd_apr, SPY.loc[:"2026-04-16"])
config.TREND_TEMPLATE_ENABLED = True
assert r_amd is not None and r_amd["trend_template_applied"] is False and r_amd["price"] == 278.26
print("  ✓ AMD 16.04.2026 (close $278.26, 50DMA $210.57 под 150DMA $215.04): със стария филтър минава, с шаблона — не;")
print("    още 3 дни (17, 20, 21.04) са в същото положение; в останалите ~480 тикъро-дни от четирите фикстури шаблонът не променя нищо")
print()

print("── RS score: 40% последното тримесечие + по 20% за трите преди него ──")
q = config.RS_QUARTER_BARS
def series_from(pts, n_pre=3):
    """СИНТЕТИЧНО: линейни отсечки между 5 опорни цени през 4 тримесечия (63 сесии всяко)."""
    xs = [np.linspace(pts[i], pts[i + 1], q + 1)[:-1] if i < 3 else np.linspace(pts[i], pts[i + 1], q + 1) for i in range(4)]
    return pd.Series(np.concatenate(xs))
pts = [100.0, 130.0, 130.0, 117.0, 140.4]                  # Q4=+30%, Q3=0%, Q2=-10%, Q1=+20%
c = series_from(pts)
assert len(c) == 4 * q + 1 and c.iloc[0] == 100.0 and c.iloc[-1] == 140.4
exp = 0.4 * (140.4 / 117.0 - 1) + 0.2 * (117.0 / 130.0 - 1) + 0.2 * (130.0 / 130.0 - 1) + 0.2 * (130.0 / 100.0 - 1)
assert abs(screener.rs_score(c) - exp) < 1e-12 and abs(exp - (0.4 * 0.2 + 0.2 * -0.1 + 0 + 0.2 * 0.3)) < 1e-12
assert screener.rs_score(c.iloc[1:]) is None                              # 4 тримесечия + 1 бар не достигат (252 бара)
assert screener.rs_score(pd.Series([100.0] * 300).where(lambda s: s.index != 299)) is None       # NaN в опорна точка
assert screener.rs_score(pd.Series([0.0] + [100.0] * 4 * q)) is None      # нулева цена
print("  ✓ +20% / -10% / 0% / +30% по тримесечия → 0.4×0.2 + 0.2×(-0.1) + 0.2×0 + 0.2×0.3 = +0.12; под 253 бара, NaN и нула → None")
for sym, last, want in (("AMD", "2026-09-21", 0.448), ("EXEL", "2026-06-26", 0.117)):
    sc = screener.rs_score(F(sym).loc[:last]["Close"])
    print(f"  РЕАЛЕН {sym} {last}: претеглена доходност {sc:+.3f}")
    assert sc is not None and abs(sc - want) < 0.0005, (sym, sc)
print()

print("── RS перцентил: целочислен, закръглен надолу (СИНТЕТИЧЕН универс) ──")
scores = {f"T{i:03d}": i / 1000 for i in range(1, 201)}                   # 200 тикъра, T200 е най-силният
rt = screener.rs_ratings(scores)
assert rt["T200"] == 100 and rt["T140"] == 70 and rt["T139"] == 69 and rt["T001"] == 1 and rt["T002"] == 1 and rt["T003"] == 1
assert rt["T004"] == 2                                                     # ранг 4 × 100 / 200 = 2.0
ties = screener.rs_ratings({"A": 1.0, "B": 1.0, "C": 2.0, "D": 3.0})        # A,B делят рангове 1 и 2 → средно 1.5 → 37.5 → 37
assert ties == {"A": 37, "B": 37, "C": 75, "D": 100}, ties
print("  ✓ ранг 140 от 200 → 70 (минава), 139 → 69 (не); най-слабият е 1 (не 0), най-силният 100; равни стойности делят средния ранг")

rows = [{"ticker": t} for t in ("T139", "T140", "T200")]
out = screener.apply_rs_rating([dict(r) for r in rows], scores)
assert [r["ticker"] for r in out] == ["T140", "T200"] and [r["rs_rating"] for r in out] == [70, 100]
config.TREND_TEMPLATE_ENABLED = False                                      # изключен шаблон: рейтингът се показва, не филтрира
out = screener.apply_rs_rating([dict(r) for r in rows], scores)
config.TREND_TEMPLATE_ENABLED = True
assert [r["ticker"] for r in out] == ["T139", "T140", "T200"] and [r["rs_rating"] for r in out] == [69, 70, 100]
small = {f"S{i}": i / 100 for i in range(config.RS_RATING_MIN_UNIVERSE - 1)}      # твърде малък универс → не режем
out = screener.apply_rs_rating([{"ticker": "S0"}, {"ticker": "S5"}], small)
assert len(out) == 2 and all(r["rs_rating"] is None for r in out)
print(f"  ✓ филтър RS ≥ {config.RS_RATING_MIN:g}: T139 отпада; изключен шаблон → само показва; универс < {config.RS_RATING_MIN_UNIVERSE} → без филтър (предупреждение)")
print()

print("── technical_screen: перцентилът е върху ЦЕЛИЯ универс, не върху оцелелите (подменен yf) ──")
rng = np.random.default_rng(7)
idx = pd.bdate_range(end="2026-10-02", periods=300)
univ = {}
for i in range(1, 181):                                                    # 180 СИНТЕТИЧНИ тикъра с разпръснати доходности
    drift = (i - 90) / 90 * 0.002
    path = 50 * np.exp(np.cumsum(rng.normal(drift, 0.01, len(idx))))
    univ[f"U{i:03d}"] = pd.DataFrame({"Open": path, "High": path * 1.01, "Low": path * 0.99, "Close": path,
                                      "Volume": 1_000_000.0}, index=idx)
tickers = list(univ)
real_scores = {t: screener.rs_score(univ[t]["Close"]) for t in tickers}
by_score = sorted(real_scores, key=real_scores.get)
mid, high, top = by_score[int(0.5 * len(by_score))], by_score[int(0.75 * len(by_score))], by_score[-1]


def fake_download(sym, **kw):
    if isinstance(sym, str):                                               # SPY
        return pd.DataFrame({"Close": univ[tickers[0]]["Close"]})
    return pd.concat({t: univ[t] for t in sym}, axis=1)


orig_dl, orig_eval = screener.yf.download, screener._evaluate_technicals
screener.yf.download = fake_download
survivors_for_test = {mid, high, top}
screener._evaluate_technicals = lambda sym, df, spy: ({"ticker": sym, "price": 10.0} if sym in survivors_for_test else None)
orig_sleep = screener.time.sleep
screener.time.sleep = lambda s: None
try:
    res = screener.technical_screen(tickers, batch_size=60)
finally:
    screener.yf.download, screener._evaluate_technicals, screener.time.sleep = orig_dl, orig_eval, orig_sleep
got = {r["ticker"]: r["rs_rating"] for r in res}
exp_rt = screener.rs_ratings(real_scores)
assert set(got) == {high, top} and got[high] == exp_rt[high] >= 70 and got[top] == exp_rt[top], got
assert exp_rt[mid] < 70 and all("rs_score" in r for r in res)
print(f"  ✓ 3 оцелели (RS {exp_rt[mid]} / {exp_rt[high]} / {exp_rt[top]} в универс от {len(tickers)}): остават с RS ≥ 70 — рейтингът на {high} е {got[high]}, не се смята върху 3-те оцелели")

print()
print("Всички тестове минаха.")
