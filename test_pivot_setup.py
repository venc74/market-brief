"""
Пакет 1, т.1 (2026-10-02): pivot без последните 5 бара, потвърден пробив (close над
pivot + обем >= BREAKOUT_VOLUME_MULT), buyable zone до +5%, extended, Watchlist с
buy-stop ниво.

РЕАЛНИ примери (tests/fixtures/ohlc_*.csv — дневни барове от Yahoo, auto_adjust=True,
свалени на 02.10.2026; със стойностите на брифовете от 22.09 и 29.06 съвпадат до цент):
  22.09.2026  AMD, TWLO   (стар Action: pivot 616.69 / 266.48, -0.19% / -0.16%)
  29.06.2026  LNTH, EXEL  (LNTH стар Watchlist, EXEL стар Action)
Граничните случаи (pivot точно, обем точно на прага, +5.00% / +5.01%, празници) са
СИНТЕТИЧНИ — маркирани като такива.

Пускане: python test_pivot_setup.py
"""
import sys, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import screener, setup_rules, main as brief_main, thermometer
from src import render

FIX = ROOT / "tests" / "fixtures"


def load(t):
    return pd.read_csv(FIX / f"ohlc_{t}.csv", index_col=0, parse_dates=True)


def row_at(sym, last_bar):
    """screener._evaluate_technicals върху РЕАЛНИТЕ барове до сигналния бар."""
    df = load(sym).loc[:last_bar]
    spy = load("SPY")["Close"].loc[:last_bar]
    r = screener._evaluate_technicals(sym, df, spy)
    assert r is not None, f"{sym} {last_bar}: не мина технически филтър"
    return r


def tight(r):
    """
    СИНТЕТИЧНО: реалният ред + тесен структурен low (5% под входа), за да остане т.1
    (pivot/обем/extended) изолирана от стопа (т.3). Реалните struct_low стойности са
    в test_stop_plan.py. Всички други полета (цена, pivot, обем) са РЕАЛНИ.
    """
    return {**r, "struct_low": round(max(r["price"], r["pivot"]) * 0.95, 2)}


print("── compute_pivot (СИНТЕТИЧНО) ──")
def series(n=120, base=100.0):
    return pd.Series([base] * n, dtype=float)

h = series(); h.iloc[-3] = 150.0           # пик в последните 5 бара → НЕ се брои
assert screener.compute_pivot(h) == 100.0
h = series(); h.iloc[-5] = 150.0           # точно 5-ият от края → още изключен
assert screener.compute_pivot(h) == 100.0
h = series(); h.iloc[-6] = 150.0           # 6-ият от края → вече е в базата
assert screener.compute_pivot(h) == 150.0
h = series(); h.iloc[-65] = 150.0          # най-старият бар на 65-барова база → включен
assert screener.compute_pivot(h) == 150.0
h = series(); h.iloc[-66] = 150.0          # извън базата
assert screener.compute_pivot(h) == 100.0
print("  ✓ пик в -3 и -5 не се брои; -6 и -65 се броят; -66 е извън базата")

orig_n = config.PIVOT_EXCLUDE_LAST_BARS
config.PIVOT_EXCLUDE_LAST_BARS = 0
h = series(); h.iloc[-1] = 150.0
assert screener.compute_pivot(h) == 150.0   # N=0 = старото поведение (включва сигналния бар)
config.PIVOT_EXCLUDE_LAST_BARS = orig_n
print("  ✓ N=0 връща старото поведение (сигналният бар е в pivot-а)")
print()

print("── classify_setup граници (СИНТЕТИЧНО) ──")
T = dt.date(2026, 9, 30)
base = {"ticker": "SYN", "pivot": 100.00, "breakout_volume": True, "volume_ratio": 1.8}

def cs(**kw):
    return setup_rules.classify_setup({**base, **kw}, T)

s = cs(price=100.00)                                  # close == pivot → НЕ е пробив
assert s["kind"] == "below_pivot" and not s["eligible"] and s["buy_stop"] == 100.00
s = cs(price=100.01)                                  # един цент над → пробив
assert s["kind"] == "confirmed" and s["eligible"] and s["buy_stop"] is None
s = cs(price=102.0, breakout_volume=False, volume_ratio=1.49)   # обем под прага
assert s["kind"] == "no_volume" and not s["eligible"]
s = cs(price=102.0, volume_ratio=1.5)                 # без флаг: обем точно 1.5× → потвърден
s2 = setup_rules.classify_setup({"ticker": "S", "pivot": 100.0, "price": 102.0, "volume_ratio": 1.5}, T)
assert s2["kind"] == "confirmed"
s2 = setup_rules.classify_setup({"ticker": "S", "pivot": 100.0, "price": 102.0, "volume_ratio": 1.49}, T)
assert s2["kind"] == "no_volume"
s = cs(price=105.00)                                  # точно +5.00% → още в buyable zone
assert s["kind"] == "confirmed" and s["max_chase"] == 105.00
s = cs(price=105.01)                                  # +5.01% → extended
assert s["kind"] == "extended" and not s["eligible"]
s = cs(price=95.0)                                    # 5% под pivot → buy-stop кандидат
assert s["kind"] == "below_pivot" and s["buy_stop"] == 100.0 and "buy-stop $100.00" in s["trigger_text"]
s = setup_rules.classify_setup({"ticker": "S"}, T)    # без данни
assert s["kind"] == "no_data" and not s["eligible"]
print("  ✓ close==pivot → below_pivot; +0.01 → confirmed; обем 1.49 → no_volume, 1.50 → confirmed;")
print("    +5.00% още buyable, +5.01% → extended; без данни → no_data (никога Action)")
print()

