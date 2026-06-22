"""
Пазарен термометър (Секция 4).
Шест индикатора + обща препоръка Offensive / Defensive / Cash.
Всеки индикатор връща {value, status, label} където status ∈ green/yellow/red.
"""
from __future__ import annotations
import io
import os
from functools import lru_cache
import requests
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


def spy_trend() -> dict:
    hist = yf.Ticker("SPY").history(period="1y")
    close = hist["Close"]
    price = float(close.iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])
    above50, above200 = price > ma50, price > ma200
    status = "green" if (above50 and above200) else ("yellow" if above200 else "red")
    return {
        "name": "SPY тренд", "value": round(price, 2),
        "ma50": round(ma50, 2), "ma200": round(ma200, 2),
        "above_50dma": above50, "above_200dma": above200, "status": status,
        "label": f"SPY {price:.0f} | {'над' if above50 else 'под'} 50DMA, "
                 f"{'над' if above200 else 'под'} 200DMA",
    }


def vix_level() -> dict:
    hist = yf.Ticker("^VIX").history(period="10d")
    vix = float(hist["Close"].iloc[-1])
    wk = float(hist["Close"].iloc[0])
    if vix < config.VIX_RISK_ON:
        status = "green"
    elif vix < config.VIX_RISK_OFF:
        status = "yellow"
    else:
        status = "red"
    return {
        "name": "VIX", "value": round(vix, 2), "chg_5d": round(vix - wk, 2),
        "status": status,
        "label": f"VIX {vix:.1f} ({'risk-on' if status == 'green' else 'risk-off' if status == 'red' else 'неутрално'})",
    }


# ── NAAIM източници (приоритет: Nasdaq Data Link [API key] → naaim.org scrape) ──
# naaim.org CSV (USE_Data_since_Inception.csv) е премахнат — върна 404 (файлът е
# изтрит/преместен). Останаха два източника: оторизиран Nasdaq endpoint и scrape.
NAAIM_NASDAQ_URL = "https://data.nasdaq.com/api/v3/datasets/NAAIM/NAAIM.json"
NAAIM_PAGE_URL = "https://naaim.org/programs/naaim-exposure-index/"
_NAAIM_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _parse_date_safe(s: str):
    """Връща (sort_key, оригинален_низ). sort_key=ISO низ ако се разпознае, иначе None."""
    s = (s or "").strip()
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d.%m.%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d"), s
        except ValueError:
            continue
    return None, s


def _naaim_from_nasdaq() -> list[dict]:
    """
    Primary: Nasdaq Data Link (Quandl) — изисква API ключ (anonymous достъп е спрян,
    връща 403). Ключът идва от env var NASDAQ_API_KEY и се подава като query параметър.
    Ако ключът липсва → чист skip (връщаме [] без да правим заявка), за да паднем
    тихо към следващия източник, вместо да генерираме 403 грешка.
    Структура: dataset.column_names + dataset.data (newest-first по подразбиране).
    Нормализираме до хронологичен ascending списък [{date, value}].
    """
    api_key = os.getenv("NASDAQ_API_KEY")
    if not api_key:
        print("[thermo] NAAIM: NASDAQ_API_KEY липсва — пропускам Nasdaq source")
        return []
    r = requests.get(NAAIM_NASDAQ_URL, timeout=20, headers=_NAAIM_HEADERS,
                     params={"api_key": api_key})
    r.raise_for_status()
    ds = r.json().get("dataset", {})
    cols = [str(c).lower() for c in ds.get("column_names", [])]
    data = ds.get("data", [])
    # колоната със средната експозиция: търсим "mean"/"average"/"naaim", иначе index 1
    val_idx = next((i for i, c in enumerate(cols)
                    if any(k in c for k in ("mean", "average", "naaim number"))), 1)
    pts = []
    for row in data:
        if not row or len(row) <= val_idx:
            continue
        try:
            val = float(row[val_idx])
        except (TypeError, ValueError):
            continue
        sort_key, raw = _parse_date_safe(str(row[0]))
        pts.append({"date": sort_key or raw, "value": round(val, 1), "_k": sort_key or raw})
    pts.sort(key=lambda p: p["_k"])  # ISO дати → безопасно ascending
    for p in pts:
        p.pop("_k", None)
    return pts


