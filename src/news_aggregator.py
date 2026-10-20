"""
news_aggregator.py — агрегатор за макро и геополитически новини.

Събира заглавия от последните 24 часа от:
  • RSS: Reuters (business + world), Financial Times, CNBC
  • Публични X/Twitter акаунти през nitter mirror: @unusual_whales, @zerohedge, @elerianm

После подава всичко на Claude с инструкция да извлече само пазарно значимите
(геополитика, Fed, секторни движения, суровини) — максимум 8, всяка с едно
изречение защо е важна днес. Резултатът влиза в макро брифа като „Значими новини".

Бележка за източниците: публичните Reuters RSS емисии и nitter инстанциите са
нестабилни (Reuters спря част от RSS-а; nitter инстанции падат). Затова всичко е
с graceful degradation — ако даден източник падне, просто се прескача; ако ВСИЧКИ
паднат, връщаме празен списък и брифът продължава без секцията (по изискване).

Резултатът се кешира за деня (data/news_cache.json), за да не вика Claude при
повторни пускания.
"""
from __future__ import annotations
import datetime as dt
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
# FIX 2026-09-18: (hours, заглавия) от последния gather_raw В ТОЗИ ПРОЦЕС —
# двама потребители в един run (significant_news + raw_pool), един fetch.
_RAW_MEMO: tuple[int, list[dict]] | None = None


# ──────────────────────────────────────────────────────────────────────────
# RSS
# ──────────────────────────────────────────────────────────────────────────
def _fetch_rss(url: str, source: str, hours: int, limit: int = 15) -> list[dict]:
    if feedparser is None:
        return []
    out = []
    try:
        # сваляме сами с requests (по-устойчиво от feedparser.parse(url) зад UA/таймаут)
        raw = requests.get(url, timeout=15, headers=_UA).content
        feed = feedparser.parse(raw)
        cutoff = time.time() - hours * 3600
        for e in feed.entries[:limit * 2]:
            ts = None
            for key in ("published_parsed", "updated_parsed"):
                if e.get(key):
                    ts = time.mktime(e[key]); break
            if ts is not None and ts < cutoff:
                continue  # по-стара от прозореца
            title = (e.get("title") or "").strip()
            if not title:
                continue
            summary = (e.get("summary") or e.get("description") or "").strip()
            summary = _strip_html(summary)[:300]
            out.append({"source": source, "title": title, "summary": summary})
            if len(out) >= limit:
                break
    except Exception as ex:
        print(f"[news] RSS {source} failed: {ex}")
    return out


def _strip_html(s: str) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(s, "html.parser").get_text(" ", strip=True)
    except Exception:
        import re
        return re.sub(r"<[^>]+>", "", s)


# ──────────────────────────────────────────────────────────────────────────
# Nitter (публичен X mirror) — с няколко инстанции за устойчивост
# ──────────────────────────────────────────────────────────────────────────
def _fetch_nitter(handle: str, limit: int = 8) -> list[dict]:
    instances = config.NITTER_INSTANCES
    for base in instances:
        try:
            url = f"{base.rstrip('/')}/{handle}"
            html = requests.get(url, timeout=12, headers=_UA).text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            tweets = soup.select(".timeline-item .tweet-content")
            rows = []
            for t in tweets[:limit]:
                txt = t.get_text(" ", strip=True)
                if txt:
                    rows.append({"source": f"@{handle}", "title": txt[:280], "summary": ""})
            if rows:
                return rows  # първата работеща инстанция стига
        except Exception as ex:
            print(f"[news] nitter {handle} @ {base} failed: {ex}")
            continue
    return []


# ──────────────────────────────────────────────────────────────────────────
# Събиране
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


