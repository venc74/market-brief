"""
Breadth <10% · текстът (09.10.2026, решение по проучването на Eric Wish). Преди: "extreme капитулация — исторически bottoming зона, contrarian bullish". Сега: "oversold, вероятен отскок — не е сигнал за дъно" + измерената
цифра. Wish ползва T2108 <10% като oversold флаг; входът му е GMI (изостава). Статусът (red в броенето) НЕ се променя — само текстът.

РЕАЛНО: tests/fixtures/breadth_spy_2006-2026-10-07.csv — собственият breadth (% над 40dMA върху днешния универс на S&P500 + NDX100 + MidCap400, с оцеляване) и затварянето на SPY за 5184 общи сесии 2006-03-01 → 2026-10-07;
тестът ПРЕИЗЧИСЛЯВА 17 епизода и 8-те с ≥5% по-ниско затваряне — числото в config.BREADTH_OVERSOLD_STATS не е вписано на доверие. СИНТЕТИЧНО (маркирано): подменените market_breadth() входове.
Пускане: python test_breadth_oversold_text.py
"""
import sys, pathlib, types
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import thermometer as th

df = pd.read_csv(ROOT / "tests" / "fixtures" / "breadth_spy_2006-2026-10-07.csv", index_col=0, parse_dates=True)
assert len(df) == 5184 and df.index[0].date().isoformat() == "2006-03-01" and df.index[-1].date().isoformat() == "2026-10-07"

print("── 1. числото е преизчислено от РЕАЛНИТЕ серии ──")
b, spy = df["breadth"], df["spy_close"]
low = b[b < config.BREADTH_CAPITULATION_THRESHOLD]
eps, start, last = [], None, None
for d in low.index:
    if last is None or (b.index.get_loc(d) - b.index.get_loc(last)) > 20:
        if start is not None:
            eps.append(start)
        start = d
    last = d
eps.append(start)
n = config.BREADTH_OVERSOLD_STATS["sessions"]
worst = []
for a in eps:
    pos = spy.index.get_loc(a)
    w = spy.iloc[pos + 1: pos + 1 + n]
    worst.append(float(w.min() / spy.iloc[pos] - 1) * 100)
got = {"episodes": len(eps), "lower_5pct": sum(1 for x in worst if x <= -5), "lower_any": sum(1 for x in worst if x < 0), "sessions": n}
assert got == config.BREADTH_OVERSOLD_STATS == {"episodes": 17, "lower_5pct": 8, "lower_any": 16, "sessions": 63}, got
print(f"  ✓ {got['episodes']} епизода (първи ден под 10%, пауза > 20 сесии); в следващите {n} сесии SPY затваря поне 5% по-ниско в {got['lower_5pct']}, изобщо по-ниско в {got['lower_any']}")

print()
print("── 2. текстът на индикатора ──")
th.build_universe = lambda: ["AAA"] * 300
th.time = types.SimpleNamespace(sleep=lambda s: None)


def with_pct(pct):
    """СИНТЕТИЧЕН универс от 400 тикъра, от които pct% са над SMA40 (последното затваряне над/под средната на 40 дни)."""
    n_total = 400
    above = int(round(pct / 100 * n_total))
    th.build_universe = lambda: [f"T{i}" for i in range(n_total)]
    cols = {(f"T{i}", "Close"): pd.Series([10.0] * 40 + [11.0 if i < above else 9.0]) for i in range(n_total)}
    data = pd.DataFrame(cols)
    data.columns = pd.MultiIndex.from_tuples(data.columns)
    th.yf = types.SimpleNamespace(download=lambda batch, **kw: data[[c for c in data.columns if c[0] in batch]])
    return th.market_breadth()


r = with_pct(5)
assert r["status"] == "red" and r["value"] < 10
st = config.BREADTH_OVERSOLD_STATS
assert "oversold, вероятен отскок — не е сигнал за дъно" in r["label"] and f"в {st['lower_5pct']} от {st['episodes']} исторически епизода" in r["label"] and "поне 5% по-ниско" in r["label"]
assert "bottoming" not in r["label"] and "contrarian bullish" not in r["label"] and "капитулация" not in r["label"]
print("  ✓ <10%: статус 'red' (в броенето, както преди), етикетът: «" + r["label"] + "»")
r2 = with_pct(15)
assert r2["status"] == "yellow" and "приближава капитулация" in r2["label"] and "oversold" not in r2["label"]
r3 = with_pct(50)
assert r3["status"] == "green" and "здравословна ширина" in r3["label"]
print("  ✓ 15% и 50% — непроменени: «приближава капитулация» (жълто), «здравословна ширина» (зелено)")
print("\n✅ test_breadth_oversold_text: всичко мина")
