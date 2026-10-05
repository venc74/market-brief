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
# Whitelist: (label_bg, source, ТОЧНО име в market_and_exchange_names, cftc_contract_market_code)
# source: "tff" (финансови, Leveraged Funds) или "disaggregated" (стоки, Managed Money)
# Match: ТОЧНО съвпадение по име ИЛИ по cftc_contract_market_code (виж whitelist_candidates / _resolve_whitelist) —
# кодът оцелява при преименуване на контракта от борсата, името работи с кеша, който още няма кодове. Точно един кандидат
# за всеки запис: 0 → whitelist miss (лог), повече от 1 различни контракта → двусмислие (лог, пазарът се пропуска — НЕ се
# избира първият по азбучен ред); няколко имена на ЕДИН контракт (един код) → най-скорошното име. Тестът test_cot_whitelist.py изисква точно един кандидат за всеки запис срещу реалния списък на CFTC.
#
# FIX 2026-10-05 (пакет 3, т.е): преди whitelist-ът беше по ключови думи + exclude и при няколко съвпадения избираше първото по
# азбучен ред. Върху реалния CFTC списък от 05.10.2026 XRP имаше 2 кандидата (CME и Coinbase Derivatives), Gold също 2 (COMEX
# и "GOLD -1 TROY OUNCE - COINBASE DERIVATIVES") — работеха само защото правилният се нарежда пръв; Brent имаше 6.
# Brent Crude е махнат: в CFTC има само NYMEX финансов "BRENT LAST DAY" (слаб заместител на Brent на ICE); петролът е покрит
# от WTI. Избраните контракти са същите, които резолвираха и досега (проверено срещу списъка), например:
#   • Nasdaq-100 → "NASDAQ MINI" (CFTC 209742 = CME Mini NASDAQ 100, NQ), не "NASDAQ-100 Consolidated" (агрегат);
#   • E-mini Dow → "DJIA x $5" (YM), не "DJIA Consolidated"; E-mini S&P → чистият "E-MINI S&P 500", не "Consolidated";
#   • Japanese Yen/Euro FX/British Pound → outright контрактът, не XRATE кръстосаните;
#   • WTI → "WTI-PHYSICAL" (стандартният outright), Natural Gas → "NAT GAS NYME" (NYMEX), Heating Oil → "NY HARBOR ULSD";
#   • Soybeans → "SOYBEANS" (не MINI), Wheat → "WHEAT-SRW" (Chicago SRW, най-ликвидната история; HRW е легитимна алтернатива);
#   • XRP (CME) има ~53 седмици история (под стандартните 156) — виж COT_SHORT_HISTORY_WEEKS в config.py.
# ──────────────────────────────────────────────────────────────────────────
MAJOR_MARKETS = [
    # ── Финансови (TFF · Leveraged Funds) ──
    ('E-mini S&P 500'        , "tff", 'E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE', '13874A'),
    ('Nasdaq-100'            , "tff", 'NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE', '209742'),
    ('E-mini Russell 2000'   , "tff", 'RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE', '239742'),
    ('E-mini Dow (DJIA)'     , "tff", 'DJIA x $5 - CHICAGO BOARD OF TRADE', '124603'),
    ('VIX Futures'           , "tff", 'VIX FUTURES - CBOE FUTURES EXCHANGE', '1170E1'),
    ('US Dollar Index'       , "tff", 'USD INDEX - ICE FUTURES U.S.', '098662'),
    ('Euro FX'               , "tff", 'EURO FX - CHICAGO MERCANTILE EXCHANGE', '099741'),
    ('Japanese Yen'          , "tff", 'JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE', '097741'),
    ('British Pound'         , "tff", 'BRITISH POUND - CHICAGO MERCANTILE EXCHANGE', '096742'),
    ('Swiss Franc'           , "tff", 'SWISS FRANC - CHICAGO MERCANTILE EXCHANGE', '092741'),
    ('Canadian Dollar'       , "tff", 'CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE', '090741'),
    ('Australian Dollar'     , "tff", 'AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE', '232741'),
    ('Mexican Peso'          , "tff", 'MEXICAN PESO - CHICAGO MERCANTILE EXCHANGE', '095741'),
    ('2-Year Treasury Note'  , "tff", 'UST 2Y NOTE - CHICAGO BOARD OF TRADE', '042601'),
    ('5-Year Treasury Note'  , "tff", 'UST 5Y NOTE - CHICAGO BOARD OF TRADE', '044601'),
    ('10-Year Treasury Note' , "tff", 'UST 10Y NOTE - CHICAGO BOARD OF TRADE', '043602'),
    ('Ultra Treasury Bond'   , "tff", 'ULTRA UST BOND - CHICAGO BOARD OF TRADE', '020604'),
    ('30-Year Treasury Bond' , "tff", 'UST BOND - CHICAGO BOARD OF TRADE', '020601'),
    ('Bitcoin Futures (CME)' , "tff", 'BITCOIN - CHICAGO MERCANTILE EXCHANGE', '133741'),
    ('XRP'                   , "tff", 'XRP - CHICAGO MERCANTILE EXCHANGE', '176740'),

    # ── Стоки (Disaggregated · Managed Money) ──
    ('Gold'                  , "disaggregated", 'GOLD - COMMODITY EXCHANGE INC.', '088691'),
    ('Silver'                , "disaggregated", 'SILVER - COMMODITY EXCHANGE INC.', '084691'),
    ('Copper'                , "disaggregated", 'COPPER- #1 - COMMODITY EXCHANGE INC.', '085692'),
    ('Platinum'              , "disaggregated", 'PLATINUM - NEW YORK MERCANTILE EXCHANGE', '076651'),
    ('Palladium'             , "disaggregated", 'PALLADIUM - NEW YORK MERCANTILE EXCHANGE', '075651'),
    ('WTI Crude Oil'         , "disaggregated", 'WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE', '067651'),
    ('Natural Gas'           , "disaggregated", 'NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE', '023651'),
    ('RBOB Gasoline'         , "disaggregated", 'GASOLINE RBOB - NEW YORK MERCANTILE EXCHANGE', '111659'),
    ('Heating Oil'           , "disaggregated", 'NY HARBOR ULSD - NEW YORK MERCANTILE EXCHANGE', '022651'),
    ('Corn'                  , "disaggregated", 'CORN - CHICAGO BOARD OF TRADE', '002602'),
    ('Soybeans'              , "disaggregated", 'SOYBEANS - CHICAGO BOARD OF TRADE', '005602'),
    ('Soybean Oil'           , "disaggregated", 'SOYBEAN OIL - CHICAGO BOARD OF TRADE', '007601'),
    ('Soybean Meal'          , "disaggregated", 'SOYBEAN MEAL - CHICAGO BOARD OF TRADE', '026603'),
    ('Wheat'                 , "disaggregated", 'WHEAT-SRW - CHICAGO BOARD OF TRADE', '001602'),
    ('Sugar No. 11'          , "disaggregated", 'SUGAR NO. 11 - ICE FUTURES U.S.', '080732'),
    ('Coffee C'              , "disaggregated", 'COFFEE C - ICE FUTURES U.S.', '083731'),
    ('Cocoa'                 , "disaggregated", 'COCOA - ICE FUTURES U.S.', '073732'),
    ('Cotton'                , "disaggregated", 'COTTON NO. 2 - ICE FUTURES U.S.', '033661'),
    ('Lean Hogs'             , "disaggregated", 'LEAN HOGS - CHICAGO MERCANTILE EXCHANGE', '054642'),
    ('Live Cattle'           , "disaggregated", 'LIVE CATTLE - CHICAGO MERCANTILE EXCHANGE', '057642'),
]


