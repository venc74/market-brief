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


def _build_ticker_user_prompt(slim: list[dict], sector_logic: list[dict],
                              regime: str) -> str:
    """
    Изгражда user prompt-а за един batch кандидати. Логиката е идентична на
    оригинала — само `slim` тук е подмножество (batch), не целият списък.
    Глобалните Action лимити (MAX_ACTION_TICKERS / MAX_PER_SECTOR) остават в
    prompt-а непроменени; реалното им налагане е в main.apply_hard_rules СЛЕД
    merge, така че batch-ването не нарушава глобалния cap (кодът има последната дума).
    """
    return f"""Пазарен режим: {regime}
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


def _narratives_for_batch(slim: list[dict], sector_logic: list[dict],
                          regime: str, tag: str) -> list[dict]:
    """
    Един batch → едно Claude извикване → парснат JSON. 1 retry при API/JSON грешка
    (преходни сривове). При провал и на двата опита: логва и връща [] (губим само
    тикърите от ТОЗИ batch), без да чупи останалите batch-ове или pipeline-а.
    """
    user = _build_ticker_user_prompt(slim, sector_logic, regime)
    for attempt in (1, 2):  # 1 опит + 1 retry
        try:
            out = _parse_json(_call_claude(SYSTEM_TICKERS, user,
                                           max_tokens=config.AI_BATCH_MAX_TOKENS))
            return out.get("tickers", [])
        except Exception as e:
            label = "опит" if attempt == 1 else "retry"
            print(f"[ai] ticker batch {tag} {label} неуспешен: {type(e).__name__}: {e}")
    print(f"[ai] ticker batch {tag} пропуснат след 2 опита — "
          f"губим {len(slim)} тикъра: {[c.get('ticker') for c in slim]}")
    return []


def ticker_narratives(candidates: list[dict], sector_logic: list[dict],
                      regime: str) -> list[dict]:
    """
    За всеки кандидат Claude връща:
    why_now (верижна логика макро→сектор→акция), business_bg (2-3 изречения),
    catalysts (4-8 седмици), risks, earnings_call (преди/след/не сега),
    classification (Action/Watchlist) + watchlist_trigger ако е Watchlist.

    Извикванията са на batch-ове по config.AI_BATCH_SIZE тикъра — отделно API
    извикване + отделно JSON парсване на batch, после обединяване. Така token
    budget-ът е достатъчен независимо от броя финалисти (9, 14 или 50), и един
    провален batch не сваля останалите (graceful degradation на batch ниво).
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

    if not slim:
        return []

    size = max(1, config.AI_BATCH_SIZE)
    batches = [slim[i:i + size] for i in range(0, len(slim), size)]
    n = len(batches)
    print(f"[ai] ticker_narratives: {len(slim)} финалиста → {n} batch(ове) "
          f"по ≤{size} (max_tokens={config.AI_BATCH_MAX_TOKENS}/batch)")

    merged: list[dict] = []
    for idx, batch in enumerate(batches, 1):
        merged += _narratives_for_batch(batch, sector_logic, regime, f"{idx}/{n}")
    return merged


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


# ══════════════════════════════════════════════════════════════════════════
# COT (Commitments of Traders) — Секция [нова] — Шапиро тези
# ══════════════════════════════════════════════════════════════════════════

SYSTEM_COT = """Ти си макро/позициониращ стратег, специализиран в тълкуване на \
CFTC Commitments of Traders данни по методологията на Jason Shapiro: managed \
money (спекулативни/hedge fund) позиции на екстремни percentile нива са \
contrarian сигнал — екстремно нетно дълги = потенциален bearish обрат, \
екстремно нетно къси = потенциален bullish обрат. Пишеш на български, тикери \
и технически термини на английски. Бъди директен и конкретен — не хеджирай. \
Връщаш САМО валиден JSON, без markdown огради, без преамбюл."""


