"""
Пакет 2 · т.3 (2026-10-03): Put/Call на SPY — percentile спрямо собствената история (90./10.), скрит при провал на данните
или недостатъчна история.

РЕАЛНО: 78-те стойности на P/C от записаните брифове 13.06–02.10.2026 (вградени по-долу, извадени на 03.10.2026) —
с тях се възпроизвежда разпределението на цветовете преди/след. СИНТЕТИЧНО: граничните percentile стойности,
опционната верига (мрежата е подменена), файловете на историята във временна папка.
Пускане: python test_put_call.py
"""
import sys, pathlib, json, tempfile, datetime as dt, collections, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import thermometer as th

REAL = [
    ("2026-06-13", 0.83), ("2026-06-14", 0.83), ("2026-06-18", 1.08), ("2026-06-19", 1.12),
    ("2026-06-22", 1.02), ("2026-06-24", 1.03), ("2026-06-25", 1.01), ("2026-06-26", 1.14),
    ("2026-06-29", 1.19), ("2026-06-30", 1.42), ("2026-07-01", 0.88), ("2026-07-02", 1.01),
    ("2026-07-03", 0.94), ("2026-07-06", 0.94), ("2026-07-07", 1.02), ("2026-07-08", 1.06),
    ("2026-07-09", 1.28), ("2026-07-10", 1.0), ("2026-07-13", 1.1), ("2026-07-14", 1.21),
    ("2026-07-15", 0.89), ("2026-07-16", 0.99), ("2026-07-17", 1.18), ("2026-07-20", 1.2),
    ("2026-07-21", 1.16), ("2026-07-22", 1.21), ("2026-07-23", 1.24), ("2026-07-24", 1.2),
    ("2026-07-27", 1.17), ("2026-07-28", 0.98), ("2026-07-29", 1.07), ("2026-07-30", 1.14),
    ("2026-07-31", 1.21), ("2026-08-03", 1.04), ("2026-08-04", 0.91), ("2026-08-05", 0.47),
    ("2026-08-06", 0.63), ("2026-08-07", 1.26), ("2026-08-10", 1.13), ("2026-08-11", 1.03),
    ("2026-08-12", 1.13), ("2026-08-13", 1.12), ("2026-08-14", 0.78), ("2026-08-17", 1.23),
    ("2026-08-18", 1.11), ("2026-08-19", 1.55), ("2026-08-20", 1.12), ("2026-08-21", 1.38),
    ("2026-08-24", 1.16), ("2026-08-25", 1.34), ("2026-08-26", 1.05), ("2026-08-27", 1.12),
    ("2026-08-28", 1.08), ("2026-08-31", 1.06), ("2026-09-01", 1.21), ("2026-09-02", 1.24),
    ("2026-09-03", 1.13), ("2026-09-04", 1.02), ("2026-09-07", 1.47), ("2026-09-08", 1.47),
    ("2026-09-09", 1.54), ("2026-09-10", 1.5), ("2026-09-11", 1.44), ("2026-09-14", 1.61),
    ("2026-09-15", 1.53), ("2026-09-16", 1.27), ("2026-09-17", 1.22), ("2026-09-18", 0.87),
    ("2026-09-21", 1.19), ("2026-09-22", 0.88), ("2026-09-23", 0.95), ("2026-09-24", 1.17),
    ("2026-09-25", 1.01), ("2026-09-28", 1.02), ("2026-09-29", 0.96), ("2026-09-30", 1.01),
    ("2026-10-01", 1.1), ("2026-10-02", 1.15),
]
VALS = [v for _, v in REAL]
assert len(REAL) == 78

def old_color(pc):                                  # старото правило: >1.1 зелено, <0.7 червено
    return "green" if pc > 1.1 else ("red" if pc < 0.7 else "yellow")

print("── РЕАЛНО: разпределение на цветовете преди/след (78 дни) ──")
before = collections.Counter(old_color(v) for v in VALS)
assert dict(before) == {"green": 42, "yellow": 34, "red": 2}                     # съвпада със записаното в брифовете
exp = []
for i, v in enumerate(VALS):
    hist = VALS[:i]                                                              # само предишни дни — без поглед напред
    exp.append(th._evaluate_put_call(v, hist)["status"] if len(hist) >= config.PUTCALL_MIN_HISTORY else "hidden")
after = collections.Counter(exp)
assert dict(after) == {"hidden": 30, "yellow": 31, "green": 13, "red": 4}, dict(after)
loo = collections.Counter(th._evaluate_put_call(v, VALS[:i] + VALS[i + 1:])["status"] for i, v in enumerate(VALS))
assert dict(loo) == {"yellow": 62, "green": 8, "red": 8}, dict(loo)
print(f"  преди (1.1/0.7): зелено {before['green']} ({before['green']/78*100:.0f}%) / жълто {before['yellow']} / червено {before['red']}")
print(f"  след 90./10. без поглед напред (първите 30 дни скрити): зелено {after['green']} / жълто {after['yellow']} / червено {after['red']} / скрито {after['hidden']}")
print(f"  след 90./10. в стационарно състояние (спрямо останалите дни): зелено {loo['green']} / жълто {loo['yellow']} / червено {loo['red']}  (= 10% / 80% / 10%)")
print(f"  медиана на P/C = {sorted(VALS)[39]:.2f}: затова фиксираното 'над 1.1 → зелено' беше зелено половината от дните")

