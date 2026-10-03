"""
Пакет 2 · т.2 (2026-10-03): Fed Net Liquidity — седмични нива към една и съща сряда, 4-седмична промяна, мъртва зона ±1%,
цвят със смяна след 2 поредни седмици; индикаторът е САМО информативен (не се брои), минимум видими за Offensive = 6 от 8.

РЕАЛНО: WALCL и WDTGAL (TGA "Wednesday level") и WTREGEN (TGA "Week average") за сряда 02.09–30.09.2026 и RRPONTSYD за
30.09 — от публичните страници на FRED (прочетени на 03.10.2026); петте брифа от tests/fixtures (08.06 → 02.10). РЕАЛНИТЕ
RRP стойности за другите сряди не са взети (дневната серия е едва ~$0–12 млрд) — те са СИНТЕТИЧНИ и са маркирани. Всичко
останало (граници на мъртвата зона, хистерезис, празнични сряди) е СИНТЕТИЧНО. Реплей върху 78-те реални снимки: виж commit-а.
Пускане: python test_net_liquidity.py
"""
import sys, pathlib, json, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import macro_layer as ml, thermometer as th

print("── РЕАЛНИ FRED числа: защо седмичната средна на TGA е грешна ──")
WALCL = [("2026-09-02", 6_737_204), ("2026-09-09", 6_740_619), ("2026-09-16", 6_746_548), ("2026-09-23", 6_747_704), ("2026-09-30", 6_743_031)]
WDTGAL = [("2026-09-02", 944_364), ("2026-09-09", 843_705), ("2026-09-16", 991_708), ("2026-09-23", 947_317), ("2026-09-30", 984_046)]
WTREGEN = [("2026-09-02", 967_935), ("2026-09-09", 883_335), ("2026-09-16", 877_028), ("2026-09-23", 977_084), ("2026-09-30", 948_674)]
RRP = [("2026-09-02", 0.9), ("2026-09-09", 0.6), ("2026-09-16", 0.4), ("2026-09-23", 0.8), ("2026-09-30", 11.539)]     # само 30.09 е реално; останалите СИНТЕТИЧНИ
pts = ml._wednesday_points(WALCL, WDTGAL, RRP)
assert [p["date"] for p in pts] == [d for d, _ in WALCL]
assert pts[-1] == {"date": "2026-09-30", "nl_bn": 5747.4, "walcl_bn": 6743.0, "tga_bn": 984.0, "rrp_bn": 11.5}
old_nl = 6743.031 - 11.539 - 948.674                                  # с WTREGEN (седмична средна)
assert round(old_nl - pts[-1]["nl_bn"], 1) == 35.4                   # артефактът на старата сметка за 30.09: 35 млрд
assert abs(984.046 - 948.674) > 30
diffs = [abs(w - a) / 1000 for (_, w), (_, a) in zip(WDTGAL, WTREGEN)]
assert max(diffs) > 100                                               # на 09.09 седмичната средна е 40 млрд над нивото в сряда; на 16.09 — 115 млрд под
print(f"  ✓ 30.09.2026: TGA в сряда $984.0 млрд срещу седмична средна $948.7 млрд → Net Liquidity ${pts[-1]['nl_bn']:,.1f} млрд срещу ${old_nl:,.1f} (разлика 35.4 млрд);")
print(f"    разликата между двете TGA серии достига {max(diffs):.0f} млрд в седмица — много повече от истинската седмична промяна")

print()
print("── СИНТЕТИЧНО: подравняване към сряда ──")
walcl = [("2026-06-10", 6_700_000), ("2026-06-17", 6_710_000), ("2026-06-24", 6_720_000)]
tga = [("2026-06-10", 900_000), ("2026-06-17", 910_000)]                          # 24.06: липсва TGA → седмицата се пропуска
rrp = [("2026-06-08", 5.0), ("2026-06-09", 6.0), ("2026-06-12", 7.0), ("2026-06-17", 8.0)]
p = ml._wednesday_points(walcl, tga, rrp)
assert [x["date"] for x in p] == ["2026-06-10", "2026-06-17"]
assert p[0]["rrp_bn"] == 6.0                                                    # 10.06 няма RRP → последният работен ден до 4 дни назад (09.06)
assert p[1]["rrp_bn"] == 8.0 and p[1]["nl_bn"] == round(6710 - 8.0 - 910.0, 1) == 5792.0
assert ml._wednesday_points(walcl, tga, [("2026-06-01", 5.0)]) == []            # RRP по-стар от 4 дни → седмицата се пропуска
assert ml._wednesday_points([], tga, rrp) == [] and ml._wednesday_points(walcl, [], rrp) == []
print("  ✓ RRP — от същия ден или последния работен ден до 4 дни назад; седмица без TGA или с твърде стар RRP се пропуска, не се приближава")

