"""
COT: дали работи (пакет 3 т.з, 2026-10-05). Чисти функции върху седмични цени и COT серията + една функция за теглене.

  1. Пресичане на SMA10 (преди "потвърждение от цената" — неутрално име от 05.10), изчислено от кода: инструментът ПРЕСИЧА 10-седмичната си средна (SMA10 на седмичните затваряния) в
     посоката на contrarian сигнала — за extreme_long (очаква се цената надолу) затварянето слиза под SMA10, за extreme_short
     (цената нагоре) се качва над нея; "потвърдено" само ако пресичането е скорошно (до config.COT_CONFIRM_LOOKBACK_WEEKS седмици)
     и цената още е от тази страна. Иначе "още не".
  2. Малък track record: за всеки as_of с екстремум (percentile ≤ 10 или ≥ 90 спрямо до 156 предишни седмици, както в cot.py)
     доходността на инструмента 2, 4 и 8 седмици по-късно — от наличната COT история и цените. Един ред на пазар + обобщение за секцията.

Времева линия: сигналът се вижда в петък след затварянето (отчетът е към вторник), затова входната цена е затварянето на
седмичния бар на as_of (петък) и доходността е от него. Потвърждението в историята ползва САМО барове до този момент
(без поглед напред). Само ЗАВЪРШЕНИ седмични бари (текущата, още неприключила седмица се изключва).
"""
from __future__ import annotations

import datetime as dt

import config

HORIZONS = (2, 4, 8)


def _pd():
    import pandas as pd
    return pd


def completed(close, today: dt.date | None = None):
    """Само завършените седмични бари: барът (дата = понеделник) е завършен, ако е минала петъчната му сесия (≥ 5 дни след него)."""
    today = today or dt.date.today()
    keep = [(today - ts.date()).days >= 5 for ts in close.index]
    return close[keep]


def weekly_closes(symbol: str, fetch=None):
    """Седмичните затваряния (5 г.) от Yahoo; провал/празно → None (graceful). `fetch` — за тестове (symbol → Series)."""
    try:
        if fetch is not None:
            s = fetch(symbol)
        else:
            import yfinance as yf
            from src import net_utils
            h = net_utils.fetch_with_timeout(lambda: yf.Ticker(symbol).history(period="5y", interval="1wk"))
            s = None if h is None or h.empty else h["Close"]
        if s is None:
            return None
        s = s.dropna()
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        s.index = s.index.normalize()
        return s if len(s) >= config.COT_SMA_WEEKS + 2 else None
    except Exception as e:
        print(f"[cot] цени за {symbol}: {type(e).__name__}: {e}")
        return None


def confirmation(close, direction: str) -> dict | None:
    """
    Потвърждение от цената към последния бар на `close` (седмични затваряния, най-старото първо).
    {"confirmed", "side" (below/above SMA10), "weeks_on_side", "crossed" (имало ли е пресичане), "close", "sma", "gap_pct",
     "state": "confirmed" | "not_crossed" | "stale_cross" | "from_start"}; None при твърде кратка история.
    """
    n_sma, lookback = config.COT_SMA_WEEKS, config.COT_CONFIRM_LOOKBACK_WEEKS
    if close is None or len(close) < n_sma + 1:
        return None
    sma = close.rolling(n_sma).mean()
    side = (close - sma).apply(lambda x: 0 if x != x else (1 if x > 0 else -1 if x < 0 else 0))
    want = -1 if direction == "extreme_long" else 1                     # extreme_long → цена надолу → под SMA10
    n = len(close)
    last = float(close.iloc[-1]); ma = float(sma.iloc[-1])
    out = {"close": round(last, 4), "sma": round(ma, 4), "gap_pct": round((last / ma - 1) * 100, 2),
           "side": "below" if last < ma else "above", "want": "below" if want == -1 else "above"}
    if int(side.iloc[-1]) != want:
        return {**out, "confirmed": False, "state": "not_crossed", "weeks_on_side": 0, "crossed": False}
    j = n - 1
    first_valid = n_sma - 1
    while j - 1 >= first_valid and int(side.iloc[j - 1]) == want:
        j -= 1
    run = n - j
    crossed = j - 1 >= first_valid                                         # има бар преди серията от другата страна → истинско пресичане
    if not crossed:
        return {**out, "confirmed": False, "state": "from_start", "weeks_on_side": run, "crossed": False}
    confirmed = run <= lookback
    return {**out, "confirmed": confirmed, "state": "confirmed" if confirmed else "stale_cross", "weeks_on_side": run, "crossed": True}


