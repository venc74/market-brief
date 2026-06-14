"""
Допълнение към v2 — Superinvestor Moves от dataroma.com.

dataroma.com агрегира 13F заявките на известни „superinvestors" (Бъфет, Дракенмилър,
Бъри и др.). Извличаме последните значими ПОКУПКИ (нова позиция или добавяне) и
филтрираме само транзакции над прага (по подразбиране $10M).

Логика на сигнала: 13F е със закъснение (до 45 дни след тримесечието), затова не е
тайминг инструмент — но КОНВЕРГЕНЦИЯ е силна. Ако акция, която вече излиза в нашия
CANSLIM скринер (технически + фундаментален пробив СЕГА), е била и купена от
superinvestor → маркер 'SI✓'. Техническата сила потвърждава, че умните пари не са
сбъркали; институционалното позициониране потвърждава, че пробивът има фундамент.

Източник на стойността: dataroma показва Value (стойност на позицията) на страницата
на всеки мениджър. За нова покупка (Buy) стойността на позицията ≈ стойността на
транзакцията; за добавяне (Add) е горна граница. Затова прагът се прилага върху
стойността на позицията — разумен proxy за „значима" сделка (документирано тук).

ВАЖНО: кодовете на мениджърите (config.DATAROMA_MANAGERS) идват от URL-а на dataroma
(`/m/holdings.php?m=КОД`). Те се менят рядко, но ВЕРИФИЦИРАЙ ги — при грешен код този
мениджър просто се пропуска (graceful). Ако всички per-manager страници върнат нищо,
има fallback към общата активност (`allact.php`), който не изисква кодове.

Graceful degradation (Секция 7): всяка грешка → празен резултат, брифът продължава.
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

_BASE = "https://www.dataroma.com/m"
_HOLDINGS = _BASE + "/holdings.php?m={code}"
_ALLACT = _BASE + "/allact.php"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
       "Accept": "text/html,application/xhtml+xml"}
_CACHE = config.DATA_DIR / "dataroma_cache.json"


# ──────────────────────────────────────────────────────────────────────────
# Помощни парсери
# ──────────────────────────────────────────────────────────────────────────
def _parse_money(val) -> float | None:
    """'$1,234,567' / '1,234,567' → 1234567.0 ; None при липса."""
    if val is None:
        return None
    s = re.sub(r"[^\d.]", "", str(val))
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_symbol(val) -> str | None:
    """'AAPL - Apple Inc.' / 'AAPL' → 'AAPL'."""
    if val is None:
        return None
    s = str(val).strip()
    m = re.match(r"([A-Z][A-Z\.\-]{0,6})\b", s)
    return m.group(1) if m else None


def _classify_activity(val) -> str | None:
    """'Buy' / 'Add 12.5%' / 'Reduce' / 'Sell' → 'Buy' | 'Add' | None (пропусни)."""
    s = str(val or "").lower()
    if "buy" in s:
        return "Buy"
    if "add" in s:
        return "Add"
    return None  # reduce / sell / празно — не ни интересува


def _find_col(columns, *needles):
    for i, c in enumerate(columns):
        cl = str(c).lower()
        if all(n in cl for n in needles):
            return columns[i]
    return None


# ──────────────────────────────────────────────────────────────────────────
# Слой 1: per-manager страници (стойност е налична → точен $ филтър)
# ──────────────────────────────────────────────────────────────────────────
def _manager_buys(code: str, name: str, min_value: float) -> list[dict]:
    rows = []
    try:
        html = requests.get(_HOLDINGS.format(code=code), timeout=20, headers=_UA).text
        period = None
        m = re.search(r"\bQ[1-4]\s*20\d{2}\b", html)
        if m:
            period = m.group(0)
        for tbl in pd.read_html(io.StringIO(html)):
            cols = list(tbl.columns)
            sym_c = _find_col(cols, "stock") or _find_col(cols, "ticker") or _find_col(cols, "symbol")
            act_c = _find_col(cols, "activity") or _find_col(cols, "recent")
            val_c = _find_col(cols, "value")
            if sym_c is None or act_c is None:
                continue
            for _, r in tbl.iterrows():
                action = _classify_activity(r[act_c])
                if action is None:
                    continue
                sym = _parse_symbol(r[sym_c])
                if not sym:
                    continue
                value = _parse_money(r[val_c]) if val_c is not None else None
                if value is not None and value < min_value:
                    continue
                rows.append({"ticker": sym, "manager": name, "action": action,
                             "value": value, "period": period})
            if rows:
                break  # първата валидна таблица стига
    except Exception as e:
        print(f"[dataroma] manager {code}: {e}")
    return rows


# ──────────────────────────────────────────────────────────────────────────
# Слой 2 (fallback): обща активност — без стойност, без нужда от кодове
# ──────────────────────────────────────────────────────────────────────────
def _allact_buys() -> list[dict]:
    rows = []
    try:
        html = requests.get(_ALLACT, timeout=20, headers=_UA).text
        for tbl in pd.read_html(io.StringIO(html)):
            cols = list(tbl.columns)
            sym_c = _find_col(cols, "stock") or _find_col(cols, "ticker") or _find_col(cols, "symbol")
            act_c = _find_col(cols, "activity") or _find_col(cols, "action")
            mgr_c = _find_col(cols, "manager") or _find_col(cols, "investor") or _find_col(cols, "fund")
            per_c = _find_col(cols, "period") or _find_col(cols, "date")
            if sym_c is None or act_c is None:
                continue
            for _, r in tbl.iterrows():
                action = _classify_activity(r[act_c])
                if action is None:
                    continue
                sym = _parse_symbol(r[sym_c])
                if not sym:
                    continue
                rows.append({
                    "ticker": sym,
                    "manager": str(r[mgr_c]).strip() if mgr_c is not None else "superinvestor",
                    "action": action, "value": None,
                    "period": str(r[per_c]).strip() if per_c is not None else None,
                })
            if rows:
                break
    except Exception as e:
        print(f"[dataroma] allact fallback: {e}")
    return rows


# ──────────────────────────────────────────────────────────────────────────
# Публично API
# ──────────────────────────────────────────────────────────────────────────
def fetch_superinvestor_buys(min_value: float | None = None) -> list[dict]:
    """
    Връща [{ticker, manager, action, value, period}] — значими покупки/добавяния,
    подредени по стойност (най-голямата отгоре). Кешира за деня.
    """
    min_value = min_value if min_value is not None else config.DATAROMA_MIN_VALUE
    today = dt.date.today().isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today:
                return cached.get("rows", [])
        except Exception:
            pass

    rows: list[dict] = []
    for code, name in config.DATAROMA_MANAGERS.items():
        rows.extend(_manager_buys(code, name, min_value))

    # fallback, ако per-manager пасът върна нищо (напр. сменени кодове)
    if not rows:
        fallback = _allact_buys()
        if config.DATAROMA_STRICT_VALUE:
            fallback = [r for r in fallback if r["value"] is not None and r["value"] >= min_value]
        rows = fallback

    # дедупликация: пазим записа с най-голяма стойност за всеки (мениджър, тикър)
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (r["manager"], r["ticker"])
        cur = best.get(key)
        if cur is None or (r.get("value") or 0) > (cur.get("value") or 0):
            best[key] = r
    rows = sorted(best.values(),
                  key=lambda r: (r.get("value") or 0), reverse=True)

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "rows": rows},
                                     ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[dataroma] cache write: {e}")

    return rows


def superinvestor_map(rows: list[dict] | None = None) -> dict[str, dict]:
    """
    Речник ticker → най-значимият запис за бърза проверка в enrich.
    При няколко мениджъра за един тикър пазим най-голямата сделка, но броим всички.
    """
    rows = rows if rows is not None else fetch_superinvestor_buys()
    out: dict[str, dict] = {}
    for r in rows:
        cur = out.get(r["ticker"])
        if cur is None:
            out[r["ticker"]] = {**r, "managers": [r["manager"]], "count": 1}
        else:
            cur["count"] += 1
            cur["managers"].append(r["manager"])
            if (r.get("value") or 0) > (cur.get("value") or 0):
                cur["value"] = r["value"]; cur["action"] = r["action"]
    return out


if __name__ == "__main__":
    res = fetch_superinvestor_buys()
    print(f"Significant superinvestor buys (≥ ${config.DATAROMA_MIN_VALUE:,.0f}): {len(res)}")
    for r in res[:25]:
        v = f"${r['value']:,.0f}" if r.get("value") else "—"
        print(f"  {r['ticker']:6} {r['action']:4} {v:>16}  {r['manager']} ({r.get('period')})")
