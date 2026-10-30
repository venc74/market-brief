"""
watch_monitor.py — ръчно куриран, per-ticker дневен монитор („🔎 Наблюдавани
тикъри").

Различен по предназначение от всичко останало в брифа: CANSLIM скрийнърът,
GLB и Short Screener ТЪРСЯТ нови кандидати по критерии. Тук няма търсене —
списъкът е фиксиран и ръчно поддържан (обикновено вече отворени позиции), а
въпросът е единствено „какво се случи около тази компания през последните
24 часа".

Източници — само вече налична инфраструктура, нула нови зависимости:
  • новини (29.10.2026): RSS на Yahoo Finance по ТИКЪР (config.WATCH_NEWS_RSS) + проверка, че новината е за компанията (about_company);
    yfinance .news — само резерва (на 29.10 връща нищо). До 29.10: yfinance .news, keyed по ТИКЪР. Съзнателно НЕ Google News по име
    на компанията — тествано на 18.09.2026 и се чупи при двусмислени имена:
    заявка за BLSH ("Bullish") върна "Why Democrats are starting to feel
    bullish about a midterm wave" и "AI trade rebound sparks flurry of
    unusually bullish options activity". yfinance няма този проблем и дава
    ISO timestamp за 24-часовия прозорец.
  • insider: insider_buying.fetch_insider_transactions() — покупки И продажби,
    със структурния aff10b5One флаг (виж там за rationale).

Списъкът се редактира РЪЧНО в data/watch_list.json. Сайтът е статичен, генерира
се веднъж дневно и няма жив сървър — интерактивен бутон в HTML-а е технически
невъзможен без backend. Премахването на тикър оттук НЕ влияе на това дали
компанията се появява другаде в брифа (GLB/COT/CANSLIM са напълно независими).

Изричният „нищо не се е случило" отговор е CODE-ENFORCED, не молба към промпта:
тикър без новини и без Form 4 изобщо не стига до AI-то — кодът сам слага
текста. Същата дисциплина като видимия log ред при „всичко unchanged" в
thesis_reality_check.

Graceful degradation навсякъде: провал за един тикър → само той отпада; провал
на целия модул → празен списък и брифът продължава без секцията.
"""
from __future__ import annotations
import calendar
import datetime as dt
import json
import re
import time

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
import requests
import yfinance as yf
from src import net_utils
from src import insider_buying

_LIST_PATH = config.DATA_DIR / "watch_list.json"


def load_watch_list() -> list[str]:
    """Ръчно поддържаният списък. Липсващ/повреден файл → празен списък."""
    if not _LIST_PATH.exists():
        return []
    try:
        data = json.loads(_LIST_PATH.read_text(encoding="utf-8"))
        tickers = data.get("tickers") if isinstance(data, dict) else data
        return [str(t).upper().strip() for t in (tickers or []) if str(t).strip()]
    except Exception as e:
        print(f"[watch] watch_list.json нечетим: {e}")
        return []


_NAME_SUFFIX = re.compile(r"(?:,?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?|plc|PLC|SE|N\.V\.|NV|S\.A\.|AG|Ltd\.?|Limited|Holdings?|Group|Companies|Company|Co\.?"
                          r"|Technologies|Technology))+\.?$")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def company_keys(name: str | None) -> set[str]:
    """29.10.2026 (т. 6): имената, по които новината се разпознава като за компанията — пълното име без "Inc." и т.н. и първата му дума (3+ знака). "C3.ai, Inc." → {"C3.ai"}."""
    n = _NAME_SUFFIX.sub("", (name or "").strip()).strip(" ,")
    keys = {n} if n else set()
    first = n.split()[0] if n.split() else ""
    if len(first) >= 3:
        keys.add(first)
    return keys


