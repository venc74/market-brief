"""
Пакет 1б (2026-10-05) · точка 2: обобщението на buy-stop книгата. Win rate (с интервал на Wilson), медианата на R, сравнението със SPY и разбивката по режим
се показват чак при ≥ 20 ЗАТВОРЕНИ записа; дотогава — само броят и средният R. Чисто локално четене (без мрежа).

РЕАЛНО: само образецът на числата — реплеят на реалните кандидати 13.06–02.10.2026 даде 14 затворени (13 стопа по −1.0R и 1 trailing изход +1.57R, 1 печеливш);
тези стойности са взети оттам. СИНТЕТИЧНО: всички записи на tracker-а (тикъри T01…), режимите, датите, подменената директория data/ и yf.
Пускане: python test_buystop_summary.py
"""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import backtest

_tmp = tempfile.TemporaryDirectory(prefix="mb_bss_")
config.DATA_DIR = pathlib.Path(_tmp.name)
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
backtest.yf.download = lambda *a, **k: (_ for _ in ()).throw(AssertionError("обобщението на buy-stop книгата не бива да тегли цени"))
backtest._fetch_current_prices = lambda *a, **k: (_ for _ in ()).throw(AssertionError("не бива да тегли цени"))
assert config.BUYSTOP_MIN_CLOSED_FOR_WINRATE == 20

_n = [0]


def rec(status, r=None, regime="Defensive", category="buystop", day="2026-09-10", res=None, fill=True, **kw):
    _n[0] += 1
    t = f"T{_n[0]:02d}"
    d = {"method": "v2", "ticker": t, "entry_date": day, "status": status, "buy_stop": 100.0, "max_chase": 105.0, "stop_loss": 92.0, "target_1": 116.0,
         "valid_through": "2026-09-16", "fill_date": day if fill and status not in ("pending", "not_triggered", "skipped_extended", "invalid_risk") else None,
         "fill_price": 100.0, "realized_r": r, "current_r": None, "resolution_date": res, "regime": regime, "return_pct": None, "spy_return_pct": None}
    if category:
        d["category"] = category
    d.update(kw)
    return f"{t}_{day}_{category or 'a'}", d


def put(items):
    backtest._save_tracker(dict(items))


def wilson(k, n, z=1.96):                    # НЕЗАВИСИМО изчисление на теста (не извиква кода)
    import math
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


print("── празен tracker ──")
put([])
S = backtest.get_buystop_summary()
assert S["records"] == 0 and S["closed"] == 0 and not S["stats_visible"] and S["avg_realized_r"] is None and S["not_triggered_pct"] is None
assert S["win_rate_pct"] is None and S["live"] == [] and S["recent"] == [] and S["min_closed"] == 20
print("  ✓ нула записи: нищо за показване, win rate липсва, прагът е 20")

print()
print("── 14 затворени (по образеца на реалния реплей): само брой и среден R ──")
items = [rec("stopped", -1.0, res=f"2026-09-{12 + i:02d}") for i in range(13)] + [rec("trailing_stop_exit", 1.57, res="2026-09-28")]
items += [rec("pending", fill=False) for _ in range(3)] + [rec("open") for _ in range(2)] + [rec("not_triggered", fill=False, res="2026-09-16") for _ in range(8)]
items += [rec("skipped_extended", fill=False, res="2026-09-12")]
items += [rec("open", None, category=None, regime="Defensive"), rec("stopped", -1.0, category=None, res="2026-09-20")]                       # Action записи — не се броят
put(items)
S = backtest.get_buystop_summary()
assert S["records"] == 14 + 3 + 2 + 8 + 1 == 28, S["records"]
assert (S["closed"], S["pending"], S["open"], S["not_triggered"], S["skipped"], S["triggered"]) == (14, 3, 2, 8, 1, 16)
assert S["avg_realized_r"] == round((13 * -1.0 + 1.57) / 14, 2) == -0.82
assert S["not_triggered_pct"] == round(100 * 8 / (16 + 8 + 1), 1) == 32.0
assert not S["stats_visible"] and S["win_rate_pct"] is None and S["win_ci_pct"] is None and S["wins"] is None and S["losses"] is None
assert S["median_realized_r"] is None and S["spy_compare"] is None and all(g["avg_r"] is None for g in S["by_regime"].values())
print("  ✓ 28 записа (Action записите не се броят): 14 затворени, 3 чакат, 2 отворени, 8 не се задействаха (32% от приключилите прозорци), 1 над тавана;")
print("    среден R −0.82; win rate, интервал, медиана, SPY и разбивка по режим — скрити (n < 20)")

