"""
16.10.2026 · нов ИНФОРМАТИВЕН индикатор "SOFR − IORB (финансиране)" (macro_layer.funding_spread / funding_stress, thermometer._funding_stress_indicator) — като Fed Net Liquidity:
показва се, не влиза в броенето; перцентил и z-score спрямо собствената история; "термометър, не предсказание" с числата от проучването; застояла / липсваща серия → "Скрити днес".

РЕАЛНО: tests/fixtures/funding_sofr_iorb_2026-10-15.json — SOFR (NY Fed, от 02.04.2018) и IOER / IORB (Fed Board, release PRATES) — първоизточниците, които FRED препубликува като SOFR,
IOER и IORB (самият FRED не се отвори оттук, API-то иска ключа от CI — виж бележката във fixture-а); tests/fixtures/brief_2026-10-15.json — термометърът и страницата като рамка.
СИНТЕТИЧНО (маркирано): датите "днес" за давността, отрязаните серии, подмененото теглене от FRED и _call_claude.
Пускане: python test_funding_stress.py
"""
import sys, json, pathlib, copy, re, io, contextlib, tempfile, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_fund_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import macro_layer as ml, thermometer as th, regime_claims as rc, render, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "funding_sofr_iorb_2026-10-15.json").read_text(encoding="utf-8"))
S = {k: [tuple(p) for p in FX[k]] for k in ("sofr", "ioer", "iorb")}
B15 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-15.json").read_text(encoding="utf-8"))
D = dt.date.fromisoformat

print("── 1. РЕАЛНИТЕ серии към 14.10.2026 ──")
r = ml.funding_spread(S["sofr"], S["ioer"], S["iorb"], D("2026-10-16"))
assert (r["value"], r["as_of"], r["sofr"], r["iorb"], r["percentile"], r["zscore"], r["status"], r["history_from"], r["n_history"]) == \
       (-2.0, "2026-10-14", 3.88, 3.9, 68.2, 0.22, "green", "2018-04-02", 2131), r
ind = th._funding_stress_indicator(r)
assert ind["informational"] and ind["label"].startswith("-2.0 б.п. към 14.10 (SOFR 3.88% − IORB 3.90%)") and "68. percentile, z +0.2 спрямо историята от 04.2018" in ind["label"]
assert "термометър, не предсказание: в проучването ни ранен сигнал само в 1 от 3 кризи (2007), 47–72% фалшиви сигнали" in ind["label"] and ind["label"].endswith("само информативен, не влиза в режима")
print("  ✓", ind["label"])

print()
print("── 2. история: септември 2019, преходът IOER → IORB ──")
cut = lambda last: [p for p in S["sofr"] if p[0] <= last]
r19 = ml.funding_spread(cut("2019-09-17"), S["ioer"], S["iorb"], D("2019-09-18"))
assert r19["value"] == 315.0 and r19["status"] == "red" and r19["percentile"] == 100.0
r21a, r21b = ml.funding_spread(cut("2021-07-28"), S["ioer"], S["iorb"], D("2021-07-29")), ml.funding_spread(cut("2021-07-30"), S["ioer"], S["iorb"], D("2021-08-02"))
assert r21a["iorb"] == dict(S["ioer"])["2021-07-28"] and r21b["iorb"] == dict(S["iorb"])["2021-07-30"]
print(f"  ✓ 17.09.2019 (репо кризата): +315 б.п., 100. перцентил, червен; 28.07.2021 — IOER, 30.07.2021 — IORB")