print("── прозорец от сесии (СИНТЕТИЧНО, но с РЕАЛНИТЕ празници на NYSE) ──")
# петък 12.06 → събота-бриф 13.06: сесии 15,16,17,18 и (19.06 е Juneteenth — празник) 22.06
w = setup_rules.session_window("2026-06-13", 5)
assert [d.isoformat() for d in w] == ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-22"], w
# сряда-бриф: сесията на брифа е ПЪРВАТА (включена)
w = setup_rules.session_window("2026-09-30", 5)
assert [d.isoformat() for d in w] == ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"], w
# понеделник на Labor Day (07.09.2026, празник) → първата сесия е 08.09
assert setup_rules.session_window("2026-09-07", 1)[0].isoformat() == "2026-09-08"
print("  ✓ 13.06 (събота) → 15,16,17,18,22.06 (19.06 празник); 30.09 → включва деня на брифа; 07.09 празник → 08.09")
print()

print("── РЕАЛНИ примери през screener._evaluate_technicals + classify_setup ──")
amd = tight(row_at("AMD", "2026-09-21"))
twlo = tight(row_at("TWLO", "2026-09-21"))
lnth = tight(row_at("LNTH", "2026-06-26"))
exel = tight(row_at("EXEL", "2026-06-26"))
for name, r in (("AMD 22.09", amd), ("TWLO 22.09", twlo), ("LNTH 29.06", lnth), ("EXEL 29.06", exel)):
    print(f"  {name}: цена {r['price']} pivot {r['pivot']} ({r['pct_from_pivot']:+.2f}%) обем {r['volume_ratio']}× "
          f"→ {setup_rules.classify_setup(r, dt.date(2026, 9, 22))['kind']}")

# цената и новият pivot (без последните 5 бара) — стойностите от реплея
assert amd["price"] == 615.52 and amd["pivot"] == 584.73 and 5.2 < amd["pct_from_pivot"] < 5.3
assert twlo["price"] == 266.06 and twlo["pivot"] == 258.35 and not twlo["breakout_volume"]
assert lnth["price"] == 109.80 and lnth["pivot"] == 107.99 and lnth["breakout_volume"]
assert exel["price"] == 54.77 and exel["pivot"] == 53.93 and exel["breakout_volume"]
assert setup_rules.classify_setup(amd, dt.date(2026, 9, 22))["kind"] == "extended"        # +5.3% > +5%
assert setup_rules.classify_setup(twlo, dt.date(2026, 9, 22))["kind"] == "no_volume"      # 1.42× < 1.5×
assert setup_rules.classify_setup(lnth, dt.date(2026, 6, 29))["kind"] == "confirmed"
assert setup_rules.classify_setup(exel, dt.date(2026, 6, 29))["kind"] == "confirmed"
# старото поведение за контраст: pivot включваше последните бара → под pivot
config.PIVOT_EXCLUDE_LAST_BARS = 0
old_amd = row_at("AMD", "2026-09-21")
config.PIVOT_EXCLUDE_LAST_BARS = orig_n
assert old_amd["pivot"] == 616.69 and old_amd["pct_from_pivot"] == -0.19          # както в брифа от 22.09
print("  ✓ реалните стойности съвпадат: AMD extended (+5.3%), TWLO без обем (1.42×), LNTH и EXEL потвърдени;")
print("    със старата дефиниция AMD е -0.19% под pivot 616.69 (точно като в брифа от 22.09)")
print()

print("── apply_hard_rules: кодът връща във Watchlist всичко, което не е потвърден пробив ──")
config.ENABLE_BACKTEST = False        # не чети реалния data/backtest_tracker.json


def cand(r, sector, **kw):
    c = dict(r)
    c.update({"company": r["ticker"] + " Corp", "sector": sector,
              # празни enrich блокове — само колкото шаблонът да рендерира картата
              "earnings": {"next_earnings": None, "days_to_earnings": None, "in_blackout": False},
              "options": {}, "short_view": {},
              "ai": {"classification": "Action", "why_now": "тест", "catalysts": [], "risks": []}})
    c.update(kw)
    return c


