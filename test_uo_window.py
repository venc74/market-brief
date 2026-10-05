"""
Пакет 4б (06.10.2026) · т.а: знаменателят на съотношението обем/OI е сравним между дните. Падежите са в ПРОЗОРЕЦ (ден на брифа, ден на брифа + 21 дни]: изтекъл или изтичащ в
деня на брифа падеж не участва; обемът и OI са по едни и същи падежи; снимка в стария формат (първите 4 падежа) не се ползва.

РЕАЛНО: следобедните OI снимки 29.09–02.10.2026 (tests/fixtures/oi_snapshots_2026-09-29_10-02.json, 10 тикъра, СТАР формат) и записаните знаменатели в брифовете от 02.10 и 05.10
(TSLA 626 692 → 114 346, NVDA 1 015 923 → 187 110); жив OI по падеж от Yahoo на 05.10.2026 14:30 UTC (tests/fixtures/live_oi_2026-10-05.json) — "плъзгане" на деня на брифа
пон→пет върху СЪЩИЯ OI. СИНТЕТИЧНО: границите на дати, подменените yfinance верижни данни (клас Ticker), снимките в новия формат.
Пускане: python test_uo_window.py
"""
import sys, json, pathlib, math, statistics, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import unusual_options as uo, oi_snapshot

FIX = ROOT / "tests" / "fixtures"
SNAPS = json.loads((FIX / "oi_snapshots_2026-09-29_10-02.json").read_text(encoding="utf-8"))["snapshots"]
LIVE = json.loads((FIX / "live_oi_2026-10-05.json").read_text(encoding="utf-8"))["oi"]
D = dt.date.fromisoformat

print("── прозорецът на падежите (СИНТЕТИЧНИ дати) ──")
E = ["2026-10-02", "2026-10-05", "2026-10-07", "2026-10-09", "2026-10-26", "2026-10-27", "2026-11-20"]
assert uo.window_expiries(E, D("2026-10-05")) == ["2026-10-07", "2026-10-09", "2026-10-26"]                 # пон: 02.10 изтекъл, 05.10 изтича днес — не участват; +21д = 26.10 включително
assert uo.window_expiries(E, D("2026-10-02")) == ["2026-10-05", "2026-10-07", "2026-10-09"]                 # пет: падежът в деня на брифа (02.10) не участва
assert uo.window_expiries(E, D("2026-10-05"), horizon_days=14) == ["2026-10-07", "2026-10-09"]
assert uo.window_expiries(E, D("2026-10-05"), max_n=2) == ["2026-10-07", "2026-10-09"]
assert uo.window_expiries(["bad", "2026-10-07", "2026-10-07"], D("2026-10-05")) == ["2026-10-07"] and uo.window_expiries(None, D("2026-10-05")) == []
print("  ✓ изтеклите и изтичащите в деня на брифа не участват, +21 дни е включително, дубликати/невалидни дати се игнорират, таван на броя падежи")

print()
print("── обем и OI по едни и същи падежи ──")
r = uo.window_ratio({"A": 100, "B": 50, "C": 80}, {"A": 200, "B": 0, "D": 999}, ["A", "B", "C", "D"])
assert r["used"] == ["A"] and r["dropped"] == ["B", "C", "D"] and r["volume"] == 100 and r["oi"] == 200 and r["ratio"] == 0.5
assert uo.window_ratio({"A": 5}, {}, ["A"])["ratio"] is None
print("  ✓ падеж без OI (B), без обем (D) или без и двете (C) отпада и от числителя, и от знаменателя; ratio=100/200")

