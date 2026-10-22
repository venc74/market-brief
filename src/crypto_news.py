"""
22.10.2026 (етап 4 — решения от 21–22.10): крипто секция. Новините са от RSS на Cointelegraph (config.CRYPTO_RSS_URL — https://cointelegraph.com/rss; адресът „?format=rss“
връща HTML страница) през същия начин като новините: AI избира по индекс и дава само „защо“, а заглавието и източникът са ДОСЛОВНИ от фийда (news_aggregator.pick_verbatim).
Минава: регулация, ETF потоци и одобрения, големи хакове и фалити, решения на големи борси и банки, макро с ефект върху крипто. Не минава: прогнози и дневни отчети за цената,
малки монети, мнения на анализатори, обзори. Измерено 21.10 върху 304 реални заглавия (30.09–21.10, моя преценка по критериите): минават 50, т.е. 0–6 на ден; истинският
филтър се проверява на живо първите дни. Под новините: COIN, HOOD, CRCL, BLSH (последен close и промяна) и COT за Bitcoin — само в първия бриф след нов отчет на CFTC.
Без значими новини — един ред. Всяка грешка → празен резултат с причина (graceful); кеш по ден (повторен run не вика AI втори път).
"""
from __future__ import annotations

import datetime as dt
import json

import config

CATEGORIES = {"regulation": "регулация", "etf_flows": "ETF потоци", "hack": "голям хак / фалит", "exchange_bank": "решение на голяма борса / банка", "macro": "макро с ефект върху крипто"}
LAST_STATUS: dict = {}

_SYSTEM = ("Ти си редактор на крипто новини за суинг търговец. Връщаш САМО валиден JSON. Избираш по индекс от дадените заглавия; не пишеш и не превеждаш заглавия, "
           "не измисляш факти и не добавяш числа, които ги няма в заглавието или резюмето. Не даваш препоръка за покупка или продажба.")


def _prompt(pool: list[dict], max_items: int) -> str:
    compact = [{"i": k, "t": r["title"], "d": r.get("summary") or ""} for k, r in enumerate(pool)]
    cats = "\n".join(f'- "{k}": {v}' for k, v in CATEGORIES.items())
    return ("От тези крипто новини избери САМО значимите за пазара:\n"
            f"{cats}\n"
            "Голям хак или фалит = над около $50 млн. или голяма борса / доставчик; регулация = голяма юрисдикция (САЩ, ЕС, Обединеното кралство, Азия) или правило, което засяга голяма борса или стейбълкойн.\n"
            "НЕ избирай: прогнози и дневни отчети за цената (дори когато се обясняват с макро — макрото е другаде в брифа), малки монети и технически ъпгрейди, мнения и анализи, "
            "проучвания, обзори, повторение на вече избрано събитие.\n"
            f"Най-много {max_items} новини и най-много 1 за ETF потоци. Ако няма значима — върни празен списък.\n"
            "За всяка: \"i\" (индексът), \"h\" (ДОСЛОВНО първите 6 думи на заглавието \"t\" — кодът проверява индекса), \"cat\" (ключ от списъка), "
            "\"why\" (ЕДНО изречение на български — ефектът за крипто пазара или за COIN / HOOD / CRCL / BLSH; без числа, които ги няма в \"t\" или \"d\").\n\n"
            f"НОВИНИ:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
            'Върни само JSON: {"news": [{"i": 0, "h": "първите шест думи", "cat": "regulation", "why": "..."}]}')


def crypto_news_call(system: str, user: str) -> str:
    """AI извикването на крипто секцията — именувана функция (етикетът в brief["ai_usage"] е по името на извикващия; ai_brief._SECTION_LABELS)."""
    from src import ai_brief
    return ai_brief._call_claude(system, user, max_tokens=1500)


def select(data, pool: list[dict], max_items: int | None = None) -> tuple[list[dict], list[dict]]:
    """Отговорът на AI → [{headline, source, link, cat, cat_label, why}]: индекс и ехо през news_aggregator.pick_verbatim; категория от списъка; най-много 1 за ETF потоци. Чиста функция."""
    from src import news_aggregator
    max_items = max_items or config.CRYPTO_MAX_ITEMS
    raw = data.get("news", []) if isinstance(data, dict) else []
    picked, dropped = news_aggregator.pick_verbatim(raw, pool, len(pool))
    cat_by_title = {}
    for n in raw:
        if isinstance(n, dict) and isinstance(n.get("i"), int) and not isinstance(n.get("i"), bool) and 0 <= n["i"] < len(pool):
            cat_by_title.setdefault(pool[n["i"]]["title"], n.get("cat"))
    out, etf = [], 0
    for p in picked:
        cat = cat_by_title.get(p["headline"])
        if cat not in CATEGORIES:
            dropped.append({"headline": p["headline"], "reason": f"категория извън списъка ({cat})"})
            continue
        if cat == "etf_flows":
            etf += 1
            if etf > 1:
                dropped.append({"headline": p["headline"], "reason": "второ заглавие за ETF потоци"})
                continue
        src = next((r for r in pool if r["title"] == p["headline"]), {})
        out.append({"headline": p["headline"], "source": p.get("source"), "link": src.get("link"), "cat": cat, "cat_label": CATEGORIES[cat], "why": p["why"]})
    return out[:max_items], dropped


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
    out = {"ok": False, "items": [], "pool": 0, "reason": None, "tickers": [], "cot_btc": None}
    path = cache_path or (config.DATA_DIR / "crypto_news_cache.json")
    try:
        cached = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        cached = {}
    try:
        if cached.get("date") == today and "items" in cached:
            out.update(ok=True, items=cached["items"], pool=cached.get("pool", 0), reason=cached.get("reason"))
        else:
            from src import news_aggregator
            pool = (fetch or (lambda: news_aggregator._fetch_rss(config.CRYPTO_RSS_URL, "Cointelegraph", config.CRYPTO_NEWS_HOURS, limit=50)))()
            out["pool"] = len(pool)
            if not pool:
                out["reason"] = "фийдът на Cointelegraph не върна заглавия"
            else:
                ai_call = ai_call or crypto_news_call
                from src import ai_brief as _ab
                data = _ab._parse_json(ai_call(_SYSTEM, _prompt(pool, config.CRYPTO_MAX_ITEMS)))
                items, dropped = select(data, pool)
                for d in dropped:
                    print(f"[crypto] ⚠ {d.get('reason')}: {d.get('headline') or d.get('h') or d.get('i')}")
                out.update(ok=True, items=items)
                try:
                    path.write_text(json.dumps({"date": today, "items": items, "pool": len(pool)}, ensure_ascii=False), encoding="utf-8")
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