def gather_raw(hours: int = 24) -> list[dict]:
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

    FIX 2026-09-18: резултатът се мемоизира В ПРОЦЕСА (_RAW_MEMO), защото вече
    има двама потребители в един run — significant_news() и thesis_reality_check
    през raw_pool(). Без това вторият би платил втори пълен fetch на всички
    източници. Мемото живее само колкото процеса, точно като
    backtest._RESOLVED_THIS_RUN — нов run събира наново.
    """
    global _RAW_MEMO
    if _RAW_MEMO is not None and _RAW_MEMO[0] == hours:
        return _RAW_MEMO[1]
    per_source: list[list[dict]] = []
    dead: list[str] = []
    for src, url in config.NEWS_RSS_FEEDS.items():
        got = _fetch_rss(url, src, hours, limit=config.NEWS_PER_SOURCE_LIMIT)
        if not got:
            dead.append(src)
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
    if config.NEWS_ENABLE_NITTER:
        for handle in config.NITTER_HANDLES:
            items += _fetch_nitter(handle)
    # дедупликация по заглавие
    seen, dedup = set(), []
    for it in items:
        key = it["title"].lower()[:90]
        if key not in seen:
            seen.add(key); dedup.append(it)
    _RAW_MEMO = (hours, dedup)
    return dedup


def raw_pool(hours: int = 24) -> list[dict]:
    """
    Суровият, НЕфилтриран пул заглавия — за потребители, на които филтрираните
    ~8 „значими" новини не стигат.

    FIX 2026-09-18: thesis_reality_check() работеше върху изхода на
    significant_news(), а той се подбира по ПАЗАРНА ЗНАЧИМОСТ ЗА ДЕНЯ —
    оптимизация за макро секцията. Тезите обаче имат тесни домейни (крипто,
    ядрена енергия, полупроводници, отбрана, въглища, финанси), затова общият
    макро филтър системно ги подценява.

    Потвърдено на 18.09.2026: Reuters публикува "US securities regulator rolls
    out five-year exemption for tokenized stock trading" (SEC Innovation
    Exemption, пряко релевантна за Крипто регулация тезата) 14.5ч преди run-а,
    т.е. ВЪТРЕ в прозореца; CNBC даде и свързаната "Tokenization is set to
    change stock trading". И двете стигнаха до суровия gather. Нито една не
    влезе в осемте — те бяха изцяло Fed/BOJ/петрол/доходности, което за самата
    макро секция е правилен подбор. Тезовата проверка обаче остана сляпа.

    Разширяване на филтърните категории (виж regulatory категорията в
    significant_news) помага, но не решава структурно: осем места на ден са
    тясно гърло, каквито и категории да има. Затова тезовата проверка вече
    получава целия пул.

    Graceful: провал → празен списък, извикващият продължава без проверка.
    """
    try:
        return gather_raw(hours)
    except Exception as e:
        print(f"[news] raw_pool failed: {e}")
        return []


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


def _first_words(s: str, n: int = 6) -> list[str]:
    return [w.casefold().strip("'’") for w in _WORD_RE.findall(s or "")][:n]


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


def _why_numbers(why: str, source: str) -> tuple[str, list[str]]:
    """
    19.10.2026 (С3): изречение в "why" с число, което го няма в заглавието и резюмето на източника (pool[i]: t, d — това вижда моделът) → махнато; (остатък, махнати).
    Числата от име или срок не се броят (_NUM_NAME_RE). Измерено върху 704 реда в 89 брифа: 38 "why" с число извън заглавието (резюмето не се пази в брифа — горна граница),
    най-често "~20% от световния петролен трафик" за Ормузкия проток (8 пъти) — фон на модела, не факт от новината.
    """
    have = {x.replace(",", ".") for x in _NUM_RE.findall(source or "")}                      # източникът — всичките му числа (и "19-year high")
    kept, removed = [], []
    for sent in re.split(r"(?<=[.!?])\s+", (why or "").strip()):
        extra = [x for x in _NUM_RE.findall(_NUM_NAME_RE.sub(" ", sent)) if x.replace(",", ".") not in have]
        (removed if extra else kept).append(sent)
    return " ".join(kept).strip(), removed


def pick_verbatim(items, pool: list[dict], max_items: int) -> tuple[list[dict], list[dict]]:
    """
    15.10.2026: заглавието е ДОСЛОВНО от източника — моделът връща само индекса "i" в пула, "why" и по желание превод "headline_bg"; кодът взема
    заглавието и източника от пула (до 15.10 моделът пишеше заглавието сам и го превеждаше наполовина: "Dollar languishes като…", "Iran deploy нови тактики",
    "awards $2 в damages" на 14.10; 88 от 688 заглавия в историята са смесени). Ред без валиден индекс, повторен индекс или празно "why" отпада (в причините).
    Превод с число, което го няма в оригинала, или без мащаба му се маха (_translation_ok). Чиста функция → (новини, отпаднали).
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
        if not why:
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
        r = pool[i]
        why, cut = _why_numbers(why, f"{r['title']} {r.get('summary') or ''}")
        if cut:
            dropped.append({"i": i, "reason": "изречение в why с число, което го няма в заглавието и резюмето — махнато", "removed": cut})
        row = {"headline": r["title"], "source": r.get("source"), "why": why}
        bg = (n.get("headline_bg") or "").strip() if isinstance(n.get("headline_bg"), str) else ""
        if bg and re.search(r"[А-Яа-я]", bg) and bg != r["title"]:
            if _translation_ok(bg, r["title"]):
                row["headline_bg"] = bg
            else:
                dropped.append({"i": i, "reason": "преводът на заглавието е махнат (число или мащаб, различни от оригинала)", "headline_bg": bg})
        out.append(row)
    return out[:max_items], dropped


LAST_DIAG: dict = {}
# 19.10.2026 (трети преглед, т. 12): празните новини не са тиха липса — {"ok", "reason", "count"} → банер в брифа (data_warnings)
LAST_STATUS: dict = {}


