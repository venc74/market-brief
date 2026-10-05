"""
Допълнение към пакет 2 (2026-10-05): червени distribution days → режимът е най-много Defensive (никога Offensive), с причина в
regime_reason; Cash и Defensive не се променят. + (2026-10-05, т.1 от пакет 3-заявката) асиметричен хистерезис: блокът се включва
веднага на първия червен ден и пада чак след 2 ПОРЕДНИ нечервени дни; състоянието е в regime_override_state.json (тук — във
временна директория, реалният файл се проверява, че не е пипнат). thermometer.apply_distribution_cap() върху резултата на
build_thermometer; main.py смята distribution days веднага след термометъра (преди макро брифа и режимния gate).

РЕАЛНО: брифовете от 22.09 (Offensive, SPY 10 / QQQ 6 — червено), 02.10 (Defensive по override, SPY 10 / QQQ 5 — червено), 20.08
(жълто: SPY 6 / QQQ 7) и 08.09 (зелено: SPY 6 / QQQ 5) от tests/fixtures; РЕАЛНИТЕ ежедневни броеве SPY/QQQ distribution days за
08.09 → 02.10 (прочетени от data/ снимките на 05.10.2026); РЕАЛЕН EXEL (+1.56% над pivot, обем 2.49×) за gate-а. СИНТЕТИЧНО: Cash/
Defensive по броене, "Offensive по броене" във веригата от дни (изолира хистерезиса), override-ът над Offensive по броене, граничните
броеве 8/9 (праг DISTRIBUTION_DAYS_RED=9), QQQ-само, липсващ индекс/данни, +3% кандидат, повреден state файл.
Пускане: python test_distribution_cap.py
"""
import sys, json, copy, pathlib, hashlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import thermometer as th, entry_timing, setup_rules, screener, ai_brief
from src import main as brief_main

config.ENABLE_BACKTEST = False
REAL_STATE = ROOT / "data" / "regime_override_state.json"
fp_before = hashlib.md5(REAL_STATE.read_bytes()).hexdigest() if REAL_STATE.exists() else None
_tmp = tempfile.TemporaryDirectory(prefix="mb_dist_")
STATE = pathlib.Path(_tmp.name) / "state.json"
th._OVERRIDE_STATE_FILE = STATE                                  # реалният data/regime_override_state.json не се пипа


