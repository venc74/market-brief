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


def check(tickers, today=None, get=None, cik_map=None, budget_sec: float | None = None) -> dict[str, dict]:
    """
    {тикър: засичане} за тикърите с АКТИВНО предупреждение: 8-K в последните config.SPINOFF_LOOKBACK_DAYS дни с пълно засичане и дата на разпределение ≥ днес (най-новият такъв 8-K).
    get(url) -> текст и cik_map {тикър: CIK} се подменят в тестовете. Записва кеша по документ и дневника. budget_sec: след него останалите тикъри (по реда на подаване) не се
    проверяват — LAST_DIAG["unchecked"]. Не вдига: провал → {} и LAST_DIAG ok=False.
    """
    LAST_DIAG.clear()
    LAST_DIAG.update(ok=True, requested=0, checked=0, filings=0, fetched=0, active=[], logged=0, errors=[], unchecked=[], error=None)
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
        log = _load(log_p, {"version": 1, "entries": []})
        since = (today - dt.timedelta(days=config.SPINOFF_LOOKBACK_DAYS)).isoformat()
        active: dict[str, dict] = {}
        seen_log = {(e.get("ticker"), e.get("accession")) for e in log["entries"]}
        t0 = time.monotonic()
        for i, t in enumerate(tickers):
            if budget_sec is not None and time.monotonic() - t0 > budget_sec:
                LAST_DIAG["unchecked"] = tickers[i:]
                print(f"[spinoff] бюджетът от {budget_sec} s изтече — непроверени {len(tickers) - i}: {', '.join(tickers[i:i + 20])}")
                break
            cik = cik_map.get(t)
            if not cik:
                continue
            LAST_DIAG["checked"] += 1
            try:
                fs = recent_8k(json.loads(get(f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json")), since, today.isoformat())
            except Exception as e:
                LAST_DIAG["errors"].append({"ticker": t, "error": f"submissions: {type(e).__name__}"})
                continue
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
        pathlib.Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        log_p.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        LAST_DIAG["active"] = [{"ticker": t, **{k: v for k, v in h.items() if k in ("record", "distribution", "ratio", "new", "filing_date")}} for t, h in sorted(active.items())]
        if LAST_DIAG["errors"] and not LAST_DIAG["filings"] and LAST_DIAG["checked"]:
            LAST_DIAG.update(ok=False, error="EDGAR не върна нито един списък с подавания")
        for t, h in active.items():
            print(f"[spinoff] {t}: {warning_text(h)}")
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
