"""
20.10.2026 · етап 3б (обвивката, стъпка 1): LLY изпадаше ТИХО, когато фундаментите не се изтеглят. Пробното пускане на 20.10 (12:54, ограничение от Yahoo): "fundamentals LLY failed:
Failed to perform, curl: (28) Operation timed out after 935065 milliseconds" → LLY (технически преминат) липсваше от Action/Watchlist, а "Излязоха от вчера" казваше общото
"техническите филтри са преминати — отпаднал по-късно (CANSLIM фундаментите или лимитът на финалистите)". Празен .info (таймаут на fetch_with_timeout) беше още по-тих: капитализация 0 →
"малка компания", без ред в лога. Изборът НЕ се променя (неоценен тикър не е кандидат); сега има причина (screener.LAST_FUNDAMENTALS) и банер (data_warnings).

РЕАЛНО: tests/fixtures/yahoo_info_DOCN_CORT_CRL_2026-10-07.json (.info от Yahoo на 07.10), текстът на грешката за LLY от лога на пробното пускане, tests/fixtures/ohlc_AMD.csv.
СИНТЕТИЧНО (означено): подмененият yf.Ticker, празният .info на 'EMPTY', баровете на AMD, дадени на LLY, "техническите филтри са преминати" (explain_exclusion → None).
Пускане: python test_canslim_unavailable.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import screener, data_warnings as dw

INFO = json.loads((ROOT / "tests" / "fixtures" / "yahoo_info_DOCN_CORT_CRL_2026-10-07.json").read_text(encoding="utf-8"))["info"]
LLY_ERR = "Failed to perform, curl: (28) Operation timed out after 935065 milliseconds with 0 bytes received."     # РЕАЛНО — от лога


class _T:                                                                       # СИНТЕТИЧНО: yf.Ticker с реалните .info
    def __init__(self, sym): self.sym = sym

    @property
    def info(self):
        if self.sym == "LLY":
            raise RuntimeError(LLY_ERR)
        return {} if self.sym == "EMPTY" else INFO[self.sym]


screener.yf = type("Y", (), {"Ticker": _T, "download": None})
screener.time.sleep = lambda s: None
rows = [{"ticker": t} for t in ("CORT", "DOCN", "CRL", "LLY", "EMPTY", "AMD")]

print("── 1. всеки проверен тикър има резултат ──")
with contextlib.redirect_stdout(io.StringIO()) as log:
    passed = screener.fundamental_screen(rows, max_checks=5)
F = screener.LAST_FUNDAMENTALS
assert passed == []                                                                                 # РЕАЛНО: при праговете (EPS ≥ 25%, приходи ≥ 20%, ROE ≥ 17%) никой от трите не минава
assert {t: F[t]["result"] for t in F} == {"CORT": "criteria", "DOCN": "criteria", "CRL": "criteria", "LLY": "unavailable", "EMPTY": "unavailable", "AMD": "not_checked"}, F
assert F["CORT"]["text"] == "CANSLIM: EPS +22%, приходи +32%, ROE 8% — 1 от 3 критерия (нужни 2)" and "EPS спада" in F["DOCN"]["text"] and "RuntimeError" in F["LLY"]["text"] and "празен отговор" in F["EMPTY"]["text"]
assert screener.LAST_STATUS["fundamentals_unavailable"] == ["EMPTY", "LLY"] and screener.LAST_STATUS["fundamentals_checked"] == 5
assert "фундаментите не се изтеглиха за ['EMPTY', 'LLY']" in log.getvalue()
for t in ("CORT", "DOCN", "CRL", "LLY", "EMPTY", "AMD"):
    print(f"  ✓ {t}: {F[t]['text']}")

print()
print("── 2. причината в 'Излязоха от вчера' (explain_exits) ──")
AMD = pd.read_csv(ROOT / "tests" / "fixtures" / "ohlc_AMD.csv", index_col=0, parse_dates=True)
screener.yf.download = staticmethod(lambda t, **k: AMD if isinstance(t, str) or len(t) == 1 else pd.concat({x: AMD for x in t}, axis=1))
real_ex = screener.explain_exclusion
screener.explain_exclusion = lambda *a, **k: None                                                   # СИНТЕТИЧНО: техническите филтри са преминати
try:
    with contextlib.redirect_stdout(io.StringIO()):
        screener.LAST_FUNDAMENTALS["PASSED"] = {"result": "passed", "text": ""}              # СИНТЕТИЧНО: минал CANSLIM
        why = screener.explain_exits(["LLY", "DOCN", "PASSED"])
finally:
    screener.explain_exclusion = real_ex
assert why["LLY"].startswith("техническите филтри са преминати; фундаментите (Yahoo .info) не се изтеглиха днес (RuntimeError)")
assert why["DOCN"].startswith("техническите филтри са преминати; CANSLIM: EPS -4%")
assert "CANSLIM фундаментите или лимитът" in why["PASSED"]                                            # минал CANSLIM → отпаднал по-късно (общият текст остава)
print(f"  ✓ LLY → «{why['LLY']}»")

print()
print("── 3. банерът ──")
w = dw._partial_warnings(None, {**screener.LAST_STATUS, "kind": "ok", "universe": 903, "with_bars": 903, "no_bars_n": 0}, None, None, None, None, None, None, False)
assert [x["source"] for x in w] == ["screener"] and "на 2 от 5 проверени кандидата не се изтеглиха днес (EMPTY, LLY)" in w[0]["message"]
assert dw._partial_warnings(None, {"kind": "ok", "universe": 903, "no_bars_n": 0, "fundamentals_unavailable": []}, None, None, None, None, None, None, False) == []
print("  ✓ банер с тикърите; без неизтеглени фундаменти — без банер")
print("\n✅ test_canslim_unavailable: всичко мина")
