"""
Корпоративни действия върху картите (09.10.2026). Yahoo записва отделяне (spin-off) като "сплит" с НЕЦЯЛ коефициент и коригира историята с оценъчен коефициент: CTVA на 01.10 (отделянето на Vylor) = 6.665; в деня цената
скача +7.9% при обичайно дневно отклонение 1.9% — историята около датата е приблизителна. Цял коефициент (2:1, 4:1, 10:1, обратен 1:5) е точна корекция. Затова картите на Action, Watchlist, GLB и QM получават МАРКЕР
(не изключване) "⚠ корпоративно действие на ДД.ММ …", ако в последните config.CORP_ACTION_WARN_SESSIONS сесии има събитие с нецял коефициент. Само информация; нищо не се променя в избора на карти.
Данни: една партида yf.download(…, period="6mo", actions=True) за всички тикъри на картите (колоната "Stock Splits"). Graceful: провал → без маркери, diag.ok=False и предупреждение в брифа (липсата на маркер тогава не значи "няма събитие").
"""
from __future__ import annotations
import datetime as dt
import inspect
import re

import numpy as np
import pandas as pd

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

try:
    import yfinance as yf
except Exception:                                    # pragma: no cover
    yf = None


def is_whole_ratio(r: float) -> bool:
    """Цял сплит коефициент: r или 1/r е цяло число ≥ 2 (в рамките на config.CORP_ACTION_INTEGER_TOL). 6.665, 1.243, 1.5, 2.39 → не; 2, 4, 10, 0.5, 0.2, 0.3333 → да."""
    try:
        r = float(r)
        if not r > 0 or r == 1:
            return False
        x = r if r > 1 else 1 / r
        return abs(x - round(x)) <= config.CORP_ACTION_INTEGER_TOL * x and round(x) >= 2
    except (TypeError, ValueError):
        return False


def sessions_since(event: dt.date, today: dt.date) -> int:
    """Работни дни (без NYSE празниците от config) от датата на събитието до today; събитие в бъдещето → отрицателно."""
    hol = sorted(config.NYSE_HOLIDAYS)
    if event <= today:
        return int(np.busday_count(event, today, holidays=hol))
    return -int(np.busday_count(today, event, holidays=hol))


def uncertain_events(dates, ratios, today: dt.date, sessions: int | None = None) -> list[dict]:
    """Събитията с нецял коефициент в последните `sessions` сесии: [{date, ratio, sessions_ago}] (най-новото първо). dates/ratios — паралелни редове на колоната "Stock Splits"."""
    sessions = config.CORP_ACTION_WARN_SESSIONS if sessions is None else sessions
    out = []
    for d, r in zip(dates, ratios):
        try:
            if r is None or r != r or float(r) == 0:
                continue
            day = dt.date.fromisoformat(str(d)[:10])
        except (TypeError, ValueError):
            continue
        n = sessions_since(day, today)
        if 0 <= n <= sessions and not is_whole_ratio(r):
            out.append({"date": day.isoformat(), "ratio": round(float(r), 4), "sessions_ago": n})
    return sorted(out, key=lambda e: e["date"], reverse=True)


def warning_text(ev: dict) -> str:
    d = dt.date.fromisoformat(ev["date"])
    return (f"⚠ корпоративно действие на {d.day:02d}.{d.month:02d} (коефициент {ev['ratio']:g} — отделяне или сплит с нецял коефициент) — "
            f"историята около датата е приблизителна")


def fetch_splits(tickers: list[str]) -> dict[str, tuple[list[str], list[float]]]:
    """{тикър: (дати, коефициенти)} от колоната "Stock Splits" на ЕДНА партида от Yahoo. Провал на тегленето → вдига (annotate го хваща); тикър без колона/данни просто липсва."""
    if yf is None:
        raise RuntimeError("yfinance не е наличен")
    data = yf.download(list(tickers), period="6mo", progress=False, auto_adjust=False, actions=True, group_by="ticker", threads=True)
    if data is None or len(data) == 0:
        raise ValueError("празен резултат")
    out = {}
    multi = hasattr(data.columns, "levels") and getattr(data.columns, "nlevels", 1) > 1
    for t in tickers:
        try:
            f = data[t] if multi else data
            col = f["Stock Splits"].dropna()
            out[t] = ([x.date().isoformat() for x in col.index], [float(v) for v in col.to_numpy()])
        except Exception:
            continue
    return out


