"""
COT (Commitments of Traders) — managed money net positioning, методология Jason Shapiro.

Източник: CFTC публичен Socrata API (публично, без ключ):
  https://publicreporting.cftc.gov/resource/{dataset_id}.json

Два отчета покриват пълния универс, защото "hot money" категорията се казва
различно във всеки:
  • TFF Futures Only (gpe5-46if)         — финансови фючърси (индекси, валути,
    лихвени проценти, VIX). Категория: Leveraged Funds.
  • Disaggregated Futures Only (72hh-3qpy) — стоки (петрол, злато, зърно…).
    Категория: Managed Money.

И двете се третират като един и същ концепт по-нататък: managed_money_net =
long − short на спекулативната категория за съответния пазар.

Методология (Shapiro):
  • Net position всяка седмица за всеки пазар.
  • Percentile rank на текущия net спрямо последните ~3 години (156 седмици)
    седмична история: % от историческите наблюдения, които са <= текущото.
  • Екстремум = percentile < 15 (екстремно нетно къси) или > 85 (екстремно
    нетно дълги). На екстремумите Шапиро е contrarian: екстремно дълги
    managed money = потенциален bearish сигнал за инструмента (и bullish за
    свързаните/насрещни активи), и обратно.

Кеширане: пълна 3-годишна седмична серия по пазар се тегли веднъж, после само
инкрементално се добавят нови седмици (CFTC публикува всеки петък за
предходния вторник). Кешът живее в data/cot_cache.json.

Graceful degradation: при провал на fetch → празен списък екстремуми,
секцията се крие (hide=True), не чупи pipeline-а.
"""
from __future__ import annotations
import datetime as dt
import json
import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_BASE = "https://publicreporting.cftc.gov/resource/{id}.json"
_UA = {"User-Agent": "market-brief/1.0 (personal research tool)"}

_TFF_ID = "gpe5-46if"
_DISAGG_ID = "72hh-3qpy"

_CACHE = config.DATA_DIR / "cot_cache.json"
_LOOKBACK_WEEKS = 156          # ~3 години
_FETCH_BUFFER_WEEKS = 170      # малко повече при пълно първо теглене, за буфер


# ──────────────────────────────────────────────────────────────────────────
# Fetch: TFF (финансови) и Disaggregated (стоки), инкрементално по дата
# ──────────────────────────────────────────────────────────────────────────
def _fetch_since(dataset_id: str, long_field: str, short_field: str,
                 since: str | None) -> list[dict]:
    """
    Тегли редове от Socrata API след дадена дата (ISO). since=None → пълна
    история за lookback прозореца (първо теглене). Връща плоски записи:
    [{market, date, net}], сортирани по market после дата.
    """
    params = {
        "$limit": 50000,
        "$select": f"market_and_exchange_names,report_date_as_yyyy_mm_dd,"
                   f"{long_field},{short_field}",
        "$order": "report_date_as_yyyy_mm_dd ASC",
    }
    if since:
        params["$where"] = f"report_date_as_yyyy_mm_dd > '{since}'"
    else:
        start = (dt.date.today() - dt.timedelta(weeks=_FETCH_BUFFER_WEEKS)).isoformat()
        params["$where"] = f"report_date_as_yyyy_mm_dd > '{start}'"

    r = requests.get(_BASE.format(id=dataset_id), params=params,
                     headers=_UA, timeout=60)
    r.raise_for_status()
    rows = r.json()

    out = []
    for row in rows:
        try:
            long_v = float(row.get(long_field) or 0)
            short_v = float(row.get(short_field) or 0)
        except (TypeError, ValueError):
            continue
        market = row.get("market_and_exchange_names")
        date = row.get("report_date_as_yyyy_mm_dd", "")[:10]
        if not market or not date:
            continue
        out.append({"market": market, "date": date, "net": long_v - short_v})
    return out


def _load_cache() -> dict:
    if _CACHE.exists():
        try:
            return json.loads(_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"tff": {}, "disaggregated": {}, "last_updated": None}


