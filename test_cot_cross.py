"""
Пакет 3 · т.г (2026-10-05): cross-sector COT тези — моделът връща за всеки тикър 1–2 механизма {type, quote} от затворен списък (10 типа +
"other"); ефектът (печели/губи) се изчислява от кода по таблицата (тип × вид на пазара) × очакваното движение на инструмента; два механизма
с противоположен знак → "mixed" → тикърът се изключва (записва се с причина); типове 7, 8, 10 и "other" никога не са пряк механизъм
("other" не показва посока); изречението с посоката е шаблон от кода; глагол с посока в прозата, противоречащ на ефекта → само лог.

РЕАЛНО: 18-те COT екстремума от брифа на 02.10.2026 с реалните посоки; реалните стари AI cross ефекти за 12-те (пазар, тикър) двойки;
реалната стара проза (като quote) за теста на лога. СИНТЕТИЧНО: отговорът на модела в новия формат (tests/fixtures/cot_model_answers_2026-10-02.json —
типовете и quote са зададени от теста по икономиката от старата реална проза), всички гранични случаи на схемата, mixed, "other",
подменените _call_claude и _verified_company_name.
Пускане: python test_cot_cross.py
"""
import sys, json, pathlib, io, contextlib, tempfile as _tf, html as htmllib, tempfile, itertools
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from tests import helpers_cot

import config
from src import cot_theses as ct, ai_brief, render

_CACHE_DIR = _tf.TemporaryDirectory(prefix="mb_cotcache_")
_cache_n = [0]
def fresh_cache():
    """нов (празен) файл за кеша на тезите във временна директория — реалният data/cot_theses_cache.json не се пипа"""
    _cache_n[0] += 1
    return pathlib.Path(_CACHE_DIR.name) / f"cache_{_cache_n[0]}.json"


FIX = ROOT / "tests" / "fixtures"
BRIEF = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
ANS = json.loads((FIX / "cot_model_answers_2026-10-02.json").read_text(encoding="utf-8"))["markets"]
ROWS = {c["market"]: c for c in BRIEF["cot"]}
move_of = lambda m: ai_brief._instrument_move(ROWS[m])
UP = {"move": "up", "move_text": "цената на X НАГОРЕ"}
DOWN = {"move": "down", "move_text": "цената на X НАДОЛУ"}


def ev(market, tickers, move=None, exclude=frozenset()):
    logs = []
    return ct.evaluate_cross(tickers, market, move or move_of(market), exclude, log=logs.append), logs


def tk(ticker, *mechs, company=None):
    return {"ticker": ticker, "company": company or ticker, "mechanisms": [{"type": t, "quote": q} for t, q in mechs]}


print("── схема: затворен списък, quote, валидност по вид на пазара (СИНТЕТИЧНО) ──")
Q = "описание на механизма"
th, _ = ev("Cocoa", [tk("HSY", ("input_cost", Q))])
assert [t["ticker"] for t in th["tickers"]] == ["HSY"] and th["dropped_tickers"] is None
bad = {"измислен тип": tk("A1", ("magic", Q)), "без quote": tk("A2", ("input_cost", "  ")), "без механизми": {"ticker": "A3", "company": "A3"},
       "механизмите не са списък": {"ticker": "A4", "mechanisms": "input_cost"}, "input_cost за облигации": tk("A5", ("input_cost", Q)),
       "rate_asset_yield за стока": tk("A6", ("rate_asset_yield", Q))}
for label, t in bad.items():
    kind_market = "30-Year Treasury Bond" if label == "input_cost за облигации" else "Cocoa"
    th, _ = ev(kind_market, [t])
    assert not th["tickers"] and th["dropped_tickers"][0]["code"] == "schema", (label, th)
    assert "empty_reason" in th and t["ticker"] in th["empty_reason"]