print()
print("── СИНТЕТИЧНО: мъртва зона и цвят с потвърждение ──")
def series(levels):
    return [{"date": f"w{i:02d}", "nl_bn": float(v), "walcl_bn": 0.0, "rrp_bn": 0.0, "tga_bn": 0.0} for i, v in enumerate(levels)]
BASE = 5000.0
# граници на мъртвата зона при 4 седмици назад (база 5000): +1.00% → жълто, +1.01% → зелено, -1.00% → жълто, -1.01% → червено
for last, want in ((5050.0, "yellow"), (5050.5, "green"), (4950.0, "yellow"), (4949.5, "red")):
    sig = ml.liquidity_signal(series([BASE] * 4 + [last]))
    assert sig["raw_color"] == want and sig["color"] == want, (last, sig["raw_color"])
assert ml.liquidity_signal(series([BASE] * 4 + [5050.0]))["trend"] == "flat"
assert ml.liquidity_signal(series([BASE] * 4 + [5100.0]))["trend"] == "up" and ml.liquidity_signal(series([BASE] * 4 + [4900.0]))["trend"] == "down"
assert ml.liquidity_signal(series([BASE] * 3))["hide"] is True                  # под 5 точки
print("  ✓ ±1.00% е в мъртвата зона (жълто), ±1.01% излиза от нея; под 5 седмични точки → скрит")

# хистерезис: 4-седмичната промяна се сменя ОТ седмица на седмица; тук задаваме суровите цветове директно през нивата
def colors(raw):
    return ml._confirmed_color(raw, 2)
assert colors(["yellow", "yellow", "green", "yellow", "yellow"]) == "yellow"                   # една зелена седмица не сменя цвета
assert colors(["yellow", "green", "green"]) == "green"                                         # две поредни → смяна
assert colors(["yellow", "green", "green", "red"]) == "green"                                  # една червена не сменя
assert colors(["yellow", "green", "green", "red", "red"]) == "red"
assert colors(["green", "red", "green", "red", "green"]) == "green"                            # люлеене без два поредни → остава първият
assert colors(["red"]) == "red"
# и през пълния път: нива, при които сурови цветове са [yellow, green, yellow, ...]
lv = [5000, 5000, 5000, 5000, 5000, 5100, 5000, 5000, 5000]                                    # 4-седмична промяна: 0, +2%, ... 
sig = ml.liquidity_signal(series(lv))
assert sig["raw_color"] in ("yellow", "green", "red") and sig["color"] in ("yellow", "green", "red")
up = ml.liquidity_signal(series([5000] * 4 + [5100, 5120]))                                    # две седмици +2%/+2.4% → зелено
assert (up["raw_color"], up["color"]) == ("green", "green")
one = ml.liquidity_signal(series([5000] * 4 + [5000, 5120]))                                   # само последната седмица е зелена → жълто
assert (one["raw_color"], one["color"]) == ("green", "yellow")
print("  ✓ нов цвят чак след 2 поредни седмици: една зелена седмица → остава жълто; две → зелено; люлеене → не сменя; пълният път го потвърждава")

print()
print("── индикаторът е информативен ──")
ind = th._net_liquidity_indicator(one)
assert ind["informational"] is True and ind["status"] == "yellow" and "само информативен" in ind["label"] and "седмицата е зелена" in ind["label"]
assert th._net_liquidity_indicator({"value": None})["hide"] is True
legacy = th._net_liquidity_indicator({"value": 5795.7, "trend": "down"})                       # формат от преди 03.10 (исторически брифове)
assert legacy["status"] == "red" and legacy["informational"] is True
print("  ✓ карта с 'само информативен'; празна → скрита; старият формат на macro се чете (за исторически брифове)")