def _save_cache(cache: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    cache["last_updated"] = dt.date.today().isoformat()
    _CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _merge_series(existing: dict, new_rows: list[dict]) -> dict:
    """existing: {market: [{date, net}, ...]}. Добавя нови точки, дедупликира
    по дата, тримва до _LOOKBACK_WEEKS + малък буфер, сортира ascending."""
    by_market: dict[str, dict[str, float]] = {}
    for market, pts in existing.items():
        by_market[market] = {p["date"]: p["net"] for p in pts}
    for row in new_rows:
        by_market.setdefault(row["market"], {})[row["date"]] = row["net"]

    out = {}
    keep = _LOOKBACK_WEEKS + 10
    for market, date_map in by_market.items():
        pts = sorted(({"date": d, "net": n} for d, n in date_map.items()),
                     key=lambda p: p["date"])
        out[market] = pts[-keep:]
    return out


def _update_report(cache: dict, key: str, dataset_id: str,
                   long_field: str, short_field: str) -> None:
    since = None
    existing = cache.get(key, {})
    if existing:
        # последна кеширана дата измежду всички пазари
        last_dates = [pts[-1]["date"] for pts in existing.values() if pts]
        since = max(last_dates) if last_dates else None
    try:
        new_rows = _fetch_since(dataset_id, long_field, short_field, since)
    except Exception as e:
        print(f"[cot] {key} fetch failed: {e}")
        new_rows = []
    cache[key] = _merge_series(existing, new_rows)


def refresh_cache() -> dict:
    """Обновява и връща кеша (TFF + Disaggregated), инкрементално."""
    cache = _load_cache()
    _update_report(cache, "tff", _TFF_ID,
                   "lev_money_positions_long_all", "lev_money_positions_short_all")
    _update_report(cache, "disaggregated", _DISAGG_ID,
                   "m_money_positions_long_all", "m_money_positions_short_all")
    _save_cache(cache)
    return cache


# ──────────────────────────────────────────────────────────────────────────
# Percentile + екстремуми
# ──────────────────────────────────────────────────────────────────────────
def _percentile_rank(history: list[float], current: float) -> float:
    """% от историческите наблюдения <= current. 0-100."""
    if not history:
        return 50.0
    below_or_eq = sum(1 for v in history if v <= current)
    return round(100.0 * below_or_eq / len(history), 1)


def _market_extreme(market: str, pts: list[dict], category: str,
                    low: float, high: float) -> dict | None:
    if len(pts) < 10:  # твърде къса история за смислен percentile
        return None
    window = pts[-_LOOKBACK_WEEKS:]
    values = [p["net"] for p in window]
    current = values[-1]
    pct = _percentile_rank(values[:-1] or values, current)

    if pct >= high:
        direction = "extreme_long"
    elif pct <= low:
        direction = "extreme_short"
    else:
        return None

    return {
        "market": market,
        "category": category,
        "net_position": int(current),
        "percentile": pct,
        "direction": direction,
        "weeks_of_history": len(window),
        "as_of": window[-1]["date"],
        "history": [{"date": p["date"], "net": int(p["net"])} for p in window[-52:]],
    }


def get_extremes(low: float | None = None, high: float | None = None) -> list[dict]:
    """
    Връща всички пазари (без ограничение на брой) с managed money net
    positioning под `low` или над `high` percentile спрямо 156-седмична
    история. Всеки запис маркира direction (extreme_long/extreme_short),
    за да може ai_brief да генерира directional + cross-sector тезите.
    Празен списък при пълен провал → секцията се крие gracefully.
    """
    low = low if low is not None else config.COT_PERCENTILE_LOW
    high = high if high is not None else config.COT_PERCENTILE_HIGH

    try:
        cache = refresh_cache()
    except Exception as e:
        print(f"[cot] refresh_cache failed: {e}")
        return []

    extremes = []
    for market, pts in cache.get("tff", {}).items():
        ext = _market_extreme(market, pts, "financial", low, high)
        if ext:
            extremes.append(ext)
    for market, pts in cache.get("disaggregated", {}).items():
        ext = _market_extreme(market, pts, "commodity", low, high)
        if ext:
            extremes.append(ext)

    # най-екстремните първо (най-далеч от 50)
    extremes.sort(key=lambda e: abs(e["percentile"] - 50), reverse=True)
    return extremes


if __name__ == "__main__":
    exts = get_extremes()
    print(f"{len(exts)} екстремума")
    for e in exts[:10]:
        print(f"  {e['market'][:40]:40s} {e['category']:10s} "
              f"pct={e['percentile']:5.1f} {e['direction']}")
