"""
Пазарен термометър (Секция 4).
Шест индикатора + обща препоръка Offensive / Defensive / Cash.
Всеки индикатор връща {value, status, label} където status ∈ green/yellow/red.
"""
from __future__ import annotations
import io
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


# ── NAAIM източници (приоритет: Nasdaq Data Link → naaim.org CSV → scrape) ──
NAAIM_NASDAQ_URL = "https://data.nasdaq.com/api/v3/datasets/NAAIM/NAAIM.json"
NAAIM_CSV_URL = "https://naaim.org/wp-content/uploads/data/USE_Data_since_Inception.csv"
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
    Primary: Nasdaq Data Link (Quandl) — публичен JSON, без API ключ за базов достъп.
    Структура: dataset.column_names + dataset.data (newest-first по подразбиране).
    Нормализираме до хронологичен ascending списък [{date, value}].
    """
    r = requests.get(NAAIM_NASDAQ_URL, timeout=20, headers=_NAAIM_HEADERS)
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


def _naaim_from_csv() -> list[dict]:
    """
    Secondary: историческият CSV на naaim.org. Редовете са в хронологичен ред
    (най-старият първи), затова НЕ пресортираме — пазим оригиналната подредба.
    """
    import csv
    r = requests.get(NAAIM_CSV_URL, timeout=20, headers=_NAAIM_HEADERS)
    r.raise_for_status()
    rows = list(csv.reader(io.StringIO(r.text)))
    pts = []
    for row in rows:
        if len(row) < 2:
            continue
        # първата клетка трябва да е дата; стойността = първата числова след нея
        sort_key, raw = _parse_date_safe(row[0])
        if sort_key is None:
            continue  # заглавен/празен ред
        for c in row[1:]:
            try:
                val = float(str(c).replace("%", "").replace(",", "").strip())
            except ValueError:
                continue
            if -250 <= val <= 250:
                pts.append({"date": raw, "value": round(val, 1)})
                break
    return pts


def _naaim_from_scrape() -> list[dict]:
    """
    Tertiary fallback: директен scrape на programs страницата с BeautifulSoup.
    Best-effort — вади двойки (дата, числова стойност) от таблиците. Ако датите
    се разпознават, подреждаме ascending; иначе пазим DOM реда.
    """
    from bs4 import BeautifulSoup
    r = requests.get(NAAIM_PAGE_URL, timeout=20, headers=_NAAIM_HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    pts = []
    for table in soup.find_all("table"):
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
    pts.sort(key=lambda p: p["_k"])
    for p in pts:
        p.pop("_k", None)
    return pts


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
                     ("naaim.org CSV", _naaim_from_csv),
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
    Източници по приоритет: Nasdaq Data Link → naaim.org CSV → scrape.
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
