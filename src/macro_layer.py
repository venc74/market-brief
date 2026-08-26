"""
Слой 1: Глобален макро контекст.
Събира сурови данни от FRED, NewsAPI и yfinance. Синтезът на естествен
език се прави по-късно от ai_brief.py — този модул връща само факти.
"""
from __future__ import annotations
import datetime as dt
import requests
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def _fred_series(series_id: str, days: int = 90) -> list[tuple[str, float]]:
    """Връща (дата, стойност) наблюдения от FRED за последните N дни."""
    if not config.FRED_API_KEY:
        return []
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    try:
        r = requests.get(FRED_BASE, params={
            "series_id": series_id, "api_key": config.FRED_API_KEY,
            "file_type": "json", "observation_start": start,
        }, timeout=20)
        r.raise_for_status()
        out = []
        for obs in r.json().get("observations", []):
            if obs["value"] not in (".", ""):
                out.append((obs["date"], float(obs["value"])))
        return out
    except Exception as e:
        print(f"[macro] FRED {series_id} failed: {e}")
        return []


def fed_net_liquidity() -> dict:
    """
    Net Liquidity = Fed Balance Sheet (WALCL) − Reverse Repo (RRPONTSYD)
                    − Treasury General Account (WTREGEN). В млрд USD.

    FIX 2026-08-18: staleness guard, same принцип като _is_stale() за MOVE/
    VIX (виж move_index()/vix_term_structure() в thermometer.py) — преди
    имаше само "series напълно празна" защита (walcl/rrp/tga са []), НЕ
    "валиден, но остарял отговор" защита. WALCL/WTREGEN (Fed H.4.1, седмичен
    отчет) получават config.FED_LIQUIDITY_STALENESS_DAYS (по-дълъг праг —
    легитимен 7-дневен цикъл между публикации + buffer, виж config.py
    коментара за пълния rationale). RRPONTSYD (дневна, работни дни) ползва
    same config.STALENESS_THRESHOLD_DAYS като VIX/MOVE — same клас серия.

    value=None (заедно с hide=True) при stale данни — thermometer.py's
    nl_ind construction вече прави `if nl.get("value") is None: hide=True`,
    затова downstream кодът не се нуждае от собствена staleness логика,
    само коректно value=None тук, при източника.
    """
    walcl = _fred_series("WALCL")        # millions, weekly
    rrp = _fred_series("RRPONTSYD")      # billions, daily
    tga = _fred_series("WTREGEN")        # millions, weekly (същия H.4.1 отчет като WALCL — не billions)

    if not (walcl and rrp and tga):
        return {"value": None, "trend": "unknown", "history": [], "hide": True}

    def latest(series): return series[-1][1]
    def latest_date(series): return dt.date.fromisoformat(series[-1][0])
    def prior(series): return series[-5][1] if len(series) >= 5 else series[0][1]

    for label, series, threshold in (
        ("WALCL", walcl, config.FED_LIQUIDITY_STALENESS_DAYS),
        ("WTREGEN", tga, config.FED_LIQUIDITY_STALENESS_DAYS),
        ("RRPONTSYD", rrp, config.STALENESS_THRESHOLD_DAYS),
    ):
        d = latest_date(series)
        if _is_stale(d, threshold):
            print(f"[macro] Net Liquidity: {label} stale (последно наблюдение {d}, "
                 f"праг {threshold}д)")
            return {"value": None, "trend": "unknown", "history": [], "hide": True}

    nl_now = latest(walcl) / 1000 - latest(rrp) - latest(tga) / 1000
    nl_prev = prior(walcl) / 1000 - prior(rrp) - prior(tga) / 1000
    return {
        "value": round(nl_now, 1),
        "prev": round(nl_prev, 1),
        "trend": "up" if nl_now > nl_prev else "down",
        "components": {
            "fed_balance_bn": round(latest(walcl) / 1000, 1),
            "rrp_bn": round(latest(rrp), 1),
            "tga_bn": round(latest(tga) / 1000, 1),
        },
    }


