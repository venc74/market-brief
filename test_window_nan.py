"""
Пакет 2 · т.9 (2026-10-03): VIX (thermometer.vix_level) и global_market_signals() вече не ползват позиционно `.iloc[-6]` без NaN
проверка — седмицата назад е последният бар на или преди 7 календарни дни от ПОСЛЕДНИЯ бар (както MOVE от 25.09), а NaN в
последния бар или липса на стойност за котвата → сигналът се пропуска/скрива с ред в лога, вместо "nan" към AI.

РЕАЛНО: дневните Close от tests/fixtures/yahoo_closes_2026-10-02.json (Yahoo, свалени 03.10.2026). Реален случай: ^TNX няма бар
за 07.09.2026 (Labor Day) → за 08.09 позиционната котва е 31.08 (4.758), а календарната е 01.09 (4.796): +4.8 б.п. срещу +1.0 б.п.
Записаният VIX в брифа от 02.10 (16.39, +4.59%) се възпроизвежда точно. ИЗМЕРЕНО ЕДНОКРАТНО върху 2г жива Yahoo история на 03.10
(не се проверява в теста — мрежата е изключена): котвата по позиция се различава от календарната в 86 от 499 дни (VIX), 94 от 497
(^TNX); флагът за скок на VIX (>= 20%) се обръща в 5 от 499 дни; персентилите на 5-дневната промяна на VIX се мръднаха малко
(90-ти: 18.9 → 20.1, 95-ти: 27.4 → 27.6) — прагът 20% остава на мястото си. СИНТЕТИЧНО: всички серии с дупки/NaN по-долу.
Пускане: python test_window_nan.py
"""
import sys, pathlib, json, datetime as dt, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import macro_layer as ml, thermometer as th
from src.series_utils import last_and_week_ago

FX = json.loads((ROOT / "tests" / "fixtures" / "yahoo_closes_2026-10-02.json").read_text(encoding="utf-8"))["series"]
BY_SYMBOL = {d["symbol"]: d["closes"] for d in FX.values()}
BRIEF = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-02.json").read_text(encoding="utf-8"))


def real(symbol, upto):
    return pd.Series({pd.Timestamp(k): v for k, v in BY_SYMBOL[symbol].items() if k <= upto}, dtype=float)


def patch(series_by_symbol):
    class _T:
        def __init__(self, sym): self.s = series_by_symbol.get(sym)
        def history(self, period="1mo"):
            return pd.DataFrame({"Close": self.s}) if self.s is not None else pd.DataFrame()
    ml.yf.Ticker = _T; th.yf.Ticker = _T
    ml._is_stale = lambda *a, **k: False


