"""
28.10.2026 · regime_claims: твърдения, че distribution days „блокират“ Offensive или „държат / поддържат“ Defensive, при SPY и QQQ под прага (9) и без блок по хистерезис — код "dd";
първото такова изречение се заменя с реда на кода („По кода: distribution days SPY 7/9, QQQ 7/9 — при 9 Offensive се блокира (липсват 2); под прага … не блокират … и не държат …“),
следващите се махат. Условното „при 9 Offensive се блокира (липсват 2)“ е вярно и остава.

Случаят (РЕАЛЕН): 28.10 — „Defensive-ът се държи изцяло от два механизма: (1) IEI/HYG override …; (2) distribution days SPY 7/9, QQQ 7/9 …“; 4 такива твърдения подред (23.10, 27.10,
28.10; и 19.10 — „допълнително блокират евентуален Offensive“ при 8/9). Измерено върху всичките брифове с реда „Запас до смяна на режима“ (от 15.10): 4 попадения, 0 фалшиви.

РЕАЛНО: tests/fixtures/dd_claims_2026-10-28.json — термометрите и макро текстовете от 16.10, 19.10, 20.10, 23.10, 26.10, 27.10 и 28.10. СИНТЕТИЧНО (означено): червените distribution days в т. 3.
Пускане: python test_dd_claims.py
"""
import sys, json, copy, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import regime_claims as rc, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "dd_claims_2026-10-28.json").read_text(encoding="utf-8"))["briefs"]
dd_hits = lambda d: [x for k in ("macro_brief", "regime_comment") for x in rc.check(FX[d][k], rc.facts(FX[d]["thermometer"])) if x["code"] == "dd"]

print("── 1. РЕАЛНИТЕ текстове: 4 грешни, верните условни — непокътнати ──")
hits = {d: dd_hits(d) for d in FX}
assert sorted(d for d, h in hits.items() if h) == ["2026-10-19", "2026-10-23", "2026-10-27", "2026-10-28"] and all(len(h) == 1 for h in hits.values() if h)
f28 = rc.facts(FX["2026-10-28"]["thermometer"])
assert f28["dd"] == {"line": "distribution days SPY 7/9, QQQ 7/9 — при 9 Offensive се блокира (липсват 2)", "blocking": False}
assert hits["2026-10-28"][0]["sentence"].startswith("Defensive-ът се държи изцяло от два механизма")
assert "при 9 Offensive се блокира автоматично" in FX["2026-10-16"]["regime_comment"] and not hits["2026-10-16"]
assert "при 9 Offensive се блокира, а в момента до блокажа липсват само 2 дни" in FX["2026-10-26"]["regime_comment"] and not hits["2026-10-26"]
print("  ✓ 19.10, 23.10, 27.10, 28.10 — твърдения при 7–8/9; 16.10, 20.10, 26.10 (условните „при 9 … се блокира“) — непокътнати")

print()
print("── 2. заменя се с реда на кода ──")
new, probs = rc.clean(FX["2026-10-28"]["regime_comment"], f28)
assert "се държи изцяло от два механизма" not in new and new.count("По кода: distribution days SPY 7/9, QQQ 7/9 — при 9 Offensive се блокира (липсват 2); "
                                                                 "под прага distribution days не блокират Offensive и не държат Defensive.") == 1
res = ai_brief._apply_regime_claims({"macro_brief": FX["2026-10-27"]["macro_brief"], "regime_comment": FX["2026-10-27"]["regime_comment"], "sector_logic": []}, FX["2026-10-27"]["thermometer"])
assert "Offensive е блокиран (липсват 2" not in res["regime_comment"] and any(x["code"] == "dd" for x in res["regime_claims_fixed"])
print("  ✓ 28.10 и 27.10 — изречението → „По кода: distribution days SPY 7/9, QQQ 7/9 — при 9 Offensive се блокира (липсват 2); под прага …“")

print()
print("── 3. при червени distribution days твърдението е вярно (СИНТЕТИЧНО) ──")
red = copy.deepcopy(FX["2026-10-28"]["thermometer"])
red["regime_margin"]["parts"] = ["distribution days SPY 9/9, QQQ 7/9 — червени: Offensive е блокиран; блокът пада след 2 поредни дни под 9" if p.startswith("distribution days") else p
                                 for p in red["regime_margin"]["parts"]]
assert rc.facts(red)["dd"]["blocking"] and [x for x in rc.check(FX["2026-10-23"]["regime_comment"], rc.facts(red)) if x["code"] == "dd"] == []
no_margin = {k: v for k, v in FX["2026-10-28"]["thermometer"].items() if k != "regime_margin"}
assert rc.facts(no_margin)["dd"] is None and [x for x in rc.check(FX["2026-10-23"]["regime_comment"], rc.facts(no_margin)) if x["code"] == "dd"] == []
print("  ✓ при 9/9 — без промяна; без реда на кода (брифове преди 15.10) — без проверка")
print("\n✅ test_dd_claims: всичко мина")
