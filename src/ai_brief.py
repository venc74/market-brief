"""
AI синтез чрез Claude API.
Два извиквания на ден:
  1. Макро бриф + секторна верижна логика (Слой 1 → Слой 2 наратив)
  2. Per-ticker карти: "защо сега", катализатори, рискове,
     Action/Watchlist класификация — batch в едно извикване, JSON изход.

Английски за тикъри и данни, български за обясненията (Секция 6.1).
"""
from __future__ import annotations
import json
import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

API_URL = "https://api.anthropic.com/v1/messages"


def _call_claude(system: str, user: str, max_tokens: int = 4000) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY липсва")
    r = requests.post(API_URL, headers={
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, json={
        "model": config.CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }, timeout=180)
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"]
                   if b.get("type") == "text")


def _parse_json(text: str):
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    return json.loads(clean.strip())


SYSTEM_MACRO = """Ти си макро аналитик, който пише за опитен суинг търговец \
(8+ години, познава Weinstein, CANSLIM, GMMA, RS Line, GLB). Системата е \
оперативна, не образователна — без дефиниции на базови понятия, без hedging \
фрази. Пишеш на български, тикерите и техническите термини остават на английски. \
Връщаш САМО валиден JSON, без markdown огради, без преамбюл."""


def macro_and_sector_brief(macro: dict, rotation: list[dict],
                           thermometer: dict) -> dict:
    """
    Връща:
    {
      "macro_brief": "4-6 изречения какво се случи и какво значи",
      "sector_logic": [
        {"sector": ..., "etf": ..., "chain": "конкретната верижна логика",
         "horizon_weeks": "2-6"}
      ],
      "regime_comment": "1-2 изречения коментар към режима"
    }
    """
    user = f"""Днешни данни:

ТЕРМОМЕТЪР: {json.dumps(thermometer, ensure_ascii=False, default=str)}

МАКРО (FRED + пазарни сигнали): {json.dumps(macro, ensure_ascii=False, default=str)[:6000]}

СЕКТОРНА РОТАЦИЯ (RS vs SPY): {json.dumps(rotation, ensure_ascii=False)}

Задачи:
1. "macro_brief": 4-6 изречения — какво се случи в света и какво означава за \
днешната сесия. Конкретика, не общи приказки.
2. "sector_logic": за топ 3-5 сектора с положителна динамика — пълната верижна \
логика (макро събитие → механизъм → сектор), както изисква спекът: документирай \
веригата, не само заключението. Поле "chain" за всяка.
3. "regime_comment": защо режимът {thermometer.get('regime')} е правилен днес.

Връщай само JSON с ключове: macro_brief, sector_logic (списък от обекти със \
sector, etf, chain, horizon_weeks), regime_comment."""
    return _parse_json(_call_claude(SYSTEM_MACRO, user))


SYSTEM_TICKERS = """Ти си портфолио стратег за суинг търговия. Потребителят е \
опитен (Weinstein Stage Analysis, CANSLIM, O'Neil bases, RS Line). Пишеш на \
български, тикери и термини на английски. Бъди директен — ако setup-ът е слаб, \
кажи го. Връщаш САМО валиден JSON."""


def ticker_narratives(candidates: list[dict], sector_logic: list[dict],
                      regime: str) -> list[dict]:
    """
    За всеки кандидат Claude връща:
    why_now (верижна логика макро→сектор→акция), business_bg (2-3 изречения),
    catalysts (4-8 седмици), risks, earnings_call (преди/след/не сега),
    classification (Action/Watchlist) + watchlist_trigger ако е Watchlist.
    """
    slim = []
    for c in candidates:
        slim.append({k: c.get(k) for k in (
            "ticker", "company", "sector", "industry", "business_summary",
            "price", "pivot", "pct_from_pivot", "base_type", "base_depth_pct",
            "rs_status", "volume_ratio", "breakout_volume",
            "eps_growth_yoy", "revenue_growth_yoy", "roe", "pe", "forward_pe",
            "inst_ownership_pct", "analyst_target")})
        slim[-1]["earnings"] = c.get("earnings")
        slim[-1]["short"] = c.get("short_view", {}).get("interpretation")
        slim[-1]["options"] = {k: c.get("options", {}).get(k)
                               for k in ("iv", "iv_rank", "strategy")}

    user = f"""Пазарен режим: {regime}
Активна секторна логика: {json.dumps(sector_logic, ensure_ascii=False)}

КАНДИДАТИ: {json.dumps(slim, ensure_ascii=False, default=str)}

За ВСЕКИ кандидат върни обект:
- "ticker"
- "why_now": конкретната верига макро → сектор → тази акция. Ако няма реална \
макро връзка, кажи че setup-ът е чисто технически.
- "business_bg": какво прави компанията, 2-3 изречения на български.
- "catalysts": списък от 2-4 катализатора в следващите 4-8 седмици.
- "risks": списък от 2-4 конкретни риска — какво обръща trade-а.
- "earnings_call": "преди earnings" / "след earnings" / "не сега" + защо (1 изр.).
- "classification": "Action" или "Watchlist". Watchlist ако: в earnings blackout, \
без обем при пробив и още под pivot, RS слабее, или секторът противоречи на режима.
- "watchlist_trigger": ако Watchlist — какво точно трябва да се случи (цена/обем/дата).

Правила: максимум {config.MAX_ACTION_TICKERS} Action общо — избери най-силните. \
Максимум {config.MAX_PER_SECTOR} Action от един сектор. Earnings в рамките на 5 \
работни дни = автоматично Watchlist (или Action с изрично предупреждение само при \
изключителен setup, поле "warning").

Връщай само JSON: {{"tickers": [...]}}"""
    out = _parse_json(_call_claude(SYSTEM_TICKERS, user, max_tokens=8000))
    return out.get("tickers", [])


def merge_narratives(candidates: list[dict], narratives: list[dict]) -> list[dict]:
    by_ticker = {n["ticker"]: n for n in narratives}
    for c in candidates:
        c["ai"] = by_ticker.get(c["ticker"], {})
        # Твърдите правила бият AI преценката (Секция 8):
        if c.get("earnings", {}).get("in_blackout") and not c["ai"].get("warning"):
            c["ai"]["classification"] = "Watchlist"
            c["ai"].setdefault("watchlist_trigger",
                               f"След earnings на {c['earnings'].get('next_earnings')}")
    return candidates