def _looks_like_date(s) -> bool:
    """Бърза проверка дали низ прилича на дата (за JSON евристиката)."""
    if not isinstance(s, str):
        return False
    return _parse_date_safe(s)[0] is not None


def _points_from_json_obj(obj, out: list[dict]) -> None:
    """
    Рекурсивно обхожда произволна JSON структура и събира двойки (дата, число)
    които приличат на времева серия. Покрива честите chart формати:
      • [{"date": "...", "value": N}, ...]  (Chart.js / WP плъгини)
      • [{"x": "...", "y": N}, ...]         (Highcharts/plotly)
      • [["YYYY-MM-DD", N], ...]            (двойки)
    Стойностите се ограничават до [-250, 250] (NAAIM е приблизително [-200, 200]).
    """
    if isinstance(obj, dict):
        # dict с дата-подобен ключ + числова стойност
        date_val = next((obj[k] for k in ("date", "Date", "x", "t", "time", "label")
                         if k in obj and _looks_like_date(obj.get(k))), None)
        if date_val is not None:
            num = next((obj[k] for k in ("value", "y", "mean", "naaim", "close", "v")
                        if isinstance(obj.get(k), (int, float))), None)
            if num is not None and -250 <= num <= 250:
                _, raw = _parse_date_safe(date_val)
                out.append({"date": raw, "value": round(float(num), 1),
                            "_k": _parse_date_safe(date_val)[0]})
        for v in obj.values():
            _points_from_json_obj(v, out)
    elif isinstance(obj, list):
        # двойка [date, number]
        if (len(obj) == 2 and _looks_like_date(obj[0])
                and isinstance(obj[1], (int, float)) and -250 <= obj[1] <= 250):
            _, raw = _parse_date_safe(obj[0])
            out.append({"date": raw, "value": round(float(obj[1]), 1),
                        "_k": _parse_date_safe(obj[0])[0]})
        for v in obj:
            _points_from_json_obj(v, out)