th, _ = ev("30-Year Treasury Bond", [tk("A5", ("input_cost", Q))])
assert th["dropped_tickers"][0]["reason"] == "невалидна схема: типът 'input_cost' не важи за пазар от вид 'rate'"
th, _ = ev("Cocoa", [tk("A7", ("input_cost", Q), ("input_cost", "друго"), ("consumer_wallet", Q), ("substitute", Q))])   # дубликат тип се сгъва; най-много 2 механизма
assert [m["type"] for m in th["tickers"][0]["mechanisms"]] == ["input_cost", "consumer_wallet"]
th, _ = ev("Cocoa", [tk("A1", ("input_cost", Q)), tk("A1", ("output_price", Q)), tk("A8", ("input_cost", Q)), tk("A9", ("input_cost", Q)), tk("A10", ("input_cost", Q)), tk("A11", ("input_cost", Q))])
assert [t["ticker"] for t in th["tickers"]] == ["A1", "A8", "A9"]                                                      # дубликат тикър се пропуска; най-много 3
th, _ = ev("Cocoa", [tk("hsy ", ("INPUT_COST", Q))])
assert th["tickers"][0]["ticker"] == "HSY" and th["tickers"][0]["mechanisms"][0]["type"] == "input_cost"             # нормализация на регистър/интервали
long_q = tk("LQ", ("input_cost", "а" * 500))
assert len(ev("Cocoa", [long_q])[0]["tickers"][0]["mechanisms"][0]["quote"]) == config.COT_QUOTE_MAX_CHARS
print("  ✓ невалиден тип / празен quote / без механизми / тип, който не важи за вида на пазара → изключен със 'schema' и причина; дубликати, лимити (2 механизма, 3 тикъра),")
print("    нормализация на регистъра и дължината на quote; причината за празната теза се сглобява от кода")

print()
print("── знак по таблицата (тип × вид × движение) — ЗАМРАЗЕНА таблица ──")
EXPECT = {   # (тип, вид) → знак при цена↑
    ("input_cost", "commodity"): -1, ("output_price", "commodity"): 1, ("substitute", "commodity"): 1, ("consumer_wallet", "commodity"): -1,
    ("fx_revenue_translation", "fx_foreign"): 1, ("fx_revenue_translation", "fx_usd"): -1, ("fx_cost_local", "fx_foreign"): -1, ("fx_cost_local", "fx_usd"): 1,
    ("rate_asset_yield", "rate"): -1, ("rate_duration_valuation", "rate"): 1,
    ("index_beta", "equity_index"): 1, ("index_beta", "volatility"): -1, ("index_beta", "crypto"): 1,
    ("risk_off_hedge", "equity_index"): -1, ("risk_off_hedge", "volatility"): 1, ("risk_off_hedge", "crypto"): -1}
got = {(t, k): s for t, spec in config.COT_MECHANISM_SIGN.items() for k, s in spec["sign"].items()}
assert got == EXPECT, set(got.items()) ^ set(EXPECT.items())
KIND_MARKET = {"commodity": "Cocoa", "fx_foreign": "Euro FX", "fx_usd": "US Dollar Index", "rate": "5-Year Treasury Note", "equity_index": "Nasdaq-100",
               "volatility": "VIX Futures", "crypto": "Bitcoin Futures (CME)"}
n = 0
for (typ, kind), sign in EXPECT.items():
    for mv in (UP, DOWN):
        row = tk("ZZ", (typ, Q))
        if typ in config.COT_FX_TYPES:                                                  # 08.10: валутният механизъм носи страната на експозицията (типът му се извежда от нея)
            row["mechanisms"][0].update(exposure_side={"fx_revenue_translation": "foreign_revenue", "fx_cost_local": "foreign_cost"}[typ],
                                        currencies=[config.COT_FX_MARKET_CURRENCY.get(KIND_MARKET[kind], "EUR")])
        th, _ = ev(KIND_MARKET[kind], [row], mv)
        want = "gains" if sign * (1 if mv["move"] == "up" else -1) > 0 else "loses"
        assert th["tickers"][0]["effect"] == want, (typ, kind, mv["move"])
        n += 1
print(f"  ✓ {len(EXPECT)} двойки (тип, вид) × 2 движения = {n} ефекта съвпадат със замразената таблица; всичко извън нея е невалидна схема")

