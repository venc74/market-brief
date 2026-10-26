"""
26.10.2026 · етап 4б, т. 4 · макро текстът · твърдения за КРЕДИТЕН стрес при HYG, който почти не мърда (src/regime_claims.py: код "credit", config.CREDIT_CLAIM_HYG_CONFIRM_PCT = −0.2).

Реален дефект (macro_brief на 23.10): "… ускорява се и стои на 96-ти percentile — кредитният пазар потвърждава стреса, не го опровергава, въпреки спада на yields", а разлагането на
10-дневната RoC беше IEI +1.07% / HYG −0.05% — скокът е от лихвите, кредитът почти не мърда. Измерено върху 94 брифа: 14 твърдения за кредитен стрес, при HYG над −0.2% — 3 (19.10, 20.10,
23.10), 0 фалшиви; 21.10 ("пазарът излиза от кредитен риск", HYG −0.57%) и 26.10 ("активен кредитен стрес", HYG −0.23%) остават.

РЕАЛНО: tests/fixtures/credit_claims_2026-10-26.json — термометърът и макро текстът на 08.09, 15.10, 19.10, 20.10, 21.10, 22.10, 23.10 и 26.10 (data/, 26.10); за 08.09–20.10 IEI/HYG
краката са добавени от реалните Close на Yahoo (свалени 26.10, legs_added). СИНТЕТИЧНО (означено): подмененото извикване на модела в т. 4.
Пускане: python test_credit_claims.py
"""
import sys, json, pathlib, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import regime_claims as rc, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "credit_claims_2026-10-26.json").read_text(encoding="utf-8"))["briefs"]
assert config.CREDIT_CLAIM_HYG_CONFIRM_PCT == -0.2


def credit(d: str) -> list[dict]:
    f = rc.facts(FX[d]["thermometer"])
    return [p for k in ("macro_brief", "regime_comment") for p in rc.check(FX[d][k] or "", f) if p["code"] == "credit"]


print("── 1. 23.10: „кредитният пазар потвърждава стреса“ при HYG −0.05% ──")
f23 = rc.facts(FX["2026-10-23"]["thermometer"])
assert (f23["credit"]["iei"], f23["credit"]["hyg"], f23["credit"]["roc"]) == (1.07, -0.05, 1.13)
mb = FX["2026-10-23"]["macro_brief"]
bad = "кредитният пазар потвърждава стреса, не го опровергава, въпреки спада на yields."
assert bad in mb
new, probs = rc.clean(mb, f23)
cr = [p for p in probs if p["code"] == "credit"]
assert len(cr) == 1 and cr[0]["sentence"].endswith(bad) and bad not in new
assert ("Разлагане на IEI/HYG от кода: 10-дневната RoC +1.13% — IEI +1.07% (лихвеният крак), HYG -0.05% (кредитният крак); скокът е от лихвите, кредитен стрес не е потвърден "
        "(иска HYG -0.2% или по-малко за 10 сесии).") in new
assert new.count("Разлагане на IEI/HYG") == 1
print(f"  ✓ изречението → разлагането от кода; why: {cr[0]['why']}")
assert credit("2026-10-23") == cr                                          # regime_comment ("сигнализира бягство към качество") — не е твърдение за кредитен стрес
print("  ✓ regime_comment на 23.10 („кредитният пазар сигнализира бягство към качество“) — непокътнат")

print()
print("── 2. цялата извадка: 19.10, 20.10, 23.10 — заменени; 21.10 и 26.10 (HYG ≤ −0.2%) и отрицанията — не ──")
hits = {d: [p["sentence"][:60] for p in credit(d)] for d in FX}
assert sorted(d for d, h in hits.items() if h) == ["2026-10-19", "2026-10-20", "2026-10-23"], hits
assert all(len(h) <= 1 for h in hits.values())
assert hits["2026-10-19"][0].startswith("Ключовият стрес идва от кредитните спредове") and hits["2026-10-20"][0].startswith("Първичният trigger е IEI/HYG override")
assert "пазарът излиза от кредитен риск" in FX["2026-10-21"]["regime_comment"] and rc.facts(FX["2026-10-21"]["thermometer"])["credit"]["hyg"] == -0.57
assert "с активен кредитен стрес" in FX["2026-10-26"]["macro_brief"] and rc.facts(FX["2026-10-26"]["thermometer"])["credit"]["hyg"] == -0.23
print("  ✓ 19.10 (HYG −0.07%), 20.10 (−0.19%), 23.10 (−0.05%) — заменени; 21.10 („излиза от кредитен риск“, −0.57%) и 26.10 („активен кредитен стрес“, −0.23%) — остават")
f22 = copy.deepcopy(FX["2026-10-22"]["thermometer"])
for i in f22["indicators"]:
    if i["name"].startswith("IEI/HYG"):
        i["hyg_10d_pct"] = -0.05                                           # СИНТЕТИЧНО: краката на 22.10 сменени, за да мине проверката върху реалните изречения
s22 = [p for k in ("macro_brief", "regime_comment") for p in rc.check(FX["2026-10-22"][k], rc.facts(f22)) if p["code"] == "credit"]
assert "не от класическо кредитно влошаване — може да отразява лихвена волатилност повече от реален credit stress" in FX["2026-10-22"]["regime_comment"] and s22 == []
assert "IEI/HYG е единственият real-time credit stress gauge" in FX["2026-09-08"]["regime_comment"] and hits["2026-09-08"] == []
assert "ако напрежението се пренесе в US сесията и задвижи credit spreads" in FX["2026-10-15"]["regime_comment"] and "(ниско ниво на credit stress)" in FX["2026-10-15"]["regime_comment"]
assert hits["2026-10-15"] == []
print("  ✓ „не от … влошаване … повече от реален credit stress“ (22.10), „credit stress gauge“ (08.09), „ако … credit spreads“ и „ниско ниво на credit stress“ (15.10) — не са твърдения")

print()
print("── 3. без краката на IEI/HYG (брифовете преди 19.10) — без проверка ──")
old = copy.deepcopy(FX["2026-10-23"]["thermometer"])
for i in old["indicators"]:
    i.pop("iei_10d_pct", None); i.pop("hyg_10d_pct", None)
assert rc.facts(old)["credit"] is None and [p for p in rc.check(mb, rc.facts(old)) if p["code"] == "credit"] == []
hid = copy.deepcopy(FX["2026-10-23"]["thermometer"])
for i in hid["indicators"]:
    if i["name"].startswith("IEI/HYG"):
        i["hide"] = True
assert rc.facts(hid)["credit"] is None
print("  ✓ без iei_10d_pct / hyg_10d_pct или при скрит индикатор — нищо не се пипа")

print()
print("── 4. ai_brief: поправката е в _apply_regime_claims (протокол в regime_claims_fixed) ──")
res = ai_brief._apply_regime_claims({"macro_brief": mb, "regime_comment": FX["2026-10-23"]["regime_comment"], "sector_logic": []}, FX["2026-10-23"]["thermometer"])
assert bad not in res["macro_brief"] and [x["code"] for x in res["regime_claims_fixed"]] == ["credit"] and res["regime_claims_fixed"][0]["field"] == "macro_brief"
assert res["regime_comment"] == FX["2026-10-23"]["regime_comment"]
print("  ✓ macro_brief поправен, regime_comment непокътнат, regime_claims_fixed: [credit]")
print("\n✅ test_credit_claims: всичко мина")
