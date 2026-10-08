"""
Каре "Контекст" към геополитическите тези (FIX 2026-09-29).

Поводът: на 29.09 тезата за отбраната беше маркирана от проверката срещу
новините заради договор на RTX за $20.7 млрд, а RTX беше −10% за месец, под
200DMA, в сектор, маркиран като изоставащ, с отчет на 20.10. Бележката от
новините казва какво се е случило; карето казва в какво състояние е пазарът
около тезата — за да не се чете новината като сигнал за вход.

САМО данни, без AI текст — включително обобщителният ред над таблицата се
сглобява от кода. Карето се показва при теза, маркирана от проверката срещу
новините, или със статус "active" (макро тригерът е задействан).

Отделно, за ВСИЧКИ тези: тикър без ценови данни излиза с видимо
предупреждение в брифа и в лога. CEIX (слята в CNR от 15.01.2025) и TELL
(купена от Woodside, 10.2024) стояха в конфигурацията месеци без никакъв сигнал.

Мрежова цена: една yf.download заявка за всички тикъри от тезите (~2 с за 25)
+ tk.calendar само за тикърите в карета (~0.1 с на тикър). Graceful:
провал навсякъде → тезите се връщат непроменени, липсваща стойност → "—".
"""
from __future__ import annotations
import datetime as dt

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

try:
    import pandas as pd
except Exception:
    pd = None
try:
    import yfinance as yf
except Exception:
    yf = None

# статуси от ai_brief.thesis_reality_check(), при които тезата получава каре
FLAGGED_NEWS = ("challenged", "resolved", "evolving", "confirmed")


def _closes(tickers: list[str]) -> dict:
    """Една batch заявка → {тикър: серия затваряния без NaN}. Липсващ → няма ключ."""
    out = {}
    if yf is None or not tickers:
        return out
    try:
        data = yf.download(tickers, period="1y", progress=False,
                           auto_adjust=True, threads=True)["Close"]
    except Exception as e:
        print(f"[thesis_context] ценова заявка неуспешна: {e}")
        return out
    if pd is not None and isinstance(data, pd.Series):
        data = data.to_frame(name=tickers[0])
    for sym in tickers:
        if sym in data.columns:
            s = data[sym].dropna()
            if len(s):
                out[sym] = s
    return out


def _price_stats(s) -> dict:
    """1 месец = 21 сесии; 50/200DMA = проста средна на последните N затваряния."""
    last = float(s.iloc[-1])
    out = {"chg_1m_pct": round((last / float(s.iloc[-22]) - 1) * 100, 1) if len(s) >= 22 else None,
           "above_50": None, "above_200": None, "history_days": len(s)}
    if len(s) >= 50:
        out["above_50"] = last > float(s.tail(50).mean())
    if len(s) >= 200:
        out["above_200"] = last > float(s.tail(200).mean())
    return out


def _next_earnings(sym: str, today: dt.date) -> str | None:
    """Следващ отчет от tk.calendar; минала дата се отхвърля (както enrich.earnings_info)."""
    try:
        cal = yf.Ticker(sym).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        future = sorted(d for d in (dates or []) if isinstance(d, dt.date) and d >= today)
        return future[0].isoformat() if future else None
    except Exception as e:
        print(f"[thesis_context] {sym}: календар за отчет неуспешен: {e}")
        return None


def _business_days(a: dt.date, b: dt.date) -> int:
    """Работни дни от a до b (без a) — същата мярка като EARNINGS_BLACKOUT_DAYS."""
    n, d = 0, a
    while d < b:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _sector(basket: dict, rotation: list[dict]) -> dict:
    etf = basket.get("sector_etf")
    row = next((r for r in rotation or [] if r.get("etf") == etf), None) if etf else None
    return {"etf": etf, "label": basket.get("sector_etf_label"),
            "rs_4w": row.get("rs_chg_4w_pct") if row else None,
            "rs_12w": row.get("rs_chg_12w_pct") if row else None,
            "laggard": bool(row.get("confirmed_laggard")) if row else None,
            "leading": bool(row.get("leading")) if row else None}


def _summary(rows: list[dict], sector: dict) -> str:
    """Ред-обобщение, сглобен само от числата в таблицата."""
    parts = []
    with_200 = [r for r in rows if r.get("above_200") is not None]
    if with_200:
        below = sum(1 for r in with_200 if not r["above_200"])
        parts.append(f"{below}/{len(with_200)} под 200DMA")
    if not sector.get("etf"):
        parts.append("без секторен ETF")
    elif sector.get("laggard") is None:
        parts.append("секторът: няма данни")
    elif sector["laggard"]:
        parts.append("секторът изостава")
    elif sector.get("leading"):
        parts.append("секторът води")
    else:
        parts.append("секторът неутрален")
    upcoming = [r for r in rows if r.get("days_to_earnings") is not None]
    if upcoming:
        d = min(r["days_to_earnings"] for r in upcoming)
        first = [r["ticker"] for r in upcoming if r["days_to_earnings"] == d]
        parts.append(f"отчет след {d} дни" +
                     ("" if len(first) == len(upcoming) else f" ({', '.join(first)})"))
    missing = [r["ticker"] for r in rows if r.get("no_price_data")]
    if missing:
        parts.append(f"без ценови данни: {', '.join(missing)}")
    return " · ".join(parts)


