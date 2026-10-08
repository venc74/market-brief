"""
Имена на компании · показване (08.10.2026, code-queue и дребните от прегледа на брифа). В брифа на 08.10: отрязани имена — Yahoo реже shortName на 30–31 знака ("Corcept Therapeutics Incorporat",
"Expeditors International of Was", "Northwest Natural Holding Compa", "Invesco CurrencyShares Australi", "ProShares Short 20+ Year Treasu", "Invesco S&P SmallCap Informatio"), имейлът реже на 26 символа посред дума,
"RELX PLC PLC", правни окончания, които само заемат място (Inc., Corporation, Holding Company, Limited…).
  • names.prefer_long: при отрязано shortName (сурово ≥ 30 знака, longName започва със същото) се взима longName; пълно име (31 знака, но не отрязано) не се пипа;
  • names.display_name: САМО за показване — без правни окончания и водещо "The", рязане по граница на дума със «…» (dashboard 34/40/28, имейл 26); запазеното име в данните е пълното;
  • Jinja филтър cname в шаблоните; имейлът ползва същата функция вместо name[:26];
  • еднаквите причини за изключени тикъри са на един ред (BAC, MET, PFG — mixed: …) и няма втори ред «Изключени:», когато празната теза вече ги изброява.

РЕАЛНО: tests/fixtures/yahoo_names_2026-10-08.json (shortName/longName на 14 тикъра със Yahoo на 08.10), yahoo_info_cot_2026-10-08.json (RELX, TSM, PSCT, ASML, KOF, MDLZ, HSY), yahoo_info_DOCN_CORT_CRL_2026-10-07.json;
30Y тезата от брифа на 08.10 (BAC/MET/PFG изключени с една и съща причина). СИНТЕТИЧНО (маркирано): граничните имена.
Пускане: python test_names_display.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import names, ai_brief, render, cot_theses

FIX = ROOT / "tests" / "fixtures"
N = json.loads((FIX / "yahoo_names_2026-10-08.json").read_text(encoding="utf-8"))["info"]
C = json.loads((FIX / "yahoo_info_cot_2026-10-08.json").read_text(encoding="utf-8"))
Q = json.loads((FIX / "yahoo_info_DOCN_CORT_CRL_2026-10-07.json").read_text(encoding="utf-8"))["info"]
INFO = {**N, **{k: C[k] for k in ("RELX", "TSM", "PSCT", "ASML", "KOF", "MDLZ", "HSY", "SCHA")}, **Q}
best = lambda t: ai_brief._best_company_name(INFO[t]["shortName"], INFO[t]["longName"])

print("── 1. отрязаното shortName → longName (РЕАЛНИ Yahoo отговори) ──")
TRUNC = {"CORT": "Corcept Therapeutics Incorporated", "EXPD": "Expeditors International of Washington, Inc.", "NWN": "Northwest Natural Holding Company", "HE": "Hawaiian Electric Industries, Inc.",
         "FXA": "Invesco CurrencyShares Australian Dollar Trust", "FXB": "Invesco CurrencyShares British Pound Sterling Trust", "FXE": "Invesco CurrencyShares Euro Currency Trust",
         "TBF": "ProShares Short 20+ Year Treasury", "FBTC": "Fidelity Wise Origin Bitcoin Fund", "PSCT": "Invesco S&P SmallCap Information Technology ETF",
         "TSM": "Taiwan Semiconductor Manufacturing Company Limited", "CRL": "Charles River Laboratories International, Inc."}
for t, want in TRUNC.items():
    assert len(INFO[t]["shortName"]) >= 30 and best(t) == want, (t, INFO[t]["shortName"], best(t))
print(f"  ✓ {len(TRUNC)} реални отрязани имена (напр. «{INFO['CORT']['shortName']}» → «{TRUNC['CORT']}», «{INFO['FXA']['shortName']}» → «{TRUNC['FXA']}»)")
KEEP = ("VGLT", "IWM", "SCHA", "KOF", "MDLZ", "HSY", "RELX", "ASML")
for t in KEEP:
    assert best(t) == INFO[t]["shortName"].strip(), (t, best(t))
assert best("VGLT") == "Vanguard Long-Term Treasury ETF" and best("IWM") == "iShares Russell 2000 Index Fund" and best("DOCN") == "DigitalOcean Holdings, Inc."
print("  ✓ пълно име от 31 знака не се подменя (Vanguard Long-Term Treasury ETF, iShares Russell 2000 Index Fund — longName не започва със същото); кратките са както досега")
assert names.prefer_long("Short Name Here Under Thirty", "Short Name Here Under Thirty Extended Inc") == "Short Name Here Under Thirty"      # СИНТЕТИЧНО: под 30 знака не се подозира отрязване
assert names.prefer_long(None, "Само дълго") == "Само дълго" and names.prefer_long("Само кратко", None) == "Само кратко" and names.prefer_long(None, None) is None
print("  ✓ СИНТЕТИЧНО: под 30 знака не се подозира; липсващо едно от имената — другото")

print()
print("── 2. display_name ──")
D = names.display_name
assert D("RELX PLC PLC") == "RELX" and D("Northwest Natural Holding Company") == "Northwest Natural" and D("Hawaiian Electric Industries, Inc.") == "Hawaiian Electric Industries"
assert D("Taiwan Semiconductor Manufacturing Company Limited") == "Taiwan Semiconductor Manufacturing" and D("Mondelez International, Inc.") == "Mondelez International"
assert D("The Hershey Company") == "Hershey" and D("Coca Cola Femsa S.A.B. de C.V.") == "Coca Cola Femsa" and D("SAP  SE") == "SAP" and D("Novo Nordisk A/S") == "Novo Nordisk"
assert D("Wheaton Precious Metals Corp.") == "Wheaton Precious Metals" and D("Expeditors International of Washington, Inc.") == "Expeditors International of Washington"
print("  ✓ РЕАЛНИ: RELX PLC PLC → RELX; Northwest Natural Holding Company → Northwest Natural; Taiwan Semiconductor Manufacturing Company Limited → Taiwan Semiconductor Manufacturing; The Hershey Company → Hershey; "
      "Coca Cola Femsa S.A.B. de C.V. → Coca Cola Femsa; SAP  SE → SAP")
assert D("Alphabet Inc. Class A") == "Alphabet Inc. Class A" and D("Company") == "Company" and D("") == "" and D(None) == "" and D("Holdings Inc") == "Holdings"                           # СИНТЕТИЧНО
assert D("iShares Russell 2000 ETF") == "iShares Russell 2000 ETF" and D("BHP Group Limited") == "BHP Group"                                                                    # "Group" е част от идентичността
print("  ✓ СИНТЕТИЧНО: вътрешно «Inc.» (Alphabet Inc. Class A), еднословно име, празно/None — както са; «Group» не се маха (BHP Group Limited → BHP Group)")
assert D("Expeditors International of Washington, Inc.", 26) == "Expeditors International…" and D("Taiwan Semiconductor Manufacturing Company Limited", 26) == "Taiwan Semiconductor…"
assert D("Charles River Laboratories International, Inc.", 34) == "Charles River Laboratories…" and D("Invesco CurrencyShares Australian Dollar Trust", 34) == "Invesco CurrencyShares Australian…"
assert D("Schwab Short-Term U.S. Treasury ETF", 22) == "Schwab Short-Term U.S.…" and D("Corcept Therapeutics Incorporated", 26) == "Corcept Therapeutics"
assert D("Supercalifragilisticexpialidocious Company", 20) == "Supercalifragilistic…"                                                             # СИНТЕТИЧНО: една дълга дума се реже на символ
assert len(D("Expeditors International of Washington, Inc.", 26)) <= 27 and "Incorporat" not in D("Corcept Therapeutics Incorporated", 26)
print("  ✓ рязане по граница на дума със «…»: «Expeditors International…» (26), «Charles River Laboratories…» (34), «Invesco CurrencyShares Australian…» (34); една дълга дума се реже на символ")

print()
print("── 3. страницата и имейлът (РЕАЛНИТЕ имена от 08.10 в карти и COT) ──")
tmp = tempfile.TemporaryDirectory(prefix="mb_names_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(tmp.name) / "docs", pathlib.Path(tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
B05 = json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B05)
b["watchlist"][0]["company"] = "Expeditors International of Washington, Inc."
b["cot"][0]["direct_thesis"] = {"tickers": [{"ticker": "RELX", "company": "RELX PLC PLC", "effect": "gains"}, {"ticker": "TSM", "company": "Taiwan Semiconductor Manufacturing Company Limited", "effect": "gains"}], "source": "table", "reasoning": ""}
with contextlib.redirect_stdout(io.StringIO()):
    page = htmllib.unescape(render.render_dashboard(b))
assert '<span class="company">Expeditors International of Washington</span>' in page
assert "RELX (RELX)" in page and "TSM (Taiwan Semiconductor Manufacturing)" in page and "RELX PLC PLC" not in page
print("  ✓ Watchlist картата: «Expeditors International of Washington»; COT: «RELX (RELX)», «TSM (Taiwan Semiconductor Manufacturing)» — без «PLC PLC» и без правни окончания")
from tests import helpers_page
hb, _lv = helpers_page.build_brief()                                           # РЕАЛНА Action карта (EXEL) за имейла; пише във временни папки
hb["action"][0]["company"] = "Northwest Natural Holding Company"             # РЕАЛНОТО име от 08.10 върху картата
hb["action"][0]["ticker"] = hb["action"][0]["ticker"]
with contextlib.redirect_stdout(io.StringIO()):
    email = htmllib.unescape(render.render_email(hb))
assert "Northwest Natural" in email and "Holding Company" not in email
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "company[:" not in tpl and "name[:26]" not in (ROOT / "src" / "render.py").read_text(encoding="utf-8")
print("  ✓ имейлът (Action реда): «Northwest Natural» без «Holding Company»; в шаблона няма повече company[:N], имейлът не ползва name[:26]")

print()
print("── 4. еднакви причини на един ред (РЕАЛНАТА 30Y теза от брифа на 08.10) ──")
reason = "mixed: противоположен ефект — оценка при дълга дюрация (+) срещу доходност на активите (−)"
dropped30 = [{"ticker": t, "code": "mixed", "reason": reason} for t in ("BAC", "MET", "PFG")]
assert cot_theses.group_dropped(dropped30) == [{"tickers": ["BAC", "MET", "PFG"], "reason": reason}]
empty = cot_theses.cross_empty_reason(True, dropped30)
assert empty == f"всички предложени тикъри бяха изключени при проверката (3): BAC, MET, PFG — {reason}", empty
assert cot_theses.group_dropped([{"ticker": "A", "reason": "x"}, {"ticker": "B", "reason": "y"}, {"ticker": "C", "reason": "x"}, "OLD"]) == [{"tickers": ["A", "C"], "reason": "x"}, {"tickers": ["B"], "reason": "y"}, {"tickers": ["OLD"], "reason": ""}]
b3 = copy.deepcopy(B05)
row = next(r for r in b3["cot"] if r.get("cross_sector_thesis") is not None)
row["cross_sector_thesis"] = {"tickers": [], "no_direct_link": True, "reasoning": "", "dropped_tickers": dropped30, "empty_reason": empty, "outside_screener": False}
with contextlib.redirect_stdout(io.StringIO()):
    page3 = htmllib.unescape(render.render_dashboard(b3))
assert page3.count("BAC, MET, PFG") == 1 and page3.count(reason) == 1 and "Изключени: BAC" not in page3
b3["cot"][0]["cross_sector_thesis"] = {"tickers": [{"ticker": "KEEP", "company": "Keep", "effect": "gains", "sentence": "x", "quote": "y"}], "dropped_tickers": dropped30, "outside_screener": False}
with contextlib.redirect_stdout(io.StringIO()):
    page4 = htmllib.unescape(render.render_dashboard(b3))
assert "Изключени: BAC, MET, PFG — " + reason in page4
print("  ✓ празната теза: «… (3): BAC, MET, PFG — mixed: …» ЕДНОКРАТНО (преди: три пъти в причината и още веднъж в реда «Изключени:»); при непразна теза редът «Изключени: BAC, MET, PFG — …» е един")
print("\n✅ test_names_display: всичко мина")
