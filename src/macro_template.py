"""
20.11.2026 (пакет 20.11, т. 1): макро текстът — ШАБЛОН от кода, без AI. До 20.11 разказът беше AI (3–4 изречения, с проверки за числа, причини, твърдения, посока на RS) — след
поредица грешки (19.11: „по-агресивно затягане“, „хуситски атаки … в Червено море“; 18.11: „Иранските удари … изстреляха VIX“) AI текстът излиза от брифа. Остават „Нощта“,
„Топ теми“ (дословни заглавия) и 2–3 изречения от числата: SPY / QQQ за сесията и спрямо 52-седм. връх; колко сектора нагоре / надолу и кои водят / изостават по таблицата (по сила,
RS за 4 седм.); VIX и 10-годишната доходност. Липсва число → изречението го пропуска (не измисля). Чиста функция.
"""
from __future__ import annotations


def _dm(d: str | None) -> str:
    return f"{d[8:10]}.{d[5:7]}" if d and len(d) >= 10 else ""


def _lst(xs: list[str]) -> str:
    return ", ".join(xs[:-1]) + " и " + xs[-1] if len(xs) > 1 else (xs[0] if xs else "")


def sentences(day: dict | None, board: dict | None, macro: dict | None) -> list[str]:
    """→ 2–3 изречения (или по-малко, ако числата липсват). Реално, 20.11 (към 19.11): „На 19.11 SPY −1.96%, QQQ −2.19% за сесията; SPY е 8.1% под 52-седм. връх, QQQ — 15.1%.“ …"""
    out = []
    idx = (day or {}).get("indexes") or {}
    spy, qqq = idx.get("SPY") or {}, idx.get("QQQ") or {}
    when = _dm((day or {}).get("as_of"))
    parts = [f"{n} {x['chg_1d_pct']:+.2f}%" for n, x in (("SPY", spy), ("QQQ", qqq)) if isinstance(x.get("chg_1d_pct"), (int, float))]
    if parts:
        s = (f"На {when} " if when else "") + ", ".join(parts) + " за сесията"
        hi = [f"{n} е {abs(x['from_high_pct']):.1f}% под 52-седм. връх" if x["from_high_pct"] < 0 else f"{n} е на 52-седм. връх"
              for n, x in (("SPY", spy), ("QQQ", qqq)) if isinstance(x.get("from_high_pct"), (int, float))]
        out.append(s + ("; " + ", ".join(hi) if hi else "") + ".")
    rows = [r for r in (board or {}).get("sectors") or [] if isinstance(r.get("chg_1d_pct"), (int, float))]
    if rows:
        up, down = sum(1 for r in rows if r["chg_1d_pct"] > 0), sum(1 for r in rows if r["chg_1d_pct"] < 0)
        rs = [r for r in rows if isinstance(r.get("rs_4w"), (int, float))]
        lead = [f"{r['etf']} (RS 4 седм. {r['rs_4w']:+.1f}, днес {r['chg_1d_pct']:+.1f}%)" for r in rs[:2]]
        lag = [f"{r['etf']} ({r['rs_4w']:+.1f}, днес {r['chg_1d_pct']:+.1f}%)" for r in rs[-2:][::-1]] if len(rs) > 3 else []
        s = f"Секторите: нагоре {up} от {len(rows)}, надолу {down}"
        if lead:
            s += f"; по таблицата водят {_lst(lead)}"
        if lag:
            s += f", най-слаби са {_lst(lag)}"
        out.append(s + ".")
    g = (macro or {}).get("global_signals") or {}
    vix, y10 = g.get("VIX") or {}, g.get("US10Y") or {}
    parts = []
    if isinstance(vix.get("value"), (int, float)):
        parts.append(f"VIX {vix['value']:.2f}" + (f" ({vix['chg_1d_pct']:+.1f}% за сесията)" if isinstance(vix.get("chg_1d_pct"), (int, float)) else ""))
    if isinstance(y10.get("value"), (int, float)):
        parts.append(f"10-годишната доходност {y10['value']:.2f}%" + (f" ({y10['chg_5d_bp']:+.1f} б.п. за 5 сесии)" if isinstance(y10.get("chg_5d_bp"), (int, float)) else ""))
    if parts:
        out.append(_lst(parts)[0].upper() + _lst(parts)[1:] + ".")
    return out


def macro_brief(day: dict | None, board: dict | None, macro: dict | None) -> dict:
    """{"macro_brief": текстът, "source": "code", "sentences": N} — на мястото на ai_macro (същият ключ за страницата и имейла)."""
    s = sentences(day, board, macro)
    return {"macro_brief": " ".join(s), "source": "code", "sentences": len(s)}
