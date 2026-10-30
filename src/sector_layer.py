"""
Слой 2: Секторна логика и ротация.
RS Line на всеки секторен ETF спрямо SPY — кои сектори печелят
относителна сила в последните 4 и 12 седмици. Тук са само измеримите данни;
от 30.10.2026 (разходката, т. 7) и секторната карта (sector_board) е от кода —
веригите на Claude (макро събитие → сектор) отпаднаха.
"""
from __future__ import annotations
import datetime as dt
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import net_utils


def _laggard_persistence(rs) -> tuple[float | None, bool]:
    """
    FIX 2026-08-2x (Short/Stage 4 screener): наивен single-day "chg_4w<0 AND
    chg_12w<0" дава false positives от еднодневен шум — потвърдено на живо
    (ITA/Индустрия both-negative само 1-2 от последните 20 дни, докато
    XLU/TAN устойчиво 16-20/20). Проверява последните
    config.SECTOR_PERSISTENCE_WINDOW_DAYS дни: колко от тях СЪЩО показват
    both-negative (не само днешния ред) — устойчивост, не snapshot.

    Връща (persistence_pct, confirmed_laggard). None ако rs серията е
    твърде къса за пълния прозорец (graceful — не гърми, просто не гейтва).
    """
    window = config.SECTOR_PERSISTENCE_WINDOW_DAYS
    min_needed = window + 63  # всеки тестван ден сам нуждае от 63-дневна RS история назад
    if len(rs) < min_needed:
        return None, False

    # FIX 2026-08-28 (production crash — json.dumps(rotation) в ai_brief.py
    # без default= fallback гръмна "TypeError: Object of type bool is not
    # JSON serializable"): rs.iloc[idx] тук НЕ беше float()-кастнато (за
    # разлика от останалата част на sector_rotation(), която explicit го
    # прави навсякъде другаде) — сравнения върху суров numpy/pandas scalar
    # произвеждат numpy.bool_, не native bool. NumPy 2.x показва
    # numpy.bool_.__class__.__name__ буквално като "bool" (старите версии —
    # "bool_"), затова грешката подвеждащо изглеждаше като нормален Python
    # bool. float() каст тук, same стил като rs_now/rs_4w/rs_12w по-горе.
    both_neg_flags = []
    for lag in range(window):
        idx = -1 - lag
        r_now = float(rs.iloc[idx])
        r_4w = float(rs.iloc[idx - 21])
        r_12w = float(rs.iloc[idx - 63])
        both_neg_flags.append(r_now / r_4w - 1 < 0 and r_now / r_12w - 1 < 0)

    persistence_pct = round(sum(both_neg_flags) / window * 100, 1)
    # Explicit bool() каст — defensive, дори след float()-a по-горе, за да
    # не разчитаме мълчаливо, че sum()/>= винаги връща native bool.
    confirmed_laggard = bool(sum(both_neg_flags) >= config.SECTOR_PERSISTENCE_MIN_DAYS)
    return persistence_pct, confirmed_laggard


# Състоянието на последното извикване на sector_rotation() — main го слага в брифа като предупреждение.
# {"ok": bool, "reason": str, "etfs_total": int, "etfs_ok": int}
LAST_STATUS: dict = {}


