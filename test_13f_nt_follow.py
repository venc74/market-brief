"""
13F-NT → родител (08.10.2026): Pershing Square Capital Management (CIK 1336528) на 14.08.2026 подаде 13F-NT ("холдингите на този мениджър вече са включени в доклада на публичния му родител"), а Q2 е във
13F-HR на PERSHING SQUARE INC. (CIK 2026053, преди Pershing Square Holdco, L.P.). Кодът четеше само 13F-HR на конфигурирания CIK → "закъснява" (последен 13F от 15.05) вместо реалните позиции.
Поправка: dataroma._nt_successor() чете 13F-NT, по-нов от последния 13F-HR, взема CIK-а от otherManagers и ползва най-новия 13F-HR на родителя; предишното тримесечие остава от стария CIK (сравнение по CUSIP).

РЕАЛНО (правило 9, свалени от sec.gov на 08.10.2026 през браузъра, байт по байт — размерите съвпадат с листинга на SEC): 13F-NT primary_doc.xml (2492 B), infotable.xml на Q2 на родителя (8054 B), infotable.xml на Q1 на
стария CIK (5520 B) и submissions/index.json отговорите (tests/fixtures/sec_submissions_pershing_2026-10-08.json — първите 8 записа от recent[], форматът е същият).
Трети преглед (16.10): РЕАЛНАТА пълна извадка на 13F редовете от submissions (tests/fixtures/sec_submissions_13f_2026-10-16.json) показва, че родителят е подал 13F-HR и за Q1 2026
(0001172661-26-002339, 15.05 — същия ден като стария CIK; само HHH 9 000 000 — tests/fixtures/sec_13f_infotable_2026053_0001172661-26-002339.xml). Старата извадка (първите 8 записа)
не го съдържаше. Предишното тримесечие = сборът на двата Q1 филинга → HHH 27 852 064 и в двете тримесечия — НЕ е "увеличена" (обхват, не покупка; до 16.10 тестът твърдеше "увеличена").
СИНТЕТИЧНО (маркирано): само "днес" (фиксирана дата), граничните случаи за известие без родителски филинг в прозореца, нечетим XML и мрежови отказ.
Пускане: python test_13f_nt_follow.py
"""
import sys, json, pathlib, tempfile, types, datetime as dt, contextlib, io
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import dataroma, data_warnings

FX = ROOT / "tests" / "fixtures"
NT_XML = (FX / "sec_13f_nt_1336528_0001172661-26-003777.xml").read_text(encoding="utf-8")
Q2_XML = (FX / "sec_13f_infotable_2026053_0001172661-26-003790.xml").read_text(encoding="utf-8")
Q1_XML = (FX / "sec_13f_infotable_1336528_0001172661-26-002336.xml").read_text(encoding="utf-8")
SUB = json.loads((FX / "sec_submissions_pershing_2026-10-08.json").read_text(encoding="utf-8"))
SUB16 = json.loads((FX / "sec_submissions_13f_2026-10-16.json").read_text(encoding="utf-8"))                  # пълните 13F редове на двата CIK-а (16.10)
Q1P_XML = (FX / "sec_13f_infotable_2026053_0001172661-26-002339.xml").read_text(encoding="utf-8")            # Q1 2026 на родителя — само HHH 9 000 000
OLD, NEW = "0001336528", "0002026053"
assert len(NT_XML.encode()) == 2492 and len(Q2_XML.encode()) == 8054 and len(Q1_XML.encode()) == 5520 and len(Q1P_XML.encode()) == 831      # като в листинга на SEC

_tmp = tempfile.TemporaryDirectory(prefix="mb_nt_")
config.DATA_DIR = pathlib.Path(_tmp.name)
dataroma._CACHE = config.DATA_DIR / "dataroma_cache.json"
dataroma._TMAP_CACHE = config.DATA_DIR / "sec_tickers.json"
dataroma._ticker_map = lambda: {}


class Resp:
    def __init__(self, text="", js=None):
        self.text, self._js = text, js

    def json(self):
        return self._js

    def raise_for_status(self):
        return None


CALLS = []
FAIL = {"nt": False}


