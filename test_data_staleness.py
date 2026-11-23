"""
Пакет 4а · т.7 (2026-10-03): Insider buying (до 17.11.2026 и 13F — махнат) — при празен днешен резултат старите редове носят ясен етикет
за давност (дата на данните), а ЛЕГИТИМНАТА нула се различава от провал при теглене.

Мрежата е подменена; всички редове (покупки, мениджъри, холдинги) и датите са СИНТЕТИЧНИ — тестови вход, не реални
Form 4 / 13F. Шаблонът е реалният. Пускане: python test_data_staleness.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, pathlib, tempfile, json, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import insider_buying as ib, render, thermometer


class Clock:
    """Подменя dt.date.today() в модула — датата е параметър на теста."""
    day = dt.date(2026, 10, 1)

    class _D(dt.date):
        @classmethod
        def today(cls):
            return Clock.day

    ns = type("NS", (), {"date": _D, "timedelta": dt.timedelta, "datetime": dt.datetime})


def set_day(y, m, d):
    Clock.day = dt.date(y, m, d)


tmp = tempfile.TemporaryDirectory(prefix="market_brief_stale_")
T = pathlib.Path(tmp.name)
config.DATA_DIR = T
ib.dt = Clock.ns
ib._CACHE = T / "insider_buying_cache.json"
ib._sp500_ndx_universe = lambda: ["AAA", "BBB"]
RAW = [{"ticker": "AAA", "company": "AAA Corp", "insider_name": "Jane CEO", "title": "CEO", "is_officer_role": True,
        "transaction_date": dt.date(2026, 9, 29), "shares": 5000.0, "price": 100.0, "value": 500_000.0,
        "internal_transfer": False, "ownership": "D", "nature": ""}]
CLEAN = {"ciks_resolved": 480, "tickers_with_filings": 20, "submissions_fetch_errors": 0, "unique_filings_processed": 30}
state = {"raw": RAW, "diag": CLEAN, "boom": None}


def fake_fetch(universe, since):
    if state["boom"]:
        raise RuntimeError(state["boom"])
    return list(state["raw"]), dict(state["diag"])


ib._fetch_raw_transactions = fake_fetch


def run_ib(day, **over):
    set_day(*day)
    state.update({"raw": RAW, "diag": CLEAN, "boom": None}); state.update(over)
    return ib.fetch_insider_buying(), dict(ib.LAST_STATUS)


print("── Insider buying ──")
rows, st = run_ib((2026, 10, 1))
assert len(rows) == 1 and not rows[0].get("stale") and st["kind"] == "ok" and not st["stale"]
assert json.loads(ib._CACHE.read_text())["rows_date"] == "2026-10-01"
print("  ✓ ден 1 (01.10): има покупка → ok, не е остаряла; кешът пази rows_date = 01.10")

rows, st = run_ib((2026, 10, 2), raw=[])                       # чисто теглене, нула
assert st["kind"] == "legit_zero" and st["stale"] is True and st["data_date"] == "2026-10-01"
assert rows[0]["stale"] is True and rows[0]["data_date"] == "2026-10-01" and rows[0]["latest_txn_date"] == "2026-09-29"
assert "нито една квалифицираща покупка" in st["note"] and "480 компании" in st["note"]
print("  ✓ ден 2 (02.10): чисто теглене без покупки → ЛЕГИТИМНА нула; старият ред е с етикет 'данни от 01.10', последна транзакция 29.09")

rows, st = run_ib((2026, 10, 3), raw=[], diag={**CLEAN, "submissions_fetch_errors": 40})
assert st["kind"] == "failed" and st["stale"] and st["data_date"] == "2026-10-01"      # датата на ДАННИТЕ остава 01.10, не 02.10
assert "40 от 480" in st["note"] and rows[0]["data_date"] == "2026-10-01"
rows, st = run_ib((2026, 10, 4), raw=[], diag={**CLEAN, "ciks_resolved": 0})
assert st["kind"] == "failed" and "CIK" in st["note"]
rows, st = run_ib((2026, 10, 5), boom="SEC 503")
assert st["kind"] == "failed" and "SEC 503" in st["note"] and rows[0]["data_date"] == "2026-10-01"
print("  ✓ ден 3–5: провал (40 от 480 заявки, няма CIK мапинг, изключение) → 'failed', НЕ 'нула'; датата на данните остава 01.10")

rows, st = run_ib((2026, 10, 5), raw=[])                                                  # същият ден втори път → от кеша на деня, със СЪЩИЯ статус (не прегъва провала в "нула")
assert st["kind"] == "failed" and "SEC 503" in st["note"] and rows[0]["stale"] is True and rows[0]["data_date"] == "2026-10-01"
rows2 = ib.fetch_insider_buying()
assert rows2 == rows and ib.LAST_STATUS["kind"] == "failed"
rows, st = run_ib((2026, 10, 6))
assert len(rows) == 1 and not rows[0].get("stale") and st["kind"] == "ok" and json.loads(ib._CACHE.read_text())["rows_date"] == "2026-10-06"
print("  ✓ повторно извикване в същия ден пази етикета; нова покупка (06.10) → пак ok и rows_date = 06.10")

# стар кеш (преди тази промяна): няма rows_date → етикет "датата е неизвестна", но с последната транзакция
ib._CACHE.write_text(json.dumps({"date": "2026-10-01", "rows": [{"ticker": "AAA", "company": "AAA Corp", "total_value": 500000.0,
    "cluster": False, "in_screener": False, "insiders": [{"name": "Jane CEO", "title": "CEO", "date": "2026-09-29", "value": 500000.0}]}],
    "diagnostics": {}}))
rows, st = run_ib((2026, 10, 7), raw=[])
assert rows[0]["stale"] and rows[0]["data_date"] is None and rows[0]["latest_txn_date"] == "2026-09-29" and st["data_date"] is None
print("  ✓ стар кеш без rows_date: 'датата на теглене е неизвестна', показана е последната транзакция (29.09)")
print()

print("── dashboard ──")
def render_brief(**over):
    brief = {"date": "2026-10-05", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")), "action": [], "watchlist": [],
             "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
    brief.update(over)
    with tempfile.TemporaryDirectory() as docs:
        orig = config.DOCS_DIR; config.DOCS_DIR = pathlib.Path(docs)
        try:
            return htmllib.unescape(render.render_dashboard(brief))     # autoescape (т.8): сравняваме видимия текст
        finally:
            config.DOCS_DIR = orig

stale_row = {"ticker": "AAA", "company": "AAA Corp", "total_value": 500000.0, "cluster": False, "in_screener": False, "stale": True,
             "data_date": "2026-10-01", "latest_txn_date": "2026-09-29",
             "insiders": [{"name": "Jane CEO", "title": "CEO", "date": "2026-09-29", "value": 500000.0}]}
# Пакет 4б т.в (06.10.2026): секцията "Insider Buying" отпадна — етикетите за давност живеят в маркера INS✓ (виж test_insider_markers.py); бриф със старите ключове
# не показва нито секцията, нито бележката за данните
for status in ({"kind": "legit_zero", "stale": True, "data_date": "2026-10-01", "note": "проверени 480 компании: нито една квалифицираща покупка"},
               {"kind": "failed", "stale": False, "note": "универсът S&P500+NDX100 не се зареди"}, {"kind": "ok", "stale": False, "note": ""}):
    html = render_brief(insider_buying=[stale_row], insider_buying_status=status)
    assert "Insider Buying" not in html and "Insider buying:" not in html and "Jane CEO" not in html
print("    Insider: секцията отпадна (давността е в маркера INS✓, виж test_insider_markers.py) — старите ключове в брифа не показват нищо")

tmp.cleanup()
print()
print("Всички тестове минаха.")