def whitelist_candidates(entry: tuple, markets: dict[str, str | None]) -> list[str]:
    """
    Имената в `markets` ({име на пазар: cftc код или None}), които съвпадат със записа от MAJOR_MARKETS — ТОЧНО име или
    ТОЧЕН код. Сортиран списък. Едно и също име може да се води под няколко имена за същия контракт (борсата преименува:
    Ultra T-Bond е "ULTRA US T BOND" две седмици през 09.2025 и "ULTRA UST BOND" иначе, един и същ код 020604).
    """
    _label, _source, name, code = entry
    found = {m for m in markets if m == name}
    found |= {m for m, c in markets.items() if c and c == code}
    return sorted(found)


def whitelist_contracts(entry: tuple, markets: dict[str, str | None]) -> list[str]:
    """Различните КОНТРАКТИ (код, а без код — самото име) сред кандидатите; валидният запис има точно един."""
    return sorted({markets.get(m) or m for m in whitelist_candidates(entry, markets)})


def pick_current_name(info: dict[str, tuple[str, int]]) -> str:
    """
    От няколко имена на ЕДИН контракт ({име: (последна дата, брой седмици)}) — най-скорошното (при равенство — с повече
    седмици, после по име за детерминизъм). Не "първото по азбучен ред".
    """
    return max(info, key=lambda m: (info[m][0], info[m][1], m))


