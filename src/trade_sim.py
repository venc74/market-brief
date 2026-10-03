"""
Чиста симулация на изпълнението за Track Record v2 — без I/O, без мрежа
(пакет 1, т.2 · 2026-10-03). Една и съща функция се ползва от backtest.py (живо) и
от историческия реплей, затова числата в реплея и в брифа не могат да се разминат.

Вход:  plan  — запис/план с entry_date, buy_stop (pivot), max_chase, stop_loss, target_1
       bars  — дневни OHLC (Open, High, Low, Close), индекс = дата на сесията, без NaN
Изход: речник със status, fill_date, fill_price, … (виж _blank) — НИЩО не се записва тук.

Изпълнение (т.2): buy-stop на pivot.
  • Брифът е в 05:30 UTC, преди US отваряне → първата търгувана сесия е първият бар с
    дата >= entry_date (деня на брифа; събота/неделя/празник → следващата сесия).
  • Прозорец: window_sessions сесии, ВКЛЮЧИТЕЛНО първата. Вход на първата сесия, в която
    High >= pivot, на цена max(Open, pivot) (гап над pivot = по отварянето).
  • Ако цената на входа е над max_chase (pivot +5%) → "skipped_extended" (не се гони).
  • Прозорецът изтече без вход → "not_triggered" (извън статистиката); докато още тече
    (няма достатъчно бара) → "pending".
  • Сделка с (вход − стоп) <= 0 → "invalid_risk" (извън статистиката).
Цел (т.4): на target_1 (2R) се продава TARGET_PARTIAL_FRACTION от позицията — на target_1, а
ако баровете след входния ден отварят над него, по отварянето; остатъкът минава във
фаза "trailing" и излиза при Close под TRAIL_SMA_DAYS-дневната средна. Първоначалният
стоп остава активен и в trailing; в един и същ бар стопът се проверява ПЪРВИ (консервативно).
R = дял × (цена на частичната − вход) / риск + (1 − дял) × (изход на остатъка − вход) / риск.
Изтичане (до т.5 — като досега във v1): след BACKTEST_MAX_HOLD_WEEKS от входа.
"""
from __future__ import annotations
import datetime as dt

import pandas as pd

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

LIVE = ("pending", "open", "trailing")                 # още тече (нерезолвирана)
NOT_A_POSITION = ("not_triggered", "skipped_extended", "invalid_risk")   # извън статистиката


def _blank(status: str = "pending") -> dict:
    return {"status": status, "fill_date": None, "fill_price": None, "risk_per_share": None,
            "target1_hit_date": None, "partial_price": None, "partial_fraction": 0.0,
            "exit_date": None, "exit_price": None,
            "resolution_date": None, "realized_r": None, "current_r": None, "R": None,
            "last_close": None, "last_close_date": None}


def _as_date(d) -> dt.date:
    if isinstance(d, dt.datetime):
        return d.date()
    if isinstance(d, dt.date):
        return d
    return dt.date.fromisoformat(str(d)[:10])


def simulate(plan: dict, bars: pd.DataFrame, today=None) -> dict:
    out = _blank()
    if bars is None or len(bars) == 0:
        return out
    idx = pd.DatetimeIndex(bars.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    o = bars["Open"].to_numpy(dtype=float)
    h = bars["High"].to_numpy(dtype=float)
    l = bars["Low"].to_numpy(dtype=float)
    c = bars["Close"].to_numpy(dtype=float)
    n = len(idx)

    trigger = float(plan["buy_stop"])
    chase = plan.get("max_chase")
    stop = float(plan["stop_loss"])
    t1 = float(plan["target_1"])
    window = int(plan.get("window_sessions") or config.BUY_STOP_WINDOW_SESSIONS)
    first = int(idx.searchsorted(pd.Timestamp(plan["entry_date"]), side="left"))
    if first >= n:
        return out                                           # първата сесия още не е започнала

    # ── т.2: buy-stop вход ───────────────────────────────────────────────
    fi = fill = None
    for j in range(first, min(first + window, n)):
        if o[j] >= trigger:
            f = o[j]
        elif h[j] >= trigger:
            f = trigger
        else:
            continue
        if chase is not None and f > float(chase):
            out.update(status="skipped_extended", resolution_date=idx[j].date().isoformat())
            return out
        fi, fill = j, f
        break
    if fi is None:
        if first + window > n:
            return out                                       # прозорецът още тече
        out.update(status="not_triggered", resolution_date=idx[first + window - 1].date().isoformat())
        return out
    risk = fill - stop
    if risk <= 0:
        out.update(status="invalid_risk", resolution_date=idx[fi].date().isoformat())
        return out
    out.update(fill_date=idx[fi].date().isoformat(), fill_price=round(fill, 4),
               risk_per_share=round(risk, 4))

    # ── т.4: частична продажба на цел 1, trailing за остатъка, стопът остава ──
    frac = config.TARGET_PARTIAL_FRACTION
    exp_date = idx[fi] + pd.Timedelta(weeks=config.BACKTEST_MAX_HOLD_WEEKS)
    sma = pd.Series(c).rolling(config.TRAIL_SMA_DAYS).mean().to_numpy()
    state, t_idx = "open", None
    sold = r_sold = 0.0                                      # продаден дял и R на тази част
    status = exit_px = exit_j = None
    for j in range(fi, n):
        if idx[j] > exp_date:
            break
        if l[j] <= stop:                                     # стопът е активен и след частичната; първи в бара
            status, exit_px, exit_j = "stopped", stop, j
            break
        if state == "open" and h[j] >= t1:
            state, t_idx = "trailing", j
            sell = t1 if j == fi else max(o[j], t1)          # гап над целта → по отварянето
            sold, r_sold = frac, (sell - fill) / risk
            out.update(target1_hit_date=idx[j].date().isoformat(), partial_price=round(float(sell), 4),
                       partial_fraction=frac)
            continue
        if state == "trailing" and j > t_idx:
            ma = sma[j]
            if ma == ma and c[j] < ma:
                status, exit_px, exit_j = "trailing_stop_exit", c[j], j
                break

    def weighted_r(px) -> float:
        return float(sold * r_sold + (1 - sold) * (px - fill) / risk)

    last = n - 1
    while last > fi and idx[last] > exp_date:
        last -= 1
    out.update(last_close=round(float(c[last]), 4), last_close_date=idx[last].date().isoformat())
    out["current_r"] = round(weighted_r(c[last]), 2)

    if status is None:
        expired = idx[-1] > exp_date or (today is not None and _as_date(today) > exp_date.date())
        if not expired:
            out["status"] = state                              # "open" | "trailing" — още жива
            return out
        status = "expired_in_trail" if state == "trailing" else "expired"
        out.update(status=status, resolution_date=exp_date.date().isoformat())
        if status == "expired_in_trail":
            out.update(exit_date=idx[last].date().isoformat(), exit_price=round(float(c[last]), 4),
                       R=weighted_r(c[last]))
            out["realized_r"] = round(out["R"], 2)
        return out                                             # "expired" във фаза 1 → без R

    out.update(status=status, exit_date=idx[exit_j].date().isoformat(), exit_price=round(float(exit_px), 4),
               resolution_date=idx[exit_j].date().isoformat(), R=weighted_r(exit_px))
    out["realized_r"] = round(out["R"], 2)
    return out