def annotate(cards_groups: list[list[dict]], today: str | dt.date, fetch=None, sessions: int | None = None) -> dict:
    """
    Слага card["corp_action"] = {date, ratio, sessions_ago, text} върху картите (по тикър, във всички списъци), за които има събитие с нецял коефициент в последните `sessions` сесии. Връща diag
    {ok, checked, flagged: [{ticker, date, ratio}], error}. Не вдига изключения (graceful): провал → ok=False, без маркери.
    """
    fetch = fetch or fetch_splits
    day = today if isinstance(today, dt.date) else dt.date.fromisoformat(str(today)[:10])
    tickers = sorted({c.get("ticker") for g in cards_groups for c in (g or []) if isinstance(c, dict) and c.get("ticker")})
    diag = {"ok": True, "checked": len(tickers), "flagged": [], "error": None}
    if not tickers:
        return diag
    try:
        series = fetch(tickers)
        found = {}
        for t, (dates, ratios) in series.items():
            ev = [e for e in uncertain_events(dates, ratios, day, sessions)
                  if t not in config.CORP_ACTION_EXACT_TICKERS and not is_exact_ratio(e["ratio"])]     # 13.10: 3:2 и дивидентът в акции на CBSH са точни — без маркер
            if ev:
                found[t] = {**ev[0], "text": warning_text(ev[0])}
        for g in cards_groups:
            for c in g or []:
                if isinstance(c, dict) and c.get("ticker") in found:
                    c["corp_action"] = dict(found[c["ticker"]])
        diag["flagged"] = [{"ticker": t, "date": e["date"], "ratio": e["ratio"]} for t, e in sorted(found.items())]
    except Exception as e:
        diag.update(ok=False, error=f"{type(e).__name__}: {e}")
        print(f"[corp_actions] проверката за корпоративни действия пропусната: {diag['error']}")
    return diag


# ══════════════════════════════════════════════════════════════════════════
# 13.10.2026 (решение на Венци): ИЗКЛЮЧВАНЕ вместо маркер. Тикър със събитие с НЕЦЯЛ коефициент (отделяне / сплит с оценъчен коефициент от Yahoo) не е карта, сигнал или запис в модул,
# чийто прозорец назад обхваща датата — докато прозорецът се изчисти. Повод: CTVA в GLB на 13.10 ("пробив над историческия връх" +4.6% над линия $12.71 = юнското затваряне ~$85 ÷ 6.665;
# грешката на коефициента е по-голяма от "пробива"). Прозорците (config): скрийнър — CORP_ACTION_SCREENER_SESSIONS (52 седмици, RS 12 месеца, pivot); QM — CORP_ACTION_QM_SESSIONS
# (6-месечният ръст); GLB и книгата "GLB по Уиш" — месецът на линията е ПРЕДИ събитието. Цели сплитове — без промяна. Изключените излизат като ред под секцията (brief["corp_excluded"]).
# Graceful: провал на тегленето → нищо не се изключва, LAST_DIAG ok=False (банер в data_warnings — липсата на изключване тогава не значи "няма събитие").
# ══════════════════════════════════════════════════════════════════════════
LAST_DIAG: dict = {"ok": True, "checked": 0, "excluded": [], "error": None}
_SERIES: dict = {}                                   # тикър → {"dates", "ratios", "close"} — едно теглене на тикър за run-а


def reset() -> None:
    """Нов run: празен кеш и диагностика."""
    _SERIES.clear()
    LAST_DIAG.clear()
    LAST_DIAG.update(ok=True, checked=0, excluded=[], error=None)