c_amd, c_twlo = cand(amd, "Technology"), cand(twlo, "Technology")
c_lnth, c_exel = cand(lnth, "Healthcare"), cand(exel, "Healthcare")
below = cand({**lnth, "ticker": "BELOW", "price": 105.0, "pivot": 107.99, "pct_from_pivot": -2.78,
              "breakout_volume": False, "struct_low": 100.0}, "Industrials")   # СИНТЕТИЧЕН: под pivot
for c in (c_amd, c_twlo, c_lnth, c_exel, below):
    c["setup"] = setup_rules.classify_setup(c, dt.date(2026, 9, 29))
action, watch = brief_main.apply_hard_rules([c_amd, c_twlo, c_lnth, c_exel, below], 1.0)
assert [a["ticker"] for a in action] == ["LNTH", "EXEL"], [a["ticker"] for a in action]
assert [w["ticker"] for w in watch] == ["BELOW", "TWLO", "AMD"], [w["ticker"] for w in watch]   # below → no_volume → extended
for w in watch:
    assert w["ai"]["watchlist_reason_type"] == "technical_gate" and w["ai"]["watchlist_trigger"] == w["setup"]["trigger_text"]
assert "buy-stop $107.99" in below["ai"]["watchlist_trigger"]
print("  ✓ Action: LNTH, EXEL (потвърдени). Watchlist по ред: BELOW (buy-stop $107.99) → TWLO (без обем) → AMD (extended)")

# AI-то казва Watchlist за потвърден кандидат → остава Watchlist (кодът само ограничава)
c2 = cand(lnth, "Healthcare"); c2["ai"]["classification"] = "Watchlist"; c2["ai"]["watchlist_trigger"] = "AI: чака"
c2["setup"] = setup_rules.classify_setup(c2, dt.date(2026, 6, 29))
a2, w2 = brief_main.apply_hard_rules([c2], 1.0)
assert not a2 and w2[0]["ai"]["watchlist_trigger"] == "AI: чака"
print("  ✓ потвърден кандидат, който AI е сложило във Watchlist, остава Watchlist (кодът само ограничава)")

# Watchlist лимит 10: подредбата решава кои 10 влизат (СИНТЕТИЧНО: 12 кандидата)
many = []
for i in range(12):
    kind_price = {0: 90.0, 1: 102.0, 2: 108.0}[i % 3]     # под pivot / над без обем / extended
    c = cand({**lnth, "ticker": f"S{i:02d}", "price": kind_price, "pivot": 100.0, "pct_from_pivot": kind_price - 100,
              "breakout_volume": False, "struct_low": round(max(kind_price, 100.0) * 0.95, 2)}, "Industrials")
    c["ai"]["classification"] = "Watchlist"
    c["setup"] = setup_rules.classify_setup(c, dt.date(2026, 9, 29))
    many.append(c)
_, wl = brief_main.apply_hard_rules(many, 1.0)
kinds = [w["setup"]["kind"] for w in wl]
assert len(wl) == 10 and kinds.count("extended") == 2 and kinds[:4] == ["below_pivot"] * 4, kinds
print("  ✓ при 12 кандидата Watchlist е 10: четирите buy-stop първи, extended най-отзад (изрязват се първи)")
print()

print("── screener приоритет и dashboard (СИНТЕТИЧНО за подредбата, РЕАЛНИ за картите) ──")
rows = [{**amd}, {**twlo}, {**lnth}, {**below}]
rows.sort(key=setup_rules.screen_priority)
assert [r["ticker"] for r in rows] == ["LNTH", "TWLO", "BELOW", "AMD"], [r["ticker"] for r in rows]
print("  ✓ run_screen подредба: потвърден (LNTH) → над pivot без обем (TWLO) → под pivot (BELOW) → extended (AMD)")

brief = {"date": "2026-09-29", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")),
         "action": action, "watchlist": watch,
         "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
with tempfile.TemporaryDirectory() as tmp:
    orig_docs = config.DOCS_DIR
    config.DOCS_DIR = pathlib.Path(tmp)
    try:
        html = render.render_dashboard(brief)
    finally:
        config.DOCS_DIR = orig_docs
assert "Buy-stop $107.99" in html and "валиден до 2026-10-05" in html, "buy-stop редът липсва на Watchlist картата"
assert html.count("🎯 Buy-stop") == 1                                     # само за below_pivot, не за TWLO/AMD
assert "Extended: +5.3% над pivot $584.73" in html or "Extended: +5.3%" in html
print("  ✓ dashboard: Watchlist картата на BELOW показва 'Buy-stop $107.99 · валиден до 2026-10-05' (само тя); extended/no_volume — причината")

config.ENABLE_BACKTEST = True
print()
print("Всички тестове минаха.")
