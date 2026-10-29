"""
22.10.2026 (етап 4 — решения от 21–22.10): крипто секция. Новините са от RSS на Cointelegraph (config.CRYPTO_RSS_URL — https://cointelegraph.com/rss; адресът „?format=rss“
връща HTML страница), от 29.10 и на CoinDesk (config.CRYPTO_RSS_FEEDS — разходката, т. 4б), през същия начин като новините: AI избира по индекс и дава само „защо“, а заглавието и източникът са ДОСЛОВНИ от фийда (news_aggregator.pick_verbatim).
29.10.2026 (разходката, т. 4, решение (а)): мерилото вече не е списък с категории, а въпросът „би ли променила тази новина решението на институционален инвеститор в крипто след
седмица?“ с изрични примери — да: навлизането на традиционните финанси (токенизация на ценни книжа, DTCC, големи банки, стейбълкойни, регулатори); не: прогнози за цената, малки
монети, мнения. Таван config.CRYPTO_MAX_ITEMS (5), дневните потоци в ETF — най-много един ред ("etf_flows": true). Повод: на 28.10 „DTCC unit launches tokenization services“ беше
в пула и не мина. До 29.10 кодът махаше и избраното с категория извън списъка (DTCC с „tokenization“ щеше да падне и при избор).
Под новините: COIN, HOOD, CRCL, BLSH (последен close и промяна) и COT за Bitcoin — само в първия бриф след нов отчет на CFTC.
Без значими новини — един ред. Всяка грешка → празен резултат с причина (graceful); кеш по ден (повторен run не вика AI втори път).
"""
from __future__ import annotations

import datetime as dt
import json

import config

LAST_STATUS: dict = {}

_SYSTEM = ("Ти си редактор на крипто новини за суинг търговец. Връщаш САМО валиден JSON. Избираш по индекс от дадените заглавия; не пишеш и не превеждаш заглавия, "
           "не измисляш факти и не добавяш числа, които ги няма в заглавието или резюмето. Не даваш препоръка за покупка или продажба.")
# 29.10.2026 (разходката, т. 4а): въпросът и примерите — вместо затворения списък с категории
QUESTION = "би ли променила тази новина решението на институционален инвеститор в крипто след седмица?"
IMPORTANT = ("навлизането на традиционните финанси — токенизация на ценни книжа и фондове, DTCC, NYSE / ICE, Nasdaq, CME, големи банки и управители на активи "
             "(JPMorgan, BlackRock, Fidelity …), стейбълкойни и техните емитенти; решения на регулатори (SEC, CFTC, OCC, Fed, ЕК / MiCA) и закони; одобрения на ETF "
             "и необичайни потоци в тях; големи хакове и фалити (над около $50 млн. или голяма борса / доставчик); решения на големи борси")
NOT_IMPORTANT = ("прогнози и дневни отчети за цената (дори когато се обясняват с макро — макрото е другаде в брифа), малки монети и технически ъпгрейди, мнения и анализи, "
                 "проучвания, обзори")


def _prompt(pool: list[dict], max_items: int) -> str:
    from src import news_aggregator
    compact = [{"i": k, "s": r.get("source"), "t": r["title"], "d": r.get("summary") or ""} for k, r in enumerate(pool)]
    return (f"От тези крипто новини избери САМО тези, за които отговорът на въпроса е „да“: {QUESTION}\n"
            f"Важно — да: {IMPORTANT}.\n"
            f"Не: {NOT_IMPORTANT}.\n"
            f"Най-много {max_items} новини; дневните потоци в ETF — най-много една (отбележи я с \"etf_flows\": true). Ако няма такава — върни празен списък.\n"
            f"{news_aggregator.ALSO_RULE}\n"
            "За всяка: \"i\" (индексът), \"h\" (ДОСЛОВНО първите 6 думи на заглавието \"t\" — кодът проверява индекса), "
            "\"why\" (ЕДНО изречение на български — какво променя за институционалния инвеститор в крипто или за COIN / HOOD / CRCL / BLSH; без числа, които ги няма в \"t\" или \"d\").\n\n"
            f"НОВИНИ:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
            'Върни само JSON: {"news": [{"i": 0, "h": "първите шест думи", "why": "...", "etf_flows": false, "also": [{"i": 3, "h": "първите шест думи"}]}]}')


def crypto_news_call(system: str, user: str) -> str:
    """AI извикването на крипто секцията — именувана функция (етикетът в brief["ai_usage"] е по името на извикващия; ai_brief._SECTION_LABELS)."""
    from src import ai_brief
    return ai_brief._call_claude(system, user, max_tokens=1500)


