"""
AI синтез чрез Claude API.
Два извиквания на ден:
  1. Макро бриф + секторна верижна логика (Слой 1 → Слой 2 наратив)
  2. Per-ticker карти: "защо сега", катализатори, рискове,
     Action/Watchlist класификация — batch в едно извикване, JSON изход.

Английски за тикъри и данни, български за обясненията (Секция 6.1).
"""
from __future__ import annotations
import datetime as dt
import json
from functools import lru_cache
import requests
import yfinance as yf
import json_repair

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import backtest
from src import net_utils

API_URL = "https://api.anthropic.com/v1/messages"


def _call_claude(system: str, user: str, max_tokens: int = 4000,
                 extra_messages: list[dict] | None = None) -> str:
    """
    extra_messages: FIX 2026-08-17 (macro brief crash) — опционални допълнителни
    turns СЛЕД началния user съобщение (напр. [{"role": "assistant", "content":
    <malformed отговор>}, {"role": "user", "content": "поправи JSON-а"}]) — за
    Ниво 1 "smart retry", виж macro_and_sector_brief(). Празно по подразбиране,
    съществуващите извиквания с еднократно user съобщение остават непроменени.
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY липсва")
    messages = [{"role": "user", "content": user}]
    if extra_messages:
        messages += extra_messages
    r = requests.post(API_URL, headers={
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, json={
        "model": config.CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }, timeout=180)
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"]
                   if b.get("type") == "text")


def _parse_json(text: str):
    """
    Ниво 0 защита (FIX 2026-08-17 — крашнат production run: macro_and_sector_
    brief() нямаше НИКАКВА защита срещу malformed JSON от Claude, изключението
    стигна необхванато до run() и събори целия pipeline). Споделена helper за
    macro_and_sector_brief/_narratives_for_batch/_cot_theses_for_batch — един
    fix предпазва и трите извиквания, не дублиран по call site.

    json.loads() first (бърз, строг път за нормалния случай); при провал
    json_repair.loads() поправя дребни синтактични грешки (липсваща запетайка/
    кавичка, truncated при token limit) БЕЗ нова AI заявка — нулева допълнителна
    цена. Емпирично тествано на реалистични malformed случаи — възстановява
    коректен dict във всички (виж experiments discussion 2026-08-17).

    ВАЖНО: json_repair НЕ хвърля изключение при напълно неспасяем вход — връща
    '' (empty string), не None/dict (потвърдено емпирично). Затова explicit
    проверяваме isinstance+truthiness на резултата, за да различим "поправено
    успешно" от "нищо не остана за поправяне" — второто продължава да се
    третира като провал (re-raise), за да сработи Ниво 1 retry нагоре по
    веригата (за extend-натите извиквания, виж macro_and_sector_brief).
    """
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        repaired = json_repair.loads(clean)
        if isinstance(repaired, (dict, list)) and repaired:
            print(f"[ai] _parse_json: json_repair поправи malformed JSON ({e})")
            return repaired
        raise


SYSTEM_MACRO = """Ти си макро аналитик, който пише за опитен суинг търговец \
(8+ години, познава Weinstein, CANSLIM, GMMA, RS Line, GLB). Системата е \
оперативна, не образователна — без дефиниции на базови понятия, без hedging \
фрази. Пишеш на български, тикерите и техническите термини остават на английски. \
Връщаш САМО валиден JSON, без markdown огради, без преамбюл."""


def _macro_brief_fallback(thermometer: dict) -> dict:
    """
    Ниво 2 (FIX 2026-08-17) — минимален fallback, ако и Ниво 0 (json_repair),
    и Ниво 1 (smart retry) се провалят. Суровите данни (термометър режим) без
    AI наратив, explicit label в самия macro_brief текст (директно видим в
    dashboard-ната "Макро бриф" секция, без нужда от template промяна) — за
    да продължи останалата част от брифа (screening, sizing, render) напълно
    нормално, вместо целият pipeline да се събори заради един AI hiccup.
    """
    regime = thermometer.get("regime", "?")
    return {
        "macro_brief": ("⚠ AI синтез неуспешен днес — Claude върна невалиден JSON "
                        "и след автоматична поправка, и след retry. Показваме "
                        "суровите данни от термометъра/скрийнъра без AI наратив."),
        "sector_logic": [],
        "regime_comment": f"Режим: {regime} — виж пазарния термометър по-горе за пълните индикатори.",
        "ai_synthesis_failed": True,
    }


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

    FIX 2026-08-17 (production crash — json.decoder.JSONDecodeError необхванат
    чак до run(), сборил целия pipeline): 3 нива защита, в ред на разходна
    ефективност — Ниво 0 (json_repair, вътре в _parse_json(), нулева цена),
    Ниво 1 (тук долу — smart retry: подаваме malformed отговора обратно на
    Claude с explicit инструкция да го поправи, ЕДНА допълнителна AI заявка),
    Ниво 2 (_macro_brief_fallback() — суровите данни без AI наратив, graceful,
    никога не позволяваме на изключението да стигне до run()).
    """
    user = f"""Днешни данни:

ТЕРМОМЕТЪР: {json.dumps(thermometer, ensure_ascii=False, default=str)}

МАКРО (FRED + пазарни сигнали): {json.dumps(macro, ensure_ascii=False, default=str)[:6000]}

СЕКТОРНА РОТАЦИЯ (RS vs SPY): {json.dumps(rotation, ensure_ascii=False, default=str)}

ВАЖНО за числа в текста: когато цитираш конкретна стойност от данните по-горе \
(проценти, percentile, нива, delta-и) в prose текста — копирай Я ТОЧНО както е \
в JSON-а, никога не я преизчислявай или приблизителствай наум. Специфично за \
percentile полета (напр. IEI/HYG "level_percentile"/"roc_percentile") — те са \
прецизни изчислени стойности, не грубa оценка; върни числото директно от полето, \
не генерирай "правдоподобно звучащо" число от паметта си (потвърден случай \
2026-08-26: level_percentile=0.2 цитирано в текста като "20-ти percentile").

Задачи:
1. "macro_brief": 4-6 изречения — какво се случи в света и какво означава за \
днешната сесия. Конкретика, не общи приказки.
2. "sector_logic": за топ 3-5 сектора с положителна динамика — пълната верижна \
логика (макро събитие → механизъм → сектор), както изисква спекът: документирай \
веригата, не само заключението. Поле "chain" за всяка.
3. "regime_comment": провери дали режимът {thermometer.get('regime')} е оправдан \
от данните. Ако индикатори липсват, са скрити или съдържат невалидни стойности \
(null/nan), кажи го изрично и оцени как това променя увереността в режима. НЕ \
оправдавай режима на всяка цена — ако данните му противоречат, напиши го директно.

Връщай само JSON с ключове: macro_brief, sector_logic (списък от обекти със \
sector, etf, chain, horizon_weeks), regime_comment."""

    # Ниво 0 (json_repair, вътре в _parse_json) + първи опит. try/except обхваща
    # И _call_claude, И _parse_json — мрежова/API грешка тук е РАВНОСИЛНА на
    # malformed JSON за целите на graceful degradation (и двете трябва да
    # паднат към Ниво 1 retry, не да пробият необхванати до run()).
    raw = None
    error_msg = ""
    try:
        raw = _call_claude(SYSTEM_MACRO, user)
        return _parse_json(raw)
    except Exception as e:
        # ВАЖНО: Python автоматично прави `del e` на изхода от except блока
        # ("as e" гърми UnboundLocalError, ако се ползва по-долу извън него —
        # реален бъг, хванат от изолираните тестове преди push, 2026-08-17).
        # Затова съобщението се копира в отделна променлива ТУК, преди изхода.
        error_msg = f"{type(e).__name__}: {e}"
        print(f"[ai] macro brief: първи опит неуспешен ({error_msg}) "
              f"— пробвам Ниво 1 (retry с explicit поправка)")

    try:
        fix_turns = [
            {"role": "assistant", "content": raw or "(без отговор — предходната заявка се провали изцяло)"},
            {"role": "user", "content": (
                f"Предишният ти отговор имаше JSON синтактична грешка: {error_msg}. "
                f"Върни ЦЕЛИЯ отговор наново — само валиден JSON, без markdown "
                f"огради, без обяснения извън JSON структурата.")},
        ]
        raw_retry = _call_claude(SYSTEM_MACRO, user, extra_messages=fix_turns)
        return _parse_json(raw_retry)
    except Exception as e2:
        print(f"[ai] macro brief: Ниво 1 retry също неуспешен "
              f"({type(e2).__name__}: {e2}) — Ниво 2 fallback (суровите данни, без AI наратив)")
        return _macro_brief_fallback(thermometer)


