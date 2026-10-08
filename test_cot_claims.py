"""
COT · идентичност на компанията и валутен механизъм (08.10.2026). Три реални дефекта от брифа на 08.10:
  • Lean Hogs "WH (Wyndham Hotels)" — текстът беше за WH Group (Хонконг); XRP "SI (Shoulder Innovations)" — текстът беше за Silvergate (делистната, тикърът е преизползван);
  • AUD ↓: BHP и RIO "губят" чрез "валутен превод на приходи", а те продават в USD и имат разходи в AUD (печелят);
  • Russell 2000 cross: три small-cap ETF-а (SCHA, IJR, PSCT), дубликати на IWM.
Поправка: моделът дава company_claim (за коя компания е описанието), а за валутен механизъм — exposure_side + currencies; кодът сверява името с Yahoo, извежда типа на валутния механизъм,
изключва фондове и не-USD отчитащи се от валутните тези и тикър без сектор/индустрия в Yahoo ("не може да се провери") — виж config.py над COT_CROSS_BLOCKED_QUOTE_TYPES и cot_theses.cross_gate.

РЕАЛНО: tests/fixtures/cot_real_2026-10-08.json — суровите отговори на модела от кеша (генерирани 08.10, БЕЗ новите полета) за 20 пазара/55 тикъра + последното проверено от Yahoo име на тикър в
публикуваните брифове; tests/fixtures/yahoo_info_cot_2026-10-08.json — ЖИВ Yahoo info (08.10) за всичките 55 тикъра от отговорите + инцидентите (BHP, RIO, WPM, TSM, RELX, SAP, KOF, SCHA, IJR, PSCT, WH, SI…); тикър без име = делистнат (реално).
СИНТЕТИЧНО (маркирано на всяко място): company_claim = company на модела (както би го написал по новия промпт), exposure_side/currencies по икономиката на компанията, граничните случаи,
мрежата (lookup-ът връща РЕАЛНИТЕ Yahoo полета от fixture-а). Пускане: python test_cot_claims.py
"""
import sys, json, pathlib, contextlib, io, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import ai_brief, cot_theses as ct

FX = json.loads((ROOT / "tests" / "fixtures" / "cot_real_2026-10-08.json").read_text(encoding="utf-8"))
YI = json.loads((ROOT / "tests" / "fixtures" / "yahoo_info_cot_2026-10-08.json").read_text(encoding="utf-8"))
MK = FX["markets"]
YN = {t: v["name"] for t, v in FX["yahoo_name"].items()}


def lookup_real(t):
    """lookup като ai_brief._verified_company_name, но от РЕАЛНИЯ Yahoo info (08.10) — за тикъри извън fixture-а няма сведения (verified=False)."""
    i = YI.get(t)
    if not i:
        return {"name": t, "verified": False, "quote_type": None, "category": None, "long_name": None, "short_name": None, "sector": None, "industry": None, "financial_currency": None}
    name = ai_brief._best_company_name(i["shortName"], i["longName"])
    return {"name": name or t, "verified": bool(name), "quote_type": i["quoteType"], "category": i["category"], "long_name": i["longName"], "short_name": i["shortName"],
            "sector": i["sector"], "industry": i["industry"], "financial_currency": i["financialCurrency"]}


ai_brief._verified_company_name = lookup_real
ai_brief._call_claude = lambda *a, **k: (_ for _ in ()).throw(AssertionError("моделът не бива да се вика"))


def raw_of(market, add_claim=True, **side):
    """РЕАЛНИЯТ суров отговор на модела за пазара; add_claim — СИНТЕТИЧНО добавя company_claim = company; side: {тикър: (exposure_side, [валути])} — СИНТЕТИЧНО добавя към валутните механизми."""
    out = copy.deepcopy(MK[market]["tickers"])
    for t in out:
        if add_claim:
            t["company_claim"] = t["company"]
        if t["ticker"] in side:
            for m in t["mechanisms"]:
                if m["type"] in config.COT_FX_TYPES:
                    m["exposure_side"], m["currencies"] = side[t["ticker"]][0], list(side[t["ticker"]][1])
    return out


