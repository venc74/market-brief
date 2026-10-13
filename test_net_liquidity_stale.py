"""
13.10.2026 · Fed Net Liquidity: RRPONTSYD (дневна) се проверява за застояване по СЕСИИ (допуск config.FRED_DAILY_MAX_LAG_SESSIONS = 2, както 2s10s), не по 3 календарни дни;
скритият индикатор носи причината и картата на термометъра я показва ("Скрити днес: …").

Случаят (РЕАЛЕН, брифът от 13.10): индикаторът беше скрит без банер и без ред. Последната точка на RRPONTSYD е 09.10 (12.10 — Columbus Day, облигационен празник, NYSE работи);
13.10 − 09.10 = 4 календарни дни > 3 → "stale" → hide. По сесии между 09.10 и 13.10 е само 12.10 (1 ≤ 2).

РЕАЛНО: tests/fixtures/fred_net_liquidity_2026-10-13.json (WALCL, WDTGAL, RRPONTSYD от FRED, изтеглени на 13.10), индикаторите на термометъра от брифа на 13.10
(data/2026-10-13.json → tests/fixtures/brief_2026-10-05.json е рамката на страницата). СИНТЕТИЧНО (означено): подменената "днес", отрязаната серия в т.3.
Пускане: python test_net_liquidity_stale.py
"""
import sys, json, pathlib, copy, re, tempfile, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_netliq_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"          # render пише страницата — само във временна папка
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import macro_layer as ml, thermometer, render

FX = json.loads((ROOT / "tests" / "fixtures" / "fred_net_liquidity_2026-10-13.json").read_text(encoding="utf-8"))
SER = {"WALCL": FX["WALCL"], config.NET_LIQ_TGA_SERIES: FX["WDTGAL"], "RRPONTSYD": FX["RRPONTSYD"]}


class FakeDate(dt.date):
    value = None

    @classmethod
    def today(cls):
        return cls.value


def run(today, series=SER):
    ml._fred_series = lambda sid, days=90: [x for x in series[sid] if x[0] < today]       # каквото FRED е имал сутринта (без точки от днес)
    FakeDate.value = dt.date.fromisoformat(today)
    orig = ml.dt
    ml.dt = type("M", (), {"date": FakeDate, "timedelta": dt.timedelta, "datetime": dt.datetime})
    try:
        return ml.fed_net_liquidity()
    finally:
        ml.dt = orig


print("── 1. брифът от 13.10 (РЕАЛНИТЕ серии) ──")
assert FX["RRPONTSYD"][-1][0] == "2026-10-09" and FX["WALCL"][-1][0] == "2026-10-07"
assert (dt.date(2026, 10, 13) - dt.date(2026, 10, 9)).days == 4 > config.STALENESS_THRESHOLD_DAYS                  # старото правило: 4 календарни дни > 3 → скрит
nl = run("2026-10-13")
assert not nl.get("hide") and nl["as_of"] == "2026-10-07" and nl["value"] == round((6747560 - 885783) / 1000 - 2.338, 1)
print(f"  ✓ последна точка на RRP 09.10, Columbus Day 12.10: по календар 4 дни > 3 (скрит), по сесии — 1 ≤ 2 → видим: ${nl['value']:,} млрд към {nl['as_of']}")

print()
print("── 2. застояла серия по сесии (СИНТЕТИЧНА 'днес' 16.10: 3 сесии след 09.10) ──")
nl2 = run("2026-10-16", {**SER, "RRPONTSYD": [x for x in FX["RRPONTSYD"] if x[0] <= "2026-10-09"]})
assert nl2["hide"] is True and nl2["hide_reason"] == "RRPONTSYD застояла — последно наблюдение 09.10 (праг 2 сесии)"
nl3 = run("2026-10-13", {**SER, "RRPONTSYD": []})
assert nl3["hide"] is True and nl3["hide_reason"] == "FRED не върна данни за RRPONTSYD"
print(f"  ✓ '{nl2['hide_reason']}'; празна серия → '{nl3['hide_reason']}'")

print()
print("── 3. индикаторът и картата на термометъра ──")
ind = thermometer._net_liquidity_indicator(nl2)
assert ind["hide"] is True and ind["hide_reason"] == nl2["hide_reason"] and thermometer._net_liquidity_indicator({"value": None})["hide_reason"] == "няма данни"
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
b["thermometer"]["indicators"] = [i for i in b["thermometer"]["indicators"] if i["name"] != "Fed Net Liquidity"] + [ind]
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "Скрити днес: Fed Net Liquidity — RRPONTSYD застояла — последно наблюдение 09.10 (праг 2 сесии) (информативен, не влиза в режима)" in page
sec = page[page.index("Пазарен термометър"):page.index("Скрити днес")]
assert sec.count("Fed Net Liquidity") == 0                                                                         # картата на скрития не се рисува — само редът
b2 = copy.deepcopy(b); b2["thermometer"]["indicators"] = [i for i in b2["thermometer"]["indicators"] if not i.get("hide")]
assert "Скрити днес" not in re.sub(r"<[^>]+>", " ", render.render_dashboard(b2))
print("  ✓ 'Скрити днес: Fed Net Liquidity — RRPONTSYD застояла — последно наблюдение 09.10 (праг 2 сесии) (информативен, не влиза в режима)'; без скрити — без реда")
print()
print("Всички тестове минаха.")
