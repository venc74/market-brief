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
                                              "map": out}, ensure_ascii=False, default=str))
    except Exception as e:
        print(f"[insider] ticker→CIK map: {e}")
    return out


# ──────────────────────────────────────────────────────────────────────────
# Form 4 XML парсър — потвърдена схема с жив пример (виж модулния docstring)
# ──────────────────────────────────────────────────────────────────────────
def _xml_text(el, path: str) -> str:
    node = el.find(path)
    return (node.text or "").strip() if node is not None else ""


def _xml_bool(el, path: str) -> bool | None:
    """
    FIX 2026-09-25: XML булева стойност → True/False/None.

    SEC Form 4 (схема X0609) допуска и двата XML boolean формата. Проверено на
    56 реални документа от 14 емитента:
      aff10b5One  : '0' 33, 'false' 11, '1' 7, 'true' 5
      isOfficer   : '1' 35, 'false' 8, 'true' 4, '0' 1
      isDirector  : '1' 16, '0' 13, 'true' 12, 'false' 1
    Близо една трета са "true"/"false". Дотук и двата парсера проверяваха само
    `== "1"`, така че "true" се четеше като False — директор/офицер губеше
    ролята си, а покупката му отпадаше от Insider Buying, освен при клъстер.

    Липсващо поле или непозната стойност → None ("неизвестно"), НЕ False.
    """
    if el is None:
        return None
    v = _xml_text(el, path).lower()
    if v in ("1", "true"):
        return True
    if v in ("0", "false"):
        return False
    return None


