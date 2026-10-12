"""
12.10.2026 · посоката на IEI/HYG RoC е от кода и стига до промпта за макро/секторите.

Случаят (РЕАЛЕН, брифът от 12.10): веригата за XLV казваше "IEI/HYG … с ускоряваща се RoC (84.3-ти percentile)", а кодът — "spike-ът отшумява". 10-дневната RoC на 09.10
е +0.41% срещу +1.03% преди 5 сесии (02.10; връх +1.17% на 01.10) — спада. Percentile-ът (84.3) е колко висока е RoC спрямо историята си, не дали расте.

РЕАЛНО: tests/fixtures/iei_hyg_2026-10-12.json — серията IEI/HYG до 09.10 (Yahoo, изтеглена на 12.10), индикаторът и веригата за XLV от брифа на 12.10.
СИНТЕТИЧНО (означено): подмененото извикване на модела (връща празен JSON и записва промпта).
Пускане: python test_credit_roc_trend.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
from src import thermometer, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "iei_hyg_2026-10-12.json").read_text(encoding="utf-8"))
ratio = pd.Series(FX["ratio"], index=pd.to_datetime(FX["dates"]))

print("── 1. същите числа като в брифа + посоката ──")
assert "ускоряваща се RoC" in FX["xlv_chain"]
r = thermometer._evaluate_credit_spread(ratio)
assert (r["roc_10d_pct"], r["roc_percentile"], r["level_percentile"]) == (FX["indicator"]["roc_10d_pct"], FX["indicator"]["roc_percentile"], FX["indicator"]["level_percentile"]) == (0.41, 84.3, 7.3)
assert r["roc_10d_pct_prev"] == 1.03 and r["roc_trend"] == "falling"
assert r["roc_trend_text"] == "10-дневната RoC е +0.41% срещу +1.03% преди 5 сесии — спада (забавя се)"
print("  ✓ РЕАЛНО 09.10:", r["roc_trend_text"], "(в брифа XLV: 'ускоряваща се RoC')")

print()
print("── 2. обратната посока (РЕАЛНАТА серия, отрязана към 01.10) ──")
r2 = thermometer._evaluate_credit_spread(ratio[ratio.index <= "2026-10-01"])
assert (r2["roc_10d_pct"], r2["roc_10d_pct_prev"], r2["roc_trend"]) == (1.17, -0.21, "rising")
assert r2["roc_trend_text"] == "10-дневната RoC е +1.17% срещу -0.21% преди 5 сесии — расте (ускорява се)"
print("  ✓ РЕАЛНО 01.10:", r2["roc_trend_text"])
print()
print("── 3. бележката стига до промпта ──")
th = {"regime": "Defensive", "indicators": [{**FX["indicator"], **{k: r[k] for k in ("roc_10d_pct_prev", "roc_trend", "roc_trend_text")}}]}
note = ai_brief._credit_roc_note(th)
assert "посоката на RoC е от кода — 10-дневната RoC е +0.41% срещу +1.03% преди 5 сесии — спада (забавя се)" in note and "не дали расте" in note
assert ai_brief._credit_roc_note({"indicators": [FX["indicator"]]}) == ""                          # стар индикатор без полето — без бележка
seen = {}


def fake_claude(system, user, **k):                                       # СИНТЕТИЧНО: записва промпта, връща празен отговор
    seen["user"] = user
    return '{"macro_brief": "", "sector_logic": [], "regime_comment": ""}'


ai_brief._call_claude = fake_claude
ai_brief._macro_and_sector_brief_ai({}, [], th, news=[])
assert note in seen["user"]
print("  ✓", note.strip()[:140] + "…")
print()
print("Всички тестове минаха.")