def sector_rotation() -> list[dict]:
    """
    FIX 2026-10-03 (пакет 2 т.6): паднал или празен Yahoo (yf.download връща празна таблица или хвърля) вече не сваля
    run-а с KeyError/TypeError — функцията връща [] и записва причината в LAST_STATUS (main.py я показва в брифа).
    Всеки ETF е в собствен try/except: един лош ETF (твърде къса RS история и т.н.) не губи останалите. Празният
    резултат се чете надолу като "няма секторни данни" (leading_sectors([]) = [], laggard_sectors([]) = []).
    """
    etfs = {k: v for k, v in config.SECTOR_ETFS.items() if "PROXY" not in k}
    symbols = list(etfs.keys()) + ["SPY"]
    LAST_STATUS.clear()
    LAST_STATUS.update(ok=False, reason="", etfs_total=len(etfs), etfs_ok=0)
    try:
        data = yf.download(symbols, period="6mo", progress=False, auto_adjust=True)["Close"]
        if data is None or len(data) == 0:
            raise ValueError("Yahoo върна празна таблица")
        spy = data["SPY"].dropna()
        if len(spy) < 65:
            raise ValueError(f"SPY има само {len(spy)} реда история (нужни ≥ 65)")
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        LAST_STATUS["reason"] = reason
        print(f"[sector] ⚠ секторната ротация не е изчислена — Yahoo данните са недостъпни ({reason})")
        return []

    results = []
    for sym, name in etfs.items():
        try:
            if sym not in data.columns:
                continue
            series = data[sym].dropna()
            if len(series) < 65:
                continue
            rs = (series / spy).dropna()
            rs_now = float(rs.iloc[-1])
            rs_4w = float(rs.iloc[-21])
            rs_12w = float(rs.iloc[-63])
            rs_max_6m = float(rs.max())

            chg_4w = (rs_now / rs_4w - 1) * 100
            chg_12w = (rs_now / rs_12w - 1) * 100
            at_high = rs_now >= rs_max_6m * 0.99
            persistence_pct, confirmed_laggard = _laggard_persistence(rs)

            results.append({
                "etf": sym, "sector": name,
                "rs_chg_4w_pct": round(chg_4w, 2),
                "rs_chg_12w_pct": round(chg_12w, 2),
                "rs_at_6m_high": at_high,
                "abs_chg_4w_pct": round((float(series.iloc[-1]) / float(series.iloc[-21]) - 1) * 100, 2),
                "leading": chg_4w > 0 and chg_12w > 0,
                "laggard_persistence_pct": persistence_pct,
                "confirmed_laggard": confirmed_laggard,
            })
        except Exception as e:
            print(f"[sector] {sym} пропуснат: {type(e).__name__}: {e}")

    results.sort(key=lambda x: x["rs_chg_4w_pct"], reverse=True)
    LAST_STATUS.update(ok=bool(results), etfs_ok=len(results),
                       reason="" if results else "нито един секторен ETF няма достатъчно история",
                       missing=sorted(set(etfs) - {r["etf"] for r in results}))          # 19.10.2026 (т. 12): частичната ротация — видимо
    if not results:
        print(f"[sector] ⚠ секторната ротация е празна — {LAST_STATUS['reason']}")
    return results


# ──────────────────────────────────────────────────────────────────────────
# 30.10.2026 (разходката, т. 7): секторната карта — от кода, без AI
# ──────────────────────────────────────────────────────────────────────────
def rs_word(rs_4w, rs_12w) -> str | None:
    """Думата до RS — същите като при наблюдаваните тикъри (watch_monitor.rs_word): води пазара / набира сила / отслабва / изостава."""
    from src.watch_monitor import rs_word as _w
    return _w(rs_4w, rs_12w)


def board_rows(data, spy, etfs: dict, lag: int | None = None) -> list[dict]:
    """
    Затварянията (DataFrame, колона на ETF) и SPY → редове за картата, подредени по сила: RS 4 / 12 седм. (RS линията ETF/SPY — промяна за 21 и 63 сесии, както
    sector_rotation), думата, RS на 6-месечен връх, силата = средното на двете RS и мястото преди `lag` сесии (същата сметка) → rank_change (+ = нагоре). Чиста функция.
    """
    lag = config.SECTOR_BOARD_RANK_LAG if lag is None else lag
    rows = []
    for sym, name in etfs.items():
        try:
            if sym not in data.columns:
                continue
            rs = (data[sym].dropna() / spy).dropna()
            if len(rs) < 64 + lag:
                continue
            chg = lambda i, n: (float(rs.iloc[i]) / float(rs.iloc[i - n]) - 1) * 100
            r4, r12, p4, p12 = chg(-1, 20), chg(-1, 62), chg(-1 - lag, 20), chg(-1 - lag, 62)
            rows.append({"etf": sym, "sector": name, "rs_4w": round(r4, 2), "rs_12w": round(r12, 2), "word": rs_word(r4, r12),
                         "strength": round((r4 + r12) / 2, 2), "strength_prev": (p4 + p12) / 2, "rs_at_6m_high": bool(float(rs.iloc[-1]) >= float(rs.max()) * 0.99)})          # както sector_rotation (данните са 6 месеца)
        except Exception as e:
            print(f"[sector] карта: {sym} пропуснат: {type(e).__name__}: {e}")
    prev_rank = {r["etf"]: k for k, r in enumerate(sorted(rows, key=lambda r: r["strength_prev"], reverse=True), 1)}
    rows.sort(key=lambda r: r["strength"], reverse=True)
    for k, r in enumerate(rows, 1):
        r["rank"] = k
        r["rank_change"] = prev_rank[r["etf"]] - k
        r.pop("strength_prev")
    return rows


def sector_leaders(etf: str, universe_sector: dict, trend: dict, ratings: dict, n: int | None = None) -> list[dict]:
    """
    Лидерите от нашия универс за секторен ETF: същият GICS сектор, над 50DMA и 200DMA, подредени по RS рейтинга (1–99) — с 1 месец, 50DMA и 200DMA от скрийнинга
    (за таблицата под реда на сектора). Чиста функция.
    """
    n = config.SECTOR_BOARD_LEADERS if n is None else n
    trend = trend or {}
    xs = [(t, ratings[t]) for t, sec in (universe_sector or {}).items()
          if config.GICS_SECTOR_ETF.get(sec) == etf and trend.get(t, {}).get("above_50") and trend.get(t, {}).get("above_200") and t in (ratings or {})]
    return [{"ticker": t, "rs_rating": min(99, r), "chg_1m_pct": trend[t].get("chg_1m_pct"), "above_50": trend[t]["above_50"], "above_200": trend[t]["above_200"]}
            for t, r in sorted(xs, key=lambda x: (-x[1], x[0]))[:n]]


