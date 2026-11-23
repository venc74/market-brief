"""
news_aggregator.py — агрегатор за макро и геополитически новини.

Събира заглавия от последните 24 часа (от 02.11.2026 — от предишния бриф, sessions.news_window_start) от:
  • RSS: Reuters (business + world), Financial Times, CNBC
  (04.11.2026, четвърти преглед: X/Twitter през nitter — махнат; беше изключен, NEWS_ENABLE_NITTER по подразбиране 0)

После подава всичко на Claude с инструкция да извлече само пазарно значимите
(геополитика, Fed, секторни движения, суровини) — максимум 8, всяка с едно
изречение защо е важна днес. Резултатът влиза в макро брифа като „Значими новини".

Бележка за източниците: публичните Reuters RSS емисии са
нестабилни (Reuters спря част от RSS-а). Затова всичко е
с graceful degradation — ако даден източник падне, просто се прескача; ако ВСИЧКИ
паднат, връщаме празен списък и брифът продължава без секцията (по изискване).

Резултатът се кешира за деня (data/news_cache.json), за да не вика Claude при
повторни пускания.
"""
from __future__ import annotations
import datetime as dt
import calendar
import itertools
import json
import re
import time
import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

try:
    import feedparser  # устойчив RSS/Atom парсър
except Exception:
    feedparser = None

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_CACHE = config.DATA_DIR / "news_cache.json"
# 04.11.2026 (четвърти преглед): мемото на gather_raw (_RAW_MEMO, FIX 2026-09-18) — махнато: един извикващ (significant_news) от 30.10, а ключът му се презаписваше
# в цикъла за дедупликация и никога не съвпадаше. Тестовете подменят gather_raw.


# ──────────────────────────────────────────────────────────────────────────
# RSS
# ──────────────────────────────────────────────────────────────────────────
def _fetch_rss(url: str, source: str, hours: float, limit: int = 15, since_ts: float | None = None, keep=None, keep_max: int = 0) -> list[dict]:
    """
    Заглавията на фийда в прозореца — последните `hours` часа или (02.11.2026) от since_ts (UTC epoch — началото на прозореца, sessions.news_window_start).
    02.11.2026: времето на заглавието — calendar.timegm (feedparser дава UTC); до 02.11 time.mktime го четеше като местно време — на GitHub runner-а (UTC) същото.
    """
    if feedparser is None:
        LAST_FETCH_ERRORS[source] = "feedparser липсва"
        return []
    out = []
    try:
        # сваляме сами с requests (по-устойчиво от feedparser.parse(url) зад UA/таймаут)
        resp = requests.get(url, timeout=15, headers=_UA)
        if getattr(resp, "status_code", 200) != 200:                       # 18.11.2026: HTTP грешката — в реда под новините, не само в лога
            LAST_FETCH_ERRORS[source] = f"HTTP {resp.status_code}"
        raw = resp.content
        feed = feedparser.parse(raw)
        cutoff = since_ts if since_ts is not None else time.time() - hours * 3600
        for e in feed.entries[:limit * 2]:
            ts = None
            for key in ("published_parsed", "updated_parsed"):
                if e.get(key):
                    ts = calendar.timegm(e[key]); break
            if ts is not None and ts < cutoff:
                continue  # по-стара от прозореца
            title = (e.get("title") or "").strip()
            if not title:
                continue
            summary = (e.get("summary") or e.get("description") or "").strip()
            summary = _strip_html(summary)[:300]
            row = {"source": source, "title": title, "summary": summary}
            link = _safe_link(e.get("link"))                       # 29.10.2026 (разходката, т. 3–4): заглавието в брифа е линк към статията
            if link:
                row["link"] = link
            pt = e.get("published_parsed") or e.get("updated_parsed")
            if pt:
                row["published"] = time.strftime("%Y-%m-%dT%H:%MZ", pt)     # 29.10.2026: колко назад стига фийдът (CoinDesk държи 25); feedparser дава UTC
            if len(out) >= limit:                                            # 18.11.2026 (поправка): след тавана — само приоритетните (keep), до keep_max
                if keep is not None and keep_max and keep(title):
                    out.append({**row, "beyond_limit": True})
                    keep_max -= 1
                continue
            out.append(row)
            if len(out) >= limit and not (keep is not None and keep_max):
                break
    except Exception as ex:
        print(f"[news] RSS {source} failed: {ex}")
        LAST_FETCH_ERRORS[source] = f"{type(ex).__name__}: {ex}"[:160]          # 18.11.2026: паднал източник — видим ред под новините (render.news_sources_alert)
    return out


# 18.11.2026 (спешно, т. 1): {източник: грешка} от последното теглене (HTTP ≠ 200, изключение) — gather_raw го чисти и го пише в LAST_WINDOW["dead"]
LAST_FETCH_ERRORS: dict = {}


def _safe_link(link) -> str | None:
    """29.10.2026: линкът от фийда — само http(s) (не javascript: и подобни); иначе None."""
    link = link.strip() if isinstance(link, str) else ""
    return link if re.match(r"https?://[^\s\"'<>]+$", link) else None


def _strip_html(s: str) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(s, "html.parser").get_text(" ", strip=True)
    except Exception:
        import re
        return re.sub(r"<[^>]+>", "", s)


# ──────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────
def _scrape_headlines(name: str, url: str, limit: int = 12) -> list[dict]:
    """Fallback: вади заглавия директно от страницата с BeautifulSoup (когато RSS падне)."""
    out = []
    try:
        from bs4 import BeautifulSoup
        html = requests.get(url, timeout=15, headers=_UA).text
        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        # заглавията почти винаги са в <h1>/<h2>/<h3> или линкове с дълъг текст
        for tag in soup.select("h1, h2, h3, a"):
            txt = tag.get_text(" ", strip=True)
            if 35 <= len(txt) <= 200 and txt.lower() not in seen:
                seen.add(txt.lower())
                out.append({"source": name, "title": txt, "summary": ""})
            if len(out) >= limit:
                break
    except Exception as ex:
        print(f"[news] scrape {name} failed: {ex}")
    return out


def _interleave(per_source: list[list[dict]]) -> list[dict]:
    """
    Първо заглавие от всеки източник, после второто от всеки, и т.н.

    FIX 2026-09-16: агрегатният таван в significant_news() реже СЛЕД сливането,
    затова при конкатенация по източници по-задните източници се обезкървяват
    изцяло, щом предните запълнят тавана. Редуването прави тавана справедлив:
    всеки източник дава приблизително поравно, а дълбочината (ранг 15→50) вече
    не се плаща от чуждото покритие. zip_longest понася източници с различна
    дължина и напълно мъртви източници (празен списък → нищо не допринася).
    """
    return [x for tup in itertools.zip_longest(*per_source) for x in tup if x is not None]


_WHEN = re.compile(r"when:\d+[hd]\+?")


def google_day_urls(url: str, since: dt.datetime, now: dt.datetime) -> list[tuple[str, str]]:
    """
    02.11.2026 (поправки след брифа, т. 4): Google News (Reuters, AP) връща най-много 100 заглавия — при Reuters ≈ 22 ч; „when:3d“ / „when:72h“ дават СЪЩИТЕ 100 като
    „when:24h“ (проверено 02.11.2026: Reuters 100 = 83 от 02.11 + 17 от 01.11 и при трите). При прозорец над config.NEWS_DAY_QUERY_MIN_HOURS — по една заявка
    „after:Д before:Д+1“ (100 заглавия за деня; денят на Google е по тихоокеанско време — границата ≈ 07:00 UTC) за всеки ден от началото на прозореца до деня преди
    последните 24 ч; заглавията извън прозореца отпадат в _fetch_rss. Адрес без „when:“ (не е търсене в Google News) или по-къс прозорец → []. Чиста функция.
    """
    if "news.google.com/rss/search" not in url or not _WHEN.search(url) or (now - since).total_seconds() / 3600 <= config.NEWS_DAY_QUERY_MIN_HOURS:
        return []
    out, d, last = [], since.date(), (now - dt.timedelta(hours=24)).date()
    while d <= last:
        q = f"after:{d.isoformat()}+before:{(d + dt.timedelta(days=1)).isoformat()}+"
        out.append((d.isoformat(), _WHEN.sub("", url).replace("search?q=", "search?q=" + q, 1)))
        d += dt.timedelta(days=1)
    return out


