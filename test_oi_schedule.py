"""
12.10.2026 · резерва за OI снимката в кода: още schedule тригери в oi_snapshot.yml + идемпотентност и прозорец (oi_snapshot._skip_reason, преди мрежата).

РЕАЛНО: tests/fixtures/oi_snapshot_file_2026-10-12.json — файлът със снимките в main към 12.10 (сесии 06.10–08.10; 09.10 липсва); часовете на РЕАЛНИТЕ run-ове
(dispatch 09.10 16:00:49 UTC; schedule 09.10 20:03 UTC); измереното закъснение на GitHub scheduler-а в репото (oi_snapshot "0 15": 30.09–09.10; daily_brief "30 5"/"30 6": юни).
СИНТЕТИЧНО (означено): часовете през зимното време (ноември), подмененият часовник и подмененото теглене на сесията в take_snapshot.
Пускане: python test_oi_schedule.py
"""
import sys, json, pathlib, io, contextlib, types, re, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import oi_snapshot as o

SNAPS = json.loads((ROOT / "tests" / "fixtures" / "oi_snapshot_file_2026-10-12.json").read_text(encoding="utf-8"))["snapshots"]
UTC = dt.timezone.utc
T = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=UTC)
D = dt.date.fromisoformat

print("── 1. _skip_reason върху РЕАЛНИЯ файл ──")
assert sorted(SNAPS) == ["2026-10-06", "2026-10-07", "2026-10-08"] and o.snapshot_is_complete(SNAPS["2026-10-08"])
r = o._skip_reason(D("2026-10-08"), SNAPS, T("2026-10-08T17:13:00"))                                     # съществуваща пълна снимка → прескача, без презапис
assert r.startswith("пълна снимка за сесия 2026-10-08 вече съществува (fetched_at_utc=2026-10-08 16:01)") and "не презаписвам" in r
assert o._skip_reason(D("2026-10-09"), SNAPS, T("2026-10-09T16:00:49")) is None                          # липсваща (09.10) в прозореца → снима (РЕАЛНИЯТ dispatch)
r = o._skip_reason(D("2026-10-09"), SNAPS, T("2026-10-09T20:03:22"))                                     # РЕАЛНИЯТ schedule run от 09.10 → след прага
assert "20:03 UTC (16:03 EDT) — след прага (16:00 Ню Йорк)" in r
r = o._skip_reason(D("2026-10-09"), SNAPS, T("2026-10-09T12:17:00"))                                     # cron "17 12" навреме → 08:17 EDT, преди отварянето
assert r == "12:17 UTC (08:17 EDT) — преди началото на валидния OI прозорец (09:30 Ню Йорк) — пропускам, по-късен тригер опитва пак"
assert o._skip_reason(D("2026-10-09"), SNAPS, T("2026-10-09T13:29:00")) is not None and o._skip_reason(D("2026-10-09"), SNAPS, T("2026-10-09T13:30:00")) is None
print("  ✓ 08.10 (има пълна) → 'вече съществува … не презаписвам'; 09.10 в 16:00:49 → снима; 09.10 в 20:03 → след прага; 12:17 UTC → преди 09:30 ET; 13:30 UTC — първата валидна минута")
w = [o._skip_reason(D("2026-11-10"), SNAPS, T(f"2026-11-10T{h}")) for h in ("14:29:00", "14:30:00", "20:59:00", "21:00:00")]   # СИНТЕТИЧНО: зимно време (EST)
assert w[0].startswith("14:29 UTC (09:29 EST) — преди началото") and w[1] is None and w[2] is None and "след прага" in w[3]
print("  ✓ зимно време (СИНТЕТИЧНО, 10.11): 14:29 UTC → преди отварянето; 14:30 и 20:59 → снима; 21:00 → след прага")

print()
print("── 2. take_snapshot: прескачането е преди мрежата и с ред ::notice:: ──")


class FixedDT(dt.datetime):                                                                                # СИНТЕТИЧНО: часовникът е на 08.10 в 17:13 UTC (съществува пълна снимка)
    now_value = T("2026-10-08T17:13:00")

    @classmethod
    def now(cls, tz=None):
        return cls.now_value.astimezone(tz) if tz else cls.now_value.replace(tzinfo=None)