SYSTEM_TICKERS = """Ти си портфолио стратег за суинг търговия. Потребителят е \
опитен (Weinstein Stage Analysis, CANSLIM, O'Neil bases, RS Line). Пишеш на \
български, тикери и термини на английски. Бъди директен — ако setup-ът е слаб, \
кажи го. Връщаш САМО валиден JSON."""


def _load_prior_watchlist_triggers(today: str | None = None) -> dict[str, str]:
    """
    FIX 2026-08-02 (точка 4 follow-up — cross-day watchlist_trigger честност):
    чете watchlist_trigger текста от НАЙ-СКОРОШНИЯ ПРЕДИШЕН data/YYYY-MM-DD.json
    snapshot и го подава като контекст на днешния AI промпт. Soft механизъм,
    mirroring prior_context в cot_theses() (виж по-долу в модула) — само cross-day
    вместо cross-batch. Потвърдено 5/5 проверени случая при прегледа на точка 4
    (2026-08-02): LLY, IRM, HWM, ROST, WWD — AI-то дава конкретен, измерим
    watchlist_trigger, после на следващия ден промотира тикъра в Action без нито
    едно от условията да е реално изпълнено, без обяснение защо (напр. LLY: trigger
    изискваше затваряне >$1249.45 + обем ≥1.3x + RS new_high; на деня на промоция
    цената беше $1216.95, обемът 0.62x, RS остана near_high — нищо от трите).

    ВАЖНО РАЗГРАНИЧЕНИЕ: този fix прави AI-то ЧЕСТНО за случая (обяснява
    противоречието, вместо мълчаливо да го подмине) — НЕ предотвратява
    преждевременен вход. Structural защита срещу лош entry timing е задача на
    бъдещ отделен Entry Timing модул (code-enforced праг, независим от AI текст,
    mirroring как in_blackout вече force-ва Watchlist класификация независимо от
    AI мнение — виж merge_narratives). Двете остават отделни, допълващи се слоеве
    на same проблем: тук подобряваме прозрачността на разказа; бъдещият модул би
    бил истинската защита срещу самия ранен вход.

    Graceful: липсващ/нечетим/липсващ предишен snapshot → празен dict, промптът
    просто няма prior-trigger секция, не чупи pipeline-а.
    """
    try:
        today = today or dt.date.today().isoformat()
        snaps = sorted(p for p in config.DATA_DIR.glob("*.json")
                       if backtest._SNAPSHOT_RE.match(p.name) and p.stem < today)
        if not snaps:
            return {}
        prior = json.loads(snaps[-1].read_text(encoding="utf-8"))
        out = {}
        for c in prior.get("watchlist", []):
            ticker = c.get("ticker")
            trigger = (c.get("ai") or {}).get("watchlist_trigger")
            if ticker and trigger and trigger != "Изчаква потвърждение.":
                out[ticker] = trigger
        return out
    except Exception as e:
        print(f"[ai] prior watchlist triggers зареждане неуспешно: {e}")
        return {}


