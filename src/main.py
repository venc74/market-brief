"""
Главен оркестратор. Последователност:
  Слой 1 (макро) → Термометър → Слой 2 (сектори) → Слой 3 (скрининг)
  → обогатяване → AI синтез → твърди правила → sizing → рендер → имейл.

Всеки ден записва пълния пакет в data/YYYY-MM-DD.json за исторически
tracking и бъдещ backtest модул (Секция 9).
"""
from __future__ import annotations
import datetime as dt
import json
import traceback

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

from src.macro_layer import collect_macro_layer, thesis_monitor
from src.thermometer import build_thermometer
from src.sector_layer import sector_rotation, leading_sectors, laggard_sectors
from src.screener import run_screen
from src.enrich import enrich, inject_split_catalysts
from src.sizing import position_plan
from src import ai_brief
from src import unusual_options, splits_calendar, dataroma, news_aggregator
from src import insider_buying
from src import correlation_check
from src import backtest
from src import cot
from src import entry_timing
from src import glb_screener
from src import short_screener
from src import short_tracker
from src.render import render_dashboard, render_email
from src.emailer import send_brief


def _live_positions() -> dict[str, dict]:
    """
    FIX 2026-07-15: тикър → запис за живите (open/trailing) позиции от
    backtest tracker-а. Скрийнърът нямаше представа какво вече държиш —
    на 2026-07-15 и трите ACTION тикъра (AMG, EXEL, ALL) бяха отворени
    позиции от седмици, представени като нови входове с нов риск $1000.
    """
    try:
        tracker = backtest._load_tracker()
        return {rec["ticker"]: rec for rec in tracker.values()
                if rec.get("status") in ("open", "trailing")}
    except Exception as e:
        print(f"[main] live positions check failed: {e}")
        return {}


def apply_hard_rules(candidates: list[dict], sizing_factor: float) -> tuple[list, list]:
    """
    Твърдите правила от Секция 8, наложени СЛЕД AI класификацията —
    кодът има последната дума, не моделът.
    """
    action, watchlist = [], []
    sector_count: dict[str, int] = {}
    live = _live_positions() if config.ENABLE_BACKTEST else {}

    for c in candidates:
        # FIX 2026-07-15: тикър с жива позиция НЕ получава нов Action план
        # (имплицитно удвояване на риска). Отива във Watchlist с изричен
        # OPEN✓ маркер — повторният breakout сигнал е потвърждение на
        # тезата, не нов вход.
        rec = live.get(c.get("ticker"))
        if rec:
            c.setdefault("markers", []).append({
                "tag": "OPEN✓",
                "title": (f"Отворена позиция от {rec.get('entry_date')} "
                          f"@ ${rec.get('entry_price')} — не е нов вход."),
            })
            c.setdefault("ai", {})
            c["ai"]["classification"] = "Watchlist"
            c["ai"]["watchlist_trigger"] = (
                f"Вече в портфейла от {rec.get('entry_date')} "
                f"(entry ${rec.get('entry_price')}). Повторният breakout сигнал "
                "потвърждава тезата — управлявай съществуващата позиция, не добавяй риск.")
        cls = c.get("ai", {}).get("classification", "Watchlist")
        sector = c.get("sector", "Unknown")

        if cls == "Action":
            if len(action) >= config.MAX_ACTION_TICKERS:
                cls = "Watchlist"
                c["ai"]["watchlist_trigger"] = "Лимит 5 Action тикъра — следващ по сила."
            elif sector_count.get(sector, 0) >= config.MAX_PER_SECTOR:
                cls = "Watchlist"
                c["ai"]["watchlist_trigger"] = f"Вече {config.MAX_PER_SECTOR} Action от {sector}."

        if cls == "Action":
            plan = position_plan(c, sizing_factor)
            if not plan.get("valid"):
                cls = "Watchlist"
                c["ai"]["watchlist_trigger"] = plan.get("reason", "Невалиден риск план.")
            else:
                c["plan"] = plan
                sector_count[sector] = sector_count.get(sector, 0) + 1
                action.append(c)
                continue
        c["ai"].setdefault("watchlist_trigger", "Изчаква потвърждение.")
        watchlist.append(c)

    return action, watchlist[:10]


