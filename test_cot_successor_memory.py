"""
15.10.2026 · COT: (а) намерената подсказка за нов символ се помни (ai_brief.SUCCESSOR_MEMORY ↔ config.COT_SUCCESSOR_CACHE_FILE); (б) цената в price_confirmation носи датата —
"седмично затваряне 6.492 към 02.10".

(а) Реално: GMCR (Keurig Dr Pepper) — "по името „Keurig Dr Pepper Inc.“ Yahoo води KDP … — вероятно новият символ" в брифа от 13.10, БЕЗ подсказка на 14.10 ("делистнат или сменен символ"),
пак с нея на 15.10 — търсенето в Yahoo връща резултата един ден и не го връща на следващия. BNY за BK и CSW за CSWI бяха стабилни.
(б) Седмичният бар на Yahoo е с датата на понеделника; затварянето е в последната сесия на седмицата (петък, назад през NYSE празник).

РЕАЛНО: tests/fixtures/yahoo_unverified_2026-10-12.json (записаните отговори на Yahoo от 12.10 — info, барове, търсене по име; company_claim от кеша на тезите);
tests/fixtures/brief_2026-10-14.json и brief_2026-10-15.json (изключените тикъри и текстовете за GMCR); седмичните цени — test_cot_track.py (cot_prices_2026-10-05.json).
СИНТЕТИЧНО (маркирано): "празното" търсене (14.10), подмененият yf, датите на паметта, грешното твърдение за компания.
Пускане: python test_cot_successor_memory.py
"""
import sys, json, pathlib, io, contextlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import ai_brief, cot_track

FX = json.loads((ROOT / "tests" / "fixtures" / "yahoo_unverified_2026-10-12.json").read_text(encoding="utf-8"))
CL = FX["claims"]
B14 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-14.json").read_text(encoding="utf-8"))
B15 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-15.json").read_text(encoding="utf-8"))
dropped = lambda b, t: next(d for r in b["cot"] for d in ((r.get("cross_sector_thesis") or {}).get("dropped_tickers") or []) if d.get("ticker") == t)
assert "KDP" not in dropped(B14, "GMCR")["reason"] and dropped(B15, "GMCR")["successor"] == "KDP"

SEARCH = {"empty": False}


class _T:                                                                 # СИНТЕТИЧНО: yf.Ticker със ЗАПИСАНИТЕ отговори от 12.10
    def __init__(self, t):
        self.t = t

    @property
    def info(self):
        return dict(FX["info"].get(self.t) or {})

    def history(self, **k):
        b = FX["bars"].get(self.t) or {"dates": [], "close": []}
        return pd.DataFrame({"Close": b["close"]}, index=pd.to_datetime(b["dates"])) if b["dates"] else pd.DataFrame()


class _S:
    def __init__(self, q, max_results=8):
        self.quotes = [] if SEARCH["empty"] else FX["search"].get(q, [])         # СИНТЕТИЧНО "empty": търсенето не връща нищо (като на 14.10)


class _YF:
    Ticker, Search = _T, _S


ai_brief.yf = _YF()
ai_brief._verified_company_name.cache_clear()


def reason(t):
    with contextlib.redirect_stdout(io.StringIO()):
        return ai_brief._unverified_reason({"ticker": t, "company_claim": CL[t]})[1]


print("── (а) паметта за нов символ ──")
ai_brief.SUCCESSOR_MEMORY.clear()
d1 = reason("GMCR")
assert d1["successor"] == "KDP" and "Yahoo води KDP" in d1["reason"] and "successor_remembered_from" not in d1
assert ai_brief.SUCCESSOR_MEMORY["GMCR"]["ticker"] == "KDP" and ai_brief.SUCCESSOR_MEMORY["GMCR"]["claim"] == CL["GMCR"]
SEARCH["empty"] = True
d2 = reason("GMCR")
assert d2["successor"] == "KDP" and d2["reason"] == d1["reason"] and d2["successor_remembered_from"] == ai_brief.SUCCESSOR_MEMORY["GMCR"]["last_found"]
print("  ✓ ден 1 (РЕАЛНОТО търсене): KDP, записан в паметта; ден 2 (СИНТЕТИЧНО празно търсене, като на 14.10): същият текст от паметта")
with contextlib.redirect_stdout(io.StringIO()):
    _, d3 = ai_brief._unverified_reason({"ticker": "GMCR", "company_claim": "Green Mountain Power Corp."})          # СИНТЕТИЧНО: друга компания
assert "successor" not in d3 and "Yahoo води" not in d3["reason"]
print("  ✓ твърдение за ДРУГА компания → паметта не се ползва")
d4 = reason("SWN")
assert "successor" not in d4 and "SWN" not in ai_brief.SUCCESSOR_MEMORY
SEARCH["empty"] = False
print("  ✓ тикър без намерена подсказка (SWN, придобита) — нито подсказка, нито запис")
with tempfile.TemporaryDirectory() as tmp:
    p = pathlib.Path(tmp) / "cot_successor_cache.json"
    assert ai_brief.save_successor_memory(p) and json.loads(p.read_text(encoding="utf-8"))["tickers"]["GMCR"]["ticker"] == "KDP"
    keep = dict(ai_brief.SUCCESSOR_MEMORY); ai_brief.SUCCESSOR_MEMORY.clear()
    assert ai_brief.load_successor_memory(p) == 1 and ai_brief.SUCCESSOR_MEMORY == keep
    p.write_text("{повреден", encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        assert ai_brief.load_successor_memory(p) == 0 and ai_brief.load_successor_memory(pathlib.Path(tmp) / "няма.json") == 0
print("  ✓ запис/зареждане (временна директория); повреден или липсващ файл → празна памет, без изключение")
ai_brief.SUCCESSOR_MEMORY.clear()
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.index("ai_brief.load_successor_memory()") < src.index("cot_with_theses = ai_brief.cot_theses(") < src.index("ai_brief.save_successor_memory()")
print("  ✓ main: зарежда преди COT тезите, записва след тях")

print()
print("── (б) датата на седмичното затваряне ──")
assert cot_track.week_close_date(pd.Timestamp("2026-09-28")) == "2026-10-02"                     # понеделник → петък
assert cot_track.week_close_date(pd.Timestamp("2026-03-30")) == "2026-04-02"                     # Разпети петък 03.04.2026 (NYSE празник) → четвъртък
assert cot_track.week_close_date(pd.Timestamp("2026-10-02")) == "2026-10-02"                     # етикет в петък → същият ден
c = cot_track.confirmation(pd.Series([100.0] * 12 + [99.0], index=pd.date_range("2026-07-06", periods=13, freq="7D")), "extreme_long")   # СИНТЕТИЧНА серия
assert c["close_date"] == "2026-10-02" and "седмично затваряне 99 към 02.10 срещу SMA10" in cot_track.confirmation_text(c, "extreme_long")
old = {k: v for k, v in c.items() if k != "close_date"}
assert "; цена 99 срещу SMA10" in cot_track.confirmation_text(old, "extreme_long")                # стар запис без датата — както преди
print("  ✓ 28.09 → 02.10; седмица с Разпети петък → 02.04; текстът 'седмично затваряне 99 към 02.10'; стар запис без датата — 'цена …'")
print("\n✅ test_cot_successor_memory: всичко мина")
