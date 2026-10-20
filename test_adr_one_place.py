"""
20.10.2026 · етап 3, част Б: ADR на едно място (src/trade_levels: ADR_BARS, adr_window, adr_rolling, adr_pct). До 20.10 формулата беше написана три пъти — trade_levels,
qm_breakout (rolling за всеки бар) и qm_ep (прозорец към сесията). Числовият метод на всяко място е запазен — офлайн реплеят върху 34 реални серии от fixture-ите
(qm_frames_2026-10-02, glb_seed_2026-10-07, ohlc_*, ohlc_EXPD_SPY_raw): 0 разлики.

РЕАЛНО: tests/fixtures/qm_frames_2026-10-02.json (дневни барове на DOCN, CORT, CRL …).
Пускане: python test_adr_one_place.py
"""
import sys, re, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from src import trade_levels, qm_breakout, qm_ep

FX = json.loads((ROOT / "tests/fixtures/qm_frames_2026-10-02.json").read_text(encoding="utf-8"))["frames"]
df = pd.DataFrame({"Open": FX["DOCN"]["o"], "High": FX["DOCN"]["h"], "Low": FX["DOCN"]["l"], "Close": FX["DOCN"]["c"], "Volume": FX["DOCN"]["v"]},
                  index=pd.to_datetime(FX["DOCN"]["dates"]))

print("── 1. трите пътя дават едно и също (РЕАЛНИ барове на DOCN) ──")
f = qm_breakout.compute_features(df)
last = trade_levels.adr_pct(df["High"], df["Low"])
assert round(float(f["adr"][-1]), 2) == last
e = qm_ep.enrich_gappers([{"ticker": "DOCN", "session": df.index[-1].date().isoformat(), "ah_price": float(df["Close"].iloc[-1]) * 1.12}], {"DOCN": df})[0]
assert round(e["adr"], 2) == last and e["adr"] == trade_levels.adr_window(df["High"].iloc[-20:], df["Low"].iloc[-20:])
old = float(100 * (np.mean(df["High"].to_numpy()[-20:] / df["Low"].to_numpy()[-20:]) - 1))
assert e["adr"] == old                                                                                                # бит по бит като до 20.10
print(f"  ✓ DOCN към {df.index[-1].date()}: ADR {last}% — qm_breakout, qm_ep и trade_levels дават едно и също")

print()
print("── 2. пазач: формулата не е написана отново извън trade_levels ──")
bad = []
for p in sorted((ROOT / "src").glob("*.py")):
    if p.name == "trade_levels.py":
        continue
    for i, l in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"rolling\(20\)\.mean\(\)\s*-\s*1|h\[i\s*-\s*19\s*:|\(hs\s*/\s*ls\)", l) and not l.strip().startswith("#"):
            bad.append(f"{p.name}:{i}")
assert not bad, bad
print("  ✓ няма ADR формула (20 бара) извън src/trade_levels.py; стягането на QM (диапазон за 5 бара) е друга мярка")
print("\n✅ test_adr_one_place: всичко мина")