def source_reach(items: list[dict]) -> dict:
    """{източник: {"count", "oldest"}} — oldest е най-старото заглавие в пула (UTC ISO), за бележката „докъде стига всеки източник днес“. Чиста функция."""
    out: dict = {}
    for r in items:
        s = out.setdefault(r.get("source") or "?", {"count": 0, "oldest": None})
        s["count"] += 1
        p = r.get("published")
        if p and (s["oldest"] is None or p < s["oldest"]):
            s["oldest"] = p
    return out


# 02.11.2026: прозорецът и обхватът на последното gather_raw — {since, hours, day_queries, sources: source_reach} (main → brief["news_window"])
LAST_WINDOW: dict = {}
LAST_RAW: list = []
LAST_FRONT: list = []          # 19.11.2026 (т. 2): заглавията от първата страница (config.NEWS_FRONT_FEEDS)
LAST_THEMES: list = []         # 19.11.2026 (т. 2): топ темите на деня (top_themes.themes)

# ══════════════════════════════════════════════════════════════════════════
# 18.11.2026 (поправка към спешния пакет): приоритет в пула преди тавана. Пулът е config.NEWS_MAX_TO_FILTER на 24 ч (18.11: 100 от 139) и се режеше по реда на фийдовете
# (редуването) — Reuters ≈ 31 от 50, и заглавията за отчета на Nvidia вероятно не стигнаха до модела. Сега първо са заглавията, които споменават нашите тикъри и компании
# (позициите в книгите, наблюдаваните, картите, „Нощта“ и календарът за деня), после останалите в досегашния ред; след тавана на източника (50) се вземат и приоритетните
# (до config.NEWS_PRIORITY_EXTRA_PER_SOURCE). Съвпадението е по името (без правната форма; думите, които не са общи — _GENERIC; главни букви → без значение на регистъра)
# и по тикъра (3+ знака, главни, като дума). Грешно съвпадение само мести заглавие напред — не маха нищо; от 20.11 съвпадението е и „наши тикъри“ под новината (finish_rows),
# от 23.11 — и редовете на резервния подбор (code_pick).
# ══════════════════════════════════════════════════════════════════════════
_GENERIC = {"group", "holdings", "holding", "inc", "corporation", "company", "international", "global", "american", "america", "national", "united", "first", "general",
            "financial", "energy", "bank", "capital", "technologies", "technology", "systems", "industries", "services", "solutions", "health", "healthcare", "resources",
            "brands", "partners", "properties", "realty", "trust", "insurance", "communications", "entertainment", "networks", "software", "semiconductor", "pharmaceuticals",
            "therapeutics", "home", "the", "and", "markets", "market", "nasdaq", "exchange", "street", "wall", "data", "digital", "power", "electric", "water", "motors", "foods",
            "stores", "airlines", "labs", "laboratories", "sciences", "medical", "pacific", "western", "eastern", "southern", "northern", "royal", "standard", "investment",
            "investments", "asset", "management", "media", "consolidated", "reliance", "williams", "pepper", "class", "new", "corp", "limited", "trade", "tech", "bancorp",
            "street's", "one", "can", "growth", "income", "real", "estate", "life", "world", "worldwide",
            # 18.11.2026: места и посоки — „Manhattan closet“ (MANH — Manhattan Associates), „West Bank“ / „East-West pipeline“ (WST — West Pharmaceutical) в пула от 18.11
            "west", "east", "north", "south", "central", "manhattan", "texas", "york", "boston", "chicago", "atlanta", "pacific", "atlantic", "republic", "federal", "state",
            # 18.11.2026 (по историята — 1035 заглавия 13.06–18.11): „Nasdaq“ (NDAQ — името е индексът, 9 фалшиви), „Companies“ (TRV), „Aerospace“ (GE)
            "companies", "aerospace", "defense", "chemical", "chemicals", "materials", "logistics", "automotive",
            # 20.11.2026 (пакет 20.11, т. 1 — „наши тикъри“ под новината): по историята — 1366 заглавия × 922 имена от brief["names"]: „Reuters“ (TRI, 233 — наставката на
            # източника), „News“ (News Corp, 93), „Gold“ (Royal Gold, 20 — цената на златото), „Dollar“ (DLTR / DG, 18 — валутата; 20.11: „Dollar near 19-month high“ → DLTR),
            # „Dow“ (12 — Dow futures), „Live“ (10 — „Live updates“), „Morgan“ (J.P. Morgan → Kinder Morgan), „Stanley“ / „Black“ (Morgan Stanley, „first Black House speaker“),
            # „Cincinnati“ (Cincinnati Zoo), „Commerce“ (министерството), „Electronics“ (Samsung), „Grand“ (Grand Theft Auto), „Investors“, „Silicon“ (Silicon Data),
            # „Applied“ (Applied Compute), „River“ (River One), „Banking“ (Senate Banking), „Express“ (Asia Express), „Biotech“, „Booking“ („Booking a Hilton stay“),
            # „Fidelity“ (Fidelity Investments), „Freight“, „Jones“ (S&P Dow Jones → JLL), „Five“ („Five things to know“), „Information“ (The Information → FIS), „Illinois“, „Alaska“, „Valley“ (Silicon
            # Valley), „Southwest“ (Southwest Airlines → SWX), „Micro“ (Super Micro → AMD), „Post“ (NY Post), „Martin“ (Lockheed Martin → MLM), „Warner“ / „Bros“ (Warner Bros.),
            # „Duke“, „Johnson“ (кандидатът за SEC → JNJ / JCI); пълното име и тикърът — както досега; кратко име от главни (≤ 3 знака) — с регистъра („Nov.“ ≠ NOV)
            "five", "information", "illinois", "alaska", "valley", "southwest", "micro", "post", "martin", "warner", "bros", "duke", "johnson",
            "reuters", "news", "gold", "dollar", "dow", "live", "morgan", "stanley", "black", "cincinnati", "commerce", "electronics", "grand", "investors", "silicon",
            "applied", "river", "banking", "express", "biotech", "booking", "fidelity", "freight", "jones",
            # 23.11.2026 (пакет 23.11, т. 1 — резервният подбор показва заглавията за нашите тикъри): „Music Review: 'Grand Theft Auto VI: The Album'“ → WMG (Warner Music Group);
            # по историята със списъка от 23.11 (38 имена) — единственото грешно попадение
            "music"}
_LEGAL_RE = re.compile(r"\s*\((?:the|The)\)|,?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.?|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|AG|SE)\b\.?", re.I)


def priority_matchers(entries: list[dict] | None) -> list[tuple[str, re.Pattern]]:
    """[{ticker, name}] → [(тикър, regex)]: пълното име без правната форма, отличителните думи от него (4+ букви, не от _GENERIC) и тикърът (3+ знака, главни). Чиста функция."""
    out = []
    for e in entries or []:
        t, name = str(e.get("ticker") or "").upper(), _LEGAL_RE.sub("", str(e.get("name") or "").split(",")[0]).strip()
        alts = []
        if len(name) >= 3 and name.casefold() not in _GENERIC:                # „Nasdaq“ (NDAQ) — общо име, само тикърът
            alts.append(r"\b" + re.escape(name) + r"\b" if not name.isupper() or len(name) <= 3 else r"(?i:\b" + re.escape(name) + r"\b)")
        for w in re.findall(r"[A-Za-z][A-Za-z0-9&-]{3,}", name):
            if w.casefold() not in _GENERIC and w != name:
                alts.append(r"(?i:\b" + re.escape(w) + r"\b)" if w.isupper() else r"\b" + re.escape(w) + r"(?:'s|’s)?\b")
        if len(t) >= 3 and t.isalpha():
            alts.append(r"\b" + re.escape(t) + r"\b")
        if alts:
            out.append((t, re.compile("|".join(alts))))
    return out