print()
print("── шаблонът с посоката (кодът) и 'mixed' ──")
th, _ = ev("Cocoa", [tk("HSY", ("input_cost", "купува какао като основна суровина"))])                                  # РЕАЛНА посока: Cocoa е extreme_short → цена НАГОРЕ
assert ROWS["Cocoa"]["direction"] == "extreme_short"
t = th["tickers"][0]
assert t["effect"] == "loses" and t["direction"] == "bearish"
assert t["sentence"] == "При цената на Cocoa НАГОРЕ HSY ГУБИ (механизъм: разход за суровина)." and t["quote"] == "купува какао като основна суровина"
th, _ = ev("Corn", [tk("TSN", ("input_cost", Q), ("consumer_wallet", Q))])                                              # два механизма със СЪЩИЯ знак → не е mixed
assert th["tickers"][0]["sentence"] == "При цената на Corn НАДОЛУ TSN ПЕЧЕЛИ (механизъм: разход за суровина и потребителски бюджет)."
th, _ = ev("Corn", [tk("ADM", ("input_cost", Q), ("output_price", Q)), tk("TSN", ("input_cost", Q))])
assert [t["ticker"] for t in th["tickers"]] == ["TSN"]
d = th["dropped_tickers"]
assert d == [{"ticker": "ADM", "code": "mixed", "reason": "mixed: противоположен ефект — цена на продукта (+) срещу разход за суровина (−)"}]
th, _ = ev("5-Year Treasury Note", [tk("BNK", ("rate_asset_yield", Q), ("rate_duration_valuation", Q))])
assert not th["tickers"] and th["dropped_tickers"][0]["code"] == "mixed" and "всички предложени тикъри бяха изключени" in th["empty_reason"]
print("  ✓ изречението е шаблон: 'При цената на Cocoa НАГОРЕ HSY ГУБИ (механизъм: разход за суровина).' (РЕАЛНА посока на Cocoa от 02.10);")
print("    ADM с input_cost + output_price → 'mixed' и се изключва с причина; два механизма с еднакъв знак не са mixed; празната теза получава причина от кода")

print()
print("── типове 7, 8, 10 и 'other': никога пряк механизъм; 'other' без посока ──")
assert [t for t, s in config.COT_MECHANISM_SIGN.items() if not s["direct"]] == ["index_beta", "risk_off_hedge", "consumer_wallet", "other"]
th, _ = ev("E-mini Russell 2000", [tk("IBKR", ("index_beta", Q)), tk("GLD2", ("risk_off_hedge", Q)), tk("OTH", ("other", Q))])
th2, _ = ev("E-mini Russell 2000", [tk("MIX", ("other", Q), ("index_beta", Q))])
by = {t["ticker"]: t for t in th["tickers"] + th2["tickers"]}
assert [by[k]["direct_mechanism"] for k in ("IBKR", "GLD2", "OTH", "MIX")] == [False, False, False, False]
assert (by["IBKR"]["effect"], by["GLD2"]["effect"]) == ("gains", "loses")                                          # Russell е extreme_short → цена↑
assert by["OTH"]["effect"] is None and by["OTH"]["direction"] is None and by["OTH"]["sentence"] == "Механизъм: друг механизъм — без изчислена посока."
assert by["MIX"]["effect"] == "gains" and by["MIX"]["direct_mechanism"] is False                                    # "other" не пречи на другия механизъм и не е пряк
th, _ = ev("Cocoa", [tk("WLT", ("consumer_wallet", Q)), tk("DIR", ("consumer_wallet", Q), ("input_cost", Q))])
assert [t["direct_mechanism"] for t in th["tickers"]] == [False, True]                                              # пряк е, ако поне един механизъм е пряк
# значките: отворена позиция не влиза с механизми 7/8/10/other
open_pos = {"IBKR": "2026-09-01", "OTH": "2026-09-01", "WLT": "2026-09-01", "DIR": "2026-09-01"}
assert [m["tag"] for m in ct.ticker_badges(by["IBKR"], set(), open_pos)] == [] and [m["tag"] for m in ct.ticker_badges(by["OTH"], set(), open_pos)] == []
assert [m["tag"] for m in ct.ticker_badges(th["tickers"][0], set(), open_pos)] == [] and [m["tag"] for m in ct.ticker_badges(th["tickers"][1], set(), open_pos)] == ["OPEN✓"]
print("  ✓ index_beta, risk_off_hedge, consumer_wallet и 'other' не са пряк механизъм → без OPEN✓; 'other' няма ефект/посока/изречение с посока;")
print("    'other' до друг механизъм не го прави пряк и не пречи на знака; пряк е само ако поне един механизъм е от пряк тип")

print()
print("── РЕАЛНО сравнение със стария AI (12 двойки от 02.10; типовете са зададени от теста) ──")
agree = disagree = 0
diffs, dropped_real = [], []
for m, tickers in ANS.items():
    old = {t["ticker"]: t.get("effect") for t in (ROWS[m].get("cross_sector_thesis") or {}).get("tickers") or []}
    th, _ = ev(m, tickers)
    for t in th["tickers"]:
        if t["effect"] == old[t["ticker"]]:
            agree += 1
        else:
            disagree += 1; diffs.append((m, t["ticker"], old[t["ticker"]], t["effect"]))
    dropped_real += [(m, d["ticker"], d["code"]) for d in th["dropped_tickers"] or []]
