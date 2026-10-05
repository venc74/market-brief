"""
COT тези — частта, която държи КОДЪТ, не моделът (пакет 3, 2026-10-05). Чисти функции, без мрежа и без AI.

  • таблицата с директните тикъри по пазар (config.COT_DIRECT_TICKERS) → директната теза (т.в);
  • таблицата за знака (config.COT_MECHANISM_SIGN × config.COT_MARKET_KINDS) → ефектът печели/губи от очакваното
    движение на инструмента (т.г); моделът връща само типа на механизма, не посоката.

Не импортира ai_brief (ai_brief импортира този модул) — движението се подава като речника от ai_brief._instrument_move().
"""
from __future__ import annotations

import re

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


def ticker_badges(ticker: dict, screener_tickers: set[str], open_by_ticker: dict[str, str | None],
                  closed_by_ticker: dict[str, dict] | None = None) -> list[dict]:
    """
    Значките на тикър в COT теза — слага ги КОДЪТ при показване, всеки ден (тезата се генерира сляпо и се кешира):
      • SCR✓ "в скрийнъра" — тикърът е сред днешните кандидати;
      • OPEN✓ "отворена позиция" — тикърът е сред отворените Track Record позиции. При тикър с механизми (cross теза) само ако
        поне един механизъм е ПРЯК (types 7, 8, 10 и "other" никога не са пряк механизъм — виж config.COT_MECHANISM_SIGN);
        тикър без информация за механизъм (директна таблица) се третира като пряк;
      • CLOSED — позицията е ЗАТВОРЕНА скоро (до config.COT_CLOSED_BADGE_DAYS дни назад): казва датата и изхода и че вече не е
        отворена (случаят FITB/ONB от 17.09, описани като отворени, докато бяха стопнати). Не се слага при отворена позиция.
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
    rec = (closed_by_ticker or {}).get(sym)
    if rec and sym not in open_by_ticker and _closed_recently(rec):
        r = rec.get("realized_r")
        out.append({"tag": "CLOSED", "title": (f"Позицията е затворена на {rec.get('resolution_date')}"
                                               f"{' — ' + str(rec.get('outcome')) if rec.get('outcome') else ''}"
                                               f"{f', {r:+.1f}R' if isinstance(r, (int, float)) else ''}; не е отворена.")})
    return out


def _closed_recently(rec: dict, today=None) -> bool:
    """Затворена до config.COT_CLOSED_BADGE_DAYS дни назад (по resolution_date)."""
    import datetime as dt
    try:
        d = dt.date.fromisoformat(str(rec.get("resolution_date"))[:10])
    except ValueError:
        return False
    return 0 <= ((today or dt.date.today()) - d).days <= config.COT_CLOSED_BADGE_DAYS


# ══════════════════════════════════════════════════════════════════════════
# Cross-sector теза (пакет 3 т.г): моделът връща за всеки тикър 1–2 механизма {type, quote}; кодът изчислява ефекта
# ══════════════════════════════════════════════════════════════════════════
def valid_types(kind: str | None) -> list[str]:
    """Типовете механизъм, валидни за вида на пазара (без "other", който е допустим навсякъде)."""
    return [t for t, s in config.COT_MECHANISM_SIGN.items() if t != "other" and kind in s["sign"]]


def mechanism_label(mechanism_type: str) -> str:
    return (config.COT_MECHANISM_SIGN.get(mechanism_type) or {}).get("label", mechanism_type)


def _clean_quote(q) -> str:
    q = re.sub(r"\s+", " ", str(q or "")).strip()
    return q[:config.COT_QUOTE_MAX_CHARS].rstrip()


def parse_mechanisms(raw, kind: str | None) -> tuple[list[dict], str | None]:
    """
    (механизми, грешка). Схема: списък от {type ∈ затворения списък, quote — непразно описание}; най-много
    config.COT_MECHANISMS_PER_TICKER различни типа. Тип, който не важи за вида на пазара (напр. input_cost за облигации,
    rate_* за стока), е невалидна схема. "other" е допустим навсякъде и няма знак. Всеки механизъм получава "sign"
    (+1/−1 при цена↑, None за "other").
    """
    if not isinstance(raw, list) or not raw:
        return [], "няма механизъм"
    out, seen = [], set()
    for m in raw:
        if not isinstance(m, dict):
            return [], "невалидна схема: механизмът не е обект"
        typ = str(m.get("type") or "").strip().lower()
        quote = _clean_quote(m.get("quote"))
        if typ not in config.COT_MECHANISM_SIGN:
            return [], f"невалидна схема: типът '{typ or '?'}' не е от затворения списък"
        if not quote:
            return [], f"невалидна схема: механизмът '{typ}' е без описание (quote)"
        sign = mechanism_sign(typ, kind)
        if typ != "other" and sign is None:
            return [], f"невалидна схема: типът '{typ}' не важи за пазар от вид '{kind}'"
        if typ in seen:
            continue
        seen.add(typ)
        out.append({"type": typ, "quote": quote, "sign": sign})
    return out[:config.COT_MECHANISMS_PER_TICKER], None


# Глаголи с посока в прозата на модела (само за лог — прозата трябва да описва механизма, не посоката)
_GAIN_STEMS = re.compile(r"\b(печел|облагодетел|подобря|ползва|benefit|gain|bullish)", re.I)
_LOSS_STEMS = re.compile(r"\b(губ|страда|влошава|натиск|squeez|hurt|bearish)", re.I)


def prose_direction_conflict(quote: str, effect: str | None) -> str | None:
    """Връща намерения глагол, ако прозата казва обратното на изчисления ефект (само за лог, без действие)."""
    if effect not in ("gains", "loses"):
        return None
    m = (_LOSS_STEMS if effect == "gains" else _GAIN_STEMS).search(quote or "")
    return m.group(0) if m else None


def evaluate_cross(raw_tickers, market: str, move: dict, exclude: set[str] | frozenset = frozenset(),
                   log=None) -> dict:
    """
    Cross-sector тезата от суровия отговор на модела ([{ticker, company, mechanisms:[{type, quote}]}]) — всичко решава кодът:
      • схема (затворен списък, quote, валиден за вида на пазара) → иначе тикърът е изключен с причина;
      • два механизма с ПРОТИВОПОЛОЖЕН знак → "mixed" → изключен с причина;
      • ефект (gains/loses) = знакът по таблицата × очакваното движение; "other" без друг механизъм → без посока;
      • изречението с посоката е шаблон от кода; прозата на модела (quote) описва само механизма;
      • глагол с посока в прозата, противоречащ на ефекта → само лог (log(msg)).
    `exclude` — тикъри, които не влизат (вече са директни по таблицата). Не тегли нищо и не вика AI — чиста функция,
    пуска се и при генерирането, и всеки ден върху кешираните тези.
    Връща {"tickers": [...], "dropped_tickers": [{ticker, reason, code}] | None, "source": "model", + empty_reason при празен резултат}.
    """
    kind = config.COT_MARKET_KINDS.get(market)
    kept, dropped, seen = [], [], set()
    raw_tickers = raw_tickers if isinstance(raw_tickers, list) else []
    for item in raw_tickers:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        if ticker in exclude:
            if log:
                log(f"{ticker} вече е директен по таблицата — махнат от cross-sector")
            continue
        if len(kept) >= config.COT_CROSS_MAX_TICKERS:
            break
        mechs, err = parse_mechanisms(item.get("mechanisms"), kind)
        if err:
            dropped.append({"ticker": ticker, "reason": err, "code": "schema"})
            continue
        signs = {m["sign"] for m in mechs if m["sign"] is not None}
        if len(signs) > 1:
            plus = [mechanism_label(m["type"]) for m in mechs if m["sign"] == 1]
            minus = [mechanism_label(m["type"]) for m in mechs if m["sign"] == -1]
            dropped.append({"ticker": ticker, "code": "mixed",
                            "reason": f"mixed: противоположен ефект — {', '.join(plus)} (+) срещу {', '.join(minus)} (−)"})
            continue
        sign = next(iter(signs), None)
        effect = effect_from_sign(sign, move["move"]) if sign is not None else None
        labels = " и ".join(mechanism_label(m["type"]) for m in mechs)
        if effect:
            sentence = f"При {move['move_text']} {ticker} {EFFECT_BG[effect].upper()} (механизъм: {labels})."
        else:
            sentence = f"Механизъм: {labels} — без изчислена посока."
        for m in mechs:
            verb = prose_direction_conflict(m["quote"], effect)
            if verb and log:
                log(f"{ticker}: прозата казва '{verb}', а кодът изчислява {effect} (само лог)")
        kept.append({"ticker": ticker, "company": str(item.get("company") or ticker).strip() or ticker,
                     "effect": effect, "direction": {"gains": "bullish", "loses": "bearish"}.get(effect),
                     "mechanisms": mechs, "direct_mechanism": any(config.COT_MECHANISM_SIGN[m["type"]]["direct"] for m in mechs),
                     "sentence": sentence, "quote": " ".join(m["quote"] for m in mechs), "source": "model"})
    out = {"tickers": kept, "dropped_tickers": dropped or None, "source": "model", "no_direct_link": not kept,
           "reasoning": ""}
    if not kept:
        out["empty_reason"] = cross_empty_reason(bool(raw_tickers), dropped)
    return out


def cross_empty_reason(model_returned: bool, dropped: list[dict]) -> str:
    """Причината за празна cross теза — сглобява се от кода (не от модела)."""
    if dropped:
        return (f"всички предложени тикъри бяха изключени при проверката ({len(dropped)}): "
                + "; ".join(f"{d['ticker']} — {d['reason']}" for d in dropped))
    if model_returned:
        return "предложените тикъри бяха директни по таблицата или невалидни"
    return "моделът не предложи тикър със структурен механизъм към този инструмент"