def _build_cot_user_prompt(batch: list[dict], screener_universe: list[dict],
                           regime: str) -> str:
    """
    batch: подмножество от cot.get_extremes() (market, category, net_position,
    percentile, direction, as_of).
    screener_universe: слим списък {ticker, sector, industry} от ТЕКУЩИЯ
    CANSLIM скрийнър — за cross-reference, за да предпочита Claude тикъри,
    които и без друго са в системния универс, вместо произволни имена.
    """
    return f"""Пазарен режим: {regime}

CFTC ЕКСТРЕМУМИ (managed money net positioning, percentile спрямо 156-седмична \
история): {json.dumps(batch, ensure_ascii=False, default=str)}

ТЕКУЩ CANSLIM СКРИЙНЪР (за cross-reference — предпочитай тези тикъри, когато \
логически пасват; ако нищо не пасва добре, предложи друг ликвиден тикър, но \
отбележи го с "outside_screener": true): \
{json.dumps(screener_universe, ensure_ascii=False)}

За ВСЕКИ инструмент в списъка върни обект с:
- "market": точното име както е подадено
- "direct_thesis": {{
    "direction": "bullish"/"bearish" за самия инструмент или пряко свързаните \
акции (contrarian спрямо екстремума — extreme_long → bearish обрат очакван, \
extreme_short → bullish обрат очакван),
    "tickers": [1-3 обекта {{"ticker": "ADM", "company": "Archer-Daniels-Midland"}} — \
пряко изложени на инструмента; "company" е кратко, познато име, НЕ пълното \
юридическо наименование],
    "reasoning": "2-3 изречения — защо точно тези тикъри и защо сега"
  }}
- "cross_sector_thesis": {{
    "direction": "bullish"/"bearish",
    "tickers": [1-3 обекта {{"ticker": "...", "company": "..."}} — бенефициенти \
от ОБРАТНИЯ ефект — напр. ако петрол readies за спад, кои некорелирани/обратно \
изложени сектори печелят],
    "reasoning": "2-3 изречения — верижната логика инструмент → бенефициент"
  }}
- "outside_screener": true само ако нито един предложен тикър не е от подадения \
скрийнър универс

Ако екстремумът е твърде слаб/неясен за смислена теза (напр. пазар без ликвидни \
свързани акции), пропусни го от отговора — не гадай.

Връщай само JSON: {{"theses": [...]}}"""


def _cot_theses_for_batch(batch: list[dict], screener_universe: list[dict],
                          regime: str, tag: str) -> list[dict]:
    """Един batch → едно Claude извикване. 1 retry, после graceful skip на batch-а."""
    user = _build_cot_user_prompt(batch, screener_universe, regime)
    for attempt in (1, 2):
        try:
            out = _parse_json(_call_claude(SYSTEM_COT, user,
                                           max_tokens=config.COT_BATCH_MAX_TOKENS))
            return out.get("theses", [])
        except Exception as e:
            label = "опит" if attempt == 1 else "retry"
            print(f"[ai] cot batch {tag} {label} неуспешен: {type(e).__name__}: {e}")
    print(f"[ai] cot batch {tag} пропуснат след 2 опита — "
          f"губим {len(batch)} екстремума: {[e.get('market') for e in batch]}")
    return []


def cot_theses(extremes: list[dict], screener_universe: list[dict],
              regime: str) -> list[dict]:
    """
    За всеки COT екстремум (extremes от src.cot.get_extremes()) генерира
    директна + cross-sector теза. Batch-вано по config.COT_BATCH_SIZE заради
    token budget (аналогично на ticker_narratives). Мърджва резултата обратно
    в extremes по "market", запазвайки оригиналните числови полета
    (percentile, net_position, direction, history) — Claude връща само
    тезите, не пипа числата.
    """
    if not extremes:
        return []

    slim = [{"market": e["market"], "category": e["category"],
            "percentile": e["percentile"], "direction": e["direction"],
            "net_position": e["net_position"], "as_of": e["as_of"]}
           for e in extremes]

    size = max(1, config.COT_BATCH_SIZE)
    batches = [slim[i:i + size] for i in range(0, len(slim), size)]
    n = len(batches)
    print(f"[ai] cot_theses: {len(slim)} екстремума → {n} batch(ове) по ≤{size}")

    theses_by_market: dict[str, dict] = {}
    for idx, batch in enumerate(batches, 1):
        for t in _cot_theses_for_batch(batch, screener_universe, regime, f"{idx}/{n}"):
            if t.get("market"):
                theses_by_market[t["market"]] = t

    merged = []
    for e in extremes:
        t = theses_by_market.get(e["market"])
        if not t:
            continue
        merged.append({**e, "direct_thesis": t.get("direct_thesis", {}),
                       "cross_sector_thesis": t.get("cross_sector_thesis", {}),
                       "outside_screener": t.get("outside_screener", False)})
    return merged