def treasury_spread_2s10s() -> dict:
    """T10Y2Y от FRED — директно спредът в %."""
    obs = _fred_series("T10Y2Y", days=30)
    if not obs:
        return {"value": None, "status": "unknown"}
    val = obs[-1][1]
    prev = obs[-6][1] if len(obs) >= 6 else obs[0][1]
    return {
        "value": val,
        "prev_week": prev,
        "status": "inverted" if val < 0 else "normal",
        "direction": "steepening" if val > prev else "flattening",
    }


def _is_stale(last_ts, threshold_days: int | None = None) -> bool:
    """
    Огледало на thermometer._is_stale (дублирано локално, за да няма
    cross-module coupling). Пази срещу застояли Yahoo/FRED серии — виж
    коментара в thermometer.py за ^MOVE/^VIX9D/^VIX3M инцидента.

    FIX 2026-08-18: опционален threshold_days (по подразбиране config.
    STALENESS_THRESHOLD_DAYS, same поведение както преди) — fed_net_
    liquidity() подава config.FED_LIQUIDITY_STALENESS_DAYS за WALCL/WTREGEN
    (легитимно седмични серии, стандартният 3-дневен праг би ги флагвал
    като "stale" всяка нормална седмица).
    """
    last_date = last_ts.date() if hasattr(last_ts, "date") else last_ts
    threshold = threshold_days if threshold_days is not None else config.STALENESS_THRESHOLD_DAYS
    return (dt.date.today() - last_date).days > threshold


def global_market_signals() -> dict:
    """
    DXY, VIX, gold, oil, copper, 10Y yield, MOVE — снимка + 5-дневна промяна.
    FIX 2026-07-15: staleness проверка. Преди: термометърът отхвърляше
    застоял ^MOVE (hide=True), а този модул теглеше СЪЩИЯ ^MOVE без
    проверка → AI макро наративът цитираше отхвърлената стойност като
    текуща ("MOVE падна до 69.55") — двоен стандарт за същите данни.

    FIX 2026-08-26: period="10d" + iloc[0] даваше fuzzy "~5 дни" прозорец
    (calendar days, не търговски дни) — same паттърн, вече диагностициран и
    поправен в thermometer.py: vix_level() (FIX 2026-08-02), но никога не
    пренесен тук. Потвърдено на живо 2026-08-26: VIX +6.19% оттук срещу
    -2.5% в thermometer-a за СЪЩИЯ ден в СЪЩИЯ AI промпт — обратен знак, не
    просто разлика в прецизността (VIX whipsaw между двата различни anchor-а
    в рамките на прозореца). Same fix, приложен еднакво за всичките 7
    сигнала тук (не само VIX, всичките споделяха стария паттърн):
    period="1mo" + iloc[-6] — точен 5-търговски-дневен прозорец.
    """
    tickers = {
        "DXY": "DX-Y.NYB", "VIX": "^VIX", "Gold": "GC=F",
        "Oil_WTI": "CL=F", "Copper": "HG=F", "US10Y": "^TNX", "MOVE": "^MOVE",
    }
    out = {}
    for name, symbol in tickers.items():
        try:
            hist = yf.Ticker(symbol).history(period="1mo")
            if len(hist) >= 6:
                if _is_stale(hist.index[-1]):
                    print(f"[macro] {name} stale — последен ред "
                          f"{hist.index[-1].date()}, пропускам")
                    continue
                last = float(hist["Close"].iloc[-1])
                wk = float(hist["Close"].iloc[-6])
                out[name] = {
                    "value": round(last, 2),
                    "chg_5d_pct": round((last / wk - 1) * 100, 2),
                }
        except Exception as e:
            print(f"[macro] {name} failed: {e}")
    return out