def _build_ticker_user_prompt(slim: list[dict], sector_logic: list[dict],
                              regime: str, prior_triggers: dict[str, str] | None = None) -> str:
    """
    Изгражда user prompt-а за един batch кандидати. Логиката е идентична на
    оригинала — само `slim` тук е подмножество (batch), не целият списък.
    Глобалните Action лимити (MAX_ACTION_TICKERS / MAX_PER_SECTOR) остават в
    prompt-а непроменени; реалното им налагане е в main.apply_hard_rules СЛЕД
    merge, така че batch-ването не нарушава глобалния cap (кодът има последната дума).

    prior_triggers: FIX 2026-08-02 (виж _load_prior_watchlist_triggers) — вчерашни
    watchlist_trigger текстове, филтрирани само до тикърите в ТОЗИ batch.
    """
    batch_triggers = {c["ticker"]: prior_triggers[c["ticker"]]
                      for c in slim
                      if prior_triggers and c.get("ticker") in prior_triggers}
    trigger_block = (
        f"""

ВЧЕРАШНИ WATCHLIST TRIGGER-И ЗА ТЕЗИ ТИКЪРИ (за консистентност):
{json.dumps(batch_triggers, ensure_ascii=False, default=str)}

За тикър от списъка по-горе: провери дали вчерашният trigger (цена/обем/RS \
условие) реално се е изпълнил, преди да го класифицираш като Action. Ако го \
промотираш въпреки НЕизпълнено условие, обясни изрично в "why_now" защо \
(нов катализатор, ревизирани фундаментали, друга основателна причина) — не \
просто мълчаливо да го игнорираш."""
        if batch_triggers else ""
    )
    return f"""Пазарен режим: {regime}
Активна секторна логика: {json.dumps(sector_logic, ensure_ascii=False, default=str)}

КАНДИДАТИ: {json.dumps(slim, ensure_ascii=False, default=str)}
{trigger_block}

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
работни дни (0 ≤ days_to_earnings ≤ 7) = автоматично Watchlist (или Action с \
изрично предупреждение само при изключителен setup, поле "warning"). \
days_to_earnings=0 означава earnings Е ДНЕС — пиши го изрично така, НЕ като \
"неизвестна дата". Само ако days_to_earnings ЛИПСВА (null) или е ОТРИЦАТЕЛЕН, \
датата е неизвестна/невалидна — напиши "earnings дата неизвестна" и НЕ твърди, \
че няма blackout риск.

Връщай само JSON: {{"tickers": [...]}}"""


