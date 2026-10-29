"""
29.10.2026 · разходката, т. 2 (добавка, решена при т. 5): SOFR − IORB брои поредните ПО-ВИСОКИ (или по-ниски) отчета и го пише в информативния уред — „расте 4-ти пореден отчет“;
така и разказът (т. 5) го има във входовете (надписът на уреда е в контекста на промпта). Броят е от кода (macro_layer.report_streak), поредното число — thermometer._ordinal.
РЕАЛНО (брифовете): към 27.10 — −2, −2, 0, +2, +3, +5 б.п. (20.10 → 27.10) → расте 4-ти пореден отчет (примерът от разходката казваше „шести“ — по данните е четвърти).

РЕАЛНО: tests/fixtures/funding_stress_briefs_2026-10.json — macro.funding_stress от брифовете 16.10–29.10 (as_of, value) и записът от 29.10;
tests/fixtures/funding_sofr_iorb_2026-10-15.json — SOFR (NY Fed), IOER / IORB (Fed Board), до 14.10.2026.
СИНТЕТИЧНО (означено): кратките редици в т. 3.
Пускане: python test_funding_streak.py
"""
import sys, json, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import macro_layer as ml, thermometer as th

FX = json.loads((ROOT / "tests" / "fixtures" / "funding_stress_briefs_2026-10.json").read_text(encoding="utf-8"))
SER = FX["series"]

print("── 1. РЕАЛНАТА редица от брифовете: броят за всеки ден ──")
assert [r["as_of"] for r in SER] == ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"]
vals = [r["value"] for r in SER]
got = {SER[k]["as_of"]: ml.report_streak(vals[:k + 1]) for k in range(1, len(vals))}
assert got["2026-10-27"] == {"dir": "up", "n": 4} and got["2026-10-26"] == {"dir": "up", "n": 3} and got["2026-10-21"] == {"dir": "flat", "n": 0}
assert got["2026-10-19"] == {"dir": "down", "n": 2} and got["2026-10-22"] == {"dir": "up", "n": 1}
print("  ✓ 27.10: расте 4 поредни (−2 → −2 → 0 → +2 → +3 → +5); 21.10: без промяна; 19.10: пада 2 поредни")

print()
print("── 2. уредът: надписът носи броя (РЕАЛНИЯТ запис от 29.10 + броят от редицата) ──")
fs = {**FX["brief_2026_10_29"], "streak": got["2026-10-27"]}
ind = th._funding_stress_indicator(fs)
assert "+5.0 б.п. към 27.10 (SOFR 3.95% − IORB 3.90%) · +7.0 б.п. за седмица · расте 4-ти пореден отчет · 93. percentile" in ind["label"] and ind["streak"] == {"dir": "up", "n": 4}
one = th._funding_stress_indicator({**FX["brief_2026_10_29"], "streak": {"dir": "up", "n": 1}})
old = th._funding_stress_indicator(FX["brief_2026_10_29"])                                                    # запис отпреди 29.10 — без "streak"
assert "пореден" not in one["label"] and "пореден" not in old["label"] and "streak" not in old
print(f"  ✓ «…{ind['label'][40:130]}…»; един отчет или стар запис — без броя")

print()
print("── 3. funding_spread върху РЕАЛНИТЕ първоизточници до 14.10 връща и броя; кратки редици (СИНТЕТИЧНИ) ──")
S = json.loads((ROOT / "tests" / "fixtures" / "funding_sofr_iorb_2026-10-15.json").read_text(encoding="utf-8"))
out = ml.funding_spread(S["sofr"], S["ioer"], S["iorb"], dt.date(2026, 10, 16))
assert out["as_of"] == "2026-10-14" and out["value"] == -2.0 and out["streak"]["dir"] in ("up", "down", "flat")
assert ml.report_streak([1, 2, 3, 3]) == {"dir": "flat", "n": 0} and ml.report_streak([3, 2, 1]) == {"dir": "down", "n": 2} and ml.report_streak([5]) == {"dir": "flat", "n": 0}   # СИНТЕТИЧНО
assert [th._ordinal(n) for n in (2, 3, 4, 5, 11, 12, 21, 22)] == ["2-ри", "3-ти", "4-ти", "5-и", "11-и", "12-и", "21-ви", "22-ри"]
print(f"  ✓ 14.10: {out['streak']}; кратките редици и поредните числа")
print("\n✅ test_funding_streak: всичко мина")