def cap(thermo, dd, day="2026-10-05", fresh=True):
    """един run на apply_distribution_cap; fresh=True → празно състояние (изолиран случай), fresh=False → верига от дни.
    Логовете на термометъра се заглушават (при липсващ файл _load_override_state печата дълго съобщение за override-ите)."""
    if fresh:
        STATE.unlink(missing_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        return th.apply_distribution_cap(thermo, dd, dt.date.fromisoformat(day))


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


FIX = ROOT / "tests" / "fixtures"
B = {d: json.loads((FIX / f"brief_{d}.json").read_text(encoding="utf-8")) for d in ("2026-09-22", "2026-10-02", "2026-08-20", "2026-09-08")}
T = lambda d: B[d]["thermometer"]
DD = lambda d: B[d]["distribution_days"]
assert (T("2026-09-22")["regime"], DD("2026-09-22")["status"], DD("2026-09-22")["spy_count"], DD("2026-09-22")["qqq_count"]) == ("Offensive", "red", 10, 6)

print("── РЕАЛЕН 22.09: Offensive + червени distribution days (SPY 10 / QQQ 6) ──")
src_t = T("2026-09-22")
before = copy.deepcopy(src_t)
out = cap(src_t, DD("2026-09-22"), "2026-09-22")
assert src_t == before                                                              # входът не се мутира
assert out["regime"] == "Defensive" and out["sizing_factor"] == config.DEFENSIVE_SIZING_FACTOR == 0.5
assert out["regime_reason"] == src_t["regime_reason"] + " — distribution days червени (SPY 10/25, QQQ 6/25; праг 9) — Offensive блокиран"
c = out["distribution_cap"]
assert c["active"] and c["changed_regime"] and c["kind"] == "red" and (c["spy_count"], c["qqq_count"], c["count"], c["threshold"], c["lookback"]) == (10, 6, 10, 9, 25)
assert c["text"] == "distribution days червени (SPY 10/25, QQQ 6/25; праг 9) — Offensive блокиран (по броене: Offensive)"
assert "Режимът по броенето е Offensive" in out["exit_rule"] and "пада чак след 2 поредни нечервени дни" in out["exit_rule"] and "сега е 10" in out["exit_rule"]
assert state()["distribution_block"] == {"blocked": True, "streak_nonred": 0, "last_date": "2026-09-22"}
assert th.apply_distribution_cap(out, DD("2026-09-22"), dt.date(2026, 9, 22)) is out                        # втори вик над същия thermo — no-op
assert out["regime_reason"].count("Offensive блокиран") == 1
print(f"  ✓ Offensive → Defensive, sizing 1.0 → 0.5; причина: '…{out['regime_reason'][-85:]}'")
print("  ✓ входният речник не се мутира; състоянието е записано (blocked, streak 0); повторно прилагане е no-op")
print()

print("── без промяна: РЕАЛНИ 02.10 / 20.08 / 08.09 ──")
t02 = T("2026-10-02")
assert t02["regime_by_count"] == "Defensive" and DD("2026-10-02")["status"] == "red"
assert cap(t02, DD("2026-10-02")) is t02                                                  # Defensive по броене + червено → нищо
assert cap(T("2026-08-20"), DD("2026-08-20")) is T("2026-08-20")                           # жълто, не е бил блокиран
assert cap(T("2026-09-08"), DD("2026-09-08")) is T("2026-09-08") and T("2026-09-08")["regime"] == "Offensive"   # зелено
print("  ✓ 02.10 (Defensive по override и по броене, червено), 20.08 (жълто), 08.09 (Offensive, зелено) → същият обект, без промяна")
print()

print("── СИНТЕТИЧНО: Cash, Defensive, празни данни, превключвател ──")
red = {"count": 12, "spy_count": 12, "qqq_count": 4, "status": "red", "label": "x"}
cash = {**copy.deepcopy(src_t), "regime": "Cash", "regime_by_count": "Cash"}
assert cap(cash, red) is cash and "distribution_cap" not in cash                            # Cash не се променя
dfn = {**copy.deepcopy(src_t), "regime": "Defensive", "regime_by_count": "Defensive"}
assert cap(dfn, red) is dfn                                                               # Defensive по броене — нищо
assert cap(src_t, None) is src_t and cap(src_t, {**red, "status": "yellow"}) is src_t and cap(src_t, {**red, "status": "green"}) is src_t
STATE.unlink(missing_ok=True)
config.DISTRIBUTION_DAYS_BLOCKS_OFFENSIVE = False
assert cap(src_t, red, fresh=False) is src_t and not STATE.exists()     # изключен; състоянието не се пипа
config.DISTRIBUTION_DAYS_BLOCKS_OFFENSIVE = True
assert cap({"regime": "Defensive", "unavailable": True, "regime_by_count": "Defensive"}, red)["regime"] == "Defensive"   # fallback термометър
print("  ✓ Cash и Defensive по броене → без промяна; None / жълто / зелено (без предишен блок) → без промяна; превключвателят изключва блока и не пише състояние")

ov = {**copy.deepcopy(src_t), "regime": "Defensive", "regime_by_count": "Offensive", "sizing_factor": 0.5,
      "regime_reason": "MOVE: тест override", "exit_rule": "Override-ът пада, когато MOVE падне."}
o2 = cap(ov, red)
assert o2["regime"] == "Defensive" and o2["sizing_factor"] == 0.5 and o2["distribution_cap"]["changed_regime"] is False
assert o2["regime_reason"].startswith("MOVE: тест override · distribution days червени (SPY 12/25, QQQ 4/25; праг 9)") and "и без override" in o2["regime_reason"]
assert o2["exit_rule"].startswith("Override-ът пада") and "Освен това: Блокът се включва на първия червен ден" in o2["exit_rule"]
print("  ✓ Defensive по override (Offensive по броене): режимът не се променя, но причината и exit_rule казват, че и без override Offensive е блокиран")
print()

print("── граница на прага (праг 9) през evaluate_distribution_days ──")
def dd(spy, qqq):
    entry_timing._count_distribution_days = lambda sym, lb: spy if sym == "SPY" else qqq
    return entry_timing.evaluate_distribution_days()
assert dd(8, 8)["status"] == "yellow" and cap(src_t, dd(8, 8)) is src_t
at = cap(src_t, dd(9, 3))
assert dd(9, 3)["status"] == "red" and at["regime"] == "Defensive" and "(SPY 9/25, QQQ 3/25; праг 9)" in at["regime_reason"]
qq = cap(src_t, dd(3, 10))                                                                # червено само заради QQQ
assert qq["regime"] == "Defensive" and "(SPY 3/25, QQQ 10/25; праг 9)" in qq["regime_reason"]
only_spy = cap(src_t, dd(9, None))                                                        # QQQ не се изтегли
assert "(SPY 9/25; праг 9)" in only_spy["regime_reason"] and "QQQ" not in only_spy["regime_reason"]
assert dd(None, None) is None and cap(src_t, dd(None, None)) is src_t
print("  ✓ 8 → жълто, без промяна; 9 → червено, блок; червено само от QQQ → и двата броя в текста; липсващ индекс → само наличния; без данни → без промяна")
print()

print("── ХИСТЕРЕЗИС: първият червен ден блокира веднага, блокът пада след 2 поредни нечервени дни ──")
off = {**copy.deepcopy(src_t), "regime": "Offensive", "regime_by_count": "Offensive", "counts": "6 зелени / 1 жълти / 0 червени от 8 видими",
       "regime_reason": "6 зелени / 1 жълти / 0 червени от 8 видими", "exit_rule": "", "sizing_factor": 1.0}
G, Y, R = {"status": "green", "count": 4, "spy_count": 4, "qqq_count": 3}, {"status": "yellow", "count": 8, "spy_count": 8, "qqq_count": 6}, \
    {"status": "red", "count": 9, "spy_count": 9, "qqq_count": 6}
def day_(n, ddict, thermo=off):
    return cap(thermo, ddict, f"2026-11-{n:02d}", fresh=False)
STATE.unlink(missing_ok=True)
seq = [(2, G, "Offensive", None), (3, R, "Defensive", "red"), (4, Y, "Defensive", "hysteresis"), (5, G, "Offensive", None)]
for n, d_, want, kind in seq:
    r = day_(n, d_)
    assert r["regime"] == want, (n, r["regime"])
    assert (r.get("distribution_cap") or {}).get("kind") == kind, (n, r.get("distribution_cap"))
assert state()["distribution_block"]["blocked"] is False and state()["distribution_block"]["last_date"] == "2026-11-05" and state()["distribution_block"]["streak_nonred"] == 2
print("  ✓ ден 2 зелено → Offensive; ден 3 червено → Defensive веднага; ден 4 жълто → още Defensive (хистерезис 1/2); ден 5 зелено → освободен, Offensive")
STATE.unlink(missing_ok=True)
h = [day_(n, d_) for n, d_ in ((3, R), (4, Y))]
assert h[1]["distribution_cap"]["text"] == ("distribution days вече не са червени (SPY 8/25, QQQ 6/25; праг 9), но блокът се държи по хистерезис — "
                                            "1/2 нечервени дни — Offensive блокиран (по броене: Offensive)")
assert h[1]["regime_reason"].endswith("— Offensive блокиран") and "още 1 нечервен ден" in h[1]["exit_rule"] and h[1]["sizing_factor"] == 0.5
assert state()["distribution_block"]["streak_nonred"] == 1
print("  ✓ причината при хистерезис: 'вече не са червени (SPY 8/25, QQQ 6/25; праг 9), но блокът се държи по хистерезис — 1/2 нечервени дни'; exit_rule: още 1 нечервен ден")

STATE.unlink(missing_ok=True)
rr = [day_(n, d_)["regime"] for n, d_ in ((3, R), (4, Y), (5, R), (6, Y), (7, Y), (8, Y))]
assert rr == ["Defensive", "Defensive", "Defensive", "Defensive", "Offensive", "Offensive"]      # нов червен ден нулира броя
print("  ✓ червен, жълт, ЧЕРВЕН (нулира), жълт, жълт → Offensive чак на втория пореден нечервен: Def Def Def Def Off Off")

# повторен run същия ден не брои двойно
STATE.unlink(missing_ok=True)
day_(3, R); day_(4, Y)
again = day_(4, Y)
assert state()["distribution_block"]["streak_nonred"] == 1 and again["regime"] == "Defensive"
print("  ✓ повторен run на същия ден не брои двойно (streak остава 1)")

# режимът Cash/Defensive по броене също води състоянието: червен ден при Defensive, на следващия Offensive по броене и жълто → още блокиран
STATE.unlink(missing_ok=True)
dfn_off = {**off, "regime": "Defensive", "regime_by_count": "Defensive"}
r1 = day_(3, R, dfn_off); assert r1 is dfn_off
r2 = day_(4, Y)
assert r2["regime"] == "Defensive" and r2["distribution_cap"]["kind"] == "hysteresis"
print("  ✓ червен ден при Defensive по броене (нищо не се променя) пак води състоянието: на следващия ден Offensive по броене + жълто → още блокиран 1/2")

# липсващи данни: не е нечервен ден — блокът се държи; освобождава се след HYSTERESIS_HIDDEN_RELEASE_DAYS поредни дни без данни
STATE.unlink(missing_ok=True)
day_(3, R)
res = [day_(n, None) for n in range(4, 4 + config.HYSTERESIS_HIDDEN_RELEASE_DAYS)]
assert [x["regime"] for x in res[:-1]] == ["Defensive"] * (config.HYSTERESIS_HIDDEN_RELEASE_DAYS - 1) and res[-1] is off
assert res[0]["distribution_cap"]["kind"] == "no_data" and "1-и ден" in res[0]["distribution_cap"]["text"] and state()["distribution_block"]["streak_nonred"] == 2
print(f"  ✓ без данни дни 1–{config.HYSTERESIS_HIDDEN_RELEASE_DAYS - 1}: блокът се държи ('N-и ден без данни'), на {config.HYSTERESIS_HIDDEN_RELEASE_DAYS}-ия се освобождава (като при скрит индикатор)")
STATE.unlink(missing_ok=True)
assert day_(4, None) is off and not STATE.exists()                                        # без предишен блок + без данни → нищо, и нищо не се пише
day_(3, R); day_(4, None); back = day_(5, Y)
assert back["distribution_cap"]["kind"] == "hysteresis" and back["distribution_cap"]["nonred_days"] == 1 and state()["distribution_block"].get("frozen_days") is None
print("  ✓ без данни и без предишен блок → нищо; данните се върнат (жълто) след пауза → броенето започва от 1/2, frozen_days се чисти")

# повреден state: започва се начисто — червен ден блокира, нечервен не
STATE.write_text("{ не е json")
assert day_(3, Y) is off
STATE.write_text("{ не е json"); assert day_(3, R)["regime"] == "Defensive" and state()["distribution_block"]["blocked"] is True
STATE.write_text(json.dumps({"distribution_block": "боклук", "move_spike": {"streak_below": 1, "last_date": "2026-11-01"}}))
assert day_(3, R)["regime"] == "Defensive" and state()["move_spike"] == {"streak_below": 1, "last_date": "2026-11-01"}      # чуждите ключове се пазят
print("  ✓ повреден файл/запис → начисто (червен ден блокира, нечервен не); чуждите ключове (move_spike) не се губят")
print()

print("── РЕАЛНА верига 08.09 → 02.10 (реални броеве SPY/QQQ; 'Offensive по броене' е СИНТЕТИЧНО за всеки ден, за да се види само блокът) ──")
REAL_DD = [("2026-09-08", 6, 5), ("2026-09-09", 7, 5), ("2026-09-10", 7, 5), ("2026-09-11", 8, 6), ("2026-09-14", 8, 6), ("2026-09-15", 8, 7),
           ("2026-09-16", 9, 7), ("2026-09-17", 10, 6), ("2026-09-18", 10, 6), ("2026-09-21", 10, 6), ("2026-09-22", 10, 6), ("2026-09-23", 9, 6),
           ("2026-09-24", 9, 5), ("2026-09-25", 9, 5), ("2026-09-28", 8, 5), ("2026-09-29", 9, 6), ("2026-09-30", 9, 5), ("2026-10-01", 10, 5), ("2026-10-02", 10, 5)]
def mk(spy, qqq):
    n = max(spy, qqq)
    return {"count": n, "spy_count": spy, "qqq_count": qqq, "status": "red" if n >= 9 else "yellow" if n >= 7 else "green"}
STATE.unlink(missing_ok=True)
with_h, without_h = [], []
for d_, spy, qqq in REAL_DD:
    dd_ = mk(spy, qqq)
    with_h.append(cap(off, dd_, d_, fresh=False)["regime"][:3])
    without_h.append("Def" if dd_["status"] == "red" else "Off")
diff = [d_ for (d_, _, _), a, b in zip(REAL_DD, with_h, without_h) if a != b]
assert diff == ["2026-09-28"], diff
assert with_h[[d_ for d_, _, _ in REAL_DD].index("2026-09-28")] == "Def" and without_h[[d_ for d_, _, _ in REAL_DD].index("2026-09-28")] == "Off"
print("  ✓ единственият ден, в който хистерезисът променя нещо спрямо блока без него: 28.09 (жълто, SPY 8/QQQ 5, между червени 25.09 и 29.09)")
print("    с хистерезис: Def (1/2), без: Off — броят хвърля 9 → 8 → 9, Offensive за един ден между два червени")
print()

print("── gate и sizing надолу по веригата (РЕАЛЕН EXEL, СИНТЕТИЧЕН +3% кандидат) ──")
df = pd.read_csv(FIX / "ohlc_EXEL.csv", index_col=0, parse_dates=True).loc[:"2026-06-26"]
spy = pd.read_csv(FIX / "ohlc_SPY.csv", index_col=0, parse_dates=True)["Close"].loc[:"2026-06-26"]
exel = screener._evaluate_technicals("EXEL", df, spy)
D0 = dt.date(2026, 6, 29)
def cand(row, **over):
    c = dict(row)
    c.update({"company": c["ticker"] + " Corp", "sector": "Healthcare",
              "earnings": {"next_earnings": None, "days_to_earnings": None, "in_blackout": False},
              "options": {}, "short_view": {}, "ai": {"classification": "Action", "why_now": "тест", "catalysts": [], "risks": []}})
    c.update(over); c["setup"] = setup_rules.classify_setup(c, D0)
    return c
ext = cand({"ticker": "SYN3", "price": 103.0, "pivot": 100.0, "pct_from_pivot": 3.0, "volume_ratio": 2.0,
            "breakout_volume": True, "struct_low": 96.0})
real = cand(exel)
for regime, sizing in (("Offensive", 1.0), (out["regime"], out["sizing_factor"])):
    action, watch = brief_main.apply_hard_rules([copy.deepcopy(real), copy.deepcopy(ext)], sizing, regime)
    if regime == "Offensive":
        assert [a["ticker"] for a in action] == ["EXEL", "SYN3"] and not watch
        risk_off = {a["ticker"]: a["plan"]["max_risk_usd"] for a in action}
    else:
        assert [a["ticker"] for a in action] == ["EXEL"] and [w["ticker"] for w in watch] == ["SYN3"]
        assert watch[0]["ai"]["watchlist_reason_type"] == "regime_block" and "Режим Defensive" in watch[0]["ai"]["watchlist_trigger"]
        assert action[0]["plan"]["max_risk_usd"] == risk_off["EXEL"] / 2 and action[0]["plan"]["sizing_factor"] == 0.5
print("  ✓ при Offensive (sizing 1.0): РЕАЛЕН EXEL (+1.56%, 'good') и СИНТЕТИЧЕН +3% → 2 Action; при блока (Defensive, sizing 0.5):")
print(f"    EXEL остава Action с риск ${risk_off['EXEL'] / 2:,.0f} вместо ${risk_off['EXEL']:,.0f}, +3% отива във Watchlist 'regime_block'")
print()

print("── макро промптът и рендерът ──")
seen = {}
ai_brief._call_claude = lambda system, user, max_tokens=0: (seen.setdefault("u", user), json.dumps({"macro_brief": "x", "sector_logic": [], "regime_comment": "y"}))[1]
ai_brief.macro_and_sector_brief({}, [], out)
assert "блокът от distribution days" in seen["u"] and "не позволява Offensive" in seen["u"]
seen.clear(); ai_brief.macro_and_sector_brief({}, [], src_t)
assert "блокът от distribution days" not in seen["u"]
import html as htmllib
from src import render
new_fmt = {**src_t, "counts": src_t["regime_reason"], "regime_by_count": "Offensive", "overrides": []}
out_new = cap(new_fmt, DD("2026-09-22"), "2026-09-22")
assert out_new["regime_by_count"] == "Offensive" and out_new["regime"] == "Defensive"
brief = json.loads(json.dumps(B["2026-09-22"])); brief["thermometer"] = out
brief_new = json.loads(json.dumps(B["2026-09-22"])); brief_new["thermometer"] = out_new
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2_ = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        dash = htmllib.unescape(render.render_dashboard(brief)); mail = htmllib.unescape(render.render_email(brief))
        plain = htmllib.unescape(render.render_dashboard(json.loads(json.dumps(B["2026-09-22"]))))
        dash_new = htmllib.unescape(render.render_dashboard(brief_new)); mail_new = htmllib.unescape(render.render_email(brief_new))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2_
assert "distribution days червени (SPY 10/25, QQQ 6/25; праг 9) — Offensive блокиран" in dash and "Offensive блокиран" in mail
assert "Offensive блокиран" not in plain
assert ">Defensive</div>" in dash
assert "⚡ distribution days червени (SPY 10/25, QQQ 6/25; праг 9) — Offensive блокиран (по броене: Offensive)" in dash_new
assert ">Defensive</div>" in dash_new and "Offensive блокиран" in mail_new
print("  ✓ макро промптът казва, че кодът е блокирал Offensive (само когато има блок); dashboard (ред в заглавието) и имейл показват причината")
print()

print("── main.py ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.count("entry_timing.evaluate_distribution_days()") == 1                                    # един fetch
i_dd, i_cap = src.index("entry_timing.evaluate_distribution_days()"), src.index("apply_distribution_cap(thermo, distribution_days)")
i_thermo, i_macro, i_hard = src.index("thermo = build_thermometer(macro)"), src.index("ai_brief.macro_and_sector_brief("), src.index("apply_hard_rules(candidates, thermo[")
assert i_thermo < i_dd < i_cap < i_macro < i_hard
seg = src[i_dd - 200:i_cap + 400]
assert seg.count("try:") >= 2 and seg.count("except Exception") >= 2
print("  ✓ термометър → distribution days (try/except) → apply_distribution_cap (try/except) → макро бриф → apply_hard_rules; един fetch")
print()

fp_after = hashlib.md5(REAL_STATE.read_bytes()).hexdigest() if REAL_STATE.exists() else None
assert fp_before == fp_after, "реалният data/regime_override_state.json е пипнат!"
print("  ✓ реалният data/regime_override_state.json не е пипнат (md5 преди = след)")
_tmp.cleanup()
print()
print("Всички тестове минаха.")
