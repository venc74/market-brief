"""
watch_monitor.py — ръчно куриран, per-ticker дневен монитор („🔎 Наблюдавани
тикъри").

Различен по предназначение от всичко останало в брифа: CANSLIM скрийнърът,
GLB и Short Screener ТЪРСЯТ нови кандидати по критерии. Тук няма търсене —
списъкът е фиксиран и ръчно поддържан (обикновено вече отворени позиции), а
въпросът е единствено „какво се случи около тази компания през последните
24 часа".

Източници — само вече налична инфраструктура, нула нови зависимости:
  • новини (29.10.2026): RSS на Yahoo Finance по ТИКЪР (config.WATCH_NEWS_RSS) + проверка, че новината е за компанията (about_company).
    04.11.2026 (четвърти преглед, В1): без резервата yfinance .news (от 29.10 връщаше нищо и скриваше провала на RSS); провал на RSS (HTTP статус ≠ 200, нечетим фийд,
    изключение) → news_checked False на реда + LAST_STATUS (брояч и причина) — стъпката е „частично“ над config.WATCH_PARTIAL_SHARE. До 29.10: yfinance .news, keyed по ТИКЪР. Съзнателно НЕ Google News по име
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
import pandas as pd
import yfinance as yf
from src import insider_buying

_LIST_PATH = config.DATA_DIR / "watch_list.json"

# 04.11.2026 (четвърти преглед, В1): какво НЕ се провери в последния collect — {"tickers", "news_failed": {тикър: причина}, "price_missing": [...], "insider_ok"}.
# До 04.11 провал на RSS, на цените или на Form 4 оставяше само ред в лога, а редът казваше „няма новини“ (тишината не е информация).
LAST_STATUS: dict = {}
_NEWS_FAIL: dict = {}


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


def load_watch_names() -> dict[str, str]:
    """
    03.11.2026 (поправки след брифа, т. 1): имената на компаниите — записани веднъж в data/watch_list.json ("names": {тикър: име}); до 03.11 — от Yahoo .info, която на 02.11
    и 03.11 върна HTTP 401 за 14 от 14. Липсващ файл / ключ → {} (редът показва само тикъра; филтърът на новините — само по символа).
    """
    try:
        data = json.loads(_LIST_PATH.read_text(encoding="utf-8")) if _LIST_PATH.exists() else {}
        names = data.get("names") if isinstance(data, dict) else None
        return {str(k).upper().strip(): str(v).strip() for k, v in (names or {}).items() if str(v).strip()}
    except Exception as e:
        print(f"[watch] имената от watch_list.json не се прочетоха: {e}")
        return {}


_NAME_SUFFIX = re.compile(r"(?:,?\s+(?:Inc\.?|Incorporated|Corporation|Corp\.?|plc|PLC|SE|N\.V\.|NV|S\.A\.|AG|Ltd\.?|Limited|Holdings?|Group|Companies|Company|Co\.?"
                          r"|Technologies|Technology))+\.?$")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def company_keys(name: str | None, others=None) -> set[str]:
    """
    29.10.2026 (т. 6): имената, по които новината се разпознава като за компанията — пълното име без "Inc." и т.н. и първата му дума (3+ знака). "C3.ai, Inc." → {"C3.ai"}.
    17.11.2026 (пакет 1, т. 4): първата дума — САМО ако не е първа дума и на друга компания (others — имената от универса и другите наблюдавани): HONA „Honeywell Aerospace“
    се търси по „Honeywell Aerospace“, не по „Honeywell“ (хващаше и HON). Реално към 17.11: от 6-те наблюдавани само HONA има такава двойка (HON).
    """
    n = _NAME_SUFFIX.sub("", (name or "").strip()).strip(" ,")
    keys = {n} if n else set()
    first = n.split()[0] if n.split() else ""
    taken = {str(o).split()[0].lower() for o in (others or []) if str(o or "").split()}
    if len(first) >= 3 and first.lower() not in taken:
        keys.add(first)
    return keys


def _other_names(ticker: str, watch_names: dict | None = None) -> list[str]:
    """17.11.2026 (т. 4): имената на ДРУГИТЕ компании — универсът (screener.LAST_UNIVERSE_NAME, иначе data/universe.json) и другите наблюдавани. Graceful: провал → []."""
    try:
        from src import screener
        names = dict(screener.LAST_UNIVERSE_NAME) or (json.loads((config.DATA_DIR / config.UNIVERSE_CACHE_NAME).read_text(encoding="utf-8")).get("name") or {})
    except Exception:
        names = {}
    names = {**names, **(watch_names or {})}
    return [v for k, v in names.items() if k != ticker and v]


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
    """
    Новините от RSS на Yahoo Finance в прозореца, само за компанията (about_company); None — фийдът не се изтегли (причината — в _NEWS_FAIL[тикър]). fetch(url) → bytes (за тестове).
    04.11.2026 (В1): HTTP статус ≠ 200 (401 / 429 с HTML тяло) е провал, не празен фийд.
    """
    try:
        import feedparser
        url = config.WATCH_NEWS_RSS.format(ticker=ticker)
        if fetch:
            raw = fetch(url)
        else:
            r = requests.get(url, timeout=15, headers=_UA)
            if r.status_code != 200:
                _NEWS_FAIL[ticker] = f"HTTP {r.status_code}"
                print(f"[watch] {ticker} RSS новини: HTTP {r.status_code}")
                return None
            raw = r.content
        feed = feedparser.parse(raw)
        if not feed.entries and getattr(feed, "bozo", False):
            _NEWS_FAIL[ticker] = "фийдът не се прочете"
            print(f"[watch] {ticker} RSS новини: фийдът не се прочете ({type(getattr(feed, 'bozo_exception', None)).__name__})")
            return None
    except Exception as e:
        _NEWS_FAIL[ticker] = type(e).__name__
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


def _recent_news(ticker: str, hours: int, keys: set[str] | None = None) -> list[dict] | None:
    """29.10.2026: RSS на Yahoo по тикър, само за компанията. 04.11.2026 (В1): провал → None (не „няма новини“); резервата yfinance .news е махната — от 29.10 връщаше нищо."""
    return _rss_news(ticker, hours, keys or set())


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
    if c is not None and len(c) == 1:                                       # 19.11.2026 (пакет 19.11, т. 1): първият ден на борсата (ANT) — цената, без промяна
        return {"date": c.index[-1].date().isoformat(), "close": round(float(c.iloc[-1]), 2), "first_day": True}
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


def rs_sign(v: float | None) -> int | None:
    """30.10.2026 (т. 7): +1 / −1 извън мъртвата зона (±config.RS_WORD_DEAD_ZONE пункта), 0 в нея — „в крак с пазара“."""
    if v is None:
        return None
    dz = config.RS_WORD_DEAD_ZONE
    return 1 if v > dz else (-1 if v < -dz else 0)


def rs_word(rs_4w: float | None, rs_12w: float | None) -> str | None:
    """
    Думата до RS (30.10.2026, т. 3) — с мъртва зона от 30.10.2026 (т. 7): RS между −1 и +1 пункта е „в крак с пазара“, не плюс / минус. 4 седмици решават посоката,
    12 — дали е трайно:
                            12 седм. > +1     ±1               < −1
        4 седм. > +1        води пазара       набира сила      набира сила
        4 седм. ±1          в крак с пазара   в крак с пазара  в крак с пазара
        4 седм. < −1        отслабва          отслабва         изостава
    До 30.10 (т. 7) знакът беше спрямо 0: XLI +0.2 / −8.5 излизаше „набира сила“ заради +0.2.
    """
    if rs_4w is None or rs_12w is None:
        return None
    s4, s12 = rs_sign(rs_4w), rs_sign(rs_12w)
    if s4 == 0:
        return "в крак с пазара"
    if s4 > 0:
        return "води пазара" if s12 > 0 else "набира сила"
    return "изостава" if s12 < 0 else "отслабва"


def range_facts(high, low, close) -> dict:
    """
    03.11.2026 (поправки след брифа, т. 1 — на мястото на short interest): ADR% за 20 бара (trade_levels.adr_pct — формулата е там) и разстоянието до 52-седмичния връх
    (най-високият High за последните 252 сесии) от последното затваряне — от цените, които вече се теглят (без нови заявки). Къса история → без съответното поле. Чиста функция.
    """
    from src import trade_levels
    out = {}
    try:
        df = pd.DataFrame({"h": high, "l": low, "c": close}).dropna()
    except Exception:
        return out
    if len(df) == 0:
        return out
    a = trade_levels.adr_pct(df["h"], df["l"])
    if a is not None:
        out["adr_pct"] = round(float(a), 1)
    if len(df) < config.WATCH_52W_MIN_BARS:                     # 17.11.2026 (пакет 1, т. 10): нова на борсата (HONA, отделена от Honeywell) — само собствената история
        try:                                                    # (празните дни преди листването падат с dropna); 52-седм. показатели — само при ≥ 1 година
            out["listed_since"] = pd.Timestamp(df.index[0]).date().isoformat()
        except Exception:
            out["listed_since"] = None
        out["history_bars"] = len(df)
        return out
    hi = float(df["h"].iloc[-252:].max())
    if hi > 0:
        out["high_52w"] = round(hi, 2)
        out["off_high_pct"] = round((float(df["c"].iloc[-1]) / hi - 1) * 100, 1)
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


def facts(tickers: list[str], download=None, earnings_fn=None, names: dict | None = None) -> dict[str, dict]:
    """
    {тикър: {name, price: price_facts + range_facts, earnings: {next, days}}} — цените с ЕДНО теглене (тикърите + SPY, 1 година, без днешния частичен бар), следващият отчет
    (enrich.earnings_info — същата логика като картите) по тикър. Провал за тикър → празните полета само за него; провал на тегленето → без цени.
    03.11.2026 (поправки след брифа, т. 1): БЕЗ Yahoo .info — на 02.11 и 03.11 тя върна HTTP 401 („Invalid Crumb“) за 14 от 14; short interest отпада, името е от
    data/watch_list.json (load_watch_names), а на мястото на short interest — ADR% (20 дни) и разстоянието до 52-седмичния връх (range_facts) от същите цени.
    download(tickers) → DataFrame като yf.download(group_by="ticker"); earnings_fn(t) → dict; names — {тикър: име} (за тестове).
    """
    from src import sessions as _sessions
    names = load_watch_names() if names is None else names
    out = {t: {"name": names.get(t), "price": {}, "earnings": {}} for t in tickers}
    if not tickers:
        return out
    try:
        dl = download or (lambda ts: yf.download(ts, period="1y", auto_adjust=False, group_by="ticker", progress=False, threads=True))
        df = _sessions.cut_today(dl(list(tickers) + ["SPY"]))
        spy = df["SPY"]["Close"] if "SPY" in df.columns.get_level_values(0) else None
        for t in tickers:
            try:
                out[t]["price"] = price_facts(df[t]["Close"], spy)
                if out[t]["price"] and "High" in df[t] and "Low" in df[t]:
                    out[t]["price"].update(range_facts(df[t]["High"], df[t]["Low"], df[t]["Close"]))
            except Exception as e:
                print(f"[watch] {t} цени: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"[watch] цените не се изтеглиха: {type(e).__name__}: {e}")
    for t in tickers:
        try:
            if earnings_fn is None:
                from src import enrich
                earnings_fn = lambda x: enrich.earnings_info(x, with_info=False)        # 03.11.2026: без .info (т. 1)
            e = earnings_fn(t) or {}
            out[t]["earnings"] = {"next": e.get("next_earnings"), "days": e.get("days_to_earnings"), "status": e.get("earnings_status"),
                                  "estimate": e.get("earnings_estimate")}                 # 03.11.2026 (т. 3): прогнозна дата → „~ДД.ММ (прогноза)“
        except Exception as e:
            print(f"[watch] {t} отчет: {type(e).__name__}: {e}")
    return out


def insider_flags(txns: list[dict], context: list[dict] | None = None) -> list[dict]:
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
        ctx = [t for t in (context if context is not None else xs) if t.get("code") == code]          # 16.11.2026 (т. 4): CLUSTER — сред всичките в посоката
        f = {"dir": code, "label": label, "n": len(xs), "owners": len({t.get("owner_name") for t in xs}), "value": round(sum(float(t.get("value") or 0) for t in xs)),
             "cluster": _insider_cluster(ctx), "plan": plan}
        if groups:
            top = max(groups.values(), key=lambda g: g["value"])
            f["top_offplan"] = {**top, "value": round(top["value"])}
        out.append(f)
    return out


def stake_sold_pct(txns: list[dict]) -> float | None:
    """
    10.11.2026 (т. 5): колко % от дела си е продал (купил) човекът по редовете — по сметки. Всеки ред на Form 4 носи броя акции след сделката; поредните
    сделки в една сметка се свързват (преди = след на предишния ред), а отделните сметки (пряко / тръст) са отделни вериги. Началото на всяка верига е
    „преди“, което не е „след“ на друг ред (мултимножество — без значение от реда на редовете). Дялът = продадени / сбора на началата. Ред без „след“ → None.
    Реално: CRCL, Allaire 05.11 — пряко 277 560 → … и четири тръста по ~58 798 → 57 282. Чиста функция.
    """
    import collections
    xs = [t for t in txns or [] if t.get("shares")]
    if not xs or any(t.get("shares_after") is None for t in xs):
        return None
    before = collections.Counter(round(float(t["shares"]) + float(t["shares_after"])) for t in xs)
    after = collections.Counter(round(float(t["shares_after"])) for t in xs)
    start = sum(k * v for k, v in (before - after).items())
    return round(sum(float(t["shares"]) for t in xs) / start * 100, 1) if start > 0 else None


def _plan_of(xs: list[dict]):
    pl = {t.get("planned_10b5_1") for t in xs}
    return next(iter(pl)) if len(pl) == 1 else None


def person_days(txns: list[dict]) -> list[dict]:
    """
    10.11.2026 (т. 5, CRCL): редовете на Form 4, обединени по човек, ден и посока — {date, code, owner_name, owner_title, is_director, is_officer, n, shares, value,
    pct_of_holdings (stake_sold_pct за деня), planned_10b5_1 (общото; смесено → None), plan_mixed}. На 10.11 CRCL имаше 54 реда от 4 души → 7 реда.
    Нови първо, после по сума. Чиста функция.
    """
    groups: dict = {}
    for t in txns or []:
        k = (str(t.get("date"))[:10], t.get("code"), t.get("owner_name"))
        groups.setdefault(k, []).append(t)
    out = []
    for (d, code, owner), xs in groups.items():
        out.append({"date": d, "code": code, "owner_name": owner, "owner_title": xs[0].get("owner_title"), "is_director": any(t.get("is_director") for t in xs),
                    "is_officer": any(t.get("is_officer") for t in xs), "n": len(xs), "shares": sum(float(t.get("shares") or 0) for t in xs),
                    "value": round(sum(float(t.get("value") or 0) for t in xs), 2), "pct_of_holdings": stake_sold_pct(xs),
                    "planned_10b5_1": _plan_of(xs), "plan_mixed": len({t.get("planned_10b5_1") for t in xs}) > 1})
    out.sort(key=lambda r: (r["date"], r["value"]), reverse=True)
    return out


def big_sellers(txns: list[dict], pct: float | None = None) -> list[dict]:
    """
    10.11.2026 (т. 5): кой продава ≥ config.INSIDER_BIG_SELL_PCT % от дела си за прозореца — от кода, независимо от 10b5-1 (и планова продажба на четвърт от дела
    не е „рутинна“). → [{owner, title, pct, value, n, first, last, planned_10b5_1}], по дела. Чиста функция.
    """
    lim = config.INSIDER_BIG_SELL_PCT if pct is None else pct
    by: dict = {}
    for t in txns or []:
        if t.get("code") == "S":
            by.setdefault(t.get("owner_name"), []).append(t)
    out = []
    for owner, xs in by.items():
        p = stake_sold_pct(xs)
        if p is not None and p >= lim:
            ds = sorted(str(t.get("date"))[:10] for t in xs)
            out.append({"owner": owner, "title": xs[0].get("owner_title") or ("директор" if any(t.get("is_director") for t in xs) else ""), "pct": p,
                        "value": round(sum(float(t.get("value") or 0) for t in xs)), "n": len(xs), "first": ds[0], "last": ds[-1], "planned_10b5_1": _plan_of(xs)})
    out.sort(key=lambda b: -b["pct"])
    return out


def big_sell_text(b: dict) -> str:
    """„продава ≥25% от дела си: Chief Financial Officer — 31.3% ($1.2 млн, 22.10; по план 10b5-1)“ — страницата."""
    v = f"${b['value'] / 1e6:.1f} млн" if b["value"] >= 1e6 else f"${b['value']:,.0f}"
    d = f"{b['first'][8:10]}.{b['first'][5:7]}" + (f"–{b['last'][8:10]}.{b['last'][5:7]}" if b["last"] != b["first"] else "")
    plan = {True: "; по план 10b5-1", False: "; извънпланова"}.get(b.get("planned_10b5_1"), "")
    who = b.get("title") or b.get("owner") or "инсайдър"
    return f"продава ≥{config.INSIDER_BIG_SELL_PCT:g}% от дела си: {who} — {b['pct']:g}% ({v}, {d}{plan})"


def _money(v: float) -> str:
    return f"${v / 1e6:.1f} млн" if v >= 1e6 else f"${v:,.0f}"


def insider_summary(days: list[dict] | None) -> list[str]:
    """
    23.11.2026 (пакет 23.11, т. 2): фактите от НОВИТЕ Form 4 (person_days) като готови редове — на мястото на AI „прочита“ (insider_read). По посока: колко души, общата сума,
    по план 10b5-1 / извънпланови / смесено-неизвестно, най-голямата сделка (длъжност, сума, дата, % от дела). Без оценка („рутинно“, „тревожно“) — само числата. Чиста функция.
    Реално (16.11, BFLY): „Продажби: 2 души, 2 записа (човек × ден), $984,925 — по план 10b5-1: 1, извънпланови: 1; най-голямата: President & CEO $634,925 (30.10, 1.2% от дела).“
    """
    out = []
    for code, word in (("P", "Покупки"), ("S", "Продажби")):
        xs = [d for d in days or [] if d.get("code") == code]
        if not xs:
            continue
        owners = {d.get("owner_name") for d in xs}
        total = sum(float(d.get("value") or 0) for d in xs)
        plan = sum(1 for d in xs if d.get("planned_10b5_1") is True and not d.get("plan_mixed"))
        off = sum(1 for d in xs if d.get("planned_10b5_1") is False and not d.get("plan_mixed"))
        other = len(xs) - plan - off
        top = max(xs, key=lambda d: float(d.get("value") or 0))
        who = top.get("owner_title") or ("директор" if top.get("is_director") else top.get("owner_name") or "инсайдър")
        d = str(top.get("date") or "")
        pct = top.get("pct_of_holdings")
        out.append(f"{word}: {len(owners)} {'човек' if len(owners) == 1 else 'души'}, {len(xs)} {'запис' if len(xs) == 1 else 'записа'} (човек × ден), {_money(total)} — "
                   f"по план 10b5-1: {plan}, извънпланови: {off}"
                   + (f", смесено / неизвестно: {other}" if other else "")
                   + f"; най-голямата: {who} {_money(float(top.get('value') or 0))} ({d[8:10]}.{d[5:7]}"
                   + (f", {pct:g}% от дела" if isinstance(pct, (int, float)) else "") + ").")
    return out


def translate_news(rows: list[dict], call=None, pool_titles: list | None = None) -> dict:
    """
    23.11.2026 (пакет 23.11, т. 2): заглавията на наблюдаваните — превод с проверката (src/translate.py: числа, мащаб, тикъри, имена); неприет → оригиналът с бележка.
    Мутира row["news"][*] (headline_bg / translation_note). → отчетът {"n", "ok", "skipped"}; провал → бележка на всяко заглавие.
    """
    items = [n for r in rows or [] for n in r.get("news") or [] if isinstance(n, dict) and n.get("title")]
    if not items:
        return {"n": 0, "ok": 0, "skipped": []}
    must = {id(n): sorted(company_keys(r.get("name"))) for r in rows or [] for n in r.get("news") or [] if isinstance(n, dict)}
    try:
        from src import translate
        # заглавията на Yahoo са в Title Case (224 от 246) — имената се учат от обикновените заглавия на деня (pool_titles — пулът на новините) и от тези в обикновен регистър
        caps = translate.proper_caps([n["title"] for n in items] + list(pool_titles or []))
        return translate.apply(items, caps, call=call, key="title", must=lambda n: must.get(id(n)) or [])
    except Exception as e:
        print(f"[watch] преводът пропуснат: {type(e).__name__}: {e}")
        for n in items:
            n.setdefault("translation_note", "преводът не се получи")
        return {"n": len(items), "ok": 0, "skipped": [], "error": type(e).__name__}


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


def split_new_old(txns: list[dict], since_day: str) -> tuple[list[dict], list[dict]]:
    """
    16.11.2026 (пакет 16.11, т. 4): Form 4 — подадени от деня на предишния бриф нататък (нови) и по-старите (вече показани). Сутрешният бриф е в ~01:30 Ню Йорк, а EDGAR
    приема подаванията в работния ден — подаденото на датата на предишния бриф е след него. Без "filed" (стар запис) → старо. Чиста функция.
    """
    new = [t for t in txns or [] if str(t.get("filed") or "") >= since_day]
    return new, [t for t in txns or [] if t not in new]


def collect(tickers: list[str] | None = None, facts_fn=None, window_hours: float | None = None, since_day: str | None = None) -> list[dict]:
    """
    Суровите данни за всеки watched тикър, БЕЗ AI слой.

    Връща [{ticker, name, facts, news: [...], insider: [...], insider_cluster: bool,
             quiet: bool}], в реда на списъка. `quiet=True` значи нула новини и
    нула Form 4 — извикващият не бива да праща такъв тикър към AI-то (29.10.2026: фактите на реда не са събитие). 03.11.2026 (поправки след брифа, т. 5): "event" — новина
    в прозореца ИЛИ Form 4, подаден в прозореца ("filed" ≥ началото му); само такива редове отиват към AI (на 03.11 BFLY, ELF и ACN получиха „Няма новини … само insider
    транзакции“ заради Form 4 отпреди 1–5 седмици). Без "filed" (стар запис) → не е нов. "f4_new" — броят им.
    02.11.2026 (т. 4): window_hours — прозорецът на новините (main: от предишния бриф — понеделник 72 ч); без него — config.WATCH_NEWS_WINDOW_HOURS.
    """
    tickers = tickers if tickers is not None else load_watch_list()
    LAST_STATUS.clear()
    _NEWS_FAIL.clear()
    if not tickers:
        return []
    insider_ok = True
    try:
        fx = (facts_fn or facts)(tickers)
    except Exception as e:
        print(f"[watch] фактите не се изчислиха: {type(e).__name__}: {e}")
        fx = {}
    try:
        insider = insider_buying.fetch_insider_transactions(tickers)
    except Exception as e:
        print(f"[watch] insider блок се провали изцяло: {e}")
        insider, insider_ok = {}, False

    try:
        _watch_names = load_watch_names() or {}
    except Exception:
        _watch_names = {}
    rows = []
    since_day = since_day or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=window_hours or config.WATCH_NEWS_WINDOW_HOURS)).date().isoformat()
    for tk in tickers:
        f = fx.get(tk) or {}
        news = _recent_news(tk, window_hours or config.WATCH_NEWS_WINDOW_HOURS, company_keys(f.get("name"), _other_names(tk, _watch_names)))      # 17.11.2026 (т. 4)
        checked = news is not None                                                     # 04.11.2026 (В1): None — новините не се провериха (не „няма новини“)
        news = news or []
        txns = insider.get(tk, [])
        new_f4, old_f4 = split_new_old(txns, since_day)                               # 03.11.2026 (т. 5): Form 4, подаден в прозореца (от предишния бриф)
        # 16.11.2026 (пакет 16.11, т. 4, SIRI): отметките, таблицата, ≥25% и AI — САМО от новите Form 4; старите (вече показани) — сгънати „вече показано“.
        # До 16.11 всичко беше от 30-дневния прозорец (config.WATCH_INSIDER_LOOKBACK_DAYS) — покупките на Berkshire в SIRI от 30.10–03.11 стояха всеки ден до края на месеца,
        # а AI ги преразказваше наново в дните с новина (10.11, 11.11). CLUSTER — сред всичките 30 дни, но само ако в посоката има нов Form 4.
        new_owners = {t.get("owner_name") for t in new_f4 if t.get("code") == "S"}
        big = big_sellers(txns)
        rows.append({
            "ticker": tk,
            "name": f.get("name"),
            "facts": {k: f.get(k) or {} for k in ("price", "earnings")},                 # 03.11.2026: без short interest (без .info)
            "news": news,
            "news_checked": checked, **({} if checked else {"news_error": _NEWS_FAIL.get(tk) or "неизвестна причина"}),     # 04.11.2026 (В1)
            "insider": [{**t, "date": t["date"].isoformat()} for t in txns],
            "insider_cluster": _insider_cluster(txns) and bool(new_f4),
            "insider_flags": insider_flags(new_f4, context=txns),   # 30.10.2026: по посока — покупки / продажби, с плана; 16.11: само новите
            "insider_days": person_days(new_f4),                    # 10.11.2026 (т. 5): по човек и ден (CRCL: 54 реда → 7); 16.11: само новите
            "insider_days_old": person_days(old_f4),                # 16.11.2026 (т. 4): вече показани — сгънати
            "insider_summary": insider_summary(person_days(new_f4)),     # 23.11.2026 (пакет 23.11, т. 2): фактите от новите Form 4 — от кода, без AI
            "insider_big_sell": [b for b in big if b["owner"] in new_owners],      # 10.11.2026 (т. 5): ≥25% от дела — от кода, независимо от 10b5-1; 16.11: при нова продажба
            "insider_big_sell_old": [b for b in big if b["owner"] not in new_owners],
            "since": since_day,                                     # 16.11.2026 (т. 4): „нищо ново от ДД.ММ“
            "quiet": not news and not txns,
            "event": bool(news or new_f4), "f4_new": len(new_f4),               # 03.11.2026 (т. 5): AI коментар само при новина или нов Form 4
        })
    LAST_STATUS.update(tickers=len(rows), news_failed={r["ticker"]: r["news_error"] for r in rows if not r["news_checked"]},
                       price_missing=[r["ticker"] for r in rows if not r["facts"].get("price")], insider_ok=insider_ok)
    if LAST_STATUS["news_failed"] or LAST_STATUS["price_missing"] or not insider_ok:
        print(f"[watch] ⚠ не се провери: новини {len(LAST_STATUS['news_failed'])} от {len(rows)} {LAST_STATUS['news_failed']}; без цени {LAST_STATUS['price_missing']}; "
              f"Form 4 {'ok' if insider_ok else 'ПРОВАЛ'}")
    quiet = [r["ticker"] for r in rows if r["quiet"]]
    print(f"[watch] {len(rows)} наблюдавани тикъра — "
          f"{len(rows) - len(quiet)} със събития, {len(quiet)} без "
          f"({', '.join(quiet) if quiet else '—'})")
    return rows


def status_note(status: dict | None = None) -> str | None:
    """
    04.11.2026 (четвърти преглед, В1): причината за „частично“ на стъпката watch — новините не се провериха / без цени при ≥ config.WATCH_PARTIAL_SHARE от тикърите, или
    Form 4 изцяло не се провери; иначе None (единичен провал — само белегът на реда). Чиста функция.
    """
    st = LAST_STATUS if status is None else status
    n = st.get("tickers") or 0
    if not n:
        return None
    parts = []
    nf = st.get("news_failed") or {}
    if len(nf) >= config.WATCH_PARTIAL_SHARE * n:
        why = sorted({v for v in nf.values()})
        parts.append(f"новините не се провериха за {len(nf)} от {n} ({', '.join(why[:3])})")
    pm = st.get("price_missing") or []
    if len(pm) >= config.WATCH_PARTIAL_SHARE * n:
        parts.append(f"без цени за {len(pm)} от {n}")
    if st.get("insider_ok") is False:
        parts.append("Form 4 не се провери")
    return "; ".join(parts) or None
