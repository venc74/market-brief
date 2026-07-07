"""
COT (Commitments of Traders) — managed money net positioning, методология Jason Shapiro.

Източник: CFTC публичен Socrata API (публично, без ключ):
  https://publicreporting.cftc.gov/resource/{dataset_id}.json

Два отчета покриват универса, защото "hot money" категорията се казва различно
във всеки:
  • TFF Futures Only (gpe5-46if)         — финансови фючърси. Категория: Leveraged Funds.
  • Disaggregated Futures Only (72hh-3qpy) — стоки. Категория: Managed Money.

v2 (след review): CFTC докладва стотици пазари, повечето регионални
power/basis контракти без реален retail интерес (PJM zones, ISO-NE hubs...) и
без ясна свързаност с търгуеми тикъри. Затова само MAJOR_MARKETS whitelist-ът
по-долу се разглежда — ~35 наистина ликвидни, широко следени пазара с ясен
tradeable proxy (ETF/фючърс/сектор). Това елиминира и дублирането (един
резолвнат market_and_exchange_names запис на whitelist entry).

Методология (Shapiro):
  • Net position всяка седмица за всеки пазар.
  • Percentile rank на текущия net спрямо последните ~3 години (156 седмици).
  • Екстремум = percentile < COT_PERCENTILE_LOW или > COT_PERCENTILE_HIGH.
    По подразбиране 10/90 (по-строго от първоначалните 15/85) — по-малко,
    но по-сигнификантни резултати; contrarian: екстремно дълги = потенциален
    bearish обрат за инструмента, екстремно къси = потенциален bullish обрат.

Кеширане: инкрементално в data/cot_cache.json (само новите седмици на ден).
Graceful degradation: при провал → празен списък, секцията се крие.
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
_LOOKBACK_WEEKS = 156
_FETCH_BUFFER_WEEKS = 170

# ──────────────────────────────────────────────────────────────────────────
# Whitelist: (label_bg, source, all_keywords, exclude_keywords)
# source: "tff" (финансови, Leveraged Funds) или "disaggregated" (стоки, Managed Money)
# Match: market_and_exchange_names (uppercase) съдържа ВСИЧКИ all_keywords и
# НИТО ЕДИН exclude_keyword. При няколко съвпадения — избира се първото по
# азбучен ред (детерминистично, елиминира дублиране).
# ──────────────────────────────────────────────────────────────────────────
MAJOR_MARKETS = [
    # ── Финансови (TFF · Leveraged Funds) ──
    ("E-mini S&P 500",        "tff", ["E-MINI S&P 500"],            []),
    ("Nasdaq-100",            "tff", ["NASDAQ-100"],                []),
    ("E-mini Russell 2000",   "tff", ["RUSSELL", "E-MINI"],         []),
    ("E-mini Dow (DJIA)",     "tff", ["DJIA"],                      []),
    ("VIX Futures",           "tff", ["VIX"],                       []),
    ("US Dollar Index",       "tff", ["DOLLAR INDEX"],              []),
    ("Euro FX",               "tff", ["EURO FX"],                   []),
    ("Japanese Yen",          "tff", ["JAPANESE YEN"],               []),
    ("British Pound",         "tff", ["BRITISH POUND"],             []),
    ("Swiss Franc",           "tff", ["SWISS FRANC"],                []),
    ("Canadian Dollar",       "tff", ["CANADIAN DOLLAR"],            []),
    ("Australian Dollar",     "tff", ["AUSTRALIAN DOLLAR"],          []),
    ("Mexican Peso",          "tff", ["MEXICAN PESO"],               []),
    ("2-Year Treasury Note",  "tff", ["UST", "2Y"],                 []),
    ("5-Year Treasury Note",  "tff", ["UST", "5Y"],                 []),
    ("10-Year Treasury Note", "tff", ["UST", "10Y"],                ["ULTRA"]),
    ("Ultra Treasury Bond",   "tff", ["ULTRA", "UST", "BOND"],       []),
    ("30-Year Treasury Bond", "tff", ["UST", "BOND"],               ["ULTRA"]),

    # ── Стоки (Disaggregated · Managed Money) ──
    ("Gold",           "disaggregated", ["GOLD"],          ["MICRO", "MINI"]),
    ("Silver",         "disaggregated", ["SILVER"],        ["MICRO", "MINI"]),
    ("Copper",         "disaggregated", ["COPPER"],        []),
    ("Platinum",       "disaggregated", ["PLATINUM"],      []),
    ("Palladium",      "disaggregated", ["PALLADIUM"],     []),
    ("WTI Crude Oil",  "disaggregated", ["WTI"],           []),
    ("Brent Crude",    "disaggregated", ["BRENT"],         []),
    ("Natural Gas",    "disaggregated", ["NATURAL GAS"],   ["BASIS", "HUB", "ZONE"]),
    ("RBOB Gasoline",  "disaggregated", ["GASOLINE"],      []),
    ("Heating Oil",    "disaggregated", ["HEATING OIL"],   []),
    ("Corn",           "disaggregated", ["CORN"],          []),
    ("Soybeans",       "disaggregated", ["SOYBEANS"],      ["OIL", "MEAL"]),
    ("Soybean Oil",    "disaggregated", ["SOYBEAN OIL"],   []),
    ("Soybean Meal",   "disaggregated", ["SOYBEAN MEAL"],  []),
    ("Wheat",          "disaggregated", ["WHEAT"],         []),
    ("Sugar No. 11",   "disaggregated", ["SUGAR"],         []),
    ("Coffee C",       "disaggregated", ["COFFEE"],        []),
    ("Cocoa",          "disaggregated", ["COCOA"],         []),
    ("Cotton",         "disaggregated", ["COTTON"],        []),
    ("Lean Hogs",      "disaggregated", ["LEAN HOGS"],     []),
    ("Live Cattle",    "disaggregated", ["LIVE CATTLE"],   []),
]


# ──────────────────────────────────────────────────────────────────────────
# Fetch: TFF и Disaggregated, инкрементално по дата
# ──────────────────────────────────────────────────────────────────────────
def _fetch_since(dataset_id: str, long_field: str, short_field: str,
                 since: str | None) -> list[dict]:
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
        last_dates = [pts[-1]["date"] for pts in existing.values() if pts]
        since = max(last_dates) if last_dates else None
    try:
        new_rows = _fetch_since(dataset_id, long_field, short_field, since)
    except Exception as e:
        print(f"[cot] {key} fetch failed: {e}")
        new_rows = []
    cache[key] = _merge_series(existing, new_rows)


def refresh_cache() -> dict:
    cache = _load_cache()
    _update_report(cache, "tff", _TFF_ID,
                   "lev_money_positions_long", "lev_money_positions_short")
    _update_report(cache, "disaggregated", _DISAGG_ID,
                   "m_money_positions_long_all", "m_money_positions_short_all")
    _save_cache(cache)
    return cache


# ──────────────────────────────────────────────────────────────────────────
# Whitelist резолюция
# ──────────────────────────────────────────────────────────────────────────
def _resolve_whitelist(cache: dict) -> list[tuple[str, str, str]]:
    """
    Връща [(label_bg, source, resolved_market_name), ...] — само за whitelist
    entries, които реално се намират в текущия кеш. Едно съвпадение на entry
    (първото по азбучен ред), за да елиминираме дублиране.
    """
    resolved = []
    for label, source, keywords, excludes in MAJOR_MARKETS:
        markets = sorted(cache.get(source, {}).keys())
        match = None
        for m in markets:
            up = m.upper()
            if all(k in up for k in keywords) and not any(x in up for x in excludes):
                match = m
                break
        if match:
            resolved.append((label, source, match))
        else:
            print(f"[cot] whitelist miss: '{label}' няма съвпадение в '{source}' (все още)")
    return resolved


# ──────────────────────────────────────────────────────────────────────────
# Percentile + екстремуми
# ──────────────────────────────────────────────────────────────────────────
def _percentile_rank(history: list[float], current: float) -> float:
    if not history:
        return 50.0
    below_or_eq = sum(1 for v in history if v <= current)
    return round(100.0 * below_or_eq / len(history), 1)


def _market_extreme(label: str, pts: list[dict], category: str,
                    low: float, high: float) -> dict | None:
    if len(pts) < 10:
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
        "market": label,
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
    Връща екстремумите за MAJOR_MARKETS whitelist-а (не целия CFTC универс),
    под `low` или над `high` percentile спрямо 156-седмична история.
    Строги прагове по подразбиране (10/90) — малко на брой, но значими.
    """
    low = low if low is not None else config.COT_PERCENTILE_LOW
    high = high if high is not None else config.COT_PERCENTILE_HIGH

    try:
        cache = refresh_cache()
    except Exception as e:
        print(f"[cot] refresh_cache failed: {e}")
        return []

    resolved = _resolve_whitelist(cache)
    category_map = {"tff": "financial", "disaggregated": "commodity"}

    extremes = []
    for label, source, market_name in resolved:
        pts = cache.get(source, {}).get(market_name, [])
        ext = _market_extreme(label, pts, category_map[source], low, high)
        if ext:
            extremes.append(ext)

    extremes.sort(key=lambda e: abs(e["percentile"] - 50), reverse=True)
    return extremes


if __name__ == "__main__":
    exts = get_extremes()
    print(f"{len(exts)} екстремума (от {len(MAJOR_MARKETS)} whitelist пазара)")
    for e in exts:
        print(f"  {e['market']:24s} {e['category']:10s} "
              f"pct={e['percentile']:5.1f} {e['direction']}")
