"""
Пакет 3 · т.д (2026-10-05): ежедневни ДЕТЕРМИНИРАНИ проверки върху (кешираните) COT тези, без AI — таблицата за знака, верификация на
тикъра (делистнат / commodity ETF за друга суровина / identity), outside_screener и значка спрямо днешния скрийнър, отворена/затворена
позиция, схема (quote + валиден тип). Изключените отиват в dropped_tickers с причина; НИКОГА не се регенерира заради отхвърляне;
empty_reason при празна теза се сглобява от кода. Проверките са ai_brief.evaluate_cot_theses() — функция, която няма достъп до модела.

РЕАЛНО: 18-те COT екстремума на 02.10.2026; реалната проверка през Yahoo (05.10.2026) за CANE ("Teucrium Sugar Fund", Commodities Focused) —
реалният случай от 11.09 (CANE се появи в Cotton); реалният скрийнър на 02.10; реалният текст и данни от случая ASR/Arca Continental от 14.09
(prose "ASR (Arca Continental) е мексикански bottler"; ASR е Grupo Aeroportuario del Sureste, Airports & Air Services — както е описано в кода).
СИНТЕТИЧНО: "кешираните" механизми на модела (tests/fixtures/cot_model_answers_2026-10-02.json), промените между "дните", делистваният тикър,
позициите, редакцията на таблицата за знака.
Пускане: python test_cot_daily_checks.py
"""
import sys, json, pathlib, io, contextlib, copy, datetime as dt, html as htmllib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from tests import helpers_cot

import config
from src import ai_brief, cot_theses as ct, render

FIX = ROOT / "tests" / "fixtures"
BRIEF = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
ANS = json.loads((FIX / "cot_model_answers_2026-10-02.json").read_text(encoding="utf-8"))["markets"]
CHK = json.loads((FIX / "cot_direct_tickers_2026-10-05.json").read_text(encoding="utf-8"))["checked"]
EXTREMES = [{k: c[k] for k in ("market", "category", "net_position", "percentile", "direction", "as_of", "weeks_of_history", "history")} for c in BRIEF["cot"]]
REAL_SCREENER = [{"ticker": a["ticker"]} for a in BRIEF["action"] + BRIEF["watchlist"]]

calls = {"ai": 0}
def no_ai(*a, **k):
    calls["ai"] += 1
    raise AssertionError("ежедневните проверки не бива да викат модела")
ai_brief._call_claude = no_ai

company = {t: r["name"] for t, r in CHK.items() if r["name"]}
for c in BRIEF["cot"]:
    for k in ("direct_thesis", "cross_sector_thesis"):
        for t in (c.get(k) or {}).get("tickers") or []:
            company.setdefault(t["ticker"], t["company"])
LOOKUP_OVERRIDE = {}
def lookup(t):
    if t in LOOKUP_OVERRIDE:
        return LOOKUP_OVERRIDE[t]
    r = CHK.get(t)
    return {"name": company.get(t, t), "verified": t in company, "quote_type": (r or {}).get("quote_type"), "category": (r or {}).get("category"),
            "long_name": company.get(t), "sector": None, "industry": None}
ai_brief._verified_company_name = lookup
helpers_cot.neutral_identity(ai_brief)                                                                                          # проверките за идентичност имат свой тест (test_cot_claims.py)


def day(raw, screener=REAL_SCREENER, open_pos=None, closed=None, extremes=EXTREMES):
    with contextlib.redirect_stdout(io.StringIO()):
        out = ai_brief.evaluate_cot_theses(extremes, raw, screener, open_pos, closed)
    return {c["market"]: c for c in out}


def cross(out, market):
    return out[market]["cross_sector_thesis"]


def names(th):
    return [t["ticker"] for t in th.get("tickers") or []]


RAW = copy.deepcopy(ANS)
print("── ден 1: базова оценка на кешираните механизми (без AI) ──")
d1 = day(RAW)
assert len(d1) == 18 and calls["ai"] == 0
assert names(cross(d1, "Corn")) == ["TSN", "PPC"] and names(cross(d1, "5-Year Treasury Note")) == ["JPM", "ALL", "AIZ"]
print("  ✓ 18 пазара, cross тезите са от механизмите; нито едно извикване на модела")

