"""
Спешни находки 1-3 от прегледа (само четене, main 8eb4649): скрити индикатори
в термометъра.

  т.1 KeyError при скрит IEI/HYG (и MOVE) докато хистерезисът държи override;
      + fallback "Defensive (термометърът е недостъпен)", ако термометърът гръмне.
  т.2 минимум видими индикатори за Offensive (реална конфигурация от 08.09).
  т.3 хистерезисът не брои скрит ден за спокоен (streak се замразява).

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

REAL = json.load(open(ROOT / "tests" / "fixtures" / "brief_2026-10-02.json", encoding="utf-8"))
REAL_IND = {i["name"]: i for i in REAL["thermometer"]["indicators"]}
OLD = json.load(open(ROOT / "tests" / "fixtures" / "brief_2026-09-08.json", encoding="utf-8"))
HIDDEN = {i["name"]: i for i in OLD["thermometer"]["indicators"] if i.get("hide")}
assert {"MOVE (Bond Vol)", "IEI/HYG (Credit Spread)"} <= set(HIDDEN)

STUBS = ("spy_trend", "vix_level", "market_put_call", "move_index", "vix_term_structure",
         "credit_spread_proxy", "market_breadth", "_breadth_divergence")
NAMES = {"spy_trend": "SPY тренд", "vix_level": "VIX", "market_put_call": "Put/Call (SPY)",
         "move_index": "MOVE (Bond Vol)", "vix_term_structure": "VIX Term Structure",
         "credit_spread_proxy": "IEI/HYG (Credit Spread)", "market_breadth": "Market Breadth (% над 40dMA)"}


def run_with(patch: dict, prior_state, today: dt.date, hide=(), state_file_text=None, base=None, macro=None):
    """build_thermometer без мрежа. patch: {име: полета}; hide: имена, заменени със СКРИТ вариант."""
    ind = {k: dict(v) for k, v in (base or REAL_IND).items()}
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
                out = th.build_thermometer(macro or REAL["macro"], today=today)
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
print("── т.2: минимум видими индикатори за Offensive ──")
CALM = {"move_spike": {"streak_below": 9, "last_date": "2026-09-07"},
        "credit_spike": {"streak_below": 9, "last_date": "2026-09-07"}}
OLD_IND = {i["name"]: i for i in OLD["thermometer"]["indicators"]}
assert OLD["thermometer"]["regime"] == "Offensive" and OLD["thermometer"]["sizing_factor"] == 1.0
t, _, _ = run_with({}, CALM, dt.date(2026, 9, 8), base=OLD_IND, macro=OLD["macro"])  # CALM: изолира т.2 от хистерезиса
print("  РЕАЛНО 08.09 (преди фикса):", OLD["thermometer"]["regime"], "|", OLD["thermometer"]["regime_reason"])
print("  РЕАЛНА конфигурация 08.09 (след фикса):", t["regime"], "|", t["regime_reason"])
assert t["regime"] == "Defensive" and t["sizing_factor"] == config.DEFENSIVE_SIZING_FACTOR
assert t["regime_reason"].startswith("5 зелени / 0 жълти / 0 червени от 5 видими")
assert "недостатъчно данни за Offensive (видими 5 от 8, нужни ≥ 6)" in t["regime_reason"]    # пакет 2 т.2: 8 броени, Net Liquidity е информативен
assert not t["overrides"], t["overrides"]  # режимът е от броенето, не от override
print("  ✓ реалната 08.09 конфигурация (5 видими, 4 скрити) вече дава Defensive с причина")

print("  СИНТЕТИЧНО (реалните индикатори от 02.10, всички зелени, спокоен хистерезис):")
GREEN = {n: {"status": "green"} for n in REAL_IND}
GREEN["IEI/HYG (Credit Spread)"].update({"spike": False, "roc_percentile": 30.0})
GREEN["MOVE (Bond Vol)"].update({"spike": False, "delta_1w": 1.0, "value": 80.0})
for hide, expect in (((), "Offensive"),
                     (("VIX Term Structure", "Market Breadth (% над 40dMA)"), "Offensive"),   # 6 видими = граница
                     (("VIX Term Structure", "Market Breadth (% над 40dMA)", "Put/Call (SPY)"), "Defensive")):  # 5
    t, _, _ = run_with(GREEN, CALM, dt.date(2026, 9, 8), hide=hide)
    n_vis = 8 - len(hide)
    assert t["regime"] == expect, (n_vis, t["regime"], t["regime_reason"])
    print(f"    {n_vis} видими, всички зелени → {t['regime']}")
assert "недостатъчно данни" in t["regime_reason"]
print("  ✓ граница: 6 видими (от 8 броени) → Offensive, 5 → Defensive; 8 → Offensive (без регресия)")

# Cash/Defensive по броенето не се смекчават от прага (прагът само затяга)
t, _, _ = run_with({"MOVE (Bond Vol)": {"status": "red", "spike": False},
                    "Put/Call (SPY)": {"status": "red"}, "VIX": {"status": "red"}},
                   CALM, dt.date(2026, 9, 8), hide=("VIX Term Structure", "Market Breadth (% над 40dMA)", "Fed Net Liquidity"))
assert t["regime_by_count"] in ("Cash", "Defensive")
print("  ✓ при червени индикатори прагът не променя Cash/Defensive:", t["regime_by_count"])

print()
print("── т.3: скрит ден не е спокоен ден — streak се замразява (СИНТЕТИЧНО, вериги от дни) ──")
D = lambda n: dt.date(2026, 10, n)
calm_credit = {"IEI/HYG (Credit Spread)": {"spike": False, "status": "green", "roc_percentile": 40.0}}
MOVE_H = "MOVE (Bond Vol)"
state = {"move_spike": {"streak_below": 0, "last_date": "2026-10-02"},   # вчера: spike
         "credit_spike": {"streak_below": 9, "last_date": "2026-10-02"}}

# два поредни скрити дни: преди фикса streak стигаше 2 и override-ът падаше
t, log, state = run_with(calm_credit, state, D(5), hide=(MOVE_H,))
assert state["move_spike"]["streak_below"] == 0 and state["move_spike"]["frozen_days"] == 1
assert "замразен" in log and any(o["trigger"] == "MOVE" for o in t["overrides"])
t, log, state = run_with(calm_credit, state, D(6), hide=(MOVE_H,))
assert state["move_spike"]["streak_below"] == 0 and state["move_spike"]["frozen_days"] == 2
ov = {o["trigger"]: o for o in t["overrides"]}
assert "MOVE" in ov and "2-и ден без данни" in ov["MOVE"]["text"], ov
print("  ✓ 2 поредни скрити дни → streak остава 0, override още активен (2-и ден без данни)")
print("    лог:", log.strip().splitlines()[0])

# първият ВИДИМ спокоен ден продължава от замразеното: 0 → 1 (още активен), после 2 → пада
t, log, state = run_with(calm_credit, state, D(7))
assert state["move_spike"]["streak_below"] == 1 and "frozen_days" not in state["move_spike"]
assert any(o["trigger"] == "MOVE" for o in t["overrides"])
t, log, state = run_with(calm_credit, state, D(8))
assert state["move_spike"]["streak_below"] == 2 and not any(o["trigger"] == "MOVE" for o in t["overrides"])
print("  ✓ видим спокоен ден 1 → 1/2 (държи), ден 2 → 2/2 (пада); frozen_days се чисти")

# скрит ден между два спокойни: не нулира и не добавя
state = {"move_spike": {"streak_below": 1, "last_date": "2026-10-02"},
         "credit_spike": {"streak_below": 9, "last_date": "2026-10-02"}}
t, log, state = run_with(calm_credit, state, D(5), hide=(MOVE_H,))
assert state["move_spike"]["streak_below"] == 1
t, log, state = run_with(calm_credit, state, D(6))
assert state["move_spike"]["streak_below"] == 2 and not any(o["trigger"] == "MOVE" for o in t["overrides"])
print("  ✓ streak 1, скрит ден (остава 1), видим спокоен ден → 2 → пада (скритият не нулира)")

# същото за IEI/HYG
state = {"credit_spike": {"streak_below": 0, "last_date": "2026-10-02"},
         "move_spike": {"streak_below": 9, "last_date": "2026-10-02"}}
CH = "IEI/HYG (Credit Spread)"
for d in (5, 6, 7):
    t, log, state = run_with({}, state, D(d), hide=(CH,))
assert state["credit_spike"]["streak_below"] == 0 and state["credit_spike"]["frozen_days"] == 3
assert any(o["trigger"] == "IEI/HYG" for o in t["overrides"])
print("  ✓ IEI/HYG: 3 скрити дни → streak 0, override активен (3-и ден без данни)")

# идемпотентност в рамките на един ден: frozen_days не расте двойно
state = {"move_spike": {"streak_below": 0, "last_date": "2026-10-02"}, "credit_spike": {"streak_below": 9, "last_date": "2026-10-02"}}
_, _, state = run_with(calm_credit, state, D(5), hide=(MOVE_H,))
_, _, state = run_with(calm_credit, state, D(5), hide=(MOVE_H,))
assert state["move_spike"]["frozen_days"] == 1
print("  ✓ повторен run същия ден → frozen_days остава 1")

# няма записан spike (празно състояние) + скрит индикатор → НЯМА фантомен override
t, log, state = run_with(calm_credit, {}, D(5), hide=(MOVE_H,))
assert not any(o["trigger"] == "MOVE" for o in t["overrides"]) and "няма записано състояние" in log
print("  ✓ скрит MOVE без записано състояние → няма override (преди фикса fail-safe държеше фантомен)")

# повреден запис за ключа + скрит индикатор → fail-safe: държи
t, log, _ = run_with(calm_credit, {"move_spike": "боклук", "credit_spike": {"streak_below": 9, "last_date": "2026-10-02"}}, D(5), hide=(MOVE_H,))
assert any(o["trigger"] == "MOVE" for o in t["overrides"]) and "fail-safe" in log
print("  ✓ повреден запис + скрит индикатор → fail-safe, override се държи")

print()
print("Всички тестове минаха.")
