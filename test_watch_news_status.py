"""
04.11.2026 · четвърти преглед, В1: наблюдаваните — провалът на новините / цените / Form 4 оставя следа (до 04.11 само ред в лога, а редът казваше „няма новини“).
  1. RSS на Yahoo с HTTP статус ≠ 200 (401 / 429 с HTML тяло) → None (не празен списък) и причината; РЕАЛНИЯТ фийд → новините, както досега;
  2. collect: news_checked / news_error на реда, LAST_STATUS (брояч и причина), без резервата yfinance .news;
  3. status_note: „частично“ над config.WATCH_PARTIAL_SHARE (и при паднал Form 4); единичен провал — само белегът на реда;
  4. страницата: белег „новините не се провериха“ на реда и един ред под таблицата.

РЕАЛНО: tests/fixtures/watch_yahoo_rss_AI_2026-10-29.xml и watch_yahoo_rss_SAP_2026-10-29.xml (RSS на Yahoo Finance, свалени 29.10.2026 в 18:49 UTC — бележката в test_watch_table);
tests/fixtures/watch_facts_2026-10-29.json (имената); tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): отговорите HTTP 429 / 401 (подменен requests.get), подменените facts / Form 4, широкият прозорец за новините.
Пускане: python test_watch_news_status.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_watchst_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import watch_monitor as wm, render, insider_buying

FXD = ROOT / "tests" / "fixtures"
FX = json.loads((FXD / "watch_facts_2026-10-29.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
rss = lambda t: (FXD / f"watch_yahoo_rss_{t}_2026-10-29.xml").read_bytes()
q = lambda: contextlib.redirect_stdout(io.StringIO())


class Resp:                                                     # СИНТЕТИЧНО: отговорът на requests.get
    def __init__(self, status, body):
        self.status_code, self.content = status, body


print("── 1. HTTP статус ≠ 200 → None и причината; РЕАЛНИЯТ фийд → новините ──")
assert not hasattr(wm, "_yf_news")                                                              # резервата е махната (от 29.10 връщаше нищо)
orig_get = wm.requests.get
try:
    wm.requests.get = lambda url, **k: Resp(429, b"<html><body>Too Many Requests</body></html>")
    wm._NEWS_FAIL.clear()
    with q():
        assert wm._rss_news("AI", 24 * 3650, {"C3.ai"}) is None
    assert wm._NEWS_FAIL["AI"] == "HTTP 429", wm._NEWS_FAIL
    wm.requests.get = lambda url, **k: Resp(200, rss("AI"))                                     # РЕАЛНИЯТ фийд през същия път
    got = wm._rss_news("AI", 24 * 3650, wm.company_keys(FX["info"]["AI"]["longName"]))
    assert isinstance(got, list) and got, got
finally:
    wm.requests.get = orig_get
print("  ✓ 429 → None („HTTP 429“); 200 с реалния фийд → списък с новини")

print("── 2. collect: news_checked / news_error и LAST_STATUS ──")
facts = lambda ts: {t: {"name": FX["info"].get(t, {}).get("longName"), "price": ({"close": 1.0, "chg_1d_pct": 0.5} if t != "SAP" else {}), "earnings": {}} for t in ts}   # СИНТЕТИЧНО
orig_ins = insider_buying.fetch_insider_transactions
insider_buying.fetch_insider_transactions = lambda ts: {}
try:
    wm.requests.get = lambda url, **k: (Resp(200, rss("SAP")) if "s=SAP" in url else Resp(401, b"<html>Unauthorized</html>"))
    with q():
        rows = wm.collect(["AI", "SAP", "ELF"], facts_fn=facts, window_hours=24 * 3650)
finally:
    wm.requests.get = orig_get
    insider_buying.fetch_insider_transactions = orig_ins
by = {r["ticker"]: r for r in rows}
assert by["SAP"]["news_checked"] is True and "news_error" not in by["SAP"] and by["SAP"]["news"], by["SAP"]
assert by["AI"]["news_checked"] is False and by["AI"]["news_error"] == "HTTP 401" and by["AI"]["news"] == [], by["AI"]
assert wm.LAST_STATUS == {"tickers": 3, "news_failed": {"AI": "HTTP 401", "ELF": "HTTP 401"}, "price_missing": ["SAP"], "insider_ok": True}, wm.LAST_STATUS
print("  ✓ SAP — проверени (реалният фийд); AI, ELF — „HTTP 401“, news_checked False; SAP без цени")

print("── 3. status_note: „частично“ над прага; единичен провал — None ──")
assert wm.status_note() == "новините не се провериха за 2 от 3 (HTTP 401)", wm.status_note()
assert wm.status_note({"tickers": 13, "news_failed": {"AI": "HTTP 429"}, "price_missing": [], "insider_ok": True}) is None
assert wm.status_note({"tickers": 13, "news_failed": {}, "price_missing": [], "insider_ok": False}) == "Form 4 не се провери"
assert wm.status_note({"tickers": 4, "news_failed": {}, "price_missing": ["A", "B"], "insider_ok": True}) == "без цени за 2 от 4"
assert wm.status_note({}) is None
print("  ✓ 2 от 3 → „частично“ с причината; 1 от 13 → само белегът; паднал Form 4 → „частично“")

print("── 4. страницата ──")
b = copy.deepcopy(B19); b["watch"] = rows
with q():
    page = render.render_dashboard(b, publish=False)
assert page.count(">новините не се провериха</span>") == 2, page.count(">новините не се провериха</span>")
assert "Новините не се провериха днес за: AI (HTTP 401), ELF (HTTP 401)" in page
print("  ✓ белегът на двата реда и редът под таблицата")
print("\n✅ test_watch_news_status: всичко мина")