print()
print("── ден 2: ТЕЗИ СЪЩИТЕ суров отговор, променени проверки ──")
# 1) верификация: тикър, който е станал делистнат
LOOKUP_OVERRIDE["PPC"] = {"name": "PPC", "verified": False, "quote_type": None, "category": None, "long_name": None, "sector": None, "industry": None}
d2 = day(RAW)
corn = cross(d2, "Corn")
assert names(corn) == ["TSN"] and corn["dropped_tickers"] == [{"ticker": "PPC", "code": "unverified", "reason": "няма име в Yahoo (вероятно делистнат или преименуван)"}]
assert names(cross(d2, "5-Year Treasury Note")) == ["JPM", "ALL", "AIZ"]                                    # останалите пазари не са пипнати
LOOKUP_OVERRIDE["JPM"] = dict(LOOKUP_OVERRIDE["PPC"], name="JPM")
d2b = day(RAW)
t30 = cross(d2b, "30-Year Treasury Bond")                                                                    # единственият тикър отпада → празна теза с причина от кода
assert t30["tickers"] == [] and t30["empty_reason"] == "всички предложени тикъри бяха изключени при проверката (1): JPM — няма име в Yahoo (вероятно делистнат или преименуван)"
LOOKUP_OVERRIDE.clear()
print("  ✓ делистнат тикър (PPC): изключен в dropped_tickers с причина, TSN и другите пазари остават; когато е единственият (JPM на 30Y) — празна теза с empty_reason от кода")

# 2) РЕАЛЕН случай 11.09: CANE (Teucrium Sugar Fund) в тезата за Cotton
assert CHK["CANE"]["name"] == "Teucrium Sugar Fund" and CHK["CANE"]["category"] == "Commodities Focused"
raw2 = copy.deepcopy(RAW)
raw2["Cotton"] = [{"ticker": "CANE", "company": "Teucrium Sugar Fund", "mechanisms": [{"type": "substitute", "quote": "фонд върху фючърси на захар"}]},
                  {"ticker": "GAP", "company": "Gap Inc.", "mechanisms": [{"type": "input_cost", "quote": "памукът е основна суровина за облеклото"}]}]
company["GAP"] = "Gap, Inc."
d = day(raw2)
cot = cross(d, "Cotton")
assert names(cot) == ["GAP"] and [(x["ticker"], x["code"]) for x in cot["dropped_tickers"]] == [("CANE", "etf")] and "Teucrium Sugar Fund" in cot["dropped_tickers"][0]["reason"]
print("  ✓ РЕАЛЕН случай 11.09: CANE (захар) в тезата за Cotton → изключен; от 08.10 като фонд в cross (код 'etf'; 'commodity ETF за друга суровина' остава за директните тикъри), GAP остава")

# 3) РЕАЛЕН случай 14.09: identity — ASR е Grupo Aeroportuario del Sureste, а прозата го описва като Arca Continental
LOOKUP_OVERRIDE["ASR"] = {"name": "Grupo Aeroportuario del Sureste", "verified": True, "quote_type": "EQUITY", "category": None,
                          "long_name": "Grupo Aeroportuario del Sureste, S.A.B. de C.V.", "sector": "Industrials", "industry": "Airports & Air Services"}
raw3 = copy.deepcopy(RAW)
raw3["Sugar No. 11"] = [{"ticker": "ASR", "company": "Arca Continental", "mechanisms": [{"type": "input_cost", "quote": "ASR (Arca Continental) е мексикански bottler с голяма захарна разходна позиция"}]},
                        {"ticker": "KO", "company": "Coca-Cola", "mechanisms": [{"type": "input_cost", "quote": "подсладителите са съществен разход на производителя на напитки"}]}]
company["KO"] = "Coca-Cola Company"
d = day(raw3)
sug = cross(d, "Sugar No. 11")
assert names(sug) == ["KO"] and sug["dropped_tickers"][0]["ticker"] == "ASR" and sug["dropped_tickers"][0]["code"] == "identity"
assert "описанието го представя като 'Arca Continental'" in sug["dropped_tickers"][0]["reason"] and "Grupo Aeroportuario del Sureste" in sug["dropped_tickers"][0]["reason"]
LOOKUP_OVERRIDE.clear()
print("  ✓ РЕАЛЕН случай 14.09: ASR ('Arca Continental' в прозата, а е летищен оператор) → изключен САМО този тикър (преди падаше цялата под-теза), KO остава")

# 4) знак по таблицата и схема върху същия кеш
raw4 = copy.deepcopy(RAW)
raw4["Corn"] = [{"ticker": "ADM", "company": "ADM", "mechanisms": [{"type": "input_cost", "quote": "купува зърно"}, {"type": "output_price", "quote": "продава продукти"}]},
                {"ticker": "TSN", "company": "TSN", "mechanisms": [{"type": "input_cost", "quote": "  "}]},
                {"ticker": "PPC", "company": "PPC", "mechanisms": [{"type": "input_cost", "quote": "фураж"}]}]
d = day(raw4)
cn = cross(d, "Corn")
assert names(cn) == ["PPC"] and [(x["ticker"], x["code"]) for x in cn["dropped_tickers"]] == [("ADM", "mixed"), ("TSN", "schema")]
assert ai_brief.COT_DIAG["mixed"] == ["Corn/ADM"] and any(x.startswith("Corn/TSN: невалидна схема") for x in ai_brief.COT_DIAG["dropped"])
print("  ✓ mixed (ADM: input_cost + output_price) и схема (TSN: празен quote) → изключени с причина още при оценката; без регенерация")