# ──────────────────────────────────────────────────────────────────────────
# Fetch: TFF и Disaggregated, инкрементално по дата
# ──────────────────────────────────────────────────────────────────────────
def _fetch_since(dataset_id: str, long_field: str, short_field: str,
                 since: str | None) -> list[dict]:
    params = {
        "$limit": 50000,
        "$select": f"market_and_exchange_names,cftc_contract_market_code,report_date_as_yyyy_mm_dd,"
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
        out.append({"market": market, "date": date, "net": long_v - short_v,
                    "code": row.get("cftc_contract_market_code") or None})
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
    _CACHE.write_text(json.dumps(cache, ensure_ascii=False, default=str), encoding="utf-8")


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
    # пакет 3 т.е: кодът на контракта се пази отделно (пазар → код) за whitelist резолюцията по код; старите кешове го
    # получават постепенно — с всеки нов седмичен ред (резолюцията по име работи и без него)
    codes = cache.setdefault("codes", {}).setdefault(key, {})
    for r in new_rows:
        if r.get("code"):
            codes[r["market"]] = r["code"]


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
    Връща [(label_bg, source, resolved_market_name), ...] — за whitelist записите с ТОЧНО един кандидат в текущия кеш
    (точно име или точен cftc код, виж whitelist_candidates). 0 кандидата → whitelist miss (лог); повече от 1 → двусмислие
    (лог, пазарът се пропуска — никога "първият по азбучен ред").
    """
    resolved = []
    for entry in MAJOR_MARKETS:
        label, source = entry[0], entry[1]
        names = cache.get(source, {})
        codes = (cache.get("codes") or {}).get(source, {})
        markets = {m: codes.get(m) for m in names}
        cands, contracts = whitelist_candidates(entry, markets), whitelist_contracts(entry, markets)
        if len(contracts) == 1:
            # едно или няколко имена на ЕДИН контракт (преименуване) → най-скорошното
            info = {m: ((names[m][-1]["date"] if names.get(m) else ""), len(names.get(m) or [])) for m in cands}
            resolved.append((label, source, pick_current_name(info)))
        elif not contracts:
            print(f"[cot] whitelist miss: '{label}' няма точно съвпадение в '{source}' (име '{entry[2]}', код {entry[3]})")
        else:
            print(f"[cot] ⚠ whitelist двусмислие: '{label}' има {len(contracts)} различни контракта в '{source}' {cands} — пропуска се")
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


# Състоянието на последния get_extremes(): давност на най-новия отчет — main го слага в брифа (cot_status), шаблонът
# показва банер, ако е стар. {"as_of", "age_days", "stale", "threshold_days", "reason"}
LAST_STATUS: dict = {}


def freshness(cache: dict, resolved: list[tuple[str, str, str]], today: dt.date | None = None) -> dict:
    """
    FIX 2026-10-03 (пакет 2 т.7): давност на данните. Най-новата дата на отчет сред whitelist пазарите срещу днес; "стар" е
    повече от config.COT_STALE_DAYS дни (спряна или забавена публикация на CFTC, провалено теглене — кешът мълчаливо
    остава с по-стари данни и екстремумите изглеждат актуални). Без никакви данни → stale с причина "no_data".
    """
    today = today or dt.date.today()
    limit = config.COT_STALE_DAYS
    dates = []
    for _label, source, market in resolved:
        pts = cache.get(source, {}).get(market, [])
        if pts:
            dates.append(pts[-1]["date"])
    if not dates:
        return {"as_of": None, "age_days": None, "stale": True, "threshold_days": limit, "reason": "no_data"}
    as_of = max(dates)
    age = (today - dt.date.fromisoformat(as_of)).days
    stale = age > limit
    return {"as_of": as_of, "age_days": age, "stale": stale, "threshold_days": limit, "reason": "stale" if stale else ""}


def get_extremes(low: float | None = None, high: float | None = None, today: dt.date | None = None) -> list[dict]:
    """
    Връща екстремумите за MAJOR_MARKETS whitelist-а (не целия CFTC универс),
    под `low` или над `high` percentile спрямо 156-седмична история.
    Строги прагове по подразбиране (10/90) — малко на брой, но значими.
    Давността на данните остава в LAST_STATUS (виж freshness()).
    """
    low = low if low is not None else config.COT_PERCENTILE_LOW
    high = high if high is not None else config.COT_PERCENTILE_HIGH

    LAST_STATUS.clear()
    try:
        cache = refresh_cache()
    except Exception as e:
        print(f"[cot] refresh_cache failed: {e}")
        LAST_STATUS.update(as_of=None, age_days=None, stale=True, threshold_days=config.COT_STALE_DAYS, reason="no_data")
        return []

    resolved = _resolve_whitelist(cache)
    LAST_STATUS.update(freshness(cache, resolved, today))
    if LAST_STATUS["stale"]:
        print("[cot] ⚠ няма COT данни за whitelist пазарите" if LAST_STATUS["as_of"] is None else
              f"[cot] ⚠ данните са остарели — последен отчет {LAST_STATUS['as_of']} "
              f"({LAST_STATUS['age_days']} дни, праг {LAST_STATUS['threshold_days']})")
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