def _narratives_for_batch(slim: list[dict], sector_logic: list[dict],
                          regime: str, tag: str,
                          prior_triggers: dict[str, str] | None = None) -> list[dict]:
    """
    Един batch → едно Claude извикване → парснат JSON. 1 retry при API/JSON грешка
    (преходни сривове). При провал и на двата опита: логва и връща [] (губим само
    тикърите от ТОЗИ batch), без да чупи останалите batch-ове или pipeline-а.
    """
    user = _build_ticker_user_prompt(slim, sector_logic, regime, prior_triggers)
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

    # FIX 2026-08-02 (точка 4 follow-up): вчерашни watchlist_trigger текстове,
    # заредени веднъж за целия run — виж _load_prior_watchlist_triggers.
    prior_triggers = _load_prior_watchlist_triggers()

    merged: list[dict] = []
    for idx, batch in enumerate(batches, 1):
        merged += _narratives_for_batch(batch, sector_logic, regime, f"{idx}/{n}", prior_triggers)
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


@lru_cache(maxsize=256)
def _verified_company_name(ticker: str) -> dict:
    """
    FIX 2026-08-01: COT proxy тикъри получаваха различно AI-халюцинирано "company"
    име при всяко извикване — напр. "WH" ту "Wyndham Hotels", ту "World Wrestling",
    ту грешно "Westrock Coffee" (реалният WEST тикър е различен, различна компания).
    AI-то вече не се доверява за company полето — верифицираме през yfinance
    (същия shortName/longName паттърн като magic_formula.py/screener.py).

    FIX 2026-08-11: потвърдени случаи (MRO — придобита от ConocoPhillips
    22.11.2024, делистната; HBI — придобита от Gildan 01.12.2025, делистната;
    COTT-фамилията — вероятно предаденствала до PRMW, самата PRMW също се
    оказа "possibly delisted; no price data found" в реалната yfinance
    проверка) — AI-то продължава уверено да предлага такива тикъри в COT
    тезите (training данните му вероятно предхождат сделките), а старият тих
    fallback ("върни ticker символа") показваше "MRO (MRO)" в dashboard-а без
    никакъв сигнал ЗАЩО lookup-ът е паднал. Потвърдено на живо: делистнати
    тикъри системно връщат shortName=None И longName=None от yfinance
    (докато валидни тикъри — AAPL/JPM/GOOGL — винаги ги връщат коректно) —
    надежден, вече-съществуващ сигнал, нулев допълнителен network call.

    Вместо гол string, сега връща {"name": ..., "verified": bool} —
    извикващият код (_verify_thesis_tickers) премахва цели тикъри при
    verified=False, вместо само да показва грозно "TICKER (TICKER)" име.
    lru_cache пести повторни заявки за един и същ тикър в рамките на процеса.
    """
    try:
        info = net_utils.fetch_with_timeout(lambda: yf.Ticker(ticker).info) or {}
        name = info.get("shortName") or info.get("longName")
        return {"name": name or ticker, "verified": bool(name)}
    except Exception as e:
        print(f"[ai] company lookup {ticker}: {e}")
        return {"name": ticker, "verified": False}


