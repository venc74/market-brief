"""
Секция 3.2 — Borrow Rate в реално време от iborrowdesk.com.

iborrowdesk публикува borrow rate и short availability директно от Interactive
Brokers. Има публично JSON API: https://iborrowdesk.com/api/ticker/{SYMBOL}
(по-надеждно от HTML scrape). Връща поредица от записи с fee и available.

Интерпретация (от спека):
  • Borrow Rate > 20%  → акцията е трудна за шортиране, шортистите са под натиск.
  • Borrow Rate > 50%  → extreme squeeze territory.
  • Падащ Available при покачваща цена → шортистите се покриват.

Резултатът влиза в секцията Short Interest на всяка Action карта.

Graceful degradation (Секция 7): при недостъпен сайт връщаме {available: False}
и картата просто не показва borrow ред.
"""
from __future__ import annotations
import requests

_API = "https://iborrowdesk.com/api/ticker/{sym}"
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
       "Accept": "application/json"}


def borrow_info(sym: str) -> dict:
    """
    Връща:
      {available, fee_rate, available_shares, fee_trend, interpretation}
    available=False означава „няма данни" (системата продължава без реда).
    """
    out = {"available": False, "fee_rate": None, "available_shares": None,
           "fee_trend": None, "interpretation": None}
    try:
        r = requests.get(_API.format(sym=sym.upper()), timeout=12, headers=_UA)
        r.raise_for_status()
        data = r.json() or {}

        # API форматът: {"daily": [{"time", "fee", "available", "rebate"}...], ...}
        series = data.get("daily") or data.get("data") or []
        if not series:
            return out

        latest = series[-1]
        fee = latest.get("fee")
        avail = latest.get("available")

        # тренд на fee за последните до 5 записа
        fees = [s.get("fee") for s in series[-5:] if s.get("fee") is not None]
        trend = None
        if len(fees) >= 2:
            trend = "покачващ" if fees[-1] > fees[0] else \
                    "падащ" if fees[-1] < fees[0] else "стабилен"

        out.update({
            "available": True,
            "fee_rate": round(float(fee), 2) if fee is not None else None,
            "available_shares": int(avail) if avail not in (None, "") else None,
            "fee_trend": trend,
        })
        out["interpretation"] = _interpret(out["fee_rate"], out["available_shares"], trend)
        return out
    except Exception as e:
        print(f"[borrow_data] {sym}: {e}")
        return out


def _interpret(fee: float | None, avail: int | None, trend: str | None) -> str:
    if fee is None:
        return ""
    if fee >= 50:
        base = (f"Borrow rate {fee:.1f}% — extreme squeeze зона. Шортирането е почти "
                "невъзможно/много скъпо; всеки спусък нагоре наказва шортистите жестоко.")
    elif fee >= 20:
        base = (f"Borrow rate {fee:.1f}% — акцията е трудна за шортиране, шортистите "
                "плащат скъпо да задържат позициите.")
    else:
        base = f"Borrow rate {fee:.1f}% — нормално, евтино за шортиране, без особен натиск."

    if trend == "падащ" and avail is not None:
        base += " Падащ fee + ограничено наличие → част от шортистите се покриват."
    elif trend == "покачващ":
        base += " Покачващ fee → натискът върху шортистите расте."
    return base


if __name__ == "__main__":
    for t in ("GME", "AAPL", "BTU"):
        print(t, "→", borrow_info(t))