def run(market, raw, direction=None):
    ext = {"market": market, "category": "x", "net_position": 0, "percentile": 5, "direction": direction or MK[market]["direction"], "as_of": (MK.get(market) or {}).get("as_of", "2026-09-29"), "weeks_of_history": 156, "history": []}
    with contextlib.redirect_stdout(io.StringIO()):
        out = ai_brief.evaluate_cot_theses([ext], {market: raw}, [], [], [])
    return out[0]["cross_sector_thesis"]


def dropped(th):
    return {d["ticker"]: d["code"] for d in th.get("dropped_tickers") or []}


def kept(th):
    return {t["ticker"]: t["effect"] for t in th["tickers"]}


print("── 1. сверяване на името: РЕАЛНИ двойки (име на модела от кеша × РЕАЛЕН Yahoo lookup на 08.10) ──")
seen, rows = set(), []
for m, e in MK.items():
    for t in e["tickers"]:
        k = (t["ticker"], t["company"])
        lk = lookup_real(t["ticker"])
        if k in seen or not lk["verified"]:                                                                                           # без име в Yahoo (делистнат/преименуван): хваща се от стария gate 'unverified'
            continue
        seen.add(k)
        rows.append((t["ticker"], t["company"], lk["name"], ct.claim_matches(t["company"], lk)))
N = len(rows)
bad = sorted(r[0] for r in rows if not r[3])
assert bad == ["SI", "WH"], bad
print(f"  ✓ {N - 2} от {N} реални двойки съвпадат; несъвпадат точно двата реални инцидента: SI (Silvergate Capital ≠ Shoulder Innovations, Inc.), WH (Smithfield Foods (WH Group ADR) ≠ Wyndham Hotels & Resorts, Inc.); 0 фалшиви положителни")
for tk_, claim in (("MSTR", "MicroStrategy"), ("MARA", "Marathon Digital Holdings"), ("KOF", "Coca-Cola FEMSA"), ("JPM", "JPMorgan Chase"), ("HSY", "Hershey"), ("MDLZ", "Mondelēz International")):
    assert ct.claim_matches(claim, lookup_real(tk_)), (tk_, claim)
print("  ✓ преименувани/написани различно — съвпадат: MicroStrategy ↔ Strategy Inc, Marathon Digital ↔ MARA Holdings, Coca-Cola FEMSA ↔ Coca Cola Femsa, JPMorgan ↔ JP Morgan Chase, Mondelēz ↔ Mondelez")
assert not ct.claim_matches("Silvergate Capital", {"name": "Axis Capital Holdings Limited"})                                      # СИНТЕТИЧНО: обща дума 'Capital' не е идентичност
assert not ct.claim_matches("", {"name": "X"}) and not ct.claim_matches("Inc.", {"name": "Apple Inc."}) and not ct.claim_matches("Тест", {"name": "Test"})   # СИНТЕТИЧНО: празно/само правна форма/кирилица
assert ct.claim_matches("Global Industries", {"name": "Global Industries Ltd"})                                                  # СИНТЕТИЧНО: само общи думи → сравняват се и те
print("  ✓ СИНТЕТИЧНО: обща дума (Capital) не е идентичност; празно твърдение / само правна форма / кирилица → не съвпада; само общи думи ('Global Industries') → сравняват се и те")

