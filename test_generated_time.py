"""
Пакет 2 · т.8 (2026-10-03): "генериран HH:MM CET" беше часът на машината (UTC на runner-а), не берлинският. Сега render.berlin_clock()
дава берлинско време със сезонния етикет (CET/CEST), а страницата го показва.

РЕАЛНО: в 79 архивни страници от docs/archive (измерено на 03.10.2026) 68 са "генериран 05:xx CET" — реалното cron пускане е
~05:30–05:56 UTC, т.е. 07:30–07:56 CEST (лятно време до 25.10.2026); първата и последната от тях: 05:36 … 19:38 (ръчни пускания).
Календарът на смяната на часа е реален: 2026-03-29 и 2026-10-25. СИНТЕТИЧНО: точните моменти (датите на проверка), подмененото
време и липсата на tz база данни; брифът за рендера е РЕАЛНИЯТ от 02.10 (tests/fixtures).
Пускане: python test_generated_time.py
"""
import sys, pathlib, json, tempfile, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import render

U = lambda y, m, d, h, mi: dt.datetime(y, m, d, h, mi, tzinfo=dt.timezone.utc)

print("── berlin_clock() ──")
assert render.berlin_clock(U(2026, 10, 2, 5, 53)) == ("07:53", "CEST")             # РЕАЛНО: страницата от 02.10 казваше "05:53 CET"
assert render.berlin_clock(U(2026, 10, 2, 5, 36)) == ("07:36", "CEST")
print("  ✓ РЕАЛНО пускане 02.10: 05:53 UTC → 07:53 CEST (старата страница казваше '05:53 CET')")
assert render.berlin_clock(U(2026, 1, 15, 6, 30)) == ("07:30", "CET")              # зимата: UTC+1
assert render.berlin_clock(U(2026, 7, 15, 5, 30)) == ("07:30", "CEST")             # лятото: UTC+2
print("  ✓ СИНТЕТИЧНО: 15.01 06:30 UTC → 07:30 CET; 15.07 05:30 UTC → 07:30 CEST")
assert render.berlin_clock(U(2026, 10, 25, 0, 59)) == ("02:59", "CEST")            # последният час преди края на лятното (01:00 UTC)
assert render.berlin_clock(U(2026, 10, 25, 1, 0)) == ("02:00", "CET")              # същият стенен час 02:00, вече зимно
assert render.berlin_clock(U(2026, 3, 29, 0, 59)) == ("01:59", "CET")
assert render.berlin_clock(U(2026, 3, 29, 1, 0)) == ("03:00", "CEST")              # 02:00–03:00 не съществува
print("  ✓ смяната на часа: 25.10 00:59 UTC = 02:59 CEST → 01:00 UTC = 02:00 CET; 29.03 00:59 UTC = 01:59 CET → 01:00 UTC = 03:00 CEST")
assert render.berlin_clock(dt.datetime(2026, 10, 2, 5, 53)) == ("07:53", "CEST")    # наивно време се счита за UTC
local = dt.datetime(2026, 10, 2, 8, 53, tzinfo=dt.timezone(dt.timedelta(hours=3)))  # локално пускане в UTC+3 (напр. София през лятото)
assert render.berlin_clock(local) == ("07:53", "CEST")
print("  ✓ наивно време = UTC; локално пускане в UTC+3 (08:53) → същият берлински час 07:53 CEST")

import zoneinfo
orig = zoneinfo.ZoneInfo
def no_tz(key):
    raise zoneinfo.ZoneInfoNotFoundError(key)
zoneinfo.ZoneInfo = no_tz
try:
    assert render.berlin_clock(U(2026, 10, 2, 5, 53)) == ("05:53", "UTC")
finally:
    zoneinfo.ZoneInfo = orig
print("  ✓ СИНТЕТИЧНО: без tz база данни → честно '05:53 UTC', не грешно 'CET'")
now_h, now_tz = render.berlin_clock()
assert len(now_h) == 5 and now_tz in ("CET", "CEST")
print(f"  ✓ без аргумент (сега): {now_h} {now_tz}")
print()

print("── premarket_note() — часът до US pre-market (04:00 Ню Йорк) от момента на генериране ──")
_pm = render.premarket_note
assert _pm(U(2026, 10, 2, 5, 53)) == "2 ч 7 мин до US pre-market (04:00 ET)"                    # РЕАЛНО пускане 02.10 (07:53 CEST): 127 минути, не 90
assert _pm(U(2026, 10, 8, 5, 30)) == "2 ч 30 мин до US pre-market (04:00 ET)"                    # типично пускане 07:30 CEST
assert _pm(U(2026, 10, 27, 5, 30)) == "2 ч 30 мин до US pre-market (04:00 ET)"                   # седмицата 25.10–01.11: Берлин вече зимно (CET), Ню Йорк още лятно (EDT) — часът се смята по ET, не по берлинския
assert _pm(U(2026, 11, 3, 6, 30)) == "2 ч 30 мин до US pre-market (04:00 ET)"                    # и двете зимни: 04:00 EST = 09:00 UTC
assert _pm(U(2026, 10, 8, 7, 35)) == "25 мин до US pre-market (04:00 ET)" and _pm(U(2026, 10, 8, 8, 30)) == "US pre-market тече" and _pm(U(2026, 10, 8, 13, 29)) == "US pre-market тече"
assert _pm(U(2026, 10, 8, 13, 30)) == "" and _pm(U(2026, 10, 8, 19, 0)) == ""
assert _pm(dt.datetime(2026, 10, 8, 5, 30)) == "2 ч 30 мин до US pre-market (04:00 ET)"           # наивно време = UTC
zoneinfo.ZoneInfo = no_tz
try:
    assert _pm(U(2026, 10, 8, 5, 30)) == ""
finally:
    zoneinfo.ZoneInfo = orig
print("  ✓ 02.10 07:53 CEST → «2 ч 7 мин» (РЕАЛНОТО пускане; твърдото «90 мин» не беше вярно); 07:30 CEST → «2 ч 30 мин»; седмицата 25.10–01.11 (Берлин CET, Ню Йорк още EDT) и зимата дават същото; 07:35 UTC → «25 мин»;")
print("    след 04:00 ET → «US pre-market тече»; след 09:30 ET → празно; без tz база → празно")
print()

print("── страницата (РЕАЛЕН бриф от 02.10) ──")
brief = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-02.json").read_text(encoding="utf-8"))
render.berlin_clock = lambda now=None, _o=render.berlin_clock: _o(U(2026, 10, 2, 5, 53))
render.premarket_note = lambda now=None, _o=render.premarket_note: _o(U(2026, 10, 2, 5, 53))
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2 = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        page = htmllib.unescape(render.render_dashboard(brief))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2
assert "генериран 07:53 CEST · 2 ч 7 мин до US pre-market (04:00 ET)" in page and "05:53" not in page.split("генериран")[1][:30]
assert "90 мин" not in page
print("  ✓ при момент 05:53 UTC страницата казва 'генериран 07:53 CEST · 2 ч 7 мин до US pre-market (04:00 ET)' (а не '05:53 CET' и не твърдото '90 мин')")
src = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "{{ generated_at }} CET" not in src and "{{ generated_tz }}" in src
print("  ✓ шаблонът няма хардкоднат 'CET'")
print()
print("Всички тестове минаха.")
