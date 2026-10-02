"""
Спешни находки 1-3 от прегледа (само четене, main 8eb4649): скрити индикатори
в термометъра.

  т.1 KeyError при скрит IEI/HYG (и MOVE) докато хистерезисът държи override;
      + fallback "Defensive (термометърът е недостъпен)", ако термометърът гръмне.
  т.2 (допълва се в следващия commit) минимум видими индикатори за Offensive.
  т.3 (допълва се в следващия commit) хистерезисът не брои скрит ден за спокоен.

РЕАЛНИ данни: индикаторите от data/2026-10-02.json; формата на СКРИТ индикатор е
копирана от data/2026-09-08.json (реален ден с 4 скрити). Състоянието на
хистерезиса и комбинациите "вчера spike + днес скрит" са СИНТЕТИЧНИ
(маркирани), в tempdir — реалният data/regime_override_state.json не се пипа.

Пускане: python test_thermometer_hidden.py
"""
import sys, json, pathlib, tempfile, datetime as dt, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import thermometer as th

REAL = json.load(open(ROOT / "data" / "2026-10-02.json", encoding="utf-8"))
REAL_IND = {i["name"]: i for i in REAL["thermometer"]["indicators"]}
OLD = json.load(open(ROOT / "data" / "2026-09-08.json", encoding="utf-8"))
HIDDEN = {i["name"]: i for i in OLD["thermometer"]["indicators"] if i.get("hide")}
assert {"MOVE (Bond Vol)", "IEI/HYG (Credit Spread)"} <= set(HIDDEN)

STUBS = ("spy_trend", "vix_level", "market_put_call", "move_index", "vix_term_structure",
         "credit_spread_proxy", "market_breadth", "_breadth_divergence")
NAMES = {"spy_trend": "SPY тренд", "vix_level": "VIX", "market_put_call": "Put/Call (SPY)",
         "move_index": "MOVE (Bond Vol)", "vix_term_structure": "VIX Term Structure",
         "credit_spread_proxy": "IEI/HYG (Credit Spread)", "market_breadth": "Market Breadth (% над 40dMA)"}


def run_with(patch: dict, prior_state, today: dt.date, hide=(), state_file_text=None):
    """build_thermometer без мрежа. patch: {име: полета}; hide: имена, заменени със СКРИТ вариант."""
    ind = {k: dict(v) for k, v in REAL_IND.items()}
    for name, p in patch.items():
        ind[name].update(p)
    for name in hide:
        ind[name] = dict(HIDDEN[name]) if name in HIDDEN else {
            "name": name, "value": None, "status": "yellow", "hide": True, "label": ""}
    saved = {n: getattr(th, n) for n in STUBS}
    for fn, name in NAMES.items():
        setattr(th, fn, (lambda n=name: ind[n]))
    th._breadth_divergence = lambda _i: None
    orig = th._OVERRIDE_STATE_FILE
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        th._OVERRIDE_STATE_FILE = pathlib.Path(tmp) / "state.json"
        if state_file_text is not None:
            th._OVERRIDE_STATE_FILE.write_text(state_file_text)
        elif prior_state is not None:
            th._OVERRIDE_STATE_FILE.write_text(json.dumps(prior_state))
        try:
            with contextlib.redirect_stdout(buf):
                out = th.build_thermometer(REAL["macro"], today=today)
            return out, buf.getvalue(), json.loads(th._OVERRIDE_STATE_FILE.read_text()) \
                if th._OVERRIDE_STATE_FILE.exists() else None
        finally:
            th._OVERRIDE_STATE_FILE = orig
            for n, f in saved.items():
                setattr(th, n, f)


T = dt.date(2026, 10, 5)
Y = "2026-10-02"  # "вчера"/последния запис в state
print("── т.1: скрит индикатор докато хистерезисът го държи (СИНТЕТИЧНО състояние) ──")

# IEI/HYG: вчера spike (streak 0), днес скрит — преди фикса: KeyError 'roc_10d_pct'
prior = {"credit_spike": {"streak_below": 0, "last_date": Y},
         "move_spike": {"streak_below": 5, "last_date": Y}}
