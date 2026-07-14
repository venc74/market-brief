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


def _recent_form4_for_cik(cik: str, since: dt.date) -> list[tuple[str, str]] | None:
    """
    Връща [(accessionNumber, primaryDocument), ...] за form=='4' с filingDate
    >= since. None (не []) при провал на самата заявка — различимо от "заявката
    мина успешно, просто няма скорошни Form 4" за diagnostics в кеша (виж
    fetch_insider_buying: submissions_fetch_errors vs tickers_with_filings).
    """
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                         timeout=20, headers=_EDGAR_UA)
        r.raise_for_status()
        rec = (r.json() or {}).get("filings", {}).get("recent", {})
    except Exception as e:
        print(f"[insider] submissions {cik}: {e}")
        return None
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


def _fetch_raw_transactions(universe: list[str], since: dt.date) -> tuple[list[dict], dict]:
    """
    За всеки тикър от universe: намира скорошни Form 4 filings и парсва P-code
    транзакции. Връща (суров списък без филтър по стойност/роля — приложени в
    _build_rows, diagnostics dict) — diagnostics захранва instrumentation-а в
    кеша (виж fetch_insider_buying), за да различим "0 квалифициращи" от "тих
    провал по средата на loop-а" без нужда от GitHub Actions лог достъп.
    Graceful: провал на отделен тикър/filing/XML се пропуска.
    """
    cik_map = _ticker_cik_map()
    raw: list[dict] = []
    ciks_resolved = 0
    tickers_with_filings = 0
    submissions_fetch_errors = 0
    for ticker in universe:
        cik = cik_map.get(ticker)
        if not cik:
            continue
        ciks_resolved += 1
        filings = _recent_form4_for_cik(cik, since)
        time.sleep(_SLEEP)
        if filings is None:
            submissions_fetch_errors += 1
            continue  # заявката се провали — различимо от "0 filings" (виж docstring)
        if filings:
            tickers_with_filings += 1
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
    return raw, {"ciks_resolved": ciks_resolved, "tickers_with_filings": tickers_with_filings,
                "submissions_fetch_errors": submissions_fetch_errors}


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


def _group_by_ticker(rows: list[dict]) -> list[dict]:
    """
    Групира плоски per-транзакция rows (от _build_rows) по тикър — един
    "group" запис вместо N повтарящи се реда за същия тикър, ако няколко
    officers купуват в различни дни (напр. 5 отделни FISV покупки). Аналогично
    на dataroma.superinvestor_map()/_fetch_body() паттърна — агрегацията става
    в самия fetch модул, не в main.py/шаблона, за да останат consumers-ите
    (main.py in_screener loop, render.py, dashboard-а) непроменени/агностични
    към формата.

    "insiders" вътре в групата се сортира по дата НИЗХОДЯЩО (най-новите first)
    — не по стойност — защото cluster сигналът е фундаментално за близост ВЪВ
    ВРЕМЕТО (3+ инсайдъри в 14-дневен прозорец); датовия ред позволява визуално
    потвърждение "да, тези са близо във времето" на пръв поглед, докато
    подредба по стойност би разбъркала хронологията и скрила точно това.
    Групите (тикърите) остават сортирани по total_value низходящо, както преди.
    """
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["ticker"], {
            "ticker": r["ticker"],
            "company": r["company"],
            "total_value": 0.0,
            "cluster": False,
            "in_screener": r.get("in_screener", False),
            "insiders": [],
        })
        g["total_value"] += r["value"]
        g["cluster"] = g["cluster"] or r["cluster"]
        g["insiders"].append({
            "name": r["insider_name"],
            "title": r["title"],
            "date": r["transaction_date"],
            "value": r["value"],
        })

    for g in groups.values():
        g["insiders"].sort(key=lambda x: x["date"], reverse=True)

    return sorted(groups.values(), key=lambda g: g["total_value"], reverse=True)