def fake_get(url, **kw):
    CALLS.append(url)
    for cik in (OLD, NEW):
        if url == f"https://data.sec.gov/submissions/CIK{cik}.json":
            return Resp(js=SUB16["submissions"][cik])
    if url.endswith("/1336528/000117266126003777/primary_doc.xml"):
        if FAIL["nt"]:
            raise ConnectionError("SEC недостъпен")                                                           # СИНТЕТИЧНО
        return Resp(NT_XML)
    if url.endswith("/2026053/000117266126003790/index.json"):
        return Resp(js=SUB["index_json_2026053_0001172661-26-003790"])
    if url.endswith("/2026053/000117266126003790/infotable.xml"):
        return Resp(Q2_XML)
    if url.endswith("/1336528/000117266126002336/index.json"):
        return Resp(js=SUB["index_json_1336528_0001172661-26-002336"])
    if url.endswith("/1336528/000117266126002336/infotable.xml"):
        return Resp(Q1_XML)
    if url.endswith("/2026053/000117266126002339/index.json"):
        return Resp(js=SUB16["index_json_2026053_0001172661-26-002339"])
    if url.endswith("/2026053/000117266126002339/infotable.xml"):
        return Resp(Q1P_XML)
    raise AssertionError(f"неочакван URL: {url}")


dataroma.requests = types.SimpleNamespace(get=fake_get)
dataroma._MEMO.clear()

print("── 1. парсерът на 13F-NT (реалният файл) ──")
assert dataroma._nt_other_managers(NT_XML) == [(NEW, "PERSHING SQUARE INC.")]
assert dataroma._nt_other_managers("<edgarSubmission><formData/></edgarSubmission>") == [] and dataroma._nt_other_managers("не е XML <<") == []                  # СИНТЕТИЧНО: без otherManagers / нечетим
print("  ✓ РЕАЛЕН 13F-NT на Pershing → [('0002026053', 'PERSHING SQUARE INC.')]; без otherManagers и нечетим XML → []")

print()
print("── 2. старото поведение (пропуска): само 13F-HR на стария CIK ──")
assert dataroma._recent_13f_filings(OLD, n=2) == [("0001172661-26-002336", "2026-05-15", "2026-03-31"), ("0001172661-26-001091", "2026-02-17", "2025-12-31")]   # 13F-NT от 14.08 не се брои → "закъснява"
assert dataroma.late_filer("2026-05-15", dt.date(2026, 10, 8))
print("  ✓ _recent_13f_filings(1336528) = 13F-HR от 15.05 (Q1) и 17.02 (Q4) с reportDate (13F-NT от 14.08 не се брои) → без следване Pershing 'закъснява'")

print()
print("── 3. _nt_successor ──")
s = dataroma._nt_successor(OLD, "2026-05-15")
assert s == {"cik": NEW, "name": "PERSHING SQUARE INC.", "acc": "0001172661-26-003790", "date": "2026-08-14", "nt_acc": "0001172661-26-003777", "nt_date": "2026-08-14"}, s
print(f"  ✓ РЕАЛНО: 13F-NT от {s['nt_date']} → родител {s['name']} (CIK {s['cik']}), 13F-HR {s['acc']} от {s['date']}")
assert dataroma._nt_successor(OLD, "2026-08-20") is None                                                                                                  # СИНТЕТИЧНО: последният 13F-HR е по-нов от известието → няма следване
assert dataroma._nt_successor(NEW, "2026-05-15") is None                                                                                                  # родителят няма 13F-NT
FAIL["nt"] = True
with contextlib.redirect_stdout(io.StringIO()):
    assert dataroma._nt_successor(OLD, "2026-05-15") is None                                                                                              # СИНТЕТИЧНО: мрежов отказ → graceful None
FAIL["nt"] = False
orig_recent = dataroma._recent_13f_filings
dataroma._recent_13f_filings = lambda cik, n=2: [("x", "2026-12-01")]                                                                                      # СИНТЕТИЧНО: филинг на родителя извън прозореца ±20 дни
assert dataroma._nt_successor(OLD, "2026-05-15") is None
dataroma._recent_13f_filings = orig_recent
print("  ✓ СИНТЕТИЧНО: без по-ново известие / родителят без известие / мрежов отказ / филинг извън прозореца → None (старото поведение, без изключение)")

print()
print("── 4. целият път: _manager_snapshot и _fetch_all_uncached ──")
dataroma._MEMO.clear()
with contextlib.redirect_stdout(io.StringIO()):
    snap = dataroma._manager_snapshot(OLD, "Бил Акман · Pershing Square")