# 5) таблицата за знака се променя → ефектите се преизчисляват от същия кеш
before = {t["ticker"]: t["effect"] for t in cross(day(RAW), "Corn")["tickers"]}
orig = config.COT_MECHANISM_SIGN["input_cost"]["sign"]["commodity"]
config.COT_MECHANISM_SIGN["input_cost"]["sign"]["commodity"] = +1
after = {t["ticker"]: t["effect"] for t in cross(day(RAW), "Corn")["tickers"]}
config.COT_MECHANISM_SIGN["input_cost"]["sign"]["commodity"] = orig
assert before == {"TSN": "gains", "PPC": "gains"} and after == {"TSN": "loses", "PPC": "loses"}
assert {t["ticker"]: t["effect"] for t in cross(day(RAW), "Corn")["tickers"]} == before
print("  ✓ СИНТЕТИЧНО: редакция на таблицата за знака (input_cost → +1) обръща ефектите на кешираните механизми (gains → loses) без AI; връщането ги възстановява")

print()
print("── днешният скрийнър, отворена и затворена позиция ──")
real_tickers = {x["ticker"] for x in REAL_SCREENER}
d_a = day(RAW, screener=REAL_SCREENER)
d_b = day(RAW, screener=[{"ticker": "ZZZZ"}])
amd_a = [t for t in cross(d_a, "Copper")["tickers"] if t["ticker"] == "AMD"][0]
amd_b = [t for t in cross(d_b, "Copper")["tickers"] if t["ticker"] == "AMD"][0]
assert "AMD" in real_tickers and [m["tag"] for m in amd_a["markers"]] == ["SCR✓"] and amd_b["markers"] == []
assert cross(d_a, "Copper")["outside_screener"] is False and cross(d_b, "Copper")["outside_screener"] is True
assert amd_a["sentence"] == amd_b["sentence"] and amd_a["effect"] == amd_b["effect"]                                         # тезата е същата; сменя се само флагът
print("  ✓ outside_screener и SCR✓ следват ДНЕШНИЯ скрийнър (РЕАЛЕН от 02.10: AMD е в него; с друг скрийнър — извън), тезата не се променя")
today = dt.date.today()
iso = lambda n: (today - dt.timedelta(days=n)).isoformat()
closed = [{"ticker": "UAL", "resolution_date": iso(3), "realized_r": -1.0, "outcome": "стоп"},
          {"ticker": "TSN", "resolution_date": iso(30), "realized_r": 2.4, "outcome": "trailing изход"},
          {"ticker": "PPC", "resolution_date": iso(2), "realized_r": 0.5, "outcome": "стоп"}]
opened = [{"ticker": "PPC", "company": "Pilgrim's", "entry_date": iso(1)}]                                                 # PPC е затворена преди и пак отворена → отворена печели
d_c = day(RAW, open_pos=opened, closed=closed)
tags = lambda out, mk, tk_: [m["tag"] for t in cross(out, mk)["tickers"] if t["ticker"] == tk_ for m in t["markers"]]
assert tags(d_c, "RBOB Gasoline", "UAL") == ["CLOSED"]                                                                    # затворена преди 3 дни
assert tags(d_c, "Corn", "TSN") == []                                                                                      # затворена преди 30 дни (> 14) → без значка
assert tags(d_c, "Corn", "PPC") == ["OPEN✓"]                                                                               # отворена → само OPEN✓
ual_title = [m["title"] for t in cross(d_c, "RBOB Gasoline")["tickers"] for m in t["markers"]][0]
assert ual_title == f"Позицията е затворена на {iso(3)} — стоп, -1.0R; не е отворена."
d_d = day(RAW, open_pos=[{"ticker": "UAL", "entry_date": iso(0)}], closed=closed)
assert tags(d_d, "RBOB Gasoline", "UAL") == ["OPEN✓"]
print("  ✓ СИНТЕТИЧНО: затворена преди 3 дни → CLOSED (дата, изход, R, 'не е отворена'); преди 30 дни → без значка; отворена → само OPEN✓ (дори при по-ранно затваряне)")

print()
print("── без регенерация и в брифа ──")
assert calls["ai"] == 0
print("  ✓ през всички проверки по-горе моделът не е викан нито веднъж (evaluate_cot_theses няма достъп до него; отхвърляне = dropped_tickers, не нов отговор)")
LOOKUP_OVERRIDE["PPC"] = {"name": "PPC", "verified": False, "quote_type": None, "category": None, "long_name": None, "sector": None, "industry": None}
brief = json.loads(json.dumps(BRIEF)); brief["cot"] = list(day(RAW, open_pos=opened, closed=closed).values())
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2 = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        page = htmllib.unescape(render.render_dashboard(brief))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2
assert "Изключени: PPC — няма име в Yahoo (вероятно делистнат или преименуван)." in page and "CLOSED" in page and "OPEN✓" in page
print("  ✓ dashboard-ът показва 'Изключени: PPC — няма име в Yahoo…' и значките CLOSED/OPEN✓")
print()
print("Всички тестове минаха.")