def run() -> dict:
    today = dt.date.today().isoformat()
    print(f"═══ AI Инвестиционен Бриф · {today} ═══")

    print("[1/7] Слой 1: макро контекст…")
    macro = collect_macro_layer()

    print("[2/7] Пазарен термометър…")
    thermo = build_thermometer(macro)
    print(f"      Режим: {thermo['regime']} — {thermo['regime_reason']}")

    # v2 · Секция 5 — кои геополитически тези са активни при текущото макро
    theses = thesis_monitor(macro)

    print("[3/7] Слой 2: секторна ротация…")
    rotation = sector_rotation()
    leaders = leading_sectors(rotation)
    # Short/Stage 4 screener вход — persistence-gated (не еднодневен snapshot),
    # виж laggard_sectors() docstring-а. Реалният screening (мрежово скъп) се
    # случва по-долу, до GLB блока — тук само евтиното sector-level изчисление.
    laggards = laggard_sectors(rotation)

    print("[4/7] Слой 3: скрининг…")
    candidates = run_screen([s["sector"] for s in leaders])

    print(f"[5/7] Обогатяване на {len(candidates)} кандидата…")
    candidates = enrich(candidates)
    screener_universe = [{"ticker": c["ticker"], "sector": c.get("sector"),
                          "industry": c.get("industry")} for c in candidates]
    print("[6/7] AI синтез (Claude API)…")
    ai_macro = ai_brief.macro_and_sector_brief(macro, rotation, thermo)
    # Значими новини (RSS + nitter → Claude филтър) — преди останалия анализ
    news = news_aggregator.significant_news() if config.ENABLE_NEWS else []
    narratives = ai_brief.ticker_narratives(
        candidates, ai_macro.get("sector_logic", []), thermo["regime"])
    candidates = ai_brief.merge_narratives(candidates, narratives)
    # v2 · Секция 3.4 — споменаване на предстоящ сплит в катализаторите (след AI merge)
    candidates = inject_split_catalysts(candidates)
    print("      COT екстремуми…")
    cot_extremes = cot.get_extremes() if config.ENABLE_COT else []
    cot_with_theses = ai_brief.cot_theses(
        cot_extremes, screener_universe, thermo["regime"]) if cot_extremes else []
    action, watchlist = apply_hard_rules(candidates, thermo["sizing_factor"])
    print(f"      Action: {[a['ticker'] for a in action]}")
    print(f"      Watchlist: {[w['ticker'] for w in watchlist]}")
    # чисто информационен badge на картата — не пипа classification/plan/sizing,
    # screening и timing остават разделени, виж entry_timing.py docstring-а
    if config.ENABLE_ENTRY_TIMING:
        action = entry_timing.evaluate(action)
    # концепция 3 — пазарно-глобален сигнал, не per-ticker (виж entry_timing.py)
    distribution_days = (entry_timing.evaluate_distribution_days()
                         if config.ENABLE_ENTRY_TIMING else None)
    # чисто информационен флаг — не променя избора на Action, виж correlation_check.py
    correlation_flags = (correlation_check.fetch_correlation_flags(action)
                         if config.ENABLE_CORRELATION_CHECK else [])

    # v2 · допълнителни dashboard данни (Секции 3.3, 3.4, 6) — кеширани за деня
    unusual_today = unusual_options.fetch_unusual_options(10) if config.ENABLE_UNUSUAL_OPTIONS else []
    splits_month = splits_calendar.fetch_upcoming_splits() if config.ENABLE_SPLITS_CALENDAR else []
    superinvestor_moves = dataroma.fetch_superinvestor_buys() if config.ENABLE_DATAROMA else []
    # FIX 2026-08-17: high-conviction нови позиции (>DATAROMA_MIN_NEW_POSITION_PCT%
    # от портфейл) и major exits (>DATAROMA_MAJOR_EXIT_PCT%, explicit разделени от
    # "мениджър спрял да подава" — виж dataroma.py docstring-а) — отделни dashboard
    # сигнали от общия Moves feed.
    superinvestor_new_positions = dataroma.fetch_new_position_highlights() if config.ENABLE_DATAROMA else []
    superinvestor_exits = (dataroma.fetch_major_exits() if config.ENABLE_DATAROMA
                           else {"exits": [], "stopped_managers": []})
    insider_buys = insider_buying.fetch_insider_buying() if config.ENABLE_INSIDER_BUYING else []
    # конвергенция: тикър и в CANSLIM скрийнъра (action+watchlist), и в insider buying — виж insider_buying.py docstring
    our_tickers = {c["ticker"] for c in action} | {c["ticker"] for c in watchlist}
    for row in insider_buys:
        row["in_screener"] = row["ticker"] in our_tickers
    # (superinvestor_new_positions/superinvestor_exits конвергенцията се
    # изчислява в темплейта, "s.ticker in our_tickers" — same паттърн като
    # съществуващата superinvestor_moves секция, не precomputed поле тук)
    # GLB (Green Line Breakout) — независим механичен скрийнър, изцяло
    # извън CANSLIM/Weinstein pipeline-а (собствен universe fetch, виж
    # glb_screener.py docstring). Explicit try/except тук, въпреки че
    # screen() вече е graceful вътрешно (batch+per-ticker) — не искаме и
    # неочакван bug в нов модул да чупи целия дневен run.
    if config.ENABLE_GLB_SCREENER:
        try:
            glb_candidates = glb_screener.screen()
        except Exception as e:
            print(f"[main] GLB screener failed: {e}")
            glb_candidates = []
    else:
        glb_candidates = []
    for row in glb_candidates:
        row["in_screener"] = row["ticker"] in our_tickers

    # Short/Stage 4 screener — Модул 1, Short/Reversal тема (2026-08-2x).
    # Sector-first, изцяло независим от CANSLIM/Weinstein pipeline-а (виж
    # short_screener.py docstring за пълния feasibility/backtest trail).
    # Explicit try/except, same дух като GLB блока по-горе.
    if config.ENABLE_SHORT_SCREENER:
        try:
            short_candidates = short_screener.run_short_screen(laggards)
        except Exception as e:
            print(f"[main] Short screener failed: {e}")
            short_candidates = []
    else:
        short_candidates = []
    # Global-vs-regional context (Аспект 2) — само за capped подмножество
    # лагиращи сектори, сортирано по severity (виж MAX_LAGGARD_SECTORS_FOR_
    # AI_CONTEXT коментара в config.py — 2023-2025 daily co-occurrence тест
    # показа медиана 5, до 12 едновременно, cost/latency контрол е нужен на
    # точно тази стъпка, не на detection gate-а).
    short_sectors_seen = {c["lagging_sector"] for c in short_candidates}
    global_context = {}
    for sector in laggards[:config.MAX_LAGGARD_SECTORS_FOR_AI_CONTEXT]:
        if sector["sector"] not in short_sectors_seen:
            continue
        global_context[sector["sector"]] = ai_brief.short_thesis_global_context(
            sector["sector"], news)
    for row in short_candidates:
        row["in_screener"] = row["ticker"] in our_tickers
        row["global_context"] = global_context.get(row.get("lagging_sector"))

    # FIX 2026-07-15: самостоятелната Magic Formula топ-10 секция е премахната —
    # конвергенцията вече е MF✓ ("value confirmed") бадж на самите карти (enrich.py).
    # Track Record: ingest четe data/*.json snapshot-и от диска — днешният {today}.json
    # още не е записан на този етап (пише се по-долу). FIX 2026-08-01: предишният
    # коментар тук твърдеше, че "едно-дневното забавяне на ingest-а е безобидно" —
    # ГРЕШНО. apply_hard_rules() по-горе вика _live_positions(), който чете
    # tracker-а ПРЕДИ ingest-а — файловото четене-от-утре създаваше систематичен
    # "ден+1" прозорец, в който днешен Action тикър не се разпознаваше като жива
    # позиция утре (потвърдени случаи: FITB, JPM, HWM). Подаваме днешния action
    # списък директно, за да е налично в tracker-а от утрешния run нататък.
    if config.ENABLE_BACKTEST:
        backtest.update_backtest_tracker(action, today)
    backtest_summary = backtest.get_backtest_summary() if config.ENABLE_BACKTEST else {}

    # short_tracker.py — prospective проследяване на short кандидатите, same
    # "ден+1" fix и graceful degradation дух като backtest блока по-горе.
    # Единственият начин да измерим реален hit rate занапред (виж
    # short_screener.py docstring-а за структурния лимит на историческата
    # валидация на survival-risk критериите).
    if config.ENABLE_SHORT_SCREENER:
        short_tracker.update_short_tracker(short_candidates, today)
    short_tracker_summary = (short_tracker.get_short_tracker_summary()
                             if config.ENABLE_SHORT_SCREENER else {})

    brief = {
        "date": today,
        "macro": macro,
        "thermometer": thermo,
        "rotation": rotation,
        "ai_macro": ai_macro,
        "action": action,
        "watchlist": watchlist,
        # v2 нови блокове
        "theses": theses,
        "unusual_options": unusual_today,
        "splits": splits_month,
        "superinvestor_moves": superinvestor_moves,
        "superinvestor_new_positions": superinvestor_new_positions,
        "superinvestor_exits": superinvestor_exits,
        "insider_buying": insider_buys,
        "glb_candidates": glb_candidates,
        "news": news,
        "cot": cot_with_theses,
        "correlation_flags": correlation_flags,
        "distribution_days": distribution_days,
        "backtest": backtest_summary,
        "short_candidates": short_candidates,
        "short_tracker": short_tracker_summary,
    }

    # исторически JSON за бъдещия backtest модул
    config.DATA_DIR.mkdir(exist_ok=True)
    (config.DATA_DIR / f"{today}.json").write_text(
        json.dumps(brief, indent=1, ensure_ascii=False, default=str),
        encoding="utf-8")

    print("[7/7] Рендериране + доставка…")
    render_dashboard(brief)
    email_html = render_email(brief)
    subject = (f"[{thermo['regime']}] AI Бриф {dt.date.today().strftime('%d.%m')} · "
               f"{len(action)} Action: {', '.join(a['ticker'] for a in action) or '—'}")
    send_brief(email_html, subject)

    print("═══ Готово ═══")
    return brief


if __name__ == "__main__":
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