def _verify_thesis_tickers(thesis: dict | None, screener_tickers: set[str]) -> dict | None:
    """
    Заменя AI-generated 'company' с верифицирано yfinance име за всеки тикър в тезата.

    FIX 2026-08-10: 'outside_screener' вече се изчислява ТУК от кода (сравнение
    с реалния screener_tickers set), не се доверяваме на AI self-report. Преди,
    едно top-level 'outside_screener' поле покриваше ЦЯЛАТА теза (direct_thesis
    + cross_sector_thesis заедно) — потвърдено грешно на 10.08.2026, Soybeans
    тезата: direct_thesis тикъри (ADM/BG/MOO) РЕАЛНО бяха извън скрийнъра,
    cross_sector тикъри (ABNB/ROKU) РЕАЛНО бяха в скрийнъра (потвърдено в
    watchlist-а от same ден), но AI-то върна едно 'outside_screener: true' за
    целия обект — footer бележката директно противоречеше на cross_sector
    reasoning текста, който изрично твърдеше "ABNB и ROKU са в скрийнъра".
    Сега всяка под-теза получава СВОЙ собствен, code-computed флаг.

    thesis=None (напр. когато AI-то върне празен cross_sector_thesis при липса
    на директен бенефициент) → връща None непроменено, template-ът вече прави
    {% if c.cross_sector_thesis %} truthiness проверка.

    FIX 2026-08-11: тикъри, за които _verified_company_name() върне
    verified=False (потвърдени случаи MRO/HBI — делистнати, вероятно и
    COTT/PRMW фамилията), се ПРЕМАХВАТ изцяло от финалния tickers списък —
    не просто показват с грозно "TICKER (TICKER)" име. AI-то продължава
    уверено да предлага такива тикъри от training данните си; тих fallback
    не е достатъчен за delisted компания, предложена като реален trade
    кандидат. Ако ВСИЧКИ тикъри в тезата отпаднат по тази причина, цялата
    под-теза се връща като None — reasoning текстът реферира конкретно
    премахнатите тикъри и би бил подвеждащ самичък, без нито един реален
    тикър до него (template-ът вече прави truthiness проверка, скрива блока).
    Частично отпаднали тикъри → останалите се показват нормално, плюс
    "dropped_tickers" бележка (виж dashboard.html.j2).
    """
    if not thesis:
        return thesis
    tickers = thesis.get("tickers")
    thesis = dict(thesis)
    if not tickers:
        thesis["outside_screener"] = False
        return thesis

    verified, dropped = [], []
    for t in tickers:
        if not (isinstance(t, dict) and t.get("ticker")):
            continue
        lookup = _verified_company_name(t["ticker"])
        if lookup["verified"]:
            verified.append({**t, "company": lookup["name"]})
        else:
            dropped.append(t["ticker"])

    if dropped:
        print(f"[ai] COT тикъри премахнати при верификация "
              f"(вероятно delisted/renamed): {dropped}")

    if not verified:
        return None

    thesis["tickers"] = verified
    thesis["dropped_tickers"] = dropped or None
    thesis["outside_screener"] = not any(
        t.get("ticker") in screener_tickers for t in thesis["tickers"])
    return thesis


