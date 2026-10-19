"""
19.10.2026 · етап 2, доп. т. 2: straddle за отчета и при НОВА карта. Снимката (oi_snapshot) теглеше straddle-и само за тогавашните карти, затова AAPL на 19.10 получи "тикърът не е в опционната
снимка", докато UOV✓ на същата карта идва от същата снимка (AAPL е в референтната кошница). (а) straddle-и и за кошницата, щом отчетът е в прозореца (веригите ѝ така или иначе се теглят);
(б) иначе вярна причина: "картата е нова — при снимката на ДД.ММ не беше сред кандидатите" (AMGN) или "при снимката на ДД.ММ няма straddle за този отчет" (в снимката, без straddle).

РЕАЛНО: tests/fixtures/oi_snapshot_2026-10-16.json — снимката за сесия 16.10 (66 тикъра, кошница 55, straddle-и за 14 наши; AAPL — в кошницата, AMGN — не);
tests/fixtures/brief_2026-10-19.json — картите на AAPL (UOV✓, отчет 02.11) и AMGN (отчет 03.11) с "тикърът не е в опционната снимка". СИНТЕТИЧНО: няма.
Пускане: python test_earnings_straddle_reason.py
"""
import sys, json, copy, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import earnings_move as em

SNAP = json.loads((ROOT / "tests" / "fixtures" / "oi_snapshot_2026-10-16.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
cards = {c["ticker"]: copy.deepcopy(c) for c in B19["watchlist"] if c["ticker"] in ("AAPL", "AMGN")}
assert "AAPL" in SNAP["reference"] and "AAPL" not in SNAP["straddles"] and "AMGN" not in SNAP["tickers"]
assert [m["tag"] for m in cards["AAPL"]["markers"]] == ["UOV✓"] and "тикърът не е в опционната снимка" in cards["AAPL"]["earnings_warning"]["text"]   # какво казваше брифът

print("── (б) вярната причина (РЕАЛНИТЕ снимка от 16.10 и карти от 19.10) ──")
for c in cards.values():
    c.pop("earnings_warning", None)
n = em.annotate(list(cards.values()), today=dt.date(2026, 10, 19), snapshot_loader=lambda: (SNAP, "2026-10-16", ""))
assert n == 2
assert cards["AAPL"]["earnings_warning"]["text"] == "⚠ Отчет на 02.11 (след 10 сесии) — няма данни за очаквано движение (при снимката на 16.10 няма straddle за този отчет)."
assert cards["AMGN"]["earnings_warning"]["text"] == "⚠ Отчет на 03.11 (след 11 сесии) — няма данни за очаквано движение (картата е нова — при снимката на 16.10 не беше сред кандидатите)."
print("  ✓ AAPL: 'при снимката на 16.10 няма straddle за този отчет'; AMGN: 'картата е нова — при снимката на 16.10 не беше сред кандидатите' (беше 'тикърът не е в опционната снимка')")

print()
print("── (а) снимката взема straddle-и и за кошницата ──")
src = (ROOT / "src" / "oi_snapshot.py").read_text(encoding="utf-8")
assert "earnings_move.snapshot_straddles(own + [t for t in reference if t not in own], session, uo.yf)" in src
seen = {}
em.dates_from_briefs = lambda max_briefs=None: {"AAPL": "2026-11-02", "ZBRA": "2026-11-03"}                     # датите от картите (РЕАЛНИТЕ от 19.10)
em.snapshot_straddle = lambda tk, d, session, spot=None: seen.setdefault(tk, d)
class _Y:
    @staticmethod
    def Ticker(s): return s
out = em.snapshot_straddles(["ZBRA"] + ["AAPL"], dt.date(2026, 10, 16), _Y, today=dt.date(2026, 10, 16))
assert set(out) == {"ZBRA", "AAPL"} and seen == {"ZBRA": "2026-11-03", "AAPL": "2026-11-02"}
print("  ✓ take_snapshot подава и кошницата; AAPL (отчет 02.11 — в прозореца от 16.10) получава straddle")
print("\n✅ test_earnings_straddle_reason: всичко мина")