print()
print("── границата 19 → 20 ──")
more = [rec("stopped", -1.0, res="2026-09-29") for _ in range(5)]
put(items + more[:4])                                                                                                  # 18 затворени → скрито
assert not backtest.get_buystop_summary()["stats_visible"]
put(items + more[:5])                                                                                                  # 19
assert not backtest.get_buystop_summary()["stats_visible"] and backtest.get_buystop_summary()["closed"] == 19
put(items + more[:5] + [rec("trailing_stop_exit", 2.1, res="2026-09-30")])                                             # 20-ият затворен
S = backtest.get_buystop_summary()
assert S["closed"] == 20 and S["stats_visible"]
assert (S["wins"], S["losses"], S["win_rate_pct"]) == (2, 18, 10.0)
assert S["win_ci_pct"] == wilson(2, 20)
assert S["median_realized_r"] == -1.0
print(f"  ✓ при 19 затворени всичко е скрито; при 20-ия се появяват: win rate 10.0% (2 печеливши / 18 губещи), интервал {S['win_ci_pct']} (= независимото Wilson), медиана R −1.0")
assert backtest._wilson_ci_pct(10, 20) == [29.9, 70.1] and backtest._wilson_ci_pct(0, 0) is None

print()
print("── медиана, сравнение със SPY и режими (≥ 20) ──")
rs = [-1.0] * 10 + [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 1.2, 0.8, 0.4, 0.2]
regs = (["Offensive"] * 6 + ["Defensive"] * 12 + ["Cash"] * 2)
items = [rec("stopped" if r < 0 else "trailing_stop_exit", r, regime=g, res=f"2026-09-{10 + i:02d}", return_pct=r * 6.0, spy_return_pct=1.0)
         for i, (r, g) in enumerate(zip(rs, regs))]
items += [rec("open", None, regime=None)]                                                                              # запис без режим → "н/д"
put(items)
S = backtest.get_buystop_summary()
assert S["closed"] == 20 and S["stats_visible"]
srt = sorted(rs); med = (srt[9] + srt[10]) / 2
assert S["median_realized_r"] == round(med, 2) == -0.4
assert S["wins"] == 10 and S["win_rate_pct"] == 50.0 and S["win_ci_pct"] == [29.9, 70.1]
assert S["spy_compare"]["n"] == 20 and S["spy_compare"]["avg_spy_pct"] == 1.0 and S["spy_compare"]["avg_return_pct"] == round(sum(r * 6.0 for r in rs) / 20, 2)
assert S["spy_compare"]["avg_alpha_pct"] == round(S["spy_compare"]["avg_return_pct"] - 1.0, 2)
br = S["by_regime"]
assert br["Offensive"]["records"] == 6 and br["Defensive"]["closed"] == 12 and br["Cash"]["closed"] == 2 and br["н/д"] == {"records": 1, "closed": 0, "avg_r": None}
assert br["Offensive"]["avg_r"] == round(sum(rs[:6]) / 6, 2) and br["Cash"]["avg_r"] == round(sum(rs[18:]) / 2, 2)
print("  ✓ 20 затворени (10 печеливши): win rate 50.0% [29.9; 70.1], медиана, SPY сравнение (n=20), разбивка по режим (Offensive 6 / Defensive 12 / Cash 2 затворени; запис без режим → 'н/д')")

print()
print("── редовете за показване ──")
items = [rec("pending", day="2026-10-06", fill=False), rec("open", day="2026-10-02"), rec("trailing", day="2026-09-30", current_r=1.2)]
items += [rec("stopped", -1.0, res=f"2026-09-{i:02d}") for i in range(1, 13)]
put(items)
S = backtest.get_buystop_summary()
assert [x["entry_date"] for x in S["live"]] == ["2026-09-30", "2026-10-02", "2026-10-06"] and S["live"][0]["current_r"] == 1.2
assert S["open"] == 2 and S["pending"] == 1
assert len(S["recent"]) == 10 and [x["resolution_date"] for x in S["recent"]] == [f"2026-09-{i:02d}" for i in range(12, 2, -1)]
assert all(x["resolution"] == "stopped" and x["realized_r"] == -1.0 and x["regime"] == "Defensive" for x in S["recent"])
print("  ✓ живите (чакащи/отворени/trailing) са по дата на картата; 'последни затворени' са най-много 10, по най-нова резолюция")

print()
print("── изключване ──")
config.TRACK_BUYSTOP = False
assert backtest.get_buystop_summary() == {}
config.TRACK_BUYSTOP = True
print("  ✓ TRACK_BUYSTOP=0 → празно обобщение")

print()
print("Всички тестове минаха.")