print()
print("── 2. РЕАЛНИТЕ отговори от 08.10 (без новите полета) през новите проверки ──")
th = run("Lean Hogs", raw_of("Lean Hogs", add_claim=False))
assert th["tickers"] == [] and dropped(th) == {"TSN": "mixed", "WH": "no_claim", "HRL": "no_claim"}, dropped(th)               # TSN е "mixed" още в evaluate_cross (старо правило)
print("  ✓ суров отговор БЕЗ company_claim (стара версия/стар кеш при провал на batch) → всички изключени с 'no_claim' — идентичността не се проверява на доверие")
th = run("Lean Hogs", raw_of("Lean Hogs"))                                                                                                # company_claim = company (СИНТЕТИЧНО добавено)
assert dropped(th) == {"WH": "identity_claim", "TSN": "mixed"} and kept(th) == {"HRL": "loses"}, (dropped(th), kept(th))
why = next(d["reason"] for d in th["dropped_tickers"] if d["ticker"] == "WH")
assert "Smithfield Foods (WH Group ADR)" in why and "Wyndham Hotels & Resorts, Inc." in why
print(f"  ✓ Lean Hogs: WH изключен — {why}; HRL остава; TSN е 'mixed' по старото правило")
th = run("XRP", raw_of("XRP"))
assert dropped(th) == {"SI": "identity_claim"} and sorted(kept(th)) == ["AFRM", "COIN"], (dropped(th), kept(th))
assert "Silvergate Capital" in th["dropped_tickers"][0]["reason"] and "Shoulder Innovations, Inc." in th["dropped_tickers"][0]["reason"]
print("  ✓ XRP: SI (Silvergate Capital) изключен — Yahoo води SI като 'Shoulder Innovations, Inc.'; COIN и AFRM остават")
r = raw_of("XRP")
for t in r:
    if t["ticker"] == "SI":
        t["company_claim"] = "Shoulder Innovations, Inc."                                                                                    # СИНТЕТИЧНО: твърдение, което съвпада с името
th = run("XRP", r)
assert dropped(th) == {"SI": "unverifiable"} and "няма сектор и индустрия" in th["dropped_tickers"][0]["reason"]
print("  ✓ СИНТЕТИЧНО твърдение, което съвпада с името, но РЕАЛНИЯТ Yahoo запис на SI няма сектор и индустрия → 'не може да се провери' (изключен)")
th = run("E-mini Russell 2000", raw_of("E-mini Russell 2000"))
assert th["tickers"] == [] and dropped(th) == {"SCHA": "etf", "IJR": "etf", "PSCT": "etf"}, dropped(th)
assert "ETF (Schwab U.S. Small-Cap ETF)" in th["dropped_tickers"][0]["reason"] and "всички предложени тикъри бяха изключени" in th["empty_reason"]
print("  ✓ Russell 2000: SCHA, IJR, PSCT (РЕАЛЕН quoteType ETF) → изключени с 'etf'; празната теза носи причина от кода")
d = ai_brief.COT_DIAG
assert d["dropped_by_code"] == {"etf": 3}, d["dropped_by_code"]
print("  ✓ COT_DIAG['dropped_by_code'] = {'etf': 3} — мери се колко пъти работи всяка проверка")

