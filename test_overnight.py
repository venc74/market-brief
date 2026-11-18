"""
18.11.2026 (спешно, т. 2): блокът „Нощта“ (src/overnight.py) — от кода, без AI, в началото на брифа: отчетите след затварянето на предишната сесия (EPS факт срещу очаквана —
Nasdaq; приходи — Yahoo срещу очакваните, записани сутринта преди отчета; прогноза — само дословно заглавие; движението след затварянето) и ES / NQ / доларът спрямо 16:00 Ню Йорк,
10Y (затварянето) и ZN=F. Всеки ред с източника; липсва → „няма данни“.

РЕАЛНО: tests/fixtures/overnight_2026-11-18.json.gz — календарът за 17.11 от брифа на 17.11 (NVDA след затварянето), Nasdaq за 17.11 след отчетите (NVDA EPS $2.68 срещу $2.47),
Yahoo quoteSummary NVDA (приходи $115.84 млрд за 3Q2026, earningsDate 17.11 21:00 UTC), 5-мин. бари NVDA / ES=F / NQ=F / DX-Y.NYB / ZN=F / ^TNX до 18.11 01:35 Ню Йорк и заглавията
на четирите източника до 18.11 06:43 UTC (свалени на 18.11 следобед — НЕ точният пул на брифа). СИНТЕТИЧНО (означено): записаното очакване за приходите (т. 2), отговорът на
Yahoo за capture_estimates (т. 3), заглавието с прогноза (т. 4), празните входове (т. 5).
Пускане: python test_overnight.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, re, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_night_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
import pandas as pd
from src import overnight as ov, render

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "overnight_2026-11-18.json.gz").read_bytes()))
frame = lambda d: pd.DataFrame(list(d.values()), index=pd.to_datetime(list(d.keys()), utc=True), columns=["Open", "High", "Low", "Close", "Volume"])
FR = {k: frame(v) for k, v in FX["frames"].items()}
NOW = dt.datetime(2026, 11, 18, 6, 35, tzinfo=dt.timezone.utc)                     # 07:35 Берлин — часът на брифа
PREV = {"week_calendar": {"days": [FX["calendar_2026_11_17"]]}}

print("── 1. РЕАЛНО: 18.11 — NVDA и пазарът през нощта ──")
r = ov.build("2026-11-18", PREV, frames=FR, now_utc=NOW, nasdaq_rows=FX["nasdaq_2026_11_17"], qs=FX["qs"], pool=FX["pool"])
assert r["session"] == "2026-11-17" and [c["ticker"] for c in r["companies"]] == ["NVDA"]
L = r["companies"][0]["lines"]
assert L == ["EPS $2.68 срещу $2.47 очаквана (Nasdaq)",
             "приходи $115.84 млрд (Yahoo; очакване: няма данни — не е записано преди отчета)",
             "прогноза: няма заглавие в източниците на новините",
             "след затварянето +3.9% ($161.46 в 18:55 Ню Йорк срещу $155.46; Yahoo)"], L
M = [m["text"] for m in r["market"]]
assert M[0] == "ES (S&P 500 фючърс) +0.19% (7 377.25 в 01:30 Ню Йорк спрямо 16:00 на 17.11; Yahoo)" and M[1].startswith("NQ (Nasdaq-100 фючърс) +0.55%"), M
assert M[2].startswith("долар (DXY) +0.19%") and M[3] == "10Y 5.10% (затваряне 17.11, Yahoo ^TNX — нощем няма котировка)" and M[4].startswith("фючърсът на 10-годишните (ZN=F) +0.03%")
assert ov.yahoo_when(FX["qs"]["NVDA"], "2026-11-17") == "след затварянето"
assert ov.guidance_headline("NVIDIA Corporation", "NVDA", FX["pool"]) is None                  # „… swing lower“ (AP) не е прогноза
print("  ✓ " + " · ".join(L)[:150] + "…")

print("── 2. СИНТЕТИЧНО: очакването за приходите, записано сутринта преди отчета ──")
P2 = copy.deepcopy(PREV); P2["week_calendar"]["days"][0]["earnings"][0].update(revenue_estimate=112.1e9, estimate_as_of="2026-11-17")
r2 = ov.build("2026-11-18", P2, frames=FR, now_utc=NOW, nasdaq_rows=FX["nasdaq_2026_11_17"], qs=FX["qs"], pool=FX["pool"])
assert r2["companies"][0]["lines"][1] == "приходи $115.84 млрд срещу $112.10 млрд очаквани (Yahoo, записани 17.11 преди отчета)", r2["companies"][0]["lines"][1]
print("  ✓ „приходи $115.84 млрд срещу $112.10 млрд очаквани …“")

print("── 3. СИНТЕТИЧНО: capture_estimates — само днешните след затварянето / с неизвестен час ──")
W = {"days": [{"date": "2026-11-18", "earnings": [{"ticker": "PANW", "when": "след затварянето"}, {"ticker": "LOW", "when": "преди отварянето"}]},
              {"date": "2026-11-19", "earnings": [{"ticker": "WMT", "when": "преди отварянето"}]}]}
ce = lambda t: {"calendarEvents": {"earnings": {"earningsDate": [{"fmt": "2026-11-18"}], "revenueAverage": {"raw": 2.6e9}, "earningsAverage": {"raw": 0.52}}}}
assert ov.capture_estimates(W, "2026-11-18", qs_fn=ce) == 1
assert W["days"][0]["earnings"][0]["revenue_estimate"] == 2.6e9 and "revenue_estimate" not in W["days"][0]["earnings"][1]
other = lambda t: {"calendarEvents": {"earnings": {"earningsDate": [{"fmt": "2027-02-01"}], "revenueAverage": {"raw": 3e9}}}}
W2 = {"days": [{"date": "2026-11-18", "earnings": [{"ticker": "PANW", "when": "след затварянето"}]}]}
assert ov.capture_estimates(W2, "2026-11-18", qs_fn=other) == 0                                 # Yahoo вижда друга дата — не се записва
print("  ✓ PANW записан; LOW (преди отварянето) — не; друга дата в Yahoo — не")

print("── 4. СИНТЕТИЧНО: заглавие с прогноза ──")
pool = FX["pool"] + [{"source": "Reuters Business", "published": "2026-11-17T21:31Z", "title": "Nvidia forecasts fourth-quarter revenue above estimates - Reuters"}]
g = ov.guidance_headline("NVIDIA Corporation", "NVDA", pool)
assert g["title"].startswith("Nvidia forecasts fourth-quarter revenue") and g["source"] == "Reuters Business"
assert ov.name_keys("Walt Disney Company (The)", "DIS") == ["Walt Disney", "Disney", "DIS"]
print("  ✓ „Nvidia forecasts fourth-quarter revenue above estimates“ (Reuters)")

print("── 5. СИНТЕТИЧНО: липсващи данни — „няма данни“, не тишина ──")
r5 = ov.build("2026-11-18", PREV, frames={}, now_utc=NOW, nasdaq_rows=[], qs={}, pool=[], pool_checked=False)
assert r5["companies"][0]["lines"] == ["EPS: няма данни (отчетът още не е в Nasdaq / Yahoo)", "приходи: няма данни (Yahoo още не дава тримесечието)",
                                      "прогноза: заглавията не се провериха", "след затварянето: няма данни (Yahoo без post-market бари)"]
assert all("няма данни" in m["text"] for m in r5["market"])
r6 = ov.build("2026-11-18", {}, frames=FR, now_utc=NOW)
assert r6["companies"] == [] and r6["notes"][0].startswith("отчети след затварянето на 17.11 от следените компании няма")
print("  ✓ празните входове — всеки ред казва „няма данни“")

print("── 6. страницата и имейлът ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B); b["overnight"] = r
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
    mail = render.render_email(b)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
assert "Нощта · отчетите след затварянето на 17.11 и фючърсите" in txt and "NVDA · NVIDIA" in txt and "EPS $2.68 срещу $2.47 очаквана (Nasdaq)" in txt
assert txt.index("Нощта · отчетите") < txt.index("Пазарен термометър")
assert "Нощта · отчетите след затварянето на 17.11" in mail and "ES (S&amp;P 500 фючърс) +0.19%" in mail
b2 = copy.deepcopy(B); b2.pop("overnight", None)
with contextlib.redirect_stdout(io.StringIO()):
    assert "Нощта · отчетите" not in render.render_dashboard(b2, publish=False)
print("  ✓ в началото на страницата и в имейла; стар бриф — без блока")
print("── 7. run_for_brief: предишният бриф с календар отпреди 18.11 (РЕАЛНИ отговори, СИНТЕТИЧНО подменена мрежа) ──")
from src import econ_calendar as ec, preopen as po
orig = (ec.fetch_earnings, ov.fetch_quote_summary, po.fetch_market)
ec.fetch_earnings = lambda d: [dict(r) for r in FX["nasdaq_2026_11_17"]]
ov.fetch_quote_summary = lambda t, modules="": FX["qs"].get(t, {})
po.fetch_market = lambda syms: {k: v for k, v in FR.items() if k in syms}
try:
    with contextlib.redirect_stdout(io.StringIO()):
        rr = ov.run_for_brief("2026-11-18", PREV, ours={}, pool=FX["pool"], now_utc=NOW)
finally:
    ec.fetch_earnings, ov.fetch_quote_summary, po.fetch_market = orig
tk = [c["ticker"] for c in rr["companies"]]
assert tk[0] == "NVDA" and "HD" not in tk and set(tk) == {"NVDA", "DIS", "BHP"}, tk      # HD — преди отварянето по Yahoo (13:30 UTC); DIS, BHP — Yahoo без часа за 17.11
assert any("по Yahoo (Nasdaq го губи след отчета)" in n for n in rr["notes"])
print(f"  ✓ {tk}: HD (преди отварянето) — вън; DIS, BHP — с бележка за часа")
print("\n✅ test_overnight: всичко мина")
