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
    Връща [{ticker, company, manager, action, value, period}] от последните 13F
    (EDGAR primary → dataroma scrape → кеш), подредени по стойност. Кешира за деня.
    """
    min_value = min_value if min_value is not None else config.DATAROMA_MIN_VALUE
    return _fetch_body(min_value)

# ══════════════════════════════════════════════════════════════════════════
# SEC EDGAR 13F (Поправка 3) — primary, публичен API без блокиране
# ══════════════════════════════════════════════════════════════════════════
import xml.etree.ElementTree as ET

_EDGAR_UA = {"User-Agent": config.EDGAR_UA, "Accept-Encoding": "gzip, deflate"}
_TMAP_CACHE = config.DATA_DIR / "sec_tickers.json"


def _norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", "", str(name).lower())
    for w in (" inc", " corp", " corporation", " co", " ltd", " plc", " the",
              " class a", " class b", " holdings", " group", " company"):
        s = s.replace(w, "")
    return re.sub(r"\s+", " ", s).strip()


def _ticker_map() -> dict[str, str]:
    """SEC company_tickers.json → {нормализирано име: тикър}. Кеш месечно."""
    if _TMAP_CACHE.exists():
        try:
            c = json.loads(_TMAP_CACHE.read_text())
            if c.get("month") == dt.date.today().isoformat()[:7]:
                return c["map"]
        except Exception:
            pass
    out = {}
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         timeout=20, headers=_EDGAR_UA)
        r.raise_for_status()
        for v in (r.json() or {}).values():
            t = (v.get("ticker") or "").upper()
            title = v.get("title") or ""
            if t and title:
                out[_norm(title)] = t
        config.DATA_DIR.mkdir(exist_ok=True)
        _TMAP_CACHE.write_text(json.dumps({"month": dt.date.today().isoformat()[:7],
                                           "map": out}, ensure_ascii=False))
    except Exception as e:
        print(f"[edgar] ticker map: {e}")
    return out


def _latest_13f(cik: str) -> tuple[str, str] | None:
    """Връща (accessionNumber, filingDate) на последния 13F-HR за CIK."""
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                         timeout=20, headers=_EDGAR_UA)
        r.raise_for_status()
        rec = (r.json() or {}).get("filings", {}).get("recent", {})
        forms = rec.get("form", [])
        accs = rec.get("accessionNumber", [])
        dates = rec.get("filingDate", [])
        best = None
        for i, f in enumerate(forms):
            if f == "13F-HR":
                d = dates[i] if i < len(dates) else ""
                if best is None or d > best[1]:
                    best = (accs[i], d)
        return best
    except Exception as e:
        print(f"[edgar] submissions {cik}: {e}")
        return None


def _info_table(cik: str, accession: str) -> list[dict]:
    """Сваля и парсва information table XML на 13F → [{issuer, value, cusip}]."""
    cik_int = str(int(cik))
    acc_nodash = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}"
    holdings = []
    try:
        idx = requests.get(f"{base}/index.json", timeout=20, headers=_EDGAR_UA).json()
        items = (idx.get("directory", {}) or {}).get("item", [])
        xmls = [it["name"] for it in items if str(it.get("name", "")).lower().endswith(".xml")]
        # предпочитаме файл, който прилича на info table
        cand = [n for n in xmls if re.search(r"info.?table|form13f|information", n, re.I)]
        for name in (cand or xmls):
            try:
                xml = requests.get(f"{base}/{name}", timeout=20, headers=_EDGAR_UA).text
                root = ET.fromstring(xml)
                rows = []
                for el in root.iter():
                    if el.tag.split("}")[-1] == "infoTable":
                        d = {ch.tag.split("}")[-1]: ch for ch in el.iter()}
                        issuer = d.get("nameOfIssuer")
                        val = d.get("value")
                        cusip = d.get("cusip")
                        if issuer is not None and val is not None:
                            rows.append({"issuer": (issuer.text or "").strip(),
                                         "value": float(re.sub(r"[^\d.]", "", val.text or "0") or 0),
                                         "cusip": (cusip.text or "").strip() if cusip is not None else ""})
                if rows:
                    holdings = rows
                    break
            except Exception:
                continue
    except Exception as e:
        print(f"[edgar] info table {cik}/{accession}: {e}")
    return holdings


def _edgar_positions() -> list[dict]:
    """Топ позиции от последните 13F на всички CIK мениджъри (с резолюция на тикър)."""
    tmap = _ticker_map()
    rows = []
    for cik, name in config.DATAROMA_CIK.items():
        latest = _latest_13f(cik)
        if not latest:
            continue
        acc, fdate = latest
        period = f"13F · {fdate}" if fdate else "13F"
        holdings = _info_table(cik, acc)
        # 13F стойностите след 2023 са в долари; преди — в хиляди. Евристика:
        if holdings:
            mx = max(h["value"] for h in holdings)
            scale = 1000 if mx < 1e7 else 1  # ако максимумът е „малък", значи са хиляди
            for h in holdings:
                ticker = tmap.get(_norm(h["issuer"]))
                rows.append({
                    "ticker": ticker or h["issuer"][:14].upper(),
                    "company": h["issuer"],
                    "manager": name,
                    "action": "13F",
                    "value": h["value"] * scale,
                    "period": period,
                    "_resolved": bool(ticker),
                })
    return rows


# ══════════════════════════════════════════════════════════════════════════
def _fetch_body(min_value: float) -> list[dict]:
    today = dt.date.today().isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today and cached.get("rows"):
                return cached.get("rows", [])
        except Exception:
            pass

    # 1) EDGAR primary
    rows = _edgar_positions()

    # 2) стар dataroma scrape, ако EDGAR върна нищо
    if not rows:
        for code, name in config.DATAROMA_MANAGERS.items():
            rows.extend(_manager_buys(code, name, min_value))
        if not rows:
            fb = _allact_buys()
            if config.DATAROMA_STRICT_VALUE:
                fb = [r for r in fb if r["value"] is not None and r["value"] >= min_value]
            rows = fb

    # 3) ако всичко падна — последен кеш (по изискване)
    if not rows and _CACHE.exists():
        try:
            return json.loads(_CACHE.read_text()).get("rows", [])
        except Exception:
            return []

    # дедупликация по тикър (пазим най-голямата стойност, броим мениджърите)
    best: dict[str, dict] = {}
    for r in rows:
        key = r["ticker"]
        cur = best.get(key)
        if cur is None:
            best[key] = {**r, "managers": [r["manager"]], "count": 1}
        else:
            cur["count"] += 1
            if r["manager"] not in cur["managers"]:
                cur["managers"].append(r["manager"])
            if (r.get("value") or 0) > (cur.get("value") or 0):
                cur["value"] = r["value"]; cur["company"] = r.get("company", cur.get("company"))
    rows = sorted(best.values(), key=lambda r: (r.get("value") or 0), reverse=True)

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "rows": rows},
                                     ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[dataroma] cache write: {e}")
    return rows


def superinvestor_map(rows: list[dict] | None = None) -> dict[str, dict]:
    """Речник ticker → запис (с managers/count) за маркера в enrich."""
    rows = rows if rows is not None else fetch_superinvestor_buys()
    out: dict[str, dict] = {}
    for r in rows:
        out[r["ticker"]] = {
            **r,
            "managers": r.get("managers", [r["manager"]]),
            "count": r.get("count", 1),
        }
    return out


if __name__ == "__main__":
    res = fetch_superinvestor_buys()
    print(f"Significant superinvestor buys (≥ ${config.DATAROMA_MIN_VALUE:,.0f}): {len(res)}")
    for r in res[:25]:
        v = f"${r['value']:,.0f}" if r.get("value") else "—"
        print(f"  {r['ticker']:6} {r['action']:4} {v:>16}  {r['manager']} ({r.get('period')})")
