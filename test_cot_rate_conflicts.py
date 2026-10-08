"""
Пакет 3 (2026-10-05) · междупазарна проверка за лихвените пазари: един и същ тикър с ПРОТИВОПОЛОЖЕН ефект в различни лихвени пазари (2Y/5Y/10Y/Ultra/30Y) при
една и съща посока на доходностите → "mixed" → изключен от всички тези пазари с причина.

РЕАЛНО: екстремумите от брифа на 05.10.2026 — 2-Year Treasury Note и 30-Year Treasury Bond (и двата extreme_long → цена надолу → доходности нагоре), RBOB Gasoline;
реалните ефекти на EXPD от старите AI тези: губи в 2Y, печели в 30Y, печели в RBOB (tests/fixtures/brief_2026-10-05.json). СИНТЕТИЧНО: механизмите на модела (типовете,
които биха дали тези ефекти: 2Y rate_duration_valuation, 30Y rate_asset_yield, RBOB input_cost), другите тикъри, пазарите с друга посока/вид, подменените lookup и _call_claude.
Пускане: python test_cot_rate_conflicts.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from tests import helpers_cot

import config
from src import ai_brief, cot_theses as ct

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
ROWS = {c["market"]: c for c in B05["cot"]}
keys = ("market", "category", "net_position", "percentile", "direction", "as_of", "weeks_of_history", "history")
ext = lambda m, **o: {**{k: ROWS[m][k] for k in keys}, **o}
real = {m: {t["ticker"]: t["effect"] for t in (ROWS[m]["cross_sector_thesis"] or {}).get("tickers") or []} for m in ("2-Year Treasury Note", "30-Year Treasury Bond", "RBOB Gasoline")}
assert real["2-Year Treasury Note"]["EXPD"] == "loses" and real["30-Year Treasury Bond"]["EXPD"] == "gains" and real["RBOB Gasoline"]["EXPD"] == "gains"
assert ROWS["2-Year Treasury Note"]["direction"] == ROWS["30-Year Treasury Bond"]["direction"] == "extreme_long"

ai_brief._verified_company_name = lambda t: {"name": t, "verified": True, "quote_type": "EQUITY", "category": None, "long_name": t, "sector": None, "industry": None}
helpers_cot.neutral_identity(ai_brief)                                                                                          # проверките за идентичност имат свой тест (test_cot_claims.py)
ai_brief._call_claude = lambda *a, **k: (_ for _ in ()).throw(AssertionError("моделът не бива да се вика"))
T = lambda t, *m: {"ticker": t, "company": t, "mechanisms": [{"type": a, "quote": "описание на механизма"} for a in m]}


def run(raw, extremes):
    with contextlib.redirect_stdout(io.StringIO()):
        out = ai_brief.evaluate_cot_theses(extremes, raw, [], [], [])
    return {c["market"]: c for c in out}


E = [ext("2-Year Treasury Note"), ext("30-Year Treasury Bond"), ext("RBOB Gasoline")]
RAW = {"2-Year Treasury Note": [T("EXPD", "rate_duration_valuation"), T("JPM", "rate_asset_yield")],
       "30-Year Treasury Bond": [T("EXPD", "rate_asset_yield"), T("JPM", "rate_asset_yield")],
       "RBOB Gasoline": [T("EXPD", "input_cost")]}

print("── РЕАЛЕН случай 05.10: EXPD е 'губи' в 2Y и 'печели' в 30Y при доходности нагоре ──")
out = run(RAW, E)
two, thirty, rbob = (out[m]["cross_sector_thesis"] for m in ("2-Year Treasury Note", "30-Year Treasury Bond", "RBOB Gasoline"))
assert [t["ticker"] for t in two["tickers"]] == ["JPM"] and [t["ticker"] for t in thirty["tickers"]] == ["JPM"]          # EXPD е изключен и от двата; JPM (еднакъв ефект) остава
want = ("mixed между пазари: печели в 30-Year Treasury Bond (доходност на активите), но губи в 2-Year Treasury Note (оценка при дълга дюрация) "
        "при една и съща посока на доходностите (нагоре)")
for th in (two, thirty):
    d = th["dropped_tickers"]
    assert d == [{"ticker": "EXPD", "code": "mixed_cross_market", "reason": want}], d
assert [t["ticker"] for t in rbob["tickers"]] == ["EXPD"] and rbob["tickers"][0]["effect"] == "gains" and not rbob.get("dropped_tickers")        # нелихвен пазар — не се пипа
print("  ✓ EXPD се изключва и от 2Y, и от 30Y със същата причина ('печели в 30Y …, но губи в 2Y …, доходности нагоре'); JPM (печели и в двата) остава; RBOB EXPD (нелихвен пазар) не се пипа")
assert ai_brief.COT_DIAG["mixed_cross_market"] == ["2-Year Treasury Note/EXPD", "30-Year Treasury Bond/EXPD"]
assert {t["ticker"]: t["effect"] for t in two["tickers"]} == {"JPM": "gains"}

print()
print("── границите ──")
raw2 = {"2-Year Treasury Note": [T("EXPD", "rate_duration_valuation")], "30-Year Treasury Bond": [T("EXPD", "rate_asset_yield")]}
o2 = run(raw2, E[:2])
assert o2["2-Year Treasury Note"]["cross_sector_thesis"]["tickers"] == [] and o2["30-Year Treasury Bond"]["cross_sector_thesis"]["tickers"] == []
assert o2["30-Year Treasury Bond"]["cross_sector_thesis"]["empty_reason"] == (
    "всички предложени тикъри бяха изключени при проверката (1): EXPD — " + want)
print("  ✓ когато това е единственият тикър, тезата остава празна с причина, сглобена от кода")
# друга посока на доходностите (5Y extreme_short = цена нагоре = доходности надолу) → естествено противоположен ефект, не е конфликт
five = ext("2-Year Treasury Note", market="5-Year Treasury Note", direction="extreme_short")
o3 = run({"2-Year Treasury Note": [T("EXPD", "rate_duration_valuation")], "5-Year Treasury Note": [T("EXPD", "rate_duration_valuation")]}, [ext("2-Year Treasury Note"), five])
assert [t["ticker"] for t in o3["2-Year Treasury Note"]["cross_sector_thesis"]["tickers"]] == ["EXPD"] and [t["ticker"] for t in o3["5-Year Treasury Note"]["cross_sector_thesis"]["tickers"]] == ["EXPD"]
effs = {m: o3[m]["cross_sector_thesis"]["tickers"][0]["effect"] for m in o3}
assert effs == {"2-Year Treasury Note": "loses", "5-Year Treasury Note": "gains"}                        # един механизъм, обратни посоки на доходностите → обратен ефект, нормално
print("  ✓ СИНТЕТИЧНО: при ОБРАТНА посока на доходностите (2Y нагоре, 5Y надолу) противоположният ефект е нормален (един механизъм) → без конфликт")
# еднакъв ефект в три лихвени пазара; ефект None не се брои; три срока с един различен → изключва се от всички три
three = [ext("2-Year Treasury Note"), ext("30-Year Treasury Bond"), ext("2-Year Treasury Note", market="10-Year Treasury Note")]
o4 = run({"2-Year Treasury Note": [T("AA", "rate_asset_yield"), T("BB", "rate_asset_yield"), T("CC", "other")], "30-Year Treasury Bond": [T("AA", "rate_asset_yield"), T("BB", "rate_duration_valuation"), T("CC", "rate_asset_yield")],
          "10-Year Treasury Note": [T("AA", "rate_asset_yield"), T("BB", "rate_asset_yield"), T("CC", "rate_asset_yield")]}, three)
by = {m: [t["ticker"] for t in o4[m]["cross_sector_thesis"]["tickers"]] for m in o4}
assert by == {"2-Year Treasury Note": ["AA", "CC"], "30-Year Treasury Bond": ["AA", "CC"], "10-Year Treasury Note": ["AA", "CC"]}, by          # BB: 2 пазара печелят, 1 губи → изключен навсякъде; CC: other няма ефект → не се брои
assert [d["ticker"] for d in o4["10-Year Treasury Note"]["cross_sector_thesis"]["dropped_tickers"]] == ["BB"]
print("  ✓ СИНТЕТИЧНО: A печели навсякъде (остава); BB печели в два срока и губи в един → изключен от ВСИЧКИ три; CC с 'other' в единия (без ефект) → не се брои, остава")
# нелихвени пазари с противоположен ефект — не е това правило
o5 = run({"RBOB Gasoline": [T("XX", "input_cost")], "Corn": [T("XX", "output_price")]}, [ext("RBOB Gasoline"), ext("Corn")])
assert all(o5[m]["cross_sector_thesis"]["tickers"] for m in o5)
print("  ✓ нелихвени пазари (RBOB/Corn) със същия тикър и различен механизъм — правилото не ги засяга")
print()
print("Всички тестове минаха.")
