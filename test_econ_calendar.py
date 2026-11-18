"""
16.11.2026 (пакет 16.11, т. 8–9): (8) календар на седмицата в сутрешния бриф — отчетите на компаниите с тегло > 2% в S&P 500 (утре NVDA след затварянето) и на нашите (карти,
книги, наблюдавани), Fed (речи, протоколи, решения), основните данни с консенсуса; източник — календарът на Nasdaq, с етикет; провал → червен ред. (9) Икономическите заглавия
в карето в 15:05 — с очакванията: 13.11 „Wholesale prices rose 0.3% in October, putting annual rate at 6.5% …“ без „под очакваното: 0.3% срещу 0.4%“.
ИЗМЕРЕНО: икономическият календар на Nasdaq връща събитията на деня ПРЕДИ подадената дата (заявка за 14.11 → петък 13.11, PPI) — заявката е за деня + 1; пазач: Initial Jobless
Claims в четвъртък.

РЕАЛНО: tests/fixtures/nasdaq_econ_q<дата>.json.gz — отговорите на api.nasdaq.com/api/calendar/economicevents?date=<дата> (заявката; събитията са за деня преди нея) за 12, 14,
16–21.11, и nasdaq_earnings_<дата>.json.gz — api.nasdaq.com/api/calendar/earnings?date=<дата> за 16–20.11; изтеглени 16.11.2026 ~15:30 Берлин. Заглавието за PPI от
data/preopen/2026-11-13.json (CNBC, 09:02 Ню Йорк) — цитирано тук. brief_2026-10-19.json и ep_aaon_sanm_2026-11-10.json — рамката и карето.
СИНТЕТИЧНО (означено): т. 2 — отместване 0 (за пазача), провал на източника; кои тикъри са „нашите“.
Пускане: python test_econ_calendar.py
"""
import sys, json, gzip, re, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cal_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import econ_calendar as ec, render

FXD = ROOT / "tests" / "fixtures"


def get(url):
    q = re.search(r"date=(\d{4}-\d{2}-\d{2})", url).group(1)
    return json.loads(gzip.decompress((FXD / f"nasdaq_{'econ_q' if 'economicevents' in url else 'earnings_'}{q}.json.gz").read_bytes()))


ECON = lambda d: ec.fetch_econ(d, get)
EARN = lambda d: ec.fetch_earnings(d, get)
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. РЕАЛНО: отместването с ден и PPI на 13.11 ──")
r13 = ECON(dt.date(2026, 11, 13))                                                          # заявка за 14.11
ppi = [r for r in r13 if r["event"] == "PPI"]
assert [(r["actual"], r["consensus"], r["previous"]) for r in ppi] == [("0.3%", "0.4%", "1.4%"), ("6.5%", "6.6%", "6.3%")] and ppi[0]["time_ny"] == "08:30"
assert all(r["date"] == "2026-11-13" for r in r13)
E = ec.expectations_for("PPI", r13)
assert E == ("очаквания (Nasdaq): Core PPI — факт 0.3%, консенсус 0.3% (предишно 0.8%) · факт 5.0%, консенсус 5.0% (предишно 5.0%); "
             "PPI — факт 0.3%, консенсус 0.4% (предишно 1.4%) · факт 6.5%, консенсус 6.6% (предишно 6.3%)"), E
assert ec.expectations_for("CPI", r13) == "очаквания: няма данни" and ec.expectations_for(None, r13) == "очаквания: няма данни"
print(f"  ✓ 13.11 (заявка 14.11): {E}")

print("── 2. РЕАЛНО: седмицата от 16.11 ──")
big = {"NVDA": "тегло 6.4% в S&P 500", "AAPL": "тегло 7.9% в S&P 500"}
ours = {"HD": "наблюдаван"}                                                                 # СИНТЕТИЧНО: HD като наш тикър
with q():
    W = ec.build_week(dt.date(2026, 11, 16), big, ours, econ_fn=ECON, earnings_fn=EARN)
assert W["ok"] and W["errors"] == [] and [d["date"] for d in W["days"]] == ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
L = {d["date"]: ec.day_lines(d) for d in W["days"]}
assert L["2026-11-17"][:2] == ["отчет: NVDA · NVIDIA Corporation — след затварянето (EPS очаквана $2.49, Nasdaq) · тегло 6.4% в S&P 500",
                               "отчет: HD · Home Depot, Inc. (The) — преди отварянето (EPS очаквана $3.86, Nasdaq) · наблюдаван"], L["2026-11-17"]
