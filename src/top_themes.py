"""
19.11.2026 (пакет 19.11, т. 2): ТОП ТЕМИТЕ на деня — от кода, без ръчни списъци и без AI. Заглавията от всички източници за прозореца (главните фийдове + първата страница / световните
новини: FT World, Reuters World — config.NEWS_FRONT_FEEDS) се групират по общи ключови имена: собствени имена и съкращения от заглавието („Xi“, „Putin“, „Anthropic“, „IPO“);
първата дума — само ако е име и другаде (не „Stocks“). Кандидат е едно име (не по-често от config.THEME_SINGLE_MAX_SHARE от заглавията — „Trump“, „China“ са твърде общи сами)
или двойка имена, които са заедно в заглавията; тема е кандидат с ≥ config.THEME_MIN_PUBLISHERS издателя (FT, Reuters, AP, CNBC) или ≥ config.THEME_MIN_HEADLINES заглавия.
Припокриващите се кандидати се сливат; първи са темите с заглавие от първата страница, после по издатели и заглавия; до config.THEME_MAX.

Темата влиза в пула към подбора първа и задължително (news_aggregator), редът „Топ теми“ под „Нощта“ дава дословното заглавие (от първата страница, иначе от най-надеждния
източник), броя източници и часа; AI в макрото може да я спомене само с факти от тези заглавия (ai_brief — блокът и проверката на твърденията срещу заглавията).
Реално 19.11: срещата Тръмп–Си–Путин — 12 заглавия в пула от 4 издателя (подборът взе едно, трето по ред; разказът не я спомена). Чисти функции.
"""
from __future__ import annotations

import re

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_SUFFIX = re.compile(r"\s+-\s+(?:Reuters|AP News|AP|CNBC|Financial Times|FT|Bloomberg)\s*$")
_TOKEN = re.compile(r"[A-Z][A-Za-z0-9&’'.-]*[A-Za-z0-9]|[A-Z]{2,}")
_STOP = {"US", "U.S", "UK", "EU", "THE", "A", "AN", "NEW", "DAY", "LIVE", "UPDATE", "UPDATES", "EXCLUSIVE", "BREAKINGVIEWS", "COMMENTARY", "ANALYSIS", "INSTANT", "VIEW",
         "TRADING", "FACTBOX", "EXPLAINER", "HERE", "WHAT", "WHY", "HOW", "WHO", "STOCKS", "STOCK", "WALL", "STREET", "DOW", "NASDAQ", "S&P", "MARKETS", "MARKET", "GLOBAL",
         "WEEK", "AHEAD", "VIDEO", "REUTERS", "AP", "CNBC", "FT", "NEWS", "INC", "CO", "CORP", "CEO", "CFO", "Q1", "Q2", "Q3", "Q4", "TAKEAWAYS", "MORNING", "BID", "OPINION",
         "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER",
         "OCTOBER", "NOVEMBER", "DECEMBER", "I", "MY", "OUR", "WE", "HE", "SHE", "IT", "THEY", "THIS", "THAT", "AS", "AT", "IN", "ON", "FOR", "TO", "OF", "AND", "OR", "BUT", "IF",
         "IS", "ARE", "WILL", "CAN", "SAYS", "SAY", "SAID", "TOP", "BIG", "MORE", "MOST", "AFTER", "BEFORE", "WITH", "FROM", "BY", "OVER", "UNDER", "UP", "DOWN", "ALL", "NO",
         "NOT", "YES", "FIRST", "LAST", "NEXT", "EARNINGS", "AI",
         # общи думи от имена („Deutsche Bank“ и „Bank of England“ не са една тема)
         "BANK", "BANKS", "GROUP", "FUND", "FUNDS", "CAPITAL", "HOLDINGS", "PARTNERS", "INTERNATIONAL", "NATIONAL", "CENTRAL", "FEDERAL", "STATE", "STATES", "UNITED",
         "COMPANY", "COMPANIES", "MINISTER", "PRESIDENT", "PM", "GOVERNMENT", "OFFICIALS", "LEADERS", "INVESTORS", "NEWSLETTER", "INSIDE", "SUMMIT"}