def about_company(ticker: str, keys: set[str], title: str, summary: str = "") -> str | None:
    """
    29.10.2026 (т. 6, решение 4): за компанията ли е новината — "symbol" (тикърът в скоби, след "NYSE:" / "Nasdaq:", или с "$"), "ticker" (тикър от 3+ букви, с главни, като дума),
    "name" (името — с главните му букви, като дума) или None. Тикър от 1–2 букви ("AI", "SN") се приема само като символ: "AI" като дума е изкуственият интелект. Чиста функция.
    """
    text = f"{title or ''} {summary or ''}"
    t = re.escape(ticker)
    if re.search(rf"\({t}\)|\b(?:NYSE|NASDAQ|Nasdaq|NYSEAMERICAN)\s*:\s*{t}\b|\${t}\b", text):
        return "symbol"
    if len(ticker) >= 3 and re.search(rf"(?<![\w$]){t}(?![\w])", text):
        return "ticker"
    if any(re.search(rf"(?<![\w.]){re.escape(k)}(?![\w])", text) for k in keys or ()):
        return "name"
    return None


def _rss_news(ticker: str, hours: int, keys: set[str], fetch=None) -> list[dict] | None:
    """Новините от RSS на Yahoo Finance в прозореца, само за компанията (about_company); None — фийдът не се изтегли. fetch(url) → bytes (за тестове)."""
    try:
        import feedparser
        url = config.WATCH_NEWS_RSS.format(ticker=ticker)
        raw = fetch(url) if fetch else requests.get(url, timeout=15, headers=_UA).content
        feed = feedparser.parse(raw)
        if not feed.entries and getattr(feed, "bozo", False):
            return None
    except Exception as e:
        print(f"[watch] {ticker} RSS новини: {type(e).__name__}: {e}")
        return None
    cutoff = time.time() - hours * 3600
    out = []
    for e in feed.entries:
        pt = e.get("published_parsed") or e.get("updated_parsed")
        ts = calendar.timegm(pt) if pt else None
        if ts is not None and ts < cutoff:
            continue
        title, summary = (e.get("title") or "").strip(), re.sub(r"<[^>]+>", "", e.get("summary") or "").strip()
        if not title or not about_company(ticker, keys, title, summary):
            continue
        link = e.get("link") if isinstance(e.get("link"), str) and e["link"].startswith(("https://", "http://")) else None
        out.append({"title": title, "publisher": (e.get("source") or {}).get("title", "") if isinstance(e.get("source"), dict) else "",
                    "when": dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat() if ts else None, "summary": summary[:300], **({"link": link} if link else {})})
    return out[:config.WATCH_MAX_NEWS_PER_TICKER]


def _recent_news(ticker: str, hours: int, keys: set[str] | None = None) -> list[dict]:
    """29.10.2026: RSS на Yahoo по тикър, само за компанията; провал на RSS → yfinance .news (също филтрирани). Провал → празен списък."""
    got = _rss_news(ticker, hours, keys or set())
    if got is not None:
        return got
    return [n for n in _yf_news(ticker, hours) if about_company(ticker, keys or set(), n["title"], n.get("summary") or "")]


def _yf_news(ticker: str, hours: int) -> list[dict]:
    """yfinance .news, орязан до прозореца. Провал → празен списък. (29.10.2026: само резерва — връща нищо.)"""
    try:
        items = net_utils.fetch_with_timeout(lambda: yf.Ticker(ticker).news) or []
    except Exception as e:
        print(f"[watch] {ticker} новини: {e}")
        return []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out = []
    for it in items:
        c = it.get("content") or it
        title = (c.get("title") or "").strip()
        if not title:
            continue
        ts = c.get("pubDate") or c.get("displayTime")
        when = None
        if ts:
            try:
                when = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except ValueError:
                when = None
        elif it.get("providerPublishTime"):
            when = dt.datetime.fromtimestamp(it["providerPublishTime"], dt.timezone.utc)
        if when is not None and when < cutoff:
            continue
        out.append({
            "title": title,
            "publisher": ((c.get("provider") or {}).get("displayName")
                          if isinstance(c.get("provider"), dict) else c.get("publisher")) or "",
            "when": when.isoformat() if when else None,
            "summary": (c.get("summary") or c.get("description") or "")[:300],
        })
    return out[:config.WATCH_MAX_NEWS_PER_TICKER]


