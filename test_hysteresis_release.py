"""
Пакет 2 · т.10 (2026-10-03): скрит индикатор, задържан от хистерезиса (MOVE spike / IEI-HYG spike), се ОСВОБОЖДАВА след
config.HYSTERESIS_HIDDEN_RELEASE_DAYS (10) ПОРЕДНИ дни без данни — ред в лога + текст в брифа (regime_reason, hysteresis_released,
бележка в макро промпта). Преди замразеният streak държеше override-а без край.

РЕАЛНО: индикаторите от брифа на 02.10.2026 (tests/fixtures/brief_2026-10-02.json — IEI/HYG в spike, MOVE спокоен: +3.5 пункта) и
формата на СКРИТ индикатор от брифа на 08.09. ИЗМЕРЕНО на 03.10 в 78-те брифа от data/ (не се проверява тук): ^MOVE е скрит в 27
брифа, най-дългата поредица е 22 дни (юли 2026); IEI/HYG — 1 ден. СИНТЕТИЧНО: състоянието на хистерезиса (streak 0 на 02.10 е
реалната логика на spike в този ден, но файлът е конструиран), веригата от дни 03.10 → 14.10, и върнатите данни след паузата.
Състоянието е в tempdir — реалният data/regime_override_state.json не се пипа.
Пускане: python test_hysteresis_release.py
"""
import sys, json, pathlib, tempfile, datetime as dt, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import thermometer as th, ai_brief, render

REAL = json.load(open(ROOT / "tests" / "fixtures" / "brief_2026-10-02.json", encoding="utf-8"))
REAL_IND = {i["name"]: i for i in REAL["thermometer"]["indicators"]}
OLD = json.load(open(ROOT / "tests" / "fixtures" / "brief_2026-09-08.json", encoding="utf-8"))
HIDDEN = {i["name"]: i for i in OLD["thermometer"]["indicators"] if i.get("hide")}
MOVE, CRED = "MOVE (Bond Vol)", "IEI/HYG (Credit Spread)"
assert REAL_IND[CRED].get("spike") and not REAL_IND[MOVE].get("spike")              # РЕАЛНО 02.10: IEI/HYG в spike; MOVE спокоен (override-ът му се държеше от хистерезиса)

NAMES = {"spy_trend": "SPY тренд", "vix_level": "VIX", "market_put_call": "Put/Call (SPY)",
         "move_index": MOVE, "vix_term_structure": "VIX Term Structure", "credit_spread_proxy": CRED,
         "market_breadth": "Market Breadth (% над 40dMA)"}
CALM = {MOVE: {"spike": False, "status": "yellow", "delta_1w": 2.0},
        CRED: {"spike": False, "status": "green", "roc_percentile": 40.0}}
LIMIT = config.HYSTERESIS_HIDDEN_RELEASE_DAYS
assert LIMIT == 10


def day(state, today, hide=(), patch=None):
    """един run на build_thermometer без мрежа; връща (термометър, лог, ново състояние)."""
    ind = {k: dict(v) for k, v in REAL_IND.items()}
    for n, p in (patch or {}).items():
        ind[n].update(p)
    for n in hide:
        ind[n] = dict(HIDDEN[n])
    saved = {fn: getattr(th, fn) for fn in NAMES}
    saved["_breadth_divergence"] = th._breadth_divergence
    for fn, n in NAMES.items():
        setattr(th, fn, (lambda n=n: ind[n]))
    th._breadth_divergence = lambda _i: None
    orig = th._OVERRIDE_STATE_FILE
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        th._OVERRIDE_STATE_FILE = pathlib.Path(tmp) / "state.json"
        th._OVERRIDE_STATE_FILE.write_text(json.dumps(state))
        try:
            with contextlib.redirect_stdout(buf):
                out = th.build_thermometer(REAL["macro"], today=today)
            return out, buf.getvalue(), json.loads(th._OVERRIDE_STATE_FILE.read_text())
        finally:
            th._OVERRIDE_STATE_FILE = orig
            for n, f in saved.items():
                setattr(th, n, f)


D0 = dt.date(2026, 10, 2)
D = lambda k: D0 + dt.timedelta(days=k)
START = {"move_spike": {"streak_below": 0, "last_date": D0.isoformat()},
         "credit_spike": {"streak_below": 9, "last_date": D0.isoformat()}}          # IEI/HYG е спокоен — изолираме MOVE


def chain_hidden(trigger_name, key, state, start_k, end_k, patch):
    """скрит индикатор ден след ден; връща списък (k, термометър, лог) и последното състояние."""
    out = []
    for k in range(start_k, end_k + 1):
        t, log, state = day(state, D(k), hide=(trigger_name,), patch=patch)
        out.append((k, t, log))
    return out, state