def priority_hits(title: str, matchers: list) -> list[str]:
    """Тикърите, чиито имена / тикъри са в заглавието."""
    return [t for t, rx in matchers or [] if rx.search(title or "")]


def prioritize(items: list[dict], matchers: list) -> tuple[list[dict], int]:
    """Стабилно разделяне: заглавията с попадение — първи (в досегашния ред), после останалите. → (подредени, брой с попадение). Чиста функция."""
    if not matchers:
        return list(items), 0
    hit, rest = [], []
    for it in items:
        h = priority_hits(it.get("title"), matchers)
        (hit if h else rest).append({**it, "priority": h} if h else it)
    return hit + rest, len(hit)


def priority_entries(prev_brief: dict | None, today: str, candidates: list | None = None, watched: list | None = None, books: list | None = None) -> list[dict]:
    """priority_entries_raw, който не вдига: провал → [] (пулът — както до 18.11) и ред в лога."""
    try:
        return priority_entries_raw(prev_brief, today, candidates, watched, books)
    except Exception as e:
        print(f"[news] приоритетът на пула пропуснат: {type(e).__name__}: {e}")
        return []


def priority_entries_raw(prev_brief: dict | None, today: str, candidates: list | None = None, watched: list | None = None, books: list | None = None) -> list[dict]:
    """
    Чии са заглавията с приоритет: позициите в книгите, наблюдаваните, картите (днешният скрийнинг и картите на предишния бриф — CANSLIM, Kullamägi, GLB, EP), отчетите след
    затварянето на предишната сесия („Нощта“ — календарът на предишния бриф) и отчетите за днес. → [{ticker, name, why}] без повторения; имената — от картите, календара и
    brief["names"] на предишния бриф. Чиста функция.
    """
    from src import sessions
    pb = prev_brief or {}
    names = dict(pb.get("names") or {})
    out: dict = {}

    def add(t, why, name=None):
        t = str(t or "").upper().strip()
        if t and t not in out:
            out[t] = {"ticker": t, "name": name or names.get(t), "why": why}
        elif t and name and not out[t].get("name"):
            out[t]["name"] = name
    for t in books or []:
        add(t, "книгите")
    for t in watched or []:
        add(t, "наблюдаван")
    for c in list(candidates or []) + list(pb.get("action") or []) + list(pb.get("watchlist") or []) + list(pb.get("qm_breakout") or []) \
            + list(pb.get("glb_candidates") or []) + list(((pb.get("qm_ep") or {}).get("rows")) or []):
        if isinstance(c, dict):
            add(c.get("ticker"), "карта", c.get("name"))
    prev_s = sessions.prev_session(dt.date.fromisoformat(today)).isoformat()
    for d in ((pb.get("week_calendar") or {}).get("days")) or []:
        for e in d.get("earnings") or []:
            if (d.get("date") == prev_s and e.get("when") in ("след затварянето", "неизвестен час")) or d.get("date") == today:
                add(e.get("ticker"), "отчет (Нощта)" if d.get("date") == prev_s else "отчет днес", e.get("name"))
    return list(out.values())


def gather_raw(hours: float = 24, since: dt.datetime | None = None, keep=None) -> list[dict]:
    """
    FIX 2026-09-15: провалът се засича PER-SOURCE, не агрегатно.

    Преди: единственият сигнал беше `if len(items) < 5`. Мъртъв източник, който
    връща HTTP 200 с празен, валиден RSS, не вдига нито грешка, нито праг —
    останалите източници лесно покриват петицата и загубата е напълно тиха.
    Потвърдено на 15.09.2026: Reuters и AP връщаха 0 заглавия (спрял Google News
    "allinurl:" оператор, виж config.NEWS_RSS_FEEDS), CNBC+FT даваха 27, прагът
    никога не се задействаше — системата работеше месеци с 2 от 4 източника,
    без нито един ред в лога. Реална цена: Reuters заглавието "US Senate to vote
    on advancing landmark crypto bill" (CLARITY Act) не стигна до филтъра.

    Сега: всеки източник с нула заглавия се логва поименно, и самò по себе си
    задейства scrape fallback-а — не се чака агрегатният праг.

    FIX 2026-09-18 → 04.11.2026: мемото в процеса (_RAW_MEMO) е махнато — от 30.10 има един потребител (significant_news).

    02.11.2026 (поправки след брифа, т. 4): since (UTC) — началото на прозореца (предишният бриф, sessions.news_window_start); без since — последните `hours` часа (както
    до 02.11). При прозорец над config.NEWS_DAY_QUERY_MIN_HOURS — и заявките по дни за Google News (google_day_urls), всяка като отделен списък в редуването.
    """
    now = dt.datetime.now(dt.timezone.utc)
    since_ts = since.timestamp() if since else None
    per_source: list[list[dict]] = []
    dead: list[str] = []
    day_queries = 0
    LAST_FETCH_ERRORS.clear()
    fetched: dict = {}
    for src, url in config.NEWS_RSS_FEEDS.items():
        got = _fetch_rss(url, src, hours, limit=config.NEWS_PER_SOURCE_LIMIT, since_ts=since_ts, keep=keep, keep_max=config.NEWS_PRIORITY_EXTRA_PER_SOURCE if keep else 0)
        fetched[src] = len(got)
        if not got:
            dead.append(src)
        per_source.append(got)
    for src, url in config.NEWS_RSS_FEEDS.items():                       # 02.11.2026: по-ранните дни на прозореца (Reuters / AP) — след основните, за да не ги изместват
        for day, u in (google_day_urls(url, since, now) if since else []):
            day_queries += 1
            got = _fetch_rss(u, src, hours, limit=config.NEWS_PER_SOURCE_LIMIT, since_ts=since_ts, keep=keep, keep_max=config.NEWS_PRIORITY_EXTRA_PER_SOURCE if keep else 0)
            if not got:
                print(f"[news] {src}: заявката за {day} не върна заглавия в прозореца")
            per_source.append(got)
    # FIX 2026-09-16: редуване, не конкатенация — виж config.NEWS_PER_SOURCE_LIMIT
    items: list[dict] = _interleave(per_source)
    if dead:
        print(f"[news] ⚠ {len(dead)}/{len(config.NEWS_RSS_FEEDS)} източника върнаха "
              f"НУЛА заглавия: {', '.join(dead)} — HTTP 200 с празен резултат не е "
              "грешка, но е тиха загуба на покритие; провери дали URL-ът/заявката "
              "още е валидна")
    # Fallback: при МЪРТЪВ източник или твърде малко заглавия общо
    if dead or len(items) < 5:
        for name, url in config.NEWS_SCRAPE_FALLBACK.items():
            scraped = _scrape_headlines(name, url)
            if not scraped:
                print(f"[news] ⚠ scrape fallback '{name}' също върна нула")
            items += scraped
    # дедупликация по заглавие
    seen, dedup = set(), []
    for it in items:
        key = it["title"].lower()[:90]
        if key not in seen:
            seen.add(key); dedup.append(it)
    LAST_RAW.clear()
    LAST_RAW.extend(dedup)
    # 19.11.2026 (пакет 19.11, т. 2): първата страница / световните новини (FT World, Reuters World) — само за топ темите и техния приоритет (не влизат в редуването)
    LAST_FRONT.clear()
    front_n, front_dead = {}, []
    for src, url in config.NEWS_FRONT_FEEDS.items():
        got = _fetch_rss(url, src, hours, limit=config.NEWS_PER_SOURCE_LIMIT, since_ts=since_ts)
        front_n[src] = len(got)
        if not got:
            front_dead.append({"source": src, **({"error": LAST_FETCH_ERRORS[src]} if LAST_FETCH_ERRORS.get(src) else {})})
        LAST_FRONT.extend(got)                                                   # 18.11.2026 (т. 2): целият пул (преди тавана) — за заглавията с прогноза в блока „Нощта“
    LAST_WINDOW.clear()
    LAST_WINDOW.update({"since": since.isoformat() if since else (now - dt.timedelta(hours=hours)).isoformat(), "hours": round((now - since).total_seconds() / 3600, 2) if since else hours,
                        "day_queries": day_queries, "sources": source_reach(dedup),
                        # 18.11.2026 (спешно, т. 1): колко върна всеки фийд и кои са празни / паднали (с грешката) — за видимия ред под новините
                        "fetched": fetched, "dead": [{"source": d, **({"error": LAST_FETCH_ERRORS[d]} if LAST_FETCH_ERRORS.get(d) else {})} for d in dead],
                        "front": front_n, "front_dead": front_dead})
    if since:
        print(f"[news] прозорец: от {since:%d.%m %H:%M} UTC ({LAST_WINDOW['hours']:g} ч), заявки по дни: {day_queries}; обхват — "
              + " · ".join(f"{k} {v['count']} (до {v['oldest'][8:10]}.{v['oldest'][5:7]} {v['oldest'][11:16]})" if v.get("oldest") else f"{k} {v['count']}"
                           for k, v in LAST_WINDOW["sources"].items()))
    return dedup