print()
print("── 3. валутен механизъм: страната на експозицията извежда типа (AUD ↓, РЕАЛНИТЕ BHP/RIO/WPM) ──")
real_aud = raw_of("Australian Dollar", add_claim=True)
th = run("Australian Dollar", real_aud)                                                                                                   # 3.1 стар отговор: без exposure_side
assert th["tickers"] == [] and set(dropped(th).values()) == {"fx_exposure"}, dropped(th)
print("  ✓ РЕАЛНИЯТ отговор от 08.10 (fx_revenue_translation без exposure_side) → изключени с 'fx_exposure'; БЕЗ страна на експозицията валутен механизъм не се приема")
OLD_SIGN = ct.mechanism_sign("fx_revenue_translation", "fx_foreign")
assert OLD_SIGN == 1 and ct.effect_from_sign(OLD_SIGN, "down") == "loses"                                                                 # така BHP/RIO бяха "губят" на 08.10
SIDES = {"BHP": ("foreign_cost", ["AUD"]), "RIO": ("foreign_cost", ["AUD"]), "WPM": ("foreign_cost", ["AUD"])}                            # СИНТЕТИЧНО: според икономиката (продават в USD, разходи в AUD)
th = run("Australian Dollar", raw_of("Australian Dollar", **SIDES))
assert kept(th) == {"BHP": "gains", "RIO": "gains", "WPM": "gains"}, (kept(th), dropped(th))
assert all(t["mechanisms"][0]["type"] == "fx_cost_local" and t["mechanisms"][0]["exposure_side"] == "foreign_cost" for t in th["tickers"])
assert sorted(ai_brief.COT_DIAG["fx_corrected"]) == ["Australian Dollar/BHP", "Australian Dollar/RIO"]                                   # BHP и RIO бяха с типа fx_revenue_translation; WPM вече с fx_cost_local
print("  ✓ AUD ↓ (extreme_long): с exposure_side=foreign_cost (СИНТЕТИЧНО по икономиката) типът става fx_cost_local → BHP, RIO, WPM ПЕЧЕЛЯТ; поправките на BHP и RIO са в COT_DIAG['fx_corrected']")
th = run("Australian Dollar", raw_of("Australian Dollar", BHP=("foreign_revenue", ["AUD"]), RIO=("both", ["AUD"]), WPM=("foreign_cost", ["EUR"])))
assert kept(th) == {"BHP": "loses"} and dropped(th) == {"RIO": "fx_both", "WPM": "fx_currency"}, (kept(th), dropped(th))
print("  ✓ СИНТЕТИЧНО: foreign_revenue в AUD → 'губи' (старото поведение е по избор на страната); both → 'fx_both' (изключен); валутите без AUD → 'fx_currency'")
th = run("Australian Dollar", raw_of("Australian Dollar", BHP=("foreign_cost", []), RIO=("някъде", ["AUD"])))
assert dropped(th) == {"BHP": "fx_exposure", "RIO": "fx_exposure", "WPM": "fx_exposure"}                                         # WPM остава с реалния отговор от 08.10 — без страна
print("  ✓ СИНТЕТИЧНО: без валути / невалидна страна → 'fx_exposure'")
th = run("Australian Dollar", raw_of("Australian Dollar", **SIDES), direction="extreme_short")
assert kept(th) == {"BHP": "loses", "RIO": "loses", "WPM": "loses"}
print("  ✓ AUD ↑ (extreme_short) — обратният ефект (разходи в AUD растат): губят")
usd = [{"ticker": "MCD", "company": "McDonald's", "company_claim": "McDonald's Corporation", "mechanisms": [{"type": "fx_revenue_translation", "quote": "франчайз такси в чужбина", "exposure_side": "foreign_revenue", "currencies": ["EUR", "GBP"]}]}]   # СИНТЕТИЧНО (РЕАЛЕН lookup на MCD)
th = run("US Dollar Index", usd, direction="extreme_short")
assert kept(th) == {"MCD": "loses"}                                                                                                       # DXY ↑: приходи в чужда валута → по-малко USD
usd[0]["mechanisms"][0]["currencies"] = ["USD"]
th = run("US Dollar Index", usd, direction="extreme_short")
assert dropped(th) == {"MCD": "fx_exposure"} and "само в USD" in th["dropped_tickers"][0]["reason"]
print("  ✓ US Dollar Index: валутите на експозицията (EUR, GBP) не се сверяват с една конкретна валута → приходи в чужбина при DXY ↑ 'губи'; експозиция само в USD → 'fx_exposure'")