# 19.11.2026: държава / регион / град САМА не е тема („India“ на 19.11 — Adani, Бангладеш, индийският пазар, Fairfax: 6 несвързани заглавия); в двойка — да („Putin“ + „Ukraine“)
_PLACES = {"CHINA", "INDIA", "JAPAN", "RUSSIA", "UKRAINE", "IRAN", "ISRAEL", "GAZA", "BRITAIN", "BRITISH", "GERMANY", "GERMAN", "FRANCE", "FRENCH", "ITALY", "SPAIN", "EUROPE",
           "EUROPEAN", "ASIA", "ASIAN", "ASIA-PACIFIC", "AFRICA", "CANADA", "MEXICO", "BRAZIL", "KOREA", "SOUTH", "NORTH", "TAIWAN", "AUSTRALIA", "BANGLADESH", "PAKISTAN",
           "TURKEY", "SAUDI", "ARABIA", "GULF", "MIDDLE", "EAST", "WEST", "WASHINGTON", "BEIJING", "MOSCOW", "LONDON", "TOKYO", "PARIS", "BERLIN", "AMERICA", "AMERICAN",
           "CHINESE", "RUSSIAN", "JAPANESE", "INDIAN", "KOREAN", "VENEZUELA", "ARGENTINA", "INDONESIA", "VIETNAM", "SWITZERLAND", "SWISS", "NETHERLANDS", "POLAND", "SWEDEN",
           "NORWAY", "DENMARK", "IRELAND", "SCOTLAND", "SCOTCH", "APEC", "G7", "G20", "NATO", "UN"}


def publisher(source: str | None) -> str:
    """Издателят на фийда — „Reuters Business“ / „Reuters World“ → Reuters, „Financial Times“ / „FT World“ → FT."""
    s = (source or "").lower()
    return "Reuters" if "reuters" in s else "FT" if ("ft" in s.split() or "financial times" in s or s.startswith("ft")) else "AP" if s.startswith("ap") else "CNBC" if "cnbc" in s else (source or "?")


def _norm(tok: str) -> str:
    t = tok.replace("’", "'")
    t = re.sub(r"'s$|'$", "", t).strip(".-'")
    return {"U.S": "US", "U.S.": "US", "U.K": "UK"}.get(t, t).upper()


def tokens(title: str, later_caps: set | None = None) -> set[str]:
    """Ключовите имена в заглавието (нормализирани, главни). Първата дума — само ако е съкращение, притежателна („Nvidia's“) или е име и по-нататък в друго заглавие."""
    t = _SUFFIX.sub("", title or "")
    out = set()
    for k, m in enumerate(_TOKEN.finditer(t)):
        raw = m.group(0)
        n = _norm(raw)
        if not n or n in _STOP or len(n) < 2:
            continue
        if m.start() == 0 and not (raw.isupper() or re.search(r"['’]s$", raw) or (later_caps is not None and n in later_caps)):
            continue
        out.add(n)
    return out


def _later_caps(titles: list[str]) -> set[str]:
    s = set()
    for t in titles:
        for m in _TOKEN.finditer(_SUFFIX.sub("", t or "")):
            if m.start() > 0:
                s.add(_norm(m.group(0)))
    return s


