"""
SEC Form 4 — Insider Buying (открита пазарна покупка от officers).

Discovery сигнал, НЕ confirmation: за разлика от CANSLIM скрийнъра (технически
пробив СЕГА), тук следим кой от ръководството купува собствени акции на пазара
— независимо дали тикърът вече е в скрийнъра. Конвергенция (тикър, който е
и в скрийнъра, И тук) се маркира с 'in_screener' — попълва се по-късно в
main.py, по същия паттърн като dataroma.superinvestor_map()/magic_formula.
top_set() (виж enrich.py: _build_crosscheck_sets/_apply_markers).

Технически подход — ЗАЩО per-company submissions API, не market-wide feed:
SEC предлага и real-time Atom feed (browse-edgar?action=getcurrent&type=4),
но той е ограничен твърдо до 100 записа независимо от count= параметъра —
на практика това е ~1-2 часа Form 4 подавания в ЦЕЛИЯ пазар (хиляди
компании), не филтрируеми по тикър/компания. За еднократен дневен run върху
S&P500+NDX100 универс той пропуска почти всичко. Затова, аналогично на
dataroma.py (13F), тук вървим per-company: ticker → CIK (company_tickers.
json) → submissions.json (filings.recent, form=="4") → директно XML на
конкретния filing (submissions.json дава primaryDocument, което сочи към
XSLT-рендернатия HTML view — суровият XML винаги е на същото базово име,
но БЕЗ директорийната xslF345X06/ представка, в корена на accession-а;
потвърдено с жив пример, вижда се basename(primaryDocument)).

Роля на инсайдъра (основен сигнал): officers с officerTitle, съдържащ CEO/
CFO/President/COO (case-insensitive substring, isOfficer==1). Директори
(isDirector, без officer титла) НЕ влизат в основния сигнал сами по себе си.

Cluster buying (бонус сигнал, независим от роля): ако 3+ РАЗЛИЧНИ инсайдъри
(по име, не по filing) купуват в един и същ тикър в прозорец от
config.INSIDER_CLUSTER_WINDOW_DAYS дни — маркираме 'cluster': true. Това е
role-agnostic: директорска покупка, която иначе не влиза в основния сигнал,
СЕ включва в изхода, ако тикърът ѝ е потвърден cluster (интерпретация на
изискването „флагвай отделно, дори ролите да не са CEO/CFO/President" —
без това directors-only клъстери биха останали напълно невидими в изхода).

Transaction code филтър (КРИТИЧНО): само transactionCode == "P" (open market
purchase). "A" (grant), "M" (option exercise), "F" (tax withholding при
vesting), "G" (gift) и др. НЕ са реални пазарни покупки — точно както
необработените 13F holdings преди CUSIP diff поправката в dataroma.py,
биха замърсили сигнала (виж живия пример по-долу: code "F" ~= данъчно
удържане при vesting, изключен коректно).

Праг: config.INSIDER_MIN_VALUE (default $100k) върху shares × price на
самата транзакция — прилага се преди cluster броенето (сравнимо по дух с
config.DATAROMA_MIN_VALUE в dataroma.py).

Lookback: submissions.json връща ПЪЛНАТА история на filings за CIK-а, но ние
парсваме XML само за filings от последните _LOOKBACK_DAYS (30 = 14-дневния
cluster прозорец + буфер за изчакване между transaction date и filing date).

Graceful degradation (Секция 7): всяка грешка на ниво тикър/filing/XML —
пропуска се, не убива целия pipeline. Празен резултат → секцията се крие.
Кеш за деня в config.DATA_DIR (same day-gate паттърн като другите v2 модули).
"""
from __future__ import annotations
import datetime as dt
import json
import re
import time
import xml.etree.ElementTree as ET

import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src.unusual_options import _sp500_ndx_universe

_EDGAR_UA = {"User-Agent": config.EDGAR_UA, "Accept-Encoding": "gzip, deflate"}
_CACHE = config.DATA_DIR / "insider_buying_cache.json"
_CIK_MAP_CACHE = config.DATA_DIR / "insider_ticker_cik_cache.json"

_OFFICER_TITLE_KEYWORDS = ("ceo", "cfo", "president", "coo")
_LOOKBACK_DAYS = config.INSIDER_CLUSTER_WINDOW_DAYS + 16  # ≈30д: cluster прозорец + filing lag буфер
_SLEEP = 0.12  # ~10 заявки/сек SEC fair-use лимит с коректен UA


