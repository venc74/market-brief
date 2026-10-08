"""
Distribution days · начално състояние на блока от историята + един знак след запетаята около прага на IEI/HYG (08.10.2026, точка 2д).

Блокът от червени distribution days (асиметричен хистерезис: включва се на първия червен ден, пада след 2 поредни нечервени) започваше с ПРАЗНО състояние ("не е блокиран"), докато не дойде червен ден —
пакетът тръгна на 05.10, а реалната история е червена 15.09–24.09 и 28.09–05.10: ако състоянието се загуби/започне наново на 07.10, Offensive щеше да се отключи ден по-рано от правилото
(вчера, 06.10, още е червено-блокиран с 1/2). Сега при първия run с тази версия (белег "seed") състоянието се гради ЕДНОКРАТНО от историята: ден по ден със същите правила върху последните
config.DISTRIBUTION_SEED_SESSIONS (15) сесии преди последната (последната се прилага от самия блок по обичайния път).

РЕАЛНО: tests/fixtures/ohlc_SPY_2026-10-07.csv и ohlc_QQQ_2026-10-07.csv — дневни барове от Yahoo до 07.10.2026 вкл. (149 сесии, четени на 08.10); от тях се смята статусът на всяка сесия.
СИНТЕТИЧНО (маркирано): състоянието "преди" (празно), термометърът "Offensive по броене" за да се види ефектът върху режима, граничните последователности, повредената история.
Пускане: python test_distribution_seed.py
"""
import sys, json, pathlib, tempfile, io, contextlib, datetime as dt, random
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import thermometer as th, entry_timing

FIX = ROOT / "tests" / "fixtures"
SPY = pd.read_csv(FIX / "ohlc_SPY_2026-10-07.csv", index_col=0, parse_dates=True)
QQQ = pd.read_csv(FIX / "ohlc_QQQ_2026-10-07.csv", index_col=0, parse_dates=True)
assert SPY.index[-1].date().isoformat() == QQQ.index[-1].date().isoformat() == "2026-10-07" and len(SPY) == len(QQQ) == 149

_tmp = tempfile.TemporaryDirectory(prefix="mb_distseed_")
STATE = pathlib.Path(_tmp.name) / "state.json"
th._OVERRIDE_STATE_FILE = STATE
quiet = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. статусът на всяка сесия от РЕАЛНИТЕ SPY/QQQ барове ──")
series = entry_timing.distribution_series(SPY, QQQ)
by = {r["date"]: r for r in series}


def independent(h, date):                                                       # без rolling: ръчен цикъл по определението (close надолу ≥ 0.2% И обем над предходния), последните 25 сесии до датата
    h = h.loc[:date]
    n = 0
    for i in range(len(h) - config.DISTRIBUTION_DAYS_LOOKBACK, len(h)):
        if (h["Close"].iloc[i] / h["Close"].iloc[i - 1] - 1) * 100 <= -config.DISTRIBUTION_DAYS_MIN_DECLINE_PCT and h["Volume"].iloc[i] > h["Volume"].iloc[i - 1]:
            n += 1
    return n


for d in ("2026-09-01", "2026-09-15", "2026-09-25", "2026-09-30", "2026-10-05", "2026-10-06", "2026-10-07"):
    assert (by[d]["spy_count"], by[d]["qqq_count"]) == (independent(SPY, d), independent(QQQ, d)), d
status = {d: r["status"] for d, r in by.items()}
seq = [(d, status[d]) for d in sorted(status) if "2026-09-08" <= d <= "2026-10-07"]
assert [s for d, s in seq if "2026-09-15" <= d <= "2026-09-24"] == ["red"] * 8 and status["2026-09-25"] == "yellow"
assert [status[d] for d in ("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05")] == ["red"] * 6
assert (status["2026-10-06"], status["2026-10-07"]) == ("yellow", "yellow") and (by["2026-10-06"]["count"], by["2026-10-07"]["count"]) == (8, 7)
print("  ✓ независим цикъл = rolling смятането; РЕАЛНАТА история: червено 15.09–24.09, жълто 25.09, червено 28.09–05.10 (SPY 9–10), жълто 06.10 (8) и 07.10 (7)")