# ──────────────────────────────────────────────────────────────────────────
# Публично API
# ──────────────────────────────────────────────────────────────────────────
def fetch_insider_buying(min_value: float | None = None) -> list[dict]:
    """
    Връща [{ticker, company, total_value, cluster, in_screener, insiders:
    [{name, title, date, value}, ...]}] — един запис на ТИКЪР (не на
    транзакция), групирано от _group_by_ticker(), за S&P500+NDX100 универса (кеш от
    unusual_options._sp500_ndx_universe()) — само open market покупки (code
    "P") на officers (CEO/CFO/President/COO) над min_value, плюс cluster-
    flagged директорски покупки. Кешира за деня.

    Instrumentation: кешът пази и "diagnostics" — ПИШЕ СЕ ВИНАГИ, дори при
    0 rows, за да разчетем утре причината директно от кеш файла, без нужда от
    GitHub Actions лог достъп:
      - universe_size = 0                          → _sp500_ndx_universe() провал
      - ciks_resolved = 0                          → company_tickers.json/UA проблем в основата
      - ciks_resolved > 0, submissions_fetch_errors > 0 → мрежов/UA проблем на
        конкретни submissions.json заявки (частичен провал)
      - ciks_resolved > 0, submissions_fetch_errors = 0, tickers_with_filings = 0
        → легитимно затишие, никой тикър няма скорошен Form 4
      - tickers_with_filings > 0, raw_transactions_parsed = 0 → filings намерени,
        но 0 P-code транзакции в тях (нормално — повечето Form 4 са sell/grant/exercise)
      - raw_transactions_parsed > 0, qualifying_after_filter = 0 → P-code
        транзакции има, но под INSIDER_MIN_VALUE прага/не officer роля без cluster

    ВАЖНО — две отделни неща в кеша, с различна семантика:
      - "diagnostics" = ВИНАГИ истинският резултат от ДНЕШНИЯ опит, дори 0 —
        никога carry-over, инструментът трябва да е точен всеки ден поотделно.
      - "rows" = fallback-aware display данни: ако днешният fetch е празен,
        пазим последните ИЗВЕСТНИ добри резултати (не []) — и в кеша на диска,
        и във върнатата стойност — за да не се къса fallback веригата след
        първия провален ден (иначе провал ден N+1 презаписва диска с [], и
        провал ден N+2 вече няма откъде да "падне назад").
    """
    min_value = min_value if min_value is not None else config.INSIDER_MIN_VALUE
    today = dt.date.today().isoformat()

    previous_rows: list[dict] = []
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today and cached.get("rows"):
                return cached["rows"]
            previous_rows = cached.get("rows", [])
        except Exception:
            pass

    rows: list[dict] = []
    diagnostics = {
        "universe_size": 0,
        "ciks_resolved": 0,
        "tickers_with_filings": 0,
        "submissions_fetch_errors": 0,
        "raw_transactions_parsed": 0,
        "qualifying_after_filter": 0,
    }
    try:
        universe = _sp500_ndx_universe()
        diagnostics["universe_size"] = len(universe)
        since = dt.date.today() - dt.timedelta(days=_LOOKBACK_DAYS)
        raw, fetch_diag = _fetch_raw_transactions(universe, since)
        diagnostics.update(fetch_diag)
        diagnostics["raw_transactions_parsed"] = len(raw)
        rows = _build_rows(raw, min_value, config.INSIDER_CLUSTER_WINDOW_DAYS,
                           config.INSIDER_CLUSTER_MIN_COUNT)
        diagnostics["qualifying_after_filter"] = len(rows)  # брой ТРАНЗАКЦИИ, преди групиране по тикър
        rows = _group_by_ticker(rows)
    except Exception as e:
        print(f"[insider] fetch failed: {e}")
        rows = []

    # "rows" в кеша = fallback-aware display данни (за dashboard-а) — ако
    # днешният fetch е празен, пазим последните ИЗВЕСТНИ добри резултати, за
    # да не се къса fallback веригата след първия провален ден (провал ден
    # N+1 пише [] върху диска → провал ден N+2 вече няма откъде да "падне
    # назад"). "diagnostics" пази ВИНАГИ истинския резултат от ДНЕШНИЯ опит
    # (rows, не display_rows) — никога не се carry-over-ва, за да остане
    # instrumentation-ът точен инструмент за утрешна диагностика.
    display_rows = rows or previous_rows

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "rows": display_rows, "diagnostics": diagnostics},
                                     ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[insider] cache write: {e}")

    return display_rows


if __name__ == "__main__":
    res = fetch_insider_buying()
    print(f"Insider buying (≥ ${config.INSIDER_MIN_VALUE:,.0f}, P-code само, групирано по тикър): {len(res)}")
    for g in res[:25]:
        tag = " [CLUSTER]" if g["cluster"] else ""
        print(f"  {g['ticker']:6} {g['company']:30} ${g['total_value']:>12,.0f}{tag}")
        for ins in g["insiders"]:
            print(f"      {ins['date']}  {ins['name']:20} {ins['title']:24} ${ins['value']:>12,.0f}")
    if _CACHE.exists():
        diag = json.loads(_CACHE.read_text()).get("diagnostics", {})
        print("diagnostics:", json.dumps(diag, ensure_ascii=False))