def themes(items: list, front_sources: set | None = None, max_n: int | None = None) -> list[dict]:
    """
    items — [{title, source, published}] (или [source, published, title]); front_sources — имената на фийдовете от първата страница. → до max_n теми
    [{key, names, headline, source, published, publishers, n_publishers, n_headlines, front, items}]. Чиста функция.
    """
    front_sources = set(front_sources or config.NEWS_FRONT_FEEDS)
    rows = []
    for it in items or []:
        if isinstance(it, dict):
            rows.append({"title": it.get("title") or it.get("headline") or "", "source": it.get("source"), "published": it.get("published")})
        elif isinstance(it, (list, tuple)) and len(it) >= 3:
            rows.append({"title": it[2] or "", "source": it[0], "published": it[1]})
    seen, uniq = set(), []
    for r in rows:
        k = _SUFFIX.sub("", r["title"]).lower()[:90]
        if r["title"] and k not in seen:
            seen.add(k); uniq.append(r)
    if not uniq:
        return []
    caps = _later_caps([r["title"] for r in uniq])
    disp: dict = {}
    for r in uniq:
        for m in _TOKEN.finditer(_SUFFIX.sub("", r["title"])):
            disp.setdefault(_norm(m.group(0)), re.sub(r"['’]s$", "", m.group(0)).strip(".-'’"))
    toks = [tokens(r["title"], caps) for r in uniq]
    n = len(uniq)
    freq: dict = {}
    for ts in toks:
        for t in ts:
            freq[t] = freq.get(t, 0) + 1
    cand: dict = {}
    for i, ts in enumerate(toks):
        lst = sorted(ts)
        for t in lst:
            if freq[t] / n <= config.THEME_SINGLE_MAX_SHARE and t not in _PLACES:
                cand.setdefault((t,), set()).add(i)
        for a in range(len(lst)):
            for b in range(a + 1, len(lst)):
                cand.setdefault((lst[a], lst[b]), set()).add(i)
    qual = []
    for key, idx in cand.items():
        pubs = {publisher(uniq[i]["source"]) for i in idx}
        if len(pubs) >= config.THEME_MIN_PUBLISHERS or len(idx) >= config.THEME_MIN_HEADLINES:
            if len(key) == 1 and len(idx) < 3:
                continue
            qual.append((key, idx, pubs))
    qual.sort(key=lambda x: (-len(x[2]), -len(x[1]), -len(x[0])))
    chosen: list[dict] = []
    for key, idx, pubs in qual:
        hit = next((c for c in chosen if len(idx & c["_idx"]) / max(1, min(len(idx), len(c["_idx"]))) >= 0.5), None)
        if hit:
            if len(idx & hit["_idx"]) / max(1, len(idx)) >= 0.5:                 # припокриване — сливане на имената, заглавията остават на първия
                hit["names"] = list(dict.fromkeys(hit["names"] + [k for k in key]))[:4]
            continue
        chosen.append({"_idx": set(idx), "names": list(key)})
    out = []
    order = {s: k for k, s in enumerate(config.NEWS_SOURCE_PRIORITY)}
    for c in chosen:
        its = [uniq[i] for i in sorted(c["_idx"])]
        pubs = sorted({publisher(r["source"]) for r in its})
        front = [r for r in its if r["source"] in front_sources]
        names = set(c["names"])
        caps_all = caps
        # представителното заглавие — с най-много от имената на темата и с име в началото; при равенство — от първата страница, после по надеждност на източника, после най-новото
        def _pos(r):                                                             # заглавието ЗА темата започва с име от нея („Anthropic raises …“, не „Dollar … eye Anthropic IPO“)
            t = _SUFFIX.sub("", r["title"])
            ps = [m.start() for m in _TOKEN.finditer(t) if _norm(m.group(0)) in names]
            return min(ps) // 15 if ps else 99
        rep = sorted(its, key=lambda r: (-len(tokens(r["title"], caps_all) & names), _pos(r), r["source"] not in front_sources, order.get(r["source"], 99),
                                         "".join(chr(0x10FFFF - ord(ch)) for ch in (r.get("published") or ""))))[0]
        last = max((r.get("published") or "" for r in its), default="")
        out.append({"key": "–".join(disp.get(n, n) for n in c["names"]), "names": c["names"], "headline": rep["title"], "source": rep["source"],
                    "published": last or rep.get("published"), "publishers": pubs, "n_publishers": len(pubs), "n_headlines": len(its), "front": bool(front),
                    "items": [{"title": r["title"], "source": r["source"], "published": r.get("published")} for r in its]})
    out.sort(key=lambda t: (not t["front"], -t["n_publishers"], -t["n_headlines"]))
    return out[:max_n or config.THEME_MAX]


def pool_items(themes_: list[dict], per_theme: int | None = None) -> list[dict]:
    """Заглавията на темите, които влизат ПЪРВИ в пула към подбора — по до per_theme на тема, различни издатели първо (представителното — първо). Чиста функция."""
    per_theme = per_theme or config.THEME_POOL_PER_THEME
    out = []
    for t in themes_ or []:
        its = sorted(t.get("items") or [], key=lambda r: r["title"] != t.get("headline"))
        picked, pubs = [], set()
        for r in its:                                                        # първо по един от издател
            if publisher(r.get("source")) not in pubs:
                picked.append(r); pubs.add(publisher(r.get("source")))
        for r in its:
            if r not in picked:
                picked.append(r)
        out += [{**r, "theme": t.get("key")} for r in picked[:per_theme]]
    return out