print()
print("── 4. не-USD отчитащи се са извън валутните тези (РЕАЛНИ Yahoo: KOF→MXN, SAP→EUR, RELX→GBP, TSM→TWD; LLY, MCD, BHP, RIO, WPM→USD) ──")
assert [YI[t]["financialCurrency"] for t in ("KOF", "SAP", "RELX", "TSM", "LLY", "MCD", "BHP", "RIO", "WPM")] == ["MXN", "EUR", "GBP", "TWD", "USD", "USD", "USD", "USD", "USD"]
th = run("Mexican Peso", raw_of("Mexican Peso", KOF=("foreign_revenue", ["MXN"]), BSMX=("foreign_revenue", ["MXN"]), AMXL=("foreign_revenue", ["MXN"])))
assert dropped(th) == {"GME": "schema", "KOF": "non_usd_reporter", "BSMX": "unverified", "AMXL": "unverified"} and th["tickers"] == [], dropped(th)
assert "отчита в MXN" in next(d["reason"] for d in th["dropped_tickers"] if d["ticker"] == "KOF")
print("  ✓ РЕАЛНИЯТ отговор за Mexican Peso (+ СИНТЕТИЧНА страна foreign_revenue/MXN): KOF → 'non_usd_reporter' (Yahoo financialCurrency MXN); BSMX и AMXL без име в Yahoo → 'unverified'; GME без механизъм → 'schema'")
th = run("Euro FX", raw_of("Euro FX", SAP=("foreign_revenue", ["EUR"]), LLY=("foreign_revenue", ["EUR"]), MCD=("foreign_revenue", ["EUR"])))
assert dropped(th) == {"SAP": "non_usd_reporter"} and kept(th) == {"LLY": "gains", "MCD": "gains"}, (dropped(th), kept(th))
print("  ✓ РЕАЛНИЯТ отговор за Euro FX (EUR ↑, extreme_short; страната е СИНТЕТИЧНА): SAP (отчита в EUR) изключен; LLY и MCD (USD) остават и ПЕЧЕЛЯТ")
eur = [{"ticker": "RELX", "company": "RELX PLC", "company_claim": "RELX PLC", "mechanisms": [{"type": "fx_revenue_translation", "quote": "приходи в паунд", "exposure_side": "foreign_revenue", "currencies": ["GBP"]}]}]   # СИНТЕТИЧНО
th = run("British Pound", eur, direction="extreme_short")
assert dropped(th) == {"RELX": "non_usd_reporter"} and "GBP" in th["dropped_tickers"][0]["reason"]
nonfx = [{"ticker": "RELX", "company": "RELX PLC", "company_claim": "RELX PLC", "mechanisms": [{"type": "index_beta", "quote": "бета към пазара"}]}]   # СИНТЕТИЧНО
th = run("Nasdaq-100", nonfx, direction="extreme_short")
assert kept(th) == {"RELX": "gains"}
print("  ✓ RELX (GBP) е изключен от валутна теза, но НЕ от невалутна (index_beta към Nasdaq-100 остава) — правилото е само за валутни механизми")
th = run("Euro FX", [{"ticker": "SAP", "company": "SAP SE", "company_claim": "SAP SE", "mechanisms": [{"type": "fx_revenue_translation", "quote": "приходи в евро", "exposure_side": "foreign_revenue", "currencies": ["EUR"]}]}])
assert dropped(th) == {"SAP": "non_usd_reporter"}
YI_BAK = YI["SAP"]["financialCurrency"]
YI["SAP"]["financialCurrency"] = None                                                                                                      # СИНТЕТИЧНО: Yahoo не връща валута на отчитане
th = run("Euro FX", [{"ticker": "SAP", "company": "SAP SE", "company_claim": "SAP SE", "mechanisms": [{"type": "fx_revenue_translation", "quote": "приходи в евро", "exposure_side": "foreign_revenue", "currencies": ["EUR"]}]}])
YI["SAP"]["financialCurrency"] = YI_BAK
assert dropped(th) == {"SAP": "unverifiable"} and "валута на отчитане" in th["dropped_tickers"][0]["reason"]
print("  ✓ СИНТЕТИЧНО: Yahoo без валута на отчитане → 'не може да се провери' (изключен)")

print()
print("── 5. директната таблица не е засегната от cross проверките ──")
with contextlib.redirect_stdout(io.StringIO()):
    tbl = ai_brief.evaluate_cot_theses([{"market": "E-mini Russell 2000", "category": "x", "net_position": 0, "percentile": 5, "direction": "extreme_short", "as_of": "2026-09-29", "weeks_of_history": 156, "history": []}],
                                       {"E-mini Russell 2000": []}, [], [], [])
direct = tbl[0]["direct_thesis"]
assert direct["tickers"] and all(t.get("source") == "table" for t in direct["tickers"]) and not direct.get("dropped_tickers")
print(f"  ✓ директната теза за Russell 2000 ({', '.join(t['ticker'] for t in direct['tickers'])}) остава: ETF-ите в таблицата са нормални, правилото 'без ETF' е само за cross от модела")

print()
print("── 6. версията на промпта се смени → кешът не се ползва повторно ──")
v = ai_brief.cot_prompt_version()
assert v != "v1-bf414d7d" and v.startswith("v1-")
assert "company_claim" in ai_brief._build_cot_user_prompt([]) and "exposure_side" in ai_brief._build_cot_user_prompt([])
print(f"  ✓ версията е {v}, а ключовете в кеша от 08.10 са v1-bf414d7d → следващият run регенерира с новите полета")
print("\n✅ test_cot_claims: всичко мина")