print()
print("── броенето за режима без Net Liquidity (РЕАЛНИ брифове) ──")
def regime(d, min_visible, informational):
    t = json.loads((ROOT / f"tests/fixtures/brief_{d}.json").read_text(encoding="utf-8"))["thermometer"]
    ind = copy.deepcopy(t["indicators"])
    for i in ind:
        if informational and i["name"] == "Fed Net Liquidity":
            i["informational"] = True
    return th._count_regime(ind, min_visible=min_visible)
# 20.08.2026: 7 зелени, единственият червен е Net Liquidity ($5795.7 млрд) → досега Defensive
old, old_reason, _ = regime("2026-08-20", 7, False)
new, new_reason, new_counts = regime("2026-08-20", 6, True)
assert old == "Defensive" and "7 зелени / 0 жълти / 1 червени от 8 видими" in old_reason
assert new == "Offensive" and new_counts == "7 зелени / 0 жълти / 0 червени от 7 видими · не се броят: Fed Net Liquidity (информативен)", new_counts
print("  ✓ 20.08.2026 (РЕАЛНО): 7 зелени и само Net Liquidity червен → преди Defensive, сега Offensive:", new_counts)
# другите реални дни не се променят
for d, was, now in (("2026-06-29", "Defensive", "Defensive"), ("2026-09-08", "Defensive", "Defensive"),
                    ("2026-09-22", "Offensive", "Offensive"), ("2026-10-02", "Defensive", "Defensive")):
    assert regime(d, 7, False)[0] == was and regime(d, 6, True)[0] == now, d
r8, why8, _ = regime("2026-09-08", 6, True)
assert "видими 5 от 8, нужни ≥ 6" in why8                                                       # 08.09: 3 скрити от 8 броени → пак Defensive
print("  ✓ 29.06, 08.09, 22.09 и 02.10 — режимът по броене е същият; 08.09 остава Defensive ('видими 5 от 8, нужни ≥ 6')")

# граница 6 видими (СИНТЕТИЧНО върху реалните индикатори от 20.08 — тогава още няма IEI/HYG, броени са 7)
t = json.loads((ROOT / "tests/fixtures/brief_2026-08-20.json").read_text(encoding="utf-8"))["thermometer"]
def hide_n(n):
    ind = copy.deepcopy(t["indicators"])
    for i in ind:
        if i["name"] == "Fed Net Liquidity":
            i["informational"] = True
    k = 0
    for i in ind:
        if k < n and not i.get("informational"):
            i.update(hide=True, value=None); k += 1
    return th._count_regime(ind)
assert [hide_n(n)[0] for n in (0, 1, 2)] == ["Offensive", "Offensive", "Defensive"]          # 7 и 6 видими → Offensive, 5 → Defensive
assert "видими 5 от 7, нужни ≥ 6" in hide_n(2)[1]
assert config.THERMOMETER_MIN_VISIBLE_FOR_OFFENSIVE == 6
print("  ✓ СИНТЕТИЧНО: 7 броени, скрити 0–1 (7 и 6 видими, всички зелени) → Offensive; 2 скрити (5 видими) → Defensive 'видими 5 от 7, нужни ≥ 6'")
print()
print("── макро промптът ──")
from src import ai_brief
seen = {}
ai_brief._call_claude = lambda system, user, max_tokens=0: seen.setdefault("user", user) and json.dumps({"macro_brief": "x", "sector_logic": [], "regime_comment": "y"})
ai_brief.macro_and_sector_brief({"net_liquidity": one}, [], {"regime": "Defensive", "indicators": [ind]})
assert "Fed Net Liquidity: индикаторът е САМО информативен" in seen["user"] and "НЕ влиза в броенето за режима" in seen["user"]
print("  ✓ промптът казва, че Net Liquidity е само информативен и не е довод за режима")
print()
print("Всички тестове минаха.")
