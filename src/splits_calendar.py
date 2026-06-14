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

Graceful degradation: при провал на всичко → празен списък, секцията се скрива.
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
def _from_nasdaq(monday: dt.date) -> list[dict]:
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
    return rows


# ──────────────────────────────────────────────────────────────────────────
# Източник 2 · stockanalysis.com HTML (КОРЕКТНА детекция на колони)
# ──────────────────────────────────────────────────────────────────────────
def _from_stockanalysis() -> list[dict]:
    rows = []
    if pd is None:
        return rows
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
    return rows


# ──────────────────────────────────────────────────────────────────────────
# Обогатяване с yfinance (цена + market cap) и филтри
# ──────────────────────────────────────────────────────────────────────────
def _enrich_and_filter(rows: list[dict]) -> list[dict]:
    if yf is None:
        return rows
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
                continue  # няма достатъчно данни → пропускаме (graceful)
            if price < config.SPLITS_MIN_PRICE or market_cap < config.SPLITS_MIN_MARKET_CAP:
                continue  # изхвърля микро/пени компании
            r["price"] = round(float(price), 2)
            r["market_cap"] = float(market_cap)
            out.append(r)
        except Exception as e:
            print(f"[splits] enrich {r['ticker']}: {e}")
            continue
    return out


# ──────────────────────────────────────────────────────────────────────────
# Публично API
# ──────────────────────────────────────────────────────────────────────────
def fetch_upcoming_splits(days: int = 7) -> list[dict]:
    """
    Връща сплитове за ТЕКУЩАТА седмица:
    [{ticker, company, date, date_human, ratio, split_type, price, market_cap}].
    Кешира за деня.
    """
    iso = dt.date.today().isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == iso:
                return cached.get("rows", [])
        except Exception:
            pass

    monday, sunday = _current_week()
    rows = _from_nasdaq(monday) or _from_stockanalysis()

    # филтър по текущата седмица (където има валидна дата)
    in_week = []
    for r in rows:
        d = _parse_date(r.get("date"))
        if d and monday <= d <= sunday:
            r["date_human"] = d.strftime("%b %d, %Y")  # пълна година — без bug-а
            in_week.append(r)

    # дедупликация по тикър
    seen, dedup = set(), []
    for r in in_week:
        if r["ticker"] not in seen:
            seen.add(r["ticker"]); dedup.append(r)

    result = _enrich_and_filter(dedup)
    result.sort(key=lambda r: r.get("date") or "")

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": iso, "rows": result},
                                     ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[splits] cache write: {e}")
    return result


def splits_map(rows: list[dict] | None = None) -> dict[str, dict]:
    """Речник ticker → split, за маркера в enrich."""
    rows = rows if rows is not None else fetch_upcoming_splits()
    return {r["ticker"]: r for r in rows}


if __name__ == "__main__":
    res = fetch_upcoming_splits()
    print(f"Сплитове тази седмица (цена>${config.SPLITS_MIN_PRICE:.0f}, cap>${config.SPLITS_MIN_MARKET_CAP/1e6:.0f}M): {len(res)}")
    for r in res:
        print(f"  {r['ticker']:6} {r.get('ratio'):>6} {r.get('split_type'):7} "
              f"${r.get('price')}  {r.get('date_human')}  {r.get('company')[:30]}")
