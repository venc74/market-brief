"""
Пакет 4а · т.7 (2026-10-03): Insider buying и 13F — при празен днешен резултат старите редове носят ясен етикет
за давност (дата на данните), а ЛЕГИТИМНАТА нула се различава от провал при теглене.

Мрежата е подменена; всички редове (покупки, мениджъри, холдинги) и датите са СИНТЕТИЧНИ — тестови вход, не реални
Form 4 / 13F. Шаблонът е реалният. Пускане: python test_data_staleness.py
"""
import sys, pathlib, tempfile, json, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import insider_buying as ib, dataroma, render, thermometer


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

print("── 13F (dataroma) ──")
dataroma.dt = Clock.ns
dataroma._CACHE = T / "dataroma_cache.json"
dataroma._TMAP_CACHE = T / "sec_tickers.json"
dataroma._ticker_map = lambda: {}
config.DATAROMA_CIK = {"0000000001": "Тест · Fund A", "0000000002": "Тест · Fund B"}
calls = {"n": 0}
FIL = {"0000000001": [("a-new", "2026-09-20"), ("a-old", "2026-06-20")], "0000000002": [("b-new", "2026-09-22"), ("b-old", "2026-06-22")]}
HOLD = {"a-new": [{"issuer": "NEWCO INC", "value": 80e6, "cusip": "N1", "shares": 1000.0}, {"issuer": "OLDCO INC", "value": 20e6, "cusip": "O1", "shares": 100.0}],
        "a-old": [{"issuer": "OLDCO INC", "value": 20e6, "cusip": "O1", "shares": 100.0}],
        "b-new": [{"issuer": "SAME INC", "value": 50e6, "cusip": "S1", "shares": 500.0}],
        "b-old": [{"issuer": "SAME INC", "value": 50e6, "cusip": "S1", "shares": 500.0}]}
mode = {"edgar": "ok", "allact": []}


def fake_filings(cik, n=2):
    calls["n"] += 1
    if mode["edgar"] == "down":
        return []
    if mode["edgar"] == "quiet" and cik == "0000000001":
        return [("b-new", "2026-09-22"), ("b-old", "2026-06-22")]            # същите холдинги и за А → нищо ново
    return FIL[cik][:n]


dataroma._recent_13f_filings = fake_filings
dataroma._info_table = lambda cik, acc: [dict(h) for h in HOLD.get(acc, [])]
dataroma._allact_buys = lambda: list(mode["allact"])


def run_dr(day, m, allact=()):
    set_day(*day)
    mode.update({"edgar": m, "allact": list(allact)}); dataroma._MEMO.clear()
    return dataroma._fetch_all(config.DATAROMA_MIN_VALUE), dataroma.fetch_status()


b, st = run_dr((2026, 10, 1), "ok")
assert st["kind"] == "ok" and not st["stale"] and [r["company"] for r in b["new_positions"]] == ["NEWCO INC"]
assert json.loads(dataroma._CACHE.read_text())["date"] == "2026-10-01"
print("  ✓ ден 1 (01.10): EDGAR работи → ok, кешът е от 01.10")

b, st = run_dr((2026, 10, 2), "down")
assert st["kind"] == "failed" and st["stale"] and st["data_date"] == "2026-10-01" and "0 от 2 мениджъра" in st["note"]
assert [r["company"] for r in b["new_positions"]] == ["NEWCO INC"] and b["meta"]["stale"] is True
assert json.loads(dataroma._CACHE.read_text())["date"] == "2026-10-01"                 # кешът на диска не се пипа — датата му е реалната дата на данните
print("  ✓ ден 2 (02.10): EDGAR недостъпен (0 от 2) → 'failed'; старите данни са с етикет 'от 01.10', кешът на диска е непокътнат")

b, st = run_dr((2026, 10, 3), "quiet")
assert st["kind"] == "legit_zero" and st["stale"] and st["data_date"] == "2026-10-01" and "2 от 2 мениджъра" in st["note"]
print("  ✓ ден 3 (03.10): EDGAR работи, но нищо ново → ЛЕГИТИМНА нула (различна от провала), старите данни пак са с етикет от 01.10")

b, st = run_dr((2026, 10, 4), "down", allact=[{"ticker": "ZZZ", "manager": "X", "action": "Buy", "value": None, "period": None}])
assert st["kind"] == "fallback_allact" and not st["stale"] and [r["ticker"] for r in b["moves"]] == ["ZZZ"]
print("  ✓ ден 4: EDGAR падна, но dataroma.com върна общ списък → 'fallback_allact' (без стойности, не е остарял кеш)")

(T / "dataroma_cache.json").unlink()
b, st = run_dr((2026, 10, 5), "down")
assert st["kind"] == "failed" and not st["stale"] and not b["moves"] and not b["new_positions"]
calls["n"] = 0
set_day(2026, 10, 5); dataroma._MEMO.clear(); mode["edgar"] = "ok"
for _ in range(4):
    dataroma._fetch_all(config.DATAROMA_MIN_VALUE)
assert calls["n"] == 2 * 1                                                              # 2 мениджъра × ЕДИН fetch на процес (не 4)
print("  ✓ без кеш и без данни: 'failed' с празен резултат; четири извиквания в един run теглят EDGAR само веднъж")
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
html = render_brief(insider_buying=[stale_row], insider_buying_status={"kind": "legit_zero", "stale": True, "data_date": "2026-10-01",
                                                                           "note": "проверени 480 компании: нито една квалифицираща покупка"})
flat = " ".join(html.split())
assert "Insider buying: показаното е от по-ранно теглене — данни от 2026-10-01, не от днес." in flat
assert "Днешното теглене е чисто, но празно: проверени 480 компании" in flat
assert "⚠ остарели данни — теглени на 2026-10-01 · последна транзакция 2026-09-29" in flat
html = render_brief(insider_buying=[], insider_buying_status={"kind": "failed", "stale": False, "note": "универсът S&P500+NDX100 не се зареди"})
assert "Insider buying: тегленето не успя — универсът S&P500+NDX100 не се зареди." in " ".join(html.split()) and "Insider Buying · Form 4" in html
html = render_brief(insider_buying=[], insider_buying_status={"kind": "ok", "stale": False, "note": ""})
assert "Insider Buying · Form 4" not in html                                              # нормален празен ден без статус за показване
html = render_brief(superinvestor_moves=[{"ticker": "NEWCO", "manager": "Тест · Fund A", "action": "нова позиция", "value": 8e7, "period": "13F · 2026-09-20"}],
                    superinvestor_status={"kind": "failed", "stale": True, "data_date": "2026-10-01", "note": "EDGAR недостъпен (0 от 2 мениджъра с данни)"})
flat = " ".join(html.split())
assert "13F: показаното е от по-ранно теглене — данни от 2026-10-01, не от днес." in flat and "Днешното теглене не успя: EDGAR недостъпен" in flat
html = render_brief(superinvestor_moves=[], superinvestor_status={"kind": "failed", "stale": False, "note": "EDGAR недостъпен (0 от 2 мениджъра с данни)"})
assert "13F: тегленето не успя — EDGAR недостъпен" in " ".join(html.split())
print("  ✓ остарели редове: 'показаното е от по-ранно теглене — данни от 01.10, не от днес' + причина (чисто, но празно / не успя) + етикет")
print("    на всяка карта; провал без данни → видима бележка; нормален празен ден → нищо; същото за 13F")

tmp.cleanup()
print()
print("Всички тестове минаха.")
