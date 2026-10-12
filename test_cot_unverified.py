"""
12.10.2026 · COT тикър без име в Yahoo: повторен опит, проверка за цени, текст "не можа да се провери днес" срещу "няма котировка — делистнат или сменен символ",
подсказка за новия символ по company_claim на модела.

Случаят (РЕАЛЕН, брифът от 12.10): BK (2-Year Treasury Note) и CSWI (E-mini Russell 2000) отпаднаха като "няма име в Yahoo (вероятно делистнат или преименуван)", а компаниите
работят — символите са сменени: BNY Mellon BK → BNY (21.05.2026), CSW Industrials CSWI → CSW (09.06.2025). Yahoo на 12.10 връща 404 и 0 бара и за двата — затова "делистнат"
само по цените би ги хванал пак; новият символ се намира с търсене по името, което моделът твърди (company_claim).

РЕАЛНО (tests/fixtures/yahoo_unverified_2026-10-12.json): записаните на 12.10 отговори на Yahoo (info, барове за 7 дни, търсене по име) за BK, CSWI, GMCR, SWN, BSMX, DNKN, MAG,
HBI, SAFM и контролата EXPD; company_claim от кеша на тезите; изключените в брифа от 12.10. СИНТЕТИЧНО (означено): подмененият yf (връща записаните отговори), първият провал
на lookup-а при повторния опит, тикър с цени без име, паднала ценова проверка.
Пускане: python test_cot_unverified.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
from src import ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "yahoo_unverified_2026-10-12.json").read_text(encoding="utf-8"))
CL = FX["claims"]


class _T:                                                                 # СИНТЕТИЧНО: yf.Ticker, който връща ЗАПИСАНИТЕ отговори от 12.10
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
        self.quotes = FX["search"].get(q, [])


class _YF:
    Ticker, Search = _T, _S


ai_brief.yf = _YF()
ai_brief._verified_company_name.cache_clear()


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


print("── 1. изключените от 12.10 и записаните отговори ──")
got = {(d["market"], d["ticker"]) for d in FX["dropped_2026_10_12"]}
assert {("2-Year Treasury Note", "BK"), ("E-mini Russell 2000", "CSWI")} <= got and len(got) == 7
assert all(FX["info"][t]["shortName"] is None and not FX["bars"][t]["dates"] for t in ("BK", "CSWI", "GMCR", "SWN", "BSMX", "DNKN", "MAG", "HBI", "SAFM"))
assert FX["info"]["EXPD"]["shortName"] and FX["bars"]["EXPD"]["dates"]
print("  ✓ 7 изключени като 'unverified' на 12.10 (вкл. BK и CSWI); Yahoo на 12.10: без име и без нито един бар за всичките 9, контролата EXPD — с име и цени")

print()
print("── 2. новият символ по company_claim (РЕАЛНИТЕ резултати от търсенето) ──")
s = {t: quiet(ai_brief._successor_by_claim, t, CL[t]) for t in ("BK", "CSWI", "GMCR", "BSMX", "DNKN", "MAG", "HBI", "SAFM")}
assert s["BK"]["ticker"] == "BNY" and s["CSWI"]["ticker"] == "CSW" and s["GMCR"]["ticker"] == "KDP"
assert all(s[t] is None for t in ("BSMX", "DNKN", "MAG", "HBI", "SAFM"))
assert quiet(ai_brief._successor_by_claim, "BK", None) is None and quiet(ai_brief._successor_by_claim, "BK", "  ") is None
print(f"  ✓ BK → {s['BK']['ticker']} ({s['BK']['name']}), CSWI → {s['CSWI']['ticker']}, GMCR (твърдение 'Keurig Dr Pepper Inc.') → KDP; BSMX, DNKN, MAG, HBI, SAFM (придобити) — нищо")

print()
print("── 3. текстът на изключването ──")
_, d = quiet(ai_brief._unverified_reason, {"ticker": "BK", "company_claim": CL["BK"]})
assert d["code"] == "unverified" and d["successor"] == "BNY" and "делистнат или сменен символ" in d["reason"] and "Yahoo води BNY" in d["reason"]
assert "вероятно делистнат" not in d["reason"]
_, d2 = quiet(ai_brief._unverified_reason, {"ticker": "HBI", "company_claim": CL["HBI"]})
assert d2["code"] == "unverified" and "successor" not in d2 and d2["reason"] == "няма котировка в Yahoo (нито име, нито цени за последните 5 сесии) — делистнат или сменен символ"
FX["info"]["XYZ"] = {"shortName": None, "longName": None, "quoteType": "EQUITY"}; FX["bars"]["XYZ"] = FX["bars"]["EXPD"]       # СИНТЕТИЧНО: без име, но с цени (EXPD-овите)
_, d3 = quiet(ai_brief._unverified_reason, {"ticker": "XYZ"})
assert d3["code"] == "unverified_today" and "не можа да се провери днес" in d3["reason"] and "цени има" in d3["reason"]
real_bars = ai_brief._recent_bars
ai_brief._recent_bars = lambda t: None                                                                                          # СИНТЕТИЧНО: ценовата проверка пада
_, d4 = quiet(ai_brief._unverified_reason, {"ticker": "BK", "company_claim": CL["BK"]})
assert d4["code"] == "unverified_today" and d4["reason"] == "не можа да се провери днес (Yahoo не върна нито име, нито цени)"
ai_brief._recent_bars = real_bars
print("  ✓ BK:", d["reason"])
print("  ✓ HBI:", d2["reason"])
print("  ✓ без име, с цени (СИНТЕТИЧНО) → 'не можа да се провери днес'; паднала ценова проверка (СИНТЕТИЧНО) → 'не можа да се провери днес'")

print()
print("── 4. повторният опит ──")
calls = {"n": 0}
real_lookup = ai_brief._verified_company_name


def flaky(t):                                                                                                                   # СИНТЕТИЧНО: първият lookup пада, вторият — успява
    calls["n"] += 1
    return {"name": t, "verified": False} if calls["n"] == 1 else {"name": "Expeditors International of Washington", "verified": True}


ai_brief._verified_company_name = flaky
assert flaky("EXPD")["verified"] is False                                                                                        # първото извикване (в _verify_thesis_tickers)
lk, why = quiet(ai_brief._unverified_reason, {"ticker": "EXPD"})
assert calls["n"] == 2 and lk["verified"] is True and why is None                                                               # _unverified_reason прави ВТОРОТО
ai_brief._verified_company_name = real_lookup
print("  ✓ провал при първото, успех при повторното → тикърът не се изключва")

print()
print("── 5. през _verify_thesis_tickers (cross теза на 2-Year Treasury Note с РЕАЛНИЯ тикър BK) ──")
th = {"tickers": [{"ticker": "BK", "source": "model", "company_claim": CL["BK"], "quote": "банка за попечителство (СИНТЕТИЧЕН текст)"}], "reasoning": ""}
out = quiet(ai_brief._verify_thesis_tickers, th, set(), "2-Year Treasury Note")
dr = out["dropped_tickers"]
assert out["tickers"] == [] and dr[0]["ticker"] == "BK" and dr[0]["code"] == "unverified" and "BNY" in dr[0]["reason"]
assert "BNY" in out["empty_reason"]
print("  ✓", out["empty_reason"])
print()
print("Всички тестове минаха.")