print()
print("── 2. history(n): последните n сесии ПРЕДИ последната ──")
fetched = []
hist = entry_timing.distribution_history(15, fetch=lambda s: fetched.append(s) or (SPY if s == "SPY" else QQQ))
assert fetched == ["SPY", "QQQ"] and len(hist) == 15 and hist[0]["date"] == "2026-09-16" and hist[-1]["date"] == "2026-10-06"
assert "2026-10-07" not in [r["date"] for r in hist]                                                 # последната сесия е днешната — не е в историята
with quiet():
    assert entry_timing.distribution_history(15, fetch=lambda s: (_ for _ in ()).throw(RuntimeError("СИНТЕТИЧНО: мрежата падна"))) == []
    assert entry_timing.distribution_history(15, fetch=lambda s: pd.DataFrame()) == []
print("  ✓ 15 сесии 16.09 → 06.10 (07.10 е последната и не влиза); провал на теглене / празен отговор → [] (началното състояние остава празно, без изключение)")

print()
print("── 3. replay_distribution_block = _distribution_block ден по ден ──")
def stepwise(statuses):
    STATE.unlink(missing_ok=True)
    out = []
    for i, st in enumerate(statuses):
        dd = {"status": st, "count": {"red": 9, "yellow": 7, "green": 3}[st], "spy_count": 5, "qqq_count": 5}
        with quiet():
            blk = th._distribution_block(dd, f"2027-01-{i + 1:02d}")
        out.append((blk["blocked"], blk["nonred_days"]))
    return out


def replayed(statuses):
    return [(r["blocked"], r["streak_nonred"]) for r in (th.replay_distribution_block(statuses[:i + 1]) for i in range(len(statuses)))]


rnd = random.Random(8)
cases = [[st for _, st in seq]] + [[rnd.choice(["green", "yellow", "red"]) for _ in range(30)] for _ in range(40)] + [["red"], ["yellow"], ["red", "yellow"], ["red", "yellow", "green", "red", "green"]]
for c in cases:
    assert stepwise(c) == replayed(c), c
print(f"  ✓ {len(cases)} последователности (РЕАЛНАТА 08.09–07.10 + 40 СИНТЕТИЧНИ случайни + граничните): replay_distribution_block съвпада със самия _distribution_block във всеки ден")

print()
print("── 4. студен старт на сутринта на 07.10 и 08.10 (СИНТЕТИЧНО празно състояние, РЕАЛНА история) ──")
def run_day(day, last_session, live_status, with_history, offensive=True):
    """run на сутринта на `day`: последната затворена сесия е `last_session` с РЕАЛНИЯ ѝ статус; история = сесиите преди нея."""
    cut = lambda h: h.loc[:last_session]
    thermo = {"regime": "Offensive" if offensive else "Defensive", "regime_by_count": "Offensive", "regime_reason": "4 зелени / 0 жълти / 0 червени от 8 видими", "counts": "4 зелени / 0 жълти / 0 червени от 8 видими",
              "sizing_factor": 1.0 if offensive else 0.5, "exit_rule": "", "overrides": []}                       # СИНТЕТИЧНО: чисто Offensive по броене
    row = by[last_session]
    dd = {"status": row["status"], "count": row["count"], "spy_count": row["spy_count"], "qqq_count": row["qqq_count"]}
    hf = (lambda: entry_timing.distribution_history(config.DISTRIBUTION_SEED_SESSIONS, fetch=lambda s: cut(SPY if s == "SPY" else QQQ))) if with_history else None
    with quiet():
        return th.apply_distribution_cap(thermo, dd, dt.date.fromisoformat(day), hf)


STATE.unlink(missing_ok=True)
old = run_day("2026-10-07", "2026-10-06", "yellow", with_history=False)                                       # преди: празно състояние → не е блокиран → Offensive
assert old["regime"] == "Offensive" and "distribution_cap" not in old
STATE.unlink(missing_ok=True)
new = run_day("2026-10-07", "2026-10-06", "yellow", with_history=True)
assert new["regime"] == "Defensive" and new["distribution_cap"]["kind"] == "hysteresis" and new["distribution_cap"]["nonred_days"] == 1
assert "блокът се държи по хистерезис — 1/2 нечервени дни" in new["regime_reason"]
st = json.loads(STATE.read_text())["distribution_block"]
assert st["seed"] == {"version": 1, "sessions": 15, "from": "2026-09-15", "to": "2026-10-05"} and st["blocked"] is True and st["streak_nonred"] == 1 and st["last_date"] == "2026-10-07"
print("  ✓ 07.10 сутринта (последна сесия 06.10, жълта): без история → Offensive (блокът не е знаел за червената 05.10); с историята → Defensive, 'блокът се държи по хистерезис — 1/2 нечервени дни'")
nxt = run_day("2026-10-08", "2026-10-07", "yellow", with_history=True)                                       # следващият ден: същото състояние, без повторно изграждане
assert nxt["regime"] == "Offensive" and "distribution_cap" not in nxt
st2 = json.loads(STATE.read_text())["distribution_block"]
assert st2["blocked"] is False and st2["seed"] == st["seed"] and st2["last_date"] == "2026-10-08"
print("  ✓ 08.10 сутринта (последна сесия 07.10, жълта, 2/2): блокът пада и режимът се връща към броенето; белегът 'seed' се пази, историята не се чете повторно")
STATE.unlink(missing_ok=True)
cold8 = run_day("2026-10-08", "2026-10-07", "yellow", with_history=True)
assert cold8["regime"] == "Offensive" and json.loads(STATE.read_text())["distribution_block"]["blocked"] is False
print("  ✓ студен старт на 08.10 с историята = същото състояние, което реално имаше системата (не е блокиран): началното състояние от историята съвпада с непрекъснатата верига")