def _price_diverges(rows: list[dict], sector: dict) -> bool:
    """
    FIX 2026-10-01 (т.2 от прегледа на 01.10): чисто визуален флаг — gate-овете
    (news_status/G0-G3, laggard/leading класификацията) НЕ се пипат тук, само
    се чете резултатът им. True когато "потвърдена от новина" тезата всъщност
    се търгува обратно на механизма ѝ: мнозинство тикъри под 200DMA (сред
    редовете с известна стойност — not None) ИЛИ секторният RS е отрицателен
    и на 4, и на 12 седмици. "Мнозинство" = строго >50% (не тай/половина) —
    реалният пример от 01.10 (Финанси: JPM above_200=True, BAC above_200=False,
    1/2 не е мнозинство) пада под тази проверка през RS крака (-6.65%/-6.14%),
    не през 200DMA крака — двата критерия са умишлено независими (ИЛИ, не И).
    """
    with_200 = [r for r in rows if r.get("above_200") is not None]
    majority_below_200 = bool(with_200) and sum(1 for r in with_200 if not r["above_200"]) > len(with_200) / 2
    rs_both_negative = (sector.get("rs_4w") is not None and sector.get("rs_12w") is not None
                        and sector["rs_4w"] < 0 and sector["rs_12w"] < 0)
    return majority_below_200 or rs_both_negative


def annotate(theses: list[dict], rotation: list[dict], regime: str,
             positions: set[str], action: set[str], watchlist: set[str],
             today: dt.date | None = None) -> list[dict]:
    """
    Добавя към всяка теза "missing_price" (тикъри без ценови данни), а към
    маркираните — "context" {regime, sector, summary, rows}. Не пипа status,
    chain или news_* полетата.
    """
    if not theses:
        return theses
    today = today or dt.date.today()
    try:
        baskets = {b["name"]: b for b in config.THESIS_BASKETS}
        all_tickers = sorted({t for th in theses for t in th.get("tickers") or []})
        closes = _closes(all_tickers)
        # празен резултат за ВСИЧКИ = паднала заявка, не делистнати тикъри —
        # без предупреждения (иначе фалшива тревога за 25 тикъра)
        price_ok = bool(closes)
        if not price_ok:
            print("[thesis_context] няма ценови данни за нито един тикър — заявката "
                  "вероятно е паднала; проверката за делистнати се пропуска днес")
        out = []
        for th in theses:
            th = dict(th)
            missing = [t for t in th.get("tickers") or [] if price_ok and t not in closes]
            if missing:
                print(f"[thesis_context] ⚠ '{th.get('name')}': няма ценови данни за "
                      f"{missing} — вероятно делистнат/сменен тикър, провери "
                      f"config.THESIS_BASKETS")
                th["missing_price"] = missing
            if th.get("news_status") in FLAGGED_NEWS or th.get("status") == "active":
                th["context"] = _context(th, baskets.get(th.get("name"), {}), closes,
                                         rotation, regime, positions, action, watchlist, today)
            out.append(th)
        n_ctx = sum(1 for t in out if t.get("context"))
        n_miss = sum(len(t.get("missing_price") or []) for t in out)
        print(f"[thesis_context] {len(all_tickers)} тикъра · {len(closes)} с цени · "
              f"{n_ctx} карета · {n_miss} без ценови данни")
        return out
    except Exception as e:
        print(f"[thesis_context] неуспешен изцяло: {type(e).__name__}: {e}")
        return theses


def _context(th, basket, closes, rotation, regime, positions, action, watchlist, today):
    rows = []
    for sym in th.get("tickers") or []:
        row = {"ticker": sym}
        if sym in closes:
            row.update(_price_stats(closes[sym]))
        elif closes:  # при паднала заявка — "—", не "няма ценови данни"
            row["no_price_data"] = True
        ed = _next_earnings(sym, today)
        if ed:
            d = dt.date.fromisoformat(ed)
            row.update({"next_earnings": ed, "days_to_earnings": (d - today).days,
                        "earnings_soon": _business_days(today, d) <= config.EARNINGS_BLACKOUT_DAYS})
        row["status"] = ("позиция" if sym in positions else "Action" if sym in action
                         else "watchlist" if sym in watchlist else None)
        rows.append(row)
    sector = _sector(basket, rotation)
    ctx = {"regime": regime, "sector": sector, "rows": rows,
           "summary": _summary(rows, sector),
           "price_diverges": _price_diverges(rows, sector)}
    groups = _group_blocks(basket, rows, rotation)
    if groups:                                    # 08.10 (2в): подгрупи със собствен ориентир и собствено обобщение; предупреждението за цената — ако някоя група се търгува обратно на механизма
        ctx["groups"] = groups
        ctx["price_diverges"] = any(g["price_diverges"] for g in groups)
    return ctx


def _group_blocks(basket: dict, rows: list[dict], rotation: list[dict]) -> list[dict]:
    """
    Подгрупите на тезата (config.THESIS_BASKETS "groups": име, тикъри, sector_etf[, sector_etf_label]) — за всяка свой ориентир (секторен ETF), собствена таблица и собствено обобщение,
    сглобено САМО от числата в нейните редове. Група без ред от таблицата се пропуска. Основание (08.10): добивът на уран и операторите/реакторите не се движат заедно — общ ориентир (URA)
    за всички шест тикъра казва нещо само за добива.
    """
    out = []
    for g in basket.get("groups") or []:
        syms = set(g.get("tickers") or [])
        sub = [r for r in rows if r["ticker"] in syms]
        if not sub:
            continue
        sector = _sector(g, rotation)
        out.append({"name": g.get("name"), "sector": sector, "rows": sub, "summary": _summary(sub, sector),
                    "price_diverges": _price_diverges(sub, sector)})
    return out
