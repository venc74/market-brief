"""
watch_monitor.py — ръчно куриран, per-ticker дневен монитор („🔎 Наблюдавани
тикъри").

Различен по предназначение от всичко останало в брифа: CANSLIM скрийнърът,
GLB и Short Screener ТЪРСЯТ нови кандидати по критерии. Тук няма търсене —
списъкът е фиксиран и ръчно поддържан (обикновено вече отворени позиции), а
въпросът е единствено „какво се случи около тази компания през последните
24 часа".

Източници — само вече налична инфраструктура, нула нови зависимости:
  • новини: yfinance .news, keyed по ТИКЪР. Съзнателно НЕ Google News по име
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
import datetime as dt
import json

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
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


def _recent_news(ticker: str, hours: int) -> list[dict]:
    """yfinance .news, орязан до прозореца. Провал → празен списък."""
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


def collect(tickers: list[str] | None = None) -> list[dict]:
    """
    Суровите данни за всеки watched тикър, БЕЗ AI слой.

    Връща [{ticker, news: [...], insider: [...], insider_cluster: bool,
             quiet: bool}], в реда на списъка. `quiet=True` значи нула новини и
    нула Form 4 — извикващият не бива да праща такъв тикър към AI-то.
    """
    tickers = tickers if tickers is not None else load_watch_list()
    if not tickers:
        return []
    try:
        insider = insider_buying.fetch_insider_transactions(tickers)
    except Exception as e:
        print(f"[watch] insider блок се провали изцяло: {e}")
        insider = {}

    rows = []
    for tk in tickers:
        news = _recent_news(tk, config.WATCH_NEWS_WINDOW_HOURS)
        txns = insider.get(tk, [])
        rows.append({
            "ticker": tk,
            "news": news,
            "insider": [{**t, "date": t["date"].isoformat()} for t in txns],
            "insider_cluster": _insider_cluster(txns),
            "quiet": not news and not txns,
        })
    quiet = [r["ticker"] for r in rows if r["quiet"]]
    print(f"[watch] {len(rows)} наблюдавани тикъра — "
          f"{len(rows) - len(quiet)} със събития, {len(quiet)} без "
          f"({', '.join(quiet) if quiet else '—'})")
    return rows