def _naaim_from_scrape() -> list[dict]:
    """
    Fallback: scrape на programs страницата. Първо опитва HTML таблици; ако страницата
    е JS-rendered SPA (без таблици / почти празно body), търси вграден JSON в
    <script type="application/json"> (и подобни inline script блокове) като
    алтернативен начин за извличане. Best-effort, подреждаме ascending по дата.
    """
    from bs4 import BeautifulSoup
    r = requests.get(NAAIM_PAGE_URL, timeout=20, headers=_NAAIM_HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # — опит 1: класически HTML таблици —
    pts = []
    tables = soup.find_all("table")
    for table in tables:
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            sort_key, raw = _parse_date_safe(cells[0])
            if sort_key is None:
                continue  # първата клетка не е дата → пропускаме заглавни редове
            for c in cells[1:]:
                try:
                    val = float(c.replace("%", "").replace(",", "").strip())
                except ValueError:
                    continue
                if -250 <= val <= 250:  # NAAIM е приблизително в [-200, +200]
                    pts.append({"date": raw, "value": round(val, 1), "_k": sort_key})
                    break

    # — опит 2: SPA / JS-rendered страница → вграден JSON —
    # Признаци за SPA: няма таблици с данни ИЛИ много малко видим текст спрямо script.
    if not pts:
        import json as _json
        scripts = soup.find_all("script")
        body_text = soup.get_text(" ", strip=True)
        is_spa = (not tables) or (len(body_text) < 600 and len(scripts) > 3)
        if is_spa or scripts:
            for sc in scripts:
                stype = (sc.get("type") or "").lower()
                blob = sc.string or sc.get_text() or ""
                blob = blob.strip()
                if not blob:
                    continue
                # приоритет на декларираните JSON блокове, но опитваме и inline скриптове
                candidates = []
                if "json" in stype:
                    candidates.append(blob)
                else:
                    # извличаме първия балансиран {…} или […] от inline script
                    for opener, closer in (("[", "]"), ("{", "}")):
                        i, j = blob.find(opener), blob.rfind(closer)
                        if 0 <= i < j:
                            candidates.append(blob[i:j + 1])
                for cand in candidates:
                    try:
                        data = _json.loads(cand)
                    except (ValueError, TypeError):
                        continue
                    _points_from_json_obj(data, pts)
                if pts:
                    break

    # дедупликация по (date, value) + сортиране ascending
    seen, uniq = set(), []
    for p in pts:
        key = (p["date"], p["value"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    uniq.sort(key=lambda p: p.get("_k") or p["date"])
    for p in uniq:
        p.pop("_k", None)
    return uniq


@lru_cache(maxsize=1)
def _naaim_series() -> tuple:
    """
    Връща хронологичен ascending кортеж точки от първия успял източник.
    Кешира се за процеса (lru_cache) → exposure + history теглят мрежата веднъж.
    При пълен провал на трите → празен кортеж (→ graceful hide нагоре по веригата).
    Връща tuple (immutable), за да е hashable/безопасен за кеширане; консумерите
    го третират като последователност (slice/индексиране работят непроменено).
    """
    for name, fn in (("nasdaq", _naaim_from_nasdaq),
                     ("naaim.org scrape", _naaim_from_scrape)):
        try:
            pts = fn()
            if pts:
                return tuple(pts)
            print(f"[thermo] NAAIM source '{name}' върна 0 точки — пробвам следващия")
        except Exception as e:
            print(f"[thermo] NAAIM source '{name}' failed: {e}")
    return ()


def naaim_exposure() -> dict:
    """
    NAAIM Exposure Index — седмичен барометър на експозицията на активните мениджъри.
    <30 = дефанзивни (contrarian bullish при дъна), >90 = еуфория (предупреждение).
    Източници по приоритет: Nasdaq Data Link (API ключ) → naaim.org scrape.
    При провал и на трите картичката се скрива gracefully (hide=True), вместо
    да показва "няма данни" текст.
    """
    pts = _naaim_series()
    if not pts:
        return {"name": "NAAIM", "value": None, "status": "yellow",
                "hide": True, "label": ""}
    last = pts[-1]
    val, date = last["value"], last["date"]
    status = "yellow"
    if val > 90: status = "red"      # crowded long
    elif val < 30: status = "green"  # песимизъм = гориво
    return {"name": "NAAIM", "value": val, "as_of": date, "status": status,
            "label": f"NAAIM {val:.0f}"}


def market_put_call() -> dict:
    """
    Пазарен P/C ratio — апроксимация чрез SPY опционната верига
    (CBOE total P/C изисква платен фийд). >1.1 = страх, <0.8 = алчност.
    """
    try:
        spy = yf.Ticker("SPY")
        exp = spy.options[0]
        chain = spy.option_chain(exp)
        put_vol = int(chain.puts["volume"].fillna(0).sum())
        call_vol = int(chain.calls["volume"].fillna(0).sum())
        pc = put_vol / call_vol if call_vol else None
        if pc is None:
            raise ValueError("no volume")
        status = "green" if pc > 1.1 else ("red" if pc < 0.7 else "yellow")
        return {"name": "Put/Call (SPY)", "value": round(pc, 2), "status": status,
                "label": f"P/C {pc:.2f}"}
    except Exception as e:
        print(f"[thermo] P/C failed: {e}")
        return {"name": "Put/Call (SPY)", "value": None, "status": "yellow",
                "label": "P/C: няма данни"}


def build_thermometer(macro: dict) -> dict:
    """
    Сглобява 6-те индикатора + правилото за режим:
    - VIX > 30 → задължително Defensive (Секция 8)
    - 4+ зелени → Offensive; 2+ червени → Cash/Defensive; иначе Defensive
    """
    spread = macro.get("spread_2s10s", {})
    nl = macro.get("net_liquidity", {})

    spread_ind = {
        "name": "2Y/10Y спред",
        "value": spread.get("value"),
        "status": "red" if spread.get("status") == "inverted" else "green",
        "label": (f"{spread.get('value', '?')}% "
                  f"({'инверсия' if spread.get('status') == 'inverted' else 'нормален'}, "
                  f"{spread.get('direction', '')})"),
    }
    nl_ind = {
        "name": "Fed Net Liquidity",
        "value": nl.get("value"),
        "status": "green" if nl.get("trend") == "up" else
                  ("red" if nl.get("trend") == "down" else "yellow"),
        "label": f"${nl.get('value', '?')} млрд ({'↑' if nl.get('trend') == 'up' else '↓'})",
    }

    indicators = [spy_trend(), vix_level(), naaim_exposure(),
                  market_put_call(), spread_ind, nl_ind]

    greens = sum(1 for i in indicators if i["status"] == "green")
    reds = sum(1 for i in indicators if i["status"] == "red")
    vix_val = next((i["value"] for i in indicators if i["name"] == "VIX"), None)

    if vix_val is not None and vix_val > config.VIX_DEFENSIVE_THRESHOLD:
        regime, reason = "Defensive", f"VIX {vix_val:.0f} > 30 — автоматичен Defensive режим, sizing −50%"
    elif greens >= 4 and reds == 0:
        regime, reason = "Offensive", f"{greens}/6 индикатора зелени, нула червени"
    elif reds >= 3:
        regime, reason = "Cash", f"{reds}/6 индикатора червени — капиталът е позиция"
    elif reds >= 2:
        regime, reason = "Defensive", f"{reds} червени индикатора — намален риск"
    else:
        regime, reason = "Offensive" if greens >= 3 else "Defensive", \
                         f"{greens} зелени / {reds} червени"

    sizing_factor = config.DEFENSIVE_SIZING_FACTOR if (
        vix_val is not None and vix_val > config.VIX_DEFENSIVE_THRESHOLD) else 1.0

    return {"indicators": indicators, "regime": regime,
            "regime_reason": reason, "sizing_factor": sizing_factor}


if __name__ == "__main__":
    import json
    from macro_layer import collect_macro_layer
    print(json.dumps(build_thermometer(collect_macro_layer()),
                     indent=2, ensure_ascii=False, default=str))


# ══════════════════════════════════════════════════════════════════════════
# v2 НАДСТРОЙКА · Секция 6 — NAAIM исторически прозорец (52 седмици)
# naaim_exposure() по-горе чете само последната стойност. Тук връщаме цялата
# поредица за chart в dashboard-а, с маркери за зоните <30 (дъно) и >90 (опасно).
# Additive — съществуващите функции не са пипани.
# ══════════════════════════════════════════════════════════════════════════
def naaim_history(weeks: int | None = None) -> dict:
    """
    Връща {points: [{date, value}], low_zone: 30, high_zone: 90, current}.
    Контрарианска логика: <30 = buy zone, >90 = caution. Празно при провал.
    Ползва същия многоизточников fetcher като naaim_exposure() (Nasdaq Data Link
    → naaim.org CSV → scrape), затова e достатъчно да поправим source-а на едно място.
    """
    weeks = weeks or config.NAAIM_HISTORY_WEEKS
    out = {"points": [], "low_zone": 30, "high_zone": 90, "current": None}
    pts = _naaim_series()
    if pts:
        out["points"] = pts[-weeks:]
        out["current"] = out["points"][-1]["value"]
    return out