print("── MOVE: верига от 12 дни без данни (СИНТЕТИЧНО състояние, РЕАЛНИ индикатори от 02.10) ──")
rows, st = chain_hidden(MOVE, "move_spike", START, 1, 12, {CRED: CALM[CRED]})
for k, t, log in rows:
    names = {o["trigger"]: o for o in t["overrides"]}
    if k < LIMIT:
        assert "MOVE" in names and names["MOVE"]["state"] == "hysteresis", (k, t["overrides"])
        assert f"{k}-и ден без данни" in names["MOVE"]["text"] and f"освобождава се на {LIMIT}-ия" in names["MOVE"]["text"]
        assert t["regime"] == "Defensive" and t["hysteresis_released"] == [] and "ОСВОБОДЕН" not in t["regime_reason"]
        assert f"освобождава се на {LIMIT}-ия" in log and "ОСВОБОЖДАВА" not in log
    else:
        assert "MOVE" not in names and t["overrides"] == [], (k, t["overrides"])
        assert t["regime"] == t["regime_by_count"]                                   # режимът е по броенето
        if k == LIMIT:
            assert t["hysteresis_released"] == [{"trigger": "MOVE", "hidden_days": LIMIT}]
            assert "Override-ът за MOVE е ОСВОБОДЕН: 10 поредни дни без данни за индикатора (праг 10)" in t["regime_reason"]
            assert "move_spike: ⚠ 10 поредни дни без данни (праг 10) — override-ът се ОСВОБОЖДАВА" in log
        else:
            assert t["hysteresis_released"] == [] and "ОСВОБОДЕН" not in t["regime_reason"]       # съобщението е само в деня на освобождаването
assert st["move_spike"]["frozen_days"] == 12 and st["move_spike"]["streak_below"] == 2 and st["move_spike"]["released_on"] == D(10).isoformat()
print(f"  ✓ дни 1–9: override MOVE се държи ('N-и ден без данни, освобождава се на 10-ия'), режим Defensive; ден 10 ({D(10)}): освободен —")
print("    няма override, режимът е по броенето, regime_reason казва 'ОСВОБОДЕН: 10 поредни дни', в лога има ред; дни 11–12: без override, без повторно съобщение")
t10 = rows[LIMIT - 1][1]
print(f"    текст в брифа (ден 10): {t10['regime_reason']}")

# повторен run същия ден 10 — идемпотентно (frozen не расте, съобщението остава)
rows9, state9 = chain_hidden(MOVE, "move_spike", START, 1, 9, {CRED: CALM[CRED]})
t_rel, _, s10 = day(state9, D(10), hide=(MOVE,), patch={CRED: CALM[CRED]})
t_rel2, _, s10b = day(s10, D(10), hide=(MOVE,), patch={CRED: CALM[CRED]})
assert t_rel["hysteresis_released"] == t_rel2["hysteresis_released"] == [{"trigger": "MOVE", "hidden_days": 10}]
assert s10["move_spike"]["frozen_days"] == s10b["move_spike"]["frozen_days"] == 10 and t_rel["overrides"] == t_rel2["overrides"] == []
print("  ✓ повторен run на деня на освобождаването → същият резултат, frozen_days остава 10 (не се брои двойно)")

print()
print("── след освобождаването: данните се връщат ──")
t, _, s = day(st, D(13), patch=CALM)                                              # MOVE видим и спокоен
assert t["overrides"] == [] and s["move_spike"]["streak_below"] == 3 and "frozen_days" not in s["move_spike"]
print("  ✓ данните се връщат спокойни (ден 13) → няма override (streak 3), frozen_days се чисти")
SPIKE = {"spike": True, "status": "red", "value": 126.0, "delta_1w": 21.0, "label": "MOVE 126 (+21 пункта/седмица) ⚠ рязък скок"}   # СИНТЕТИЧЕН spike
t, _, s = day(st, D(13), patch={CRED: CALM[CRED], MOVE: SPIKE})
names = {o["trigger"]: o for o in t["overrides"]}
assert names["MOVE"]["state"] == "active" and s["move_spike"]["streak_below"] == 0
print("  ✓ данните се връщат със spike (ден 13, СИНТЕТИЧЕН spike +21 пункта) → override-ът се вдига наново, активен (streak 0)")
print()

