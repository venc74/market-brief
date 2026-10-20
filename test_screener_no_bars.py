"""
20.10.2026 · етап 3б (обвивката, стъпка 1): банерът за непълен скрийнър — спрямо нормалния фон. Старият праг ("с история < 90% от универса") не сработи в пробното пускане
при ограничение на 20.10: 865 от 903 с история, 869 с поне един бар — 34 тикъра без НИТО ЕДИН бар, без грешка в партидата. На чист run (16.10, 19.10, 20.10) всичките 903 имат бар,
898 — история (5 нови листинга — структурно). Сега screener.LAST_STATUS носи with_bars / no_bars_n / no_bars и банерът е при no_bars_n ≥ config.PARTIAL_DATA_WARN_SHARE (1%) от универса.

РЕАЛНО: tests/fixtures/ohlc_SPY.csv, ohlc_AMD.csv, ohlc_TWLO.csv, ohlc_EXEL.csv (дневни барове от Yahoo). СИНТЕТИЧНО: подмененият yf.download и тикърите ZZZ1, ZZZ2 без данни.
Пускане: python test_screener_no_bars.py
"""
import sys, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import config
from src import screener, data_warnings as dw

FIX = ROOT / "tests" / "fixtures"
REAL = {t: pd.read_csv(FIX / f"ohlc_{t}.csv", index_col=0, parse_dates=True) for t in ("SPY", "AMD", "TWLO", "EXEL")}
IDX = REAL["SPY"].index


def fake_download(tickers, **kw):                                                            # СИНТЕТИЧНО: Yahoo, който мълчаливо не връща нищо за ZZZ1/ZZZ2
    if isinstance(tickers, str):
        return REAL[tickers]
    empty = pd.DataFrame(np.nan, index=IDX, columns=REAL["SPY"].columns)
    return pd.concat({t: REAL[t].reindex(IDX) if t in REAL else empty for t in tickers}, axis=1)


screener.yf = type("Y", (), {"download": staticmethod(fake_download)})
screener.time.sleep = lambda s: None
universe = ["AMD", "TWLO", "EXEL", "ZZZ1", "ZZZ2"]

print("── 1. тикърите без бар се броят отделно ──")
with contextlib.redirect_stdout(io.StringIO()):
    screener.technical_screen(universe)
st = screener.LAST_STATUS
assert st["kind"] == "ok" and st["universe"] == 5 and st["with_bars"] == 3 and st["no_bars_n"] == 2 and st["no_bars"] == ["ZZZ1", "ZZZ2"], st
assert st["with_history"] <= st["with_bars"]
print(f"  ✓ универс 5 · с бар {st['with_bars']} · с история {st['with_history']} · без бар {st['no_bars']} (партидата е без грешка)")

print()
print("── 2. банерът — над фона ──")
w = dw._partial_warnings(None, st, None, None, None, None, None, None, False)
assert [x["source"] for x in w] == ["screener"] and "за 2 от 5 тикъра Yahoo не върна нито един бар днес (ZZZ1, ZZZ2)" in w[0]["message"]
assert config.PARTIAL_DATA_WARN_SHARE == 0.01
print("  ✓ 2 от 5 без бар → банер с имената; нормата (0 от 903) и под 1% — без банер (test_silent_failures)")
print("\n✅ test_screener_no_bars: всичко мина")