def recent_headlines(max_items: int = 25) -> list[dict]:
    """
    Новини от последните 24ч в категориите от спека: монетарна политика,
    геополитика, макро данни. NewsAPI free tier — ако ключ липсва, празно.
    """
    if not config.NEWS_API_KEY:
        return []
    query = ("Federal Reserve OR FOMC OR inflation OR CPI OR tariffs OR sanctions "
             "OR OPEC OR \"interest rates\" OR geopolitics OR war")
    try:
        r = requests.get("https://newsapi.org/v2/everything", params={
            "q": query, "language": "en", "sortBy": "publishedAt",
            "from": (dt.datetime.utcnow() - dt.timedelta(hours=24)).isoformat(),
            "pageSize": max_items, "apiKey": config.NEWS_API_KEY,
        }, timeout=20)
        r.raise_for_status()
        return [{
            "title": a["title"],
            "source": a["source"]["name"],
            "published": a["publishedAt"],
            "description": (a.get("description") or "")[:300],
        } for a in r.json().get("articles", [])]
    except Exception as e:
        print(f"[macro] NewsAPI failed: {e}")
        return []


def collect_macro_layer() -> dict:
    """Пълният Слой 1 пакет — подава се на AI синтеза и термометъра."""
    return {
        "date": dt.date.today().isoformat(),
        "net_liquidity": fed_net_liquidity(),
        "spread_2s10s": treasury_spread_2s10s(),
        "global_signals": global_market_signals(),
        "headlines": recent_headlines(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(collect_macro_layer(), indent=2, ensure_ascii=False))


# ══════════════════════════════════════════════════════════════════════════
# v2 НАДСТРОЙКА · Секция 5 — Thesis Monitor
# Проверява дали текущите макро условия активират тематичните кошници от
# config.THESIS_BASKETS и обяснява верижната логика. Additive — не пипа
# съществуващите функции по-горе.
# ══════════════════════════════════════════════════════════════════════════
def _trigger_fires(trigger: str | None, macro: dict) -> tuple[bool, str]:
    """Връща (активиран ли е тригерът, кратко обяснение защо)."""
    if trigger is None:
        return False, ""
    g = macro.get("global_signals", {})
    oil = (g.get("Oil_WTI") or {}).get("chg_5d_pct")
    gold = (g.get("Gold") or {}).get("chg_5d_pct")
    vix = (g.get("VIX") or {}).get("value")
    spread = macro.get("spread_2s10s", {})

    if trigger == "oil_shock":
        if oil is not None and oil >= 5:
            return True, f"Петролът (WTI) +{oil:.1f}% за 5 дни — енергиен шок в развитие."
        return False, ""
    if trigger == "geopolitical_stress":
        if vix is not None and vix >= 25 and (gold or 0) > 0:
            return True, f"VIX {vix:.0f} + злато нагоре ({gold:+.1f}%) — бягство към сигурност."
        return False, ""
    if trigger == "curve_steepening":
        if spread.get("direction") == "steepening":
            return True, f"2s10s спредът се разкривява ({spread.get('value')}%)."
        return False, ""
    return False, ""


def thesis_monitor(macro: dict) -> list[dict]:
    """
    Връща списък активни/структурни/наблюдавани тези с обяснение на веригата.
    Подава се на секторния бриф и dashboard-а (нов раздел).
    """
    out = []
    for b in config.THESIS_BASKETS:
        status = b.get("default_status", "watch")
        fired, why = _trigger_fires(b.get("trigger"), macro)
        if fired:
            status = "active"
        out.append({
            "name": b["name"],
            "tickers": b["tickers"],
            "status": status,          # active | structural | watch
            "chain": b["chain"],
            "trigger_reason": why,
        })
    # активните най-отгоре, после структурните, после наблюдаваните
    order = {"active": 0, "structural": 1, "watch": 2}
    out.sort(key=lambda t: order.get(t["status"], 3))
    return out