assert "Fed: FOMC Meeting Minutes — 14:00 Ню Йорк" in L["2026-11-18"] and "Fed: Fed Chair Warsh Speaks — 12:00 Ню Йорк" in L["2026-11-16"]
assert "Retail Sales — 08:30 Ню Йорк: консенсус 0.2% (предишно 0.8%)" in L["2026-11-17"]
assert "Initial Jobless Claims — 08:30 Ню Йорк: консенсус 199K (предишно 200K)" in L["2026-11-19"]
assert not any("Balance Sheet" in l or "GDPNow" in l or "Bill Auction" in l for ls in L.values() for l in ls)
print("  ✓ 17.11: NVDA след затварянето, HD преди отварянето; 18.11: протоколът на FOMC; 19.11: jobless claims с консенсуса")
# 18.11.2026 (спешно, т. 6): и големите компании — капитализация ≥ $100 млрд по Nasdaq (РЕАЛНО: отговорите за 18.11 и 19.11); TGT ($73 млрд) — под прага
e18 = {e["ticker"]: e["why"] for e in next(d for d in W["days"] if d["date"] == "2026-11-18")["earnings"]}
assert e18 == {"PANW": "капитализация $264 млрд", "TJX": "капитализация $150 млрд", "LOW": "капитализация $128 млрд"}, e18
assert "отчет: PANW · Palo Alto Networks, Inc. — след затварянето (EPS очаквана $0.52, Nasdaq) · капитализация $264 млрд" in L["2026-11-18"], L["2026-11-18"]
e19 = {e["ticker"]: e["why"] for e in next(d for d in W["days"] if d["date"] == "2026-11-19")["earnings"]}
assert e19["WMT"] == "капитализация $1.0 трлн" and "TGT" not in e18 and W["cap_min_bn"] == 100
assert ec.market_cap("$264,078,852,000") == 264078852000.0 and ec.market_cap("") is None and ec.market_cap("N/A") is None
print("  ✓ 18.11: PANW, TJX, LOW (≥ $100 млрд); 19.11: WMT „$1.0 трлн“; TGT ($73 млрд) — под прага")

print("── 3. СИНТЕТИЧНО: пазачът за отместването и провалът ──")
config.ECON_CAL_DAY_SHIFT = 0
with q():
    W0 = ec.build_week(dt.date(2026, 11, 16), big, ours, econ_fn=ECON, earnings_fn=EARN)
config.ECON_CAL_DAY_SHIFT = 1
assert not W0["ok"] and "Initial Jobless Claims е на петък 20.11 — датите на източника не съвпадат" in W0["errors"]
def boom(d):
    raise ConnectionError("blocked")
with q():
    Wf = ec.build_week(dt.date(2026, 11, 16), big, ours, econ_fn=boom, earnings_fn=EARN)
assert not Wf["ok"] and Wf["errors"][0] == "данни 16.11: ConnectionError" and Wf["days"][1]["earnings"]
print("  ✓ без отместването — „Initial Jobless Claims е на петък 20.11 — датите на източника не съвпадат“; паднал източник — ред по ден, отчетите остават")

print("── 4. страницата и имейлът ──")
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19); b["week_calendar"] = {**W, "weights_note": "теглата — позициите на SPY от SSGA, към 13.11"}
with q():
    page, mail = render.render_dashboard(b, publish=False), render.render_email(b)
assert "<h2>Календар на седмицата</h2>" in page and "отчет: NVDA · NVIDIA Corporation — след затварянето" in page and "Източник: Nasdaq" in page
assert "Календар на седмицата" in mail and "NVDA · NVIDIA Corporation" in mail
b["week_calendar"] = Wf
with q():
    page_f = render.render_dashboard(b, publish=False)
assert "⚠ Календарът е непълен: данни 16.11: ConnectionError" in page_f
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'steps.step("week_calendar", _week_calendar' in src and '"week_calendar": week_calendar' in src
print("  ✓ секцията и имейлът; провал — червен ред")

print("\n✅ test_econ_calendar: всичко мина")