def _build_cot_user_prompt(batch: list[dict], screener_universe: list[dict],
                           regime: str, prior_context: str = "") -> str:
    """
    batch: подмножество от cot.get_extremes() (market, category, net_position,
    percentile, direction, as_of).
    screener_universe: слим списък {ticker, sector, industry} от ТЕКУЩИЯ
    CANSLIM скрийнър — за cross-reference, за да предпочита Claude тикъри,
    които и без друго са в системния универс, вместо произволни имена.
    prior_context: FIX 2026-08-01 (soft cross-batch consistency, т.3 от прегледа
    на 15-31.07) — компактно резюме на тикъри, вече характеризирани в ПО-РАННИ
    batch-ове в СЪЩИЯ run (напр. "HWM: Copper/direct_thesis bearish — ...").
    Batch-овете са изолирани Claude извиквания (виж cot_theses) — без това AI-то
    няма видимост към собствените си по-раншни тези в същия бриф и може да даде
    противоречива характеристика на един и същ тикър (напр. "defensive" в една
    тема, "risk-on beta" в друга, същия ден) без да го отбележи. Празен низ на
    първия batch (няма все още нищо генерирано).
    """
    prior_block = (
        f"""

ВЕЧЕ ХАРАКТЕРИЗИРАНИ ТИКЪРИ ПО-РАНО В ТОЗИ БРИФ (за консистентност):
{prior_context}

Ако предложиш тикър от списъка по-горе: провери дали новата роля/характеристика \
съвпада с предишната (defensive/cyclical/hedge/core bet и т.н.). Ако тезата тук \
предполага различна роля — кажи го ИЗРИЧНО в reasoning-а (напр. "за разлика от \
ролята му в Copper тезата, тук HWM действа като hedge, не core bet"), не просто \
противоречи мълчаливо на предишната характеристика. Легитимно е тикър да има \
няколко ортогонални роли (различни причини) — проблем е само ПРЯКОТО, необяснено \
противоречие в характера на тикъра."""
        if prior_context else ""
    )
    return f"""Пазарен режим: {regime}

CFTC ЕКСТРЕМУМИ (managed money net positioning, percentile спрямо до 156-седмична \
история — "weeks_of_history" полето показва точния брой за всеки инструмент, \
виж инструкцията по-долу защо е важно): {json.dumps(batch, ensure_ascii=False, default=str)}

ТЕКУЩ CANSLIM СКРИЙНЪР (за cross-reference — предпочитай тези тикъри, когато \
логически пасват; ако нищо не пасва добре, предложи друг ликвиден тикър — дали \
е извън скрийнъра се засича автоматично от кода, не отбелязвай го сам): \
{json.dumps(screener_universe, ensure_ascii=False, default=str)}
{prior_block}

ВАЖНО за инструменти с "weeks_of_history" под {config.COT_SHORT_HISTORY_WEEKS} \
(стандартният дизайн е 156 седмици/~3г — по-млад контракт означава по-кратка \
налична история, не грешка в данните): добави explicit изречение В КРАЯ на \
всеки reasoning текст (direct_thesis И cross_sector_thesis, ако имат tickers), \
което flag-ва по-ниската статистическа увереност спрямо стандартните 156-\
седмични инструменти в тезата — напр. "История само {{N}} седмици (под \
стандартните ~156) — percentile-ът тук е по-малко статистически сигурен от \
обичайното." Не пропускай тази бележка мълчаливо — юзърът трябва да я вижда \
directamente в текста, не само да се досеща от суровите данни.

За ВСЕКИ инструмент в списъка върни обект с:
- "market": точното име както е подадено
- "direct_thesis": {{
    "direction": "bullish"/"bearish" за самия инструмент или пряко свързаните \
акции (contrarian спрямо екстремума — extreme_long → bearish обрат очакван, \
extreme_short → bullish обрат очакван),
    "tickers": [1-3 обекта {{"ticker": "ADM", "company": "Archer-Daniels-Midland"}} — \
пряко изложени на инструмента; "company" е кратко, познато име, НЕ пълното \
юридическо наименование],
    "reasoning": "2-3 изречения — защо точно тези тикъри и защо сега. Ако НЯМА \
нито един реален, ликвиден, публично търгуван тикър с истинска директна \
експозиция на инструмента (напр. основният производител не е самостоятелно \
публичен), върни ПРАЗЕН tickers списък ([]) и кажи го изрично тук — не \
насилвай слаб/индиректен избор само за да запълниш полето."
  }}
- "cross_sector_thesis": {{
    "direction": "bullish"/"bearish",
    "tickers": [1-3 обекта {{"ticker": "...", "company": "..."}} — бенефициенти \
от ОБРАТНИЯ ефект, САМО ако има ДИРЕКТНА икономическа връзка (1-2 стъпки: input \
costs, revenue exposure, конкурентна позиция спрямо самия инструмент) — НЕ \
generic макро верига от типа "цената пада → инфлацията спада → потребителите \
харчат повече → X печели донякъде" (технически вярно, но твърде разредено за \
реална теза — почти всяка discretionary акция "пасва" на почти всяка commodity \
deflation тема по този начин, което го прави безсмислено),
    "reasoning": "2-3 изречения — директната верижна логика инструмент → \
бенефициент. Ако НИКОЙ кандидат няма реална директна връзка, върни ПРАЗЕН \
tickers списък ([]) и кажи го изрично тук (напр. 'няма пряк бенефициент сред \
днешните кандидати') — не насилвай генерична връзка само за да запълниш полето."
  }}

Ако екстремумът е твърде слаб/неясен за смислена теза (напр. пазар без ликвидни \
свързани акции), пропусни го от отговора — не гадай.

Връщай само JSON: {{"theses": [...]}}"""