# 30.10.2026 (разходката, т. 8): raw_pool() (суровият пул за проверката на тезите, FIX 2026-09-18) — махнат заедно с тезите; единственият му потребител беше
# ai_brief.thesis_news_pick.


# ──────────────────────────────────────────────────────────────────────────
# Claude филтър
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM = ("Ти си макро редактор за суинг търговец. Връщаш САМО валиден JSON, "
           "без markdown огради, без преамбюл. Пишеш на български, тикери и "
           "термини на английски.")


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_SCALE_EN = re.compile(r"\b(million|billion|trillion|mln|bn|tn)\b", re.I)
_SCALE_BG = re.compile(r"млн|млрд|трлн|милион|милиард|трилион", re.I)


def _translation_ok(bg: str, title: str) -> bool:
    """
    15.10.2026: преводът на заглавието (headline_bg) не бива да носи числа, които ги няма в оригинала, нито да губи мащаба ("awards $2 в damages" на 14.10 —
    в оригинала сумата е с мащаб). Всяко число в превода трябва да е в оригинала; оригинал с million/billion/trillion → преводът трябва да има млн/млрд/трлн.
    """
    nums = {n.replace(",", ".") for n in _NUM_RE.findall(title)}
    if any(n.replace(",", ".") not in nums for n in _NUM_RE.findall(bg)):
        return False
    return not (_SCALE_EN.search(title) and not _SCALE_BG.search(bg))


_WORD_RE = re.compile(r"[\w$%€£¥]+(?:[.,'’-][\w$%]+)*")
# 19.10.2026 (С3): числа, които са част от име или срок, не са твърдение ("Russell 2000", "S&P 500", "10-годишните", "Q3", "G7")
# Само в "why": срокът е с тире или слят ("10-year", "10-годишните", "19-годишен"); "3 години" е твърдение и се проверява (16.10: "почти 3 години" е в заглавието).
_NUM_NAME_RE = re.compile(r"(?:S&P|Russell|Nasdaq|Stoxx|FTSE|DAX|Nikkei|CAC|MSCI|Euro Stoxx)\s*\d+|\d+-?(?:годиш\w*|year\w*|месеч\w*|month\w*|седмич\w*|днев\w*)"
                          r"|\b\d+Y\b|\b[QG]\d\b", re.I)


# 18.11.2026 (спешно, т. 1 — Nvidia): моделът пише ехото с права апострофа („Nvidia's“), фийдът — с типографска („Nvidia’s“); до 18.11 думите не съвпадаха и избраната
# новина падаше с „индексът не съвпада със заглавието“ — 7 основни новини от 10.11 до 18.11 (всичките с апостроф; + 16 „също“ от 30.10 с апостроф в ехото — заглавието им не е пазено) (на 18.11 — „Nvidia’s Kress tells CNBC's Jim
# Cramer …“ и „China’s Xi calls for removing trade …“). Сравнението е след уеднаквяване на кавичките.
_QUOTES = str.maketrans({"’": "'", "‘": "'", "‛": "'", "′": "'", "`": "'", "“": '"', "”": '"', "„": '"', "″": '"'})


def _first_words(s: str, n: int = 6) -> list[str]:
    return [w.casefold().strip("'") for w in _WORD_RE.findall((s or "").translate(_QUOTES))][:n]


def _echo_index(h, i: int, pool: list[dict], seen: set) -> tuple[int | None, str]:
    """
    19.10.2026 (трети преглед, С3): моделът повтаря първите ~6 думи на заглавието ("h"); кодът ги сверява с pool[i]. Съвпадение → i. Разминаване → еднозначният ред в пула
    със същото начало (индексът е объркан — заглавието и "why" са за него) или None. Без "h" (стар отговор) → i, без проверка.
    """
    if not isinstance(h, str) or not h.strip():
        return i, "без ехо"
    want = _first_words(h)
    if len(want) < 3 and want != _first_words(pool[i]["title"]):
        return None, "ехото е по-кратко от 3 думи"
    if _first_words(pool[i]["title"])[:len(want)] == want:
        return i, ""
    hits = [j for j, r in enumerate(pool) if j not in seen and _first_words(r["title"])[:len(want)] == want]
    return (hits[0], f"индексът поправен по заглавието: {i} → {hits[0]}") if len(hits) == 1 else (None, "индексът не съвпада със заглавието")


# 29.10.2026 (разходката, т. 3, решение 3): число в "why", което го няма в източника, маха САМО частта с него — числото с мярката и количествения предлог ("до 20% от", "с 25 bps",
# "над 5 месеца", "на 24 септември"), не цялото изречение. Предлог без количествено значение ("за", "на", "в", "с") остава пред съществително ("коридор за ~20% от световния петрол" →
# "коридор за световния петрол", "AMD с 107% ръст" → "AMD с ръст") и пада пред служебна дума или запетая ("лихвата с 25 bps под Warsh" → "лихвата под Warsh").
_WHY_MONTHS = (r"(?:януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември"
               r"|January|February|March|April|May|June|July|August|September|October|November|December)")
_WHY_UNIT = (r"(?:\s?%\+?|\s?(?:bps|bp|б\.\s?п\.|базисни\s+пункта|процентни\s+пункта|пункта|пункт|млрд\.?|млн\.?|трлн\.?|bn|B|M|долара|евро|месеца|години|седмици|дни|пъти|г\.)(?![\w]))*")
_WHY_NUM = r"[~≈+\-−]?[$€£¥]?\d+(?:[.,]\d+)*(?:\s\d{3})*(?:\s?[–-]\s?[$€£¥]?\d+(?:[.,]\d+)*)?"
_WHY_ADV = r"(?:около|над|под|близо\s+до|почти|едва|повече\s+от|по-малко\s+от)"                     # количествени — падат с числото винаги
_WHY_PREP = r"(?:от|до|при|с|със|за|на|във|в)"                                                      # "от", "до", "при" падат; "с", "за", "на", "в" — само пред служебна дума
_WHY_FUNC = r"(?:под|над|в|във|на|за|от|до|с|със|при|след|преди|през|и|или|но|а|което|която|които|че|като|вместо|срещу|въпреки|заради|поради|докато|когато|ако|защото|понеже|макар|дори|също|още)\b"
_WHY_PHRASE = re.compile(
    rf"(?<!\S)(?:(?:на|от|до|през|в|след|преди)\s+)?(?P<d>\d{{1,2}}\s+{_WHY_MONTHS}|\d{{4}}\s?г\.)(?![\w])"
    rf"|(?<!\S)(?:{_WHY_ADV}\s+)*(?P<p>{_WHY_PREP}\s+(?:{_WHY_ADV}\s+)*)?(?P<n>(?<![\w-]){_WHY_NUM}{_WHY_UNIT})(?![\w])(?P<of>\s+от(?=\s))?", re.I)