print()
print("── РЕАЛНО: знаменателят преди (записан в брифовете) ──")
bd = {"2026-10-02": json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8")), "2026-10-05": json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))}
pairs = {"2026-09-30": "2026-09-29", "2026-10-01": "2026-09-30", "2026-10-02": "2026-10-01", "2026-10-05": "2026-10-02"}     # бриф → сесия на снимката


def den_old(sym, d, s):          # старото правило: най-близките 2 падежа, които още са в сутрешната верига (>= деня на брифа)
    oi = SNAPS[s]["tickers"][sym]
    return sum(oi[e] for e in [e for e in sorted(oi) if e >= d][:2])


for day in ("2026-10-02", "2026-10-05"):
    raw = bd[day]["unusual_options_diag"]["raw_oi"]
    for sym in ("TSLA", "NVDA"):
        assert den_old(sym, day, pairs[day]) == raw[sym], (day, sym)
print("  ✓ старото правило от снимките възпроизвежда записаното в брифовете: 02.10 TSLA 626 692 / NVDA 1 015 923; 05.10 TSLA 114 346 / NVDA 187 110")


def den_gt(sym, d, s, k):
    oi = SNAPS[s]["tickers"][sym]
    return sum(oi[e] for e in [e for e in sorted(oi) if e > d][:k])


NAMES = list(SNAPS["2026-10-02"]["tickers"])
assert len(NAMES) == 10


def stab(f):
    cvs, swings = [], []
    for sym in NAMES:
        ds = [f(sym, d, s) for d, s in pairs.items()]
        cvs.append(statistics.pstdev(ds) / statistics.mean(ds))
        swings += [abs(math.log(ds[i + 1] / ds[i])) for i in range(3) if ds[i] > 0 and ds[i + 1] > 0]
    return statistics.mean(cvs), math.exp(statistics.median(swings)), math.exp(max(swings))


s_old, s_gt2, s_gt3 = stab(den_old), stab(lambda a, b, c: den_gt(a, b, c, 2)), stab(lambda a, b, c: den_gt(a, b, c, 3))
print("  знаменател по дни (бриф 30.09 / 01.10 / 02.10 / 05.10):")
for sym in ("TSLA", "NVDA"):
    print(f"    {sym} старо правило: {[den_old(sym, d, s) for d, s in pairs.items()]}")
print(f"  стабилност на 10 тикъра (CV · типична дневна промяна · най-голяма): старо ×2 → {s_old[0]:.2f} · ×{s_old[1]:.2f} · ×{s_old[2]:.1f};")
print(f"    само 'без изтичащите' (първите 2) → {s_gt2[0]:.2f} · ×{s_gt2[1]:.2f} · ×{s_gt2[2]:.1f};  първите 3 → {s_gt3[0]:.2f} · ×{s_gt3[1]:.2f} · ×{s_gt3[2]:.1f}")
assert s_gt2[0] > s_old[0] and s_gt2[1] > 3 * s_old[1]            # буквалното правило САМО по себе си не стабилизира знаменателя — по-лошо е от старото
assert s_gt3[0] < s_old[0]                                         # повече падежи помагат
print("  ✓ буквално 'без изтичащите, най-близките 2' е ПО-НЕСТАБИЛНО от старото (петъчният падеж влиза/излиза); повече падежи стабилизират → затова прозорец")

print()
print("── РЕАЛНО: плъзгане на деня на брифа върху СЪЩИЯ жив OI (05.10) ──")
DS = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]


def near2(oi, d):
    return sum(oi[e] for e in [e for e in sorted(oi) if e > d][:2])


def window(oi, d):
    w = uo.window_expiries(list(oi), D(d))
    return sum(oi[e] for e in w)


print(f"  {'':6} {'най-близките 2 (пон…пет)':<48} {'прозорец 21д (пон…пет)':<44}")
out = {}
for sym in ("TSLA", "NVDA", "AAPL"):
    a, b = [near2(LIVE[sym], d) for d in DS], [window(LIVE[sym], d) for d in DS]
    out[sym] = (max(a) / min(a), max(b) / min(b))
    print(f"  {sym:<6} {str(a):<48} {str(b):<44} ×{out[sym][0]:.1f} → ×{out[sym][1]:.2f}")
assert out["TSLA"][0] > 10 and out["NVDA"][0] > 20 and out["AAPL"][0] > 10
assert all(out[s][1] < 1.5 for s in out)
for sym in ("EXPD", "FTNT"):                                              # без седмични падежи — всяко правило е стабилно
    a, b = [near2(LIVE[sym], d) for d in DS], [window(LIVE[sym], d) for d in DS]
    assert max(a) / min(a) < 1.1 and max(b) / min(b) < 1.15
print(f"  ✓ най-близките 2 се клатят ×{out['TSLA'][0]:.1f} / ×{out['NVDA'][0]:.1f} / ×{out['AAPL'][0]:.1f} (TSLA/NVDA/AAPL) за една седмица, прозорецът от 21 дни — ×{out['TSLA'][1]:.2f} / ×{out['NVDA'][1]:.2f} / ×{out['AAPL'][1]:.2f}; EXPD и FTNT (само месечни падежи) са стабилни и в двата случая")

