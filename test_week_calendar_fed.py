"""
17.11.2026 (пакет 1, т. 8): календарът на седмицата — (1) липсваха протоколите от FOMC (сряда 18.11, 14:00 Ню Йорк): в 07:30 Берлин на 17.11 календарът на Nasdaq беше празен
за 18, 19 и 23.11 (вечерта на 17.11 същите заявки са пълни, вкл. „FOMC Meeting Minutes“ 14:00). Сега: графикът на FOMC (config.FOMC_MEETINGS, официалният календар на Fed)
добавя решение / пресконференция / протоколи, когато Nasdaq ги няма — с етикет „(график на Fed)“; празен ден от източника — изричен ред, не „нищо от следените“.
(2) Една дата на отчета за страницата: календарът (Nasdaq) срещу картите (Yahoo) — при разминаване и двете, с етикет. (3) Консенсусът — с източника („EPS очаквана $2.17, Nasdaq“).

РЕАЛНО: tests/fixtures/fed_fomc_calendar_2026-11-17.html.gz — federalreserve.gov/monetarypolicy/fomccalendars.htm, свален 17.11.2026 (166 065 байта, SHA-256 d892a90f3eea8498…);
week_calendar от брифа на 17.11 (data/2026-11-17.json — дните 17–23.11; 18.11 празен) и WSM — „$2.17“ (Nasdaq). СИНТЕТИЧНО (означено): т. 3 — датата 18.11 от Yahoo за WSM.
Пускане: python test_week_calendar_fed.py
"""
import sys, re, gzip, copy, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import econ_calendar as ec, render

print("── 1. РЕАЛНО: графикът в config = календарът на Fed ──")
html = gzip.decompress((ROOT / "tests" / "fixtures" / "fed_fomc_calendar_2026-11-17.html.gz").read_bytes()).decode("utf-8", "replace")
months = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6, "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12}
got = []
for y in ("2026", "2027"):
    seg = html[html.index(f"{y} FOMC Meetings"):]
    seg = seg[:seg.index("FOMC Meetings", 30)] if "FOMC Meetings" in seg[30:] else seg
    for mon, days in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<', seg, re.S):
        a, b = re.findall(r"\d+", days)[:2]
        m = months[mon.split("/")[0]]
        got.append((f"{y}-{m:02d}-{int(a):02d}", f"{y}-{m:02d}-{int(b):02d}"))
assert tuple(got) == config.FOMC_MEETINGS, got
s26 = html[html.index("2026 FOMC Meetings"):]
s26 = s26[:s26.index("FOMC Meetings", 30)] if "FOMC Meetings" in s26[30:] else s26
rel = [dt.datetime.strptime(x, "%B %d, %Y").date() for x in re.findall(r"Released ([A-Za-z]+ \d+, \d{4})", s26)]
assert rel and all((d - dt.date.fromisoformat(e)).days == config.FOMC_MINUTES_DAYS for d, (_, e) in zip(rel, config.FOMC_MEETINGS))
print(f"  ✓ {len(got)} заседания 2026–2027; протоколите на 2026 ({len(rel)}) — 21 дни след заседанието")

print("── 2. РЕАЛНО: 18.11 (празен в брифа от 17.11) → протоколите по графика ──")
day = {"date": "2026-11-18", "fed": [], "econ": [], "earnings": [], "econ_empty": True}
assert ec.add_fed_schedule(day) == 1
lines = ec.day_lines(day)
assert lines == ["Fed: FOMC — протоколи от заседанието 27–28.10 — 14:00 Ню Йорк (график на Fed)",
                 "данните на Nasdaq за деня още не са публикувани — Fed е по графика; останалото — в следващия бриф"], lines
d2 = {"date": "2026-11-18", "fed": [{"date": "2026-11-18", "time_ny": "14:00", "event": "FOMC Meeting Minutes"}], "econ": [], "earnings": []}
assert ec.add_fed_schedule(d2) == 0                                                        # Nasdaq го има → не се дублира (РЕАЛНОТО име от Nasdaq, вечерта на 17.11)
assert [x["event"] for x in ec.fed_schedule(dt.date(2026, 12, 9))] == ["FOMC — решение за лихвите (заседанието 08–09.12)", "FOMC — пресконференция"]
print(f"  ✓ «{lines[0]}»; Nasdaq с протоколите — без дубликат; 09.12 — решение и пресконференция")

print("── 3. отчетът: източникът на консенсуса и разминаването на датите (WSM) ──")
wk = {"days": [{"date": "2026-11-19", "fed": [], "econ": [], "earnings": [{"date": "2026-11-19", "ticker": "WSM", "name": "Williams-Sonoma, Inc.", "when": "преди отварянето",
                                                                           "eps_forecast": "$2.17", "why": "в книгите"}]}]}                            # РЕАЛНОТО от 17.11
assert ec.day_lines(wk["days"][0]) == ["отчет: WSM · Williams-Sonoma, Inc. — преди отварянето (EPS очаквана $2.17, Nasdaq) · в книгите"]
conf = ec.reconcile_dates(copy.deepcopy(wk), {"WSM": "2026-11-18"})                       # СИНТЕТИЧНО: Yahoo с 18.11
assert conf == {"WSM": "отчет 18.11 (Yahoo) / 19.11 (Nasdaq) — източниците се разминават"}
w2 = copy.deepcopy(wk); ec.reconcile_dates(w2, {"WSM": "2026-11-18"})
assert ec.day_lines(w2["days"][0])[0].endswith("· ⚠ Yahoo: 18.11") and ec.reconcile_dates(copy.deepcopy(wk), {"WSM": "2026-11-19"}) == {}
card = {"ticker": "WSM", "setup": {"kind": "too_wide", "struct_risk_pct": 12.0}, "earnings": {"next_earnings": "2026-11-18", "date_conflict": conf["WSM"]}}
assert render.radar_reason(card).endswith("· ⚠ отчет 18.11 (Yahoo) / 19.11 (Nasdaq) — източниците се разминават")
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "{{ st.earnings.date_conflict }}" in tpl and '_ec.reconcile_dates(week_calendar' in (ROOT / "src" / "main.py").read_text(encoding="utf-8")
print("  ✓ „EPS очаквана $2.17, Nasdaq“; разминаване → в календара „⚠ Yahoo: 18.11“, в радара и на картата — и двете дати")
print("\n✅ test_week_calendar_fed: всичко мина")
