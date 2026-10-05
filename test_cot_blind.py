"""
Пакет 3 · т.б (2026-10-05): COT тезите се генерират "сляпо" — промптът не съдържа дневния скрийнър, отворените позиции, пазарния режим и
контекст от други batch-ове; редът, който канеше позициите към cross тезите, е махнат. Значките "в скрийнъра" (SCR✓) и "отворена позиция"
(OPEN✓) ги слага кодът всеки ден при показване.

РЕАЛНО: 18-те COT екстремума и реалните стари AI cross отговори от брифа на 02.10.2026 (tests/fixtures), реалният скрийнър на същия ден
(Action ∪ Watchlist), реалните имена на тикърите от проверката през Yahoo (05.10.2026). СИНТЕТИЧНО: подменените _call_claude и
_verified_company_name, "отворените позиции" (FCX от 22.09 и VLO от 12.08 — имената са взети от реалния случай RBOB/VLO от 15.09, но позициите
в теста са зададени от теста), другият скрийнър/режим, механизмите с типове 7/8/10 (формата идва със следващата точка).
Пускане: python test_cot_blind.py
"""
import sys, json, pathlib, io, contextlib, inspect, html as htmllib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import ai_brief, cot_theses as ct, render

FIX = ROOT / "tests" / "fixtures"
BRIEF = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
CHK = json.loads((FIX / "cot_direct_tickers_2026-10-05.json").read_text(encoding="utf-8"))["checked"]
EXTREMES = [{k: c[k] for k in ("market", "category", "net_position", "percentile", "direction", "as_of", "weeks_of_history", "history")} for c in BRIEF["cot"]]
REAL_SCREENER = [{"ticker": a["ticker"], "sector": a.get("sector"), "industry": a.get("industry")} for a in BRIEF["action"] + BRIEF["watchlist"]]
assert REAL_SCREENER and len(EXTREMES) == 18

company = {t: r["name"] for t, r in CHK.items() if r["name"]}
for c in BRIEF["cot"]:
    for k in ("direct_thesis", "cross_sector_thesis"):
        for t in (c.get(k) or {}).get("tickers") or []:
            company.setdefault(t["ticker"], t["company"])
ai_brief._verified_company_name = lambda t: {"name": company.get(t, t), "verified": t in company, "quote_type": (CHK.get(t) or {}).get("quote_type"),
                                              "category": (CHK.get(t) or {}).get("category"), "long_name": company.get(t), "sector": None, "industry": None}
config.COT_BATCH_SIZE = 100
prompts = []
def fake_claude(system, user, max_tokens=0):
    prompts.append(user)
    rows = [{"market": c["market"], "assumed_move": "up" if c["direction"] == "extreme_short" else "down",
             "cross_sector_thesis": c.get("cross_sector_thesis")} for c in BRIEF["cot"]]
    return json.dumps({"theses": rows}, ensure_ascii=False)
ai_brief._call_claude = fake_claude


def run(screener, positions):
    with contextlib.redirect_stdout(io.StringIO()):
        return ai_brief.cot_theses(EXTREMES, screener, positions)


print("── промптът е сляп ──")
assert list(inspect.signature(ai_brief.cot_theses).parameters) == ["extremes", "screener_universe", "open_positions"]      # без режим
POS_A = [{"ticker": "VLO", "company": "Valero Energy Corporation", "entry_date": "2026-08-12"}, {"ticker": "FCX", "company": "Freeport-McMoRan Inc.", "entry_date": "2026-09-22"}]
out_a = run(REAL_SCREENER, POS_A)
out_b = run([{"ticker": "ZZZZ", "sector": "x", "industry": "y"}], [])
out_c = run([], [{"ticker": "SCCO", "company": "Southern Copper", "entry_date": "2026-09-01"}])
assert len(prompts) == 3 and prompts[0] == prompts[1] == prompts[2]                                              # същият промпт при различен скрийнър/позиции
u = prompts[0]
for forbidden in ("ТЕКУЩ CANSLIM СКРИЙНЪР", "ОТВОРЕНИ TRACK RECORD", "Пазарен режим", "ВЕЧЕ ХАРАКТЕРИЗИРАНИ", "ZZZZ", "Valero", "предложи я нормално",
                  "по-рано характеризираните"):
    assert forbidden not in u, forbidden
for ticker in [x["ticker"] for x in REAL_SCREENER][:6]:
    assert f'"{ticker}"' not in u or ticker in {t for v in config.COT_DIRECT_TICKERS.values() for t in [e["ticker"] for e in v["tickers"]]}, ticker   # скрийнърът не изтича в промпта
