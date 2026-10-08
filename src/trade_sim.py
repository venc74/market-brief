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
Гап през стопа (т.5): на бар СЛЕД входния, който отваря на или под стопа, изходът е по
отварянето (min(Open, стоп) — загубата може да е над 1R); ако стопът е ударен вътре в бара,
изходът е на стоп-цената. На входния ден — винаги на стоп-цената (редът на ценовите
събития в бара е неизвестен).
Изтичане (т.5): BACKTEST_MAX_HOLD_WEEKS след ВХОДА; позицията се оценява по последния Close
(mark-to-market, претеглен с частичната продажба) — "expired" / "expired_in_trail" вече
носят R и влизат в статистиката (преди "expired" беше без R и невидим за win rate).
"""
from __future__ import annotations
import datetime as dt

import numpy as np
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
            "return_pct": None, "last_close": None, "last_close_date": None}


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
    out.update(fill_date=idx[fi].date().isoformat(), fill_price=round(float(fill), 4),
               risk_per_share=round(float(risk), 4))

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
        if j > fi and o[j] <= stop:                          # т.5: гап през стопа → по отварянето
            status, exit_px, exit_j = "stopped", o[j], j
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

    def weighted_ret(px) -> float:
        """% доходност върху входа, претеглена с частичната продажба (виж spy_return_pct)."""
        sell = out["partial_price"] if out["partial_price"] is not None else px
        return float((sold * (sell - fill) + (1 - sold) * (px - fill)) / fill * 100)

    last = n - 1
    while last > fi and idx[last] > exp_date:
        last -= 1
    out.update(last_close=round(float(c[last]), 4), last_close_date=idx[last].date().isoformat())
    out["current_r"] = round(weighted_r(c[last]), 2)
    out["return_pct"] = round(weighted_ret(c[last]), 2)           # mark-to-market; терминалните го презаписват

    if status is None:
        expired = idx[-1] > exp_date or (today is not None and _as_date(today) > exp_date.date())
        if not expired:
            out["status"] = state                              # "open" | "trailing" — още жива
            return out
        status = "expired_in_trail" if state == "trailing" else "expired"
        out.update(status=status, resolution_date=exp_date.date().isoformat(),
                   exit_date=idx[last].date().isoformat(), exit_price=round(float(c[last]), 4),
                   R=weighted_r(c[last]))                      # т.5: mark-to-market и във фаза 1
        out["realized_r"] = round(out["R"], 2)
        out["return_pct"] = round(weighted_ret(c[last]), 2)
        return out

    out.update(status=status, exit_date=idx[exit_j].date().isoformat(), exit_price=round(float(exit_px), 4),
               resolution_date=idx[exit_j].date().isoformat(), R=weighted_r(exit_px))
    out["realized_r"] = round(out["R"], 2)
    out["return_pct"] = round(weighted_ret(exit_px), 2)
    return out


def spy_return_pct(res: dict, spy: pd.DataFrame) -> float | None:
    """
    Пакет 1, т.8: какво щеше да направи SPY със СЪЩИЯ капитал за СЪЩИТЕ периоди на държане —
    купува се на Open на деня на входа; частичната продажба (target1_hit_date) и остатъкът се
    продават на Close на съответните си дати (за живи позиции — на последния Close). Така
    сравнението е честно и с частичната продажба: фракция × (SPY до целта) + остатък × (SPY до
    изхода). None без вход, без дати или ако SPY няма бар за някоя от датите.
    """
    if res.get("fill_price") is None or res.get("fill_date") is None:
        return None
    end = res.get("exit_date") or res.get("last_close_date")
    if end is None or spy is None or len(spy) == 0:
        return None
    try:
        idx = pd.DatetimeIndex(spy.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        s = spy.copy()
        s.index = idx
        open_in = float(s.loc[pd.Timestamp(res["fill_date"]), "Open"])
        rest = float(s.loc[pd.Timestamp(end), "Close"]) / open_in - 1
        if res.get("partial_price") is not None and res.get("target1_hit_date"):
            frac = float(res.get("partial_fraction") or 0.0)
            sold = float(s.loc[pd.Timestamp(res["target1_hit_date"]), "Close"]) / open_in - 1
            return round((frac * sold + (1 - frac) * rest) * 100, 2)
        return round(rest * 100, 2)
    except (KeyError, ValueError, TypeError):
        return None


# ══════════════════════════════════════════════════════════════════════════
# Qullamaggie breakout (06.10.2026): вход на нивото на пробива, стоп = Low на входния ден, изход по неговите правила
# ══════════════════════════════════════════════════════════════════════════
QM_NOT_A_POSITION = ("not_triggered", "skipped_extended", "skipped_adr", "invalid_risk")     # извън статистиката
QM_TERMINAL = ("stopped", "trailing_stop_exit", "expired")


def _blank_qm(status: str = "pending") -> dict:
    return {"status": status, "fill_date": None, "fill_price": None, "stop_loss": None, "risk_per_share": None,
            "target1_hit_date": None, "partial_price": None, "partial_fraction": 0.0, "trail_ma": None,
            "exit_date": None, "exit_price": None, "resolution_date": None,
            "R": None, "R_pess": None, "realized_r": None, "realized_r_pess": None, "current_r": None,
            "return_pct": None, "return_pct_pess": None, "last_close": None, "last_close_date": None, "how": None}


def simulate_qm(rec: dict, bars: pd.DataFrame, today=None) -> dict:
    """
    Чиста симулация (без I/O) на Qullamaggie breakout по ДНЕВНИ барове — ПОЛЗВА СЕ И В РЕПЛЕЯ, И В Track Record-а (книгата "qm_breakout").
    Вход: rec = {entry_date (денят на брифа = първата сесия), buy_stop (нивото на пробива), adr (ADR20 в %)}; bars = дневни Open/High/Low/Close, без NaN.

    Вход: ЕДНА сесия (config.QM_ENTRY_WINDOW_SESSIONS) — High >= нивото → вход по max(Open, ниво); гап над нивото с повече от QM_CHASE_ADR×ADR → "skipped_extended".
    Стоп = Low на входния ден (в реалността е low of the day КЪМ момента на входа — по-висок; тук е по-ниският, дневният). Стоп по-широк от QM_ADR_STOP×ADR → "skipped_adr".
    Изход (негов): QM_PARTIAL_FRACTION от позицията на затварянето на QM_PARTIAL_DAYS-тата сесия след входния ден, стопът към break-even за остатъка, остатъкът — първо
    ЗАТВАРЯНЕ под SMA10 (ADR >= QM_TRAIL_ADR_SWITCH) или SMA20; гап през стопа → по отварянето; максимум QM_MAX_HOLD_SESSIONS (mark-to-market, "expired").
    Две граници за стопа на входния ден: R/return_pct ("opt": low-ът е бил ПРЕДИ входа, стопът на входния ден не се удря) и R_pess/return_pct_pess ("pess": ако денят затваря
    под входа → −1R). Без плъзгане и комисионни. Връща речник като _blank_qm: статус pending|not_triggered|skipped_extended|skipped_adr|invalid_risk|open|trailing|stopped|
    trailing_stop_exit|expired; за живи — current_r (mark-to-market), за затворени — realized_r / realized_r_pess.
    """
    out = _blank_qm()
    if bars is None or len(bars) == 0:
        return out
    idx = pd.DatetimeIndex(bars.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    o, h, l, c = (bars[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close"))
    n = len(idx)
    trig, adr = float(rec["buy_stop"]), float(rec["adr"])
    first = int(idx.searchsorted(pd.Timestamp(rec["entry_date"]), side="left"))
    if first >= n:
        return out
    window = config.QM_ENTRY_WINDOW_SESSIONS
    fi = fill = None
    for j in range(first, min(first + window, n)):
        if o[j] >= trig:
            f = o[j]
        elif h[j] >= trig:
            f = trig
        else:
            continue
        if f > trig * (1 + config.QM_CHASE_ADR * adr / 100):
            out.update(status="skipped_extended", resolution_date=idx[j].date().isoformat())
            return out
        fi, fill = j, f
        break
    if fi is None:
        if first + window > n:
            return out
        out.update(status="not_triggered", resolution_date=idx[first + window - 1].date().isoformat())
        return out
    stop0 = float(l[fi])
    risk = fill - stop0
    if risk <= 0:
        out.update(status="invalid_risk", resolution_date=idx[fi].date().isoformat())
        return out
    if risk / fill * 100 > config.QM_ADR_STOP * adr:
        out.update(status="skipped_adr", resolution_date=idx[fi].date().isoformat())
        return out
    trail_n = 10 if adr >= config.QM_TRAIL_ADR_SWITCH else 20
    sma = pd.Series(c).rolling(trail_n).mean().to_numpy()
    out.update(fill_date=idx[fi].date().isoformat(), fill_price=round(float(fill), 4), stop_loss=round(stop0, 4), risk_per_share=round(float(risk), 4),
               trail_ma=trail_n)
    pess_day1 = bool(c[fi] < fill)                                         # граница "pess": денят затваря под входа

    frac, pdays = config.QM_PARTIAL_FRACTION, config.QM_PARTIAL_DAYS
    stop, part, r_part, p_px, p_j = stop0, False, 0.0, None, None
    how = ex = exj = None
    last = min(n - 1, fi + config.QM_MAX_HOLD_SESSIONS)
    for j in range(fi + 1, last + 1):
        if o[j] <= stop:                                                   # гап през стопа → по отварянето
            how, ex, exj = ("stop_gap", float(o[j]), j)
            break
        if l[j] <= stop:
            how, ex, exj = ("stop", float(stop), j)
            break
        if not part and j == fi + pdays:                                   # частична продажба на затварянето; стопът към break-even
            part, p_px, p_j = True, float(c[j]), j
            r_part = (p_px - fill) / risk
            stop = max(stop, fill)
            continue
        if part and sma[j] == sma[j] and c[j] < sma[j]:                    # първо ЗАТВАРЯНЕ под MA
            how, ex, exj = ("trail", float(c[j]), j)
            break
    if part:
        out.update(target1_hit_date=idx[p_j].date().isoformat(), partial_price=round(p_px, 4), partial_fraction=frac)

    def weighted(px):
        r = (frac * r_part + (1 - frac) * (px - fill) / risk) if part else (px - fill) / risk
        ret = ((frac * (p_px - fill) + (1 - frac) * (px - fill)) / fill * 100) if part else ((px - fill) / fill * 100)
        return float(r), float(ret)

    r_pess_day1, ret_pess_day1 = -1.0, float((stop0 / fill - 1) * 100)
    out.update(last_close=round(float(c[last]), 4), last_close_date=idx[last].date().isoformat())
    if exj is None:
        cur_r, cur_ret = weighted(float(c[last]))
        out["current_r"], out["return_pct"] = round(cur_r, 2), round(cur_ret, 2)
        if pess_day1:
            out["R_pess"], out["return_pct_pess"] = r_pess_day1, round(ret_pess_day1, 2)
        else:
            out["R_pess"], out["return_pct_pess"] = round(cur_r, 2), round(cur_ret, 2)
        if not (last - fi >= config.QM_MAX_HOLD_SESSIONS):
            out["status"] = "trailing" if part else "open"
            return out
        # максимумът на държане е достигнат → mark-to-market на последния Close
        how, ex, exj = "mtm", float(c[last]), last
        status = "expired"
    else:
        status = "trailing_stop_exit" if how == "trail" else "stopped"
    r_opt, ret_opt = weighted(ex)
    out.update(status=status, how=how, exit_date=idx[exj].date().isoformat(), exit_price=round(ex, 4), resolution_date=idx[exj].date().isoformat(),
               R=r_opt, realized_r=round(r_opt, 2), return_pct=round(ret_opt, 2), current_r=round(r_opt, 2))
    out["R_pess"] = r_pess_day1 if pess_day1 else r_opt
    out["return_pct_pess"] = round(ret_pess_day1, 2) if pess_day1 else round(ret_opt, 2)
    out["realized_r_pess"] = round(out["R_pess"], 2)
    return out


# ══════════════════════════════════════════════════════════════════════════
# GLB по Уиш (09.10.2026): вход при затваряне над зелената линия, изход при ПЪРВОТО затваряне под нея — без стоп, доходност в %
# ══════════════════════════════════════════════════════════════════════════
GW_TERMINAL = ("line_exit", "expired")
GW_NOT_A_POSITION = ("invalid_signal",)             # извън статистиката


def _blank_gw(status: str = "pending") -> dict:
    return {"status": status, "fill_date": None, "fill_price": None, "fill_exec_date": None, "fill_exec_price": None,
            "line_used": None, "split_scale": None, "exit_date": None, "exit_price": None, "exit_exec_date": None, "exit_exec_price": None,
            "resolution_date": None, "return_pct": None, "return_pct_exec": None, "current_return_pct": None,
            "last_close": None, "last_close_date": None, "dist_to_line_pct": None, "hold_sessions": None, "how": None}


def simulate_glb_wish(rec: dict, bars: pd.DataFrame, today=None) -> dict:
    """
    Чиста симулация (без I/O) на книгата "GLB по Уиш" по ДНЕВНИ барове — ПОЛЗВА СЕ И В РЕПЛЕЯ, И В Track Record-а (както simulate_qm).
    Вход: rec = {signal_date (последният цял бар с пробива), line (замразената линия при сигнала), signal_close (затварянето на сигналния ден — за откриване на сплит)};
    bars = дневни Open/Close (индекс = дата на сесията, без NaN; другите колони се пренебрегват).

    Две граници (без плъзгане и комисионни):
      • literal — вход на затварянето на сигналния бар, изход на затварянето на ПЪРВИЯ бар след него с Close < линията (return_pct): така е описано правилото;
      • exec    — първото изпълнимо: вход на отварянето на следващата сесия, изход на отварянето на сесията след затварянето под линията (return_pct_exec); None, докато този бар още не съществува.
    Горна граница на държане (config.GLB_WISH_MAX_HOLD_SESSIONS, 0 = няма): след толкова сесии от сигналния бар — оценка по затварянето му (status "expired", how "mtm").
    Сплит след сигнала: данните от Yahoo са ретроактивно split-коригирани, а линията е замразена в старата скала → съотношението съхранен/сегашен close на сигналния ден (над GLB_WISH_SPLIT_TOLERANCE)
    мащабира линията (split_scale); никакви мрежови заявки.
    Статуси: pending (сигналният бар още не е в данните) | open | line_exit | expired | invalid_signal (няма бар за деня или close не е над линията).
    """
    out = _blank_gw()
    if bars is None or len(bars) == 0:
        return out
    idx = pd.DatetimeIndex(bars.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    o = bars["Open"].to_numpy(dtype=float)
    c = bars["Close"].to_numpy(dtype=float)
    n = len(idx)
    sd = pd.Timestamp(rec["signal_date"])
    s = int(idx.searchsorted(sd, side="left"))
    if s >= n:
        return out                                           # сигналният бар още не е в данните
    if idx[s] != sd:                                         # за деня няма бар, а по-късни има → няма да се появи
        out.update(status="invalid_signal", how="no_bar", resolution_date=idx[s].date().isoformat())
        return out
    scale = 1.0
    sc = rec.get("signal_close")
    if sc and c[s] > 0 and abs(float(sc) / c[s] - 1) > config.GLB_WISH_SPLIT_TOLERANCE:
        scale = float(sc) / c[s]
    line = float(rec["line"]) / scale
    if not c[s] > line:
        out.update(status="invalid_signal", how="not_above_line", resolution_date=idx[s].date().isoformat())
        return out
    fill = float(c[s])
    cap = int(config.GLB_WISH_MAX_HOLD_SESSIONS or 0)
    last_bar = n - 1
    lim = min(last_bar, s + cap) if cap else last_bar
    exit_j = how = None
    for j in range(s + 1, lim + 1):
        if c[j] < line:
            exit_j, how = j, "line"
            break
    if exit_j is None and cap and s + cap <= last_bar:
        exit_j, how = s + cap, "mtm"
    jj = exit_j if exit_j is not None else last_bar
    out.update(fill_date=idx[s].date().isoformat(), fill_price=round(fill, 4), line_used=round(line, 4), split_scale=None if scale == 1.0 else round(scale, 4),
               last_close=round(float(c[jj]), 4), last_close_date=idx[jj].date().isoformat(), dist_to_line_pct=round((float(c[jj]) / line - 1) * 100, 2),
               hold_sessions=int(jj - s), return_pct=round((float(c[jj]) / fill - 1) * 100, 2))
    e0 = float(o[s + 1]) if s + 1 < n else None
    if e0 is not None:
        out.update(fill_exec_date=idx[s + 1].date().isoformat(), fill_exec_price=round(e0, 4))
    if exit_j is None:
        out.update(status="open", current_return_pct=out["return_pct"], how=None)
        out["return_pct_exec"] = round((float(c[jj]) / e0 - 1) * 100, 2) if e0 else None      # оценка по последното затваряне, докато е отворена
        return out
    out.update(status="line_exit" if how == "line" else "expired", how=how, exit_date=idx[exit_j].date().isoformat(), exit_price=round(float(c[exit_j]), 4),
               resolution_date=idx[exit_j].date().isoformat(), current_return_pct=out["return_pct"])
    if exit_j + 1 < n:
        x0 = float(o[exit_j + 1])
        out.update(exit_exec_date=idx[exit_j + 1].date().isoformat(), exit_exec_price=round(x0, 4))
        out["return_pct_exec"] = round((x0 / e0 - 1) * 100, 2) if e0 else None
    return out


def spy_return_pct_gw(res: dict, spy: pd.DataFrame, exec_leg: bool = False) -> float | None:
    """
    SPY за СЪЩИТЕ дати на записа от книгата "GLB по Уиш": literal — от Close на деня на входа до Close на деня на изхода (за отворена — на последния Close); exec_leg — от Open на деня на входа до Open на деня на
    изхода (за отворена — до последния Close). None без вход/дати или ако SPY няма бар за някоя от тях.
    """
    if res.get("fill_date") is None or spy is None or len(spy) == 0:
        return None
    try:
        s = spy.copy()
        idx = pd.DatetimeIndex(s.index)
        s.index = idx.tz_localize(None) if idx.tz is not None else idx
        if not exec_leg:
            end = res.get("exit_date") or res.get("last_close_date")
            return round((float(s.loc[pd.Timestamp(end), "Close"]) / float(s.loc[pd.Timestamp(res["fill_date"]), "Close"]) - 1) * 100, 2)
        if res.get("fill_exec_date") is None:
            return None
        e0 = float(s.loc[pd.Timestamp(res["fill_exec_date"]), "Open"])
        if res.get("exit_exec_date"):
            return round((float(s.loc[pd.Timestamp(res["exit_exec_date"]), "Open"]) / e0 - 1) * 100, 2)
        if res.get("exit_date"):
            return None                                       # затворена, но следващото отваряне още не съществува
        return round((float(s.loc[pd.Timestamp(res["last_close_date"]), "Close"]) / e0 - 1) * 100, 2)
    except (KeyError, ValueError, TypeError):
        return None