_WHY_COPULA = {"е", "са", "беше", "бяха", "бъде", "бил", "била", "били", "достига", "достигна", "възлиза", "възлизат", "стига", "стигна"}
_WHY_SENT = re.compile(r"(?<=[.!?…])\s+(?=[A-ZА-Я„\"(\d])")                                        # не след "млрд. долара", "2024 г. усилва"
_WHY_CLAUSE = re.compile(r"(\s[—–]\s|;\s|,\s)")
_WHY_NAME = re.compile(_NUM_NAME_RE.pattern + r"|\b[A-Za-z]+-?\d+\b", re.I)                          # + слети с име: FY2028, Mag7, GLP-1


def _why_extra(s: str, have: set) -> list[str]:
    return [x for x in _NUM_RE.findall(_WHY_NAME.sub(" ", s)) if x.replace(",", ".") not in have]


def _why_trim_sentence(sent: str, have: set) -> tuple[str, list[str]]:
    """Едно изречение → (изречението без частите с числа извън източника, махнатите части). Нечетимо (под 4 думи) или с останало число → ("", [цялото изречение])."""
    if not _why_extra(sent, have):
        return sent, []
    masks: list[str] = []
    s = _WHY_NAME.sub(lambda m: (masks.append(m.group(0)), f"\x00{len(masks) - 1}\x00")[1], sent)       # имената ("S&P 500", "10-year") не се пипат
    removed: list[str] = []

    def repl(m):
        if m.group("d"):
            if not _why_extra(m.group("d"), have):
                return m.group(0)
            removed.append(m.group(0).strip())
            return " "
        if not _why_extra(m.group("n"), have):
            return m.group(0)
        removed.append(m.group(0).strip())
        head = (m.group("p") or "").split()[0] if m.group("p") else ""
        nxt = m.string[m.end():]
        if head.lower() in ("с", "със", "за", "на", "в", "във") and (m.group("of") or (re.match(r"\s+\w", nxt) and not re.match(rf"\s+{_WHY_FUNC}", nxt, re.I))):
            if head.lower() not in ("с", "със"):
                return f" {head} "
            w = re.match(r"\s+(\w)", nxt).group(1).lower() if re.match(r"\s+\w", nxt) else ""
            return " " + ("С" if head[0] == "С" else "с") + ("ъс" if w and w in "сз" else "") + " "         # "със спад"
        return " "
    out = re.sub(r"\x00(\d+)\x00", lambda m: masks[int(m.group(1))], _WHY_PHRASE.sub(repl, s))
    parts, orig = _WHY_CLAUSE.split(out), _WHY_CLAUSE.split(sent)
    if removed and len(parts) > 1 and len(parts) == len(orig):                                         # клауза, чийто предикат беше числото ("Печалбата е +40% — …"), пада цяла
        segs, seps = parts[0::2], parts[1::2]
        keep = [(seps[k - 1] if k else "", seg) for k, seg in enumerate(segs)
                if not (_why_extra(orig[0::2][k], have) and (len(re.findall(r"\w+", seg)) < 2 or re.findall(r"\w+", seg)[-1].lower() in _WHY_COPULA))]
        out = "".join((sep if i else "") + seg for i, (sep, seg) in enumerate(keep))
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"^[,;—–\s]+", "", re.sub(r"\(\s*\)", "", out))
    out = re.sub(r"[,;]\s*([.!?])$", r"\1", out)
    if out[:1].islower():
        out = out[0].upper() + out[1:]
    if _why_extra(out, have) or len(re.findall(r"\w+", out)) < 4:
        return "", [sent]
    return out, removed


def _why_numbers(why: str, source: str) -> tuple[str, list[str]]:
    """
    19.10.2026 (С3): число в "why", което го няма в заглавието и резюмето на източника (pool[i]: t, d — това вижда моделът); (остатък, махнати). Числата от име или срок не се броят
    (_NUM_NAME_RE, от 29.10 и слетите с име — FY2028, Mag7, GLP-1). Измерено върху 704 реда в 89 брифа: 38 "why" с число извън заглавието (резюмето не се пази в брифа — горна граница),
    най-често "~20% от световния петролен трафик" за Ормузкия проток (8 пъти) — фон на модела, не факт от новината.
    29.10.2026 (разходката, т. 3): до 29.10 падаше цялото изречение — "why" е обикновено едно изречение и оставаше празно (3 от 767 новини: 23.10 AP за jobless claims, 29.10 CNBC и FT
    за Fed). Сега пада само частта с числото (_why_trim_sentence); цялото изречение — само ако остатъкът е под 4 думи или пак носи число. Върху историята (39 "why" с число извън
    заглавието, 13.06–29.10): 39 изрязани, 0 празни; 2 от 39 се четат накъсо ("приходи на OpenAI вместо очакваните разклатиха…", "добавили към инфлацията в категории стоки").
    Изреченията се делят само пред главна буква / цифра / кавичка — не след "млрд. долара" (до 29.10 там се делеше).
    """
    have = {x.replace(",", ".") for x in _NUM_RE.findall(source or "")}                      # източникът — всичките му числа (и "19-year high")
    kept, removed = [], []
    for sent in _WHY_SENT.split((why or "").strip()):
        t, r = _why_trim_sentence(sent, have)
        if t:
            kept.append(t)
        removed += r
    return " ".join(kept).strip(), removed


def _source_rank(source) -> int:
    """Мястото на източника в config.NEWS_SOURCE_PRIORITY (по-малко = по-надежден); непознат — след всички."""
    order = config.NEWS_SOURCE_PRIORITY
    return order.index(source) if source in order else len(order)


def _also_group(also, i: int, pool: list[dict], seen: set, dropped: list) -> list[int]:
    """
    29.10.2026 (разходката, т. 3–4, решение 2): "also" от модела — другите заглавия в пула за СЪЩОТО събитие ([{"i", "h"}] или индекси). Всяко минава проверките на основното
    (валиден индекс, неизползван, ехото на първите 6 думи — _echo_index, но БЕЗ поправка на индекса: ехо на друго заглавие = друга история); неминалите са в причините.
    Връща групата: [i] + приетите. Чиста функция.
    """
    group = [i]
    for a in also if isinstance(also, list) else []:
        k, h = (a.get("i"), a.get("h")) if isinstance(a, dict) else (a, None)
        if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k < len(pool) or k in seen or k in group:
            dropped.append({"i": k, "reason": "също: невалиден или вече използван индекс", "of": i})
            continue
        j, note = _echo_index(h, k, pool, seen | set(group))
        if j != k:                                                           # за "също" — без поправка по ехото: друго заглавие значи друга история
            dropped.append({"i": k, "reason": "също: ехото не съвпада със заглавието", "of": i, "h": h})
            continue
        group.append(k)
    return group