def select(data, pool: list[dict], max_items: int | None = None) -> tuple[list[dict], list[dict]]:
    """
    Отговорът на AI → [{headline, source, link, why, also?}]: индекс и ехо през news_aggregator.pick_verbatim (и сливането на дублите — "also"); най-много 1 ред за дневни потоци
    в ETF ("etf_flows": true от модела). 29.10.2026: без проверка по категории — мерилото е въпросът в промпта. Чиста функция.
    """
    from src import news_aggregator
    max_items = max_items or config.CRYPTO_MAX_ITEMS
    raw = data.get("news", []) if isinstance(data, dict) else []
    picked, dropped = news_aggregator.pick_verbatim(raw, pool, len(pool))
    flows_by_title = {}
    for n in raw:
        if isinstance(n, dict) and isinstance(n.get("i"), int) and not isinstance(n.get("i"), bool) and 0 <= n["i"] < len(pool):
            ks = [n["i"]] + [a.get("i") if isinstance(a, dict) else a for a in (n.get("also") if isinstance(n.get("also"), list) else [])]
            for k in ks:                                                                       # основното заглавие може да е от "also" (по-надеждният източник)
                if isinstance(k, int) and not isinstance(k, bool) and 0 <= k < len(pool):
                    flows_by_title.setdefault(pool[k]["title"], n.get("etf_flows") is True)
    out, etf = [], 0
    for p in picked:
        if flows_by_title.get(p["headline"]):
            etf += 1
            if etf > 1:
                dropped.append({"headline": p["headline"], "reason": "второ заглавие за дневни потоци в ETF"})
                continue
        src = next((r for r in pool if r["title"] == p["headline"]), {})
        out.append({"headline": p["headline"], "source": p.get("source"), "link": src.get("link"), "why": p["why"], **({"also": p["also"]} if p.get("also") else {})})
    if len(out) > max_items:
        dropped += [{"headline": x["headline"], "reason": f"над тавана от {max_items}"} for x in out[max_items:]]
    return out[:max_items], dropped


def pool_record(pool: list[dict], data, items: list[dict], dropped: list[dict]) -> list[dict]:
    """
    29.10.2026: целият пул в данните на брифа — [{i, title, status, reason?}]; status: "избрана" / "слята с избрана" (същото събитие — в „също“) / "махната от кода" (AI я избра,
    проверката я махна — reason) / "не е избрана от AI". Причината: на 29.10 не се виждаше дали „DTCC unit launches tokenization services“ (28.10, 13:19 UTC) е била в пула и е отсята, или фийдът не я е дал. Чиста функция.
    """
    picked = {x.get("headline") for x in items or []}
    merged = {a.get("headline") for x in items or [] for a in x.get("also") or []}
    ai = {}
    for n in (data.get("news", []) if isinstance(data, dict) else []):
        if isinstance(n, dict) and isinstance(n.get("i"), int) and not isinstance(n.get("i"), bool) and 0 <= n["i"] < len(pool):
            ai.setdefault(n["i"], True)
    why = {}
    for d in dropped or []:
        k = d.get("i") if isinstance(d.get("i"), int) else next((j for j, r in enumerate(pool) if r["title"] == d.get("headline")), None)
        if k is not None:
            why.setdefault(k, d.get("reason"))
    out = []
    for k, r in enumerate(pool):
        row = {"i": k, "title": r["title"]}
        if r["title"] in picked:
            row["status"] = "избрана"
        elif r["title"] in merged:
            row["status"] = "слята с избрана"
        elif k in ai:
            row.update(status="махната от кода", reason=why.get(k) or "след проверките")
        else:
            row["status"] = "не е избрана от AI"
        out.append(row)
    return out


def fetch_pool() -> list[dict]:
    """29.10.2026 (разходката, т. 4б): пулът — Cointelegraph и CoinDesk (config.CRYPTO_RSS_FEEDS), заглавията на редуване (news_aggregator._interleave); дубълът по заглавие отпада.
    Източник без заглавия — ред в лога (останалият стига)."""
    from src import news_aggregator
    per = []
    for name, url in config.CRYPTO_RSS_FEEDS.items():
        got = news_aggregator._fetch_rss(url, name, config.CRYPTO_NEWS_HOURS, limit=50)
        if not got:
            print(f"[crypto] ⚠ {name}: фийдът не върна заглавия")
        per.append(got)
    seen, pool = set(), []
    for r in news_aggregator._interleave(per):
        k = r["title"].casefold()[:90]
        if k not in seen:
            seen.add(k); pool.append(r)
    return pool


def pool_sources(pool: list[dict]) -> dict:
    """{източник: {"count", "oldest"}} — oldest е най-старото заглавие в пула (UTC), за да се види дали фийдът покрива прозореца (CRYPTO_NEWS_HOURS). Чиста функция."""
    out = {name: {"count": 0, "oldest": None} for name in config.CRYPTO_RSS_FEEDS}
    for r in pool:
        o = out.setdefault(r.get("source"), {"count": 0, "oldest": None})
        o["count"] += 1
        if r.get("published") and (o["oldest"] is None or r["published"] < o["oldest"]):
            o["oldest"] = r["published"]
    return out


