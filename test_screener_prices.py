"""
Втори преглед (10.10.2026) · CANSLIM скрийнърът тегли цени, коригирани САМО за сплитове (config.SCREENER_AUTO_ADJUST = False), както книгите, GLB и QM.
Измерено на 10.10 (898 тикъра): pivot при дивидентна корекция е по-нисък от реалния при 503 тикъра (> 1% при 79, P90 0.95%, макс 3.83%); книгата симулира върху реални цени.
РЕАЛНО: дневните барове на EXPD и SPY до 06.10.2026 (tests/fixtures/screen_real_2026-10-06.json). СИНТЕТИЧНО: колоната "Adj Close" (каквато Yahoo връща при auto_adjust=False),
подмененото yf.download.
Пускане: python test_screener_prices.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import screener

SCR = json.loads((ROOT / "tests" / "fixtures" / "screen_real_2026-10-06.json").read_text(encoding="utf-8"))
f = SCR["frames"]["EXPD"]
DF = pd.DataFrame({"Open": f["c"], "High": f["h"], "Low": f["l"], "Close": f["c"], "Volume": f["v"]}, index=pd.to_datetime(f["dates"]))
SPY = pd.Series(SCR["spy"]["c"], index=pd.to_datetime(SCR["spy"]["dates"]))
assert config.SCREENER_AUTO_ADJUST is False

calls = []
def fake_dl(tickers, **kw):
    calls.append(kw.get("auto_adjust"))
    if tickers == "SPY":
        return pd.DataFrame({"Close": SPY, "Adj Close": SPY * 0.98})
    return DF.assign(**{"Adj Close": DF["Close"] * 0.98})                           # СИНТЕТИЧНО: дивидентно коригираният close, който НЕ се ползва
screener.yf.download = fake_dl
screener.time.sleep = lambda s: None
config.RS_LINE_HYSTERESIS = False
with contextlib.redirect_stdout(io.StringIO()):
    rows = screener.technical_screen(["EXPD"])
    expl = screener.explain_exits(["EXPD"])
assert calls and all(a is False for a in calls), calls
ref = screener._evaluate_technicals("EXPD", DF, SPY)
assert (rows[0]["pivot"] if rows else None) == (ref["pivot"] if ref else None)
assert ref is None or ref["pivot"] == round(float(screener.compute_pivot(DF["High"])), 2)
print(f"  ✓ всички {len(calls)} тегления (SPY, партидата, explain_exits) са с auto_adjust=False; pivot на EXPD = върху реалните High (Adj Close не влияе)")
print()
print("Всички тестове минаха.")
