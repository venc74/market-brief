"""
10.11.2026 (т. 7): кеш на фундаментите (Yahoo .info) по тикър до следващия отчет — датата е от същия отговор (earningsTimestampStart / earningsTimestamp
в бъдещето), без допълнителна заявка; таванът от 60 важи само за НОВИТЕ заявки. Пазарната капитализация и P/E на запис от кеша — от днешната цена.

РЕАЛНО: tests/fixtures/yahoo_info_DOCN_CORT_CRL_2026-10-07.json (.info на CORT, DOCN, CRL от 07.10 — последният отчет 29.07 / 04.08 / 05.08, следващият 04.11).
СИНТЕТИЧНО (означено): подмененият yf.Ticker (връща реалните .info и брои заявките), датите на „днес“, цените на кандидатите, записът с изтекла давност.
Пускане: python test_fundamentals_cache.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_fundcache_")
config.DATA_DIR = pathlib.Path(_tmp.name)
from src import screener, render

INFO = json.loads((ROOT / "tests" / "fixtures" / "yahoo_info_DOCN_CORT_CRL_2026-10-07.json").read_text(encoding="utf-8"))["info"]
CALLS = []


class _T:                                                                        # СИНТЕТИЧНО: yf.Ticker с реалните .info; брои заявките
    def __init__(self, sym): self.sym = sym

    @property
    def info(self):
        CALLS.append(self.sym)
        return copy.deepcopy(INFO[self.sym])


screener.yf = type("Y", (), {"Ticker": _T, "download": None})
screener.time.sleep = lambda s: None
D = dt.date
rows = lambda *ts: [{"ticker": t, "price": INFO[t].get("currentPrice")} for t in ts]
def run(rs, today, cache=None, n=60):
    CALLS.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        return screener.fundamental_screen(rs, max_checks=n, today=today, cache=cache)

print("── 1. РЕАЛНО: датата на следващия отчет от самия .info ──")
assert [screener.next_report_date(INFO[t], D(2026, 10, 8)) for t in ("CORT", "DOCN", "CRL")] == ["2026-11-04"] * 3
assert screener.next_report_date(INFO["CORT"], D(2026, 11, 4)) is None                                         # в деня на отчета — не е „след днес“
assert screener.next_report_date({}, D(2026, 10, 8)) is None
print("  ✓ CORT, DOCN, CRL: 04.11 (earningsTimestampStart; earningsTimestamp е последният — 29.07 / 04.08 / 05.08)")

print("── 2. ден 1 (08.10): таван 2 нови заявки → CORT, DOCN теглени и в кеша; CRL — не проверен ──")
cache = {}
run(rows("CORT", "DOCN", "CRL"), D(2026, 10, 8), cache, n=2)
F1 = copy.deepcopy(screener.LAST_FUNDAMENTALS)
assert CALLS == ["CORT", "DOCN"] and set(cache) == {"CORT", "DOCN"} and cache["CORT"]["next_report"] == "2026-11-04" and cache["CORT"]["fetched"] == "2026-10-08"
assert F1["CRL"]["result"] == "not_checked" and screener.LAST_STATUS["fundamentals_cache"] == {"hits": 0, "requests": 2, "stored": 2}
assert "longBusinessSummary" in cache["CORT"]["info"] and "earningsQuarterlyGrowth" in cache["CORT"]["info"]
print("  ✓ 2 заявки; кешът: CORT и DOCN до 04.11")

print("── 3. ден 2 (09.10): CORT и DOCN от кеша (без заявка), таванът 2 отива за CRL — същият резултат ──")
run(rows("CORT", "DOCN", "CRL"), D(2026, 10, 9), cache, n=2)
F2 = screener.LAST_FUNDAMENTALS
assert CALLS == ["CRL"] and screener.LAST_STATUS["fundamentals_cache"] == {"hits": 2, "requests": 1, "stored": 1} and screener.LAST_STATUS["fundamentals_checked"] == 3
assert F2["CORT"] == F1["CORT"] and F2["DOCN"] == F1["DOCN"] and F2["CRL"]["result"] == "criteria"
assert F2["CORT"]["text"] == "CANSLIM: нетна печалба г/г +22% (Yahoo), приходи +32%, ROE 8% — 1 от 3 критерия (нужни 2)"
print("  ✓ 1 заявка вместо 2; CRL вече е проверен; CORT/DOCN — същият текст")

print("── 4. денят на отчета (04.11) и давността ──")
run(rows("CORT", "DOCN", "CRL"), D(2026, 11, 3), cache, n=60)
assert CALLS == [] and screener.LAST_STATUS["fundamentals_cache"]["hits"] == 3
run(rows("CORT", "DOCN", "CRL"), D(2026, 11, 4), cache, n=60)
assert CALLS == ["CORT", "DOCN", "CRL"]                                                                          # строго преди деня на отчета
old = {"fetched": "2026-06-01", "next_report": "2026-11-04", "info": {}}                                         # СИНТЕТИЧНО: 129 дни > 100
assert not screener.fund_cache_valid(old, D(2026, 10, 8)) and screener.fund_cache_valid({**old, "fetched": "2026-07-01"}, D(2026, 10, 8))
assert not screener.fund_cache_valid(None, D(2026, 10, 8)) and not screener.fund_cache_valid({"fetched": "x"}, D(2026, 10, 8))
print("  ✓ на 03.11 — от кеша; на 04.11 — наново; над 100 дни — наново")

print("── 5. пазарна капитализация и P/E от днешната цена ──")
e = {"fetched": "2026-10-08", "next_report": "2026-11-04", "info": {k: INFO["CORT"].get(k) for k in screener._FUND_FIELDS if INFO["CORT"].get(k) is not None}}
i0, i1 = screener.info_from_cache(e, None), screener.info_from_cache(e, INFO["CORT"]["currentPrice"] * 1.1)
assert i0["marketCap"] == INFO["CORT"]["marketCap"] and abs(i1["marketCap"] / (INFO["CORT"]["sharesOutstanding"] * INFO["CORT"]["currentPrice"]) - 1.1) < 1e-9
if (INFO["CORT"].get("trailingEps") or 0) > 0:
    assert abs(i1["trailingPE"] - INFO["CORT"]["currentPrice"] * 1.1 / INFO["CORT"]["trailingEps"]) < 1e-9
print(f"  ✓ CORT при +10% цена: капитализация ×1.10 (sharesOutstanding × цена)")

print("── 6. файлът в config.DATA_DIR: запис, четене, изтеклите отпадат; изключен кеш — както преди ──")
assert screener.fund_cache_path().parent == pathlib.Path(_tmp.name)
CALLS.clear()
with contextlib.redirect_stdout(io.StringIO()):
    screener.fundamental_screen(rows("CORT", "DOCN"), max_checks=60, today=D(2026, 10, 8))
    screener.fundamental_screen(rows("CORT", "DOCN", "CRL"), max_checks=60, today=D(2026, 10, 9))
assert CALLS == ["CORT", "DOCN", "CRL"] and set(screener.load_fund_cache()) == {"CORT", "DOCN", "CRL"}
screener.save_fund_cache(screener.load_fund_cache(), D(2026, 11, 4))
assert screener.load_fund_cache() == {}
screener.fund_cache_path().write_text("{не е json", encoding="utf-8")
assert screener.load_fund_cache() == {}
config.FUNDAMENTALS_CACHE = False
try:
    CALLS.clear(); run(rows("CORT", "DOCN", "CRL"), D(2026, 10, 9), {"CORT": e}, n=2)
    assert CALLS == ["CORT", "DOCN"] and "fundamentals_cache" in screener.LAST_STATUS
finally:
    config.FUNDAMENTALS_CACHE = True
print("  ✓ data/ не се пипа (тестът е в temp); повреден файл → празен кеш; FUNDAMENTALS_CACHE=0 → старото поведение")

print("── 7. редът под радара ──")
st = {"fundamentals_not_checked": {"n": 4, "max": 60, "top": [{"ticker": "CRL", "rs_rating": 91}]}, "fundamentals_cache": {"hits": 37, "requests": 60, "stored": 12}}
T = render.fundamentals_note(st)
assert T == "Фундаментите не са проверени за 4 имена (таван 60 нови заявки към Yahoo на ден — проверяват се най-силните по RS; още 37 — от кеша до следващия отчет); с най-висок RS от тях: CRL (RS 91) — те не са в списъците по-горе.", T
st.pop("fundamentals_cache")
assert "(таван 60 заради Yahoo — проверяват се най-силните по RS)" in render.fundamentals_note(st)             # стар бриф
print(f"  ✓ {T}")
print("\n✅ test_fundamentals_cache: всичко мина")
