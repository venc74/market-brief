"""
17.11.2026 (пакет 3 — решения след реплея): ЕДНО пазарно правило за всички стратегии (CANSLIM, Kullamägi, GLB). Нови входове (Offensive) само когато: SPY е над растяща
50DMA; няма активен override (VIX > 30, MOVE, IEI/HYG — само при кредитен натиск: HYG за 10 дни ≤ −1% или 20-дневната промяна на HY OAS ≥ 75-и перцентил);
distribution days не са червени. Несиметричен престой: към Defensive / Cash — веднага; към Offensive — след 2 поредни брифа с изпълнени условия („ден 1 от 2“).
Плочката — ред с условията (✓ / ✗), без „X зелени / Y жълти“ като основание. 2Y/10Y и Put/Call — информативни.

РЕАЛНО: tests/fixtures/thermo_2026-11-17.json — термометърът и distribution days от брифа на 17.11 (SPY 739.95 под 50DMA 763.52; HYG −0.21% за 10 дни; HY OAS —
44-и перцентил на промяната към 13.11; DD 9 = червени); brief_2026-10-19.json — рамката. СИНТЕТИЧНО (означено): т. 3 — последователностите за престоя; т. 4 — без HY OAS.
Пускане: python test_market_rule.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_rule_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import thermometer as th, render, backtest

FX = json.loads((ROOT / "tests" / "fixtures" / "thermo_2026-11-17.json").read_text(encoding="utf-8"))
T17 = FX["thermometer"]
IND = {i["name"]: i for i in T17["indicators"]}

print("── 1. РЕАЛНО: кредитният натиск на 17.11 ──")
cp = th.credit_pressure(IND["IEI/HYG (Credit Spread)"], IND["HY / IG OAS (кредитни спредове)"])
assert cp["active"] is False and cp["hyg_10d_pct"] == -0.21 and cp["oas_chg_pct"] == 44.2
assert cp["text"] == "HYG за 10 дни -0.2% (праг -1%); HY OAS — 44-и перцентил на 20-дневната промяна (праг 75-и)"
print(f"  ✓ {cp['text']} → няма натиск")

print("── 2. РЕАЛНО: правилото върху 17.11 — Defensive, с причините ──")
t = th.apply_market_rule(copy.deepcopy(T17), FX["distribution_days"], {"regime": "Defensive"}, dd_block={"blocked": True, "kind": "red"})
c = {x["key"]: x for x in t["rule"]["conditions"]}
assert t["regime"] == "Defensive" and not t["rule"]["met"] and t["rule"]["pending"] is None
assert c["trend"]["text"] == "SPY 740 под 50DMA (764) ✗" and not c["override"]["ok"] and "MOVE" in c["override"]["text"]
assert c["dd"]["text"].startswith("distribution days червени (") and "зелени" not in t["regime_reason"]
print(f"  ✓ «{t['regime_reason']}»")

print("── 3. СИНТЕТИЧНО: несиметричният престой ──")
GOOD = copy.deepcopy(T17)
GOOD["overrides"] = []
for i in GOOD["indicators"]:
    if i["name"] == "SPY тренд":
        i.update(value=780.0, ma50=760.0, ma50_prev=750.0, above_50dma=True, ma50_rising=True, trend_ok=True)
    if not i.get("informational"):
        i["status"] = "green"
run = lambda prev: th.apply_market_rule(copy.deepcopy(GOOD), None, prev, dd_block={"blocked": False})
d1 = run({"regime": "Defensive", "rule": {"met": False, "streak": 0}})
assert d1["regime"] == "Defensive" and d1["rule"]["met"] and d1["rule"]["streak"] == 1
assert d1["rule"]["pending"] == "условията са изпълнени — ден 1 от 2: Offensive от утре, ако се задържат"
d2 = run({"regime": "Defensive", "rule": d1["rule"]})
assert d2["regime"] == "Offensive" and d2["rule"]["streak"] == 2 and d2["sizing_factor"] == 1.0
d3 = run({"regime": "Offensive", "rule": d2["rule"]})
assert d3["regime"] == "Offensive"
bad = th.apply_market_rule(copy.deepcopy(GOOD), None, {"regime": "Offensive", "rule": d3["rule"]}, dd_block={"blocked": True, "kind": "red"})
assert bad["regime"] == "Defensive" and bad["rule"]["streak"] == 0                                          # към Defensive — веднага
assert run({"regime": "Defensive"})["regime"] == "Defensive"                                                # стар бриф без „rule“ — ден 1
print("  ✓ ден 1 → Defensive („ден 1 от 2“); ден 2 → Offensive; червени DD → Defensive веднага; стар бриф — ден 1")

print("── 4. СИНТЕТИЧНО: HY OAS без данни — само по HYG, видимо ──")
oas = copy.deepcopy(IND["HY / IG OAS (кредитни спредове)"]); oas["hy"]["hide"] = True
cp2 = th.credit_pressure(dict(IND["IEI/HYG (Credit Spread)"], hyg_10d_pct=-1.4), oas)
assert cp2["active"] is True and cp2["oas_missing"] and "HY OAS: няма данни от 13.11 — само по HYG" in cp2["text"]
assert th.credit_pressure({"hide": True}, None)["active"] is None
GONE = copy.deepcopy(T17)                                                                                   # СИНТЕТИЧНО: днес FRED не върна HY OAS
for i in GONE["indicators"]:
    if "OAS" in i["name"]:
        i.clear(); i.update({"name": "HY / IG OAS (кредитни спредове)", "value": None, "status": "yellow", "hide": True, "informational": True, "label": "", "hide_reason": "HY OAS — няма данни"})
GONE["credit_pressure"] = th.credit_pressure(IND["IEI/HYG (Credit Spread)"], next(i for i in GONE["indicators"] if "OAS" in i["name"]))
g = th.apply_market_rule(GONE, None, T17, dd_block={"blocked": False})                                     # предишният бриф (17.11) — HY OAS към 13.11
assert g["rule"]["credit"].endswith("HY OAS: няма данни от 13.11 — условието за кредит е само по HYG") and g["rule"]["oas_missing_since"] == "2026-11-13"
assert next(i for i in g["indicators"] if "OAS" in i["name"])["hide_reason"] == "HY OAS: няма данни от 13.11 — условието за кредит е само по HYG"
print(f"  ✓ «{cp2['text']}»; без HYG и HY OAS — „няма данни“ (override-ът на IEI/HYG остава)")

print("── 5. плочката, GLB, книгите ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B); b["thermometer"] = d1
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
assert "SPY 780 над растяща 50DMA (760) ✓" in txt and "⏳ условията са изпълнени — ден 1 от 2" in txt and "Едно правило за CANSLIM, Kullamägi и GLB" in txt
assert "Пазарът: Defensive" in txt and "наш заместител на пазарното правило на Уиш" not in txt
assert backtest.regime_rule_tag("2026-11-18") == {"regime_rule": config.REGIME_RULE_VERSION} and backtest.regime_rule_tag("2026-11-17") == {}
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'steps.step("market_rule", lambda: apply_market_rule(thermo, distribution_days, prev_for_regime.get("thermometer")' in src
print("  ✓ условията на плочката, „ден 1 от 2“, GLB — „Пазарът: …“ по същото правило; новите записи — regime_rule")
print("\n✅ test_market_rule: всичко мина")
