"""
COT тези — частта, която държи КОДЪТ, не моделът (пакет 3, 2026-10-05). Чисти функции, без мрежа и без AI.

  • таблицата с директните тикъри по пазар (config.COT_DIRECT_TICKERS) → директната теза (т.в);
  • таблицата за знака (config.COT_MECHANISM_SIGN × config.COT_MARKET_KINDS) → ефектът печели/губи от очакваното
    движение на инструмента (т.г); моделът връща само типа на механизма, не посоката.

Не импортира ai_brief (ai_brief импортира този модул) — движението се подава като речника от ai_brief._instrument_move().
"""
from __future__ import annotations

import config

EFFECT_BG = {"gains": "печели", "loses": "губи"}


def mechanism_sign(mechanism_type: str, kind: str | None) -> int | None:
    """
    Ефектът върху компанията, когато ЦЕНАТА на инструмента расте: +1 печели, −1 губи; None ако типът няма знак за този вид
    пазар ("other", невалиден тип, или типът не важи за вида на пазара). "tracks_instrument" не е в таблицата за механизми —
    знакът му е по "side" на записа (виж entry_sign).
    """
    spec = config.COT_MECHANISM_SIGN.get(mechanism_type)
    if not spec or not kind:
        return None
    return spec["sign"].get(kind)


def effect_from_sign(sign: int, move: str) -> str:
    """sign (при цена↑) + реалното очаквано движение ("up"/"down") → "gains"/"loses"."""
    return "gains" if sign * (1 if move == "up" else -1) > 0 else "loses"


def entry_sign(entry: dict, kind: str | None) -> int | None:
    """Знакът (при цена↑) на запис от config.COT_DIRECT_TICKERS."""
    if entry.get("mechanism_type") in config.COT_DIRECT_ONLY_TYPES:
        return 1 if entry.get("side") == "long" else -1
    return mechanism_sign(entry.get("mechanism_type"), kind)


def direct_thesis(market: str, move: dict) -> dict:
    """
    Директната теза за пазара — от фиксираната таблица, без AI. Форма като на старата AI под-теза: tickers (с ефект/посока,
    изчислени от кода), reasoning (шаблон от кода), no_direct_link / empty_reason при празен запис. Тикърите още не са
    верифицирани (company = самият тикър; ai_brief._verify_thesis_tickers слага името и маха делистнатите).

    move: речникът от ai_brief._instrument_move() ("move" up/down, "move_text").
    """
    spec = config.COT_DIRECT_TICKERS.get(market)
    if spec is None:
        return {"tickers": [], "no_direct_link": True, "reasoning": "", "source": "table",
                "empty_reason": "пазарът няма запис в таблицата с директни тикъри", "outside_screener": False}
    entries = spec.get("tickers") or []
    if not entries:
        return {"tickers": [], "no_direct_link": True, "reasoning": "", "source": "table",
                "empty_reason": spec.get("empty_reason") or "няма директен тикър в таблицата", "outside_screener": False}
    kind = config.COT_MARKET_KINDS.get(market)
    tickers = []
    for e in entries:
        sign = entry_sign(e, kind)
        if sign is None:                                  # невалиден запис (тестът го хваща) — не показваме тикър без знак
            continue
        eff = effect_from_sign(sign, move["move"])
        tickers.append({"ticker": e["ticker"], "company": e["ticker"], "effect": eff,
                        "direction": "bullish" if eff == "gains" else "bearish",
                        "mechanism_type": e["mechanism_type"], "side": e["side"],
                        "partial": bool(e.get("partial")), "source": "table"})
    parts = []
    for e, t in zip([x for x in entries if entry_sign(x, kind) is not None], tickers):
        note = e.get("note") or ""
        if e.get("partial"):
            note = (note + "; " if note else "") + "частична експозиция"
        parts.append(f"{t['ticker']} {EFFECT_BG[t['effect']]}" + (f" ({note})" if note else ""))
    reasoning = (f"Фиксирана таблица с директни тикъри (не е AI). При очакваното движение — {move['move_text']}: "
                 + "; ".join(parts) + ".")
    return {"tickers": tickers, "no_direct_link": False, "reasoning": reasoning, "source": "table"}


def ticker_badges(ticker: dict, screener_tickers: set[str], open_by_ticker: dict[str, str | None]) -> list[dict]:
    """
    Значките на тикър в COT теза — слага ги КОДЪТ при показване, всеки ден (тезата се генерира сляпо):
      • SCR✓ "в скрийнъра" — тикърът е сред днешните кандидати;
      • OPEN✓ "отворена позиция" — тикърът е сред отворените Track Record позиции. При тикър с механизми (cross теза) само ако
        поне един механизъм е ПРЯК (types 7, 8, 10 и "other" никога не са пряк механизъм — виж config.COT_MECHANISM_SIGN);
        тикър без информация за механизъм (директна таблица, стар формат) се третира като пряк.
    """
    out = []
    sym = ticker.get("ticker")
    if sym in screener_tickers:
        out.append({"tag": "SCR✓", "title": "В днешния скрийнър (кандидат за Action/Watchlist) — слага се от кода."})
    mechs = ticker.get("mechanisms")
    direct = True if not mechs else any(config.COT_MECHANISM_SIGN.get(m.get("type"), {}).get("direct") for m in mechs)
    if sym in open_by_ticker and direct:
        since = open_by_ticker[sym]
        out.append({"tag": "OPEN✓", "title": "Отворена позиция" + (f" от {since}" if since else "") + " — слага се от кода."})
    return out
