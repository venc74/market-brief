"""
03.11.2026 · поправки след брифа, т. 3: прогнозната дата на отчета. Yahoo маркира датата като прогнозна (quoteSummary calendarEvents → earnings.isEarningsDateEstimate), но tk.calendar
губи флага. AMG: брифовете 09.10–02.11 казваха „Отчет на 02.11“ — прогнозата на Yahoo; компанията обяви 09.11 (на 03.11 Yahoo: 09.11, isEarningsDateEstimate false). Сега
enrich.calendar_events чете същата заявка с флага; enrich.earnings_info → earnings_estimate (True / False / None — датата е от get_earnings_dates); картите, предупреждението,
причината на радара и наблюдаваните пишат „~ДД.ММ (прогноза)“. Правилото за отчета (нов Action най-рано след отчета) НЕ се променя — прогнозната дата се третира като дата
(предпазливо), само се казва, че е прогноза. Измерено на живо на 03.11 (26 тикъра от картите и наблюдаваните): 8 прогнозни, 10 потвърдени, 8 без флаг (от get_earnings_dates).

РЕАЛНО: tests/fixtures/yahoo_calendar_events_2026-11-03.json — отговорът calendarEvents на Yahoo за AMG (09.11, false), AAPL (28.01.2027, true), EXPD (03.11, false), 03.11.2026.
СИНТЕТИЧНО (означено): подменените обекти на yfinance, датите в т. 4–5 (AMG на 29.10 с прогнозна 02.11 — флагът тогава не се пазеше), картата на радара.
Пускане: python test_earnings_estimate.py
"""
import sys, json, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_earn_est_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import enrich, earnings_move, render

RAW = json.loads((ROOT / "tests" / "fixtures" / "yahoo_calendar_events_2026-11-03.json").read_text(encoding="utf-8"))["raw"]
q = lambda: contextlib.redirect_stdout(io.StringIO())


class _Q:
    def __init__(self, raw): self.raw = raw
    def _fetch(self, modules): return self.raw


class _Tk:                                                                                     # СИНТЕТИЧНО: yf.Ticker с РЕАЛНИЯ отговор на calendarEvents
    def __init__(self, raw, info_ok=True):
        self._quote, self.info_ok = _Q(raw), info_ok
    def get_earnings_dates(self, limit=8): return None
    @property
    def info(self):
        if not self.info_ok:
            raise AssertionError(".info не бива да се вика (with_info=False)")
        return {"epsCurrentYear": 1.0}


print("── 1. calendar_events — РЕАЛНИТЕ отговори на Yahoo от 03.11 ──")
amg, aapl, expd = (enrich.calendar_events(_Tk(RAW[t])) for t in ("AMG", "AAPL", "EXPD"))
assert amg == ({"Earnings Date": [dt.date(2026, 11, 9)]}, False) and expd == ({"Earnings Date": [dt.date(2026, 11, 3)]}, False)
assert aapl == ({"Earnings Date": [dt.date(2027, 1, 28)]}, True)
class _Old:                                                                                    # СИНТЕТИЧНО: без частния _quote → tk.calendar, флагът — неизвестен
    calendar = {"Earnings Date": [dt.date(2026, 11, 9)]}
assert enrich.calendar_events(_Old()) == ({"Earnings Date": [dt.date(2026, 11, 9)]}, None) and enrich.calendar_events(_Tk(None)) == (None, None)
print("  ✓ AMG 09.11 — потвърдена · AAPL 28.01.2027 — прогнозна · EXPD 03.11 — потвърдена; без частния достъп → tk.calendar без флага")

print()
print("── 2. earnings_info → earnings_estimate; with_info=False не вика .info ──")
real = enrich.yf.Ticker
now = dt.datetime(2026, 11, 3, 6, 30, tzinfo=dt.timezone.utc)
enrich.earnings_recap = lambda sym: None
try:
    enrich.yf.Ticker = lambda s: _Tk(RAW["AAPL"], info_ok=False)
    with q():
        e = enrich.earnings_info("AAPL", now=now, with_info=False)
    assert (e["next_earnings"], e["earnings_estimate"], e["eps_estimate"], e["earnings_status"]) == ("2027-01-28", True, None, "ok"), e
    enrich.yf.Ticker = lambda s: _Tk(RAW["AMG"])
    with q():
        e2 = enrich.earnings_info("AMG", now=now)
    assert (e2["next_earnings"], e2["earnings_estimate"], e2["eps_estimate"]) == ("2026-11-09", False, 1.0)
finally:
    enrich.yf.Ticker = real
print("  ✓ AAPL → 2027-01-28, earnings_estimate True, без .info; AMG → 2026-11-09, False (с .info за картите)")

print()
print("── 3. надписът ──")
assert enrich.earnings_dm("2027-01-28", True) == "~28.01 (прогноза)" and enrich.earnings_dm("2026-11-09", False) == "09.11" and enrich.earnings_dm(None, True) == ""
print("  ✓ „~28.01 (прогноза)“ / „09.11“")

print()
print("── 4. предупреждението на картата (СИНТЕТИЧНО: AMG на 29.10 с прогнозната 02.11 — както брифовете 09.10–02.11) ──")
w = earnings_move.warning_for("2026-11-02", dt.date(2026, 10, 29), None, "няма снимка", estimate=True)
assert w["text"] == "⚠ Отчет на ~02.11 (прогноза) (след 2 сесии) — няма данни за очаквано движение (няма снимка)." and w["estimate"] is True
assert earnings_move.warning_for("2026-11-09", dt.date(2026, 11, 3), None, "няма снимка")["text"].startswith("⚠ Отчет на 09.11 (след 4 сесии)")
print("  ✓ „⚠ Отчет на ~02.11 (прогноза) (след 2 сесии) — …“; потвърдената — без „~“")

print()
print("── 5. радарът и текстът на картата; правилото за отчета — непроменено (СИНТЕТИЧНО) ──")
card = {"ticker": "X", "setup": {"kind": "confirmed"}, "ai": {"watchlist_reason_type": "earnings_blackout"},
        "earnings": {"next_earnings": "2026-11-05", "days_to_earnings": 2, "earnings_estimate": True}}
assert render.radar_reason(card) == "отчет на ~05.11 (прогноза) (2 дни) — вход след отчета"
card["earnings"]["earnings_estimate"] = False
assert render.radar_reason(card) == "отчет на 05.11 (2 дни) — вход след отчета"
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'ne = enrich_mod.earnings_dm(e.get("next_earnings"), e.get("earnings_estimate"))' in main_src
w_src = (ROOT / "src" / "watch_monitor.py").read_text(encoding="utf-8")
assert "enrich.earnings_info(x, with_info=False)" in w_src and '"estimate": e.get("earnings_estimate")' in w_src
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert '{% if e.estimate %}~{% endif %}{{ e.next[8:10] }}.{{ e.next[5:7] }}{% if e.estimate %} <span class="wt-mu">(прогноза)</span>{% endif %}' in tpl
print("  ✓ радарът: „отчет на ~05.11 (прогноза) (2 дни) — вход след отчета“; текстът на картата и наблюдаваните — същият надпис; наблюдаваните — без .info")
print("\n✅ test_earnings_estimate: всичко мина")