# ──────────────────────────────────────────────────────────────────────────
# 29.10.2026 (разходката, т. 6, решение 2): компактен ред с факти от кода (без AI) за всеки тикър
# ──────────────────────────────────────────────────────────────────────────
def price_facts(closes, spy=None) -> dict:
    """
    Дневни затваряния (pandas Series, без днешния частичен бар) → цена, промяна за сесията, над/под 50DMA и 200DMA, RS спрямо S&P 500 за 4 и 12 седмици
    (config.WATCH_RS_SESSIONS). 30.10.2026 (поправки от брифа, т. 3): RS е РАЗЛИКАТА в ръста — ръстът на акцията минус ръстът на SPY, в процентни пунктове (до 30.10 —
    (1 + r) / (1 + r_SPY) − 1) — и "rs_word" от кода (rs_word). Къса история → None за съответното поле. Чиста функция.
    """
    c = closes.dropna() if closes is not None else None
    if c is None or len(c) < 2:
        return {}
    last, prev = float(c.iloc[-1]), float(c.iloc[-2])
    out = {"date": c.index[-1].date().isoformat(), "close": round(last, 2), "chg_1d_pct": round((last / prev - 1) * 100, 2)}
    for n in (50, 200):
        if len(c) >= n:
            ma = float(c.iloc[-n:].mean())
            out[f"ma{n}"] = round(ma, 2)
            out[f"above_{n}"] = last > ma
    s = spy.dropna().reindex(c.index).dropna() if spy is not None else None
    for n in config.WATCH_RS_SESSIONS:
        if s is not None and len(c) > n and len(s) > n:
            r, rs_ = last / float(c.iloc[-1 - n]) - 1, float(s.iloc[-1]) / float(s.iloc[-1 - n]) - 1
            out[f"rs_{n}"] = round((r - rs_) * 100, 1)
    w = rs_word(out.get(f"rs_{config.WATCH_RS_SESSIONS[0]}"), out.get(f"rs_{config.WATCH_RS_SESSIONS[1]}"))
    if w:
        out["rs_word"] = w
    return out


def rs_word(rs_4w: float | None, rs_12w: float | None) -> str | None:
    """30.10.2026 (т. 3): думата до RS — "води пазара" (+ и за двата), "набира сила" (− за 12, + за 4 седмици), "отслабва" (+ за 12, − за 4), "изостава" (− и за двата); 0 е „не +“."""
    if rs_4w is None or rs_12w is None:
        return None
    up4, up12 = rs_4w > 0, rs_12w > 0
    return {(True, True): "води пазара", (True, False): "набира сила", (False, True): "отслабва", (False, False): "изостава"}[(up4, up12)]


def short_facts(info: dict | None) -> dict:
    """
    Short interest от Yahoo .info: % от float, дни за покриване, промяна спрямо предишното отчитане (sharesShort / sharesShortPriorMonth − 1) и ДАТИТЕ на двете отчитания
    (dateShortInterest, sharesShortPreviousMonthDate). Липсващо поле → без него. Чиста функция.
    """
    i = info or {}
    day = lambda ts: dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date().isoformat() if isinstance(ts, (int, float)) and ts > 0 else None
    out = {}
    if isinstance(i.get("shortPercentOfFloat"), (int, float)):
        out["pct_float"] = round(i["shortPercentOfFloat"] * 100, 1)
    if isinstance(i.get("shortRatio"), (int, float)):
        out["days_to_cover"] = round(i["shortRatio"], 1)
    now, prior = i.get("sharesShort"), i.get("sharesShortPriorMonth")
    if isinstance(now, (int, float)) and isinstance(prior, (int, float)) and prior > 0:
        out["chg_pct"] = round((now / prior - 1) * 100, 1)
    if day(i.get("dateShortInterest")):
        out["as_of"] = day(i.get("dateShortInterest"))
    if day(i.get("sharesShortPreviousMonthDate")):
        out["prior_as_of"] = day(i.get("sharesShortPreviousMonthDate"))
    return out


# 29.10.2026 (т. 6): маркер, ако тикърът е и в наш скрийнър / книга — по реда на показване
MARKER_ORDER = ("Action", "Watchlist", "QM", "GLB", "EP", "книга Action", "книга buy-stop", "книга QM", "книга GLB по Уиш")


def brief_markers(tickers: list[str], sources: dict[str, set]) -> dict[str, list[str]]:
    """{тикър: [маркери]} — sources: {маркер: множество тикъри} (Action, Watchlist, QM, GLB, EP, отворените записи в книгите). Чиста функция."""
    return {t: [m for m in MARKER_ORDER if t in (sources.get(m) or set())] for t in tickers}