print()
print("── 3. скрит: застояла SOFR / липсващ IORB → 'Скрити днес' ──")
st = ml.funding_spread(S["sofr"], S["ioer"], S["iorb"], D("2026-10-21"))                     # СИНТЕТИЧНО: "днес" 21.10 при последна точка 14.10
assert st == {"value": None, "hide": True, "hide_reason": "SOFR застояла — последно наблюдение 14.10 (праг 2 сесии)"}
assert ml.funding_spread(S["sofr"], S["ioer"], [], D("2026-10-16"))["hide_reason"] == "FRED не върна IORB" and ml.funding_spread([], S["ioer"], S["iorb"])["hide_reason"] == "FRED не върна SOFR"
hid = th._funding_stress_indicator(st)
assert hid["hide"] and hid["informational"] and hid["hide_reason"].startswith("SOFR застояла") and th._funding_stress_indicator(None) is None
print("  ✓ 7 сесии без нова точка (СИНТЕТИЧНО 21.10) → скрит с причина; без IORB / без SOFR → скрит; изключен (None) → няма карта")

print()
print("── 4. не влиза в броенето ──")
inds = [i for i in B15["thermometer"]["indicators"]]
with_fs = inds[:5] + [ind] + inds[5:]
assert th._count_regime(with_fs)[0] == th._count_regime(inds)[0] == "Offensive"
assert th._count_regime(with_fs)[2].startswith("6 зелени / 2 жълти / 0 червени от 8 видими") and "не се броят: Fed Net Liquidity, SOFR − IORB (финансиране) (информативни)" in th._count_regime(with_fs)[2]
f = rc.facts({"indicators": with_fs})
assert f["groups"]["informational"] == ["Fed Net Liquidity", "SOFR − IORB (финансиране)"]
assert [p["code"] for p in rc.check("Днес 2 жълти (Put/Call, SOFR).", f)] == ["member"]                 # SOFR не е в никоя група
print("  ✓ режимът и броенето (РЕАЛНИЯТ термометър от 15.10) са същите; 'не се броят: … (информативни)'; SOFR сред жълтите → поправка от regime_claims")

print()
print("── 5. теглене от FRED (подменено с РЕАЛНИТЕ серии), промптът и страницата ──")
real, real_spread = ml._fred_series, ml.funding_spread
ml._fred_series = lambda sid, days=90: {"SOFR": S["sofr"], "IOER": S["ioer"], "IORB": S["iorb"]}[sid]
ml.funding_spread = lambda a, b, c, today=None: real_spread(a, b, c, today=D("2026-10-15"))     # 20.10.2026: денят е фиксиран (СИНТЕТИЧНО) — с днешната дата серията до 14.10 е "застояла" от 20.10 и тестът падаше
try:
    fs = ml.funding_stress()
finally:
    ml._fred_series, ml.funding_spread = real, real_spread
assert fs["value"] == -2.0 and fs["as_of"] == "2026-10-14"
prompts = []
ai_brief._call_claude = lambda system, user, **k: (prompts.append(user), json.dumps({"macro_brief": "x", "sector_logic": [], "regime_comment": "y"}))[1]
th15 = copy.deepcopy(B15["thermometer"]); th15["indicators"] = with_fs
with contextlib.redirect_stdout(io.StringIO()):
    ai_brief.macro_and_sector_brief({}, [], th15)
assert "ВАЖНО за SOFR − IORB" in prompts[0] and "не предсказание" in prompts[0] and "SOFR − IORB (финансиране)" in prompts[0]
b = copy.deepcopy(B15); b["thermometer"] = th15
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "SOFR − IORB (финансиране) -2.0 -2.0 б.п. към 14.10" in page
b2 = copy.deepcopy(B15); b2["thermometer"]["indicators"] = inds[:5] + [hid] + inds[5:]
p2 = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b2))))
assert "Скрити днес: SOFR − IORB (финансиране) — SOFR застояла — последно наблюдение 14.10 (праг 2 сесии) (информативен, не влиза в режима)" in p2
print("  ✓ funding_stress() върху РЕАЛНИТЕ серии; промптът — 'само информативен, не предсказание'; картата в термометъра; скрит → ред 'Скрити днес' с причината")
print("\n✅ test_funding_stress: всичко мина")