print()
print("── 5. идемпотентност, версия, повредена история (СИНТЕТИЧНО) ──")
calls = []
hf = lambda: calls.append(1) or [{"date": "2026-09-30", "status": "red"}, {"date": "2026-10-01", "status": "yellow"}]
STATE.unlink(missing_ok=True)
dd = {"status": "yellow", "count": 7, "spy_count": 7, "qqq_count": 3}
with quiet():
    b1 = th._distribution_block(dd, "2026-10-02", hf)
    b2 = th._distribution_block(dd, "2026-10-02", hf)                                                    # същият ден, втори run
assert calls == [1] and b1 == b2 and b1["blocked"] is False and b1["nonred_days"] == 2                  # червен 30.09, жълти 01.10 и днес → 2 поредни нечервени → блокът пада
s = json.loads(STATE.read_text())["distribution_block"]
assert s["seed"]["sessions"] == 2 and calls == [1]
config.DISTRIBUTION_SEED_VERSION = 2                                                                      # СИНТЕТИЧНО: правилото се промени → нов белег → ново изграждане
with quiet():
    th._distribution_block(dd, "2026-10-03", hf)
assert calls == [1, 1] and json.loads(STATE.read_text())["distribution_block"]["seed"]["version"] == 2
config.DISTRIBUTION_SEED_VERSION = 1
STATE.unlink(missing_ok=True)
with quiet():
    bad = th._distribution_block(dd, "2026-10-02", lambda: (_ for _ in ()).throw(RuntimeError("СИНТЕТИЧНО")))
    empty = th._distribution_block(dd, "2026-10-02", lambda: [])
assert bad["blocked"] is False and empty["blocked"] is False and "seed" not in json.loads(STATE.read_text())["distribution_block"]
config.DISTRIBUTION_SEED_SESSIONS = 0
STATE.unlink(missing_ok=True)
with quiet():
    off = th._distribution_block(dd, "2026-10-02", hf)
assert off["blocked"] is False and calls == [1, 1]                                                       # изключено: историята не се чете
config.DISTRIBUTION_SEED_SESSIONS = 15
print("  ✓ втори run същия ден не чете историята отново; смяна на версията изгражда наново; провал/празна история → старото поведение (без белег, не е блокиран); DISTRIBUTION_SEED_SESSIONS=0 го изключва")

print()
print("── 6. IEI/HYG: един знак след запетаята около прага ──")
ref = config.IEI_HYG_ROC_SPIKE_PERCENTILE
assert ref == 90
assert th._pct_ord(91.3) == "91.3" and th._pct_ord(90.4) == "90.4" and th._pct_ord(89.6) == "89.6" and th._pct_ord(88.1) == "88.1" and th._pct_ord(88.0) == "88."      # |p − 90| < 2 → един знак (точно 2 пункта вече не)
assert th._pct_ord(92.0) == "92." and th._pct_ord(87.6) == "88." and th._pct_ord(75.2) == "75." and th._pct_ord(100.0) == "100."
print(f"  ✓ 91.3 → «91.3», 90.4 → «90.4», 89.6 → «89.6» (по-малко от 2 пункта от прага {ref}); 92.0 → «92.», 75.2 → «75.» (по-далеч — цяло число с точка, както досега)")
print("    РЕАЛНО от 08.10: roc_percentile = 91.3 → публикуваният текст казваше «91. percentile», а коментарът на модела — «91.3»; сега и двата са «91.3 percentile»")
print("\n✅ test_distribution_seed: всичко мина")
