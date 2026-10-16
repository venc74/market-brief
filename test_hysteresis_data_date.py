"""
16.10.2026 · В2в (трети преглед): броячите на хистерезиса (override-и, дни без данни) и блокът от distribution days се движат по ДАТАТА НА ДАННИТЕ (последния бар на серията / на SPY),
не по деня на брифа — повторена стойност (застоял бар, облигационен празник) не е нов ден.

РЕАЛНО: tests/fixtures/move_spy_bars_2026-07-01_10-15.json — дневните затваряния на ^MOVE и SPY от Yahoo (16.10.2026): ^MOVE няма бар за 07.09 (Labor Day) и 12.10 (облигационен празник) →
брифовете от 12.10 и 13.10 четат същото 09.10 (98.47); в git историята на data/regime_override_state.json move_spike е 7 на 12.10 и 8 на 13.10 (отброен "нов" ден без нови данни).
tests/fixtures/ohlc_SPY_2026-10-07.csv и ohlc_QQQ_2026-10-07.csv — за distribution days. СИНТЕТИЧНО (маркирано): файлът със състоянието (временен), изключената проверка за давност
(тя има свой тест), подмененият yf.Ticker.
Пускане: python test_hysteresis_data_date.py
"""
import sys, json, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import thermometer as th

FX = json.loads((ROOT / "tests" / "fixtures" / "move_spy_bars_2026-07-01_10-15.json").read_text(encoding="utf-8"))
SER = {s: pd.Series(FX[s]["close"], index=pd.to_datetime(FX[s]["dates"])) for s in ("^MOVE", "SPY")}
_tmp = tempfile.TemporaryDirectory(prefix="mb_hyst_")
th._OVERRIDE_STATE_FILE = pathlib.Path(_tmp.name) / "regime_override_state.json"
quiet = lambda: contextlib.redirect_stdout(io.StringIO())

class Tk:                                                                          # СИНТЕТИЧНО: yf.Ticker върху РЕАЛНИТЕ серии, отрязани до сутринта на брифа
    cut = None
    def __init__(self, sym): self.sym = sym
    def history(self, period=None, **k):
        s = SER[self.sym][SER[self.sym].index < pd.Timestamp(Tk.cut)]
        return pd.DataFrame({"Close": s})

print("── 1. MOVE: датата на последния бар в брифовете от 12.10 и 13.10 (РЕАЛНИ барове) ──")
real_tk, real_stale = th.yf.Ticker, th._is_stale
th.yf.Ticker, th._is_stale = Tk, (lambda ts: False)                                   # СИНТЕТИЧНО: давността има свой тест
try:
    got = {}
    for brief in ("2026-10-12", "2026-10-13", "2026-10-14", "2026-09-07", "2026-09-08"):
        Tk.cut = brief
        with quiet():
            m = th.move_index()
        got[brief] = (m["as_of"], m["value"])
finally:
    th.yf.Ticker, th._is_stale = real_tk, real_stale
assert got["2026-10-12"] == got["2026-10-13"] == ("2026-10-09", 98.5) and got["2026-10-14"] == ("2026-10-13", 101.1)
assert got["2026-09-07"] == got["2026-09-08"] == ("2026-09-04", 73.1)
print("  ✓ 12.10 и 13.10 → бар от 09.10 (98.5); 07.09 и 08.09 → бар от 04.09 (73.1); 14.10 → 13.10")

print()
print("── 2. брояч на override-а: един и същ бар не е нов ден ──")
def run(days, key="move_spike", raw=False):
    th._OVERRIDE_STATE_FILE.unlink(missing_ok=True)
    out = []
    with quiet():
        for d in days:
            out.append(th._hysteresis_effective(key, raw, d))
    return out
assert run(["2026-10-09", "2026-10-09"]) == [(True, 1), (True, 1)]                     # по датата на данните: 12.10 и 13.10 са ЕДИН ден → override-ът още се държи
assert run(["2026-10-12", "2026-10-13"]) == [(True, 1), (False, 2)]                     # старото поведение (по деня на брифа) — свободен след 2 "дни" с едни и същи данни
assert run(["2026-10-09", "2026-10-13"]) == [(True, 1), (False, 2)]                     # истински нов бар на 13.10 → втори ден
src = (ROOT / "src" / "thermometer.py").read_text(encoding="utf-8")
assert '_hysteresis_effective("move_spike", move_spike_raw, move_ind.get("as_of") or today_iso)' in src and '_hysteresis_effective("credit_spike", credit_spike_raw, credit_ind.get("as_of") or today_iso)' in src
assert '_hysteresis_hidden("move_spike", market_day)' in src and '_hysteresis_hidden("credit_spike", market_day)' in src
print("  ✓ 09.10 два пъти → streak 1 (държи); по деня на брифа (12.10, 13.10) → 2 (беше освободен); build_thermometer подава датата на бара")

print()
print("── 3. скрит индикатор: дните без данни — по деня на пазара (последния бар на SPY) ──")
th._OVERRIDE_STATE_FILE.write_text(json.dumps({"move_spike": {"streak_below": 0, "last_date": "2026-10-08"}}), encoding="utf-8")
with quiet():
    a = th._hysteresis_hidden("move_spike", "2026-10-09"); b = th._hysteresis_hidden("move_spike", "2026-10-09"); c = th._hysteresis_hidden("move_spike", "2026-10-13")
assert (a[2], b[2], c[2]) == (1, 1, 2)
print("  ✓ същият бар на SPY → frozen_days не расте; нов бар → +1")

print()
print("── 4. блокът от distribution days — по датата на бара (РЕАЛНИТЕ SPY/QQQ до 07.10) ──")
from src import entry_timing as et
H = {s: pd.read_csv(ROOT / "tests" / "fixtures" / f"ohlc_{s}_2026-10-07.csv", index_col=0, parse_dates=True) for s in ("SPY", "QQQ")}
real_fwt = et.net_utils.fetch_with_timeout
SYM = ["SPY"]
calls = []
def fake_fetch(fn, *a, **k):                                                          # СИНТЕТИЧНО: подменено теглене, РЕАЛНИТЕ барове
    sym = SYM.pop(0)
    calls.append(sym)
    return H[sym]
et.net_utils.fetch_with_timeout = fake_fetch
try:
    SYM[:] = ["SPY", "QQQ"]
    with quiet():
        dd = et.evaluate_distribution_days()
finally:
    et.net_utils.fetch_with_timeout = real_fwt
assert dd["as_of"] == "2026-10-07" and calls == ["SPY", "QQQ"]                       # статусът ok/partial/failed — test_distribution_status.py
th._OVERRIDE_STATE_FILE.write_text(json.dumps({"distribution_block": {"blocked": True, "streak_nonred": 0, "last_date": "2026-10-06", "seed": {"version": config.DISTRIBUTION_SEED_VERSION}}}), encoding="utf-8")
nonred = {**dd, "status": "yellow"}
with quiet():
    b1 = th._distribution_block(nonred, nonred["as_of"]); b2 = th._distribution_block(nonred, nonred["as_of"])
assert b1["nonred_days"] == b2["nonred_days"] == 1 and b1["blocked"] and b2["blocked"]
assert "_distribution_block(distribution_days, (distribution_days or {}).get(\"as_of\") or today_iso, history)" in src
print(f"  ✓ distribution days носят датата на бара ({dd['as_of']}); два пъти същият бар → 1/2 нечервени дни (блокът се държи), не 2/2")
print("\n✅ test_hysteresis_data_date: всичко мина")