print("── само ПОРЕДНИ дни ──")
rows, st = chain_hidden(MOVE, "move_spike", START, 1, 6, {CRED: CALM[CRED]})            # 6 скрити дни
assert st["move_spike"]["frozen_days"] == 6 and "released_on" not in st["move_spike"]
t, _, st = day(st, D(7), patch=CALM)                                                    # 1 видим спокоен ден прекъсва серията
assert st["move_spike"]["streak_below"] == 1 and "frozen_days" not in st["move_spike"] and {o["trigger"] for o in t["overrides"]} == {"MOVE"}
rows, st = chain_hidden(MOVE, "move_spike", st, 8, 13, {CRED: CALM[CRED]})              # още 6 скрити дни (общо 12 скрити от 13)
assert st["move_spike"]["frozen_days"] == 6 and "released_on" not in st["move_spike"]
assert all("MOVE" in {o["trigger"] for o in t2["overrides"]} and t2["hysteresis_released"] == [] for _, t2, _ in rows)
print("  ✓ 6 скрити + 1 видим ден + 6 скрити (12 от 13 дни) → НЕ се освобождава: броят е на последователните скрити дни (frozen_days 6)")
print()

print("── IEI/HYG ──")
START_C = {"credit_spike": {"streak_below": 0, "last_date": D0.isoformat()},
           "move_spike": {"streak_below": 9, "last_date": D0.isoformat()}}
rows, st = chain_hidden(CRED, "credit_spike", START_C, 1, LIMIT, {MOVE: CALM[MOVE]})
for k, t, log in rows[:-1]:
    assert "IEI/HYG" in {o["trigger"] for o in t["overrides"]} and t["hysteresis_released"] == [], k
t = rows[-1][1]
assert t["overrides"] == [] and t["hysteresis_released"] == [{"trigger": "IEI/HYG", "hidden_days": LIMIT}]
assert "Override-ът за IEI/HYG е ОСВОБОДЕН: 10 поредни дни" in t["regime_reason"]
print("  ✓ същото за IEI/HYG: държи се дни 1–9, на 10-ия е освободен със съобщение")
print()

print("── параметърът от config.py ──")
config.HYSTERESIS_HIDDEN_RELEASE_DAYS = 3
rows, st = chain_hidden(MOVE, "move_spike", START, 1, 4, {CRED: CALM[CRED]})
assert [bool(t["overrides"]) for _, t, _ in rows] == [True, True, False, False]
assert rows[2][1]["hysteresis_released"] == [{"trigger": "MOVE", "hidden_days": 3}] and "освобождава се на 3-ия" in rows[0][1]["overrides"][0]["text"]
config.HYSTERESIS_HIDDEN_RELEASE_DAYS = 10
print("  ✓ HYSTERESIS_HIDDEN_RELEASE_DAYS=3 → държи 2 дни, освобождава на 3-ия")
print()

print("── без държан override нищо не се променя ──")
calm_state = {"move_spike": {"streak_below": 6, "last_date": D0.isoformat()}, "credit_spike": {"streak_below": 6, "last_date": D0.isoformat()}}
rows, st = chain_hidden(MOVE, "move_spike", calm_state, 1, 12, {CRED: CALM[CRED]})
assert all(t["overrides"] == [] and t["hysteresis_released"] == [] for _, t, _ in rows) and "released_on" not in st["move_spike"]
print("  ✓ скрит индикатор със спокоен запис (streak 6) за 12 дни → никога override, никога съобщение за освобождаване")
print()

print("── в брифа: dashboard, имейл, макро промпт (термометърът от деня на освобождаването) ──")
brief = json.loads(json.dumps(REAL)); brief["thermometer"] = t_rel                  # a = ден 10 на освобождаването
assert "ОСВОБОДЕН" in brief["thermometer"]["regime_reason"]
import html as htmllib
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2 = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        dash = htmllib.unescape(render.render_dashboard(brief)); mail = htmllib.unescape(render.render_email(brief))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2
for page_name, page in (("dashboard", dash), ("имейл", mail)):
    assert "Override-ът за MOVE е ОСВОБОДЕН: 10 поредни дни без данни" in page, page_name
seen = {}
ai_brief._call_claude = lambda system, user, max_tokens=0: (seen.setdefault("u", user), json.dumps({"macro_brief": "x", "sector_logic": [], "regime_comment": "y"}))[1]
ai_brief.macro_and_sector_brief({}, [], t_rel)
assert "override-ът за MOVE (10 поредни дни без данни) е ОСВОБОДЕН" in seen["u"] and "НЕ е подобрение на пазарните условия" in seen["u"]
seen.clear()
ai_brief.macro_and_sector_brief({}, [], day(START, D(1), hide=(MOVE,), patch={CRED: CALM[CRED]})[0])
assert "ОСВОБОДЕН от кода" not in seen["u"]
print("  ✓ dashboard и имейл показват изречението в заглавието на режима; макро промптът казва 'НЕ е подобрение на пазара'; в обикновен ден бележката я няма")
print()
print("Всички тестове минаха.")