def next_earnings(sym: str, today: dt.date) -> dict:
    """
    Следващият отчет за лидер — tk.calendar (~0.1 с на тикър); минала дата се отхвърля и тогава — get_earnings_dates (както enrich.earnings_info; без recap — той е за
    картите на кандидатите). Реално 30.10: 8 от 33 лидера с календар на току-що минал отчет (ILMN 29.10, TRV 16.10 …) — резервът дава следващия (ILMN 04.02.2027, TRV 20.01.2027).
    {next_earnings, days_to_earnings, earnings_soon} (скоро = до config.EARNINGS_BLACKOUT_DAYS сесии) или {} — провал / няма дата (graceful).
    """
    try:
        tk = yf.Ticker(sym)
        cal = net_utils.fetch_with_timeout(lambda: tk.calendar)
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        days = [d.date() if isinstance(d, dt.datetime) else d for d in (dates or []) if isinstance(d, dt.date)]
        future = sorted(d for d in days if d >= today)
        if not future:
            df = net_utils.fetch_with_timeout(lambda: tk.get_earnings_dates(limit=4))
            future = sorted(d for d in (ts.date() for ts in (df.index if df is not None else [])) if d >= today)
        if not future:
            return {}
        from src import sessions as _sessions
        d = future[0]
        return {"next_earnings": d.isoformat(), "days_to_earnings": (d - today).days, "earnings_soon": _sessions.sessions_in(today, d) <= config.EARNINGS_BLACKOUT_DAYS}
    except Exception as e:
        print(f"[sector] {sym}: календар за отчет неуспешен: {type(e).__name__}: {e}")
        return {}


def board_summary(rows: list[dict]) -> str:
    """
    Едно изречение от кода над таблицата: кои водят (думата „води пазара“), кои изостават („изостава“) и какво значи — групата с поне 2 от първите 3 (config.SECTOR_GROUPS);
    иначе „смесена картина“. Чиста функция.
    """
    if not rows:
        return ""
    lead = [r["sector"] for r in rows if r.get("word") == "води пазара"][:3]
    lag = [r["sector"] for r in reversed(rows) if r.get("word") == "изостава"][:3]
    top3 = {r["etf"] for r in rows[:3]}
    meaning = next((m for m, etfs in config.SECTOR_GROUPS.items() if len(top3 & set(etfs)) >= 2), "смесена картина — няма ясна посока на ротацията")
    lst = lambda xs: ", ".join(xs[:-1]) + " и " + xs[-1] if len(xs) > 1 else (xs[0] if xs else "")
    parts = [f"Водят {lst(lead)}" if lead else "Нито един сектор не води и на двата периода", f"изостават {lst(lag)}" if lag else "нито един не изостава и на двата"]
    return f"{parts[0]}; {parts[1]} — {meaning}."


def sector_board(download=None, universe_sector: dict | None = None, trend: dict | None = None, ratings: dict | None = None,
                 earnings_fn=None, today: dt.date | None = None) -> dict:
    """
    30.10.2026 (т. 7): {"sectors": [...редове + leaders], "subsectors": [...], "top_sub": 5, "bottom_sub": 3, "summary", "as_of"} — едно теглене (11-те секторни ETF-а,
    подсекторите и SPY, 6 месеца). Лидерите — от последния скрийнинг (screener.LAST_UNIVERSE_SECTOR / LAST_TREND / rs_ratings), подадени отвън; следващият отчет — next_earnings
    (earnings_fn(sym, today) за тестове). Провал → {} (graceful).
    """
    etfs = {e: config.SECTOR_ETFS.get(e, e) for e in config.SECTOR_BOARD_ETFS}
    subs = dict(config.SUBSECTOR_ETFS)
    try:
        from src import sessions as _sessions
        dl = download or (lambda syms: yf.download(syms, period="6mo", progress=False, auto_adjust=True)["Close"])
        data = _sessions.cut_today(dl(list(etfs) + list(subs) + ["SPY"]))                 # без днешния частичен бар (сутрин няма такъв — повторен run в сесията)
        spy = data["SPY"].dropna()
        sectors, subsectors = board_rows(data, spy, etfs), board_rows(data, spy, subs)
    except Exception as e:
        print(f"[sector] секторната карта не е изчислена: {type(e).__name__}: {e}")
        return {}
    today = today or dt.date.today()
    for r in sectors:
        r["leaders"] = sector_leaders(r["etf"], universe_sector or {}, trend or {}, ratings or {})
        for l in r["leaders"]:
            l.update((earnings_fn or next_earnings)(l["ticker"], today) or {})
    return {"sectors": sectors, "subsectors": subsectors, "summary": board_summary(sectors), "as_of": spy.index[-1].date().isoformat(),
            "top_sub": subsectors[:config.SECTOR_BOARD_SUB_TOP], "bottom_sub": subsectors[-config.SECTOR_BOARD_SUB_BOTTOM:][::-1] if len(subsectors) > config.SECTOR_BOARD_SUB_TOP else []}