def fetch_actions(tickers: list[str], period: str | None = None, start: dt.date | None = None) -> dict[str, dict]:
    """
    {тикър: {"dates": [...], "ratios": [...], "close": pd.Series, "from": "YYYY-MM-DD" | None}} от ЕДНА партида yf.download(…, actions=True). Провал → вдига (exclude го хваща).
    start (19.10.2026, Н4) — от тази дата вместо периода; "from" казва откъде е изтеглено (кешът на run-а тегли наново, ако модул иска по-стара дата).
    """
    if yf is None:
        raise RuntimeError("yfinance не е наличен")
    tickers = list(tickers)
    span = {"start": start.isoformat()} if start else {"period": period or config.CORP_ACTION_FETCH_PERIOD}
    data = yf.download(tickers, **span, progress=False, auto_adjust=False, actions=True, group_by="ticker", threads=True)
    if data is None or len(data) == 0:
        raise ValueError("празен резултат")
    multi = hasattr(data.columns, "levels") and getattr(data.columns, "nlevels", 1) > 1
    out = {}
    for t in tickers:
        try:
            f = data[t] if multi else data
            sp = f["Stock Splits"].dropna()
            sp = sp[sp != 0]
            out[t] = {"dates": [x.date().isoformat() for x in sp.index], "ratios": [float(v) for v in sp.to_numpy()], "close": f["Close"].dropna(),
                      "from": start.isoformat() if start else None}
        except Exception:
            continue
    return out


def fetch_start(rows: list[dict], module: str, day: dt.date) -> dt.date:
    """
    19.10.2026 (трети преглед, Н4): откъде да се теглят събитията — по-старото от (днес − CORP_ACTION_FETCH_PERIOD) и първия ден на месеца на най-старата линия (GLB / "GLB по Уиш":
    прозорецът е "събитие след месеца на линията", а линията може да е години назад). Реално: PR в GLB на 25.08–01.09.2026 с линия от 09.2018 (5 г. назад стигаха до 08.2021 —
    събитие от 10.2018 до 08.2021 не се виждаше); TMO с линия 12.2021 щеше да излезе от прозореца около 20.12.2026.
    """
    m = re.fullmatch(r"(\d+)(y|mo|d)", str(config.CORP_ACTION_FETCH_PERIOD).strip())
    n, unit = (int(m.group(1)), m.group(2)) if m else (5, "y")
    base = (dt.date(day.year - n, day.month, min(day.day, 28)) if unit == "y" else day - dt.timedelta(days=n * 31 if unit == "mo" else n))
    if module not in ("glb", "glb_wish"):
        return base
    months = []
    for r in rows or []:
        mm = re.fullmatch(r"(\d{4})-(\d{2})", str((r or {}).get("prior_high_month") or "")[:7]) if isinstance(r, dict) else None
        if mm:
            months.append(dt.date(int(mm.group(1)), int(mm.group(2)), 1))
    return min([base] + months)


def _covered(ticker: str, start: dt.date) -> bool:
    """Кешът на run-а стига ли до `start`. Без "from" (подменено теглене в тестовете, по-стар формат) — да."""
    s = _SERIES.get(ticker)
    if not s:
        return False
    f = s.get("from")
    return f is None or f <= start.isoformat()


def _takes_start(fn) -> bool:
    try:
        return "start" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _sessions_after(day: dt.date, n: int) -> dt.date:
    """Датата, на която се навършват n NYSE сесии след `day` (без самия ден) — краят на прозореца."""
    d, k = day, 0
    while k < n:
        d += dt.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in config.NYSE_HOLIDAYS:
            k += 1
    return d


def is_exact_ratio(r: float) -> bool:
    """
    13.10.2026: точна корекция — цял коефициент (is_whole_ratio) или проста дроб p/q с q ≤ config.CORP_ACTION_EXACT_MAX_DENOM (1.5 = 3:2, 1.25 = 5:4, 0.6667 = 2:3). Отделянията
    (6.665, 1.243, 1.241, 1.327 …) не са. Чиста функция.
    """
    try:
        r = float(r)
        if not r > 0 or r == 1:
            return False
        if is_whole_ratio(r):
            return True
        for q in range(2, config.CORP_ACTION_EXACT_MAX_DENOM + 1):
            pq = round(r * q)
            if pq >= 1 and pq != q and abs(r * q - pq) <= config.CORP_ACTION_INTEGER_TOL:      # абсолютно върху числителя: 6.665 × 3 = 19.995 → не е 20/3
                return True
        return False
    except (TypeError, ValueError):
        return False


