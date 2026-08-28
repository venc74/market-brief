"""
Short Tracker — prospective проследяване на Short/Stage 4 кандидатите
(short_screener.py), same дух и структура като backtest.py, но за ОБРАТНА
позиция: печалба идва от падаща цена, не растяща.

СТРУКТУРЕН ЛИМИТ (виж short_screener.py docstring-а): survival-risk
критериите не могат да бъдат ретроактивно тествани отвъд ~2г история —
този tracker е ЕДИНСТВЕНИЯТ начин да измерим реален hit rate занапред,
натрупвайки собствена история от деня на деплой-а, а не от предполагаема
(недоказуема) историческа справедливост.

Entry/stop/target: НЕ пълен sizing.py-стил план (position sizing/$ размер
е explicit извън обхвата на тази версия, виж 2026-08-2x дискусията) —
лек, self-contained risk anchor само за механично проследяване:
  entry_price = цена в момента на screen-а
  stop_loss   = ma50 (над него — Stage 4 тезата е невалидна, "покрий")
  target_1    = entry_price - risk_per_share * config.MIN_REWARD_RISK
(mirror на sizing.py's "под 50DMA" конвенция, обърнат знак).

Двуфазова резолюция (ОБЪРНАТА спрямо backtest.py):
  Фаза 1 ("open"): Low <= target_1 (цената пада достатъчно) → Фаза 2.
                    High >= stop_loss (цената расте срещу нас) → "stopped".
                    Гап ден с двете → "stopped" печели (консервативно, same
                    допускане като backtest.py).
  Фаза 2 ("trailing"): Close > rolling 10DMA (цената отскача обратно НАГОРЕ,
                        обратно на низходящия моментум) → "trailing_stop_exit"
                        (покрий/cover).

Extreme move disclosure (FIX 2026-08-2x, т.3 от 2026-08-2x дискусията):
нямаме надежден, безплатен data source за programmatic Chapter-11-filing
detection (потвърдено — виж config.py коментара). Потвърден, документиран
риск (SPWR: filing 05.08.2024, последван от значителен post-filing price
spike — класически post-bankruptcy спекулативна volatility, не индикация
за грешна теза). Вместо bankruptcy-специфична логика: generic detector —
ако резолюция чрез "stopped" се случи на ден с необичайно голямо движение
(>= config.SHORT_EXTREME_MOVE_PCT) И обем (>= config.SHORT_EXTREME_VOLUME_MULT
× 50-дневна средна), записът получава explicit "unusual_move_disclosure"
бележка — резолюцията НЕ се блокира/променя механично, само се маркира за
човешки преглед. Explicit, документиран compromise, не гаранция.

Graceful degradation (Секция 7): провал на price fetch за конкретен тикър
→ остава в текущия си статус; липсващ/повреден tracker JSON → празен dict.
"""
from __future__ import annotations
import datetime as dt
import json
import re

import pandas as pd
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import net_utils
from src import enrich

_TRACKER_PATH = config.DATA_DIR / "short_tracker.json"
_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
_LIVE_STATUSES = ("open", "trailing")


