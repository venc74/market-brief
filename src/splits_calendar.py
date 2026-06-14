"""
Секция 3.4 — Предстоящи Stock Splits от TipRanks.

tipranks.com/calendars/stock-splits/upcoming публикува предстоящи сплитове.
Защо ни вълнуват: психологически правят акцията „по-достъпна", обикновено носят
momentum в седмиците преди, и понякога сигнализират management confidence.

Извличаме тикър, дата и ratio (2:1, 3:1...). Ако предстоящ split е в следващите
N дни И акцията е в CANSLIM скринера → маркер 'SPLIT✓' + споменаване в катализаторите.
Отделен mini-раздел в dashboard: „Upcoming Splits This Month".

TipRanks е силно JavaScript-зависим и често зарежда данните през вътрешен API.
Опитваме два пътя: (1) публичния им JSON API; (2) pandas.read_html върху страницата.
При провал → празен списък (Секция 7, graceful degradation).
"""
from __future__ import annotations
import datetime as dt
import io
import json
import re
import requests
import pandas as pd

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_PAGE = "https://www.tipranks.com/calendars/stock-splits/upcoming"
_API = "https://www.tipranks.com/api/calendars/stockSplits/"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
       "Accept": "application/json, text/html"}
_CACHE = config.DATA_DIR / "splits_cache.json"


def _parse_ratio(val) -> str | None:
    s = str(val)
    m = re.search(r"(\d+)\s*[:\-/ ]\s*(\d+)", s)
    return f"{m.group(1)}:{m.group(2)}" if m else (s.strip() or None)


def fetch_upcoming_splits(days: int = 30) -> list[dict]:
    """Връща [{ticker, date, ratio}] за сплитове в следващите `days` дни. Кешира за деня."""
    today = dt.date.today()
    iso = today.isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == iso:
                return cached.get("rows", [])
        except Exception:
            pass

    rows: list[dict] = []

    # ── Път 1: вътрешен JSON API ───────────────────────────────────────────
    try:
        r = requests.get(_API, timeout=15, headers=_UA)
        if r.ok and "application/json" in r.headers.get("Content-Type", ""):
            for item in (r.json() or []):
                sym = (item.get("ticker") or item.get("symbol") or "").upper()
                date = item.get("executionDate") or item.get("date")
                ratio = _parse_ratio(item.get("splitRatio") or item.get("ratio"))
                if sym and date:
                    rows.append({"ticker": sym, "date": str(date)[:10], "ratio": ratio})
    except Exception as e:
        print(f"[splits_calendar] API path failed: {e}")

    # ── Път 2: HTML таблица (ако API не върна нищо) ─────────────────────────
    if not rows:
        try:
            html = requests.get(_PAGE, timeout=20, headers=_UA).text
            for tbl in pd.read_html(io.StringIO(html)):
                cols = [str(c).lower() for c in tbl.columns]
                sc = next((tbl.columns[i] for i, c in enumerate(cols)
                           if "ticker" in c or "symbol" in c or "company" in c), None)
                dc = next((tbl.columns[i] for i, c in enumerate(cols) if "date" in c), None)
                rc = next((tbl.columns[i] for i, c in enumerate(cols) if "ratio" in c or "split" in c), None)
                if sc is None:
                    continue
                for _, row in tbl.iterrows():
                    sym = re.sub(r"[^A-Z\.\-]", "", str(row[sc]).upper())[:6]
                    if not sym:
                        continue
                    rows.append({
                        "ticker": sym,
                        "date": str(row[dc])[:10] if dc is not None else None,
                        "ratio": _parse_ratio(row[rc]) if rc is not None else None,
                    })
                break
        except Exception as e:
            print(f"[splits_calendar] HTML path failed: {e}")

    # ── Път 3: stockanalysis.com fallback (ако TipRanks се провали) ────────
    if not rows:
        try:
            html = requests.get("https://stockanalysis.com/actions/splits/",
                                timeout=20, headers=_UA).text
            for tbl in pd.read_html(io.StringIO(html)):
                cols = [str(c).lower() for c in tbl.columns]
                sc = next((tbl.columns[i] for i, c in enumerate(cols)
                           if "symbol" in c or "ticker" in c), None)
                dc = next((tbl.columns[i] for i, c in enumerate(cols)
                           if "date" in c or "effective" in c or "ex" in c), None)
                rc = next((tbl.columns[i] for i, c in enumerate(cols)
                           if "ratio" in c or "split" in c), None)
                if sc is None:
                    continue
                for _, row in tbl.iterrows():
                    sym = re.sub(r"[^A-Z\.\-]", "", str(row[sc]).upper())[:6]
                    if not sym:
                        continue
                    rows.append({
                        "ticker": sym,
                        "date": str(row[dc])[:10] if dc is not None else None,
                        "ratio": _parse_ratio(row[rc]) if rc is not None else None,
                    })
                break
        except Exception as e:
            print(f"[splits_calendar] stockanalysis fallback failed: {e}")

    # филтър по прозорец от `days` дни (където има валидна дата)
    horizon = today + dt.timedelta(days=days)
    filtered = []
    for r in rows:
        d = r.get("date")
        try:
            if d and today <= dt.date.fromisoformat(d) <= horizon:
                filtered.append(r)
        except ValueError:
            filtered.append(r)  # неясна дата → пускаме я, по-добре да се види
    filtered = filtered or rows  # ако филтърът изпразни всичко, върни суровото

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": iso, "rows": filtered},
                                     ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[splits_calendar] cache write: {e}")

    return filtered


def splits_map(rows: list[dict] | None = None) -> dict[str, dict]:
    """Речник ticker → split ред, за бърза проверка в enrich."""
    rows = rows if rows is not None else fetch_upcoming_splits()
    return {r["ticker"]: r for r in rows}


if __name__ == "__main__":
    res = fetch_upcoming_splits()
    print(f"Предстоящи сплитове: {len(res)}")
    for r in res:
        print(" ", r)