def attach_markers(rows: list[dict], cards: dict[str, list | None], books: bool = True, book_records=None) -> None:
    """
    29.10.2026 (т. 6): row["in_brief"] = маркерите (brief_markers) — cards: {маркер: списък карти / редове с "ticker"} (Action, Watchlist, QM, GLB, EP); books → и отворените /
    чакащите записи в книгите (Action, buy-stop, QM, GLB по Уиш). Грешка → без маркери, ред в лога (graceful).
    """
    try:
        src = {k: {c.get("ticker") for c in v or [] if isinstance(c, dict)} for k, v in (cards or {}).items()}
        if books:
            from src import backtest
            br = book_records or backtest.book_records
            for label, cat in (("книга Action", backtest.CATEGORY_ACTION), ("книга buy-stop", backtest.CATEGORY_BUYSTOP), ("книга QM", backtest.CATEGORY_QM),
                               ("книга GLB по Уиш", backtest.CATEGORY_GLB_WISH_HIGH)):
                src[label] = {r.get("ticker") for r in br(cat, statuses=("open", "trailing", "pending"))}
        marks = brief_markers([r["ticker"] for r in rows], src)
        for r in rows:
            r["in_brief"] = marks.get(r["ticker"], [])
    except Exception as e:
        print(f"[watch] маркерите (скрийнър / книги) пропуснати: {type(e).__name__}: {e}")