def significant_news(max_items: int = 8) -> list[dict]:
    """
    Връща [{headline, source, why, headline_bg?}] — до max_items пазарно значими новини; headline е ДОСЛОВНО от източника (15.10.2026, pick_verbatim).
    Кешира за деня. Празен списък при провал (graceful degradation).
    """
    today = dt.date.today().isoformat()
    LAST_STATUS.clear()
    LAST_STATUS.update(ok=False, reason="не завърши", count=0)
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today:
                LAST_STATUS.update(ok=bool(cached.get("news")), reason="" if cached.get("news") else "кешът за деня е празен", count=len(cached.get("news") or []))
                return cached.get("news", [])
        except Exception:
            pass

    raw = gather_raw(hours=24)
    if not raw:
        print("[news] нула източници върнаха данни — пропускам секцията")
        LAST_STATUS.update(reason="нито един RSS източник не върна заглавия")
        return []

    # ограничаваме промпта; 15.10.2026: всяко заглавие с индекс "i" — заглавието на брифа е дословно от пула по този индекс
    pool = raw[:config.NEWS_MAX_TO_FILTER]
    compact = [{"i": k, "s": r["source"], "t": r["title"], "d": r["summary"]} for k, r in enumerate(pool)]
    user = (
        "От тези новини извлечи само тези с пазарно значение — геополитика, Fed, "
        "макро release-и (CPI, jobs report/nonfarm payrolls, GDP, PCE, unemployment), "
        "секторни движения, суровини, "
        # FIX 2026-09-18: регулаторни/законодателни събития нямаха СВОЯ категория
        # и системно отпадаха. Потвърдено на 18.09 — Reuters "US securities
        # regulator rolls out five-year exemption for tokenized stock trading"
        # беше в суровия пул и не влезе в осемте.
        "регулаторни и законодателни събития с пазарен ефект (решения и правила "
        "на SEC/CFTC/FTC/ЕК, гласувания в Конгреса, антитръст, тарифи, санкции). "
        f"Максимум {max_items} новини, всяка с едно "
        "изречение защо е важна за пазарите днес. Заглавието НЕ го пишеш и не го превеждаш в \"why\" — кодът показва оригиналното "
        "заглавие дословно по индекса \"i\" от списъка. По желание дай кратък превод на заглавието на български в \"headline_bg\" "
        "(само превод — без нови факти, със същите числа и мащаб: million → млн, billion → млрд).\n"
        # 19.10.2026 (трети преглед, С3 + "why" = заглавието): ехо на заглавието за проверка на индекса; why — само ефектът, без преразказ и без числа извън източника
        "В \"h\" повтори ДОСЛОВНО първите 6 думи на заглавието (\"t\") по индекса \"i\" — кодът проверява, че индексът е верен. "
        "\"why\" е САМО ефектът за пазарите (кои активи/сектори и в каква посока) — НЕ преразказва заглавието (то е в headline_bg) и не носи числа, "
        "които ги няма в \"t\" или \"d\" на същата новина.\n\n"
        f"НОВИНИ:\n{json.dumps(compact, ensure_ascii=False, default=str)}\n\n"
        'Върни само JSON: {"news": [{"i": 0, "h": "първите шест думи на заглавието", "why": "...", "headline_bg": "..."}]}'
    )
    try:
        from src import ai_brief
        text = ai_brief._call_claude(_SYSTEM, user, max_tokens=2000)
        data = ai_brief._parse_json(text)
        news, dropped = pick_verbatim(data.get("news", []) if isinstance(data, dict) else [], pool, max_items)
        LAST_DIAG.clear()
        got = data.get("news", []) if isinstance(data, dict) else []
        LAST_DIAG.update(returned=len(got), kept=len(news), dropped=dropped,
                         no_echo=sum(1 for n in got if isinstance(n, dict) and not (isinstance(n.get("h"), str) and n["h"].strip())))   # 19.10.2026 (С3)
        for d in dropped:
            print(f"[news] ⚠ {d['reason']}: {d}")
    except Exception as ex:
        print(f"[news] Claude филтър неуспешен: {ex}")
        LAST_STATUS.update(reason=f"подборът (AI) не успя: {type(ex).__name__}")
        return []

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "news": news},
                                     ensure_ascii=False, indent=1, default=str))
    except Exception as ex:
        print(f"[news] cache write: {ex}")

    LAST_STATUS.update(ok=bool(news), reason="" if news else f"подборът не върна нито една новина от {len(pool)} заглавия", count=len(news))
    return news


if __name__ == "__main__":
    raw = gather_raw()
    print(f"Събрани сурови заглавия: {len(raw)}")
    for r in raw[:10]:
        print(f"  [{r['source']}] {r['title'][:90]}")
    print("\nПазарно значими (Claude):")
    for n in significant_news():
        print(f"  • {n['headline']} — {n['why']}")
