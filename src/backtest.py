"""
Track Record — проследява какво реално се случва с исторически Action
препоръки след като са дадени. Данните вече се трупат ежедневно в
data/YYYY-MM-DD.json (виж main.py docstring-а) именно за тази цел.

Entry price = средата (midpoint) на plan.entry_range в деня на препоръката.

Двуфазова резолюция (реалната система НЕ затваря позицията на target_1 —
превключва на trailing stop под 10DMA, за да улови допълнителен upside):

  Фаза 1 ("open"): от деня СЛЕД entry-то, следим дневен High/Low спрямо
  target_1/stop_loss.
    - Low <= stop_loss           → терминално "stopped", realized_r = -1.0
    - High >= target_1           → преминаваме във Фаза 2 ("trailing")
    - И двете в един ден (gap)   → "stopped" печели (консервативно допускане)
    - Нищо от горното до config.BACKTEST_MAX_HOLD_WEEKS след entry-то
      → терминално "expired", realized_r = None (неопределен изход, target_1
      никога не е бил стигнат — не участва в win/loss статистиката)

  Фаза 2 ("trailing"): от деня СЛЕД докосването на target_1, следим дневен
  Close спрямо rolling 10-дневна средна (10DMA) на Close.
    - Close < 10DMA за първи път  → терминално "trailing_stop_exit",
      realized_r = (exit_price - entry_price) / (entry_price - stop_loss),
      закръглено до 2 знака (не хардкоднато +2.0 — реалният upside/downside
      след target_1 варира).
    - Ако Фаза 2 продължи отвъд config.BACKTEST_MAX_HOLD_WEEKS (броено от
      ОРИГИНАЛНОТО entry, не от target_1 датата) без Close < 10DMA
      → терминално "expired_in_trail", realized_r по същата формула спрямо
      последната налична Close цена (НЕ null — за разлика от Фаза-1
      "expired", тук вече знаем сделката е била печеливша поне до target_1).

Уникален идентификатор на позиция: (ticker, entry_date) — един тикър,
препоръчан на различни дати, е ОТДЕЛНА позиция, ОСВЕН ако вече има ЖИВА
(open/trailing) позиция за същия тикър — без значение откога. Нова позиция
за същия тикър се разрешава едва СЛЕД реална резолюция на предходната
(stopped/trailing_stop_exit/expired/expired_in_trail), не по изтичане на
времеви прозорец — иначе screener-ът препоръчва пак същия незатворен
интерес и той се брои като отделна сделка, изкуствено удвоявайки/
утроявайки статистиката (виж _has_live_position).

Персистира се в data/backtest_tracker.json, keyed по "{ticker}_{entry_date}".

Graceful degradation (Секция 7): провал на price fetch за конкретен тикър
→ остава в текущия си статус, опитва пак следващия ден; липсващ/повреден
tracker JSON → започва от празен dict; провал на update_backtest_tracker()
като цяло → старият tracker на диска остава недокоснат (последно успешно
състояние), get_backtest_summary() продължава да го чете нормално.
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

_TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
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
            print(f"[backtest] tracker JSON повреден, започвам от празен: {e}")
    return {}


def _save_tracker(tracker: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    _TRACKER_PATH.write_text(json.dumps(tracker, ensure_ascii=False, indent=1),
                             encoding="utf-8")


def _snapshot_files() -> list[pathlib.Path]:
    """Само YYYY-MM-DD.json — изключва кеш файлове (cot_cache.json и т.н.)."""
    return sorted(p for p in config.DATA_DIR.glob("*.json") if _SNAPSHOT_RE.match(p.name))


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 1: нови позиции от Action snapshot-ите (с дедупликация)
# ──────────────────────────────────────────────────────────────────────────
def _has_live_position(tracker: dict, ticker: str) -> bool:
    """
    True ако вече има ЖИВА (open/trailing) позиция за този тикър — без значение
    откога. Нова позиция за същия тикър се разрешава едва СЛЕД реална резолюция
    (stopped/trailing_stop_exit/expired/expired_in_trail) на предходната —
    иначе screener-ът препоръчва пак същия незатворен интерес и той се брои
    като отделна сделка, изкуствено удвоявайки статистиката.
    """
    return any(rec.get("ticker") == ticker and rec.get("status") in _LIVE_STATUSES
              for rec in tracker.values())


def _ingest_new_positions(tracker: dict) -> None:
    for path in _snapshot_files():
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[backtest] snapshot {path.name} нечетим, пропускам: {e}")
            continue

        entry_date = snap.get("date") or path.stem
        for c in snap.get("action", []) or []:
            ticker = c.get("ticker")
            plan = c.get("plan") or {}
            entry_range = plan.get("entry_range")
            target_1 = plan.get("target_1")
            stop_loss = plan.get("stop_loss")
            if not (ticker and entry_range and len(entry_range) == 2
                   and target_1 is not None and stop_loss is not None):
                continue

            key = f"{ticker}_{entry_date}"
            if key in tracker:
                continue
            if _has_live_position(tracker, ticker):
                continue  # продължение на съществуваща позиция, не нова сделка

            tracker[key] = {
                "ticker": ticker,
                "entry_date": entry_date,
                "status": "open",
                "entry_price": round((entry_range[0] + entry_range[1]) / 2, 2),
                "target_1": target_1,
                "stop_loss": stop_loss,
                "target1_hit_date": None,
                "resolution_date": None,
                "realized_r": None,
            }


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 2: резолюция на живите позиции (batch price fetch, двуфазово)
# ──────────────────────────────────────────────────────────────────────────
def _resolve_position(rec: dict, h: "pd.Series", l: "pd.Series", c: "pd.Series",
                      today: dt.date) -> None:
    """Мутира rec на място. Фаза 1 → евентуален преход във Фаза 2 в СЪЩИЯ проход."""
    if rec["status"] == "open":
        entry_dt = pd.Timestamp(rec["entry_date"])
        h1, l1 = h[h.index > entry_dt], l[l.index > entry_dt]

        hit_target1 = False
        for day in h1.index:
            if day not in l1.index:
                continue
            if bool(l1.loc[day] <= rec["stop_loss"]):   # gap ден — stop печели консервативно
                rec["status"] = "stopped"
                rec["resolution_date"] = day.date().isoformat()
                rec["realized_r"] = -1.0
                return
            if bool(h1.loc[day] >= rec["target_1"]):
                rec["status"] = "trailing"
                rec["target1_hit_date"] = day.date().isoformat()
                hit_target1 = True
                break

        if not hit_target1:
            entry_cutoff = entry_dt.date() + dt.timedelta(weeks=config.BACKTEST_MAX_HOLD_WEEKS)
            if today >= entry_cutoff:
                rec["status"] = "expired"
                rec["resolution_date"] = entry_cutoff.isoformat()
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
            if avg != avg:            # NaN guard без нужда от отделен math/numpy импорт
                continue
            close_val = float(c.loc[day])
            if close_val < avg:
                rec["status"] = "trailing_stop_exit"
                rec["resolution_date"] = day.date().isoformat()
                rec["realized_r"] = round((close_val - entry_price) / (entry_price - original_stop), 2)
                return

        entry_dt = pd.Timestamp(rec["entry_date"])
        entry_cutoff = entry_dt.date() + dt.timedelta(weeks=config.BACKTEST_MAX_HOLD_WEEKS)
        if today >= entry_cutoff and len(c):
            last_close = float(c.iloc[-1])
            rec["status"] = "expired_in_trail"
            rec["resolution_date"] = entry_cutoff.isoformat()
            rec["realized_r"] = round((last_close - entry_price) / (entry_price - original_stop), 2)


def _normalize_price_columns(data: "pd.DataFrame", tickers: list[str],
                             fields: tuple[str, ...]) -> dict[str, "pd.DataFrame | None"]:
    """
    yf.download за списък с ЕДИН тикър понякога връща плосък DataFrame
    (директни Open/High/Low/Close колони, без ticker ниво) вместо MultiIndex.
    Опаковаме в единична ticker-именувана колона, за да работи еднакво
    result[field][ticker] надолу по кода, независимо от формата.
    """
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
    try:
        data = yf.download(tickers, start=earliest, progress=False, auto_adjust=False)
    except Exception as e:
        print(f"[backtest] batch price fetch failed за {tickers}: {e}")
        return
    if data is None or data.empty:
        print("[backtest] price fetch върна празен резултат")
        return

    cols = _normalize_price_columns(data, tickers, ("High", "Low", "Close"))
    highs, lows, closes = cols.get("High"), cols.get("Low"), cols.get("Close")
    if highs is None or lows is None or closes is None:
        print("[backtest] price fetch не върна High/Low/Close колони")
        return

    today = dt.date.today()
    for _, rec in live_items:
        ticker = rec["ticker"]
        if ticker not in getattr(highs, "columns", []):
            print(f"[backtest] {ticker}: няма данни в batch резултата — пропускам (остава {rec['status']})")
            continue
        try:
            _resolve_position(rec, highs[ticker].dropna(), lows[ticker].dropna(),
                              closes[ticker].dropna(), today)
        except Exception as e:
            print(f"[backtest] {ticker}: резолюция неуспешна, остава {rec['status']}: {e}")
            continue


def _fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """
    Batch fetch на последната налична Close цена за списък тикъри (за
    unrealized % на отворените позиции). Graceful: провал на целия fetch
    или на конкретен тикър → просто липсва в резултата, не гърми.
    """
    if not tickers:
        return {}
    try:
        data = yf.download(tickers, period="5d", progress=False, auto_adjust=False)
    except Exception as e:
        print(f"[backtest] current price fetch failed за {tickers}: {e}")
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
def update_backtest_tracker() -> None:
    """
    Ingest на нови Action позиции (с дедупликация) + резолюция на живите.
    Провал някъде в средата → tracker-ът на диска остава последното успешно
    записано състояние (не презаписваме частично/счупено).
    """
    tracker = _load_tracker()
    try:
        _ingest_new_positions(tracker)
        _resolve_open_positions(tracker)
        _save_tracker(tracker)
    except Exception as e:
        print(f"[backtest] update_backtest_tracker failed: {e}")


def get_backtest_summary() -> dict:
    """
    Обобщение за dashboard-а. "Win" = всякакъв терминален изход с
    realized_r > 0 (не само чист target_hit — trailing_stop_exit и
    expired_in_trail може да имат частичен положителен R). Празен/повреден
    tracker → нулеви стойности, никога грешка.

    Забележка: прави batch мрежова заявка (текущи цени за отворените
    позиции, за "open_positions"/unrealized %) — не е чисто локално четене
    от диска както преди. Провал на тази заявка е graceful (виж
    _fetch_current_prices) — не чупи останалата част на summary-то.
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

    # "recent" = само тази ISO седмица (пон-нед) — иначе стара резолюция може
    # да "залепне" в топ-10 с дни наред, ако няма нови след нея. Кумулативната
    # статистика по-горе (total_resolved/win_rate/avg_r/by_status) НЕ се
    # ресетва седмично — трупа се от началото на tracking-а.
    today = dt.date.today()
    monday_this_week = (today - dt.timedelta(days=today.weekday())).isoformat()
    recent_pool = [r for r in records
                  if r.get("status") not in _LIVE_STATUSES and r.get("resolution_date")
                  and r["resolution_date"] >= monday_this_week]
    recent_pool.sort(key=lambda r: r["resolution_date"], reverse=True)
    recent = [{"ticker": r["ticker"], "entry_date": r["entry_date"], "resolution": r["status"],
              "resolution_date": r["resolution_date"], "realized_r": r.get("realized_r")}
             for r in recent_pool[:20]]  # горен таван само като edge-case защита, не нормално поведение

    # Живи позиции + текуща цена (batch fetch) за unrealized % изгледа в dashboard-а.
    live_records = [r for r in records if r.get("status") in _LIVE_STATUSES]
    open_positions = []
    if live_records:
        tickers = sorted({r["ticker"] for r in live_records})
        prices = _fetch_current_prices(tickers)
        for r in live_records:
            entry_price = r.get("entry_price")
            cur = prices.get(r["ticker"])
            unrealized_pct = (round((cur - entry_price) / entry_price * 100, 1)
                              if cur is not None and entry_price else None)
            open_positions.append({
                "ticker": r["ticker"],
                "entry_date": r["entry_date"],
                "entry_price": entry_price,
                "current_price": round(cur, 2) if cur is not None else None,
                "unrealized_pct": unrealized_pct,
            })
        open_positions.sort(key=lambda r: r["entry_date"])  # възходящо — най-старите първи

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
    update_backtest_tracker()
    summary = get_backtest_summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
