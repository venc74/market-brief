"""
Пакет 2 · т.5 (2026-10-03): доходностите (^TNX = US10Y) се движат в БАЗИСНИ ПУНКТОВЕ — `chg_5d_bp = (last − wk) × 100`, без
относителен % (`chg_5d_pct`) за доходност; макро промптът казва "б.п." като при MOVE "пункта"; 2s10s носи `change_1w_bp`.
В global_signals няма 2Y (има само ^TNX) — 2Y присъства единствено като спреда T10Y2Y от FRED.

РЕАЛНО: дневни Close на 7-те тикъра от tests/fixtures/yahoo_closes_2026-10-02.json (Yahoo, свалени 03.10.2026, до 02.10);
стойностите на 02.10 бриф (tests/fixtures/brief_2026-10-02.json) — със среза "до 01.10" фикстурата дава ТОЧНО записаните
VIX 16.39/+4.59%, US10Y 5.24/+1.45% и MOVE 108.13/+3.39% (DXY/злато/петрол/мед в брифа са с вътредневен бар и не се връзват —
те не се проверяват срещу брифа, а само не се променят от т.5). СИНТЕТИЧНО: подмененият yfinance/FRED, спредовете 0.20→0.46.
Пускане: python test_yield_bp.py
"""
import sys, pathlib, json
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import macro_layer as ml, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "yahoo_closes_2026-10-02.json").read_text(encoding="utf-8"))["series"]
BRIEF = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-02.json").read_text(encoding="utf-8"))["macro"]
BY_SYMBOL = {d["symbol"]: d["closes"] for d in FX.values()}


class _T:
    def __init__(self, symbol, upto):
        self.s = pd.Series({pd.Timestamp(k): v for k, v in BY_SYMBOL[symbol].items() if k <= upto}, dtype=float)

    def history(self, period="1mo"):
        return pd.DataFrame({"Close": self.s})


def run(upto):
    ml.yf.Ticker = lambda sym: _T(sym, upto)
    ml._is_stale = lambda *a, **k: False                      # фикстурата е стара (бар 01.10) — свежестта е друг тест
    return ml.global_market_signals()


print("── РЕАЛНИ данни до 01.10 (последният бар, който 02.10 брифът е видял) ──")
g = run("2026-10-01")
rec = BRIEF["global_signals"]
assert g["US10Y"] == {"value": 5.24, "chg_5d_bp": 7.5}, g["US10Y"]
assert "chg_5d_pct" not in g["US10Y"]                                       # без относителен % за доходност
assert rec["US10Y"] == {"value": 5.24, "chg_5d_pct": 1.45}                  # стария запис: същото движение като +1.45% (= 7.5 б.п.)
assert g["VIX"] == rec["VIX"] and g["MOVE"] == rec["MOVE"]                  # РЕАЛНО: непроменени и съвпадат с брифа
for n in ("DXY", "Gold", "Oil_WTI", "Copper", "VIX", "MOVE"):
    assert set(g[n]) == {"value", "chg_5d_pct"}, n                           # само доходността е сменена
print("  ✓ US10Y: 5.24 → {'value': 5.24, 'chg_5d_bp': 7.5}  (стария формат: chg_5d_pct 1.45, същото движение)")
print("  ✓ VIX 16.39/+4.59% и MOVE 108.13/+3.39% са идентични със записаните в брифа от 02.10; DXY/злато/петрол/мед още са в %")

g2 = run("2026-10-02")
assert g2["US10Y"] == {"value": 5.28, "chg_5d_bp": 9.3}, g2["US10Y"]        # 5.277 − 5.184 (пет бара назад = 25.09)
print("  ✓ до 02.10: US10Y 5.28, +9.3 б.п. (5.277 − 5.184 = 0.093)")
print()

print("── СИНТЕТИЧНО: знак, малки и големи стойности ──")
def one(closes):
    base = pd.Timestamp("2026-09-01")
    s = pd.Series(closes, index=pd.bdate_range(base, periods=len(closes)), dtype=float)
    ml.yf.Ticker = lambda sym: type("H", (), {"history": lambda self, period="1mo": pd.DataFrame({"Close": s})})()
    ml._is_stale = lambda *a, **k: False
    return ml.global_market_signals()["US10Y"]
assert one([4.00] * 5 + [4.00, 4.00, 4.00, 4.00, 4.00, 3.90])["chg_5d_bp"] == -10.0
assert one([4.00] * 5 + [4.00, 4.00, 4.00, 4.00, 4.00, 4.00])["chg_5d_bp"] == 0.0
assert one([0.10] * 6 + [0.10] * 4 + [0.15])["chg_5d_bp"] == 5.0           # ниска база: относителният % би бил +50%
print("  ✓ −10.0 б.п., 0.0 б.п.; при ниска база (0.10 → 0.15) са 5.0 б.п., а относителният % би бил +50% — затова няма %")
print()

print("── спредът 2s10s и промптът ──")
ml._fred_series = lambda sid, days=30: [("2026-09-%02d" % d, 0.31) for d in range(1, 6)] + [("2026-09-30", 0.46)]
sp = ml.treasury_spread_2s10s()
assert sp["value"] == 0.46 and sp["prev_week"] == 0.31 and sp["change_1w_bp"] == 15.0
assert (BRIEF["spread_2s10s"]["value"], BRIEF["spread_2s10s"]["prev_week"]) == (0.46, 0.31)       # РЕАЛНИТЕ числа от брифа 02.10
print("  ✓ T10Y2Y 0.46 срещу 0.31 (реалните от 02.10; серията е СИНТЕТИЧНА) → change_1w_bp +15.0")

seen = {}
ai_brief._call_claude = lambda system, user, max_tokens=0: (seen.setdefault("u", user), json.dumps({"macro_brief": "x", "sector_logic": [], "regime_comment": "y"}))[1]
ai_brief.macro_and_sector_brief({"global_signals": g, "spread_2s10s": sp}, [], {"regime": "Defensive", "indicators": []})
u = seen["u"]
assert '"chg_5d_bp": 7.5' in u and '"change_1w_bp": 15.0' in u
assert "ВАЖНО за доходностите" in u and "БАЗИСНИ ПУНКТОВЕ" in u and "никога \"%\"" in u
assert "ВАЖНО за единиците на MOVE" in u                                      # съществуващото правило е непокътнато
print("  ✓ промптът носи chg_5d_bp/change_1w_bp и правилото 'б.п., никога %'; правилото за MOVE е непроменено")
print()
print("Всички тестове минаха.")
