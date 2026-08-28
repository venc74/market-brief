"""
Допълнение към v2 — Superinvestor сигнали от SEC EDGAR 13F-HR (16 мениджъра,
config.DATAROMA_CIK). Три отделни, но споделящи данни изхода (виж _fetch_all
+ _manager_snapshot по-долу — ЕДИН fetch на 13F данни на мениджър, консумиран
от трите):

  1. fetch_superinvestor_buys() — общ "Moves" feed (нова позиция/увеличена,
     $DATAROMA_MIN_VALUE праг). Top-N-per-manager селекция (config.
     DATAROMA_TOP_PER_MANAGER), не global top-по-стойност — Berkshire's
     позиции ($10B+) системно изяждаха всичките dashboard слота преди
     FIX 2026-08-17.
  2. fetch_new_position_highlights() — high-conviction "нова позиция":
     съвсем нова (CUSIP отсъства в предишния filing) И >= config.
     DATAROMA_MIN_NEW_POSITION_PCT% от портфейла на мениджъра. % на
     портфейл, НЕ $ праг — нормализира за размера на фонда.
  3. fetch_major_exits() — {"exits", "stopped_managers"}: позиция, била
     >= config.DATAROMA_MAJOR_EXIT_PCT% от портфейла, отсъства напълно
     сега. Explicit РАЗДЕЛЕНО от "мениджърът е спрял да подава 13F"
     (config.DATAROMA_STALE_FILER_DAYS) — двете са различни събития
     (потвърден реален случай: Michael Burry/Scion, фонд закрит 2025,
     последен filing 2025-11-03 — "стопиран", не "продал всичко").

Логика на сигнала: 13F е със закъснение (до 45 дни след тримесечието), затова
не е тайминг инструмент — но КОНВЕРГЕНЦИЯ е силна. Ако акция, която вече
излиза в нашия CANSLIM скринер, е била и купена от superinvestor →
конвергенция маркер в dashboard-а (виж dashboard.html.j2, "in our_tickers").

CUSIP-базирано сравнение между последните 2 13F-HR filings на един CIK
(стабилен идентификатор — имената на емитента могат леко да варират между
подавания). config.DATAROMA_MIN_SHARE_INCREASE_PCT определя "увеличена".

EDGAR CIK-овете са ВЕРИФИЦИРАНИ directamente през data.sec.gov/submissions
(виж config.py FIX бележките — две грешки хванати само по име: грешен CIK и
отдавна-неактивни filing entities). ⚠ ако разширяваш DATAROMA_CIK, потвърди
по СЪЩИЯ начин, не само по textual name match.

Graceful degradation (Секция 7): всяка грешка → празен резултат, брифът
продължава. Пълен EDGAR провал (0 активни мениджъра с данни) → dataroma.com
allact.php fallback само за "moves" (new_positions/major_exits нямат смисъл
без EDGAR $ context).
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


def _truncate_words(s: str, limit: int) -> str:
    """Реже на цяла дума до limit знака — не по средата, ако има space за отрязване."""
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return cut if cut else s[:limit]


# ──────────────────────────────────────────────────────────────────────────
# Fallback: обща активност (dataroma.com allact.php) — без стойност, без
# нужда от per-manager кодове. _manager_buys() (dataroma.com per-manager
# scrape, старата "Слой 1") премахнат 2026-08-17 заедно с config.
# DATAROMA_MANAGERS — беше практически мъртъв код (виж config.py коментара).
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
        # word-boundary anchor (\s|$) — без него " corp" изяжда префикса на
        # " corporation" (naive substring replace: "chevron corporation" →
        # "chevronoration" вместо "chevron")
        s = re.sub(re.escape(w) + r"(?=\s|$)", "", s)
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
                key = _norm(title)
                # един емитент може да има няколко тикъра (common + preferred
                # класове) със СЪЩОТО SEC заглавие (напр. BAC/BAC-PK/BAC-PL/
                # BAC-PS всички = "BANK OF AMERICA CORP /DE/") — предпочитаме
                # "чист" тикър без "-" (обикновено common stock) пред preferred,
                # независимо от реда в SEC JSON-а
                if key not in out or ("-" in out[key] and "-" not in t):
                    out[key] = t
        config.DATA_DIR.mkdir(exist_ok=True)
        _TMAP_CACHE.write_text(json.dumps({"month": dt.date.today().isoformat()[:7],
                                           "map": out}, ensure_ascii=False, default=str))
    except Exception as e:
        print(f"[edgar] ticker map: {e}")
    return out


def _recent_13f_filings(cik: str, n: int = 2) -> list[tuple[str, str]]:
    """
    Връща до n най-нови (accessionNumber, filingDate) 13F-HR за CIK, сортирани
    низходящо по дата (filings[0] = последно, filings[1] = предходно тримесечие).
    Ако мениджърът има само 1 филинг (нов CIK / фонд без история) — връща списък
    с 1 елемент; извикващият код третира липсата на предходно тримесечие gracefully.
    """
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                         timeout=20, headers=_EDGAR_UA)
        r.raise_for_status()
        rec = (r.json() or {}).get("filings", {}).get("recent", {})
        forms = rec.get("form", [])
        accs = rec.get("accessionNumber", [])
        dates = rec.get("filingDate", [])
        filings = [(accs[i], dates[i] if i < len(dates) else "")
                   for i, f in enumerate(forms) if f == "13F-HR"]
        filings.sort(key=lambda x: x[1], reverse=True)
        return filings[:n]
    except Exception as e:
        print(f"[edgar] submissions {cik}: {e}")
        return []


def _info_table(cik: str, accession: str) -> list[dict]:
    """Сваля и парсва information table XML на 13F → [{issuer, value, cusip, shares}]."""
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
                        shares = d.get("sshPrnAmt")
                        if issuer is not None and val is not None:
                            rows.append({"issuer": (issuer.text or "").strip(),
                                         "value": float(re.sub(r"[^\d.]", "", val.text or "0") or 0),
                                         "cusip": (cusip.text or "").strip() if cusip is not None else "",
                                         "shares": float(re.sub(r"[^\d.]", "", shares.text or "0") or 0)
                                                  if shares is not None else 0.0})
                if rows:
                    holdings = rows
                    break
            except Exception:
                continue
    except Exception as e:
        print(f"[edgar] info table {cik}/{accession}: {e}")
    return holdings


def _aggregate_by_cusip(holdings: list[dict]) -> dict[str, dict]:
    """
    Сумира value/shares по CUSIP — един 13F понякога разбива една позиция на
    няколко infoTable реда (sole/shared/none voting authority split), затова
    сумираме преди сравнение, вместо да третираме всеки ред поотделно.
    Редове без CUSIP се пропускат — CUSIP е задължително поле в 13F схемата,
    липсата му означава повреден/нечетим ред, а той е единствената надеждна
    ключ за съпоставка между тримесечия (имената на емитента могат леко да
    се различават между подавания).
    """
    agg: dict[str, dict] = {}
    for h in holdings:
        cusip = h.get("cusip") or ""
        if not cusip:
            continue
        a = agg.setdefault(cusip, {"issuer": h["issuer"], "value": 0.0, "shares": 0.0})
        a["value"] += h.get("value", 0.0)
        a["shares"] += h.get("shares", 0.0)
    return agg


def _manager_snapshot(cik: str, name: str) -> dict:
    """
    FIX 2026-08-17: единствен fetch на последните 2 13F-HR filings за
    мениджъра — консумиран от ТРИТЕ downstream изхода (moves feed,
    high-conviction new positions, major exits), вместо да теглим EDGAR
    3 пъти за same данни. current_agg/prev_agg носят ПЪЛНИЯ {value, shares}
    (не само shares, за разлика от старата _edgar_positions()) — major
    exits логиката се нуждае и от предишните $ стойности, не само дяловете.

    filing_status:
      "no_filings" — CIK без НИТО ЕДИН 13F-HR (пропуска се навсякъде)
      "stopped"    — последният filing е по-стар от config.DATAROMA_STALE_
                     FILER_DAYS (виж config.py защо — Burry/Scion е реалният
                     потвърден случай, фондът закрит 2025, не единична
                     продажба на позиция)
      "active"     — нормален случай
    """
    filings = _recent_13f_filings(cik, n=2)
    if not filings:
        return {"manager": name, "cik": cik, "filing_status": "no_filings"}

    acc, fdate = filings[0]
    days_since = None
    if fdate:
        try:
            days_since = (dt.date.today() - dt.date.fromisoformat(fdate)).days
        except ValueError:
            pass
    filing_status = ("stopped" if (days_since is not None
                                   and days_since > config.DATAROMA_STALE_FILER_DAYS)
                     else "active")
    period = f"13F · {fdate}" if fdate else "13F"

    holdings = _info_table(cik, acc)
    if not holdings:
        return {"manager": name, "cik": cik, "filing_status": filing_status,
                "period": period, "last_filing_date": fdate, "days_since_filing": days_since}
    current_agg = _aggregate_by_cusip(holdings)
    # 13F стойностите след 2023 са в долари; преди — в хиляди. Евристика:
    mx = max((a["value"] for a in current_agg.values()), default=0)
    cur_scale = 1000 if mx and mx < 1e7 else 1
    current_total = sum(a["value"] for a in current_agg.values()) * cur_scale

    prev_agg: dict[str, dict] = {}
    prev_scale = 1
    prev_total = 0.0
    if len(filings) >= 2:
        prev_acc, _ = filings[1]
        prev_holdings = _info_table(cik, prev_acc)
        if prev_holdings:
            prev_agg = _aggregate_by_cusip(prev_holdings)
            pmx = max((a["value"] for a in prev_agg.values()), default=0)
            prev_scale = 1000 if pmx and pmx < 1e7 else 1
            prev_total = sum(a["value"] for a in prev_agg.values()) * prev_scale

    return {
        "manager": name, "cik": cik, "filing_status": filing_status,
        "period": period, "last_filing_date": fdate, "days_since_filing": days_since,
        "current_agg": current_agg, "current_scale": cur_scale, "current_total": current_total,
        "prev_agg": prev_agg, "prev_scale": prev_scale, "prev_total": prev_total,
    }


def _moves_from_snapshot(snap: dict, min_value: float, tmap: dict) -> list[dict]:
    """
    "Нова позиция"/"увеличена" — same логика, каквато преди живееше в
    _edgar_positions(), сега extract-ната да работи върху споделен snapshot.
    """
    rows = []
    current_agg = snap.get("current_agg") or {}
    prev_agg = snap.get("prev_agg") or {}
    cur_scale = snap.get("current_scale", 1)
    for cusip, cur in current_agg.items():
        prev_shares = (prev_agg.get(cusip) or {}).get("shares")
        if prev_shares is None or prev_shares <= 0:
            action = "нова позиция"
        elif cur["shares"] >= prev_shares * (1 + config.DATAROMA_MIN_SHARE_INCREASE_PCT / 100):
            action = "увеличена"
        else:
            continue  # непроменена/намалена — не е "покупка"
        value = cur["value"] * cur_scale
        if value < min_value:
            continue
        ticker = tmap.get(_norm(cur["issuer"]))
        rows.append({
            "ticker": ticker or _truncate_words(cur["issuer"], 24).upper(),
            "company": cur["issuer"], "manager": snap["manager"], "action": action,
            "value": value, "period": snap["period"], "_resolved": bool(ticker),
        })
    return rows


def _new_position_highlights_from_snapshot(snap: dict, tmap: dict) -> list[dict]:
    """
    High-conviction "нова позиция": CUSIP отсъства в предишния filing И
    value >= config.DATAROMA_MIN_NEW_POSITION_PCT% от ТЕКУЩИЯ портфейл на
    мениджъра. Explicit БЕЗ $ праг (config.DATAROMA_MIN_VALUE) — виж
    config.py коментара: % на портфейл вече нормализира за размера на фонда,
    $ праг би изтрил точно small-fund high-conviction сигналите (напр. 2% от
    Pabrai/Dalal Street ~$327M портфейл е ~$6.5M, под $10M).
    """
    out = []
    current_agg = snap.get("current_agg") or {}
    prev_agg = snap.get("prev_agg") or {}
    cur_scale = snap.get("current_scale", 1)
    total = snap.get("current_total") or 0
    if not total:
        return out
    for cusip, cur in current_agg.items():
        if cusip in prev_agg:
            continue  # присъствала в предишния filing — не е "нова"
        value = cur["value"] * cur_scale
        pct = value / total * 100
        if pct < config.DATAROMA_MIN_NEW_POSITION_PCT:
            continue
        ticker = tmap.get(_norm(cur["issuer"]))
        out.append({
            "ticker": ticker or _truncate_words(cur["issuer"], 24).upper(),
            "company": cur["issuer"], "manager": snap["manager"], "value": value,
            "pct_of_portfolio": round(pct, 1), "period": snap["period"],
            "_resolved": bool(ticker),
        })
    return out


def _major_exits_from_snapshot(snap: dict, tmap: dict) -> list[dict]:
    """
    Major exit: CUSIP присъствал в ПРЕДИШНИЯ filing на >= config.
    DATAROMA_MAJOR_EXIT_PCT% от ТОГАВАШНИЯ портфейл, отсъства напълно сега.
    Извикващият код (_fetch_all) вика тази функция САМО за filing_status=
    "active" мениджъри — "stopped" мениджъри НЕ произвеждат exit редове тук
    изобщо (виж config.py DATAROMA_STALE_FILER_DAYS — "фондът закри се" е
    различно събитие от "продадена конкретна позиция").
    """
    out = []
    current_agg = snap.get("current_agg") or {}
    prev_agg = snap.get("prev_agg") or {}
    prev_scale = snap.get("prev_scale", 1)
    prev_total = snap.get("prev_total") or 0
    if not prev_total:
        return out
    for cusip, prev in prev_agg.items():
        if cusip in current_agg:
            continue  # все още държана — не е exit
        value = prev["value"] * prev_scale
        pct = value / prev_total * 100
        if pct < config.DATAROMA_MAJOR_EXIT_PCT:
            continue
        ticker = tmap.get(_norm(prev["issuer"]))
        out.append({
            "ticker": ticker or _truncate_words(prev["issuer"], 24).upper(),
            "company": prev["issuer"], "manager": snap["manager"],
            "prior_value": value, "prior_pct_of_portfolio": round(pct, 1),
            "period": snap["period"], "_resolved": bool(ticker),
        })
    return out


def _dedupe_by_ticker(rows: list[dict]) -> list[dict]:
    """Пази най-голямата стойност на тикър, брои и изброява мениджърите — за конвергенция."""
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
    return list(best.values())


# ══════════════════════════════════════════════════════════════════════════
def _fetch_all(min_value: float) -> dict:
    """
    Единствен fetch pass на ден (кеширан) — връща {"moves", "new_positions",
    "major_exits", "stopped_managers"} общо, всичките производни на same
    manager snapshots (виж _manager_snapshot). ЗАБЕЛЕЖКА: min_value влияе
    само на "moves" ($ праг) — new_positions/major_exits ползват % на
    портфейл, не $ (виж config.py). Кешът е по ДЕН, не по min_value — same
    ограничение съществуваше и в старата _fetch_body() имплементация.
    """
    today = dt.date.today().isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today and cached.get("bundle"):
                return cached["bundle"]
        except Exception:
            pass

    tmap = _ticker_map()
    manager_top: dict[str, list[dict]] = {}
    new_positions: list[dict] = []
    major_exits: list[dict] = []
    stopped_managers: list[dict] = []
    any_active_data = False

    for cik, name in config.DATAROMA_CIK.items():
        snap = _manager_snapshot(cik, name)
        status = snap["filing_status"]
        if status == "no_filings":
            continue
        if status == "stopped":
            stopped_managers.append({
                "manager": name, "last_filing_date": snap.get("last_filing_date"),
                "days_since_filing": snap.get("days_since_filing"),
            })
            continue  # НЕ смятаме moves/exits за спрели мениджъри
        if not snap.get("current_agg"):
            continue

        any_active_data = True
        mgr_rows = _moves_from_snapshot(snap, min_value, tmap)
        manager_top[name] = sorted(mgr_rows, key=lambda r: r.get("value") or 0,
                                   reverse=True)[:config.DATAROMA_TOP_PER_MANAGER]
        new_positions += _new_position_highlights_from_snapshot(snap, tmap)
        major_exits += _major_exits_from_snapshot(snap, tmap)

    pooled = [r for rows in manager_top.values() for r in rows]
    moves = _dedupe_by_ticker(pooled)
    moves = sorted(moves, key=lambda r: (r.get("value") or 0),
                   reverse=True)[:config.DATAROMA_MOVES_DISPLAY_LIMIT]

    # Ако EDGAR напълно е паднал (нито един активен мениджър с данни) —
    # dataroma.com allact.php fallback, само за moves (няма % context за
    # new_positions/major_exits без EDGAR $ данните).
    if not any_active_data:
        fb = _allact_buys()
        if config.DATAROMA_STRICT_VALUE:
            fb = [r for r in fb if r["value"] is not None and r["value"] >= min_value]
        moves = _dedupe_by_ticker(fb)[:config.DATAROMA_MOVES_DISPLAY_LIMIT]

    new_positions.sort(key=lambda r: r.get("pct_of_portfolio", 0), reverse=True)
    major_exits.sort(key=lambda r: r.get("prior_pct_of_portfolio", 0), reverse=True)

    bundle = {"moves": moves, "new_positions": new_positions,
             "major_exits": major_exits, "stopped_managers": stopped_managers}

    if moves or new_positions or major_exits or stopped_managers:
        try:
            config.DATA_DIR.mkdir(exist_ok=True)
            _CACHE.write_text(json.dumps({"date": today, "bundle": bundle},
                                         ensure_ascii=False, indent=1, default=str))
        except Exception as e:
            print(f"[dataroma] cache write: {e}")
    elif _CACHE.exists():
        # всичко падна ДНЕС — последен кеш (по изискване, съществуваше и в старата логика)
        try:
            return json.loads(_CACHE.read_text()).get("bundle", bundle)
        except Exception:
            pass
    return bundle


# ──────────────────────────────────────────────────────────────────────────
# Публично API
# ──────────────────────────────────────────────────────────────────────────
def fetch_superinvestor_buys(min_value: float | None = None) -> list[dict]:
    """
    Връща [{ticker, company, manager(s), action, value, period}] — top-N-per-
    manager selection (config.DATAROMA_TOP_PER_MANAGER), dedup по тикър,
    общ таван config.DATAROMA_MOVES_DISPLAY_LIMIT. Кешира за деня.
    """
    min_value = min_value if min_value is not None else config.DATAROMA_MIN_VALUE
    return _fetch_all(min_value)["moves"]


def fetch_new_position_highlights(min_value: float | None = None) -> list[dict]:
    """High-conviction нови позиции (>= DATAROMA_MIN_NEW_POSITION_PCT% от портфейла)."""
    min_value = min_value if min_value is not None else config.DATAROMA_MIN_VALUE
    return _fetch_all(min_value)["new_positions"]


def fetch_major_exits(min_value: float | None = None) -> dict:
    """
    {"exits": [...], "stopped_managers": [...]} — explicit разделени, за да
    не се бъркат "продадена конкретна позиция" с "фондът е спрял да подава"
    (виж _major_exits_from_snapshot докстринга).
    """
    min_value = min_value if min_value is not None else config.DATAROMA_MIN_VALUE
    bundle = _fetch_all(min_value)
    return {"exits": bundle["major_exits"], "stopped_managers": bundle["stopped_managers"]}


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
    moves = fetch_superinvestor_buys()
    print(f"Superinvestor Moves (top {config.DATAROMA_TOP_PER_MANAGER}/мениджър, "
         f"таван {config.DATAROMA_MOVES_DISPLAY_LIMIT}): {len(moves)}")
    for r in moves:
        v = f"${r['value']:,.0f}" if r.get("value") else "—"
        mgrs = "/".join(r.get("managers", [r.get("manager")]))
        print(f"  {r['ticker']:6} {r['action']:4} {v:>16}  {mgrs} ({r.get('period')})")

    print(f"\nHigh-Conviction New Positions (>= {config.DATAROMA_MIN_NEW_POSITION_PCT}% от портфейл):")
    for r in fetch_new_position_highlights():
        print(f"  {r['ticker']:6} {r['pct_of_portfolio']:>5.1f}%  ${r['value']:,.0f}  {r['manager']}")

    exits = fetch_major_exits()
    print(f"\nMajor Position Exits (>= {config.DATAROMA_MAJOR_EXIT_PCT}% от предишен портфейл):")
    for r in exits["exits"]:
        print(f"  {r['ticker']:6} {r['prior_pct_of_portfolio']:>5.1f}%  {r['manager']}")
    if exits["stopped_managers"]:
        print("\nМениджъри, спрели да подават 13F:")
        for s in exits["stopped_managers"]:
            print(f"  {s['manager']} — последен filing {s['last_filing_date']} "
                 f"({s['days_since_filing']} дни)")