def _is_paired_transfer(buy_leg: dict, legs: list[dict]) -> bool:
    """
    FIX 2026-09-21 (Дефект 2): True ако този P крак има съответстващ S крак в
    СЪЩИЯ filing — същата дата, същия брой акции, същата цена, и кодове
    "disposed" → "acquired". Това не е покупка, а прехвърляне на собственост.

    Потвърденият случай: FOX, MURDOCH LACHLAN K, 2026-09-15 —
      крак 1: S, 149934 акции @ $68.53, A/D=D, пряка собственост,  дял след: 152
      крак 2: P, 149934 акции @ $68.53, A/D=A, "By LKM Family Trust", дял: 1401713
    Прякото държане пада от ~150 хиляди на 152 акции, тръстът получава точно
    толкова. Нула нов капитал. Влизаше в брифа като най-голямата insider
    покупка в цялата история на секцията ($10.27 млн).

    Критерият е СЪЗНАТЕЛНО тесен. Първата интуиция — да се изключи индиректната
    собственост (FOX записът е "I / By LKM Family Trust") — е ИЗМЕРЕНО грешна:
    14 от 48 истински покупки в периода са индиректни, включително втората по
    големина (INTC, $10 млн, "by Family Trust"). Купуването през семеен тръст е
    нормален начин за реална покупка; разграничителят е СДВОЯВАНЕТО, не формата
    на собственост.

    Измерено срещу всички 49 P крака от 01.06.2026 за 16-те тикъра, минавали
    през секцията: 1 попадение (точно FOX), 0 фалшиви. 2% по брой, но 18.8% по
    стойност — явлението е рядко и голямо.
    """
    if buy_leg.get("acquired_disposed") != "A":
        return False
    return any(
        s["code"] == "S"
        and s["date"] == buy_leg["date"]
        and abs(s["shares"] - buy_leg["shares"]) < 0.01
        and abs(s["price"] - buy_leg["price"]) < 0.01
        and s.get("acquired_disposed") == "D"
        for s in legs
    )


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
        # FIX 2026-09-25: _xml_bool приема и "true" — виж там
        is_officer = _xml_bool(rel, "isOfficer") is True
        owners.append({"name": name, "title": title, "is_officer": is_officer})

    # FIX 2026-09-21 (Дефект 2): първо СЕ ЧЕТАТ и двата вида крака, за да може
    # да се засече сдвоен трансфер — виж _is_paired_transfer() по-долу.
    legs = []
    for txn in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _xml_text(txn, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue  # виж docstring за изключените кодове (A/F/G/M и т.н.)
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
        legs.append({
            "code": code, "date": date, "shares": shares, "price": price,
            "value": shares * price,
            "acquired_disposed": _xml_text(txn, "transactionAmounts/"
                                           "transactionAcquiredDisposedCode/value"),
            "ownership": _xml_text(txn, "ownershipNature/directOrIndirectOwnership/value"),
            "nature": _xml_text(txn, "ownershipNature/natureOfOwnership/value"),
        })

    transactions = []
    for leg in legs:
        if leg["code"] != "P":
            continue  # навън се връщат само покупки, точно както преди
        transactions.append({
            "date": leg["date"], "shares": leg["shares"], "price": leg["price"],
            "value": leg["value"],
            "internal_transfer": _is_paired_transfer(leg, legs),
            "ownership": leg["ownership"],
            "nature": leg["nature"],
        })

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
    # FIX 2026-09-21: дедупликация по accession номер.
    #
    # Универсът съдържа компании с два класа акции ПО ДВА ПЪТИ, а двата тикъра
    # сочат към ЕДИН И СЪЩ CIK — потвърдено за трите двойки в текущия универс:
    #   FOX / FOXA   -> 0001754301
    #   GOOG / GOOGL -> 0001652044
    #   NWS / NWSA   -> 0001564708
    # Loop-ът обхожда тикъри, не CIK-ове, затова един и същи filing се теглеше
    # и парсваше по веднъж за всеки тикър. А _parse_form4 връща ticker от
    # issuerTradingSymbol (за FOXA също "FOX"), значи двата резултата попадаха
    # в една група като ИДЕНТИЧНИ редове.
    #
    # Потвърдено в production: FOX/MURDOCH LACHLAN K, 2026-09-15, $10.27 млн се
    # показваше два пъти (общо $20.5 млн) на 17, 18 и 21.09. Един filing в SEC
    # (0001628280-26-062330), не двойно подаване.
    #
    # Не е регресия от commit — латентно от началото на модула; трите двойки
    # просто нямаха квалифицираща покупка досега (FOXA/GOOG/GOOGL/NWS/NWSA не
    # са се появявали в секцията нито веднъж).
    #
    # Дедупликацията е по accession, не по списък от известни CIK-ове:
    # accession номерата са глобално уникални за filing, затова това покрива и
    # бъдещи dual-class двойки без поддръжка на ръчен списък. Пропускането е
    # ПРЕДИ fetch-а — спестява и дублиращата се SEC заявка.
    seen_accessions: set[str] = set()
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
            if accession in seen_accessions:
                continue  # вече обработен под друг тикър на същия CIK
            seen_accessions.add(accession)
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
                    # FIX 2026-09-21 (Дефект 2) — виж _is_paired_transfer()
                    "internal_transfer": txn.get("internal_transfer", False),
                    "ownership": txn.get("ownership", ""),
                    "nature": txn.get("nature", ""),
                })
    return raw, {"ciks_resolved": ciks_resolved, "tickers_with_filings": tickers_with_filings,
                "submissions_fetch_errors": submissions_fetch_errors,
                # видимост за дедупликацията — колко уникални filings реално са
                # обработени; ако dual-class двойка има filings, това число ще е
                # по-малко от сумата на filings-ите по тикър, и това е коректно
                "unique_filings_processed": len(seen_accessions)}


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
    """
    FIX 2026-09-21 (Дефект 2): сдвоените S+P трансфери се ИЗКЛЮЧВАТ от всички
    агрегати — total_value, клъстер броенето и подредбата — но НЕ изчезват:
    маркират се с internal_transfer=True и се показват като отделен, изрично
    етикетиран ред под истинските покупки (виж шаблона).

    Изключването от клъстер броенето е съществено, не козметично: клъстерът е
    "3+ различни инсайдъри купуват за кратко" и прехвърляне между собствени
    сметки не е покупка, значи не бива да помага на тикър да мине прага.
    """
    qualifying = [t for t in raw if t["value"] >= min_value]
    real = [t for t in qualifying if not t.get("internal_transfer")]

    by_ticker: dict[str, list[dict]] = {}
    for t in qualifying:
        by_ticker.setdefault(t["ticker"], []).append(t)

    rows = []
    for ticker, txns in by_ticker.items():
        # клъстерът се смята САМО върху реалните покупки за този тикър
        cluster = _has_cluster([t for t in txns if not t.get("internal_transfer")],
                               cluster_window, cluster_min)
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
                "internal_transfer": bool(t.get("internal_transfer")),
                "ownership": t.get("ownership", ""),
                "nature": t.get("nature", ""),
                "in_screener": False,  # попълва се по-късно в main.py (виж модулния docstring)
            })
    # трансферите НЕ участват в подредбата по стойност — те не са сигнал
    rows.sort(key=lambda r: (r["internal_transfer"], -r["value"]))
    if any(r["internal_transfer"] for r in rows):
        n = sum(1 for r in rows if r["internal_transfer"])
        print(f"[insider] {n} сдвоен(и) S+P трансфер(а) изключен(и) от агрегатите "
              "— показват се отделно като вътрешно преструктуриране")
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
            # FIX 2026-09-21 (Дефект 2): сдвоените трансфери живеят в отделен
            # списък, не в "insiders" — така total_value и cluster остават чисти,
            # а информацията не се губи (виж _is_paired_transfer)
            "transfers": [],
        })
        if r.get("internal_transfer"):
            g["transfers"].append({
                "name": r["insider_name"],
                "title": r["title"],
                "date": r["transaction_date"],
                "shares": r["shares"],
                "value": r["value"],
                "destination": r.get("nature") or ("индиректно държане"
                                                   if r.get("ownership") == "I" else ""),
            })
            continue
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
        g["transfers"].sort(key=lambda x: x["date"], reverse=True)

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
                                     ensure_ascii=False, indent=1, default=str))
    except Exception as e:
        print(f"[insider] cache write: {e}")

    return display_rows


