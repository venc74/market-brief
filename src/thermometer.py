"""
Пазарен термометър (Секция 4).
Шест индикатора + обща препоръка Offensive / Defensive / Cash.
Всеки индикатор връща {value, status, label} където status ∈ green/yellow/red.
"""
from __future__ import annotations
import io
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


def naaim_exposure() -> dict:
    """
    NAAIM Exposure Index — публикува се седмично като CSV на naaim.org.
    <30 = мениджърите са дефанзивни (contrarian bullish при дъна),
    >90 = еуфория (предупреждение).
    """
    url = "https://naaim.org/wp-content/uploads/data/USE_Data_since_Inception.csv"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        import csv
        rows = list(csv.reader(io.StringIO(r.text)))
        # последен ред с числова втора колона
        for row in reversed(rows):
            if len(row) >= 2:
                try:
                    val = float(row[1])
                    date = row[0]
                    break
                except ValueError:
                    continue
        else:
            raise ValueError("no numeric rows")
        status = "yellow"
        if val > 90: status = "red"      # crowded long
        elif val < 30: status = "green"  # песимизъм = гориво
        return {"name": "NAAIM", "value": val, "as_of": date, "status": status,
                "label": f"NAAIM {val:.0f}"}
    except Exception as e:
        print(f"[thermo] NAAIM failed: {e}")
        return {"name": "NAAIM", "value": None, "status": "yellow",
                "label": "NAAIM: няма данни"}


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
    """
    weeks = weeks or config.NAAIM_HISTORY_WEEKS
    url = "https://naaim.org/wp-content/uploads/data/USE_Data_since_Inception.csv"
    out = {"points": [], "low_zone": 30, "high_zone": 90, "current": None}
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        import csv
        rows = list(csv.reader(io.StringIO(r.text)))
        pts = []
        for row in rows:
            if len(row) >= 2:
                try:
                    val = float(row[1])
                except ValueError:
                    continue
                pts.append({"date": row[0].strip(), "value": round(val, 1)})
        pts = pts[-weeks:]
        out["points"] = pts
        if pts:
            out["current"] = pts[-1]["value"]
    except Exception as e:
        print(f"[thermo] NAAIM history failed: {e}")
    return out