def _cot_theses_for_batch(batch: list[dict], screener_universe: list[dict],
                          regime: str, tag: str, prior_context: str = "") -> list[dict]:
    """Един batch → едно Claude извикване. 1 retry, после graceful skip на batch-а."""
    user = _build_cot_user_prompt(batch, screener_universe, regime, prior_context)
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


def _record_ticker_context(seen: dict[str, str], market: str, thesis_type: str,
                           thesis: dict) -> None:
    """
    FIX 2026-08-01 (т.3): записва компактно резюме на всеки тикър от тази теза в
    running `seen` речника — подава се на СЛЕДВАЩИТЕ batch-ове (виж cot_theses)
    за soft consistency check. Пази само ПОСЛЕДНАТА поява на тикъра (не пълна
    история) — целта е "не противоречи на скорошното", не пълен audit trail.

    FIX 2026-08-02: капнато на config.COT_SEEN_TICKERS_CAP записа (FIFO) — без
    това prior_context би растял неограничено на дни с много batch-ове/тикъри.
    `del` преди презапис премества тикъра в края на dict-а (Python 3.7+ пази ред
    по вмъкване) — така eviction-ът реално маха НАЙ-СТАРО ДОКОСНАТИЯ тикър, не
    просто първия въведен, ако той междувременно е бил обновен отново.
    """
    direction = thesis.get("direction", "?")
    reasoning = (thesis.get("reasoning") or "")[:120]
    for t in thesis.get("tickers") or []:
        ticker = t.get("ticker") if isinstance(t, dict) else None
        if not ticker:
            continue
        seen.pop(ticker, None)
        seen[ticker] = f'{ticker}: {market}/{thesis_type} {direction} — "{reasoning}"'
        while len(seen) > config.COT_SEEN_TICKERS_CAP:
            seen.pop(next(iter(seen)))


def cot_theses(extremes: list[dict], screener_universe: list[dict],
              regime: str) -> list[dict]:
    """
    За всеки COT екстремум (extremes от src.cot.get_extremes()) генерира
    директна + cross-sector теза. Batch-вано по config.COT_BATCH_SIZE заради
    token budget (аналогично на ticker_narratives). Мърджва резултата обратно
    в extremes по "market", запазвайки оригиналните числови полета
    (percentile, net_position, direction, history) — Claude връща само
    тезите, не пипа числата.

    FIX 2026-08-01 (т.3 от прегледа на 15-31.07): тикъри често се появяват в
    2-6+ различни тези същия ден (потвърдено емпирично — JPM до 6 пъти в 1 бриф),
    а batch-овете са изолирани Claude извиквания без взаимна видимост → противоречиви
    характеристики на един и същ тикър (напр. "defensive" в една тема, "risk-on
    beta" в друга) минаваха необяснени. Soft fix: running `seen_tickers` речник се
    строи batch по batch (sequential, вече такъв е потокът) и се подава на ВСЕКИ
    следващ batch като "вече характеризирани тикъри" контекст — AI-то е
    инструктирано да обясни изрично, ако новата роля се различава, не просто да
    противоречи мълчаливо. Не забранява легитимни multi-role тикъри.
    """
    if not extremes:
        return []

    slim = [{"market": e["market"], "category": e["category"],
            "percentile": e["percentile"], "direction": e["direction"],
            "net_position": e["net_position"], "as_of": e["as_of"],
            "weeks_of_history": e.get("weeks_of_history")}
           for e in extremes]

    size = max(1, config.COT_BATCH_SIZE)
    batches = [slim[i:i + size] for i in range(0, len(slim), size)]
    n = len(batches)
    print(f"[ai] cot_theses: {len(slim)} екстремума → {n} batch(ове) по ≤{size}")

    theses_by_market: dict[str, dict] = {}
    seen_tickers: dict[str, str] = {}
    for idx, batch in enumerate(batches, 1):
        prior_context = "\n".join(seen_tickers.values())
        for t in _cot_theses_for_batch(batch, screener_universe, regime,
                                       f"{idx}/{n}", prior_context):
            if t.get("market"):
                theses_by_market[t["market"]] = t
                _record_ticker_context(seen_tickers, t["market"], "direct_thesis",
                                       t.get("direct_thesis") or {})
                _record_ticker_context(seen_tickers, t["market"], "cross_sector_thesis",
                                       t.get("cross_sector_thesis") or {})

    screener_tickers = {c["ticker"] for c in screener_universe if c.get("ticker")}
    merged = []
    for e in extremes:
        t = theses_by_market.get(e["market"])
        if not t:
            continue
        merged.append({**e,
                       "direct_thesis": _verify_thesis_tickers(
                           t.get("direct_thesis") or {}, screener_tickers),
                       "cross_sector_thesis": _verify_thesis_tickers(
                           t.get("cross_sector_thesis") or {}, screener_tickers)})
    return merged