def board_context(board: dict | None) -> list[dict]:
    """30.10.2026 (т. 7): секторите по кода за текста на картите (вместо веригите на AI) — водещите и набиращите сила: [{etf, sector, rs_4w, rs_12w, word}]."""
    return [{k: r.get(k) for k in ("etf", "sector", "rs_4w", "rs_12w", "word")} for r in (board or {}).get("sectors") or [] if r.get("word") in ("води пазара", "набира сила")]


def is_leader(row: dict) -> bool:
    """
    21.10.2026 (етап 4): ЕДНОТО правило за „водещ сектор“ — RS > 0 и на 4, и на 12 седмици, или RS на 6-месечен връх, И да НЕ е потвърдено изоставащ
    (confirmed_laggard — both-negative в поне SECTOR_PERSISTENCE_MIN_DAYS от последните SECTOR_PERSISTENCE_WINDOW_DAYS дни). Реално на 21.10: XLP (75%) и XLY (80%) бяха „водещи“
    по снимката на деня, а текстът им ги наричаше потвърдено изоставащи. Ползват го leading_sectors (подредба и SECT✓), картата и промптът.
    """
    return bool((row.get("leading") or row.get("rs_at_6m_high") is True) and not row.get("confirmed_laggard"))


def leading_sectors(rotation: list[dict], top_n: int = 6) -> list[dict]:
    """Секторите с положителна RS динамика — входът за скрининга (Слой 3). 21.10.2026: по is_leader (без потвърдено изоставащите)."""
    leaders = [s for s in rotation if is_leader(s)]
    return leaders[:top_n] if leaders else rotation[:3]


def etf_matches(row: dict, etf: str) -> bool:
    """Пакет 2 т.1: кандидатът е в сектора/индустрията на този ETF (config.SECTOR_ETF_YAHOO, точно, без регистър)."""
    rule = config.SECTOR_ETF_YAHOO.get(etf) or {}
    sector, industry = str(row.get("sector") or "").lower(), str(row.get("industry") or "").lower()
    return (bool(sector) and sector in [x.lower() for x in rule.get("sector", [])]) or \
           (bool(industry) and industry in [x.lower() for x in rule.get("industry", [])])


def tailwind_leaders(row: dict, leaders: list[dict]) -> list[dict]:
    """Водещите сектори (от leading_sectors), в които е кандидатът — [] ако няма съвпадение. Не филтрира."""
    return [l for l in leaders if etf_matches(row, l.get("etf"))]


def tailwind_marker(matched: list[dict]) -> dict | None:
    """Маркер SECT✓ за картата: кои водещи сектори и с каква относителна сила."""
    if not matched:
        return None
    parts = [f"{m.get('sector')} ({m.get('etf')}, RS {m.get('rs_chg_4w_pct'):+.1f}% за 4 седмици)"
             if isinstance(m.get("rs_chg_4w_pct"), (int, float)) else f"{m.get('sector')} ({m.get('etf')})" for m in matched]
    return {"tag": "SECT✓", "title": "Водещ сектор (макро попътен вятър): " + "; ".join(parts)}


def laggard_sectors(rotation: list[dict], top_n: int = 6) -> list[dict]:
    """
    Огледало на leading_sectors() — входът за Short/Stage 4 screener-а
    (short_screener.py). Филтрира по confirmed_laggard (persistence-gated,
    виж _laggard_persistence), НЕ по еднодневен snapshot. Сортирано по
    severity (rs_chg_12w_pct възходящо — най-отрицателните first), same
    "малко, но значимо" принцип като MAX_ACTION_TICKERS/COT whitelist-а.
    """
    laggards = sorted(
        (s for s in rotation if s.get("confirmed_laggard")),
        key=lambda x: x["rs_chg_12w_pct"],
    )
    return laggards[:top_n]


if __name__ == "__main__":
    import json
    rot = sector_rotation()
    print(json.dumps({"rotation": rot, "leaders": leading_sectors(rot)},
                     indent=2, ensure_ascii=False, default=str))
