"""
Предупреждение за ПРЕДСТОЯЩО отделяне (spin-off) от EDGAR 8-K — само за НАШИТЕ тикъри (13.10.2026, решение на Венци след измерването).

Защо: Yahoo записва отделянето като "сплит" с оценъчен коефициент чак в деня на събитието (CTVA/Vylor 01.10.2026 = 6.665), а дотогава картата и книгите не знаят нищо. Компанията обявява датата
на запис, датата на разпределение и съотношението в 8-K (точки 8.01 / 7.01) седмици по-рано.

Измерено на 13.10.2026 (РЕАЛНИ 8-K от EDGAR, 2024-10 … 2026-10; 1 149 документа):
  • 13-те компании с отделяне 2025–2026 (14 събития): засечени 11; медиана 13 сесии предварително (CTVA 12, MIDD 10, SPGI 27, HON 15 и 21, FDX 12, CMCSA 22, DD 13, WDC 15, LEN 6; FTV — чак в деня,
    защото обявяването не беше 8-K с 8.01/7.01); пропуснати BDX (съотношението определено при приключването), FNF и J (съотношението обявено СЛЕД датата на запис);
  • контролна група от 30 големи компании без отделяне: 0 фалшиви попадения в 248 документа; в документите на 13-те компании — 0 попадения извън техните отделяния.

Детекторът (detect) иска и четирите: контекст на отделяне, дата на запис (по близост до "record date" / "of record"), дата на разпределение след записа ("expected to be completed/effective",
"distribution date", "take place", "on or about", началото на "regular-way" търговията на новата компания; БЕЗ изреченията за "when-issued" и двата пазара) и съотношение (вкл. дробни:
"one-third (1/3) of one share … for each share"). Съотношението е задължително — така обикновените дивиденти ("payable … to shareholders of record") не дават попадение.

21.10.2026 (етап 3б): и ЦЕЛ НА ПРИДОБИВАНЕ — само маркер върху картата (detect_merger / LAST_MERGERS / annotate_mergers, виж секцията по-долу и config.MERGER_LOOKBACK_DAYS).

Мрежа: config.EDGAR_UA (тайната в CI, същата като на 13F/insider модулите; без нов credential), пауза 0.12 s. Кеш по документ (data/spinoff_8k_cache.json — прочетен 8-K не се чете
повторно). Всяко засичане отива в дневник (data/spinoff_log.json) за проверка на живо след месец. Graceful: провал → без предупреждения, LAST_DIAG ok=False → банер.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import time

import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

LAST_DIAG: dict = {}
LAST_MERGERS: dict[str, dict] = {}                 # 21.10.2026: тикър → {buyer, announced, filing_date, accession} — висяща сделка, в която тикърът е ЦЕЛТА (маркер върху картата)
_SLEEP = 0.12

# ──────────────────────────────────────────────────────────────────────────
# Детекторът (същият като в измерването от 13.10)
# ──────────────────────────────────────────────────────────────────────────
MON = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = re.compile(rf"\b({MON})\s+(\d{{1,2}}),\s+(\d{{4}})\b")
SPIN = re.compile(r"spin-?off|separation|distribution of (?:all|approximately|\d)", re.I)
NUM = r"one|two|three|four|five|six|seven|eight|nine|ten|twenty-five|hundred|\d+"
RATIO = re.compile(r"\b(?P<num>" + NUM + r"|\d*\.\d+|\d+/\d+|one-(?:half|third|quarter|fourth|fifth))\s*(?:\(\s*\d+/\d+\s*\)\s*)?(?:of\s+(?:a|one)\s+)?shares?\s+of\s+"
                   r"(?P<new>[A-Z][\w.,&'’ -]{1,70}?)\s+(?:(?:class [ab]\s+(?:or class [ab]\s+)?)?common stock\s+)?(?:\([^)]{0,80}\)\s+)?for\s+(?:every|each)\s+"
                   r"(?:(?P<n>" + NUM + r")\s+)?shares?\s+of", re.I)
TICK = re.compile(r"(?:under the (?:ticker |trading )?symbol|ticker symbol)\s+[“\"']\s*([A-Z]{1,5})(\s+WI)?\s*[”\"']")
REC_NEAR = [re.compile(rf"(\b(?:{MON})\s+\d{{1,2}},\s+\d{{4}})[^.;]{{0,70}}?(?:the\s+)?[“\"(]*\s*record date", re.I),
            re.compile(rf"record date[^.;]{{0,60}}?(\b(?:{MON})\s+\d{{1,2}},\s+\d{{4}})", re.I),
            re.compile(rf"of record[^.;]{{0,60}}?(\b(?:{MON})\s+\d{{1,2}},\s+\d{{4}})", re.I)]
DIST_KEY = re.compile(r"distribut|spin-?off|separation", re.I)
DIST_VERB = re.compile(r"expected|effective|on or about|will be|payable|distribution date|scheduled|completed|take place|occur", re.I)
DIST_SKIP = re.compile(r"when[- ]issued|ex-distribution|two markets|two ways to trade|record date|of record|\bsell", re.I)
DIST_STRONG = re.compile(r"distribution date|expected to be (?:completed|effective|made)|take place|on or about|is expected to occur", re.I)
REGWAY = re.compile(r"regular[- ]way\W{0,3}\s*trading|begin\s+\W?regular[- ]way", re.I)
_SENT = re.compile(r"(?<!a\.m\.)(?<!p\.m\.)(?<!Inc\.)(?<!Corp\.)(?<!No\.)(?<!U\.S\.)(?<=[.;])\s+")
_WORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty-five": 25, "hundred": 100,
         "one-half": "1/2", "one-third": "1/3", "one-quarter": "1/4", "one-fourth": "1/4", "one-fifth": "1/5"}


def text_of(h: str) -> str:
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))


def _todate(s: str) -> dt.date:
    return dt.datetime.strptime(re.sub(r"\s+", " ", s.replace(",", "")), "%B %d %Y").date()


def _num(x: str | None):
    if x is None:
        return 1
    x = x.lower()
    return _WORD.get(x, x)


def ratio_text(num: str | None, n: str | None) -> str:
    """"one", None → "1:1"; "one", "two" → "1 за 2"; "one-third", None → "1/3 за 1"; "0.060835", None → "0.060835 за 1"."""
    a, b = _num(num), _num(n)
    return "1:1" if (a, b) == (1, 1) else f"{a} за {b}"


def detect(text: str, parent: str | None = None) -> dict | None:
    """{record, distribution, ratio, new, ticker} или None — нужни са контекст на отделяне, дата на запис, дата на разпределение (след записа) и съотношение. Чиста функция."""
    if not text or not SPIN.search(text):
        return None
    rec = None
    for rx in REC_NEAR:
        mm = rx.search(text)
        if mm:
            rec = _todate(mm.group(1))
            break
    if rec is None:
        return None
    cands = []
    for s in _SENT.split(text):
        if REGWAY.search(s) and not DIST_SKIP.search(s):
            cands += [(1, d) for d in (_todate(mm.group(0)) for mm in DATE.finditer(s)) if d > rec]
        if DIST_KEY.search(s) and DIST_VERB.search(s) and not DIST_SKIP.search(s):
            cands += [(0 if DIST_STRONG.search(s) else 1, d) for d in (_todate(mm.group(0)) for mm in DATE.finditer(s)) if d > rec]
    rm = RATIO.search(text)
    if not (cands and rm):
        return None
    tick = None
    for mm in TICK.finditer(text):
        if not mm.group(2) and mm.group(1) != parent and "existing" not in text[max(0, mm.start() - 40):mm.start()]:
            tick = mm.group(1)
            break
    new = re.sub(r"\s+(?:Class [AB].*|common stock.*)$", "", rm.group("new").strip(), flags=re.I)[:60]
    return {"record": rec.isoformat(), "distribution": sorted(cands)[0][1].isoformat(), "ratio": ratio_text(rm.group("num"), rm.group("n")),
            "new": new, "new_ticker": tick}


def _dm(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}"


def warning_text(hit: dict) -> str:
    """Текстът на картата (предложението от 13.10, приет); тикърът на новата компания — ако е намерен."""
    who = hit.get("new") or "нова компания"
    val = hit.get("new_ticker") or who
    return (f"⚠ Предстои отделяне на {who} ({hit['ratio']}) на {_dm(hit['distribution'])}, запис {_dm(hit['record'])} — от {_dm(hit['distribution'])} историята ще е оценка; "
            f"цената пада с ~стойността на {val} (не е загуба); стопът в $ спира да важи; книгите не записват нов вход от датата на запис до отделянето")


def note_text(hit: dict) -> str:
    """Бележката върху отворен запис в книгите (решението от 13.10): само информация — ръчният преглед остава от деня на отделянето."""
    return f"предстои отделяне на {_dm(hit['distribution'])} (запис {_dm(hit['record'])})"


# ──────────────────────────────────────────────────────────────────────────
# 21.10.2026 (етап 3б, решение на Венци): ЦЕЛ НА ПРИДОБИВАНЕ — само маркер върху картата, картата остава.
# Измерено на 21.10 (РЕАЛНИ 8-K от EDGAR, т. 1.01, 903-те тикъра от универса, 10.2025–10.2026): в 8-К на КУПУВАЧА "the Company" е целта по дефиницията на договора
# (FOX за Roku, VRTX за Crinetics, JAZZ за Actio …) — затова маркер има само ако "the Company" (или името в изречението) е самият подател.
# ──────────────────────────────────────────────────────────────────────────
_LEGAL = re.compile(r"\b(?:the|inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|lp|l\.p|holdings?|group|n\.v|s\.a|se|ag|nv|sa|de)\b\.?", re.I)
_SUFFIX = r"(?:Inc\.?|LLC|L\.L\.C\.|L\.P\.|LP|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|SE|AG|Corp\.?|Co\.|Incorporated|Corporation)"
_NAME = r"[A-Z][\w&'’.-]*(?: (?:[A-Z][\w&'’.-]*|of|&))*(?:,? " + _SUFFIX + r")?(?![\w&'’-])"
_DEFN = re.compile(r"(" + _NAME + r")(?:,? (?:a|an) [^()“.]{0,140}?)?\s*\((\s*(?:the\s+)?“[^()]{1,90}?)\)")      # (the “Company”) / (“Fox” or “Parent”)
_TERM = re.compile(r"“\s*([A-Z][\w .&'-]{0,30}?)\s*”")
_SUBJ = r"(?P<subj>the Company|" + _NAME + r")"
_BUYER = r"(?P<buyer>the Parent|" + _NAME + r")"
_MERGER_RX = [
    re.compile(r"merge[sd]? with and into " + _SUBJ + r"[^.]{0,260}?(?:surviv\w*|continu\w*)[^.]{0,220}?wholly[- ]owned (?:direct |indirect )?subsidiary of " + _BUYER),
    re.compile(_SUBJ + r" (?:will|would) (?:become|be|continue as|survive as) (?:a |an )?(?:direct |indirect )?wholly[- ]owned (?:direct |indirect )?subsidiary of " + _BUYER),
    re.compile(_SUBJ + r",? (?:surviving|continuing)[^.]{0,120}? as (?:a |an )?(?:direct |indirect )?wholly[- ]owned (?:direct |indirect )?subsidiary of " + _BUYER),
    re.compile(r"pursuant to which " + _SUBJ + r" (?:is|will be) (?:to be )?acquired by (?P<buyer2>[^.;(]{3,140})"),
    re.compile(_BUYER + r" will acquire (?:of )?all (?:of )?the (?:issued and )?outstanding (?:common )?(?:shares|stock)(?:[^.]|\.\d){0,140}? of " + _SUBJ),
    # AES 02.03.2026: "Merger Sub will merge with and into the Company …, with the Company continuing as the surviving corporation" — без "wholly owned subsidiary of"; купувачът е "Parent"
    re.compile(r"Merger Sub(?:sidiary)?(?: \d| I+)? will (?:be )?merged? with and into " + _SUBJ + r"[^.]{0,160}?(?:surviving|continuing) as the surviving (?:corporation|company|entity)"),
]
_PARENT_TERMS = ("Parent", "Buyer", "Purchaser", "Acquiror", "Acquirer")
_MERGER_CTX = re.compile(r"Plan of Merger|Merger Agreement|Business Combination Agreement|Arrangement Agreement|Plan of Reorganization", re.I)


def _canon(name: str | None) -> list[str]:
    n = _LEGAL.sub(" ", re.sub(r"[,’'.]", " ", (name or "").replace("-", " ")))
    return [w for w in re.findall(r"[a-z0-9&]+", n.lower()) if w]


def same_company(a: str | None, filer: str | None) -> bool:
    """Името в текста е подателят: първата значима дума съвпада (TXNM ↔ "TXNM ENERGY INC", "Silicon Laboratories Inc." ↔ "SILICON LABORATORIES INC.", "Bio-Techne" ↔ "BIO-TECHNE Corp"). Чиста функция."""
    x, y = _canon(a), _canon(filer)
    return bool(x and y) and (x[0] == y[0] or "".join(x) == "".join(y)[:len("".join(x))])


def _definitions(t: str) -> dict[str, str]:
    """
    {дефиниран термин: име} от "(the “Company”)" / "(“Fox” or “Parent”)". Име след "under the laws of" е юрисдикция, не дефиниция (AXTA: "… of the Netherlands (“AkzoNobel”)" → терминът
    остава "AkzoNobel"); еднословно име след запетая се допълва с веригата преди него (TECH: "Merck KGaA, Darmstadt, Germany (“Parent”)"), но не през "the …" ("the Company, Fox Corporation").
    """
    defs: dict[str, str] = {}
    for m in _DEFN.finditer(t):
        k, name = m.start(1), m.group(1).strip(" ,")
        if re.search(r"laws of (?:the )?$", t[max(0, k - 20):k]):
            continue
        if " " not in name:
            while True:
                head = t[max(0, k - 80):k]
                mm = re.search(r"(" + _NAME + r"), $", head)
                if not mm:
                    break
                start = k - len(head) + mm.start(1)
                if re.search(r"\bthe $", t[max(0, start - 4):start]):
                    break
                k = start
            name = t[k:m.end(1)].strip(" ,")
        for term in _TERM.findall(m.group(2)):
            defs.setdefault(term.strip(), name)
    return defs


def detect_merger(text: str, filer: str, filed: str | None = None) -> dict | None:
    """
    {buyer, announced} ако 8-K казва, че ПОДАТЕЛЯТ (filer — името от EDGAR) става дъщерна на купувача / е придобит; иначе None (вкл. 8-K на купувача). Чиста функция.
    "the Company" се разрешава по дефиницията в документа; купувачът — по дефиницията на "Parent" / "Buyer" / "Purchaser"; датата на обявяване — първата дата в т. 1.01, иначе filed.
    """
    if not text or not _MERGER_CTX.search(text):
        return None
    t = re.sub(r"“\s+", "“", re.sub(r"\s+”", "”", text))
    defs = _definitions(t)
    for rx in _MERGER_RX:
        for m in rx.finditer(t):
            subj = m.group("subj")
            subj_name = defs.get("Company") if subj == "the Company" else defs.get(subj, subj)
            if not same_company(subj_name, filer):
                continue
            buyer = (m.groupdict().get("buyer") or m.groupdict().get("buyer2") or next((t2 for t2 in _PARENT_TERMS if t2 in defs), "")).strip(" ,")
            buyer = re.split(r"\.\s+(?=[A-Z])", re.sub(r"^the\s+", "", buyer))[0].strip(" ,.") if not re.search(_SUFFIX + r"$", buyer) else re.sub(r"^the\s+", "", buyer)
            buyer = defs.get(buyer, buyer)
            buyer = re.split(r"\s+(?:\(|pursuant|which|subject|and its|for \$)", buyer)[0].strip(" ,")[:90]
            if not buyer or same_company(buyer, filer) or buyer.lower() in ("parent", "merger sub"):
                continue
            item = t[t.find("Item 1.01"):] if "Item 1.01" in t else t
            d = DATE.search(item[:1500])
            announced = _todate(d.group(0)).isoformat() if d else filed
            return {"buyer": buyer, "announced": announced or filed}
    return None


def merger_text(hit: dict) -> str:
    """Маркерът на картата (решението от 21.10): „цел на придобиване (купувач, дата на обявяване)“; картата остава."""
    a = dt.date.fromisoformat(hit["announced"])
    return f"⚠ Цел на придобиване ({hit['buyer']}, обявено {a.day:02d}.{a.month:02d}.{a.year}) — цената следва условията на сделката"


def merger_state(sub: dict, announced: str) -> str | None:
    """None — сделката виси; "closed" (8-K т. 5.01 или Form 25 / 15 след обявяването) или None. Прекратяването (1.02) се проверява отделно по текста. Чиста функция."""
    r = (sub or {}).get("filings", {}).get("recent", {})
    for i, f in enumerate(r.get("form", [])):
        d = r["filingDate"][i]
        if d <= announced:
            continue
        items = (r.get("items") or [""] * len(r["form"]))[i] or ""
        if (f in ("8-K", "8-K/A") and "5.01" in items) or f in ("25-NSE", "25", "15-12B", "15-12G", "15-15D"):
            return "closed"
    return None


def recent_8k_101(sub: dict, since: str, until: str, items_any=("1.01",)) -> list[dict]:
    """8-K / 8-K/A с някоя от точките items_any, подадени в [since, until]. Чиста функция."""
    r = (sub or {}).get("filings", {}).get("recent", {})
    out = []
    for i, f in enumerate(r.get("form", [])):
        if f not in ("8-K", "8-K/A"):
            continue
        d = r["filingDate"][i]
        items = (r.get("items") or [""] * len(r["form"]))[i] or ""
        if since <= d <= until and any(x in items for x in items_any):
            out.append({"date": d, "acc": r["accessionNumber"][i], "doc": r["primaryDocument"][i], "items": items})
    return out


# ──────────────────────────────────────────────────────────────────────────
# EDGAR
# ──────────────────────────────────────────────────────────────────────────
def _http_get(url: str) -> str:
    last = None
    for attempt in range(3):
        time.sleep(_SLEEP + attempt * 3)
        try:
            r = requests.get(url, headers={"User-Agent": config.EDGAR_UA, "Accept-Encoding": "gzip, deflate"}, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last = e
            if getattr(e, "response", None) is not None and e.response.status_code in (403, 404):
                break
    raise last


def recent_8k(sub: dict, since: str, until: str) -> list[dict]:
    """8-K / 8-K/A с точки 8.01 или 7.01, подадени в [since, until], от submissions JSON. Чиста функция."""
    r = (sub or {}).get("filings", {}).get("recent", {})
    out = []
    for i, f in enumerate(r.get("form", [])):
        if f not in ("8-K", "8-K/A"):
            continue
        d = r["filingDate"][i]
        items = (r.get("items") or [""] * len(r["form"]))[i] or ""
        if since <= d <= until and ("8.01" in items or "7.01" in items):
            out.append({"date": d, "acc": r["accessionNumber"][i], "doc": r["primaryDocument"][i], "items": items})
    return out


def _scan(cik: str, f: dict, parent: str, get) -> dict | None:
    """Основният документ, после приложенията ex-99 (index.json) — първото с пълно засичане."""
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['acc'].replace('-', '')}"
    hit = detect(text_of(get(f"{base}/{f['doc']}")), parent)
    if hit:
        return {**hit, "where": "main"}
    idx = json.loads(get(f"{base}/index.json"))
    for it in idx.get("directory", {}).get("item", []):
        n = it.get("name", "")
        if re.search(r"ex-?99|exhibit99|dex99", n, re.I) and n.lower().endswith((".htm", ".html", ".txt")):
            hit = detect(text_of(get(f"{base}/{n}")), parent)
            if hit:
                return {**hit, "where": n}
    return None


def _load(path: pathlib.Path, empty):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty
    except Exception as e:
        print(f"[spinoff] {path.name} нечетим ({type(e).__name__}) — започвам наново")
        return empty


def _merger_scan(t: str, cik, sub: dict, cache: dict, today: dt.date, get) -> dict | None:
    """
    21.10.2026: висяща сделка, в която тикърът е целта: най-ранното засичане в 8-K с т. 1.01 от последните config.MERGER_LOOKBACK_DAYS дни; без засичане, приключила (merger_state) или
    прекратена (по-късен 8-K с т. 1.02, в който се прекратява договорът за сливане) → None. Документите — в cache["merger_docs"] по accession (прочетен 8-K не се чете повторно).
    """
    filer = (sub or {}).get("name") or t
    since = (today - dt.timedelta(days=config.MERGER_LOOKBACK_DAYS)).isoformat()
    base = lambda f: f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['acc'].replace('-', '')}/{f['doc']}"
    first = None
    for f in sorted(recent_8k_101(sub, since, today.isoformat()), key=lambda f: f["date"]):
        c = cache["merger_docs"].get(f["acc"])
        if c is None:
            c = cache["merger_docs"][f["acc"]] = {"ticker": t, "date": f["date"], "hit": detect_merger(text_of(get(base(f))), filer, f["date"])}
            LAST_DIAG["merger_fetched"] = LAST_DIAG.get("merger_fetched", 0) + 1
        if c.get("hit") and first is None:
            first = {**c["hit"], "filing_date": f["date"], "accession": f["acc"]}
    if not first or merger_state(sub, first["filing_date"]) == "closed":
        return None
    for f in recent_8k_101(sub, first["filing_date"], today.isoformat(), items_any=("1.02",)):
        if f["date"] <= first["filing_date"]:
            continue
        key = f["acc"] + "#1.02"
        c = cache["merger_docs"].get(key)
        if c is None:
            txt = text_of(get(base(f)))
            c = cache["merger_docs"][key] = {"ticker": t, "date": f["date"], "terminated": bool(_MERGER_CTX.search(txt) and re.search(r"terminat", txt, re.I))}
            LAST_DIAG["merger_fetched"] = LAST_DIAG.get("merger_fetched", 0) + 1
        if c.get("terminated"):
            return None
    return first


def check(tickers, today=None, get=None, cik_map=None, budget_sec: float | None = None, merger_tickers=None, subs: dict | None = None) -> dict[str, dict]:
    """
    {тикър: засичане} за тикърите с АКТИВНО предупреждение: 8-K в последните config.SPINOFF_LOOKBACK_DAYS дни с пълно засичане и дата на разпределение ≥ днес (най-новият такъв 8-K).
    get(url) -> текст и cik_map {тикър: CIK} се подменят в тестовете. Записва кеша по документ и дневника. budget_sec: след него останалите тикъри (по реда на подаване) не се
    проверяват — LAST_DIAG["unchecked"]. Не вдига: провал → {} и LAST_DIAG ok=False.
    merger_tickers (21.10.2026): за тях се търси и висяща сделка, в която тикърът е ЦЕЛТА → LAST_MERGERS (маркер само върху картите — main подава тикърите на картите).
    subs (26.10.2026, етап 4б, т. 1): речник {url: списъкът с подавания}, споделен между двете проверки на run-а (кандидатите преди класификацията и картите след нея) —
    списъкът на един тикър се тегли веднъж.
    """
    LAST_DIAG.clear()
    LAST_DIAG.update(ok=True, requested=0, checked=0, filings=0, fetched=0, active=[], logged=0, errors=[], unchecked=[], error=None, mergers=[], merger_fetched=0)
    LAST_MERGERS.clear()
    merger_tickers = set(merger_tickers or ()) if config.ENABLE_MERGER_MARKER else set()
    today = today if isinstance(today, dt.date) else dt.date.fromisoformat(str(today or dt.date.today())[:10])
    tickers = list(dict.fromkeys(t for t in (tickers or []) if t))          # редът е приоритетът (карти първо) — при изчерпан бюджет остават последните
    LAST_DIAG["requested"] = len(tickers)
    if not tickers or not config.ENABLE_SPINOFF_WATCH:
        return {}
    get = get or _http_get
    try:
        if cik_map is None:
            from src import insider_buying
            cik_map = insider_buying._ticker_cik_map()
        if not cik_map:
            raise RuntimeError("няма CIK мапинг от SEC (company_tickers.json / User-Agent)")
        cache_p, log_p = pathlib.Path(config.DATA_DIR) / config.SPINOFF_CACHE_NAME, pathlib.Path(config.DATA_DIR) / config.SPINOFF_LOG_NAME
        cache = _load(cache_p, {"version": 1, "docs": {}})
        cache.setdefault("merger_docs", {})
        log = _load(log_p, {"version": 1, "entries": []})
        since = (today - dt.timedelta(days=config.SPINOFF_LOOKBACK_DAYS)).isoformat()
        active: dict[str, dict] = {}
        seen_log = {(e.get("ticker"), e.get("accession")) for e in log["entries"]}
        t0 = time.monotonic()
        for i, t in enumerate(tickers):
            if budget_sec is not None and time.monotonic() - t0 > budget_sec:
                LAST_DIAG["unchecked"] += tickers[i:]                # 19.10.2026: + тикърите без CIK отпреди
                print(f"[spinoff] бюджетът от {budget_sec} s изтече — непроверени {len(tickers) - i}: {', '.join(tickers[i:i + 20])}")
                break
            cik = cik_map.get(t)
            if not cik:
                LAST_DIAG["unchecked"].append(t)          # 19.10.2026 (т. 12): без CIK в EDGAR — непроверен (до 19.10 тихо прескачане: checked < requested без банер)
                continue
            LAST_DIAG["checked"] += 1
            try:
                url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
                sub = subs[url] if subs is not None and url in subs else json.loads(get(url))
                if subs is not None:
                    subs[url] = sub
                fs = recent_8k(sub, since, today.isoformat())
            except Exception as e:
                LAST_DIAG["errors"].append({"ticker": t, "error": f"submissions: {type(e).__name__}"})
                continue
            if t in merger_tickers:
                try:
                    mh = _merger_scan(t, cik, sub, cache, today, get)
                    if mh:
                        LAST_MERGERS[t] = mh
                except Exception as e:
                    LAST_DIAG["errors"].append({"ticker": t, "error": f"merger: {type(e).__name__}"})
            LAST_DIAG["filings"] += len(fs)
            for f in fs:
                c = cache["docs"].get(f["acc"])
                if c is None:
                    try:
                        hit = _scan(cik, f, t, get)
                    except Exception as e:
                        LAST_DIAG["errors"].append({"ticker": t, "accession": f["acc"], "error": type(e).__name__})
                        continue
                    LAST_DIAG["fetched"] += 1
                    c = cache["docs"][f["acc"]] = {"ticker": t, "date": f["date"], "hit": hit}
                hit = c.get("hit")
                if not hit:
                    continue
                if (t, f["acc"]) not in seen_log:
                    log["entries"].append({"ticker": t, "filing_date": f["date"], "accession": f["acc"], "record": hit["record"], "distribution": hit["distribution"],
                                           "ratio": hit["ratio"], "new": hit.get("new"), "new_ticker": hit.get("new_ticker"), "where": hit.get("where"),
                                           "first_seen": today.isoformat()})
                    seen_log.add((t, f["acc"]))
                    LAST_DIAG["logged"] += 1
                if hit["distribution"] >= today.isoformat() and (t not in active or f["date"] > active[t]["filing_date"]):
                    active[t] = {**hit, "filing_date": f["date"], "accession": f["acc"]}
        cache["docs"] = {k: v for k, v in cache["docs"].items() if v.get("date", "") >= since}      # кешът не расте: подаване извън прозореца вече не се търси
        msince = (today - dt.timedelta(days=config.MERGER_LOOKBACK_DAYS)).isoformat()
        cache["merger_docs"] = {k: v for k, v in cache["merger_docs"].items() if v.get("date", "") >= msince}
        pathlib.Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        log_p.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        LAST_DIAG["active"] = [{"ticker": t, **{k: v for k, v in h.items() if k in ("record", "distribution", "ratio", "new", "filing_date")}} for t, h in sorted(active.items())]
        if LAST_DIAG["errors"] and not LAST_DIAG["filings"] and LAST_DIAG["checked"]:
            LAST_DIAG.update(ok=False, error="EDGAR не върна нито един списък с подавания")
        LAST_DIAG["mergers"] = [{"ticker": t, "buyer": h["buyer"], "announced": h["announced"], "filing_date": h["filing_date"]} for t, h in sorted(LAST_MERGERS.items())]
        for t, h in active.items():
            print(f"[spinoff] {t}: {warning_text(h)}")
        for t, h in sorted(LAST_MERGERS.items()):
            print(f"[merger] {t}: {merger_text(h)}")
        return active
    except Exception as e:
        LAST_DIAG.update(ok=False, error=f"{type(e).__name__}: {e}")
        print(f"[spinoff] проверката пропусната: {LAST_DIAG['error']}")
        return {}


def windows(log_path=None) -> dict[str, list[tuple[str, str]]]:
    """{тикър: [(запис, разпределение)]} от дневника — прозорците, в които книгите не записват нов вход (и за стари snapshot-и, които се ингестират наново). Грешка → {}."""
    try:
        log = _load(pathlib.Path(log_path or pathlib.Path(config.DATA_DIR) / config.SPINOFF_LOG_NAME), {"entries": []})
        out: dict[str, list[tuple[str, str]]] = {}
        for e in log.get("entries", []):
            if e.get("ticker") and e.get("record") and e.get("distribution"):
                w = (e["record"], e["distribution"])
                if w not in out.setdefault(e["ticker"], []):
                    out[e["ticker"]].append(w)
        return out
    except Exception as e:
        print(f"[spinoff] прозорците не се прочетоха: {type(e).__name__}: {e}")
        return {}


def annotate_mergers(cards_groups, mergers: dict[str, dict] | None = None) -> int:
    """21.10.2026: card["merger_target"] = {text, buyer, announced, filing_date} върху картите на тикърите — цели на висяща сделка (само маркер, картата остава); връща броя."""
    mergers = LAST_MERGERS if mergers is None else mergers
    n = 0
    for g in cards_groups or []:
        for c in g or []:
            h = mergers.get(c.get("ticker")) if isinstance(c, dict) else None
            if h:
                c["merger_target"] = {"text": merger_text(h), **{k: h.get(k) for k in ("buyer", "announced", "filing_date")}}
                drop_uov(c)
                n += 1
    return n


def drop_uov(row: dict) -> bool:
    """
    28.10.2026: при сделка UOV✓ не се показва — опционният обем следва условията на сделката, не сетъпа (ROKU 28.10: calls 92% върху цена, привързана към офертата на Fox).
    Маха маркера от реда / картата и пази защо (uov_hidden); връща дали е махнат.
    """
    ms = row.get("markers") or []
    keep = [m for m in ms if not (isinstance(m, dict) and str(m.get("tag", "")).startswith("UOV"))]
    if len(keep) == len(ms):
        return False
    row["markers"] = keep
    row["uov_hidden"] = "сделка — опционният обем следва условията на сделката"
    return True


def annotate(cards_groups, active: dict[str, dict]) -> int:
    """card["spinoff_warning"] = {text, record, distribution, ratio, new, new_ticker} върху картите на тикърите с активно предупреждение; връща броя."""
    n = 0
    for g in cards_groups or []:
        for c in g or []:
            h = active.get(c.get("ticker")) if isinstance(c, dict) else None
            if h:
                c["spinoff_warning"] = {"text": warning_text(h), **{k: h.get(k) for k in ("record", "distribution", "ratio", "new", "new_ticker", "filing_date")}}
                n += 1
    return n
