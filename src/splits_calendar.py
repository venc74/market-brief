"""
Предстоящи Stock Splits — само за ТЕКУЩАТА календарна седмица (пн–нд).

Поправка 1: предишната версия чупеше парсването (хващаше имена на компании за
тикъри, отрязваше годината „Jun 15, 20", слагаше дата в полето ratio). Тук:
  • източник: Nasdaq splits calendar JSON API (структуриран) → stockanalysis.com
    HTML fallback с КОРЕКТНА детекция на колони;
  • дата се парсва с пълна година и се нормализира до ISO;
  • тип на сплита: normal (2:1, 3:1…) или reverse (1:10…), + ratio;
  • обогатяване с yfinance: текуща цена + market cap;
  • филтър: само текущата седмица, цена > $10 и market cap > $500M
    (изхвърля микро китайски/японски компании);
  • маркер 'SPLIT✓' остава за тикър, който е и в нашия скрийнър.

Graceful degradation: при провал на всичко → празен списък. FIX 2026-09-27:
секцията вече НЕ се скрива — splits_report() връща state ok/empty/source_failed
+ фунията по филтри, и приоритетни сплитове за отворени позиции/наблюдавани.
"""
from __future__ import annotations
import datetime as dt
import io
import json
import re
import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

try:
    import pandas as pd
except Exception:
    pd = None
try:
    import yfinance as yf
except Exception:
    yf = None

_NASDAQ = "https://api.nasdaq.com/api/calendar/splits"
_SA = "https://stockanalysis.com/actions/splits/"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
       "Accept": "application/json, text/html"}
_CACHE = config.DATA_DIR / "splits_cache.json"


# ──────────────────────────────────────────────────────────────────────────
# Парсери за дата, ratio и тип
# ──────────────────────────────────────────────────────────────────────────
def _parse_date(val) -> dt.date | None:
    """'Jun 15, 2026' / '2026-06-15' / '06/15/2026' → date. Поправя year-bug."""
    if val is None:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # ISO с време
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def _parse_ratio(val) -> tuple[str | None, str | None]:
    """
    Връща (ratio, type). '2:1'→('2:1','normal'); '1:10'→('1:10','reverse');
    '3-for-1'→('3:1','normal'). Дати без ratio-разделител НЕ се бъркат за ratio.
    """
    if val is None:
        return None, None
    s = str(val).strip()
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if len(nums) >= 2 and re.search(r"[:/]|for|-", s, re.I):
        a, b = float(nums[0]), float(nums[1])
        return f"{nums[0]}:{nums[1]}", ("reverse" if a < b else "normal")
    return (s or None), None


# ──────────────────────────────────────────────────────────────────────────
# Текуща календарна седмица (пн–нд)
# ──────────────────────────────────────────────────────────────────────────
def _current_week() -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    return monday, monday + dt.timedelta(days=6)


# ──────────────────────────────────────────────────────────────────────────
# Източник 1 · Nasdaq JSON
# ──────────────────────────────────────────────────────────────────────────
def _from_nasdaq(monday: dt.date) -> tuple[list[dict], str | None]:
    """Връща (редове, грешка). Грешката е None при успешна заявка, дори с 0 реда."""
    rows = []
    try:
        r = requests.get(_NASDAQ, params={"date": monday.isoformat()},
                         timeout=15, headers=_UA)
        r.raise_for_status()
        data = r.json() or {}
        records = (((data.get("data") or {}).get("rows")) or [])
        for it in records:
            sym = (it.get("symbol") or "").strip().upper()
            if not sym or not re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", sym):
                continue
            ratio, stype = _parse_ratio(it.get("ratio") or it.get("splitRatio"))
            d = _parse_date(it.get("executionDate") or it.get("exDate") or it.get("date"))
            rows.append({"ticker": sym, "company": (it.get("name") or "").strip(),
                         "date": d.isoformat() if d else None,
                         "ratio": ratio, "split_type": stype})
    except Exception as e:
        print(f"[splits] Nasdaq failed: {e}")
        return rows, f"Nasdaq: {type(e).__name__}: {e}"
    return rows, None


# ──────────────────────────────────────────────────────────────────────────
# Източник 2 · stockanalysis.com HTML (КОРЕКТНА детекция на колони)
# ──────────────────────────────────────────────────────────────────────────
def _from_stockanalysis() -> tuple[list[dict], str | None]:
    rows = []
    if pd is None:
        return rows, "pandas липсва"
    try:
        html = requests.get(_SA, timeout=20, headers=_UA).text
        for tbl in pd.read_html(io.StringIO(html)):
            cols = {str(c).lower(): c for c in tbl.columns}
            # символът е в колона "Symbol"; компанията е отделно — НЕ ги бъркаме
            sym_c = next((cols[k] for k in cols if k in ("symbol", "ticker")), None)
            comp_c = next((cols[k] for k in cols if "company" in k or "name" in k), None)
            date_c = next((cols[k] for k in cols if "date" in k or "effective" in k), None)
            ratio_c = next((cols[k] for k in cols if "ratio" in k or k == "split"), None)
            if sym_c is None:
                continue
            for _, row in tbl.iterrows():
                sym = re.sub(r"[^A-Z.\-]", "", str(row[sym_c]).upper())
                if not sym or len(sym) > 6:
                    continue
                ratio, stype = _parse_ratio(row[ratio_c]) if ratio_c is not None else (None, None)
                d = _parse_date(row[date_c]) if date_c is not None else None
                rows.append({"ticker": sym,
                             "company": str(row[comp_c]).strip() if comp_c is not None else "",
                             "date": d.isoformat() if d else None,
                             "ratio": ratio, "split_type": stype})
            if rows:
                break
    except Exception as e:
        print(f"[splits] stockanalysis failed: {e}")
        return rows, f"stockanalysis: {type(e).__name__}: {e}"
    return rows, None