def is_material(ticker: str | None, ratio: float, date: str | None = None) -> bool:
    """
    13.10.2026: събитието е СЪЩЕСТВЕНО (изключване от модулите, ръчен преглед в книгите), ако НЕ е точна корекция и коефициентът е ≥ config.CORP_ACTION_MATERIAL_RATIO
    (1.10 ≈ отделени 9% от стойността), или е изрично отбелязано в config.CORP_ACTIONS_KNOWN ("material": True за тази дата). Под прага — само маркер.
    """
    if ticker in config.CORP_ACTION_EXACT_TICKERS or is_exact_ratio(ratio):
        return False
    k = config.CORP_ACTIONS_KNOWN.get(ticker or "") or {}
    confirmed = bool(k) and bool(date) and k.get("date") == str(date)[:10]
    if confirmed and "material" in k:
        return bool(k["material"])                                     # потвърдено в таблицата — нейната преценка
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return False
    if r < 1:
        return True                    # 13.10.2026: под 1 и не е проста дроб (HON 0.9535 — отделяне, слято с обратен сплит) → съществено по подразбиране, докато не се потвърди в таблицата
    return r >= config.CORP_ACTION_MATERIAL_RATIO


def needs_check(ticker: str | None, ratio: float, date: str | None) -> bool:
    """13.10.2026: съществено САМО по подразбирането за коефициент под 1 (не е проста дроб, няма запис за датата в CORP_ACTIONS_KNOWN) → редът казва "нужна проверка"."""
    k = config.CORP_ACTIONS_KNOWN.get(ticker or "") or {}
    try:
        return float(ratio) < 1 and not is_exact_ratio(ratio) and not (k and date and k.get("date") == str(date)[:10])
    except (TypeError, ValueError):
        return False


def is_material_between(ticker: str | None, ratio: float, start: str | None, end: str | None) -> bool:
    """Като is_material, когато датата не е известна (книгата "GLB по Уиш" вижда само общия коефициент): изричен запис "material" в CORP_ACTIONS_KNOWN с дата в (start, end] → съществено."""
    k = config.CORP_ACTIONS_KNOWN.get(ticker or "") or {}
    if k.get("material") and k.get("date") and start and end and str(start)[:10] < k["date"] <= str(end)[:10]:
        return True
    return is_material(ticker, ratio)


def window_hit(module: str, row: dict, events: list[dict]) -> dict | None:
    """Събитието (най-новото), което попада в прозореца назад на модула, или None. events — от uncertain_events (с sessions_ago)."""
    for ev in events:
        if module == "screener" and 0 <= ev["sessions_ago"] < config.CORP_ACTION_SCREENER_SESSIONS:
            return ev
        if module == "qm" and 0 <= ev["sessions_ago"] < config.CORP_ACTION_QM_SESSIONS:
            return ev
        if module in ("glb", "glb_wish"):
            month = str(row.get("prior_high_month") or "")[:7]
            if (ev["date"][:7] > month) if month else (0 <= ev["sessions_ago"] < config.CORP_ACTION_SCREENER_SESSIONS):
                return ev
    return None


def _close_before(close, day: str):
    try:
        c = close[close.index.tz_localize(None) < pd.Timestamp(day)] if getattr(close.index, "tz", None) is not None else close[close.index < pd.Timestamp(day)]
        return float(c.iloc[-1]) if len(c) else None
    except Exception:
        return None


def _last_close(close):
    try:
        idx = close.index.tz_localize(None) if getattr(close.index, "tz", None) is not None else close.index
        return float(close.iloc[-1]), pd.Timestamp(idx[-1]).date()
    except Exception:
        return None, None