t, log, _ = run_with({}, prior, T, hide=("IEI/HYG (Credit Spread)",))
ov = {o["trigger"]: o for o in t["overrides"]}
assert "IEI/HYG" in ov and ov["IEI/HYG"]["state"] == "hysteresis"
assert "данните липсват днес" in ov["IEI/HYG"]["text"] and "хистерезис" in ov["IEI/HYG"]["text"]
assert t["regime"] == "Defensive" and "IEI/HYG" in t["regime_reason"]
print("  ✓ IEI/HYG скрит, вчера spike → без крах:", ov["IEI/HYG"]["text"])

# MOVE: вчера spike, днес скрит — override-ът не бива тихо да изчезне
prior = {"move_spike": {"streak_below": 0, "last_date": Y},
         "credit_spike": {"streak_below": 9, "last_date": Y}}
t, log, _ = run_with({"IEI/HYG (Credit Spread)": {"spike": False, "status": "green", "roc_percentile": 40.0}},
                     prior, T, hide=("MOVE (Bond Vol)",))
ov = {o["trigger"]: o for o in t["overrides"]}
assert "MOVE" in ov and "данните липсват днес" in ov["MOVE"]["text"], t["overrides"]
assert t["regime"] == "Defensive"
print("  ✓ MOVE скрит, вчера spike → override се държи, изричен текст:", ov["MOVE"]["text"])

# и двата скрити
prior = {"move_spike": {"streak_below": 0, "last_date": Y}, "credit_spike": {"streak_below": 0, "last_date": Y}}
t, log, _ = run_with({}, prior, T, hide=("MOVE (Bond Vol)", "IEI/HYG (Credit Spread)"))
assert {o["trigger"] for o in t["overrides"]} == {"MOVE", "IEI/HYG"}
print("  ✓ и двата скрити → и двата override-а се държат, без крах")

# скрит, но БЕЗ държан override (спокоен запис) → няма override, няма крах
prior = {"move_spike": {"streak_below": 6, "last_date": Y}, "credit_spike": {"streak_below": 6, "last_date": Y}}
t, log, _ = run_with({}, prior, T, hide=("MOVE (Bond Vol)", "IEI/HYG (Credit Spread)"))
assert not t["overrides"]
print("  ✓ скрити, но спокоен запис (streak 6) → няма override")

# контролен run без скрити индикатори (реалните индикатори от 02.10) минава
t, log, _ = run_with({}, {"credit_spike": {"streak_below": 0, "last_date": Y}}, T)
assert t["regime"] == "Defensive"
print("  ✓ контролен run без скрити индикатори минава")

print()
print("── т.1: fallback при крах на целия термометър ──")
class Boom(Exception): pass
fb = th.thermometer_unavailable(Boom("тест"))
assert fb["regime"] == "Defensive" and fb["regime_reason"] == "Defensive (термометърът е недостъпен)"
assert fb["sizing_factor"] == config.DEFENSIVE_SIZING_FACTOR and fb["indicators"] == [] and fb["overrides"] == []
# шаблонът и имейлът четат тези ключове — рендерът с fallback не бива да гърми
from src import render
brief = {"date": "2026-10-05", "thermometer": fb, "action": [], "watchlist": [],
         "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
with tempfile.TemporaryDirectory() as tmp:
    orig = config.DOCS_DIR
    config.DOCS_DIR = pathlib.Path(tmp)
    try:
        html = render.render_dashboard(brief)
        email = render.render_email(brief)
    finally:
        config.DOCS_DIR = orig
assert "термометърът е недостъпен" in html and "термометърът е недостъпен" in email
print("  ✓ fallback има формата на нормалния резултат; dashboard и имейл се рендерират")

# main.run: build_thermometer, който хвърля → run продължава (проверка на try в кода)
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "thermo = thermometer_unavailable(e)" in src
print("  ✓ main.py опакова build_thermometer в try с fallback")

print()
print("Всички тестове минаха.")