assert (agree, disagree) == (11, 1) and diffs == [("Copper", "AMD", "loses", "gains")]
assert dropped_real == [("Swiss Franc", "ALL", "schema"), ("Swiss Franc", "AIZ", "schema")]
amd_prose = ROWS["Copper"]["cross_sector_thesis"]["reasoning"]
assert "по-ниска цена на медта намалява" in amd_prose.lower() or "по-ниска цена на медта" in amd_prose
print("  ✓ 11 от 12 съвпадат със стария реален ефект; единственото разминаване: Copper/AMD — старото AI поле казваше 'loses', докато собствената му проза")
print("    казваше, че по-ниската цена на медта намалява разходите (= печели); кодът дава 'gains' (input_cost, цена↓)")
print("  ✓ Swiss Franc ALL/AIZ ('защитно позициониране' = risk_off_hedge) → невалидна схема за вид fx_foreign: изключени (в старата теза бяха 'gains' без механизъм)")

print()
print("── лог (без действие) за глаголи с посока в прозата ──")
th, logs = ev("Lean Hogs", [tk("TSN", ("input_cost", ROWS["Lean Hogs"]["cross_sector_thesis"]["reasoning"]))])         # РЕАЛНАТА стара проза като quote
assert th["tickers"][0]["effect"] == "loses" and logs == ["TSN: прозата казва 'печел', а кодът изчислява loses (само лог)"]
norm = " ".join(ROWS["Lean Hogs"]["cross_sector_thesis"]["reasoning"].split())
assert len(norm) > config.COT_QUOTE_MAX_CHARS and th["tickers"][0]["quote"] == norm[:config.COT_QUOTE_MAX_CHARS].rstrip()   # прозата се показва, подрязана до лимита
th, logs = ev("Cocoa", [tk("HSY", ("input_cost", "губи от поскъпването"))])                                              # СИНТЕТИЧНО: съгласие → без лог
assert logs == []
th, logs = ev("Cocoa", [tk("HSY", ("input_cost", "печели от по-висока цена"))])
assert logs and th["tickers"][0]["effect"] == "loses"                                                                   # логът не променя ефекта
assert ct.prose_direction_conflict("нещо", None) is None and ct.prose_direction_conflict("печели", None) is None       # без ефект няма какво да противоречи
print("  ✓ РЕАЛНАТА проза на Lean Hogs/TSN съдържа 'печел…', а кодът дава 'loses' → ред в лога; прозата и ефектът не се променят; при съгласие няма лог")

print()
print("── през ai_brief.cot_theses (СИНТЕТИЧЕН отговор, РЕАЛНИ екстремуми) ──")
CHK = json.loads((FIX / "cot_direct_tickers_2026-10-05.json").read_text(encoding="utf-8"))["checked"]
company = {t: r["name"] for t, r in CHK.items() if r["name"]}
for c in BRIEF["cot"]:
    for k in ("direct_thesis", "cross_sector_thesis"):
        for t in (c.get(k) or {}).get("tickers") or []:
            company.setdefault(t["ticker"], t["company"])
ai_brief._verified_company_name = lambda t: {"name": company.get(t, t), "verified": t in company, "quote_type": (CHK.get(t) or {}).get("quote_type"),
                                              "category": (CHK.get(t) or {}).get("category"), "long_name": company.get(t), "sector": None, "industry": None}
helpers_cot.neutral_identity(ai_brief)                                                                                          # проверките за идентичност имат свой тест (test_cot_claims.py)
config.COT_BATCH_SIZE = 100
seen = {}
extra = {"Corn": [tk("ADM", ("input_cost", Q), ("output_price", Q), company="Archer-Daniels-Midland Company")]}
def fake_claude(system, user, max_tokens=0):
    seen["user"], seen["system"] = user, system
    return json.dumps({"theses": [{"market": m, "tickers": v + extra.get(m, [])} for m, v in ANS.items()]}, ensure_ascii=False)
