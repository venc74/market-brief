"""
20.10.2026 · етап 3, част Б (решено 20.10): частичният днешен бар — и в скрийнъра, QM и термометъра (вкл. distribution days), не само в симулациите на книгите и GLB.

Повторен run в хода на US сесията получава от Yahoo ЧАСТИЧЕН бар за днес (19.10, 18:55 UTC: SPY с обем 22 млн при 64 млн на 16.10; пробното пускане на 20.10 по обед:
VIX 18.68 срещу 18.44 сутринта). Сутрин в 07:30 такъв бар няма — нищо не се реже (реплеят на 24 брифа: 0 разлики). Макро фючърсите НЕ се режат — живата нощна цена
с днешна дата е нарочна.

РЕАЛНО: tests/fixtures/ohlc_SPY.csv (дневни барове до 02.10). СИНТЕТИЧНО (означено): частичният ред с днешна дата, подмененият yfinance.
Пускане: python test_partial_bar_cut.py
"""
import sys, re, pathlib, datetime as dt, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
from src import sessions, thermometer, qm_breakout

SPY = pd.read_csv(ROOT / "tests/fixtures/ohlc_SPY.csv", index_col=0, parse_dates=True)
today = pd.Timestamp(dt.date.today())
partial = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1.0]}, index=[today])   # СИНТЕТИЧНО: частичен ред днес
with_partial = pd.concat([SPY, partial])
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. cut_today ──")
assert sessions.cut_today(with_partial).index[-1] == SPY.index[-1] and len(sessions.cut_today(SPY)) == len(SPY)
print(f"  ✓ редът с днешна дата ({today.date()}) се маха; без такъв ред — нищо")

print()
print("── 2. термометърът: SPY тренд върху РЕАЛНИТЕ барове + частичен ред (СИНТЕТИЧНО) ──")


class _T:
    def __init__(self, sym): self.sym = sym
    def history(self, period="1y"): return with_partial.copy()


real_yf, real_stale = thermometer.yf, thermometer._is_stale
thermometer.yf = type("YF", (), {"Ticker": _T})
thermometer._is_stale = lambda *a, **k: False                                                                       # fixture-ът е стар — свежестта е друг тест
try:
    with q():
        r = thermometer.spy_trend()
finally:
    thermometer.yf, thermometer._is_stale = real_yf, real_stale
assert r["value"] == round(float(SPY["Close"].iloc[-1]), 2) and r["as_of"] == SPY.index[-1].date().isoformat()
print(f"  ✓ SPY {r['value']} към {r['as_of']} — частичният ред (close 1.0) не влиза")

print()
print("── 3. QM: тегленето на кадрите (СИНТЕТИЧЕН yf.download с реалните барове) ──")
real_dl = qm_breakout.yf.download
qm_breakout.yf.download = lambda batch, **k: pd.concat({t: with_partial for t in batch}, axis=1)
try:
    with q():
        frames, st = qm_breakout.fetch_frames(["SPY"])
finally:
    qm_breakout.yf.download = real_dl
assert frames["SPY"].index[-1] == SPY.index[-1]
print("  ✓ кадърът на QM свършва на последния завършен бар")

print()
print("── 4. всички места на скрийнъра, термометъра, QM и distribution days минават през cut_today; макрото — не ──")
src = {f: (ROOT / "src" / f).read_text(encoding="utf-8") for f in ("thermometer.py", "screener.py", "qm_breakout.py", "entry_timing.py", "macro_layer.py")}
for f in ("thermometer.py", "screener.py", "qm_breakout.py", "entry_timing.py"):
    raw = [l for l in src[f].splitlines() if re.search(r"yf\.download\(|yf\.Ticker\([^)]*\)\.history\(", l) and not l.strip().startswith("#") and '"""' not in l
           and "cut_today" not in l and "data = yf.download(batch, period=\"1y\"" not in l]
    assert not raw, (f, raw)
assert src["qm_breakout.py"].count("_sessions.cut_today(data)") == 1 and "cut_today" not in src["macro_layer.py"]
print("  ✓ thermometer (SPY, VIX, MOVE, VIX9D/VIX/VIX3M, IEI/HYG, breadth), screener (SPY ×2, партидите, explain_exits), qm_breakout, entry_timing; macro_layer — живата цена")
print("\n✅ test_partial_bar_cut: всичко мина")
