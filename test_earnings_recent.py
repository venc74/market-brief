"""
16.10.2026 · В1 (трети преглед): отчетът "изчезва" сутринта след него. Брифът е в 07:30 Берлин (~01:30 ET) — отчетът снощи (AMC) или вчера сутринта (BMO) вече е минал, Yahoo дава
следващото тримесечие (или нищо) като next_earnings и прозорецът преди отчет не се задейства. Сега: отчет в ПОСЛЕДНАТА сесия → флаг от кода (enrich.recent_report) и НЕ Action;
неизвестна дата, защото тегленето не успя (earnings_status "failed") → изричен ред и Watchlist вместо Action.

РЕАЛНО: tests/fixtures/earnings_recent_2026-08-05.json — Action картата на ANET от 05.08 (цена $190.51 = затварянето на 04.08, отпреди отчета в 16:00 ET; next_earnings празно в брифа),
Watchlist картата на INCY от 29.07 (отчет 28.07 в 07:00 ET; на 29.07 датата изчезна) и часовете на отчетите по Yahoo (get_earnings_dates, свалени на 15.10).
СИНТЕТИЧНО (маркирано): подмененият yf.Ticker (календар с минала дата / провал), "сега" за брифа, AI решението "Action" на INCY, петъчният отчет в т. 1.
Пускане: python test_earnings_recent.py
"""
import sys, json, pathlib, copy, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
config.ENABLE_BACKTEST = False
from src import enrich, main as brief_main

FX = json.loads((ROOT / "tests" / "fixtures" / "earnings_recent_2026-08-05.json").read_text(encoding="utf-8"))
TS = {t: pd.to_datetime(v, utc=True).tz_convert("America/New_York") for t, v in FX["earnings_dates"].items()}       # като индекса на yfinance (tz America/New_York)
D = dt.date.fromisoformat
UTC = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)

print("── 1. recent_report върху РЕАЛНИТЕ часове на отчетите ──")
anet_last = next(x for x in TS["ANET"] if x.date().isoformat() == "2026-08-04")
incy_last = next(x for x in TS["INCY"] if x.date().isoformat() == "2026-07-28")
ra = enrich.recent_report(anet_last, D("2026-08-05"))
assert ra == {"date": "2026-08-04", "when": "amc", "text": "Отчет снощи (04.08, след затварянето) — нивата са отпреди реакцията на отчета; Action най-рано утре."}, ra
ri = enrich.recent_report(incy_last, D("2026-07-29"))
assert ri["when"] == "bmo" and ri["text"].startswith("Отчет на 28.07 преди отварянето")
assert enrich.recent_report(anet_last, D("2026-08-06")) is None and enrich.recent_report(incy_last, D("2026-07-30")) is None
fri = pd.Timestamp("2026-10-09T16:05:00-04:00")                                                              # СИНТЕТИЧНО: отчет в петък след затварянето
assert enrich.recent_report(fri, D("2026-10-12"))["when"] == "amc" and enrich.recent_report(fri, D("2026-10-13")) is None
print("  ✓ ANET 05.08: 'Отчет снощи (04.08, след затварянето) — нивата са отпреди реакцията'; INCY 29.07: 'Отчет на 28.07 преди отварянето'; ден по-късно — нищо; петък AMC → понеделник")

print()
print("── 2. earnings_info: календарът с минала дата, get_earnings_dates — РЕАЛНИЯТ индекс ──")
class Tk:                                                                                                   # СИНТЕТИЧНО: yf.Ticker
    def __init__(self, sym, fail=False): self.sym, self.fail = sym, fail
    @property
    def calendar(self):
        if self.fail: raise RuntimeError("Yahoo down (СИНТЕТИЧНО)")
        return {"Earnings Date": [D("2026-08-04")]}
    def get_earnings_dates(self, limit=8):
        if self.fail: raise RuntimeError("Yahoo down (СИНТЕТИЧНО)")
        return pd.DataFrame({"EPS Estimate": [None] * len(TS[self.sym])}, index=TS[self.sym])
    info = {}
real_tk, real_recap = enrich.yf.Ticker, enrich.earnings_recap
enrich.earnings_recap = lambda s: None
try:
    enrich.yf.Ticker = lambda s: Tk(s)
    e = enrich.earnings_info("ANET", now=UTC("2026-08-05T05:30:00"))
    enrich.yf.Ticker = lambda s: Tk(s, fail=True)
    ef = enrich.earnings_info("ANET", now=UTC("2026-08-05T05:30:00"))
finally:
    enrich.yf.Ticker, enrich.earnings_recap = real_tk, real_recap
assert e["recent_report"] == ra and e["last_report"].startswith("2026-08-04T16:00") and e["earnings_status"] == "ok" and e["in_blackout"] is False
assert ef["earnings_status"] == "failed" and ef["next_earnings"] is None and ef["recent_report"] is None
print("  ✓ next = следващото тримесечие (без прозорец), last_report 04.08 16:00 ET, recent_report — флагът; провал на тегленето → earnings_status 'failed'")

print()
print("── 3. apply_hard_rules: РЕАЛНАТА Action карта на ANET от 05.08 → Watchlist ──")
anet = copy.deepcopy(FX["anet_action_2026_08_05"])
assert anet["ai"]["classification"] == "Action" and anet["price"] == 190.51 and not (anet.get("earnings") or {}).get("next_earnings")
anet["earnings"] = e
action, watch = brief_main.apply_hard_rules([anet], 1.0, "Offensive")
assert not action and watch[0]["ai"]["watchlist_reason_type"] == "earnings_recent"
assert watch[0]["ai"]["watchlist_trigger"].startswith("Отчет снощи (04.08, след затварянето) — нивата са отпреди реакцията на отчета; Action най-рано утре.")
print("  ✓ ANET: Action → Watchlist / earnings_recent;", watch[0]["ai"]["watchlist_trigger"][:110], "…")
incy = copy.deepcopy(FX["incy_watchlist_2026_07_29"]); incy["ai"] = {"classification": "Action", "why_now": "x"}      # СИНТЕТИЧНО: AI решение Action
incy["earnings"] = {**(incy.get("earnings") or {}), "recent_report": ri, "earnings_status": "ok"}
_, w2 = brief_main.apply_hard_rules([incy], 1.0, "Offensive")
assert w2[0]["ai"]["watchlist_reason_type"] == "earnings_recent" and "Отчет на 28.07 преди отварянето" in w2[0]["ai"]["watchlist_trigger"]
unk = copy.deepcopy(FX["anet_action_2026_08_05"]); unk["earnings"] = ef
_, w3 = brief_main.apply_hard_rules([unk], 1.0, "Offensive")
assert w3[0]["ai"]["watchlist_reason_type"] == "earnings_unknown" and w3[0]["ai"]["watchlist_trigger"].startswith(enrich.UNKNOWN_EARNINGS_TEXT)
old = copy.deepcopy(FX["anet_action_2026_08_05"]); old["earnings"] = {"next_earnings": None, "days_to_earnings": None, "in_blackout": False}     # стар формат без новите полета
a4, w4 = brief_main.apply_hard_rules([old], 1.0, "Offensive")
assert not any((x.get("ai") or {}).get("watchlist_reason_type") in ("earnings_recent", "earnings_unknown") for x in a4 + w4)
print("  ✓ INCY (BMO вчера) → earnings_recent; провал на тегленето → earnings_unknown с изричния ред; стар запис без новите полета — правилата не се намесват")
print("\n✅ test_earnings_recent: всичко мина")
