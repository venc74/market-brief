"""
С5 (втори преглед, 10.10.2026) · закрепени yfinance/pandas + дневно канарче за split корекцията на Yahoo (src/data_canary.py).

РЕАЛНО: close-овете на NVDA 05–11.06.2024 от Yahoo, коригирани само за сплитове (auto_adjust=False), измерени на 10.10.2026 с yfinance 1.5.2 И 1.7.0 — 07.06 = $120.888
(1208.88 / 10, сплит 10:1 на 10.06.2024); requirements.txt. СИНТЕТИЧНО: двойна корекция (÷10 още веднъж), липсваща корекция (×10), паднало теглене, липсващ бар.
Без мрежа: тегленето е подменено с DataFrame във формата на yf.download (колони по тикър).
Пускане: python test_data_canary.py
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import data_canary, data_warnings

REAL = {"2024-06-05": 122.44, "2024-06-06": 120.998, "2024-06-07": 120.888, "2024-06-10": 121.79, "2024-06-11": 120.91}


def fake(mult=1.0, drop=None):
    def dl(ticker, **kw):
        assert ticker == "NVDA" and kw.get("auto_adjust") is False                      # книгите и GLB са върху auto_adjust=False
        d = {k: v * mult for k, v in REAL.items() if k != drop}
        idx = pd.to_datetime(list(d))
        return pd.DataFrame({("Close", "NVDA"): list(d.values()), ("Open", "NVDA"): list(d.values())}, index=idx)
    return dl


print("── 1. версиите са закрепени ──")
req = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
assert "yfinance==1.7.0" in req and "pandas==3.0.6" in req and not any(l.startswith(("yfinance>=", "pandas>=")) for l in req)
print("  ✓ requirements.txt: yfinance==1.7.0, pandas==3.0.6 (версиите на production от run-а на 09.10)")

print()
print("── 2. канарчето ──")
ok = data_canary.check(fake())
assert ok["ok"] is True and ok["close"] == 120.888 and data_warnings.collect(None, None, canary=ok) == []
dbl = data_canary.check(fake(0.1))
assert dbl["ok"] is False and dbl["close"] == 12.089
w = data_warnings.collect(None, None, canary=dbl)
assert len(w) == 1 and w[0]["source"] == "data_canary" and w[0]["level"] == "error" and "$12.089 вместо ≈ $120.888" in w[0]["message"]
raw = data_canary.check(fake(10.0))
assert raw["ok"] is False and raw["close"] == 1208.88
near = data_canary.check(fake(1.004))
assert near["ok"] is True                                                                 # 0.4% (дивидентна корекция ≈ −0.3% е под толеранса 1%)
fail = data_canary.check(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("YFRateLimitError (СИНТЕТИЧНО)")))
fw = data_warnings.collect(None, None, canary=fail)                                       # 19.10 (т. 12): канарче без проверка — ред "warn", не тишина (до 19.10 — без банер)
assert fail["ok"] is None and "YFRateLimitError" in fail["error"] and [(w["source"], w["level"]) for w in fw] == [("data_canary", "warn")] and "не провери днес" in fw[0]["message"]
nobar = data_canary.check(fake(drop="2024-06-07"))
assert nobar["ok"] is None and "няма бар" in nobar["error"]
print("  ✓ РЕАЛНИТЕ стойности → OK, без банер; СИНТЕТИЧНО двойна корекция ($12.089) / липсваща ($1208.88) → банер 'error'; 0.4% → OK; паднало теглене / липсващ бар → неизвестно, ред 'warn' (не провери днес)")

print()
print("── 3. main записва канарчето и го подава на банерите ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "canary = data_canary.check() if config.ENABLE_DATA_CANARY else None" in src and "canary=canary" in src and '"data_canary": canary,' in src
print("  ✓ data_canary.check() се пуска в main; резултатът е в брифа (data_canary) и в data_warnings")
print()
print("Всички тестове минаха.")