def pick_verbatim(items, pool: list[dict], max_items: int) -> tuple[list[dict], list[dict]]:
    """
    15.10.2026: заглавието е ДОСЛОВНО от източника — моделът връща само индекса "i" в пула, "why" и по желание превод "headline_bg"; кодът взема
    заглавието и източника от пула (до 15.10 моделът пишеше заглавието сам и го превеждаше наполовина: "Dollar languishes като…", "Iran deploy нови тактики",
    "awards $2 в damages" на 14.10; 88 от 688 заглавия в историята са смесени). Ред без валиден индекс, повторен индекс или празно "why" отпада (в причините).
    Превод с число, което го няма в оригинала, или без мащаба му се маха (_translation_ok). Чиста функция → (новини, отпаднали).
    29.10.2026: една история — една новина. "also" (_also_group) слива заглавията за същото събитие в един ред; "why" е за събитието (числата и от 16.11 твърденията
    — claim_check — се сверяват с всички заглавия и резюмета в групата), останалите са в row["also"] = [{source, headline, link}] по надеждност на източника — „също: FT, Reuters“.
    16.11.2026: основното е винаги "i" на модела (до 16.11 — най-надеждният източник в групата). Заглавие, вече влязло в група, не може да е отделна новина ("повторен индекс").
    """
    out, seen, dropped = [], set(), []
    for n in items or []:
        if not isinstance(n, dict):
            continue
        i = n.get("i")
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(pool):
            dropped.append({"i": i, "reason": "няма валиден индекс в пула", "headline": n.get("headline")})
            continue
        if i in seen:
            dropped.append({"i": i, "reason": "повторен индекс"})
            continue
        why = (n.get("why") or "").strip()
        if not why and config.NEWS_AI_WHY:                                   # 20.11.2026 (пакет 20.11, т. 1): без AI „защо“ — празното е нормата
            dropped.append({"i": i, "reason": "празно why"})
            continue
        j, note = _echo_index(n.get("h"), i, pool, seen)                 # 19.10.2026 (С3): ехото на заглавието срещу pool[i]
        if j is None:
            dropped.append({"i": i, "reason": note, "h": n.get("h"), "pool_title": pool[i]["title"]})
            continue
        if j != i:
            dropped.append({"i": i, "reason": note, "h": n.get("h")})        # не отпада — информация за дневника
            i = j
        if i in seen:
            dropped.append({"i": i, "reason": "повторен индекс"})
            continue
        seen.add(i)
        group = _also_group(n.get("also"), i, pool, seen, dropped)          # 29.10.2026: една история — една новина (заглавията за същото събитие)
        seen.update(group)
        # 16.11.2026 (пакет 16.11, т. 1, Nvidia): основното заглавие е ВИНАГИ това на модела (i) — „защо“ е писано за него и за резюмето му. До 16.11 основното ставаше
        # заглавието от по-надеждния източник в групата (29.10; от 11.11 — освен ако числата в „защо“ са само в i): на 16.11 „защо“ за FT „Bessent says Nvidia needs
        # ‘shake-up’ with external CEO“ (Treasury, експортни ограничения, външен CEO — от резюмето му) стоеше под Reuters „Trump administration to name Nvidia … 'national
        # champions'“ — друга история, слята от модела в групата. Измерено 30.10–16.11: 29 смени в 92 новини. Другите в групата — в „също“, по надеждност на източника.
        main = i
        r = pool[main]
        source_text = " ".join(f"{pool[k]['title']} {pool[k].get('summary') or ''}" for k in group)
        why, cut = _why_numbers(why, source_text) if why else (why, [])
        if cut:
            dropped.append({"i": i, "reason": "число в why, което го няма в заглавието и резюмето — махната е частта с него", "removed": cut})
        try:                                                                     # 16.11.2026 (т. 1): твърдение (институция, държава, мярка) без опора в заглавията и резюметата
            from src import claim_check
            why, unsup = claim_check.check(why, source_text) if why else (why, [])
            if unsup:
                dropped.append({"i": i, "reason": "твърдение в why, което го няма в заглавията и резюметата на групата — махнато изречението", "removed": unsup})
        except Exception as e:
            print(f"[news] проверката на твърденията пропусната: {type(e).__name__}: {e}")
        row = {"headline": r["title"], "source": r.get("source"), "why": why, "source_text": source_text[:2000]}      # 06.11.2026 (т. 8): source_text — за проверката на думите (ai_brief.check_news_why_terms го маха)
        if r.get("published"):
            row["published"] = r["published"]                                   # 20.11.2026 (пакет 20.11, т. 1): часът на заглавието
        if r.get("link"):
            row["link"] = r["link"]                                          # 29.10.2026: линкът към статията — от пула, по същия индекс
        others = sorted((k for k in group if k != main), key=lambda k: (_source_rank(pool[k].get("source")), group.index(k)))
        if others:
            row["also"] = [{"source": pool[k].get("source"), "headline": pool[k]["title"], **({"link": pool[k]["link"]} if pool[k].get("link") else {})} for k in others]
        bg = (n.get("headline_bg") or "").strip() if isinstance(n.get("headline_bg"), str) and main == i else ""
        if bg and re.search(r"[А-Яа-я]", bg) and bg != r["title"]:
            if _translation_ok(bg, r["title"]):
                row["headline_bg"] = bg
            else:
                dropped.append({"i": i, "reason": "преводът на заглавието е махнат (число или мащаб, различни от оригинала)", "headline_bg": bg})
        out.append(row)
    return out[:max_items], dropped


# 29.10.2026 (разходката, т. 3–4, решение 2): една история — една новина. Същото събитие = същото решение, данни, сделка, изказване или пазарно движение със същата причина;
# същата тема (две различни новини за Fed) НЕ е. Разпознава го моделът — проверката по общи думи не стига: на 29.10 „Alphabet sinks 10%…“ (CNBC) и „Google shares tumble 10%…“ (FT)
# нямат обща дума освен „10%“, а „Fed“ стои в различни новини (измерено на ръка в последните 24 брифа — виж config.NEWS_SOURCE_PRIORITY). Кодът проверява индексите и ехото.
ALSO_RULE = ("Една история — една новина: ако няколко заглавия (от различни източници или от един) са за СЪЩОТО събитие — същото решение, същите данни, същата сделка, "
             "същото изказване или същото пазарно движение със същата причина — върни ги като ЕДНА новина: \"i\" е заглавието за събитието, в \"also\" са останалите "
             "([{\"i\": …, \"h\": първите 6 думи}]), а \"why\" е за събитието като цяло. Същата тема НЕ е същото събитие (две различни новини за Fed са две новини). "
             "Без дубли — \"also\" е празно или липсва.")
LAST_DIAG: dict = {}
# 19.10.2026 (трети преглед, т. 12): празните новини не са тиха липса — {"ok", "reason", "count"} → банер в брифа (data_warnings)
LAST_STATUS: dict = {}


LAST_TRANSLATION: dict = {}


def finish_rows(rows: list[dict], matchers: list | None, pool_all: list | None = None) -> None:
    """
    20.11.2026 (пакет 20.11, т. 1): всяка новина — кои наши тикъри засяга (priority_hits върху заглавието и „също“) и преводът на български (src/translate.py, с проверка; без
    AI „защо“). Провал на превода → оригиналът с бележка. Мутира rows; отчетът — LAST_TRANSLATION.
    """
    for r in rows or []:
        texts = [r.get("headline") or ""] + [a.get("headline") or "" for a in r.get("also") or []]
        r["ours"] = sorted({t for x in texts for t in priority_hits(x, matchers or [])})
    LAST_TRANSLATION.clear()
    if config.NEWS_TRANSLATE and rows:
        try:
            from src import translate, top_themes
            caps = top_themes._later_caps([x.get("title") or "" for x in pool_all or []] + [r.get("headline") or "" for r in rows])
            LAST_TRANSLATION.update(translate.apply(rows, caps))
        except Exception as e:
            print(f"[news] преводът пропуснат: {type(e).__name__}: {e}")
            for r in rows:
                r.setdefault("translation_note", "преводът не се получи")



