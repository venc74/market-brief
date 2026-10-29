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
            row = {"source": source, "title": title, "summary": summary}
            link = _safe_link(e.get("link"))                       # 29.10.2026 (разходката, т. 3–4): заглавието в брифа е линк към статията
            if link:
                row["link"] = link
            pt = e.get("published_parsed") or e.get("updated_parsed")
            if pt:
                row["published"] = time.strftime("%Y-%m-%dT%H:%MZ", pt)     # 29.10.2026: колко назад стига фийдът (CoinDesk държи 25); feedparser дава UTC
            out.append(row)
            if len(out) >= limit:
                break
    except Exception as ex:
        print(f"[news] RSS {source} failed: {ex}")
    return out


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
    29.10.2026: една история — една новина. "also" (_also_group) слива заглавията за същото събитие в един ред: основното е от най-надеждния източник в групата
    (config.NEWS_SOURCE_PRIORITY; ако не е "i" на модела, преводът отпада — той е на другото заглавие), "why" е за събитието (числата се сверяват с всички заглавия в групата),
    останалите са в row["also"] = [{source, headline, link}] — „също: FT, Reuters“. Заглавие, вече влязло в група, не може да е отделна новина ("повторен индекс").
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
        group = _also_group(n.get("also"), i, pool, seen, dropped)          # 29.10.2026: една история — една новина (заглавията за същото събитие)
        seen.update(group)
        main = min(group, key=lambda k: (_source_rank(pool[k].get("source")), group.index(k)))
        if main != i:
            dropped.append({"i": i, "reason": f"основното заглавие — от по-надеждния източник ({pool[main].get('source')}), преводът отпада", "main": main})
        r = pool[main]
        why, cut = _why_numbers(why, " ".join(f"{pool[k]['title']} {pool[k].get('summary') or ''}" for k in group))
        if cut:
            dropped.append({"i": i, "reason": "число в why, което го няма в заглавието и резюмето — махната е частта с него", "removed": cut})
        row = {"headline": r["title"], "source": r.get("source"), "why": why}
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
        "които ги няма в \"t\" или \"d\" на същата новина.\n"
        # 29.10.2026 (разходката, т. 3–4, решение 2): една история — една новина
        f"{ALSO_RULE}\n\n"
        f"НОВИНИ:\n{json.dumps(compact, ensure_ascii=False, default=str)}\n\n"
        'Върни само JSON: {"news": [{"i": 0, "h": "първите шест думи на заглавието", "why": "...", "headline_bg": "...", "also": [{"i": 5, "h": "първите шест думи"}]}]}'
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