orig = (o.dt, o.uo.last_session_date, o.uo.load_oi_snapshots)
o.dt = types.SimpleNamespace(date=dt.date, timedelta=dt.timedelta, timezone=dt.timezone, datetime=FixedDT)
o.uo.load_oi_snapshots = lambda: SNAPS
o.uo.last_session_date = lambda: (_ for _ in ()).throw(AssertionError("сесията (мрежа) не бива да се тегли при прескачане"))
for now, want in (("2026-10-08T17:13:00", "пълна снимка за сесия 2026-10-08 вече съществува"), ("2026-10-09T12:17:00", "преди началото на валидния OI прозорец"),
                  ("2026-10-09T20:03:22", "след прага")):
    FixedDT.now_value = T(now)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert o.take_snapshot() is None
    log = out.getvalue()
    assert f"[oi_snapshot] " in log and want in log and re.search(r"^::notice title=OI snapshot::.*" + re.escape(want), log, re.M), log
FixedDT.now_value = T("2026-10-09T16:00:49")                                                             # в прозореца, без снимка → стига до сесията
seen = {}
o.uo.last_session_date = lambda: seen.setdefault("session", D("2026-10-08"))                               # СИНТЕТИЧНО: "днес няма сесия" — спира преди тегленето на OI
with contextlib.redirect_stdout(io.StringIO()) as out:
    assert o.take_snapshot() is None
assert seen and "днес (2026-10-09) няма сесия" in out.getvalue()
o.dt, o.uo.last_session_date, o.uo.load_oi_snapshots = orig
print("  ✓ съществуваща снимка / преди отварянето / след прага → ред в лога + ::notice:: (видим в обобщението на run-а), без теглене на сесията; в прозореца без снимка → стига до сесията")

print()
print("── 3. тригерите в oi_snapshot.yml срещу измереното закъснение ──")
yml = (ROOT / ".github" / "workflows" / "oi_snapshot.yml").read_text(encoding="utf-8")
crons = re.findall(r'-\s*cron:\s*"(\d+) (\d+) \* \* 1-5"', yml)
C = [int(h) * 60 + int(m) for m, h in crons]
assert sorted(C) == [5 * 60 + 47, 9 * 60 + 47, 12 * 60 + 17, 15 * 60, 17 * 60 + 37] and "workflow_dispatch" in yml
OCT = [(4, 54), (5, 16), (4, 51), (6, 56), (5, 7), (5, 31), (5, 37), (5, 3)]          # "0 15" → 19:54, 20:16, 19:51, 21:56, 20:07, 20:31, 20:37, 20:03 UTC (30.09–09.10)
JUN = [(14, 25), (13, 35), (10, 49), (13, 26)]                                        # "30 5"/"30 6" → 15.06 19:55 и 20:05, 19.06 16:19, 22.06 18:56 UTC
ON_TIME = [(0, 0), (0, 15), (0, 30), (1, 0)]
WIN = {"EDT": (13 * 60 + 30, 20 * 60), "EST": (14 * 60 + 30, 21 * 60)}


def in_window(delays, win, crons):
    """За всяко закъснение — колко тригера стрелят в прозореца."""
    lo, hi = win
    return [sum(lo <= (c + h * 60 + m) % 1440 < hi for c in crons) for h, m in delays]


old = [15 * 60]
for name, delays in (("октомври", OCT), ("юни", JUN), ("навреме", ON_TIME)):
    for tz, win in WIN.items():
        new_n, old_n = in_window(delays, win, C), in_window(delays, win, old)
        print(f"  {name:9s} {tz}: дни с ≥1 тригер в прозореца — сега {sum(x >= 1 for x in new_n)}/{len(delays)}, с ≥2 — {sum(x >= 2 for x in new_n)}/{len(delays)}; само \"0 15\" — {sum(x >= 1 for x in old_n)}/{len(delays)}")
assert all(x >= 2 for tz in WIN for x in in_window(OCT, WIN[tz], C))                                     # при октомврийските закъснения — поне ДВА шанса всеки ден, и лете, и зиме
assert all(x >= 2 for tz in WIN for x in in_window(ON_TIME, WIN[tz], C))                                 # навреме — 15:00 и 17:37
assert sum(x >= 1 for x in in_window(JUN, WIN["EDT"], C)) == 3 and all(x >= 1 for x in in_window(JUN, WIN["EST"], C))
assert sum(x >= 1 for x in in_window(OCT, WIN["EDT"], old)) == 2                                         # досегашният "0 15" — 2 от 8 лете
print()
print("Всички тестове минаха.")