# ──────────────────────────────────────────────────────────────────────────
# Ticker → CIK (company_tickers.json, кеш месечно — отделен от dataroma._ticker_map(),
# защото там посоката е обратна: нормализирано име → тикър, различна форма на речника)
# ──────────────────────────────────────────────────────────────────────────
def _ticker_cik_map() -> dict[str, str]:
    if _CIK_MAP_CACHE.exists():
        try:
            c = json.loads(_CIK_MAP_CACHE.read_text())
            if c.get("month") == dt.date.today().isoformat()[:7]:
                return c["map"]
        except Exception:
            pass
    out: dict[str, str] = {}
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         timeout=20, headers=_EDGAR_UA)
        r.raise_for_status()
        for v in (r.json() or {}).values():
            t = (v.get("ticker") or "").upper()
            cik = v.get("cik_str")
            if t and cik:
                out[t] = str(cik).zfill(10)
        config.DATA_DIR.mkdir(exist_ok=True)
        _CIK_MAP_CACHE.write_text(json.dumps({"month": dt.date.today().isoformat()[:7],
                                              "map": out}, ensure_ascii=False))
    except Exception as e:
        print(f"[insider] ticker→CIK map: {e}")
    return out


# ──────────────────────────────────────────────────────────────────────────
# Form 4 XML парсър — потвърдена схема с жив пример (виж модулния docstring)
# ──────────────────────────────────────────────────────────────────────────
def _xml_text(el, path: str) -> str:
    node = el.find(path)
    return (node.text or "").strip() if node is not None else ""