print(f"  ✓ три извиквания с РАЗЛИЧЕН скрийнър (реален от 02.10 / друг / празен) и различни позиции дават ПОСЛЕДОВАТЕЛНО ИДЕНТИЧЕН промпт ({len(u)} знака);")
print("    няма скрийнър, позиции, режим, контекст от други batch-ове; сигнатурата няма режим")
src_text = (ROOT / "src" / "ai_brief.py").read_text(encoding="utf-8")
assert "positions_block" not in src_text and "prior_block" not in src_text and "_record_ticker_context" not in src_text
assert "Ако позицията пасва на тезата" not in src_text
print("  ✓ редът 'ако позицията пасва на тезата, предложи я нормално' (positions_block), prior_context блокът и _record_ticker_context ги няма в кода")

print()
print("── тезите са еднакви; различават се САМО значките ──")
def strip(o):
    """тезите без показните полета, слагани от кода според деня: значки и outside_screener"""
    def sub(th):
        th = {k: v for k, v in (th or {}).items() if k != "outside_screener"}
        th["tickers"] = [{k: v for k, v in t.items() if k != "markers"} for t in th.get("tickers") or []]
        return th
    return json.dumps([{**c, "direct_thesis": sub(c["direct_thesis"]), "cross_sector_thesis": sub(c["cross_sector_thesis"])} for c in o],
                      sort_keys=True, ensure_ascii=False, default=str)
assert strip(out_a) == strip(out_b) == strip(out_c)
print("  ✓ при три различни скрийнъра/позиции тезите са идентични без показните полета (значки, outside_screener)")

print()
print("── значките ги слага кодът ──")
tick = lambda out, market, kind: {t["ticker"]: [m["tag"] for m in t["markers"]] for t in out_by(out)[market][kind]["tickers"]}
out_by = lambda out: {c["market"]: c for c in out}
copper = tick(out_a, "Copper", "direct_thesis")
assert copper == {"CPER": [], "FCX": ["OPEN✓"], "SCCO": []}                                                       # FCX — отворена позиция; нито един не е в реалния скрийнър
real_tickers = {x["ticker"] for x in REAL_SCREENER}
inscr = {t["ticker"] for c in out_a for k in ("direct_thesis", "cross_sector_thesis") for t in (c.get(k) or {}).get("tickers") or [] if t["ticker"] in real_tickers}
assert inscr, "няма тикър от реалния скрийнър в тезите на 02.10"
for c in out_a:
    for k in ("direct_thesis", "cross_sector_thesis"):
        for t in (c.get(k) or {}).get("tickers") or []:
            assert ("SCR✓" in [m["tag"] for m in t["markers"]]) == (t["ticker"] in real_tickers), (c["market"], t["ticker"])
rbob = tick(out_a, "RBOB Gasoline", "direct_thesis")
assert rbob["VLO"] == ["OPEN✓"] or rbob["VLO"] == ["SCR✓", "OPEN✓"]
assert all("OPEN✓" not in v for v in tick(out_b, "RBOB Gasoline", "direct_thesis").values())                       # без позиция — няма значка
print(f"  ✓ SCR✓ точно за тикърите от РЕАЛНИЯ скрийнър на 02.10 ({sorted(inscr)}); OPEN✓ за FCX (Copper, директен) и VLO (RBOB) при зададени позиции;")
print("    без позиции нито един OPEN✓")

# правилото за механизми (подготовка за следващата точка): 7, 8, 10 и other никога не са пряк механизъм
b1 = ct.ticker_badges({"ticker": "XYZ", "mechanisms": [{"type": "index_beta"}]}, set(), {"XYZ": "2026-09-01"})
b2 = ct.ticker_badges({"ticker": "XYZ", "mechanisms": [{"type": "risk_off_hedge"}, {"type": "other"}]}, set(), {"XYZ": "2026-09-01"})
b3 = ct.ticker_badges({"ticker": "XYZ", "mechanisms": [{"type": "consumer_wallet"}, {"type": "input_cost"}]}, set(), {"XYZ": "2026-09-01"})
b4 = ct.ticker_badges({"ticker": "XYZ", "mechanisms": [{"type": "other"}]}, {"XYZ"}, {"XYZ": None})
assert b1 == [] and b2 == [] and [m["tag"] for m in b3] == ["OPEN✓"] and [m["tag"] for m in b4] == ["SCR✓"]
assert "Отворена позиция от 2026-09-01" in b3[0]["title"]
print("  ✓ СИНТЕТИЧНО: тикър само с механизми 7/8/10/other → без OPEN✓ (но SCR✓ се слага); с поне един пряк механизъм → OPEN✓")

print()
print("── в страницата ──")
brief = json.loads(json.dumps(BRIEF)); brief["cot"] = out_a
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2 = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        page = htmllib.unescape(render.render_dashboard(brief))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2
assert "SCR✓" in page and "OPEN✓" in page and "Отворена позиция от 2026-09-22 — слага се от кода." in page
print("  ✓ dashboard-ът показва SCR✓/OPEN✓ при тикърите в COT тезите (hover/клик, като при другите значки)")
print()
print("Всички тестове минаха.")
