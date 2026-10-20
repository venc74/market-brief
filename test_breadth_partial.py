"""
20.10.2026 · етап 3б (обвивката, стъпка 1): Market Breadth губеше тикъри без банер — партида с грешка или тикър без данни просто намаляваха универса на процента. Нормалният фон
(universe_size в 48 реални брифа): 900–903 от 903, т.е. липсват 0–3; при ограничение от Yahoo (пробното пускане на 20.10) — 12. Сега индикаторът носи universe_total / missing_n /
batches / batches_failed и data_warnings дава банер при паднала партида или missing_n ≥ config.PARTIAL_DATA_WARN_SHARE (1%) от универса.

РЕАЛНО: tests/fixtures/ohlc_{AMD,TWLO,EXEL,LNTH,SPY}.csv (дневни барове от Yahoo); breadth индикаторът от tests/fixtures/brief_2026-10-19.json (902 от 903, стар формат).
СИНТЕТИЧНО (означено): подмененият yf.download и универсът, тикърът ZZZ1 без данни, падналата партида, BREADTH_MIN_VALID_TICKERS = 1.
Пускане: python test_breadth_partial.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import config
from src import thermometer as th, data_warnings as dw

FIX = ROOT / "tests" / "fixtures"
REAL = {t: pd.read_csv(FIX / f"ohlc_{t}.csv", index_col=0, parse_dates=True) for t in ("AMD", "TWLO", "EXEL", "LNTH", "SPY")}
IDX = REAL["SPY"].index
UNIV = ["AMD", "TWLO", "EXEL", "LNTH", "SPY", "ZZZ1"]
FAIL_BATCH = [False]


def fake_download(batch, **kw):                                                            # СИНТЕТИЧНО
    if FAIL_BATCH[0] and "LNTH" in batch:
        raise RuntimeError("YFRateLimitError (СИНТЕТИЧНО)")
    empty = pd.DataFrame(np.nan, index=IDX, columns=REAL["SPY"].columns)
    return pd.concat({t: REAL[t] if t in REAL else empty for t in batch}, axis=1)


th.yf = type("Y", (), {"download": staticmethod(fake_download)})
th.build_universe = lambda: list(UNIV)
th.time.sleep = lambda s: None
config.BREADTH_MIN_VALID_TICKERS = 1
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. тикър без данни ──")
with q():
    b = th.market_breadth()
assert (b["universe_total"], b["universe_size"], b["missing_n"], b["batches_failed"]) == (6, 5, 1, 0), b
w = dw._breadth_warning(b)
assert [x["source"] for x in w] == ["breadth"] and "изчислен върху 5 от 6 тикъра (Yahoo не върна данни без грешка в партидата; нормално липсват 0–3)" in w[0]["message"]
print(f"  ✓ 5 от 6 → банер: «{w[0]['message'][:90]}…»")

print()
print("── 2. паднала партида ──")
FAIL_BATCH[0], config.BREADTH_BATCH_SIZE = True, 3
with q():
    b2 = th.market_breadth()
assert b2["batches"] == 2 and b2["batches_failed"] == 1 and b2["universe_size"] == 3
assert "1 от 2 партиди не се изтеглиха" in dw._breadth_warning(b2)[0]["message"]
print("  ✓ 1 от 2 партиди → банер")

print()
print("── 3. нормата и старият формат (РЕАЛНО) ──")
assert dw._breadth_warning({**b, "universe_total": 903, "universe_size": 900, "missing_n": 3}) == []          # фонът (900 от 903) — без банер
assert dw._breadth_warning({**b, "universe_total": 903, "universe_size": 891, "missing_n": 12})                  # пробното пускане (12) — банер
B19 = json.loads((FIX / "brief_2026-10-19.json").read_text(encoding="utf-8"))
br19 = next(i for i in B19["thermometer"]["indicators"] if i["name"].startswith("Market Breadth"))
assert br19["universe_size"] == 902 and dw._breadth_warning(br19) == [] and dw._breadth_warning({"hide": True}) == []
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'breadth=next((i for i in thermo.get("indicators")' in src
print("  ✓ 3 липсващи от 903 — без банер; 12 — банер; брифът от 19.10 (стар формат, 902) и скрит индикатор — без банер; main подава индикатора")
print("\n✅ test_breadth_partial: всичко мина")
