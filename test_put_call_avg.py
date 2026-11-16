"""
16.11.2026 (пакет 16.11, т. 17 — решение на Венци): Put/Call — цветът и броенето в режима по 3-дневното средно (percentile спрямо историята на същото средно); суровата стойност
остава видима до него („P/C 0.89 днес · 3-дн. средно 1.05 …“); изречението от кода — по средното. Реално 16.11: 0.89 (7. percentile, червено) след 1.13 (49-и) — една сесия
обърна плочката и режимът стана Defensive; по средното — 1.05, 26-и, жълто.

РЕАЛНО: tests/fixtures/put_call_history_2026-11-16.json — data/put_call_history.json към 16.11 (109 стойности, 13.06–16.11). СИНТЕТИЧНО (означено): т. 3 — къса история.
Пускане: python test_put_call_avg.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import thermometer as th

H = json.loads((ROOT / "tests" / "fixtures" / "put_call_history_2026-11-16.json").read_text(encoding="utf-8"))["history"]
K = sorted(H)
assert K[-1] == "2026-11-16" and H["2026-11-16"] == 0.8941 or round(H["2026-11-16"], 2) == 0.89

print("── 1. РЕАЛНО: 16.11 — по средното жълто, суровата стойност видима ──")
r = th._evaluate_put_call_avg(H["2026-11-16"], [H[k] for k in K[:-1]])
assert (r["value"], r["raw"], r["avg_days"], round(r["percentile"]), r["status"]) == (1.05, 0.89, 3, 26, "yellow"), r
assert r["label"].startswith("P/C 0.89 днес · 3-дн. средно 1.05 (26. percentile на средното от 106 дни; в нормалния диапазон) — цветът е по средното")
raw = th._evaluate_put_call(H["2026-11-16"], [H[k] for k in K[:-1]])
assert raw["status"] == "red" and round(raw["percentile"]) == 7                                # суровото — червено (каквото беше в брифа)
S = th.put_call_sentence(r)
assert S == "Put/Call (SPY) 3-дн. средно 1.05 (днес 0.89) — 26. percentile от 106 дни: в нормалния диапазон за собствената история (жълто).", S
print(f"  ✓ {r['label']}")
print(f"  ✓ {S}")

print("── 2. РЕАЛНО: смените на цвета 14.08–16.11 ──")
def colors(fn):
    out = []
    for i, k in enumerate(K):
        if k < "2026-08-14":
            continue
        x = fn(H[k], [H[j] for j in K[:i]])
        out.append(x.get("status") if not x.get("hide") else None)
    return out
c_raw, c_avg = colors(th._evaluate_put_call), colors(th._evaluate_put_call_avg)
flips = lambda c: sum(1 for a, b in zip(c, c[1:]) if a != b)
assert len(c_raw) == 67 and flips(c_raw) == 17 and c_raw.count("red") == 3
assert flips(c_avg) <= 9 and c_avg.count("red") == 0
print(f"  ✓ 67 дни: смени на цвета {flips(c_raw)} → {flips(c_avg)}; червени дни {c_raw.count('red')} → {c_avg.count('red')}")

print("── 3. СИНТЕТИЧНО: къса история — скрит; brief.market_put_call ползва средното ──")
assert th._evaluate_put_call_avg(1.0, [1.0] * 10)["hide"]
src = (ROOT / "src" / "thermometer.py").read_text(encoding="utf-8")
assert "out = _evaluate_put_call_avg(pc, list(hist[k] for k in sorted(hist)))" in src
print("  ✓ под 30 дни история — скрит; market_put_call — по средното")
print("\n✅ test_put_call_avg: всичко мина")
