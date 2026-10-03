"""
Пакет 1, т.6 (2026-10-03): режимът ограничава Action — Cash → никакъв; Defensive → само при
Entry Timing "good" (0…+2% над pivot, с обем); Offensive → без ограничение.

РЕАЛЕН ред: EXEL, сигнален бар 26.06.2026 (бриф 29.06): close $54.77, pivot $53.93 (+1.56%), обем 2.49× —
от tests/fixtures (Yahoo, свалени на 02.10.2026). Граничните случаи (+2.00% / +2.01%, +3%) са
СИНТЕТИЧНИ — маркирани. Режимите са зададени от теста (не са от реален бриф).
Пускане: python test_regime_gate.py
"""
import sys, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import screener, setup_rules, entry_timing, watchlist_expiry
from src import main as brief_main

config.ENABLE_BACKTEST = False        # не чети реалния tracker

FIX = ROOT / "tests" / "fixtures"
df = pd.read_csv(FIX / "ohlc_EXEL.csv", index_col=0, parse_dates=True).loc[:"2026-06-26"]
spy = pd.read_csv(FIX / "ohlc_SPY.csv", index_col=0, parse_dates=True)["Close"].loc[:"2026-06-26"]
exel = screener._evaluate_technicals("EXEL", df, spy)
assert exel["price"] == 54.77 and exel["pivot"] == 53.93 and exel["breakout_volume"]
D = dt.date(2026, 6, 29)


def cand(row=None, **over):
    c = dict(row or exel)
    c.update({"company": c["ticker"] + " Corp", "sector": "Healthcare",
              "earnings": {"next_earnings": None, "days_to_earnings": None, "in_blackout": False},
              "options": {}, "short_view": {},
              "ai": {"classification": "Action", "why_now": "тест", "catalysts": [], "risks": []}})
    c.update(over)
    c["setup"] = setup_rules.classify_setup(c, D)
    return c


def run(c, regime):
    action, watch = brief_main.apply_hard_rules([c], 1.0, regime)
    return action, watch


print("── РЕАЛЕН EXEL (+1.56% над pivot, обем 2.49×): entry timing 'good' ──")
assert entry_timing.evaluate_pivot_volume(exel)["verdict"] == "good"
for regime in ("Offensive", "Defensive", None):
    a, w = run(cand(), regime)
    assert [x["ticker"] for x in a] == ["EXEL"] and not w, (regime, a, w)
a, w = run(cand(), "Cash")
assert not a and [x["ticker"] for x in w] == ["EXEL"]
assert w[0]["ai"]["watchlist_reason_type"] == "regime_block" and "Режим Cash" in w[0]["ai"]["watchlist_trigger"]
print("  ✓ Offensive / Defensive / без режим → Action; Cash → Watchlist 'regime_block' (Режим Cash — нов Action не се дава)")
print()

print("── СИНТЕТИЧНО: граници на entry timing в Defensive ──")
def synth(pct, vol=2.0):
    pivot = 100.0
    return cand({"ticker": "SYN", "price": round(pivot * (1 + pct / 100), 2), "pivot": pivot,
                 "pct_from_pivot": pct, "volume_ratio": vol, "breakout_volume": vol >= config.BREAKOUT_VOLUME_MULT,
                 "struct_low": 96.0})
a, w = run(synth(2.0), "Defensive");  assert len(a) == 1 and not w          # +2.00% още е "good"
a, w = run(synth(2.01), "Defensive")
assert not a and w[0]["ai"]["watchlist_reason_type"] == "regime_block"
assert "Режим Defensive" in w[0]["ai"]["watchlist_trigger"] and "Extended +2.0% над pivot" in w[0]["ai"]["watchlist_trigger"]
a, w = run(synth(3.0), "Offensive");  assert len(a) == 1                     # Offensive не ограничава
a, w = run(synth(3.0), "Defensive");  assert not a and w
print("  ✓ +2.00% → Action в Defensive; +2.01% и +3.0% → Watchlist 'regime_block' (текстът казва защо); Offensive — без ограничение")
print()

print("── ред на проверките, лимити и подредба ──")
too_wide = cand({**exel, "struct_low": 40.0})                   # СИНТЕТИЧЕН struct_low → твърде разтегнат
a, w = run(too_wide, "Cash")
assert not a and w[0]["ai"]["watchlist_reason_type"] == "technical_gate"       # техническият gate е първи
# блокираните от режима не заемат Action слот: в Defensive лимит 1 + един блокиран
orig_max = config.MAX_ACTION_TICKERS
config.MAX_ACTION_TICKERS = 1
good, blocked = synth(1.0), synth(3.0)
good["ticker"], blocked["ticker"] = "GOOD", "BLCK"
action, watch = brief_main.apply_hard_rules([blocked, good], 1.0, "Defensive")
config.MAX_ACTION_TICKERS = orig_max
assert [x["ticker"] for x in action] == ["GOOD"] and [x["ticker"] for x in watch] == ["BLCK"]
# подредба: потвърден пробив, спрян от режима, е преди buy-stop кандидат
below = cand({"ticker": "BELOW", "price": 98.0, "pivot": 100.0, "pct_from_pivot": -2.0, "volume_ratio": 1.0,
              "breakout_volume": False, "struct_low": 95.0})
below["ai"]["classification"] = "Watchlist"
action, watch = brief_main.apply_hard_rules([below, synth(3.0)], 1.0, "Defensive")
assert [x["ticker"] for x in watch] == ["SYN", "BELOW"], [x["ticker"] for x in watch]
print("  ✓ техническият gate е преди режимния; блокиран кандидат не заема Action слот; потвърден пробив, спрян от")
print("    режима, е пред buy-stop кандидата във Watchlist")
print()

print("── 'regime_block' не изтича като 'regime_gate' (watchlist_expiry) ──")
with tempfile.TemporaryDirectory() as tmp:
    orig_state = watchlist_expiry._STATE_PATH
    orig_dir = config.DATA_DIR
    watchlist_expiry._STATE_PATH = pathlib.Path(tmp) / "watchlist_expiry.json"
    config.DATA_DIR = pathlib.Path(tmp)
    try:
        blocked = cand(synth(3.0)); blocked["ticker"] = "BLCK"
        blocked["ai"].update(watchlist_reason_type="regime_block", watchlist_trigger="код")
        ai_gate = cand(synth(3.0)); ai_gate["ticker"] = "AIGT"
        ai_gate["ai"].update(watchlist_reason_type="regime_gate", watchlist_trigger="AI")
        day0 = watchlist_expiry.apply_regime_gate_expiry([blocked, ai_gate], "Defensive", "2026-10-01")
        assert {x["ticker"] for x in day0} == {"BLCK", "AIGT"}
        later = "2026-10-%02d" % (1 + config.WATCHLIST_STALENESS_DAYS + 1)       # след прозореца
        day_n = watchlist_expiry.apply_regime_gate_expiry([blocked, ai_gate], "Defensive", later)
        assert [x["ticker"] for x in day_n] == ["BLCK"], [x["ticker"] for x in day_n]
    finally:
        watchlist_expiry._STATE_PATH = orig_state
        config.DATA_DIR = orig_dir
print(f"  ✓ след {config.WATCHLIST_STALENESS_DAYS + 1} дни в Defensive 'regime_gate' (AI) изтича, 'regime_block' (код) остава")

config.ENABLE_BACKTEST = True
print()
print("Всички тестове минаха.")