def _parse_form4(xml_text: str) -> dict | None:
    """
    Парсва един Form 4 XML → {ticker, company, owners:[{name, title, is_officer}],
    transactions:[{date, shares, price, value}]} — само transactionCode == "P".
    None при невалиден/непарсируем XML (graceful — вика се пропуска filing-а).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    issuer = root.find("issuer")
    if issuer is None:
        return None
    ticker = _xml_text(issuer, "issuerTradingSymbol").upper()
    company = _xml_text(issuer, "issuerName")
    if not ticker:
        return None

    owners = []
    for ro in root.findall("reportingOwner"):
        name = _xml_text(ro, "reportingOwnerId/rptOwnerName")
        rel = ro.find("reportingOwnerRelationship")
        title = _xml_text(rel, "officerTitle") if rel is not None else ""
        is_officer = (_xml_text(rel, "isOfficer") == "1") if rel is not None else False
        owners.append({"name": name, "title": title, "is_officer": is_officer})

    transactions = []
    for txn in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _xml_text(txn, "transactionCoding/transactionCode")
        if code != "P":
            continue  # само open market purchase — виж docstring за изключените кодове
        date_s = _xml_text(txn, "transactionDate/value")
        shares_s = _xml_text(txn, "transactionAmounts/transactionShares/value")
        price_s = _xml_text(txn, "transactionAmounts/transactionPricePerShare/value")
        try:
            shares = float(re.sub(r"[^\d.]", "", shares_s or "0") or 0)
            price = float(re.sub(r"[^\d.]", "", price_s or "0") or 0)
            date = dt.date.fromisoformat(date_s)
        except (ValueError, TypeError):
            continue
        if shares <= 0 or price <= 0:
            continue
        transactions.append({"date": date, "shares": shares, "price": price,
                             "value": shares * price})

    if not transactions:
        return None
    return {"ticker": ticker, "company": company, "owners": owners,
            "transactions": transactions}


# ──────────────────────────────────────────────────────────────────────────
# Per-company Form 4 discovery: CIK → submissions.json → XML на всеки filing
# ──────────────────────────────────────────────────────────────────────────
def _form4_xml_url(cik: str, accession: str, primary_document: str) -> str | None:
    """Суровият XML е в корена на accession-а, basename на primaryDocument (без xslF345X06/)."""
    if not primary_document:
        return None
    xml_name = primary_document.rsplit("/", 1)[-1]
    if not xml_name.lower().endswith(".xml"):
        return None
    cik_int = str(int(cik))
    acc_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{xml_name}"


def _recent_form4_for_cik(cik: str, since: dt.date) -> list[tuple[str, str]]:
    """Връща [(accessionNumber, primaryDocument), ...] за form=='4' с filingDate >= since."""
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                         timeout=20, headers=_EDGAR_UA)
        r.raise_for_status()
        rec = (r.json() or {}).get("filings", {}).get("recent", {})
    except Exception as e:
        print(f"[insider] submissions {cik}: {e}")
        return []
    forms = rec.get("form", [])
    accs = rec.get("accessionNumber", [])
    dates = rec.get("filingDate", [])
    docs = rec.get("primaryDocument", [])
    out = []
    for i, f in enumerate(forms):
        if f != "4":
            continue
        try:
            fdate = dt.date.fromisoformat(dates[i] if i < len(dates) else "")
        except ValueError:
            continue
        if fdate < since:
            continue
        out.append((accs[i], docs[i] if i < len(docs) else ""))
    return out


def _fetch_raw_transactions(universe: list[str], since: dt.date) -> list[dict]:
    """
    За всеки тикър от universe: намира скорошни Form 4 filings и парсва P-code
    транзакции. Връща суров списък (без филтър по стойност/роля — приложени в
    _build_rows). Graceful: провал на отделен тикър/filing/XML се пропуска.
    """
    cik_map = _ticker_cik_map()
    raw: list[dict] = []
    for ticker in universe:
        cik = cik_map.get(ticker)
        if not cik:
            continue
        filings = _recent_form4_for_cik(cik, since)
        time.sleep(_SLEEP)
        for accession, primary_doc in filings:
            url = _form4_xml_url(cik, accession, primary_doc)
            if not url:
                continue
            try:
                xml_text = requests.get(url, timeout=20, headers=_EDGAR_UA).text
            except Exception as e:
                print(f"[insider] form4 fetch {ticker}/{accession}: {e}")
                continue
            time.sleep(_SLEEP)
            parsed = _parse_form4(xml_text)
            if not parsed:
                continue
            is_officer_role = any(
                o["is_officer"] and any(k in o["title"].lower() for k in _OFFICER_TITLE_KEYWORDS)
                for o in parsed["owners"]
            )
            primary_owner = parsed["owners"][0] if parsed["owners"] else {"name": "", "title": ""}
            for txn in parsed["transactions"]:
                raw.append({
                    "ticker": parsed["ticker"] or ticker,
                    "company": parsed["company"],
                    "insider_name": primary_owner["name"],
                    "title": primary_owner["title"],
                    "is_officer_role": is_officer_role,
                    "transaction_date": txn["date"],
                    "shares": txn["shares"],
                    "price": txn["price"],
                    "value": txn["value"],
                })
    return raw


# ──────────────────────────────────────────────────────────────────────────
# Cluster buying: 3+ различни инсайдъри (по име) в един тикър за N дни
# ──────────────────────────────────────────────────────────────────────────
def _has_cluster(txns: list[dict], window_days: int, min_count: int) -> bool:
    anchors = sorted({t["transaction_date"] for t in txns})
    for anchor in anchors:
        window_end = anchor + dt.timedelta(days=window_days - 1)
        insiders = {t["insider_name"] for t in txns
                   if anchor <= t["transaction_date"] <= window_end}
        if len(insiders) >= min_count:
            return True
    return False


def _build_rows(raw: list[dict], min_value: float,
                cluster_window: int, cluster_min: int) -> list[dict]:
    qualifying = [t for t in raw if t["value"] >= min_value]

    by_ticker: dict[str, list[dict]] = {}
    for t in qualifying:
        by_ticker.setdefault(t["ticker"], []).append(t)

    rows = []
    for ticker, txns in by_ticker.items():
        cluster = _has_cluster(txns, cluster_window, cluster_min)
        for t in txns:
            # основен сигнал = officer роля; директорска покупка влиза само
            # ако тикърът е потвърден cluster (role-agnostic бонус сигнал)
            if not (t["is_officer_role"] or cluster):
                continue
            rows.append({
                "ticker": ticker,
                "company": t["company"],
                "insider_name": t["insider_name"],
                "title": t["title"],
                "transaction_date": t["transaction_date"].isoformat(),
                "shares": t["shares"],
                "price": t["price"],
                "value": t["value"],
                "cluster": cluster,
                "in_screener": False,  # попълва се по-късно в main.py (виж модулния docstring)
            })
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows


# ──────────────────────────────────────────────────────────────────────────
# Публично API
# ──────────────────────────────────────────────────────────────────────────
def fetch_insider_buying(min_value: float | None = None) -> list[dict]:
    """
    Връща [{ticker, company, insider_name, title, transaction_date, shares,
    price, value, cluster, in_screener}] за S&P500+NDX100 универса (кеш от
    unusual_options._sp500_ndx_universe()) — само open market покупки (code
    "P") на officers (CEO/CFO/President/COO) над min_value, плюс cluster-
    flagged директорски покупки. Кешира за деня.
    """
    min_value = min_value if min_value is not None else config.INSIDER_MIN_VALUE
    today = dt.date.today().isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today and cached.get("rows"):
                return cached["rows"]
        except Exception:
            pass

    rows: list[dict] = []
    try:
        universe = _sp500_ndx_universe()
        since = dt.date.today() - dt.timedelta(days=_LOOKBACK_DAYS)
        raw = _fetch_raw_transactions(universe, since)
        rows = _build_rows(raw, min_value, config.INSIDER_CLUSTER_WINDOW_DAYS,
                           config.INSIDER_CLUSTER_MIN_COUNT)
    except Exception as e:
        print(f"[insider] fetch failed: {e}")
        rows = []

    if not rows and _CACHE.exists():
        try:
            return json.loads(_CACHE.read_text()).get("rows", [])
        except Exception:
            return []

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "rows": rows},
                                     ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[insider] cache write: {e}")
    return rows


if __name__ == "__main__":
    res = fetch_insider_buying()
    print(f"Insider buying (≥ ${config.INSIDER_MIN_VALUE:,.0f}, P-code само): {len(res)}")
    for r in res[:25]:
        tag = " [CLUSTER]" if r["cluster"] else ""
        print(f"  {r['ticker']:6} {r['insider_name']:20} {r['title']:24} "
             f"${r['value']:>12,.0f}  {r['transaction_date']}{tag}")