# ──────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────
def _load_tracker() -> dict:
    if _TRACKER_PATH.exists():
        try:
            return json.loads(_TRACKER_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[short_tracker] tracker JSON повреден, започвам от празен: {e}")
    return {}


def _save_tracker(tracker: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    _TRACKER_PATH.write_text(json.dumps(tracker, ensure_ascii=False, indent=1, default=str),
                             encoding="utf-8")


def _snapshot_files() -> list[pathlib.Path]:
    return sorted(p for p in config.DATA_DIR.glob("*.json") if _SNAPSHOT_RE.match(p.name))


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 1: нови позиции от short_candidates snapshot-ите (с дедупликация)
# ──────────────────────────────────────────────────────────────────────────
def _has_live_position(tracker: dict, ticker: str) -> bool:
    """Same принцип като backtest.py — виж неговия docstring за пълния rationale."""
    return any(rec.get("ticker") == ticker and rec.get("status") in _LIVE_STATUSES
              for rec in tracker.values())


def _risk_plan(row: dict) -> dict | None:
    """
    Лек, self-contained risk anchor — НЕ пълен sizing.py план (виж модул
    docstring-а). stop_loss = ma50 (над него тезата невалидна), target_1 =
    entry - risk*MIN_REWARD_RISK (same 2:1 конвенция като дългата страна,
    обърнат знак).
    """
    entry = row.get("price")
    ma50 = row.get("ma50")
    if not entry or not ma50 or ma50 <= entry:
        return None
    risk_per_share = ma50 - entry
    return {
        "entry_price": round(entry, 2),
        "stop_loss": round(ma50, 2),
        "target_1": round(entry - risk_per_share * config.MIN_REWARD_RISK, 2),
    }


def _ingest_candidate_list(tracker: dict, entry_date: str, candidates: list[dict]) -> None:
    for c in candidates or []:
        ticker = c.get("ticker")
        if not ticker:
            continue
        plan = _risk_plan(c)
        if not plan:
            continue

        key = f"{ticker}_{entry_date}"
        if key in tracker:
            continue
        if _has_live_position(tracker, ticker):
            continue

        tracker[key] = {
            "ticker": ticker,
            "entry_date": entry_date,
            "status": "open",
            "entry_price": plan["entry_price"],
            "target_1": plan["target_1"],
            "stop_loss": plan["stop_loss"],
            "lagging_sector": c.get("lagging_sector"),
            "distress_signal_count": c.get("distress_signal_count"),
            "target1_hit_date": None,
            "resolution_date": None,
            "discovered_date": None,
            "realized_r": None,
        }


def _ingest_new_positions(tracker: dict, today_candidates: list[dict] | None = None,
                          today_date: str | None = None) -> None:
    for path in _snapshot_files():
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[short_tracker] snapshot {path.name} нечетим, пропускам: {e}")
            continue
        entry_date = snap.get("date") or path.stem
        _ingest_candidate_list(tracker, entry_date, snap.get("short_candidates", []))

    # FIX 2026-08-01 (backtest.py) — same "ден+1" lag class: днешният snapshot
    # още не е записан на диска на този етап от main.py run-а. Директно
    # ingest-ване на днешния in-memory списък елиминира закъснението.
    if today_candidates and today_date:
        _ingest_candidate_list(tracker, today_date, today_candidates)


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 2: резолюция на живите позиции (ОБЪРНАТА логика спрямо backtest.py)
# ──────────────────────────────────────────────────────────────────────────
def _unusual_move_note(day_pct_move: float, day_vol_ratio: float) -> str | None:
    """
    FIX 2026-08-2x: първоначален дизайн изискваше move И volume едновременно
    (AND) — тествано срещу реалния SPWR случай (Chapter 11 05.08.2024) и НЕ
    сработи. Root cause: SPWR вече е бил heavily-traded distressed стока
    МЕСЕЦИ преди filing-а (pre-entry 50-дневен baseline ~3.2M акции/ден) —
    самият filing ден показа volume под този вече-повишен baseline (0.23×),
    докато price move-ът (+13%) беше ясно значим. AND логиката пропусна
    точно мотивиращия case. OR е по-подходящо — единичен силен сигнал
    (move ИЛИ volume) е достатъчен за "прегледай ръчно", not изисква и двата.
    """
    if (abs(day_pct_move) >= config.SHORT_EXTREME_MOVE_PCT
            or day_vol_ratio >= config.SHORT_EXTREME_VOLUME_MULT):
        return (f"Резолюцията се случи при необичайно голямо движение "
               f"({day_pct_move:+.1f}%, {day_vol_ratio:.1f}× средния обем) — "
               "възможно corporate event (bankruptcy filing, M&A, и т.н.). "
               "Механичният stop не диференцира между фундаментално-грешна "
               "теза и post-event спекулативна volatility — виж SPWR "
               "05.08.2024 случая. Прегледай ръчно преди да третираш като "
               "чист сигнал за тезата.")
    return None


def _resolve_position(rec: dict, h: "pd.Series", l: "pd.Series", c: "pd.Series",
                      v: "pd.Series", avg_vol_50: float, today: dt.date) -> None:
    """Мутира rec на място. Виж модул docstring-а за пълната Фаза 1/2 логика."""
    if rec["status"] == "open":
        entry_dt = pd.Timestamp(rec["entry_date"])
        h1, l1 = h[h.index > entry_dt], l[l.index > entry_dt]

        hit_target1 = False
        for day in h1.index:
            if day not in l1.index:
                continue
            if bool(h1.loc[day] >= rec["stop_loss"]):   # гап ден — stop печели консервативно
                rec["status"] = "stopped"
                rec["resolution_date"] = day.date().isoformat()
                rec["discovered_date"] = today.isoformat()
                rec["realized_r"] = -1.0
                day_prev_close = c[c.index < day]
                if len(day_prev_close) and day in v.index and avg_vol_50:
                    pct_move = (float(c.loc[day]) / float(day_prev_close.iloc[-1]) - 1) * 100
                    vol_ratio = float(v.loc[day]) / avg_vol_50
                    note = _unusual_move_note(pct_move, vol_ratio)
                    if note:
                        rec["unusual_move_disclosure"] = note
                return
            if bool(l1.loc[day] <= rec["target_1"]):
                rec["status"] = "trailing"
                rec["target1_hit_date"] = day.date().isoformat()
                hit_target1 = True
                break

        if not hit_target1:
            entry_cutoff = entry_dt.date() + dt.timedelta(weeks=config.BACKTEST_MAX_HOLD_WEEKS)
            if today >= entry_cutoff:
                rec["status"] = "expired"
                rec["resolution_date"] = entry_cutoff.isoformat()
                rec["discovered_date"] = today.isoformat()
                rec["realized_r"] = None
            return

    if rec["status"] == "trailing":
        entry_price = rec["entry_price"]
        original_stop = rec["stop_loss"]
        target1_dt = pd.Timestamp(rec["target1_hit_date"])
        dma10 = c.rolling(10).mean()
        after = c[c.index > target1_dt]

        for day in after.index:
            avg = dma10.loc[day] if day in dma10.index else float("nan")
            if avg != avg:
                continue
            close_val = float(c.loc[day])
            if close_val > avg:   # цената отскача обратно НАГОРЕ — покрий
                rec["status"] = "trailing_stop_exit"
                rec["resolution_date"] = day.date().isoformat()
                rec["discovered_date"] = today.isoformat()
                rec["realized_r"] = round((entry_price - close_val) / (original_stop - entry_price), 2)
                return

        entry_dt = pd.Timestamp(rec["entry_date"])
        entry_cutoff = entry_dt.date() + dt.timedelta(weeks=config.BACKTEST_MAX_HOLD_WEEKS)
        if today >= entry_cutoff and len(c):
            last_close = float(c.iloc[-1])
            rec["status"] = "expired_in_trail"
            rec["resolution_date"] = entry_cutoff.isoformat()
            rec["discovered_date"] = today.isoformat()
            rec["realized_r"] = round((entry_price - last_close) / (original_stop - entry_price), 2)


def _normalize_price_columns(data: "pd.DataFrame", tickers: list[str],
                             fields: tuple[str, ...]) -> dict[str, "pd.DataFrame | None"]:
    """Same helper като backtest.py — виж неговия docstring."""
    if isinstance(data.columns, pd.MultiIndex):
        return {f: data.get(f) for f in fields}
    only_ticker = tickers[0]
    return {f: (data[[f]].rename(columns={f: only_ticker}) if f in data.columns else None)
           for f in fields}


def _resolve_open_positions(tracker: dict) -> None:
    live_items = [(key, rec) for key, rec in tracker.items() if rec.get("status") in _LIVE_STATUSES]
    if not live_items:
        return

    tickers = sorted({rec["ticker"] for _, rec in live_items})
    earliest = min(rec["entry_date"] for _, rec in live_items)
    # FIX 2026-08-2x: avg_vol_50 (unusual-move detection, виж _unusual_move_note)
    # се смяташе от СЪЩАТА тегление, започваща точно на entry датата — baseline-ът
    # се замърсяваше от самото аномално събитие, което се опитваме да детектираме
    # (потвърдено на живо: SPWR 2024-08-19 volume ratio излизаше подценен, защото
    # 50-дневната "средна" реално покриваше само ~15-те дни СЛЕД bankruptcy filing-а,
    # вече повишени). Тегли допълнителен буфер ПРЕДИ earliest за чист pre-position
    # baseline — резолюционната логика по-долу продължава да филтрира стриктно
    # спрямо entry_dt, тази допълнителна история служи само за volume baseline-а.
    fetch_start = (pd.Timestamp(earliest) - pd.Timedelta(days=90)).date().isoformat()
    try:
        data = yf.download(tickers, start=fetch_start, progress=False, auto_adjust=False)
    except Exception as e:
        print(f"[short_tracker] batch price fetch failed за {tickers}: {e}")
        return
    if data is None or data.empty:
        print("[short_tracker] price fetch върна празен резултат")
        return

    cols = _normalize_price_columns(data, tickers, ("High", "Low", "Close", "Volume"))
    highs, lows, closes, volumes = cols.get("High"), cols.get("Low"), cols.get("Close"), cols.get("Volume")
    if highs is None or lows is None or closes is None:
        print("[short_tracker] price fetch не върна High/Low/Close колони")
        return

    today = dt.date.today()
    for _, rec in live_items:
        ticker = rec["ticker"]
        if ticker not in getattr(highs, "columns", []):
            print(f"[short_tracker] {ticker}: няма данни в batch резултата — пропускам (остава {rec['status']})")
            continue
        try:
            h_series = highs[ticker].dropna()
            l_series = lows[ticker].dropna()
            c_series = closes[ticker].dropna()
            v_series = volumes[ticker].dropna() if volumes is not None and ticker in getattr(volumes, "columns", []) else pd.Series(dtype=float)
            # PRE-entry baseline (виж fetch_start коментара по-горе) — НЕ
            # v_series.iloc[-50:] (последните 50 достъпни до "днес" реда,
            # което би включило самото пост-entry аномално движение в
            # "средната", подценявайки unusual-move детекцията).
            entry_dt = pd.Timestamp(rec["entry_date"])
            pre_entry_vol = v_series[v_series.index < entry_dt]
            avg_vol_50 = float(pre_entry_vol.iloc[-50:].mean()) if len(pre_entry_vol) else 0.0
            _resolve_position(rec, h_series, l_series, c_series, v_series, avg_vol_50, today)
        except Exception as e:
            print(f"[short_tracker] {ticker}: резолюция неуспешна, остава {rec['status']}: {e}")
            continue


def _fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """Same helper като backtest.py."""
    if not tickers:
        return {}
    try:
        data = yf.download(tickers, period="5d", progress=False, auto_adjust=False)
    except Exception as e:
        print(f"[short_tracker] current price fetch failed за {tickers}: {e}")
        return {}
    if data is None or data.empty:
        return {}

    closes = _normalize_price_columns(data, tickers, ("Close",)).get("Close")
    if closes is None:
        return {}

    out: dict[str, float] = {}
    for t in tickers:
        if t not in getattr(closes, "columns", []):
            continue
        series = closes[t].dropna()
        if len(series):
            out[t] = float(series.iloc[-1])
    return out


# ──────────────────────────────────────────────────────────────────────────
# Публично API
# ──────────────────────────────────────────────────────────────────────────
def update_short_tracker(today_candidates: list[dict] | None = None,
                         today_date: str | None = None) -> None:
    tracker = _load_tracker()
    try:
        _ingest_new_positions(tracker, today_candidates, today_date)
        _resolve_open_positions(tracker)
        _save_tracker(tracker)
    except Exception as e:
        print(f"[short_tracker] update_short_tracker failed: {e}")


def get_short_tracker_summary() -> dict:
    """
    "Win" тук = realized_r > 0, ЗАЩОТО цената реално падна достатъчно (за
    разлика от backtest.py, посоката е обърната, но R semantics-ите остават
    directional-agnostic — same формула за win/loss/avg_r).
    """
    tracker = _load_tracker()
    records = list(tracker.values())

    resolved = [r for r in records if r.get("realized_r") is not None]
    total_resolved = len(resolved)
    wins = [r for r in resolved if r["realized_r"] > 0]
    losses = [r for r in resolved if r["realized_r"] <= 0]
    win_rate = round(len(wins) / total_resolved * 100, 1) if total_resolved else 0.0
    avg_r = round(sum(r["realized_r"] for r in resolved) / total_resolved, 2) if total_resolved else 0.0

    by_status = {}
    for r in records:
        by_status[r.get("status")] = by_status.get(r.get("status"), 0) + 1

    today = dt.date.today()
    monday_this_week = (today - dt.timedelta(days=today.weekday())).isoformat()

    def _effective_date(r: dict) -> str:
        return r.get("discovered_date") or r["resolution_date"]

    recent_pool = [r for r in records
                  if r.get("status") not in _LIVE_STATUSES and r.get("resolution_date")
                  and _effective_date(r) >= monday_this_week]
    recent_pool.sort(key=_effective_date, reverse=True)
    recent = [{"ticker": r["ticker"], "entry_date": r["entry_date"], "resolution": r["status"],
              "resolution_date": r["resolution_date"], "realized_r": r.get("realized_r"),
              "unusual_move_disclosure": r.get("unusual_move_disclosure"),
              "late_discovery": bool(r.get("discovered_date")
                                     and r["discovered_date"] != r["resolution_date"])}
             for r in recent_pool[:20]]

    live_records = [r for r in records if r.get("status") in _LIVE_STATUSES]
    open_positions = []
    if live_records:
        tickers = sorted({r["ticker"] for r in live_records})
        prices = _fetch_current_prices(tickers)
        for r in live_records:
            entry_price = r.get("entry_price")
            cur = prices.get(r["ticker"])
            # unrealized_pct тук е "печалба от падане" -- обърнат знак спрямо backtest.py
            unrealized_pct = (round((entry_price - cur) / entry_price * 100, 1) + 0.0
                              if (cur is not None and entry_price) else None)
            open_positions.append({
                "ticker": r["ticker"],
                "entry_date": r["entry_date"],
                "entry_price": entry_price,
                "current_price": round(cur, 2) if cur is not None else None,
                "unrealized_pct": unrealized_pct,
                "lagging_sector": r.get("lagging_sector"),
                "earnings_recap": enrich.earnings_recap(r["ticker"]),
            })
        open_positions.sort(key=lambda r: r["entry_date"])

    return {
        "total_resolved": total_resolved,
        "win_rate_pct": win_rate,
        "wins": len(wins),
        "losses": len(losses),
        "stopped": by_status.get("stopped", 0),
        "trailing_stop_exit": by_status.get("trailing_stop_exit", 0),
        "expired_in_trail": by_status.get("expired_in_trail", 0),
        "expired": by_status.get("expired", 0),
        "still_open": by_status.get("open", 0),
        "trailing": by_status.get("trailing", 0),
        "avg_realized_r": avg_r,
        "recent": recent,
        "open_positions": open_positions,
    }


if __name__ == "__main__":
    update_short_tracker()
    summary = get_short_tracker_summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
