"""
Пакет 3 (2026-10-05) · т.г: в прозата на cross-sector механизмите няма твърдения за членство в индекс. Моделът не знае кой тикър в кой
индекс е; кодът маха механизъм, чийто quote твърди членство (Russell 2000, S&P 500, Nasdaq-100, Dow Jones, …), а тикър без друг механизъм
отпада с код "index_claim"; всяко махане се логва и отива в COT_DIAG["index_claims"].

РЕАЛНО: изреченията от брифа на 05.10.2026 (tests/fixtures/brief_2026-10-05.json) — "FTNT и ZBRA … концентрирана в Russell 2000 constituent
universe" (невярно) — и три реални изречения от по-стари брифове (30.07 UMBF/ONB, 11.08 ROKU/TWLO, 27.08 ROKU), както и две реални изречения
БЕЗ твърдение (25.08, 26.08 — "шортове в Nasdaq-100", "short позициониране в Nasdaq"), които първият вариант на регекса хващаше погрешно.
СИНТЕТИЧНО: механизмите на модела (типове index_beta/risk_off_hedge, валидни за equity_index), граничните изречения, подменените lookup и _call_claude.
Пускане: python test_cot_index_claims.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from tests import helpers_cot

import config
from src import ai_brief, cot_theses as ct

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
RUSSELL = next(c for c in B05["cot"] if c["market"] == "E-mini Russell 2000")
REAL_0510 = RUSSELL["cross_sector_thesis"]["reasoning"]
assert "Russell 2000 constituent universe" in REAL_0510 and [t["ticker"] for t in RUSSELL["cross_sector_thesis"]["tickers"]] == ["FTNT", "ZBRA"]

print("── откриване: РЕАЛНИ изречения ──")
REAL_CLAIMS = [
    ("05.10", "Fortinet и Zebra Technologies са от CANSLIM скрийнъра с реална бизнес зависимост от domestic US икономически условия — точно типа "
              "expозиция, концентрирана в Russell 2000 constituent universe — и директно се възползват от re-rating"),
    ("30.07", "Small cap банките и регионалните финансови са core Russell 2000 компоненти — UMBF и ONB са директно изложени към small cap динамиката."),
    ("11.08", "Nasdaq-100 компонентите и growth-ориентираните tech акции като ROKU и TWLO са директно свързани с индекса."),
    ("27.08", "ROKU от скрийнъра е в Communication Services/Entertainment — директно Nasdaq-100 компонент с висок beta."),
]
for day, s in REAL_CLAIMS:
    assert ct.index_claim(s), (day, s)
assert "Russell 2000 constituent universe" in ct.index_claim(REAL_CLAIMS[0][1])
REAL_OK = [
    ("25.08", "Покриването на шортове в Nasdaq-100 е индексно събитие — cross-sector ефектът е твърде разреден."),
    ("26.08", "Ако managed money покрива short позициите в Nasdaq-100, волатилността и оборотите скачат."),
    ("30.07", "При Offensive пазарен режим екстремното short позициониране в Nasdaq е особено значимо."),
]
for day, s in REAL_OK:
    assert ct.index_claim(s) is None, (day, s)
# цялата проза от cot в брифа на 05.10: точно едно изречение със съвпадение (само РЕАЛНОТО твърдение за Russell)
import re
hits = [s for c in B05["cot"] for k in ("direct_thesis", "cross_sector_thesis") for s in re.split(r"(?<=[.!?])\s+", (c.get(k) or {}).get("reasoning") or "")
        if ct.index_claim(s)]
assert len(hits) == 1 and "Russell 2000 constituent universe" in hits[0], hits
print("  ✓ четирите реални твърдения (05.10, 30.07, 11.08, 27.08) се хващат; трите реални изречения БЕЗ твърдение (25.08, 26.08, 30.07 'позициониране в Nasdaq') — не;")
print("    в цялата проза на cot от 05.10 съвпада само реалното 'Russell 2000 constituent universe'")

print()
print("── граници (СИНТЕТИЧНИ изречения) ──")
for s in ("TRV е част от S&P 500.", "Компанията влиза в Dow Jones Industrial Average.", "Акцията е member of the Russell 2000 index.",
          "Тикърът е включен в Nasdaq-100.", "Принадлежи към Russell 1000.", "Това е S&P 500 компонент.", "Russell 2000 members включват банки.",
          "Wilshire 5000 constituents"):
    assert ct.index_claim(s), s
for s in ("Фирмата купува природен газ като суровина за азотни торове.", "Секторът е в downtrend и bounce може да се изчерпи.",       # "downtrend" ≠ "Dow"
          "Бенчмаркът за малките компании е Russell 2000, но тикърът има собствена бизнес логика.",                                      # споменаване, не членство
          "Revenue exposure към US small cap банки.", "Ликвидността при S&P 500 фючърсите е висока.", ""):
    assert ct.index_claim(s) is None, s
assert ct.index_claim(None) is None
print("  ✓ 8 форми на твърдение (част от / влиза в / member of / включен в / принадлежи към / компонент / members / constituents) се хващат;")
print("    споменаване на индекс без членство, 'downtrend', празен текст и None — не")

print()
print("── parse_mechanisms ──")
claims: list = []
m, err = ct.parse_mechanisms([{"type": "index_beta", "quote": "Част от Russell 2000 и с висока бета."},
                              {"type": "risk_off_hedge", "quote": "Продава защитни продукти при стрес."}], "equity_index", claims)
assert err is None and [x["type"] for x in m] == ["risk_off_hedge"] and claims == ["Част от Russell 2000"]
m, err = ct.parse_mechanisms([{"type": "index_beta", "quote": "Част от Russell 2000."}], "equity_index", claims := [])
assert m == [] and err.startswith("твърдение за членство в индекс") and claims == ["Част от Russell 2000"]
m, err = ct.parse_mechanisms([{"type": "index_beta", "quote": "Част от Russell 2000."}], "equity_index")                   # без списък за фрагментите — пак работи
assert m == [] and err.startswith("твърдение за членство")
m, err = ct.parse_mechanisms([{"type": "index_beta", "quote": "Малка компания с висока бета към малките капитализации."}], "equity_index", claims := [])
assert err is None and claims == [] and len(m) == 1
m, err = ct.parse_mechanisms([{"type": "index_beta", "quote": "Част от Russell 2000."}, {"type": "няма_такъв", "quote": "x"}], "equity_index")
assert m == [] and err.startswith("невалидна схема")                                                                          # схемата има предимство пред кода на claim
print("  ✓ механизъм с твърдение се маха, другият остава; единствен механизъм → грешка 'твърдение за членство в индекс'; фрагментът се връща в списъка; схема > claim")

print()
print("── evaluate_cross: РЕАЛНИЯТ случай 05.10 (E-mini Russell 2000, extreme_short, цена нагоре) ──")
ai_brief._verified_company_name = lambda t: {"name": t, "verified": True, "quote_type": "EQUITY", "category": None, "long_name": t, "sector": None, "industry": None}
helpers_cot.neutral_identity(ai_brief)                                                                                          # проверките за идентичност имат свой тест (test_cot_claims.py)
ai_brief._call_claude = lambda *a, **k: (_ for _ in ()).throw(AssertionError("моделът не бива да се вика"))
keys = ("market", "category", "net_position", "percentile", "direction", "as_of", "weeks_of_history", "history")
ext = {k: RUSSELL[k] for k in keys}
T = lambda t, *mechs: {"ticker": t, "company": t, "mechanisms": [{"type": a, "quote": q} for a, q in mechs]}
RAW = {"E-mini Russell 2000": [
    T("FTNT", ("index_beta", "Концентрирана експозиция в Russell 2000 constituent universe.")),                              # единствен механизъм с твърдение → отпада
    T("ZBRA", ("index_beta", "Компонент на Russell 2000 със среден капитализиран бизнес."), ("risk_off_hedge", "Продава защитни системи при стрес.")),   # единият се маха, другият остава
    T("JPM", ("index_beta", "Голяма банка с чувствителност към кредитния цикъл на малките компании."))]}                      # без твърдение → без промяна


def run(raw):
    with contextlib.redirect_stdout(io.StringIO()):
        out = ai_brief.evaluate_cot_theses([ext], raw, [], [], [])
    return out[0]["cross_sector_thesis"]


cross = run(RAW)
assert [t["ticker"] for t in cross["tickers"]] == ["ZBRA", "JPM"], cross["tickers"]
zbra = cross["tickers"][0]
assert [m["type"] for m in zbra["mechanisms"]] == ["risk_off_hedge"] and "Russell" not in zbra["quote"] and ct.index_claim(zbra["sentence"]) is None   # изречението на кода носи името на инструмента, не твърдение
assert cross["dropped_tickers"] == [{"ticker": "FTNT", "code": "index_claim",
                                     "reason": "твърдение за членство в индекс (моделът не знае членството) — механизмът е махнат"}], cross["dropped_tickers"]
assert ai_brief.COT_DIAG["index_claims"] == ["E-mini Russell 2000/FTNT", "E-mini Russell 2000/ZBRA"], ai_brief.COT_DIAG
assert all(ct.index_claim(t["quote"]) is None for t in cross["tickers"])
print("  ✓ FTNT (единственият механизъм = твърдение) отпада с код index_claim; ZBRA остава само с втория механизъм; JPM не се пипа;")
print("    COT_DIAG['index_claims'] = [Russell 2000/FTNT, Russell 2000/ZBRA]; в quote на показаните тикъри няма 'Russell'")

logs = []
ct.evaluate_cross(RAW["E-mini Russell 2000"], "E-mini Russell 2000", ai_brief._instrument_move(ext), log=logs.append)
assert logs == ['FTNT: твърдение за членство в индекс — "Russell 2000 constituent universe" → механизмът е махнат',
                'ZBRA: твърдение за членство в индекс — "Компонент на Russell 2000" → механизмът е махнат'], logs
print("  ✓ лог на махането: " + logs[0])

print()
print("── кеш/версия: правилото е в промпта ──")
prompt = ai_brief._build_cot_user_prompt([])
assert "БЕЗ твърдения за членство в индекс" in prompt and "Russell 2000" in prompt
assert ai_brief.cot_prompt_version().startswith("v")
print("  ✓ промптът съдържа правилото (смяната му сменя cot_prompt_version → кешът се обезсилва; живо кеш още няма)")
print()
print("Всички тестове минаха.")