print()
print("── снимка в стария формат ──")
assert not uo.snapshot_in_window_format(SNAPS["2026-10-02"]) and not uo.snapshot_in_window_format(None)
assert uo.snapshot_in_window_format({"horizon_days": 28}) and not uo.snapshot_in_window_format({"horizon_days": 21})
print("  ✓ реалната снимка от 02.10 (без horizon_days) не е в новия формат; horizon_days ≥ 25 е нужен (прозорец 21 + до 4 дни между сесията и брифа)")


# ── yfinance заместител (СИНТЕТИЧНИ вериги) ──
class Chain:
    def __init__(self, c, p):
        self.calls, self.puts = c, p


class FakeTicker:
    def __init__(self, data):                                               # data: {падеж: (call_vol, call_oi, put_vol, put_oi)}
        self.data, self.options = data, tuple(sorted(data))

    def option_chain(self, exp):
        cv, co, pv, po = self.data[exp]
        mk = lambda v, o: pd.DataFrame({"volume": [v], "openInterest": [o]})
        return Chain(mk(cv, co), mk(pv, po))


print()
print("── analyze_ticker (СИНТЕТИЧНА верига, снимка в НОВИЯ формат) ──")
tk = FakeTicker({"2026-10-05": (900, 10, 900, 10), "2026-10-07": (300, 0, 100, 0), "2026-10-09": (200, 0, 200, 0), "2026-10-16": (50, 0, 50, 0), "2026-12-18": (999, 0, 999, 0)})
snap = {"horizon_days": 28, "tickers": {"XYZ": {"2026-10-07": 400, "2026-10-09": 600, "2026-10-12": 5000}}}       # 10-16 няма OI в снимката; 10-12 няма верига
a = uo.analyze_ticker("XYZ", tk, snap, D("2026-10-05"))
assert a["window"] == ["2026-10-07", "2026-10-09", "2026-10-16"] and a["used"] == ["2026-10-07", "2026-10-09"] and a["dropped"] == ["2026-10-16"]
assert a["oi_used"] == 1000 and a["ratio"] == (400 + 400) / 1000 == 0.8 and a["why"] == "" and a["call_vol"] == 550 and a["put_vol"] == 350
print("  ✓ прозорец {07.10, 09.10, 16.10}; 05.10 (изтича в деня на брифа) и 18.12 (извън прозореца) не участват; 16.10 няма OI → отпада и от обема; ratio = 800 / 1000 = 0.8")
a = uo.analyze_ticker("XYZ", tk, {"tickers": snap["tickers"]}, D("2026-10-05"))                                  # стар формат
assert a["ratio"] is None and "стария формат" in a["why"]
assert uo.analyze_ticker("XYZ", tk, None, D("2026-10-05"), "снимката липсва")["why"] == "снимката липсва"
assert "не е в следобедната" in uo.analyze_ticker("QQQ", tk, snap, D("2026-10-05"))["why"]
assert "под 50" in uo.analyze_ticker("XYZ", tk, {"horizon_days": 28, "tickers": {"XYZ": {"2026-10-07": 20}}}, D("2026-10-05"))["why"]
assert "не съвпадат" in uo.analyze_ticker("XYZ", tk, {"horizon_days": 28, "tickers": {"XYZ": {"2026-11-01": 500}}}, D("2026-10-05"))["why"]
assert uo.analyze_ticker("XYZ", FakeTicker({}), snap, D("2026-10-05")) is None
print("  ✓ стар формат на снимката, липсваща снимка, тикър извън снимката, OI < 50, несъвпадащи падежи — без съотношение и с причина; без падежи → None")

print()
print("── снимката на следобедния job (нов формат) ──")
tk2 = FakeTicker({"2026-10-02": (1, 500, 1, 500), "2026-10-05": (1, 100, 1, 100), "2026-10-30": (1, 40, 1, 40), "2026-10-31": (1, 7, 1, 7), "2026-12-18": (1, 9, 1, 9)})
per = oi_snapshot._window_oi(tk2, D("2026-10-02"))
assert per == {"2026-10-05": 200, "2026-10-30": 80}, per                                                                # 02.10 е денят на сесията (изтича) → не се снима; 31.10 е след +28д; 18.12 — далеч
print("  ✓ _window_oi: падежът, изтичащ в деня на сесията (02.10), не се снима; 05.10 и 30.10 (+28д) да; 31.10 и 18.12 — извън прозореца")
assert config.UNUSUAL_OPTIONS_HORIZON_DAYS == 21 and config.UNUSUAL_OPTIONS_OI_SNAPSHOT_HORIZON_DAYS == 28

print()
print("Всички тестове минаха.")
