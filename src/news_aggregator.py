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
import json
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


def gather_raw(hours: int = 24) -> list[dict]:
    items: list[dict] = []
    for src, url in config.NEWS_RSS_FEEDS.items():
        items += _fetch_rss(url, src, hours)
    # Fallback: ако RSS-ите върнаха твърде малко, scrape-ваме страниците директно
    if len(items) < 5:
        for name, url in config.NEWS_SCRAPE_FALLBACK.items():
            items += _scrape_headlines(name, url)
    if config.NEWS_ENABLE_NITTER:
        for handle in config.NITTER_HANDLES:
            items += _fetch_nitter(handle)
    # дедупликация по заглавие
    seen, dedup = set(), []
    for it in items:
        key = it["title"].lower()[:90]
        if key not in seen:
            seen.add(key); dedup.append(it)
    return dedup


# ──────────────────────────────────────────────────────────────────────────
# Claude филтър
# ──────────────────────────────────────────────────────────────────────────
_SYSTEM = ("Ти си макро редактор за суинг търговец. Връщаш САМО валиден JSON, "
           "без markdown огради, без преамбюл. Пишеш на български, тикери и "
           "термини на английски.")


def significant_news(max_items: int = 8) -> list[dict]:
    """
    Връща [{headline, why}] — до max_items пазарно значими новини. Кешира за деня.
    Празен списък при провал (graceful degradation).
    """
    today = dt.date.today().isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today:
                return cached.get("news", [])
        except Exception:
            pass

    raw = gather_raw(hours=24)
    if not raw:
        print("[news] нула източници върнаха данни — пропускам секцията")
        return []

    # ограничаваме промпта
    compact = [{"s": r["source"], "t": r["title"], "d": r["summary"]} for r in raw[:60]]
    user = (
        "От тези новини извлечи само тези с пазарно значение — геополитика, Fed, "
        "макро release-и (CPI, jobs report/nonfarm payrolls, GDP, PCE, unemployment), "
        f"секторни движения, суровини. Максимум {max_items} новини, всяка с едно "
        "изречение защо е важна за пазарите днес.\n\n"
        f"НОВИНИ:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        'Върни само JSON: {"news": [{"headline": "...", "why": "..."}]}'
    )
    try:
        from src import ai_brief
        text = ai_brief._call_claude(_SYSTEM, user, max_tokens=2000)
        data = ai_brief._parse_json(text)
        news = data.get("news", []) if isinstance(data, dict) else []
        news = [n for n in news if n.get("headline")][:max_items]
    except Exception as ex:
        print(f"[news] Claude филтър неуспешен: {ex}")
        return []

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "news": news},
                                     ensure_ascii=False, indent=1))
    except Exception as ex:
        print(f"[news] cache write: {ex}")

    return news


if __name__ == "__main__":
    raw = gather_raw()
    print(f"Събрани сурови заглавия: {len(raw)}")
    for r in raw[:10]:
        print(f"  [{r['source']}] {r['title'][:90]}")
    print("\nПазарно значими (Claude):")
    for n in significant_news():
        print(f"  • {n['headline']} — {n['why']}")