# ══════════════════════════════════════════════════════════════════════════
# Short/Stage 4 Screener — Аспект 2: global-vs-regional context (2026-08-2x)
# ══════════════════════════════════════════════════════════════════════════

SYSTEM_SHORT_CONTEXT = """Ти си макро анализатор, който преценява дали секторна слабост е \
глобален структурен феномен, или regional/US-специфичен проблем — за да не предложим short \
кандидат, чийто основен бизнес проблем не важи за неговия конкретен пазар (напр. US coal умира \
заради regulation, докато Индия coal расте — индийска coal компания не е валиден short на тази \
теза). Пишеш на български, тикери на английски. Връщаш САМО валиден JSON, без markdown огради."""


def short_thesis_global_context(sector_name: str, recent_news: list[dict]) -> dict:
    """
    Аспект 2 от Short/Stage 4 архитектурата (feasibility дискусия 2026-08-2x):
    AI-synthesis слой за global-vs-regional context проверка, вместо
    структурирани international данни (по-голям technical lift, отделна
    feasibility). Reuse-ва СЪЩЕСТВУВАЩИТЕ headlines (news_aggregator.py),
    без нов data source.

    Explicit honesty gate: ако headlines-ите не покриват достатъчно
    geographic context, AI-то връща "insufficient_data" вместо да гадае —
    same дух като direct_thesis "върни празно, кажи защо" instruction (COT
    секцията по-горе), и директен урок от IEI/HYG numeric fidelity инцидента
    (2026-08-26) — не позволявай правдоподобно звучащ, но неверифициран
    extrapolation да мине като сигурна преценка.

    Graceful: провал на AI извикването → "insufficient_data" fallback, не
    гърми целия short screener run.
    """
    headlines_text = "\n".join(f"- {n.get('title', '')}" for n in (recent_news or [])[:15]) \
        or "(няма скорошни headlines)"
    user = f"""Сектор с потвърдена, устойчива относителна слабост: {sector_name}

СКОРОШНИ НОВИНИ (последните ~24-48ч, може да не покриват темата изобщо):
{headlines_text}

Задача: прецени дали слабостта на "{sector_name}" е ГЛОБАЛЕН структурен феномен (важи навсякъде \
по света), или REGIONAL/US-специфичен проблем (напр. regulation, местна политика, локален \
свръхкапацитет), докато други региони показват противоположна динамика. Ако headlines-ите ПО-ГОРЕ \
не съдържат достатъчно информация за такава преценка — НЕ гадай, НЕ екстраполирай от общи \
познания за темата — върни explicit "insufficient_data" в "scope" полето.

Връщай само JSON: {{"scope": "global"/"regional"/"insufficient_data", \
"reasoning": "2-3 изречения", "confidence": "high"/"medium"/"low"}}"""

    try:
        raw = _call_claude(SYSTEM_SHORT_CONTEXT, user)
        return _parse_json(raw)
    except Exception as e:
        print(f"[ai] short global context '{sector_name}' failed: {e}")
        return {"scope": "insufficient_data",
                "reasoning": f"AI извикване неуспешно: {type(e).__name__}: {e}",
                "confidence": "low"}