def quiet(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn()
    return r, buf.getvalue()


print("── помощникът: седмица назад по дата ──")
s = real("^TNX", "2026-09-08")
last, wk, d = last_and_week_ago(s)
assert (last, wk, d) == (4.806, 4.796, dt.date(2026, 9, 8))                      # котва 01.09, не 31.08 (iloc[-6])
assert s.iloc[-6] == 4.758 and round((last - s.iloc[-6]) * 100, 1) == 4.8 and round((last - wk) * 100, 1) == 1.0
print("  ✓ РЕАЛНО ^TNX на 08.09.2026 (07.09 няма бар): котва 01.09 = 4.796 → +1.0 б.п.; позиционната (31.08 = 4.758) даваше +4.8 б.п.")
g, _ = quiet(lambda: (patch({"^TNX": s}), ml.global_market_signals())[1])
assert g["US10Y"] == {"value": 4.81, "chg_5d_bp": 1.0}, g
print("  ✓ global_market_signals() през същия случай: US10Y {'value': 4.81, 'chg_5d_bp': 1.0}")

v = real("^VIX", "2026-10-01")
patch({"^VIX": v})
vi = th.vix_level()
assert (vi["value"], vi["chg_5d"], vi["pct_5d"]) == (16.39, 0.72, 4.6) and not vi["spike"], vi
rec = next(i for i in BRIEF["thermometer"]["indicators"] if i["name"] == "VIX")
assert (rec["value"], rec["pct_5d"]) == (16.39, 4.6), rec                        # РЕАЛНО: същото като записаното на 02.10
print("  ✓ РЕАЛНО VIX до 01.10: 16.39, +0.72 (+4.6%) — идентично със записаното в брифа от 02.10")
print()

print("── СИНТЕТИЧНО: дупка в историята (липсващ бар) ──")
idx = pd.bdate_range("2026-09-01", "2026-09-17")
base = pd.Series(range(len(idx)), index=idx, dtype=float) + 10.0
holed = base.drop(pd.Timestamp("2026-09-14"))                                     # липсва бар ВЪТРЕ в прозореца (понеделник)
last, wk, _ = last_and_week_ago(holed)
assert last == base.loc["2026-09-17"]
assert wk == base.loc["2026-09-10"]                                               # по дата: точно 7 календарни дни назад
pos = holed.iloc[-6]
assert holed.index[-6] == pd.Timestamp("2026-09-09") and pos == base.loc["2026-09-09"] and pos != wk      # по позиция: 8 дни назад
print(f"  ✓ без бар за 14.09: котвата на 17.09 е 10.09 ({wk:.0f}); `.iloc[-6]` щеше да хване {holed.index[-6].date()} ({pos:.0f}) — 8 дни назад")
full_last, full_wk, _ = last_and_week_ago(base)
assert full_wk == base.loc["2026-09-10"]                                          # пълна история → точно 7 календарни дни
print("  ✓ пълна история → точно 7 календарни дни (10.09)")
for bad, msg in ((pd.Series([], dtype=float), "празна"), (base.iloc[:3], "няма стойност"), (None, "празна")):
    try:
        last_and_week_ago(bad); raise SystemExit("трябваше да вдигне ValueError: " + msg)
    except ValueError as e:
        assert msg.split()[0] in str(e), (msg, str(e))
nan_last = base.copy(); nan_last.iloc[-1] = float("nan")
try:
    last_and_week_ago(nan_last); raise SystemExit("NaN в последния бар трябваше да вдигне ValueError")
except ValueError as e:
    assert "NaN" in str(e)
nan_anchor = base.copy(); nan_anchor.loc["2026-09-10"] = float("nan")
_, wk, _ = last_and_week_ago(nan_anchor)
assert wk == base.loc["2026-09-09"]                                                # NaN котва → последната валидна преди нея
print("  ✓ празна серия / твърде къса / None / NaN в последния бар → ValueError; NaN в котвата → последната валидна стойност преди нея")
print()

print("── СИНТЕТИЧНО: флагът за скок на VIX не зависи от празник ──")
# 7 календарни дни = 5 бара без празник; с празник в прозореца позиционната котва е 1 бар по-стара
vix_idx = pd.bdate_range("2026-11-16", "2026-12-04").drop(pd.Timestamp("2026-11-26"))      # Thanksgiving: няма бар
vals = pd.Series([15.0] * len(vix_idx), index=vix_idx)
vals.loc["2026-11-25"] = 14.0                                                              # котвата за 02.12 по дата → 25.11
vals.loc["2026-11-24"] = 11.0                                                              # 5 бара назад (по позиция) е 24.11
vals.loc["2026-12-02"] = 17.0
patch({"^VIX": vals[vals.index <= "2026-12-02"]})
vi = th.vix_level()
assert vi["chg_5d"] == 3.0 and vi["pct_5d"] == 21.4 and vi["spike"] is True, vi            # (17 − 14) / 14, по дата
old_pct = (17.0 - vals.loc["2026-11-24"]) / vals.loc["2026-11-24"] * 100
assert round(old_pct, 1) == 54.5                                                           # позиционното дава +54.5%: друг размер на скока
print(f"  ✓ Thanksgiving: по дата 17.0 срещу 14.0 = +21.4% (скок ≥ {config.VIX_SPIKE_WEEKLY_PCT:.0f}%); по позиция щеше да е срещу 11.0 = +54.5%")
print()

print("── СИНТЕТИЧНО: NaN в последния бар → сигналът се пропуска/скрива, не 'nan' ──")
nanv = real("^VIX", "2026-10-01"); nanv.iloc[-1] = float("nan")
nant = real("^TNX", "2026-10-01"); nant.iloc[-1] = float("nan")
patch({"^VIX": nanv, "^TNX": nant, "GC=F": real("GC=F", "2026-10-01")})
g, log = quiet(ml.global_market_signals)
assert "VIX" not in g and "US10Y" not in g and "Gold" in g
assert "nan" not in json.dumps(g).lower()
assert "[macro] VIX failed" in log and "NaN Close" in log
vi, log2 = quiet(th.vix_level)
assert vi["hide"] is True and vi["value"] is None and "NaN Close" in log2
print("  ✓ global_market_signals: VIX и US10Y изпадат (ред в лога 'NaN Close'), златото остава, в изхода няма 'nan'")
print("  ✓ vix_level(): hide=True, value=None (термометърът го скрива; не влиза в броенето)")

short = real("^VIX", "2026-09-04").iloc[-3:]                                      # само 3 бара → няма история за седмица назад
patch({"^VIX": short})
vi, log3 = quiet(th.vix_level)
assert vi["hide"] is True and "insufficient VIX history" in log3
print("  ✓ къса история (3 бара) → vix_level() скрит, не изключение")
print()
print("Всички тестове минаха.")