def cot_reading(pts: list[dict] | None) -> dict | None:
    """COT за Bitcoin (CME, managed money net) — последният отчет и перцентилът му спрямо прозореца на COT модула (същата сметка като екстремумите). < 10 точки → None."""
    from src import cot
    if not pts or len(pts) < 10:
        return None
    window = pts[-cot._LOOKBACK_WEEKS:]
    values = [p["net"] for p in window]
    return {"as_of": window[-1]["date"], "net": int(values[-1]), "percentile": cot._percentile_rank(values[:-1] or values, values[-1]), "weeks": len(window)}


def ticker_rows(tickers: list[str], today: str, download=None) -> list[dict]:
    """Последният ЦЯЛ бар (преди днес) на тикърите: close, промяна за 1 и 5 сесии. Провал / липсва тикър → без ред за него."""
    try:
        if download is None:
            import yfinance as yf
            download = lambda t: yf.download(t, period="15d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        df = download(list(tickers))
        out = []
        for t in tickers:
            try:
                c = (df[t] if len(tickers) > 1 else df)["Close"].dropna()
                c = c[c.index < __import__("pandas").Timestamp(today)]
                if len(c) < 6:
                    continue
                out.append({"ticker": t, "date": c.index[-1].date().isoformat(), "close": round(float(c.iloc[-1]), 2),
                            "chg_1d_pct": round((float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100, 1), "chg_5d_pct": round((float(c.iloc[-1]) / float(c.iloc[-6]) - 1) * 100, 1)})
            except Exception:
                continue
        return out
    except Exception as e:
        print(f"[crypto] цените на тикърите: {type(e).__name__}: {e}")
        return []


def build(today: str, cot_fresh: bool = False, cot_series: dict | None = None, fetch=None, ai_call=None, download=None, cache_path=None) -> dict:
    """
    {"ok", "items", "pool", "reason", "tickers", "cot_btc"}. fetch() → пулът от RSS; ai_call(system, user) → JSON текст (по подразбиране ai_brief._call_claude). Кеш по ден в
    config.DATA_DIR/crypto_news_cache.json (само новините — цените и COT се смятат всеки път). Не вдига.
    """
    LAST_STATUS.clear()
    LAST_STATUS.update(ok=False, reason="не завърши", count=0)
    out = {"ok": False, "items": [], "pool": 0, "pool_items": [], "pool_sources": {}, "reason": None, "tickers": [], "cot_btc": None}
    path = cache_path or (config.DATA_DIR / "crypto_news_cache.json")
    try:
        cached = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        cached = {}
    try:
        if cached.get("date") == today and "items" in cached:
            out.update(ok=True, items=cached["items"], pool=cached.get("pool", 0), pool_items=cached.get("pool_items", []), pool_sources=cached.get("pool_sources", {}),
                       reason=cached.get("reason"))
        else:
            from src import news_aggregator
            pool = (fetch or fetch_pool)()
            out["pool"] = len(pool)
            out["pool_sources"] = pool_sources(pool)                            # 29.10.2026: колко заглавия и колко назад — по източник
            if not pool:
                out["reason"] = f"фийдовете ({', '.join(config.CRYPTO_RSS_FEEDS)}) не върнаха заглавия"
            else:
                ai_call = ai_call or crypto_news_call
                from src import ai_brief as _ab
                data = _ab._parse_json(ai_call(_SYSTEM, _prompt(pool, config.CRYPTO_MAX_ITEMS)))
                items, dropped = select(data, pool)
                for d in dropped:
                    print(f"[crypto] ⚠ {d.get('reason')}: {d.get('headline') or d.get('h') or d.get('i')}")
                pool_items = pool_record(pool, data, items, dropped)                    # 29.10.2026: целият пул и какво стана с всяко заглавие
                out.update(ok=True, items=items, pool_items=pool_items)
                try:
                    path.write_text(json.dumps({"date": today, "items": items, "pool": len(pool), "pool_items": pool_items, "pool_sources": out["pool_sources"]}, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    print(f"[crypto] кешът не се записа: {type(e).__name__}")
    except Exception as e:
        out["reason"] = f"подборът не успя ({type(e).__name__})"
        print(f"[crypto] {out['reason']}: {e}")
    out["tickers"] = ticker_rows(config.CRYPTO_TICKERS, today, download)
    if cot_fresh:
        out["cot_btc"] = cot_reading((cot_series or {}).get(config.CRYPTO_COT_MARKET))
    LAST_STATUS.update(ok=out["ok"], reason=out["reason"] or "", count=len(out["items"]))
    return out