assert snap["filing_status"] == "active" and snap["last_filing_date"] == "2026-08-14" and snap["period"] == "13F · 2026-08-14" and snap["followed_nt"]["cik"] == NEW
assert snap["late"] is None                                                                                                                                # вече не "закъснява"
assert (snap["quarter"], snap["prev_quarter"], snap["comparison"]) == ("2026-06-30", "2026-03-31", None)                                                  # поредните тримесечия по reportDate
assert len(snap["current_agg"]) == 14 and len(snap["prev_agg"]) == 11                                                                                      # Q2 (родителят) и Q1 (стария CIK + родителя: HHH е и в двата)
assert snap["current_agg"]["44267T102"]["shares"] == 18852064 + 9000000 and snap["current_scale"] == 1                                                    # двата реда на Howard Hughes се сумират по CUSIP
assert snap["prev_agg"]["44267T102"]["shares"] == 18852064 + 9000000 and snap["prev_scale_basis"] == "price+date"                                         # Q1: 18 852 064 (1336528) + 9 000 000 (2026053) — същото
assert any("/2026053/000117266126003790/" in u for u in CALLS) and any("/1336528/000117266126002336/" in u for u in CALLS) and any("/2026053/000117266126002339/" in u for u in CALLS)
print(f"  ✓ РЕАЛНО: текущо = Q2 от PERSHING SQUARE INC. ({len(snap['current_agg'])} CUSIP-а, подадено 14.08), предишно = Q1 = стария CIK + родителя ({len(snap['prev_agg'])} CUSIP-а; "
      f"HHH 18 852 064 + 9 000 000 и в двете тримесечия); 'закъснява' няма")

D = dt.date
class _Date(dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 8)
orig_dt = dataroma.dt
dataroma.dt = types.SimpleNamespace(date=_Date, timedelta=dt.timedelta, datetime=dt.datetime)
config.DATAROMA_CIK = {OLD: "Бил Акман · Pershing Square"}
dataroma._MEMO.clear()
with contextlib.redirect_stdout(io.StringIO()):
    bundle = dataroma._fetch_all_uncached(10_000_000)
dataroma.dt = orig_dt
meta = bundle["meta"]
assert meta["late_managers"] == [] and meta["followed_nt"] == [{"manager": "Бил Акман · Pershing Square", "to_cik": NEW, "to_name": "PERSHING SQUARE INC.", "nt_date": "2026-08-14", "filing_date": "2026-08-14"}]
assert meta["managers_with_data"] == 1 and meta["managers_with_comparison"] == 1 and meta["kind"] == "ok"
rows = dataroma._moves_from_snapshot(snap, 10_000_000, {})                                                                                         # всички редове на мениджъра (бандълът реже до DATAROMA_TOP_PER_MANAGER)
moves = {r["company"]: r["action"] for r in rows}
for new_pos in ("MASTERCARD INCORPORATED", "NETFLIX INC.", "S&P GLOBAL INC", "VISA INC"):
    assert moves.get(new_pos) == "нова позиция", (new_pos, moves)                                                                                          # нови в Q2 (ги нямаше в Q1)
for inc in ("META PLATFORMS INC", "MICROSOFT CORP", "UBER TECHNOLOGIES INC"):
    assert moves.get(inc) == "увеличена", (inc, moves)
assert "HOWARD HUGHES HOLDINGS INC" not in moves                                                                                                           # трети преглед: +9 млн е обхват (Q1 на родителя), не покупка — до 16.10 "увеличена"
assert moves.get("PERSHING SQUARE USA LTD") == "нова позиция"                                                                                              # РЕАЛНО: в нито един от двата Q1 филинга (otherManager 3, 4, 5)
assert {r["action"] for r in bundle["moves"]} <= {"нова позиция", "увеличена"} and bundle["moves"]                                                         # и през целия бандъл има редове за Pershing
print(f"  ✓ meta: late_managers = [], followed_nt = [Pershing → PERSHING SQUARE INC.]; нови позиции: Mastercard, Netflix, S&P Global, Visa; увеличени: Meta, Microsoft, Uber; Howard Hughes — НЕ (обхват)")
w = data_warnings.collect(None, None, superinvestor_status={"kind": "ok", "low_coverage": [], "late_managers": [{"manager": "Тест", "quarter_end": "2026-06-30", "deadline": "2026-08-14", "last_filing_date": "2026-05-15"}]})
assert w == []                                                                                                                                              # СИНТЕТИЧЕН закъснял мениджър: пак няма банер в "Проблем с данните днес"
print("  ✓ банерът за давност го няма в 'Проблем с данните днес' (етикетът е само в секцията на 13F)")
print("\n✅ test_13f_nt_follow: всичко мина")