def _parse_form4_all_codes(xml_text: str) -> dict | None:
    """
    Като _parse_form4(), но БЕЗ филтъра `code != "P"` — връща и покупки (P), и
    продажби (S), плюс сигналите, нужни за преценка routine/concerning.

    Отделна функция, НЕ промяна на _parse_form4(): секцията "Insider Buying"
    остава точно каквато е (само покупки, свой праг, своя дедупликация). Тази
    е за watch_monitor, който гледа малък, ръчно избран списък тикъри и има
    нужда от двете посоки. Additive подход, CLAUDE.md т.2.

    aff10b5One: структурният Rule 10b5-1 флаг на SEC — "1"/"true" = продажбата
    е по предварително обявен план (routine), "0"/"false" = извънпланова.
    Елементът съдържа ГОЛА стойност, не вложен <value>. Стои на ниво документ,
    не на транзакция (виж FIX 2026-09-25 по-долу). Липсва → None, което AI-то
    трябва да третира като "неизвестно", не като "0".

    ГРЕШКА В ПЪРВАТА ВЕРСИЯ (поправена 2026-09-25): полето се търсеше в
    транзакцията и се приемаха само "0"/"1". Тестът я пусна, защото беше
    конструиран XML с полето точно там — валидираше предположението, не
    реалността. Тестът вече е срещу реални документи.

    shares_after: sharesOwnedFollowingTransaction — за дял от holdings, без
    който "голяма продажба" е безсмислено число.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    issuer = root.find("issuer")
    if issuer is None:
        return None
    ticker = _xml_text(issuer, "issuerTradingSymbol").upper()
    if not ticker:
        return None

    owners = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        owners.append({
            "name": _xml_text(ro, "reportingOwnerId/rptOwnerName"),
            "title": _xml_text(rel, "officerTitle") if rel is not None else "",
            "is_officer": _xml_bool(rel, "isOfficer") is True,
            "is_director": _xml_bool(rel, "isDirector") is True,
        })

    # FIX 2026-09-25: aff10b5One е на ниво ДОКУМЕНТ (ownershipDocument/aff10b5One)
    # в 56 от 56 проверени реални Form 4 (схема X0609). Мястото, където парсерът
    # търсеше досега (transactionCoding/aff10b5One на всяка транзакция), не се
    # срещна нито веднъж — `planned_10b5_1` беше None за всяка транзакция от
    # пускането на монитора. Потвърдено на BLSH: трите продажби на директора
    # Andrew Bliss 21-23.09 носят aff10b5One=true (планови), а се показваха като
    # "неизв.". Флагът важи за целия документ — един Form 4 = един reporting
    # owner, едно декларирано състояние на 10b5-1 плана.
    doc_planned = _xml_bool(root, "aff10b5One")

    transactions = []
    for txn in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _xml_text(txn, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue  # само реални пазарни покупки/продажби; A/F/G/M са друг клас
        date_s = _xml_text(txn, "transactionDate/value")
        shares_s = _xml_text(txn, "transactionAmounts/transactionShares/value")
        price_s = _xml_text(txn, "transactionAmounts/transactionPricePerShare/value")
        after_s = _xml_text(txn, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
        try:
            shares = float(re.sub(r"[^\d.]", "", shares_s or "0") or 0)
            price = float(re.sub(r"[^\d.]", "", price_s or "0") or 0)
            date = dt.date.fromisoformat(date_s)
        except (ValueError, TypeError):
            continue
        if shares <= 0 or price <= 0:
            continue
        try:
            shares_after = float(re.sub(r"[^\d.]", "", after_s or "") or 0) or None
        except (ValueError, TypeError):
            shares_after = None
        # FIX 2026-09-25: ниво документ първо, транзакцията — само резерва
        planned = (doc_planned if doc_planned is not None
                   else _xml_bool(txn, "transactionCoding/aff10b5One"))
        transactions.append({
            "date": date, "code": code, "shares": shares, "price": price,
            "value": shares * price, "shares_after": shares_after,
            "planned_10b5_1": planned,
            "pct_of_holdings": (round(shares / (shares + shares_after) * 100, 1)
                                if shares_after else None),
        })

    if not transactions:
        return None
    return {"ticker": ticker, "company": _xml_text(issuer, "issuerName"),
            "owners": owners, "transactions": transactions}


def fetch_insider_transactions(tickers: list[str], days: int | None = None) -> dict[str, list[dict]]:
    """
    Form 4 покупки И продажби за ИЗРИЧНО подаден списък тикъри (watch_monitor).

    Различна по предназначение от fetch_insider_buying(): там универсът е
    скрийнърът и се търси сигнал (клъстери, прагове по стойност); тук списъкът
    е малък и ръчен, и се иска ПЪЛНАТА картина за конкретните тикъри — без
    праг по стойност, защото "малка продажба" е част от отговора, не шум.

    Връща {ticker: [транзакция, ...]}, всяка с owner_name/owner_title, сортирани
    по дата низходящо. Тикър без filings → липсва от резултата (извикващият го
    третира като "нищо не се е случило").

    Graceful: провал за един тикър → само той отпада, останалите минават.
    """
    days = days or config.WATCH_INSIDER_LOOKBACK_DAYS
    since = dt.date.today() - dt.timedelta(days=days)
    cikmap = _ticker_cik_map()
    out: dict[str, list[dict]] = {}
    for tk in tickers:
        cik = cikmap.get(tk.upper())
        if not cik:
            print(f"[watch] {tk}: няма CIK в SEC мапинга — пропускам insider проверката")
            continue
        filings = _recent_form4_for_cik(cik, since)
        if not filings:
            continue
        rows = []
        for acc, doc in filings:
            url = _form4_xml_url(cik, acc, doc)
            if not url:
                continue
            try:
                time.sleep(_SLEEP)
                r = requests.get(url, timeout=20, headers=_EDGAR_UA)
                r.raise_for_status()
                parsed = _parse_form4_all_codes(r.text)
            except Exception as e:
                print(f"[watch] {tk} filing {acc}: {e}")
                continue
            if not parsed or parsed["ticker"] != tk.upper():
                continue
            owner = (parsed["owners"] or [{}])[0]
            for t in parsed["transactions"]:
                rows.append({**t, "owner_name": owner.get("name", ""),
                             "owner_title": owner.get("title", ""),
                             "is_officer": owner.get("is_officer", False),
                             "is_director": owner.get("is_director", False)})
        if rows:
            rows.sort(key=lambda r: r["date"], reverse=True)
            out[tk.upper()] = rows
    return out


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
        print("diagnostics:", json.dumps(diag, ensure_ascii=False, default=str))