def confirmation_text(c: dict | None, direction: str) -> str:
    """
    Текстът за карта — шаблон от кода, НЕУТРАЛЕН: казва фактa (цената пресече ли SMA10 в посоката на сигнала), не "потвърждава" нищо
    (потребител, 05.10: на реалната история пресичането не помага за сигнала — виж track record-а).
    """
    if not c:
        return "SMA10: няма достатъчно ценови данни."
    side_bg = "под" if c["want"] == "below" else "над"
    other_bg = "над" if c["want"] == "below" else "под"
    gap = f"цена {c['close']:g} срещу SMA10 {c['sma']:g} ({c['gap_pct']:+.1f}%)"
    if c["state"] == "confirmed":
        ago = "тази седмица" if c["weeks_on_side"] <= 1 else f"преди {c['weeks_on_side'] - 1} седмици"
        return f"Цената пресече SMA10 в посоката на сигнала ({side_bg} нея, {ago}); {gap}."
    if c["state"] == "stale_cross":
        return (f"Цената е {side_bg} SMA10 от {c['weeks_on_side']} седмици — пресичането в посоката на сигнала не е скорошно "
                f"(над {config.COT_CONFIRM_LOOKBACK_WEEKS}); {gap}.")
    if c["state"] == "from_start":
        return f"Цената е {side_bg} SMA10, но няма видимо пресичане в наличната история; {gap}."
    return f"Цената не е пресякла SMA10 в посоката на сигнала (още е {other_bg} нея); {gap}."


# ──────────────────────────────────────────────────────────────────────────
# Track record
# ──────────────────────────────────────────────────────────────────────────
def historical_extremes(pts: list[dict]) -> list[dict]:
    """
    Всички седмици с екстремум в COT серията (като cot._market_extreme, но във всяка точка): percentile на нетната позиция
    спрямо ДО _LOOKBACK_WEEKS предишни седмици (без текущата), най-малко COT_TRACK_MIN_PRIOR_WEEKS предишни. Връща
    [{"as_of", "direction", "pct"}].
    """
    from src import cot
    lb, min_prior = cot._LOOKBACK_WEEKS, config.COT_TRACK_MIN_PRIOR_WEEKS
    out = []
    for i in range(min_prior, len(pts)):
        window = pts[max(0, i - lb + 1):i + 1]
        values = [p["net"] for p in window]
        pct = cot._percentile_rank(values[:-1] or values, values[-1])
        if pct >= config.COT_PERCENTILE_HIGH:
            out.append({"as_of": pts[i]["date"], "direction": "extreme_long", "pct": pct})
        elif pct <= config.COT_PERCENTILE_LOW:
            out.append({"as_of": pts[i]["date"], "direction": "extreme_short", "pct": pct})
    return out


def _bar_index(close, as_of: str) -> int | None:
    """Индексът на седмичния бар, в който попада as_of (последният бар с дата ≤ as_of); None ако е извън историята."""
    pd = _pd()
    ts = pd.Timestamp(as_of)
    i = int(close.index.searchsorted(ts, side="right")) - 1
    if i < 0 or (ts - close.index[i]).days > 6:
        return None
    return i


def track_rows(pts: list[dict], close) -> list[dict]:
    """
    Редовете на track record за пазара: за всеки исторически екстремум — потвърждение към тази седмица (само барове до нея) и
    доходностите 2/4/8 седмици по-късно (None, ако барът още не съществува). r* са сурови доходности на инструмента (дроб).
    """
    rows = []
    for ex in historical_extremes(pts):
        i = _bar_index(close, ex["as_of"])
        if i is None:
            continue
        entry = float(close.iloc[i])
        conf = confirmation(close.iloc[:i + 1], ex["direction"])
        row = {**ex, "confirmed": bool(conf and conf["confirmed"]), "has_conf": conf is not None, "entry": entry}
        for k in HORIZONS:
            row[f"r{k}"] = (float(close.iloc[i + k]) / entry - 1) if i + k < len(close) else None
        rows.append(row)
    return rows


def _signed(r: float | None, direction: str) -> float | None:
    """Доходност в посока на сигнала: extreme_long очаква спад (−r), extreme_short — ръст (+r)."""
    if r is None:
        return None
    return -r if direction == "extreme_long" else r


def episodes(rows: list[dict]) -> int:
    """Брой епизоди: поредни екстремуми на ЕДИН пазар (до 2 седмици разлика) в една посока са един епизод; сумира се по пазари."""
    n, prev = 0, {}
    for r in sorted(rows, key=lambda x: x["as_of"]):
        d = dt.date.fromisoformat(r["as_of"])
        key = (r.get("market"), r["direction"])
        p = prev.get(key)
        if p is None or (d - p).days > 14:
            n += 1
        prev[key] = d
    return n


def stats(rows: list[dict]) -> dict:
    """Агрегат за набор редове (една посока или смесено, всичко е в посока на сигнала): n, епизоди, средна и успех по хоризонт."""
    out = {"n": len(rows), "episodes": episodes(rows)}
    for k in HORIZONS:
        vals = [v for v in (_signed(r[f"r{k}"], r["direction"]) for r in rows) if v is not None]
        out[f"h{k}"] = {"n": len(vals), "mean_signal_pct": round(sum(vals) / len(vals) * 100, 2) if vals else None,
                        "hit_pct": round(sum(v > 0 for v in vals) / len(vals) * 100) if vals else None}
    return out