# ──────────────────────────────────────────────────────────────────────────
# Обогатяване с yfinance (цена + market cap) и филтри
# ──────────────────────────────────────────────────────────────────────────
def _enrich_and_filter(rows: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    """
    FIX 2026-09-27: връща и КОЙ отпада и защо (price / cap / no_data) —
    преди отпадналите изчезваха безшумно и празна секция не можеше да се
    различи от счупен източник (8 празни брифа 16–26.09 при 15–28 сурови реда).
    """
    drops: dict[str, list[str]] = {"price": [], "cap": [], "no_data": []}
    if yf is None:
        return rows, drops
    out = []
    for r in rows:
        try:
            tk = yf.Ticker(r["ticker"])
            price = market_cap = None
            try:
                fi = tk.fast_info
                price = getattr(fi, "last_price", None) or fi.get("lastPrice")
                market_cap = getattr(fi, "market_cap", None) or fi.get("marketCap")
            except Exception:
                pass
            if price is None or market_cap is None:
                info = tk.info or {}
                price = price or info.get("currentPrice") or info.get("regularMarketPrice")
                market_cap = market_cap or info.get("marketCap")
            if price is None or market_cap is None:
                drops["no_data"].append(r["ticker"])  # няма данни в yfinance (graceful)
                continue
            if price < config.SPLITS_MIN_PRICE:
                drops["price"].append(r["ticker"])  # пени акции
                continue
            if market_cap < config.SPLITS_MIN_MARKET_CAP:
                drops["cap"].append(r["ticker"])  # микро компании
                continue
            r["price"] = round(float(price), 2)
            r["market_cap"] = float(market_cap)
            out.append(r)
        except Exception as e:
            print(f"[splits] enrich {r['ticker']}: {e}")
            drops["no_data"].append(r["ticker"])
            continue
    return out, drops


def _dedup(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        if r["ticker"] not in seen:
            seen.add(r["ticker"]); out.append(r)
    return out


def _compute() -> dict:
    """
    Един fetch → пълна фуния + суровият хоризонт на източника (нужен за
    приоритетните сплитове на отворени позиции/наблюдавани, т.5).
    """
    monday, sunday = _current_week()
    errors = []
    rows, err = _from_nasdaq(monday)
    source = "nasdaq"
    if err:
        errors.append(err)
    if not rows:
        rows, err = _from_stockanalysis()
        source = "stockanalysis"
        if err:
            errors.append(err)

    # целият хоризонт с валидна дата — за приоритетния блок, без никакви филтри
    horizon = []
    for r in rows:
        d = _parse_date(r.get("date"))
        if d:
            r["date_human"] = d.strftime("%b %d, %Y")  # пълна година — без bug-а
            horizon.append(r)
    horizon.sort(key=lambda r: r["date"])

    # филтър по текущата седмица (където има валидна дата)
    in_week = [dict(r) for r in horizon if monday <= _parse_date(r["date"]) <= sunday]
    dedup = _dedup(in_week)

    result, drops = _enrich_and_filter(dedup)
    result.sort(key=lambda r: r.get("date") or "")

    diag = {
        "source": source if rows else None,
        "errors": errors,
        "source_rows": len(rows),
        "horizon_from": horizon[0]["date"] if horizon else None,
        "horizon_to": horizon[-1]["date"] if horizon else None,
        "in_week": len(dedup),
        "dropped_price": drops["price"],
        "dropped_cap": drops["cap"],
        "dropped_no_data": drops["no_data"],
        "passed": len(result),
    }
    # (б) vs (в) се решава по суровия брой от източника, НЕ по крайния резултат
    diag["state"] = ("source_failed" if not rows else "ok" if result else "empty")
    return {"rows": result, "horizon": _dedup_by_ticker_date(horizon), "diag": diag}


def _dedup_by_ticker_date(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        k = (r["ticker"], r["date"])
        if k not in seen:
            seen.add(k); out.append(r)
    return out


def _log_diag(diag: dict) -> None:
    """Фунията винаги в лога — и поименно кои нямат данни в yfinance."""
    if diag["state"] == "source_failed":
        print(f"[splits] ИЗТОЧНИКЪТ НЕ ВЪРНА ДАННИ ({'; '.join(diag['errors']) or '0 реда'})")
        return
    print(f"[splits] {diag['source']}: {diag['source_rows']} реда "
          f"(хоризонт {diag['horizon_from']}…{diag['horizon_to']}), "
          f"{diag['in_week']} в седмицата → {len(diag['dropped_price'])} под "
          f"${config.SPLITS_MIN_PRICE:.0f}, {len(diag['dropped_cap'])} под "
          f"${config.SPLITS_MIN_MARKET_CAP/1e6:.0f}M, {len(diag['dropped_no_data'])} без данни "
          f"→ {diag['passed']} минават")
    if diag["dropped_no_data"]:
        print(f"[splits] без цена/пазарна стойност в yfinance: {', '.join(diag['dropped_no_data'])}")


def _load() -> dict:
    """Кеш за деня. Стар формат (само 'rows', без 'diag') → преизчисляване."""
    iso = dt.date.today().isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == iso and "diag" in cached:
                return cached
        except Exception:
            pass
    data = _compute()
    _log_diag(data["diag"])
    # провален източник НЕ се кешира — повторен run същия ден опитва отново
    if data["diag"]["state"] != "source_failed":
        try:
            config.DATA_DIR.mkdir(exist_ok=True)
            _CACHE.write_text(json.dumps({"date": iso, **data},
                                         ensure_ascii=False, indent=1, default=str))
        except Exception as e:
            print(f"[splits] cache write: {e}")
    return data


# ──────────────────────────────────────────────────────────────────────────
# Публично API
# ──────────────────────────────────────────────────────────────────────────
def fetch_upcoming_splits(days: int = 7) -> list[dict]:
    """
    Връща сплитове за ТЕКУЩАТА седмица:
    [{ticker, company, date, date_human, ratio, split_type, price, market_cap}].
    Кешира за деня.
    """
    try:
        return _load()["rows"]
    except Exception as e:
        print(f"[splits] fetch_upcoming_splits: {e}")
        return []


def splits_map(rows: list[dict] | None = None) -> dict[str, dict]:
    """Речник ticker → split, за маркера в enrich."""
    rows = rows if rows is not None else fetch_upcoming_splits()
    return {r["ticker"]: r for r in rows}


def splits_report(positions: set[str] | None = None,
                  watched: set[str] | None = None) -> dict:
    """
    FIX 2026-09-27 (т.4 + т.5): пълният отчет за секцията.

      state     — "ok" / "empty" / "source_failed" (секцията вече не се скрива)
      diag      — фунията (източник, хоризонт, отпаднали по филтър поименно)
      rows      — седмичните сплитове по критериите, както досега (+ badge)
      priority  — сплитове на ОТВОРЕНИ ПОЗИЦИИ и НАБЛЮДАВАНИ в целия хоризонт
                  на източника (~2 седмици), без филтър за седмица/цена/cap.
                  Не дублира тикъри, които вече са в `rows`.

    MNST (изпълнение 11.08, 8-K 08.07) се появи в секцията едва на 10.08 —
    в понеделника на седмицата на изпълнение, при отворена позиция.
    """
    positions = {t.upper() for t in (positions or set())}
    watched = {t.upper() for t in (watched or set())} - positions  # позиция > наблюдаван
    try:
        data = _load()
    except Exception as e:
        print(f"[splits] splits_report: {e}")
        return {"state": "source_failed", "diag": {"errors": [str(e)]},
                "rows": [], "priority": []}

    today = dt.date.today()

    def _tag(r: dict) -> dict:
        r = dict(r)
        d = _parse_date(r.get("date"))
        r["days_to_split"] = (d - today).days if d else None
        r["badge"] = ("position" if r["ticker"] in positions
                      else "watch" if r["ticker"] in watched else None)
        return r

    rows = [_tag(r) for r in data["rows"]]
    shown = {r["ticker"] for r in rows}
    priority = [_tag(r) for r in data.get("horizon", [])
                if (r["ticker"] in positions or r["ticker"] in watched)
                and r["ticker"] not in shown]
    # позиции първо, после по дата
    priority.sort(key=lambda r: (r["badge"] != "position", r["date"]))
    if priority:
        print("[splits] приоритетни: " + ", ".join(
            f"{r['ticker']} ({r['badge']}, {r['date']}, {r['days_to_split']:+d}д)"
            for r in priority))
    return {"state": data["diag"]["state"], "diag": data["diag"],
            "rows": rows, "priority": priority}


if __name__ == "__main__":
    rep = splits_report()
    res = rep["rows"]
    print(f"Сплитове тази седмица (цена>${config.SPLITS_MIN_PRICE:.0f}, cap>${config.SPLITS_MIN_MARKET_CAP/1e6:.0f}M): {len(res)}  [state={rep['state']}]")
    for r in res:
        print(f"  {r['ticker']:6} {r.get('ratio'):>6} {r.get('split_type'):7} "
              f"${r.get('price')}  {r.get('date_human')}  {r.get('company')[:30]}")
