"""
16.10.2026 · часовете по Берлин се смятат от часовите зони (setup_rules.ny_time_in_berlin): "Проверката е отварянето (15:30 CEST / 09:30 ET)" беше твърдо — грешно в седмицата 25.10–01.11
(Европа на зимно, САЩ още на лятно време: 14:30 CET) и цялата зима (CET, не CEST); краят на after-hours (qm_ep.note_bg) — 01:55 → 00:55 в същата седмица. Отчетът в текста "Trigger"
на Watchlist — ДД.ММ, не ISO ("Отчет на 2026-11-03").

РЕАЛНО: tests/fixtures/brief_2026-10-09.json (EP секцията и дневникът — рамка за страницата и имейла); правилата за часовото време — tz базата (America/New_York, Europe/Berlin).
СИНТЕТИЧНО (маркирано): датите за рендерирането (подменен dt.date.today в render), картата за текста "Trigger".
Пускане: python test_tz_labels.py
"""
import sys, json, pathlib, copy, re, tempfile, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_tz_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import setup_rules as sr, qm_ep, render, main

D = dt.date.fromisoformat
print("── 1. отварянето и краят на after-hours по Берлин ──")
assert [sr.ny_time_in_berlin(D(d), 9, 30) for d in ("2026-10-16", "2026-10-26", "2026-11-02", "2027-03-15", "2027-03-29")] == \
       ["15:30 CEST", "14:30 CET", "15:30 CET", "14:30 CET", "15:30 CEST"]
assert [sr.ny_time_in_berlin(D(d), 19, 55) for d in ("2026-10-16", "2026-10-26", "2026-11-02")] == ["01:55 CEST", "00:55 CET", "01:55 CET"]
assert "after-hours гап в 00:55 CET" in qm_ep.note_bg(D("2026-10-26")) and "01:55 CEST" in qm_ep.note_bg(D("2026-10-16"))
print("  ✓ 16.10 15:30 CEST · 26.10 (седмицата 25.10–01.11) 14:30 CET · 02.11 15:30 CET · 15.03.2027 (пролетната седмица) 14:30 CET · 29.03.2027 15:30 CEST; AH край 01:55 → 00:55 CET")

print()
print("── 2. страницата и имейлът (РЕАЛНИЯТ бриф от 09.10; СИНТЕТИЧНА дата на рендериране) ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-09.json").read_text(encoding="utf-8"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
real_date = render.dt.date
class FakeDate(dt.date):
    fixed = D("2026-10-27")
    @classmethod
    def today(cls): return cls.fixed
try:
    render.dt.date = FakeDate
    page, mail = flat(render.render_dashboard(copy.deepcopy(B))), flat(render.render_email(copy.deepcopy(B)))
finally:
    render.dt.date = real_date
assert "Проверката е отварянето (14:30 CET / 09:30 ET)" in page and "15:30 CEST" not in page
assert "Проверката е отварянето (14:30 CET): гапът се доказва едва тогава." in mail
print("  ✓ на 27.10: страницата '(14:30 CET / 09:30 ET)', имейлът '(14:30 CET)'")

print()
print("── 3. Trigger на Watchlist: отчетът е ДД.ММ ──")
c = {"ticker": "X", "earnings": {"next_earnings": "2026-11-03", "days_to_earnings": 5, "in_blackout": True}, "setup": {"trigger_text": "Чака пробив."}}      # СИНТЕТИЧНА карта
assert main._watchlist_trigger_text(c, "Offensive").startswith("Отчет на 03.11 (5 дни) — нов Action най-рано след отчета.")
c["earnings"]["days_to_earnings"] = 0
assert main._watchlist_trigger_text(c, "Offensive").startswith("Отчет ДНЕС")
print("  ✓ 'Отчет на 03.11 (5 дни)'; в деня на отчета — 'Отчет ДНЕС'")
print("\n✅ test_tz_labels: всичко мина")