print()
print("── СИНТЕТИЧНО: граници на percentile ──")
H = [float(i) for i in range(1, 101)]                                            # история 1..100 (100 дни)
for cur, want, pct in ((90.0, "green", 90.0), (89.0, "yellow", 89.0), (11.0, "yellow", 11.0), (10.0, "red", 10.0), (1.0, "red", 1.0), (150.0, "green", 100.0)):
    r = th._evaluate_put_call(cur, H)
    assert (r["status"], r["percentile"]) == (want, pct), (cur, r)
assert th._evaluate_put_call(50.0, H)["label"] == "P/C 50.00 (50. percentile от 100 дни; в нормалния диапазон)"
r = th._evaluate_put_call(5.0, H); assert "самодоволство" in r["label"] and r["history_days"] == 100
long = [float(i) for i in range(1, 400)]                                         # само последните PUTCALL_LOOKBACK=252 стойности
assert th._evaluate_put_call(399.0, long)["history_days"] == 252
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    short = th._evaluate_put_call(1.0, [1.0] * 29)                               # 29 < 30 → скрит
assert short["hide"] is True and short["value"] is None and "недостатъчна история" in buf.getvalue()
assert th._evaluate_put_call(1.0, [1.0] * 30).get("hide") is None
print("  ✓ 90. percentile → зелено, 89. → жълто; 10. → червено, 11. → жълто; над историята → 100.; само последните 252 дни; под 30 дни → скрит")

print()
print("── СИНТЕТИЧНО: провал на данните скрива индикатора ──")
class Chain:                                                                       # опционна верига с обеми
    def __init__(self, puts, calls):
        self.puts = pd.DataFrame({"volume": puts}); self.calls = pd.DataFrame({"volume": calls})
class FakeSPY:
    def __init__(self, mode): self.mode = mode
    @property
    def options(self):
        if self.mode == "no_options": return ()
        return ("2026-10-05",)
    def option_chain(self, exp):
        if self.mode == "boom": raise RuntimeError("Yahoo 429")
        if self.mode == "no_calls": return Chain([100, 50], [0, None])
        if self.mode == "nan_vol": return Chain([None, None], [None, 10])
        return Chain([1100, 400], [1000, 500])
tmp = tempfile.TemporaryDirectory(prefix="market_brief_pc_")
T = pathlib.Path(tmp.name)
config.DATA_DIR = T
config.PUTCALL_HISTORY_FILE = T / "put_call_history.json"
orig_ticker = th.yf.Ticker
def run(mode, day):
    th.yf.Ticker = lambda sym: FakeSPY(mode)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            return th.market_put_call(today=dt.date(*day)), buf.getvalue()
    finally:
        th.yf.Ticker = orig_ticker
for mode in ("no_options", "boom", "no_calls"):
    r, log = run(mode, (2026, 10, 5))
    assert r["hide"] is True and r["value"] is None and r["label"] == "" and "P/C скрит" in log, mode
print("  ✓ няма опции / Yahoo грешка / нулев call обем → hide=True (не остава видимо жълт 'P/C: няма данни'), причината е в лога")

# включен в броенето? скритият не се брои
ind = [{"name": "A", "status": "green"}, {"name": "B", "status": "green"}, {"name": "C", "status": "green"}, {"name": "D", "status": "green"},
       {"name": "Put/Call (SPY)", "value": None, "status": "yellow", "hide": True, "label": ""}]
cnt, why, counts = th._count_regime(ind, min_visible=4)
assert cnt == "Offensive" and "4 зелени / 0 жълти / 0 червени от 4 видими (1 скрити" in counts
print("  ✓ скритият Put/Call излиза от 'видими' и не добавя жълт в броенето")

print()
print("── историята: самобутстрап от брифовете и запис ──")
# файл с история липсва → пресъздава се от snapshot файловете в data/ (СИНТЕТИЧНИ малки брифове)
for k, (d, v) in enumerate(REAL[:40]):
    (T / f"{d}.json").write_text(json.dumps({"thermometer": {"indicators": [{"name": "SPY тренд", "value": 700.0}, {"name": "Put/Call (SPY)", "value": v}]}}))
hist = th._load_put_call_history("2026-10-05")
assert len(hist) == 40 and hist["2026-06-13"] == 0.83
r, log = run("ok", (2026, 10, 5))                                                  # 1100+400 / 1000+500 = 1.0
assert r["value"] == 1.0 and r["history_days"] == 40 and r["status"] in ("green", "yellow", "red")
saved = json.loads(config.PUTCALL_HISTORY_FILE.read_text())
assert len(saved) == 41 and saved["2026-10-05"] == 1.0                            # днешната стойност е записана
r2, _ = run("ok", (2026, 10, 5))                                                   # същият ден втори път — идемпотентно, без самосравняване
assert r2["history_days"] == 40 and len(json.loads(config.PUTCALL_HISTORY_FILE.read_text())) == 41
r3, _ = run("ok", (2026, 10, 6))
assert r3["history_days"] == 41
# повреден файл → пресъздава се от брифовете, без крах
config.PUTCALL_HISTORY_FILE.write_text("{счупен json")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    h2 = th._load_put_call_history("2026-10-07")
assert len(h2) == 40 and "повреден" in buf.getvalue()
tmp.cleanup()
print("  ✓ без файл: 40 дни от брифовете; днешната стойност се записва веднъж (идемпотентно); повреден файл → пресъздава се")

print()
print("Всички тестове минаха.")
