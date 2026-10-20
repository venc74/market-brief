"""
20.10.2026 · етап 3, част А, т. 3: COT крипто — "седмично затваряне към 16.10" с различна стойност на 19.10 и 20.10.

Причина (РЕАЛНО): седмичният бар на Yahoo за BTC-USD / XRP-USD е понеделник–неделя (крипто се търгува 7 дни). В понеделник сутрин (брифът от 19.10, 05:30 UTC) той
още носеше затварянето от СЪБОТА: BTC 81382.1 / XRP 1.2926 (= 17.10); във вторник — неделното: 82017.6 / 1.305 (= 18.10). Етикетът "към 16.10" (петък, NYSE логиката)
не е верен и за двата. Euro FX (1.1238 и в двата брифа) не е засегнат.
Поправка: за крипто седмичните затваряния се строят от ДНЕВНИТЕ (последното затваряне понеделник–неделя; седмица без неделен бар отпада), етикетът е неделята,
седмицата е завършена от понеделника след нея. Етикетът на бара остава понеделникът — връзката с COT датите в track_rows не се мести.

РЕАЛНО: tests/fixtures/cot_crypto_closes_2026-10-20.json — дневните и седмичните затваряния на BTC-USD и XRP-USD от Yahoo, свалени на 20.10.2026 (дневните до 19.10).
СИНТЕТИЧНО (означено): "състоянието на 19.10" = същите дневни без неделния бар 18.10.
Пускане: python test_cot_crypto_week.py
"""
import sys, json, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
from src import cot_track as ct

FX = json.loads((ROOT / "tests/fixtures/cot_crypto_closes_2026-10-20.json").read_text(encoding="utf-8"))
ser = lambda v: pd.Series(list(v.values()), index=pd.to_datetime(list(v)), dtype=float)
daily = {s: ser(v) for s, v in FX["daily"].items()}
weekly_yahoo = {s: ser(v) for s, v in FX["weekly"].items()}

print("── 1. седмиците от дневните = седмичния бар на Yahoo за завършените седмици (РЕАЛНО) ──")
for s in ("BTC-USD", "XRP-USD"):
    w = ct.crypto_weekly_closes(daily[s])
    common = [d for d in w.index if d in weekly_yahoo[s].index and d < pd.Timestamp("2026-10-19")]
    assert len(common) >= 20 and all(abs(w[d] / weekly_yahoo[s][d] - 1) < 1e-6 for d in common), s
    assert w.index[-1] == pd.Timestamp("2026-10-12") and all(d.weekday() == 0 for d in w.index)
print("  ✓ BTC-USD и XRP-USD: всяка завършена седмица = седмичния бар на Yahoo; етикетът е понеделникът; седмицата от 19.10 (без неделя) я няма")

print()
print("── 2. брифът на 20.10 и на 19.10 ──")
w = ct.crypto_weekly_closes(daily["BTC-USD"])
assert round(w[pd.Timestamp("2026-10-12")], 1) == 82017.6 and ct.week_close_date(pd.Timestamp("2026-10-12"), crypto=True) == "2026-10-18"
d19 = daily["BTC-USD"][daily["BTC-USD"].index <= "2026-10-17"]                                                          # СИНТЕТИЧНО: без неделния бар
w19 = ct.crypto_weekly_closes(d19)
assert w19.index[-1] == pd.Timestamp("2026-10-05") and round(w19.iloc[-1], 1) == 83679.5                                   # седмицата 12–18.10 още не е завършена в данните
assert round(daily["BTC-USD"][pd.Timestamp("2026-10-17")], 1) == 81382.1                                                  # това показа брифът от 19.10 като "към 16.10"
xrp = ct.crypto_weekly_closes(daily["XRP-USD"])
assert round(xrp[pd.Timestamp("2026-10-12")], 3) == 1.305 and round(daily["XRP-USD"][pd.Timestamp("2026-10-17")], 4) == 1.2926
print("  ✓ 20.10: BTC 82017.6 / XRP 1.305 към 18.10 (неделя); без неделния бар седмицата отпада → последната завършена е 05–11.10 (BTC 83679.5 към 11.10), не съботата 81382.1")

print()
print("── 3. завършена седмица и етикет ──")
assert list(ct.completed(w, dt.date(2026, 10, 19), crypto=True).index[-1:]) == [pd.Timestamp("2026-10-12")]          # понеделник 19.10 — седмицата 12–18.10 е завършена
assert list(ct.completed(w, dt.date(2026, 10, 18), crypto=True).index[-1:]) == [pd.Timestamp("2026-10-05")]          # в неделя — още не
assert ct.week_close_date(pd.Timestamp("2026-09-28")) == "2026-10-02" and ct.week_close_date(pd.Timestamp("2026-09-28"), crypto=True) == "2026-10-04"
c = ct.confirmation(w, "extreme_long", crypto=True)
assert c["close_date"] == "2026-10-18" and "към 18.10" in ct.confirmation_text(c, "extreme_long")
assert ct.is_crypto("BTC-USD") and ct.is_crypto("XRP-USD") and not ct.is_crypto("EURUSD=X") and not ct.is_crypto("GC=F") and not ct.is_crypto(None)
print("  ✓", ct.confirmation_text(c, "extreme_long"))
src = (ROOT / "src/cot_track.py").read_text(encoding="utf-8")
assert 'if is_crypto(symbol):' in src and 'interval="1d"' in src and "close = completed(close, today, crypto)" in src
print("\n✅ test_cot_crypto_week: всичко мина")
