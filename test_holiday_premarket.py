"""
27.11.2026 (уикенд пакет, т. 1–3): денят след Thanksgiving (съкратена сесия до 13:00 Ню Йорк).
  • т. 1 — карето в 09:05 Ню Йорк падна: „премаркетът не се изтегли (празно)“, премаркет за 0 от 918. Причината не е в src/sessions.py: с period="2d" Yahoo закотвя периода на
    последния ЦЯЛ търговски ден (25.11) и не връща нито един бар за 27.11. С явни дати (sessions.intraday_range) — връща премаркета. И: затварянето в съкратена сесия е 13:00
    (sessions.close_minute) — after-hours след него не е „редовна сесия“.
  • т. 2 — 26.11 без бриф: нарочно (ENABLE_MARKET_CLOSED_SKIP); пререндираната страница вече не носи бележката „Утре (26.11)…“ от предишния бриф.
  • т. 3 — сутринта ES / NQ / DXY „няма данни (Yahoo без нощни бари)“: втори източник — котировката на Yahoo (fast_info); без премаркет — банер във всяка секция; датата за
    сравнението — винаги (до 27.11 „със затварянето на .. .“).

РЕАЛНО: tests/fixtures/yahoo_5m_holiday_2026-11-27.json — 5-мин. бари SPY, QQQ, NVDA, ES=F, NQ=F с явни дати 24–27.11 (изтеглени на 27.11 в 09:2x Ню Йорк), дните при period="2d"
(без 27.11) и котировките ES / NQ / DXY в същия момент. СИНТЕТИЧНО (означено): съкратената сесия — реалните бари на SPY от 25.11, преместени на 27.11 (затваряне 13:00).
Пускане: python run_tests.py test_holiday_premarket
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, re, io, contextlib, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_holpm_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import sessions, preopen, qm_ep, overnight, render

FX = json.loads((ROOT / "tests" / "fixtures" / "yahoo_5m_holiday_2026-11-27.json").read_text(encoding="utf-8"))


def frame(sym: str) -> pd.DataFrame:
    b = FX["bars"][sym]
    return pd.DataFrame({c: b[c] for c in ("Open", "High", "Low", "Close", "Volume")}, index=pd.to_datetime(b["index"])).dropna(subset=["Close"])


NOW = pd.Timestamp("2026-11-27 09:05", tz="America/New_York").tz_convert("UTC").to_pydatetime()

print("── 1. РЕАЛНО: period=\"2d\" е без 27.11, явните дати — с премаркета ──")
assert FX["period_2d_days"]["SPY"] == ["2026-11-24", "2026-11-25"]                                    # причината: Yahoo закотвя периода на 25.11
spy = frame("SPY")
p = preopen.premarket_point(spy, NOW)
assert p and p["session"] == "2026-11-25" and p["pm_bars"] > 0 and p["pm_last_ny"] <= "09:05", p
assert sessions.prev_session(dt.date(2026, 11, 27)) == dt.date(2026, 11, 25)                          # sessions — вярно (26.11 — празник)
assert sessions.intraday_range("2026-11-27") == ("2026-11-18", "2026-11-28") and sessions.intraday_range("2026-11-27", 1) == ("2026-11-24", "2026-11-28")
calls = []
class FakeYF:
    @staticmethod
    def download(tickers, **k):
        calls.append(k); return pd.DataFrame()
import yfinance
orig = yfinance.download
yfinance.download = FakeYF.download
try:
    with contextlib.redirect_stdout(io.StringIO()):
        preopen.fetch_5m(["SPY"]); preopen.fetch_market(["ES=F"]); qm_ep.fetch_5m(["SPY"])
finally:
    yfinance.download = orig
assert len(calls) == 3 and all("start" in k and "end" in k and "period" not in k for k in calls), calls
print(f"  ✓ SPY: затваряне 25.11 ${p['prev_close']:.2f}, премаркет ${p['pm_price']:.2f} ({p['pm_bars']} бара до {p['pm_last_ny']}); тегленето — с явни дати (3 места)")

print("── 2. СИНТЕТИЧНО: съкратена сесия (реалните бари на SPY от 25.11, преместени на 27.11) ──")
assert sessions.close_minute("2026-11-27") == 13 * 60 and sessions.close_minute("2026-11-25") == 16 * 60
d25 = spy[spy.index.tz_convert("America/New_York").date == dt.date(2026, 11, 25)].copy()
d25.index = d25.index + pd.Timedelta(days=2)                                                             # 25.11 → 27.11
ny = d25.index.tz_convert("America/New_York")
ah = qm_ep.extract_ah(d25)
reg_last = d25[(ny.hour * 60 + ny.minute >= 570) & (ny.hour * 60 + ny.minute < 780)]["Close"].iloc[-1]
assert ah["session"] == "2026-11-27" and ah["prev_close"] == float(reg_last) and ah["ah_bars"] == int(((ny.hour * 60 + ny.minute) >= 780).sum())
nov30 = pd.Timestamp("2026-11-30 09:05", tz="America/New_York").tz_convert("UTC").to_pydatetime()
mon = pd.concat([d25, (lambda x: x.set_axis(x.index + pd.Timedelta(days=3)))(spy[spy.index.tz_convert("America/New_York").date == dt.date(2026, 11, 27)])])
p30 = preopen.premarket_point(mon, nov30)
assert p30["session"] == "2026-11-27" and p30["prev_close"] == float(reg_last)                          # затварянето в 13:00, не последният бар преди 16:00
print(f"  ✓ затваряне 12:55 ${reg_last:.2f} (не 15:55); after-hours от 13:00 — {ah['ah_bars']} бара")

print("── 3. РЕАЛНО: фючърсите — без бари на 27.11, котировката като втори източник ──")
es = frame("ES=F")
assert preopen.premarket_point(es, NOW) is None                                                         # Yahoo без бари след 25.11 23:55
fp = preopen.futures_point(es, FX["quotes"]["ES=F"], NOW)
assert fp["source"] == "quote" and fp["base_label"] == "16:00 на 25.11" and fp["pm_price"] == FX["quotes"]["ES=F"]["price"]
mb = preopen.market_block({"ES=F": es, "NQ=F": frame("NQ=F")}, None, NOW, quotes={k: FX["quotes"][k] for k in ("ES=F", "NQ=F")})
assert [f["source"] for f in mb["futures"]] == ["quote", "quote"] and not mb["futures_missing"] and "котировка Yahoo, без 5-мин. бари" in mb["text"][0], mb["text"]
assert preopen.futures_point(None, {"price": 7302.0, "previous_close": 7168.25}, NOW)["base_label"] == "предишния сетълмент на договора"
assert preopen.futures_point(None, None, NOW) is None
mr = overnight.market_rows({"ES=F": es, "NQ=F": frame("NQ=F")}, pd.Timestamp("2026-11-27 01:30", tz="America/New_York").tz_convert("UTC").to_pydatetime(), "2026-11-25",
                           quotes={k: FX["quotes"][k] for k in ("ES=F", "NQ=F", "DX-Y.NYB")})
assert mr[0]["ok"] and mr[0]["source"] == "quote" and mr[1]["ok"] and "7 302.00 — котировка Yahoo, без 5-мин. бари; спрямо 16:00 на 25.11" in mr[0]["text"], mr[:2]
assert mr[2]["ok"] and "предишния сетълмент" in mr[2]["text"]                                         # DXY — без бари в набора → сетълментът
print(f"  ✓ «{mb['text'][0][:120]}…»")
print(f"  ✓ Нощта: «{mr[0]['text']}»")

print("── 4. банерът във всяка секция, датата за сравнението, затвореният ден ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B)
b["preopen"] = {"date": "2026-11-27", "time_ny": "09:05", "time_berlin": "15:05", "ok": False, "session": "2026-11-25", "diag": {"requested": 918, "with_pm": 0},
                "coverage": {"with_pm": 0, "requested": 918, "partial": True, "reason": "премаркет само за 0 от 918 тикъра"}, "gaps": [], "levels": [], "watch": [], "notes": [],
                "market": {"futures": [], "futures_missing": ["ES (S&P 500)", "NQ (Nasdaq-100)"], "text": []}}      # РЕАЛНОТО каре от 27.11 (съкратено)
b["novelty"] = {s: {"new": [], "old": [], "dropped": []} for s in ("canslim", "qm", "glb_classic", "glb_momentum", "ep")}
with contextlib.redirect_stdout(io.StringIO()):
    import html as _h
    t = re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
msg = "⚠ премаркет липсва — денят на пазарен гап не може да се провери (премаркет за 0 от 918 тикъра; фючърсите (ES (S&P 500), NQ (Nasdaq-100)) — без цена)"
assert t.count(msg) == 4, t.count(msg)                                                                  # CANSLIM, Kullamägi, EP, GLB
assert "сравнението е със затварянето на 25.11." in t
assert render.premarket_missing({"preopen": {"coverage": {"with_pm": 700, "requested": 918}, "market": {"futures": [{"x": 1}]}}}) is None
b2 = copy.deepcopy(B); b2["market_calendar_note"] = "Утре (26.11) борсата няма да работи — празник в САЩ."
with contextlib.redirect_stdout(io.StringIO()):
    closed = render.render_dashboard(b2, publish=False, closed_notice="Борсата (NYSE) е затворена днес (26.11) — последният бриф е от 25.11.")
    normal = render.render_dashboard(b2, publish=False)
assert "Утре (26.11) борсата няма да работи" not in closed and "Утре (26.11) борсата няма да работи" in normal
print("  ✓ 4 банера; „сравнението е със затварянето на 25.11.“; в затворения ден — без „Утре (26.11)…“")
print("\n✅ test_holiday_premarket: всичко мина")