def exclusion_text(ticker: str, ev: dict, module: str) -> str:
    """Редът под секцията. Известно отделяне (config.CORP_ACTIONS_KNOWN) — с новата компания и сбора; иначе — общо описание. Цената преди = затварянето преди датата × коефициента на Yahoo."""
    d = dt.date.fromisoformat(ev["date"])
    known = config.CORP_ACTIONS_KNOWN.get(ticker) or {}
    if known.get("date") and known["date"] != ev["date"]:
        known = {}
    if known.get("new_name"):
        what = f"{known.get('kind', 'отделяне')} на {known['new_name']}" + (f" ({known['ratio_text']})" if known.get("ratio_text") else "") + f" на {d:%d.%m}"
    elif needs_check(ticker, ev["ratio"], ev["date"]):
        what = (f"корпоративно действие на {d:%d.%m} (коефициент {ev['ratio']:g} — под 1 и не е проста дроб: вероятно отделяне, слято с обратен сплит) — "
                f"нужна проверка, докато не бъде потвърдено в CORP_ACTIONS_KNOWN")
    else:
        what = f"корпоративно действие на {d:%d.%m} (нецял коефициент {ev['ratio']:g} — отделяне или сплит с нецял коефициент)"
    parts = [f"{ticker} — изключена: {what}", f"историята преди датата е оценка на Yahoo (коефициент {ev['ratio']:g})"]
    s = _SERIES.get(ticker) or {}
    pre = _close_before(s.get("close"), ev["date"]) if s.get("close") is not None else None
    if known.get("new_ticker") and pre:
        now, when = _last_close(s["close"])
        new = (_SERIES.get(known["new_ticker"]) or {}).get("close")
        new_now, new_when = _last_close(new) if new is not None else (None, None)
        if now and new_now and when == new_when:
            total = now + known.get("new_per_share", 1.0) * new_now
            pre_raw = pre * ev["ratio"]
            parts.append(f"{ticker} + {known['new_ticker']} = ${total:.2f} към {when:%d.%m} спрямо ${pre_raw:.2f} преди ({(total / pre_raw - 1) * 100:+.1f}%)")
    if module == "screener":
        parts.append(f"извън скрийнъра до {_sessions_after(d, config.CORP_ACTION_SCREENER_SESSIONS):%d.%m.%Y} ({config.CORP_ACTION_SCREENER_SESSIONS} сесии — 52 седмици, RS, pivot)")
    elif module == "qm":
        parts.append(f"извън скенера до {_sessions_after(d, config.CORP_ACTION_QM_SESSIONS):%d.%m.%Y} ({config.CORP_ACTION_QM_SESSIONS} сесии — ръстът за 6 месеца)")
    else:
        parts.append(f"връща се, когато линията е от месец след {d:%m.%Y}")
    return "; ".join(parts)


def exclude(rows: list[dict], module: str, today, fetch=None) -> tuple[list[dict], list[dict]]:
    """
    (останали, изключени) за редовете на един модул ("screener" | "qm" | "glb" | "glb_wish"). Тегли (веднъж за run-а) колоната "Stock Splits" и Close за тикърите + новите компании от
    config.CORP_ACTIONS_KNOWN. Изключеният ред е {ticker, module, date, ratio, text}. Не вдига: провал → нищо не се изключва, LAST_DIAG ok=False.
    """
    day = today if isinstance(today, dt.date) else dt.date.fromisoformat(str(today)[:10])
    rows = list(rows or [])
    tickers = sorted({r.get("ticker") for r in rows if isinstance(r, dict) and r.get("ticker")})
    if not tickers:
        return rows, []
    try:
        start = fetch_start(rows, module, day)                                  # 19.10.2026 (Н4): GLB — от месеца на най-старата линия, ако е преди 5-те години
        need = [t for t in tickers if not _covered(t, start)]
        need += [k["new_ticker"] for t, k in config.CORP_ACTIONS_KNOWN.items() if t in tickers and k.get("new_ticker") and not _covered(k["new_ticker"], start)]
        if need:
            fn = fetch or fetch_actions
            _SERIES.update(fn(sorted(set(need)), start=start) if _takes_start(fn) else fn(sorted(set(need))))
            LAST_DIAG["fetch_from"] = min(filter(None, [LAST_DIAG.get("fetch_from"), start.isoformat()]))
        LAST_DIAG["checked"] = LAST_DIAG.get("checked", 0) + len(tickers)
        kept, out = [], []
        for r in rows:
            s = _SERIES.get(r.get("ticker")) if isinstance(r, dict) else None
            evs = [] if not s else [e for e in uncertain_events(s["dates"], s["ratios"], day, sessions=10 ** 6)
                                    if is_material(r.get("ticker"), e["ratio"], e["date"])]        # 13.10: под прага 1.10 — само маркер (annotate), картата остава
            ev = window_hit(module, r, evs) if evs else None
            if ev:
                out.append({"ticker": r["ticker"], "module": module, "date": ev["date"], "ratio": ev["ratio"], "text": exclusion_text(r["ticker"], ev, module)})
            else:
                kept.append(r)
        LAST_DIAG.setdefault("excluded", []).extend(out)
        for e in out:
            print(f"[corp_actions] {e['module']}: {e['text']}")
        return kept, out
    except Exception as e:
        LAST_DIAG.update(ok=False, error=f"{type(e).__name__}: {e}")
        print(f"[corp_actions] изключването за '{module}' пропуснато: {LAST_DIAG['error']}")
        return rows, []
