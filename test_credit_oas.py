"""
03.11.2026 · прегледът на 02.11, т. 4: информативна плочка в термометъра (не влиза в броенето) — HY OAS (FRED BAMLH0A0HYM2) и IG OAS (BAMLC0A0CM): ниво, промяна за 20 наблюдения,
перцентил за наличната история (FRED дава ICE сериите само за ~3 години). Изречение от кода спрямо IEI/HYG: IEI/HYG жълт/червен, а HY OAS спокоен → „натискът е от лихвите, не от
кредита“; и двата се разширяват → „кредитен стрес“. Застояли / липсващи данни → скрита карта с причината (етикет, не тишина). Тегли се през съществуващия FRED клиент
(macro_layer._fred_series — с ключа, с обработката на грешки).

РЕАЛНО: tests/fixtures/fred_oas_2026-11-03.json — двете серии от FRED, свалени на 03.11.2026 (последно наблюдение 30.10.2026); tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): подмененият _fred_series (връща РЕАЛНИТЕ наблюдения), статусите на IEI/HYG в т. 3, датата „днес“ за застоялите данни, късата история.
Пускане: python test_credit_oas.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_oas_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import macro_layer as ml, thermometer as th, render

FX = json.loads((ROOT / "tests" / "fixtures" / "fred_oas_2026-11-03.json").read_text(encoding="utf-8"))["series"]
HY, IG = [tuple(x) for x in FX["BAMLH0A0HYM2"]["obs"]], [tuple(x) for x in FX["BAMLC0A0CM"]["obs"]]
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
TODAY = dt.date(2026, 11, 3)
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. oas_reading — РЕАЛНИТЕ серии на FRED ──")
hy, ig = ml.oas_reading(HY, TODAY), ml.oas_reading(IG, TODAY)
assert (hy["value"], hy["as_of"], hy["chg_bp"], hy["percentile"], hy["history_from"]) == (3.44, "2026-10-30", 34, 87.9, "2023-11-03"), hy
assert (ig["value"], ig["chg_bp"], ig["percentile"]) == (0.94, 9, 77.1), ig
assert HY[-21] == ("2026-10-02", 3.1)                                                                            # 20 наблюдения назад
stale = ml.oas_reading(HY, dt.date(2026, 11, 6))                                                                 # СИНТЕТИЧНО: „днес“ = 06.11 — 4 сесии след 30.10
assert stale["hide"] and stale["hide_reason"] == "застояла — последно наблюдение 30.10 (праг 2 сесии)"
assert ml.oas_reading([], TODAY)["hide_reason"] == "FRED не върна данни" and ml.oas_reading(HY[-10:], TODAY)["hide_reason"] == "историята е твърде къса (10 наблюдения)"
print(f"  ✓ HY {hy['value']}% към 30.10, {hy['chg_bp']:+d} б.п. за 20 дни, {hy['percentile']}. percentile от 03.11.2023 · IG {ig['value']}% ({ig['chg_bp']:+d} б.п., {ig['percentile']}.) · застояла / празна / къса → скрита с причина")

print()
print("── 2. credit_oas — през съществуващия FRED клиент (СИНТЕТИЧНО: _fred_series връща РЕАЛНИТЕ наблюдения) ──")
asked = []
ml._fred_series = lambda sid, days=90: (asked.append((sid, days)), {"BAMLH0A0HYM2": HY, "BAMLC0A0CM": IG}[sid])[1]
real_today = ml.dt.date
class _D(dt.date):
    @classmethod
    def today(cls):
        return TODAY
ml.dt.date = _D
try:
    oas = ml.credit_oas()
finally:
    ml.dt.date = real_today
assert asked == [("BAMLH0A0HYM2", config.CREDIT_OAS_HISTORY_DAYS), ("BAMLC0A0CM", config.CREDIT_OAS_HISTORY_DAYS)]
assert {k: (v["value"], v["series"]) for k, v in oas.items()} == {"hy": (3.44, "BAMLH0A0HYM2"), "ig": (0.94, "BAMLC0A0CM")}
ml._fred_series = lambda sid, days=90: []                                                                        # СИНТЕТИЧНО: без ключ / FRED не отговори
assert ml.credit_oas()["hy"]["hide_reason"] == "FRED не върна данни"
print("  ✓ двете серии с ~3 г. история; без отговор → скрити с причина")

print()
print("── 3. изречението спрямо IEI/HYG и цветът (СИНТЕТИЧНО: статусите на IEI/HYG) ──")
iei = lambda st: {"name": "IEI/HYG (Credit Spread)", "value": 1.489, "status": st}
calm = next(ml.oas_reading(HY[:n], dt.date.fromisoformat(HY[n - 1][0])) for n in range(len(HY), 30, -1)
            if ml.oas_reading(HY[:n], dt.date.fromisoformat(HY[n - 1][0]))["chg_bp"] < config.CREDIT_OAS_WIDENING_BP)          # РЕАЛНО: последният ден със спокоен HY
assert th.credit_oas_verdict(hy, iei("green")) == "HY OAS се разширява, IEI/HYG още не"                                            # днес (РЕАЛНО)
assert th.credit_oas_verdict(hy, iei("red")) == "кредитен стрес — и IEI/HYG, и HY OAS се разширяват"
assert th.credit_oas_verdict(calm, iei("yellow")) == "натискът е от лихвите, не от кредита (IEI/HYG е жълт/червен, HY OAS е спокоен)"
assert th.credit_oas_verdict(calm, iei("green")) == "кредитът е спокоен (IEI/HYG зелен, HY OAS не се разширява)"
assert th.credit_oas_verdict(hy, {"name": "IEI/HYG (Credit Spread)", "value": None, "status": "yellow", "hide": True}) is None
tile = th._credit_oas_indicator({"hy": hy, "ig": ig}, iei("green"))
assert tile["status"] == "red" and tile["informational"] and tile["label"] == (
    "HY 3.44% (+34 б.п. за 20 дни, 88. percentile) · IG 0.94% (+9 б.п. за 20 дни, 77. percentile) · към 30.10, перцентил спрямо историята от 03.11.2023 (FRED дава ~3 г.) · "
    "HY OAS се разширява, IEI/HYG още не · само информативен, не влиза в режима"), tile["label"]
hidden = th._credit_oas_indicator({"hy": stale, "ig": ig}, iei("green"))
assert hidden["hide"] and hidden["hide_reason"] == "HY OAS — застояла — последно наблюдение 30.10 (праг 2 сесии)"
assert th._credit_oas_indicator(None, iei("green")) is None
print(f"  ✓ днес: „{tile['verdict']}“ (червено — +34 б.п. и 88. percentile); спокоен HY ({calm['as_of']}, {calm['chg_bp']:+d} б.п.) + жълт IEI/HYG → „натискът е от лихвите …“")

print()
print("── 4. не влиза в броенето; страницата (РЕАЛНИЯТ бриф от 19.10 като рамка) ──")
base = [i for i in B19["thermometer"]["indicators"] if not i.get("informational")]
before, after = th._count_regime(base), th._count_regime(base + [tile])
assert before[0] == after[0] and after[2].startswith(before[2]) and "HY / IG OAS (кредитни спредове)" in after[2]
b = copy.deepcopy(B19); b["thermometer"]["indicators"] = B19["thermometer"]["indicators"] + [tile, {**hidden, "name": "HY / IG OAS (кредитни спредове) "}]
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "HY 3.44% (+34 б.п. за 20 дни, 88. percentile)" in page and "HY OAS се разширява, IEI/HYG още не" in page
assert "HY OAS — застояла — последно наблюдение 30.10 (праг 2 сесии) (информативен, не влиза в режима)" in page
src = (ROOT / "src" / "macro_layer.py").read_text(encoding="utf-8")
assert '"credit_oas": credit_oas() if config.ENABLE_CREDIT_OAS else None' in src
print(f"  ✓ режимът по броенето не се мени ({after[0]}); „не се броят: … HY / IG OAS“; плочката и скритата причина са на страницата")
print("\n✅ test_credit_oas: всичко мина")