def _select_user(pool: list[dict], max_items: int) -> str:
    """Промптът на подбора (без промяна от 20.11; 23.11 — изнесен, за да се ползва и в повторния опит). Всяко заглавие с индекс "i" — заглавието в брифа е дословно от пула."""
    compact = [{"i": k, "s": r["source"], "t": r["title"], "d": r.get("summary") or ""} for k, r in enumerate(pool)]
    return (
        "От тези новини извлечи само тези с пазарно значение — геополитика, Fed, "
        "макро release-и (CPI, jobs report/nonfarm payrolls, GDP, PCE, unemployment), "
        "секторни движения, суровини, "
        # FIX 2026-09-18: регулаторни/законодателни събития нямаха СВОЯ категория
        # и системно отпадаха. Потвърдено на 18.09 — Reuters "US securities
        # regulator rolls out five-year exemption for tokenized stock trading"
        # беше в суровия пул и не влезе в осемте.
        "регулаторни и законодателни събития с пазарен ефект (решения и правила "
        "на SEC/CFTC/FTC/ЕК, гласувания в Конгреса, антитръст, тарифи, санкции). "
        + (f"Максимум {max_items} новини, всяка с едно "
           "изречение защо е важна за пазарите днес. Заглавието НЕ го пишеш и не го превеждаш в \"why\" — кодът показва оригиналното "
           "заглавие дословно по индекса \"i\" от списъка.\n" if config.NEWS_AI_WHY else
           f"Максимум {max_items} новини. НЕ пишеш коментар и не превеждаш — само избираш по индекса \"i\"; кодът показва оригиналното заглавие дословно.\n") +
        # 19.10.2026 (трети преглед, С3 + "why" = заглавието): ехо на заглавието за проверка на индекса; why — само ефектът, без преразказ и без числа извън източника
        "В \"h\" повтори ДОСЛОВНО първите 6 думи на заглавието (\"t\") по индекса \"i\" — кодът проверява, че индексът е верен.\n"
        + ("\"why\" е САМО ефектът за пазарите (кои активи/сектори и в каква посока) — НЕ преразказва заглавието и не носи числа, "
           "които ги няма в \"t\" или \"d\" на същата новина.\n" if config.NEWS_AI_WHY else "") +
        # 29.10.2026 (разходката, т. 3–4, решение 2): една история — една новина
        f"{ALSO_RULE}\n\n"
        f"НОВИНИ:\n{json.dumps(compact, ensure_ascii=False, default=str)}\n\n"
        + ('Върни само JSON: {"news": [{"i": 0, "h": "първите шест думи на заглавието", "why": "...", "also": [{"i": 5, "h": "първите шест думи"}]}]}' if config.NEWS_AI_WHY else
           'Върни само JSON: {"news": [{"i": 0, "h": "първите шест думи на заглавието", "also": [{"i": 5, "h": "първите шест думи"}]}]}')
    )


def news_selection_call(user: str, max_tokens: int) -> str:
    """AI извикването на подбора — именувана функция (етикетът „Значими новини“ в brief["ai_usage"])."""
    from src import ai_brief
    return ai_brief._call_claude(_SYSTEM, user, max_tokens=max_tokens)


def _ai_pick(pool: list[dict], max_items: int, call=None) -> tuple[list[dict], list[dict], list]:
    """Един опит на AI подбора → (новини, отпаднали, върнатото от модела). Хвърля при грешка / отрязан отговор."""
    from src import ai_brief
    text = (call or news_selection_call)(_select_user(pool, max_items), config.NEWS_SELECT_MAX_TOKENS)
    data = ai_brief._parse_json(text)
    got = data.get("news", []) if isinstance(data, dict) else []
    news, dropped = pick_verbatim(got, pool, max_items)
    return news, dropped, got


