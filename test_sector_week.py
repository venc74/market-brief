"""
18.11.2026 (спешно, т. 4): заглавието на секторната карта „широка ротация извън мега-технологиите“ се смяташе само по RS за 4 / 12 седмици. Сега се сверява с деня и седмицата
(sector_layer.rotation_days): водещите средно срещу SPY за деня и за 5 сесии, секторите над SPY за 5 сесии (мнозинство) и RSP срещу SPY за 5 сесии. Седмицата не я потвърждава →
„по RS за 4 седм. — широка ротация …, но за 5 сесии не се потвърждава (…)“; водещите под SPY (мъртва зона config.SECTOR_ROTATION_DEADZONE_PP) → „днес водещите (N) средно … срещу
SPY … — паднаха повече от SPY“ / „изостанаха от SPY“.

РЕАЛНО: tests/fixtures/sector_week_2026-11.json — затварянията на 11-те ETF-а, SPY и RSP (Yahoo, 02–17.11, свалени 18.11) и редовете на картата от брифовете на 13.11 и 18.11.
СИНТЕТИЧНО (означено): т. 3 — редовете без 5 сесии (старият вход).
Пускане: python test_sector_week.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import sector_layer as sl

FX = json.loads((ROOT / "tests" / "fixtures" / "sector_week_2026-11.json").read_text(encoding="utf-8"))
S = {k: pd.Series(list(v.values()), index=pd.to_datetime(list(v.keys()))) for k, v in FX["closes"].items()}


def day(brief: str):
    b = FX["briefs"][brief]
    cut = {k: v[v.index <= pd.Timestamp(b["as_of"])] for k, v in S.items()}
    rows = [dict(r, chg_5d_pct=sl._chg_n(cut[r["etf"]], 5)) for r in b["sectors"]]
    return b, rows, sl._chg_n(cut["SPY"], 5), sl._chg_n(cut["RSP"], 5)


print("── 1. РЕАЛНО: 18.11 (към 17.11) — водещите паднаха повече от SPY за деня ──")
b, rows, spy5, rsp5 = day("2026-11-18")
rd = sl.rotation_days(rows, b["spy_1d_pct"], spy5, rsp5)
assert rd["n"] == 7 and rd["lead_1d"] == -1.39 and rd["spy_1d"] == -1.01 and rd["lag_day"] and not rd["lag_week"] and rd["week_ok"], rd
assert (rd["lead_5d"], spy5, rsp5, rd["beat_5d"]) == (-1.93, -2.33, -2.32, 7), (rd, spy5, rsp5)
s = sl.board_summary(rows, b["spy_1d_pct"], spy5, rsp5)
assert s.endswith("— " + config.SECTOR_BROAD_TEXT + "; днес водещите (7) средно -1.4% срещу SPY -1.0% — паднаха повече от SPY."), s
assert b["summary"] != s and "паднаха повече" not in b["summary"]
print(f"  ✓ «…{s.split(' — ', 1)[1][-80:]}»")

print("── 2. РЕАЛНО: 13.11 (към 12.11) — седмицата не потвърждава ротацията ──")
b, rows, spy5, rsp5 = day("2026-11-13")
s = sl.board_summary(rows, b["spy_1d_pct"], spy5, rsp5)
assert "по RS за 4 седм. — широка ротация извън мега-технологиите, но за 5 сесии не се потвърждава (над SPY са 3 от 11 сектора, водещите средно +0.9% срещу SPY +3.3%, RSP +1.8%)" in s, s
assert "средната акция бие индекса" not in s and "днес водещите" not in s           # денят: −0.57 срещу −0.35 — в мъртвата зона
print("  ✓ «… не се потвърждава (над SPY са 3 от 11 …)»")

print("── 3. СИНТЕТИЧНО: старият вход без 5 сесии — както досега ──")
b, rows, _, _ = day("2026-11-18")
old_rows = [{k: v for k, v in r.items() if k != "chg_5d_pct"} for r in rows]
assert sl.board_summary(old_rows, b["spy_1d_pct"]) == b["summary"]
print("  ✓ без spy_5d — заглавието е същото като в брифа")
print("\n✅ test_sector_week: всичко мина")