def market_track(rows: list[dict], direction: str) -> dict:
    """Редът за пазара: редовете в ТЕКУЩАТА посока (сурови и в посока на сигнала доходности), без/със потвърждение."""
    same = [r for r in rows if r["direction"] == direction]
    st = stats(same)
    for k in HORIZONS:
        raw = [r[f"r{k}"] for r in same if r[f"r{k}"] is not None]
        st[f"h{k}"]["mean_raw_pct"] = round(sum(raw) / len(raw) * 100, 2) if raw else None
    st["confirmed"] = stats([r for r in same if r["confirmed"]])
    st["not_confirmed"] = stats([r for r in same if not r["confirmed"]])
    st["direction"] = direction
    return st


def track_text(st: dict) -> str:
    """Един ред за пазара — шаблон от кода."""
    if not st or not st.get("n"):
        return "История: няма предишни екстремуми в тази посока в наличната COT история."
    parts = []
    for k in HORIZONS:
        h = st[f"h{k}"]
        parts.append("—" if h["n"] == 0 else f"{h['mean_raw_pct']:+.1f}% ({h['hit_pct']}% в посоката на сигнала)")
    small = " Малка извадка — не е за изводи." if st["episodes"] < config.COT_TRACK_MIN_EPISODES else ""
    return (f"История: {st['n']} седмици с екстремум в тази посока ({st['episodes']} епизода); доходност на инструмента след "
            f"2/4/8 седмици: {' / '.join(parts)}.{small}")


def summary(rows_by_market: dict[str, list[dict]], directions: dict[str, str]) -> dict:
    """Обобщение за секцията: всичко в посока на сигнала, за пазарите в секцията и тяхната ТЕКУЩА посока; с/без потвърждение."""
    rows = [r for m, rs in rows_by_market.items() for r in rs if r["direction"] == directions.get(m)]
    return {"markets": len(rows_by_market), **stats(rows),
            "confirmed": stats([r for r in rows if r["confirmed"]]), "not_confirmed": stats([r for r in rows if not r["confirmed"]])}


def summary_text(sm: dict) -> str:
    """Един ред за секцията — шаблон от кода (честно за ограниченията)."""
    if not sm or not sm.get("n"):
        return ""
    def seg(st, label):
        if not st["n"]:
            return f"{label}: n=0"
        h = st["h4"]
        return f"{label}: n={st['n']}, след 4 седм. " + ("—" if not h["n"] else f"{h['mean_signal_pct']:+.1f}% ({h['hit_pct']}% успех)")
    h = {k: sm[f"h{k}"] for k in HORIZONS}
    main = " / ".join("—" if not h[k]["n"] else f"{h[k]['mean_signal_pct']:+.1f}% ({h[k]['hit_pct']}%)" for k in HORIZONS)
    return (f"Обобщение (в посока на сигнала, {sm['markets']} пазара, {sm['n']} седмици в {sm['episodes']} епизода): след 2/4/8 седмици "
            f"{main}. {seg(sm['confirmed'], 'С пресичане на SMA10')}; {seg(sm['not_confirmed'], 'без пресичане')} "
            f"(SMA10 = 10-седмична средна на седмичните затваряния). "
            f"Седмиците се припокриват и историята е ~2–3 години — ориентир, не доказателство.")


# ──────────────────────────────────────────────────────────────────────────
# Към редовете на секцията
# ──────────────────────────────────────────────────────────────────────────
def annotate(cot_rows: list[dict], series_by_market: dict[str, list[dict]], today: dt.date | None = None,
             fetch=None) -> tuple[list[dict], dict | None]:
    """
    Добавя към всеки COT ред "price_confirmation" и "track_record" (нищо друго не се пипа) и връща (редове, обобщение за секцията).
    Graceful: липсващ символ/цени/серия → редът остава без тези полета; провалът на един пазар не пречи на останалите.
    series_by_market — пълната COT серия за пазара (cot.LAST_SERIES).
    """
    today = today or dt.date.today()
    out, rows_by_market, directions = [], {}, {}
    for c in cot_rows:
        m = c["market"]
        row = dict(c)
        try:
            symbol = config.COT_PRICE_SYMBOLS.get(m)
            close = weekly_closes(symbol, fetch) if symbol else None
            if close is not None:
                close = completed(close, today)
            pts = series_by_market.get(m)
            if close is not None and len(close) >= config.COT_SMA_WEEKS + 1:
                conf = confirmation(close, c["direction"])
                row["price_confirmation"] = {**(conf or {}), "symbol": symbol, "text": confirmation_text(conf, c["direction"])}
                if pts:
                    rows = [{**r, "market": m} for r in track_rows(pts, close)]
                    rows_by_market[m], directions[m] = rows, c["direction"]
                    st = market_track(rows, c["direction"])
                    row["track_record"] = {**st, "symbol": symbol, "text": track_text(st)}
        except Exception as e:
            print(f"[cot] ценово потвърждение/история за '{m}': {type(e).__name__}: {e}")
        out.append(row)
    sm = summary(rows_by_market, directions) if rows_by_market else None
    if sm:
        sm["text"] = summary_text(sm)
    return out, sm