def facts(tickers: list[str], download=None, info_fn=None, earnings_fn=None) -> dict[str, dict]:
    """
    {тикър: {name, price: price_facts, short: short_facts, earnings: {next, days}}} — цените с ЕДНО теглене (тикърите + SPY, 1 година, без днешния частичен бар),
    .info и следващият отчет (enrich.earnings_info — същата логика като картите) по тикър. Провал за тикър → празните полета само за него; провал на тегленето → без цени.
    download(tickers) → DataFrame като yf.download(group_by="ticker"); info_fn(t) → dict; earnings_fn(t) → dict (за тестове).
    """
    from src import sessions as _sessions
    out = {t: {"name": None, "price": {}, "short": {}, "earnings": {}} for t in tickers}
    if not tickers:
        return out
    try:
        dl = download or (lambda ts: yf.download(ts, period="1y", auto_adjust=False, group_by="ticker", progress=False, threads=True))
        df = _sessions.cut_today(dl(list(tickers) + ["SPY"]))
        spy = df["SPY"]["Close"] if "SPY" in df.columns.get_level_values(0) else None
        for t in tickers:
            try:
                out[t]["price"] = price_facts(df[t]["Close"], spy)
            except Exception as e:
                print(f"[watch] {t} цени: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"[watch] цените не се изтеглиха: {type(e).__name__}: {e}")
    for t in tickers:
        try:
            info = (info_fn or (lambda x: net_utils.fetch_with_timeout(lambda: yf.Ticker(x).info) or {}))(t) or {}
            out[t]["name"] = info.get("longName") or info.get("shortName")
            out[t]["short"] = short_facts(info)
        except Exception as e:
            print(f"[watch] {t} .info: {type(e).__name__}: {e}")
        try:
            if earnings_fn is None:
                from src import enrich
                earnings_fn = enrich.earnings_info
            e = earnings_fn(t) or {}
            out[t]["earnings"] = {"next": e.get("next_earnings"), "days": e.get("days_to_earnings"), "status": e.get("earnings_status")}
        except Exception as e:
            print(f"[watch] {t} отчет: {type(e).__name__}: {e}")
    return out


def insider_flags(txns: list[dict]) -> list[dict]:
    """
    30.10.2026 (поправки от брифа, т. 2): флаг за всяка посока поотделно — покупки ("P") и продажби ("S") — {dir, label, n, owners, value, cluster, plan, top_offplan?}.
    cluster — ≥ INSIDER_CLUSTER_MIN_COUNT различни инсайдъри в прозореца в ТАЗИ посока (_insider_cluster); plan — "по план (10b5-1)" / "извънпланови" / "частично по план" /
    "планът неизвестен" (aff10b5One: True / False / null); top_offplan — най-голямата извънпланова сума на един инсайдър за един ден (owner, title, date, value).
    До 30.10 CLUSTER беше общ: ACN на 30.10 го носеше заради продажбите, а под него беше извънплановата покупка на CEO за ~$3 млн. Чиста функция.
    """
    out = []
    for code, label in (("P", "покупки"), ("S", "продажби")):
        xs = [t for t in txns or [] if t.get("code") == code]
        if not xs:
            continue
        pl = [t.get("planned_10b5_1") for t in xs]
        plan = ("по план (10b5-1)" if all(x is True for x in pl) else "извънпланови" if all(x is False for x in pl)
                else "частично по план" if any(x is True for x in pl) and any(x is False for x in pl) else
                "планът неизвестен" if all(x is None for x in pl) else "частично по план")
        groups: dict = {}
        for t in xs:
            if t.get("planned_10b5_1") is False:
                k = (t.get("owner_name"), str(t.get("date"))[:10])
                g = groups.setdefault(k, {"owner": t.get("owner_name"), "title": t.get("owner_title") or ("директор" if t.get("is_director") else ""),
                                          "date": str(t.get("date"))[:10], "value": 0.0})
                g["value"] += float(t.get("value") or 0)
        f = {"dir": code, "label": label, "n": len(xs), "owners": len({t.get("owner_name") for t in xs}), "value": round(sum(float(t.get("value") or 0) for t in xs)),
             "cluster": _insider_cluster(xs), "plan": plan}
        if groups:
            top = max(groups.values(), key=lambda g: g["value"])
            f["top_offplan"] = {**top, "value": round(top["value"])}
        out.append(f)
    return out


def _insider_cluster(txns: list[dict]) -> bool:
    """≥ INSIDER_CLUSTER_MIN_COUNT РАЗЛИЧНИ инсайдъри в клъстер прозореца."""
    if not txns:
        return False
    window = config.INSIDER_CLUSTER_WINDOW_DAYS
    for t in txns:
        near = {o["owner_name"] for o in txns
                if abs((o["date"] - t["date"]).days) <= window and o["code"] == t["code"]}
        if len(near) >= config.INSIDER_CLUSTER_MIN_COUNT:
            return True
    return False


def collect(tickers: list[str] | None = None, facts_fn=None) -> list[dict]:
    """
    Суровите данни за всеки watched тикър, БЕЗ AI слой.

    Връща [{ticker, name, facts, news: [...], insider: [...], insider_cluster: bool,
             quiet: bool}], в реда на списъка. `quiet=True` значи нула новини и
    нула Form 4 — извикващият не бива да праща такъв тикър към AI-то (29.10.2026: фактите на реда не са събитие).
    """
    tickers = tickers if tickers is not None else load_watch_list()
    if not tickers:
        return []
    try:
        fx = (facts_fn or facts)(tickers)
    except Exception as e:
        print(f"[watch] фактите не се изчислиха: {type(e).__name__}: {e}")
        fx = {}
    try:
        insider = insider_buying.fetch_insider_transactions(tickers)
    except Exception as e:
        print(f"[watch] insider блок се провали изцяло: {e}")
        insider = {}

    rows = []
    for tk in tickers:
        f = fx.get(tk) or {}
        news = _recent_news(tk, config.WATCH_NEWS_WINDOW_HOURS, company_keys(f.get("name")))
        txns = insider.get(tk, [])
        rows.append({
            "ticker": tk,
            "name": f.get("name"),
            "facts": {k: f.get(k) or {} for k in ("price", "short", "earnings")},
            "news": news,
            "insider": [{**t, "date": t["date"].isoformat()} for t in txns],
            "insider_cluster": _insider_cluster(txns),
            "insider_flags": insider_flags(txns),                   # 30.10.2026: по посока — покупки / продажби, с плана
            "quiet": not news and not txns,
        })
    quiet = [r["ticker"] for r in rows if r["quiet"]]
    print(f"[watch] {len(rows)} наблюдавани тикъра — "
          f"{len(rows) - len(quiet)} със събития, {len(quiet)} без "
          f"({', '.join(quiet) if quiet else '—'})")
    return rows
