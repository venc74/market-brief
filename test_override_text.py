"""
Тест за т.1 от 02.10: текстът на override в хистерезис описва реалното
състояние ("MOVE 108 > 150" беше невярно — 108 < 150), а regime_reason
показва първо реално активния тригер, после тези в хистерезис.

РЕАЛНИ данни: индикаторите и macro са КОПИРАНИ от data/2026-10-02.json
(бриф от 02.10). Състоянието на хистерезиса преди run-а (MOVE spike падна под
прага за първи път, IEI/HYG spike още активен) е възстановено в tempdir —
реалният data/regime_override_state.json не се пипа. Синтетичните случаи са
маркирани.

Пускане: python test_override_text.py
"""
import sys, json, pathlib, tempfile, datetime as dt
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src import thermometer as th

REAL = json.load(open(pathlib.Path(__file__).parent / "tests" / "fixtures" / "brief_2026-10-02.json", encoding="utf-8"))
REAL_IND = {i["name"]: i for i in REAL["thermometer"]["indicators"]}


def run_with(ind_overrides: dict, prior_state: dict, today: dt.date):
    """build_thermometer с подменени индикатори (без мрежа) и state в tempdir."""
    ind = {k: dict(v) for k, v in REAL_IND.items()}
    for name, patch in ind_overrides.items():
        ind[name].update(patch)
    saved = {n: getattr(th, n) for n in ("spy_trend", "vix_level", "market_put_call", "move_index",
                                         "vix_term_structure", "credit_spread_proxy",
                                         "market_breadth", "_breadth_divergence")}
    th.spy_trend = lambda: ind["SPY тренд"]
    th.vix_level = lambda: ind["VIX"]
    th.market_put_call = lambda: ind["Put/Call (SPY)"]
    th.move_index = lambda: ind["MOVE (Bond Vol)"]
    th.vix_term_structure = lambda: ind["VIX Term Structure"]
    th.credit_spread_proxy = lambda: ind["IEI/HYG (Credit Spread)"]
    th.market_breadth = lambda: ind["Market Breadth (% над 40dMA)"]
    th._breadth_divergence = lambda _i: None
    orig_file = th._OVERRIDE_STATE_FILE
    with tempfile.TemporaryDirectory() as tmp:
        th._OVERRIDE_STATE_FILE = pathlib.Path(tmp) / "state.json"
        th._OVERRIDE_STATE_FILE.write_text(json.dumps(prior_state))
        try:
            return th.build_thermometer(REAL["macro"], today=today)
        finally:
            th._OVERRIDE_STATE_FILE = orig_file
            for n, f in saved.items():
                setattr(th, n, f)


print("── РЕАЛНИ данни (02.10.2026, data/2026-10-02.json) ──")
PRIOR_REAL = {"move_spike": {"streak_below": 0, "last_date": "2026-10-01"},
              "credit_spike": {"streak_below": 0, "last_date": "2026-10-01"}}
t = run_with({}, PRIOR_REAL, dt.date(2026, 10, 2))
print("  regime_reason:", t["regime_reason"])
by = {o["trigger"]: o for o in t["overrides"]}
assert t["regime"] == "Defensive" and t["regime_by_count"] == "Defensive"
assert by["MOVE"]["state"] == "hysteresis" and by["IEI/HYG"]["state"] == "active"
assert [o["trigger"] for o in t["overrides"]] == ["IEI/HYG", "MOVE"], "активният първо"
assert t["regime_reason"].startswith("IEI/HYG credit spread spike (+1.2% за 10д, 96. percentile)")
assert "> 150" not in t["regime_reason"] and "> 150" not in by["MOVE"]["text"], "невярно '> 150'"
assert "спайкът отшумява (делта +3.5 пункта" in by["MOVE"]["text"] and "хистерезис 1/2" in by["MOVE"]["text"]
assert t["regime_reason"].index("IEI/HYG") < t["regime_reason"].index("MOVE")
print("  ✓ първо активният IEI/HYG (96. percentile), после MOVE в хистерезис 1/2, без '> 150'")
print()

print("── СИНТЕТИЧНИ случаи (реалните индикатори от 02.10 с променени полета) ──")
# MOVE над 150 (синтетично ниво 160) → active, 'MOVE 160 > 150'
t = run_with({"MOVE (Bond Vol)": {"value": 160.0, "status": "red"},
              "IEI/HYG (Credit Spread)": {"spike": False, "status": "green", "roc_percentile": 50.0}},
             {"move_spike": {"streak_below": 1, "last_date": "2026-10-01"},
              "credit_spike": {"streak_below": 5, "last_date": "2026-10-01"}}, dt.date(2026, 10, 2))
mv = {o["trigger"]: o for o in t["overrides"]}["MOVE"]
assert mv["state"] == "active" and "MOVE 160 > 150" in mv["text"], mv
print("  ✓ синт.: MOVE 160 → 'MOVE 160 > 150', active")

# raw spike (синтетична делта +20) → 'рязък седмичен скок', без '> 150'
t = run_with({"MOVE (Bond Vol)": {"spike": True, "delta_1w": 20.0, "status": "red"},
              "IEI/HYG (Credit Spread)": {"spike": False, "status": "green", "roc_percentile": 50.0}},
             PRIOR_REAL, dt.date(2026, 10, 2))
mv = {o["trigger"]: o for o in t["overrides"]}["MOVE"]
assert mv["state"] == "active" and "рязък седмичен скок, +20.0" in mv["text"] and "> 150" not in mv["text"], mv
print("  ✓ синт.: нов спайк +20 → active 'рязък седмичен скок', без '> 150'")

# и двата в хистерезис, нищо активно → водещ е първият хистерезисен, другият "също в хистерезис"
t = run_with({"IEI/HYG (Credit Spread)": {"spike": False, "status": "yellow", "roc_percentile": 85.0, "roc_10d_pct": 0.8}},
             {"move_spike": {"streak_below": 0, "last_date": "2026-10-01"},
              "credit_spike": {"streak_below": 0, "last_date": "2026-10-01"}}, dt.date(2026, 10, 2))
assert all(o["state"] == "hysteresis" for o in t["overrides"]) and len(t["overrides"]) == 2
assert t["regime"] == "Defensive" and "също в хистерезис" in t["regime_reason"]
print("  ✓ синт.: и двата в хистерезис → Defensive, reason показва и двата")

# 2-ри пореден ден под прага → MOVE override изчезва (хистерезисът изтича)
t = run_with({"IEI/HYG (Credit Spread)": {"spike": False, "status": "green", "roc_percentile": 40.0}},
             {"move_spike": {"streak_below": 1, "last_date": "2026-10-01"},
              "credit_spike": {"streak_below": 9, "last_date": "2026-10-01"}}, dt.date(2026, 10, 2))
assert not any(o["trigger"] == "MOVE" for o in t["overrides"]), t["overrides"]
print("  ✓ синт.: 2-ри пореден ден под прага → override-ът пада")

print()
print("Всички тестове минаха.")