ai_brief._call_claude = fake_claude
EXTREMES = [{k: c[k] for k in ("market", "category", "net_position", "percentile", "direction", "as_of", "weeks_of_history", "history")} for c in BRIEF["cot"]]
EXTREMES.append({**EXTREMES[0], "market": "XRP", "category": "financial", "weeks_of_history": 53, "direction": "extreme_long"})
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out = ai_brief.cot_theses(EXTREMES, [], None, cache_path=fresh_cache())
by = {c["market"]: c for c in out}
corn = by["Corn"]["cross_sector_thesis"]
assert [t["ticker"] for t in corn["tickers"]] == ["TSN", "PPC"] and corn["dropped_tickers"] == [{"ticker": "ADM", "code": "mixed", "reason": "mixed: противоположен ефект — цена на продукта (+) срещу разход за суровина (−)"}]
assert ai_brief.COT_DIAG["mixed"] == ["Corn/ADM"] and any("Corn/ADM" in x for x in ai_brief.COT_DIAG["dropped"])
swiss = by["Swiss Franc"]["cross_sector_thesis"]
assert swiss["tickers"] == [] and swiss["empty_reason"].startswith("всички предложени тикъри бяха изключени при проверката (2): ALL, AIZ — невалидна схема")                                                 # 08.10: еднаквата причина е на един ред
assert [x["ticker"] for x in swiss["dropped_tickers"]] == ["ALL", "AIZ"]
assert by["XRP"]["history_note"] == "История само 53 седмици (под стандартните ~156) — percentile-ът тук е по-малко статистически сигурен от обичайното." and "history_note" not in by["Cocoa"]
t30 = by["30-Year Treasury Bond"]["cross_sector_thesis"]["tickers"][0]
assert (t30["ticker"], t30["effect"], t30["sentence"]) == ("JPM", "gains", "При цената на 30-Year Treasury Bond НАДОЛУ (= доходността нагоре) JPM ПЕЧЕЛИ (механизъм: доходност на активите).")
assert "Lean Hogs/TSN" not in str(ai_brief.COT_DIAG.get("prose_direction", []))                                           # синтетичният quote е без посока
print("  ✓ Corn: ADM (input_cost + output_price) → mixed, изключен с причина и в cot_diag; Swiss Franc: празна теза с причина от кода (2 изключени по схема);")
print("    30Y: 'При цената на 30-Year Treasury Bond НАДОЛУ (= доходността нагоре) JPM ПЕЧЕЛИ (механизъм: доходност на активите).'; история 53 седмици → бележка от кода")

print()
print("── промптът ──")
u, sysmsg = seen["user"], seen["system"]
for typ, spec in config.COT_MECHANISM_SIGN.items():
    assert f'"{typ}"' in u and spec["text"] in u, typ                                   # всичките 11 типа с дефинициите им са в промпта
for kind in config.COT_KIND_TEXT:
    assert kind in u
assert "Валиден за: commodity" in u and "Валиден за: rate" in u and "Валиден за: всички видове" in u
for forbidden in ("expected_move", "assumed_move", "weeks_of_history", "percentile", "net_position", '"direction"', "extreme_long", "extreme_short",
                  "contrarian", "Пазарен режим", "СКРИЙНЪР"):
    assert forbidden not in u, forbidden
assert "contrarian" not in sysmsg and "bearish обрат" not in sysmsg and "Не преценяваш посоката" in sysmsg
assert "БЕЗ посока" in u and "по таблица" in u
print("  ✓ промптът съдържа 11-те типа с дефинициите им и валидността по вид на пазара; няма посока, percentile, net_position, режим, скрийнър; системният текст не говори за contrarian посока")

print()
print("── в страницата ──")
brief = json.loads(json.dumps(BRIEF)); brief["cot"] = out
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2 = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        page = htmllib.unescape(render.render_dashboard(brief))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2
assert "При цената на Corn НАДОЛУ TSN ПЕЧЕЛИ (механизъм: разход за суровина)." in page
assert "Изключени: ADM — mixed: противоположен ефект — цена на продукта (+) срещу разход за суровина (−)." in page
assert "Няма cross-sector теза — всички предложени тикъри бяха изключени при проверката (2): ALL, AIZ — невалидна схема" in page
assert "История само 53 седмици" in page
print("  ✓ dashboard-ът показва изречението от кода и прозата на модела отделно, 'Изключени: ADM — mixed …', причината за празна cross теза и бележката за кратка история")
print()
print("Всички тестове минаха.")