def code_pick(themes_: list[dict] | None, pool_all: list[dict] | None, matchers: list | None, max_items: int = 8, front: list[dict] | None = None) -> list[dict]:
    """
    23.11.2026 (пакет 23.11, т. 1): резервният подбор от кода — когато AI подборът падне два пъти. По реда на приоритета в пула: първо „Топ теми“ (представителното заглавие на
    темата, „също“ — по едно от другите издатели), после заглавията за нашите тикъри и компании (позициите в книгите, наблюдаваните, картите, „Нощта“, отчетите за деня — по реда
    на списъка; на тикър — най-новото заглавие, „също“ — следващите); нищо от двете → първата страница (config.NEWS_FRONT_FEEDS). Без оценка за значимост и без коментар;
    row["picked_by"] = "theme" / "ours" / "front". Чиста функция.
    """
    pool_all = list(pool_all or [])
    full = {(r.get("title") or "").lower()[:90]: r for r in pool_all + list(front or [])}
    used: set = set()
    rows: list[dict] = []
    n_also = config.NEWS_CODE_PICK_ALSO

    def mk(it: dict, others: list[dict], by: str) -> dict:
        r0 = full.get((it.get("title") or "").lower()[:90], it)
        row = {"headline": it["title"], "source": it.get("source") or r0.get("source"), "why": "", "picked_by": by}
        if it.get("published") or r0.get("published"):
            row["published"] = it.get("published") or r0.get("published")
        if r0.get("link"):
            row["link"] = r0["link"]
        al = []
        for o in others[:n_also]:
            ro = full.get((o.get("title") or "").lower()[:90], o)
            al.append({"source": o.get("source") or ro.get("source"), "headline": o["title"], **({"link": ro["link"]} if ro.get("link") else {})})
        if al:
            row["also"] = al
        for x in [it] + others[:n_also]:
            used.add((x.get("title") or "").lower()[:90])
        return row

    for t in themes_ or []:
        if len(rows) >= max_items:
            break
        its = [i for i in t.get("items") or [] if i.get("title")]
        head = next((i for i in its if i["title"] == t.get("headline")), its[0] if its else None)
        if not head or (head["title"].lower()[:90] in used):
            continue
        rest, pubs = [], {head.get("source")}
        for i in its:                                                   # „също“ — първо по едно от другите издатели
            if i is not head and i.get("source") not in pubs:
                rest.append(i); pubs.add(i.get("source"))
        rest += [i for i in its if i is not head and i not in rest]
        rows.append(mk(head, rest, "theme"))
    by_t: dict = {}
    for r in pool_all:
        k = (r.get("title") or "").lower()[:90]
        if not k or k in used:
            continue
        hits = priority_hits(r.get("title"), matchers or [])
        if hits:
            by_t.setdefault(hits[0], []).append(r)
    for t, _ in matchers or []:
        if len(rows) >= max_items:
            break
        its = sorted((i for i in by_t.get(t) or [] if (i.get("title") or "").lower()[:90] not in used), key=lambda i: i.get("published") or "", reverse=True)
        if its:
            rows.append(mk(its[0], its[1:], "ours"))
    if not rows:
        for it in (front or [])[:max(1, max_items // 2)]:
            if it.get("title") and it["title"].lower()[:90] not in used:
                rows.append(mk(it, [], "front"))
    return rows[:max_items]


def select(pool: list[dict], raw: list[dict], matchers: list | None, max_items: int = 8, call=None) -> dict:
    """
    23.11.2026 (пакет 23.11, т. 1): трите пътя на подбора → {"news", "path", "attempts", "error"}; попълва LAST_DIAG и LAST_STATUS["path"].
      "ai"       — AI подборът с лимит config.NEWS_SELECT_MAX_TOKENS (до 23.11 — 1000);
      "ai_retry" — първият отговор е отрязан (TruncatedResponse) → повторен опит с първите config.NEWS_RETRY_POOL_SHARE от пула (темите и нашите тикъри са първи);
      "code"     — повторният опит пак падна / друга грешка / AI не върна нито една валидна новина → code_pick (теми + нашите тикъри), с превод.
    """
    from src import ai_brief
    attempts, news, dropped, got, path, err = [], [], [], [], None, None
    for k, part in enumerate((pool, pool[:max(1, int(len(pool) * config.NEWS_RETRY_POOL_SHARE))])):
        try:
            news, dropped, got = _ai_pick(part, max_items, call)
            attempts.append({"pool": len(part), "max_tokens": config.NEWS_SELECT_MAX_TOKENS, "result": "ok", "kept": len(news)})
            if news:
                path = "ai" if k == 0 else "ai_retry"
            else:
                err = "AI не върна нито една валидна новина"
            break
        except ai_brief.TruncatedResponse as ex:
            attempts.append({"pool": len(part), "max_tokens": config.NEWS_SELECT_MAX_TOKENS, "result": "TruncatedResponse"})
            err = f"отрязан отговор ({config.NEWS_SELECT_MAX_TOKENS} токена)"
            if ai_brief.TRUNCATIONS and ai_brief.TRUNCATIONS[-1].get("section") == "Значими новини":       # банерът „Отрязан AI отговор“ казва какво последва
                ai_brief.TRUNCATIONS[-1]["then"] = (f"повторен опит с по-малък вход ({max(1, int(len(pool) * config.NEWS_RETRY_POOL_SHARE))} от {len(pool)} заглавия)"
                                                    if k == 0 else "резервен подбор от кода (теми и нашите тикъри)")
            print(f"[news] опит {k + 1}: {ex}" + (" — повторен опит с по-малък вход" if k == 0 else ""))
            continue
        except Exception as ex:
            attempts.append({"pool": len(part), "max_tokens": config.NEWS_SELECT_MAX_TOKENS, "result": type(ex).__name__})
            err = f"{type(ex).__name__}"
            print(f"[news] Claude филтър неуспешен: {ex}")
            break
    if path is None:
        news, dropped, got = code_pick(LAST_THEMES, list(raw) + list(LAST_FRONT), matchers, max_items, front=list(LAST_FRONT)), [], []
        path = "code"
        print(f"[news] ⚠ резервен подбор от кода ({err}): {len(news)} реда")
    finish_rows(news, matchers, list(raw) + list(LAST_FRONT))                  # 20.11.2026 (пакет 20.11, т. 1): нашите тикъри и преводът
    LAST_DIAG.clear()
    LAST_DIAG.update(returned=len(got) if path != "code" else None, kept=len(news), dropped=dropped, translation=dict(LAST_TRANSLATION),
                     pool=[[r.get("source"), r.get("published"), r["title"]] for r in pool],     # 18.11.2026 (т. 1): пулът, който видя моделът
                     no_echo=sum(1 for n in got if isinstance(n, dict) and not (isinstance(n.get("h"), str) and n["h"].strip())),
                     path=path, attempts=attempts, error=err if path != "ai" else None,
                     picked_by={b: sum(1 for r in news if r.get("picked_by") == b) for b in ("theme", "ours", "front") if any(r.get("picked_by") == b for r in news)})
    for d in dropped:
        print(f"[news] ⚠ {d['reason']}: {d}")
    LAST_STATUS["path"] = path
    return {"news": news, "path": path, "attempts": attempts, "error": None if news else (err or "нито едно заглавие за резервния подбор")}


def significant_news(max_items: int = 8, since: dt.datetime | None = None, priority: list | None = None) -> list[dict]:
    """
    Връща [{headline, source, why, headline_bg?}] — до max_items пазарно значими новини; headline е ДОСЛОВНО от източника (15.10.2026, pick_verbatim).
    Кешира за деня. Празен списък при провал (graceful degradation).
    02.11.2026 (т. 4): since — началото на прозореца (main: sessions.news_window_start — предишният бриф); без него — последните 24 ч. Таванът на заглавията към филтъра —
    config.NEWS_MAX_TO_FILTER на всеки 24 ч от прозореца (понеделник 300).
    """
    today = dt.date.today().isoformat()
    LAST_STATUS.clear()
    LAST_STATUS.update(ok=False, reason="не завърши", count=0)
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today:
                LAST_STATUS.update(ok=bool(cached.get("news")), reason="" if cached.get("news") else "кешът за деня е празен", count=len(cached.get("news") or []))
                LAST_WINDOW.clear(); LAST_WINDOW.update(cached.get("window") or {})
                LAST_THEMES.clear(); LAST_THEMES.extend(cached.get("themes") or [])           # 19.11.2026 (т. 2)
                if cached.get("path"):                                                          # 23.11.2026 (т. 1): пътят на подбора
                    LAST_DIAG.clear(); LAST_DIAG.update(path=cached["path"], attempts=cached.get("attempts") or [])
                    LAST_STATUS["path"] = cached["path"]
                return cached.get("news", [])
        except Exception:
            pass

    matchers = priority_matchers(priority)                               # 18.11.2026 (поправка): приоритетът преди тавана
    raw = gather_raw(hours=24, since=since, **({"keep": lambda t: bool(priority_hits(t, matchers))} if matchers else {}))
    if not raw:
        print("[news] нула източници върнаха данни — пропускам секцията")
        LAST_STATUS.update(reason="нито един RSS източник не върна заглавия")
        return []

    # ограничаваме промпта; 15.10.2026: всяко заглавие с индекс "i" — заглавието на брифа е дословно от пула по този индекс
    days = max(1, round((dt.datetime.now(dt.timezone.utc) - since).total_seconds() / 86400)) if since else 1     # 02.11.2026: на 24 ч от прозореца
    ordered, n_hit = prioritize(raw, matchers)
    # 19.11.2026 (пакет 19.11, т. 2): топ темите — техните заглавия влизат ПЪРВИ и задължително (независимо от тикърите), после приоритетът, после останалите
    LAST_THEMES.clear()
    try:
        from src import top_themes
        LAST_THEMES.extend(top_themes.themes(list(raw) + list(LAST_FRONT)))
        first = top_themes.pool_items(LAST_THEMES)
        keys = {it["title"].lower()[:90] for it in first}
        full = {r["title"].lower()[:90]: r for r in list(raw) + list(LAST_FRONT)}
        first = [{**full.get(it["title"].lower()[:90], it), "theme": it.get("theme")} for it in first]
        ordered = first + [r for r in ordered if r["title"].lower()[:90] not in keys]
    except Exception as e:
        print(f"[news] топ темите пропуснати: {type(e).__name__}: {e}")
    pool = ordered[:config.NEWS_MAX_TO_FILTER * days]
    # 18.11.2026 (спешно, т. 1): таванът реже след редуването — колко от всеки източник стигнаха до подбора (18.11: 100 от 139 — Reuters 31 от 50, AP 30 от 50)
    LAST_WINDOW.update(pool_total=len(raw), pool_used=len(pool), to_model={k: v["count"] for k, v in source_reach(pool).items()},
                       themes_in_pool=sum(1 for r in pool if r.get("theme")))
    if matchers:                                                         # 18.11.2026 (поправка): колко заглавия минаха напред и за кои тикъри
        LAST_WINDOW["priority"] = {"names": len(matchers), "hits": n_hit, "in_pool": sum(1 for r in pool if r.get("priority")),
                                   "beyond_limit": sum(1 for r in pool if r.get("beyond_limit")),
                                   "tickers": sorted({t for r in pool for t in r.get("priority") or []})}
    out = select(pool, raw, matchers, max_items)
    news = out["news"]
    if out.get("error") and not news:
        LAST_STATUS.update(reason=out["error"])
        return []
    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "news": news, "window": dict(LAST_WINDOW), "themes": list(LAST_THEMES),
                                     "path": LAST_DIAG.get("path"), "attempts": LAST_DIAG.get("attempts")},
                                     ensure_ascii=False, indent=1, default=str))
    except Exception as ex:
        print(f"[news] cache write: {ex}")

    LAST_STATUS.update(ok=bool(news), reason="" if news else f"подборът не върна нито една новина от {len(pool)} заглавия", count=len(news), path=LAST_DIAG.get("path"))
    return news


if __name__ == "__main__":
    raw = gather_raw()
    print(f"Събрани сурови заглавия: {len(raw)}")
    for r in raw[:10]:
        print(f"  [{r['source']}] {r['title'][:90]}")
    print("\nПазарно значими (Claude):")
    for n in significant_news():
        print(f"  • {n['headline']} — {n['why']}")
