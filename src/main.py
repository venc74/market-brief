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
from src.thermometer import build_thermometer, thermometer_unavailable, apply_distribution_cap
from src.sector_layer import sector_rotation, leading_sectors, laggard_sectors
from src.screener import run_screen
from src import screener, sector_layer, data_warnings
from src.enrich import enrich, inject_split_catalysts
from src.sizing import position_plan_v2, buy_stop_preview
from src import ai_brief
from src import unusual_options, splits_calendar, dataroma, news_aggregator
from src import insider_buying
from src import correlation_check
from src import backtest
from src import tracker_switch
from src import cot
from src import entry_timing
from src import setup_rules
from src import glb_screener
from src import short_screener
from src import short_tracker
from src import watchlist_expiry
from src import watch_monitor
from src import model_selector
from src import thesis_context
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
        # пакет 1, т.7: само v2 позиции — v1 е архив, не „държа" и не пречи на нов вход
        return {rec["ticker"]: rec for rec in tracker.values()
                if rec.get("method") == "v2" and backtest.is_action_record(rec)      # пакет 1б: buy-stop кандидатите не са позиции
                and rec.get("status") in ("open", "trailing")}
    except Exception as e:
        print(f"[main] live positions check failed: {e}")
        return {}


_RESOLUTION_BG = {
    "stopped": "стоп",
    "trailing_stop_exit": "trailing изход",
    "expired": "изтекла по време",
    "expired_in_trail": "изтекла в trail",
}


def _last_resolved_positions() -> dict[str, dict]:
    """
    FIX 2026-09-22: тикър → НАЙ-СКОРОШНАТА приключила позиция от tracker-а.

    Нужен е заради страничен ефект на фикса от 17.09. Дотогава
    resolve_positions_only() се случваше в края на pipeline-а, затова
    apply_hard_rules() четеше ПРЕДрезолюционния tracker: тикър, приключил в
    този run, още изглеждаше жив, получаваше OPEN✓ и отиваше във Watchlist.
    След преместването на резолюцията по-рано (за COT контекста) той вече не е
    жив на този етап и може да получи пълен Action план с нов риск — в същия
    run, в който предишната му позиция е приключила.

    Съзнателно БЕЗ времеви прозорец. Измерено срещу всичките 30 дневни run-а:
    маркерът би гръмнал общо 2 пъти (ANET на 05.08, 19 дни след стоп; AVT на
    14.09, 25 дни след стоп) — и двата са легитимни повторни входове. Прозорец
    от 5 или 10 дни би дал 0 попадения, т.е. само би добавил произволно число
    без да променя нищо. Показваме датата и изхода, юзърът преценява
    релевантността сам.
    """
    try:
        tracker = backtest._load_tracker()
        out: dict[str, dict] = {}
        for rec in tracker.values():
            if rec.get("method") != "v2":        # т.7: v1 историята е архив
                continue
            if not backtest.is_action_record(rec):   # пакет 1б: затворен buy-stop кандидат не е "предишна позиция"
                continue
            if rec.get("realized_r") is None or not rec.get("resolution_date"):
                continue
            cur = out.get(rec["ticker"])
            if cur is None or rec["resolution_date"] > cur["resolution_date"]:
                out[rec["ticker"]] = rec
        return out
    except Exception as e:
        print(f"[main] resolved positions check failed: {e}")
        return {}


def _regime_gate(c: dict, regime: str | None) -> str | None:
    """
    Пакет 1, т.6: текстът за Watchlist, ако режимът блокира Action за този кандидат;
    None → преминава. Cash → никакъв Action; Defensive → само при Entry Timing "good"
    (0…+ENTRY_TIMING_EXTENDED_PCT% над pivot, с обем). regime=None → без ограничение.
    """
    if regime == "Cash" and config.REGIME_CASH_BLOCKS_ACTION:
        return ("Режим Cash — нов Action не се дава (капиталът е позиция). "
                "Сетъпът се преценява отново, щом режимът се подобри.")
    if regime == "Defensive" and config.REGIME_DEFENSIVE_REQUIRES_GOOD_TIMING:
        timing = entry_timing.evaluate_pivot_volume(c)
        if not timing or timing["verdict"] != "good":
            why = timing["note"] if timing else "няма данни за entry timing"
            return (f"Режим Defensive — Action само при добър entry timing (0…+"
                    f"{config.ENTRY_TIMING_EXTENDED_PCT:g}% над pivot, с обем): {why}")
    return None


def apply_hard_rules(candidates: list[dict], sizing_factor: float,
                     regime: str | None = None) -> tuple[list, list]:
    """
    Твърдите правила от Секция 8, наложени СЛЕД AI класификацията —
    кодът има последната дума, не моделът. `regime` (термометърът) включва и
    режимния gate (т.6); без него режимът не ограничава Action.
    """
    action, watchlist = [], []
    sector_count: dict[str, int] = {}
    live = _live_positions() if config.ENABLE_BACKTEST else {}
    closed = _last_resolved_positions() if config.ENABLE_BACKTEST else {}
    today = dt.date.today().isoformat()

    for c in candidates:
        # FIX 2026-07-15: тикър с жива позиция НЕ получава нов Action план
        # (имплицитно удвояване на риска). Отива във Watchlist с изричен
        # OPEN✓ маркер — повторният breakout сигнал е потвърждение на
        # тезата, не нов вход.
        rec = live.get(c.get("ticker"))
        if rec:
            # v2: датата на ВХОДА (fill_date), не на препоръката; entry_price вече е реалната цена
            held_since = rec.get("fill_date") or rec.get("entry_date")
            c.setdefault("markers", []).append({
                "tag": "OPEN✓",
                "title": (f"Отворена позиция от {held_since} "
                          f"@ ${rec.get('entry_price')} — не е нов вход."),
            })
            c.setdefault("ai", {})
            c["ai"]["classification"] = "Watchlist"
            # FIX 2026-09-12 (findings log 04-11.09, т.2): explicit override, не
            # оставяй каквото AI-то е предложило (ако въобще) — watchlist_expiry.py
            # разчита на този таг да НЕ третира вече отворени позиции като
            # "regime_gate" (различен клас watchlist причина, не участва в
            # expiry механизма).
            c["ai"]["watchlist_reason_type"] = "existing_position"
            c["ai"]["watchlist_trigger"] = (
                f"Вече в портфейла от {held_since} "
                f"(entry ${rec.get('entry_price')}). Повторният breakout сигнал "
                "потвърждава тезата — управлявай съществуващата позиция, не добавяй риск.")
        else:
            # FIX 2026-09-22: тикърът НЯМА жива позиция, но може да е имал
            # такава, която току-що е приключила. Виж _last_resolved_positions()
            # за пълния rationale. Само при липса на жива позиция — иначе
            # OPEN✓ по-горе вече казва същественото и този маркер е шум.
            prev = closed.get(c.get("ticker"))
            if prev:
                outcome = _RESOLUTION_BG.get(prev.get("status"), prev.get("status") or "?")
                r = prev.get("realized_r")
                detail = (f"Предишна позиция от {prev.get('entry_date')} "
                          f"приключи на {prev.get('resolution_date')} "
                          f"({outcome}{f', {r:+.1f}R' if r is not None else ''}).")
                if prev.get("resolution_date") == today:
                    # Ръб на консистентността, НЕ търговска преценка: Track
                    # Record-ът няма да запише този вход като отделна сделка —
                    # _is_continuation() го третира като продължение, защото
                    # датата му попада в [entry_date, resolution_date] на току-що
                    # приключилата позиция. Ако въпреки това дадем Action план с
                    # реален риск, брифът ще показва план, който системата не
                    # проследява. На практика редки: run-ът е 05:30 UTC, преди
                    # US отваряне, затова resolution_date е винаги ≤ вчера
                    # (потвърдено: 0 от 14 резолюции носят днешна дата).
                    c.setdefault("markers", []).append({
                        "tag": "ЗАТВОРЕНА ДНЕС",
                        "title": f"{detail} Нов вход в същия ден не се планира.",
                    })
                    c.setdefault("ai", {})
                    c["ai"]["classification"] = "Watchlist"
                    c["ai"]["watchlist_reason_type"] = "other"
                    c["ai"]["watchlist_trigger"] = (
                        f"{detail} Нов вход в СЪЩИЯ ден не се планира — Track "
                        "Record-ът не може да го запише като отделна сделка. "
                        "Ако сетъпът е валиден, ще се прецени утре.")
                else:
                    c.setdefault("markers", []).append({
                        "tag": "RE-ENTRY",
                        "title": f"{detail} Това е НОВ вход, не продължение.",
                    })
                    c["prev_position"] = {
                        "entry_date": prev.get("entry_date"),
                        "resolution_date": prev.get("resolution_date"),
                        "outcome": outcome,
                        "realized_r": r,
                    }
        cls = c.get("ai", {}).get("classification", "Watchlist")
        sector = c.get("sector", "Unknown")

        # FIX 2026-10-02 (пакет 1, т.1): технически Action gate — кодът има
        # последната дума. Action е допустим САМО при потвърден пробив: close над
        # pivot (най-високия High на базата без последните N бара), до +5% над него,
        # с обем >= BREAKOUT_VOLUME_MULT × среден. Всичко останало (под pivot →
        # buy-stop ниво, над pivot без обем, extended) отива във Watchlist, колкото и
        # силно да го е оценило AI-то. Проверява се ПРЕДИ лимитите по-долу, за да не
        # заема Action слот кандидат, който така или иначе е върнат.
        setup = c.get("setup") or setup_rules.classify_setup(c, today)
        c["setup"] = setup
        if cls == "Action" and not setup["eligible"]:
            cls = "Watchlist"
            c.setdefault("ai", {})
            c["ai"]["watchlist_reason_type"] = "technical_gate"
            c["ai"]["watchlist_trigger"] = setup["trigger_text"]

        # FIX 2026-10-03 (пакет 1, т.6): режимен gate СЛЕД техническия и ПРЕДИ лимитите —
        # блокиран кандидат не заема Action слот. reason_type "regime_block" е код-наложена
        # причина и НЕ участва в 10-дневното изтичане на "regime_gate" (watchlist_expiry).
        if cls == "Action":
            gate_text = _regime_gate(c, regime)
            if gate_text:
                cls = "Watchlist"
                c.setdefault("ai", {})
                c["ai"]["watchlist_reason_type"] = "regime_block"
                c["ai"]["watchlist_trigger"] = gate_text

        if cls == "Action":
            if len(action) >= config.MAX_ACTION_TICKERS:
                cls = "Watchlist"
                c["ai"]["watchlist_reason_type"] = "other"  # портфейлен лимит, не regime-gate
                c["ai"]["watchlist_trigger"] = "Лимит 5 Action тикъра — следващ по сила."
            elif sector_count.get(sector, 0) >= config.MAX_PER_SECTOR:
                cls = "Watchlist"
                c["ai"]["watchlist_reason_type"] = "other"
                c["ai"]["watchlist_trigger"] = f"Вече {config.MAX_PER_SECTOR} Action от {sector}."

        if cls == "Action":
            # FIX 2026-10-03 (пакет 1, т.3): структурен стоп (15-баров low, макс. 8% под
            # входа), buy-stop вход, цел 50% на 2R — виж sizing.position_plan_v2
            plan = position_plan_v2(c, sizing_factor, today)
            if not plan.get("valid"):
                cls = "Watchlist"
                c["ai"]["watchlist_reason_type"] = "other"
                c["ai"]["watchlist_trigger"] = plan.get("reason", "Невалиден риск план.")
            else:
                c["plan"] = plan
                sector_count[sector] = sector_count.get(sector, 0) + 1
                action.append(c)
                continue
        c["ai"].setdefault("watchlist_trigger", "Изчаква потвърждение.")
        # пакет 2: buy-stop кандидатите показват стоп, риск %, цел 1 и размер на позицията при sizing-а на режима (само показване)
        if (c.get("setup") or {}).get("buy_stop"):
            c["plan_preview"] = buy_stop_preview(c, sizing_factor, today)
        watchlist.append(c)

    # Watchlist е най-много 10 карти: потвърден пробив, спрян от лимит/режим/earnings,
    # първи; после buy-stop кандидатите (най-близките до pivot), после "над pivot без
    # обем", extended най-накрая. Стабилна сортировка — вътре в групата остава AI редът.
    watchlist.sort(key=setup_rules.watchlist_sort_key)
    return action, watchlist[:10]


def _short_global_context(short_candidates: list[dict], laggards: list[dict], news) -> dict:
    """
    Пакет 4а т.5: AI контекстът "глобално срещу регионално" за секторите на short кандидатите.
    ИЗКЛЮЧЕН по подразбиране (config.ENABLE_SHORT_AI_CONTEXT) — няма визуализация, а всяко
    извикване е платено. Когато е включен: само за capped подмножество лагиращи сектори,
    сортирано по severity (MAX_LAGGARD_SECTORS_FOR_AI_CONTEXT — 2023-2025 daily co-occurrence
    тест: медиана 5, до 12 едновременно; cost/latency контрол на тази стъпка, не на detection gate-а).
    """
    if not config.ENABLE_SHORT_AI_CONTEXT or not short_candidates:
        return {}
    seen = {c["lagging_sector"] for c in short_candidates}
    out = {}
    for sector in laggards[:config.MAX_LAGGARD_SECTORS_FOR_AI_CONTEXT]:
        if sector["sector"] not in seen:
            continue
        out[sector["sector"]] = ai_brief.short_thesis_global_context(sector["sector"], news)
    return out


def run() -> dict:
    today = dt.date.today().isoformat()
    print(f"═══ AI Инвестиционен Бриф · {today} ═══")

    # Кой Claude модел ползваме днес — ВЕДНЪЖ, преди всяка AI стъпка. Резултатът
    # се присвоява на config.CLAUDE_MODEL и се наследява от всички извиквания,
    # защото _call_claude чете конфигурацията при всяко извикване. Виж
    # model_selector.resolve_model() за escape hatch / probe / fallback реда.
    # FIX 2026-09-23: чисти записи за отрязвания и usage за ТОЗИ run.
    ai_brief.TRUNCATIONS.clear()
    ai_brief.AI_USAGE.clear()
    model_info = {"model": config.CLAUDE_MODEL, "source": "static",
                  "rejected": None, "rejected_reason": "", "banner": {}}
    try:
        model_info = model_selector.resolve_model(today)
        config.CLAUDE_MODEL = model_info["model"]
    except Exception as e:
        print(f"[model] resolve_model се провали изцяло, оставам на "
              f"{config.CLAUDE_MODEL}: {e}")

    print("[1/7] Слой 1: макро контекст…")
    macro = collect_macro_layer()

    print("[2/7] Пазарен термометър…")
    try:
        thermo = build_thermometer(macro)
    except Exception as e:
        # термометърът не бива да сваля целия бриф (класът KeyError при скрит
        # индикатор в хистерезис) — Defensive по подразбиране, виж thermometer_unavailable
        traceback.print_exc()
        print(f"[thermo] ⚠ build_thermometer пропадна ({type(e).__name__}: {e}) — "
              f"fallback Defensive")
        thermo = thermometer_unavailable(e)
    # Допълнение към пакет 2 (2026-10-05): distribution days (пазарно-глобален сигнал, SPY + QQQ) се смятат ТУК, преди
    # макро брифа и режимния gate на Action — червени → режимът е най-много Defensive (виж apply_distribution_cap).
    # Преди се смятаха по-надолу, само за информативна карта; сега се ползва същият резултат (един fetch).
    distribution_days = None
    if config.ENABLE_ENTRY_TIMING:
        try:
            distribution_days = entry_timing.evaluate_distribution_days()
        except Exception as e:
            print(f"[entry_timing] distribution days пропаднаха: {type(e).__name__}: {e}")
        try:
            thermo = apply_distribution_cap(thermo, distribution_days)
        except Exception as e:
            print(f"[thermo] ⚠ apply_distribution_cap пропадна ({type(e).__name__}: {e}) — режимът е без този блок")
    print(f"      Режим: {thermo['regime']} — {thermo['regime_reason']}")

    # v2 · Секция 5 — кои геополитически тези са активни при текущото макро
    theses = thesis_monitor(macro)

    print("[3/7] Слой 2: секторна ротация…")
    # FIX 2026-10-03 (пакет 2 т.6): паднал Yahoo не сваля run-а — sector_rotation() връща [] и записва причината
    # в sector_layer.LAST_STATUS; в брифа излиза предупреждение (data_warnings), а не тих празен резултат.
    try:
        rotation = sector_rotation()
    except Exception as e:
        traceback.print_exc()
        sector_layer.LAST_STATUS.clear()
        sector_layer.LAST_STATUS.update(ok=False, reason=f"{type(e).__name__}: {e}")
        rotation = []
    leaders = leading_sectors(rotation)
    # Short/Stage 4 screener вход — persistence-gated (не еднодневен snapshot),
    # виж laggard_sectors() docstring-а. Реалният screening (мрежово скъп) се
    # случва по-долу, до GLB блока — тук само евтиното sector-level изчисление.
    laggards = laggard_sectors(rotation)

    print("[4/7] Слой 3: скрининг…")
    try:
        candidates = run_screen([s["sector"] for s in leaders], leaders=leaders)
    except Exception as e:
        traceback.print_exc()
        screener.LAST_STATUS.clear()
        screener.LAST_STATUS.update(ok=False, kind="crashed", reason=f"{type(e).__name__}: {e}")
        candidates = []

    print(f"[5/7] Обогатяване на {len(candidates)} кандидата…")
    candidates = enrich(candidates)
    # техническа класификация (потвърден пробив / buy-stop / extended) — ПРЕДИ AI
    # синтеза, за да я вижда и промптът; apply_hard_rules() я налага след него
    candidates = setup_rules.annotate(candidates, today)
    screener_universe = [{"ticker": c["ticker"], "sector": c.get("sector"),
                          "industry": c.get("industry")} for c in candidates]
    print("[6/7] AI синтез (Claude API)…")
    # FIX 2026-10-03 (пакет 2 т.4): значимите новини (RSS + nitter → Claude филтър) се подбират ПРЕДИ макро
    # брифа и му се подават с обяснението защо са значими — преди брифът се пишеше без тях, а NewsAPI
    # заглавията бяха празни във всичките 78 брифа. Graceful: провал на новините → празен списък.
    try:
        news = news_aggregator.significant_news() if config.ENABLE_NEWS else []
    except Exception as e:
        print(f"[main] significant_news пропадна, макро брифът е без новини: {e}")
        news = []
    ai_macro = ai_brief.macro_and_sector_brief(macro, rotation, thermo, news=news)
    # FIX 2026-09-16: тезите се сверяват срещу днешните новини — виж
    # ai_brief.thesis_reality_check(). САМО анотация (news_status/news_note);
    # `status` остава trigger-driven, `chain` остава конфиг.
    #
    # FIX 2026-09-18: подава се СУРОВИЯТ пул, не филтрираните ~8 — те се
    # подбират по обща пазарна значимост за деня и системно изпускат тезово-
    # релевантни новини в тесни домейни (потвърдено с SEC tokenized-stock
    # историята на 18.09). Виж news_aggregator.raw_pool(). Нула допълнителен
    # fetch — gather_raw мемоизира в процеса.
    theses = ai_brief.thesis_reality_check(
        theses, news_aggregator.raw_pool() if config.ENABLE_NEWS else [])
    narratives = ai_brief.ticker_narratives(
        candidates, ai_macro.get("sector_logic", []), thermo["regime"])
    candidates = ai_brief.merge_narratives(candidates, narratives)
    # v2 · Секция 3.4 — споменаване на предстоящ сплит в катализаторите (след AI merge)
    candidates = inject_split_catalysts(candidates)
    print("      COT екстремуми…")
    cot_extremes = cot.get_extremes() if config.ENABLE_COT else []
    # FIX 2026-09-15: COT промптът вижда и отворените Track Record позиции, не
    # само днешния скрийнър — виж ai_brief.cot_theses() docstring-а (RBOB/VLO
    # случаят). _live_positions() е чист локален прочит на backtest_tracker.json
    # (без мрежа), затова може да се вика тук, преди backtest блока по-долу —
    # никакво пренареждане на pipeline-а, за разлика от GLB badge фикса, който
    # трябваше да живее СЛЕД get_backtest_summary(). apply_hard_rules() по-долу
    # прави свой собствен такъв прочит; дублирането е евтино и нарочно, за да
    # не се въвежда споделено състояние между двете места.
    # Фирменото име е задължително — реалният случай назова "Valero", не "VLO".
    #
    # FIX 2026-09-17: резолюцията на живите позиции се изпълнява ТУК, преди
    # контекстът да се сглоби. Без това _live_positions() четеше вчерашното
    # състояние от диска — потвърдено на 17.09: FITB/ONB бяха описани от COT-а
    # като "вече отворени позиции" (с цитирани entry дати), а Track Record-ът
    # в СЪЩИЯ бриф ги показваше като stopped на 16.09. Виж
    # backtest.resolve_positions_only() за пълния rationale. Нула допълнителна
    # мрежова цена — update_backtest_tracker() по-долу пропуска втория fetch.
    #
    # Страничен ефект: apply_hard_rules() по-долу също вижда резолвирания
    # tracker, т.е. току-що стопнат тикър може да получи нов Action план.
    # Решено на 22.09: _last_resolved_positions() маркира такъв кандидат с
    # RE-ENTRY (нов вход, не продължение) или ЗАТВОРЕНА ДНЕС (без Action план
    # в същия ден — Track Record не би го записал като отделна сделка).
    if config.ENABLE_BACKTEST:
        # FIX 2026-10-03 (пакет 1, т.7): еднократен чист старт на Track Record-а — v1 записите се
        # архивират, отворените се затварят по последния Close ("v1_closed"). ПРЕДИ резолюцията
        # и преди каквото и да четe _live_positions() (OPEN✓/RE-ENTRY/COT гледат само v2).
        # Идемпотентно и graceful — провал оставя v1 до следващия run, без загуба на данни.
        tracker_switch.ensure_v2_methodology()
        backtest.resolve_positions_only()
    cot_live = _live_positions() if config.ENABLE_BACKTEST else {}
    cot_open_positions = [
        {"ticker": t, "company": ai_brief._verified_company_name(t)["name"],
         "entry_date": rec.get("fill_date") or rec.get("entry_date")}
        for t, rec in sorted(cot_live.items())
    ]
    cot_with_theses = ai_brief.cot_theses(
        cot_extremes, screener_universe, thermo["regime"],
        cot_open_positions) if cot_extremes else []
    action, watchlist = apply_hard_rules(candidates, thermo["sizing_factor"], thermo["regime"])
    # FIX 2026-09-12 (findings log 04-11.09, т.2): code-enforced regime-gate
    # expiry — виж watchlist_expiry.py docstring за пълния rationale (преди:
    # чист AI prose, датата "измисляна" наново всеки ден).
    watchlist = watchlist_expiry.apply_regime_gate_expiry(watchlist, thermo["regime"], today)
    print(f"      Action: {[a['ticker'] for a in action]}")
    print(f"      Watchlist: {[w['ticker'] for w in watchlist]}")
    # FIX 2026-09-29: каре "Контекст" (само данни) към маркираните тези +
    # предупреждение за тикъри без ценови данни — виж thesis_context.py. ТУК:
    # новините, ротацията, action/watchlist и резолвираните позиции са готови.
    if config.ENABLE_THESIS_CONTEXT:
        theses = thesis_context.annotate(
            theses, rotation, thermo["regime"],
            positions=set(cot_live), action={a["ticker"] for a in action},
            watchlist={w["ticker"] for w in watchlist})
    # чисто информационен badge на картата — не пипа classification/plan/sizing,
    # screening и timing остават разделени, виж entry_timing.py docstring-а
    if config.ENABLE_ENTRY_TIMING:
        action = entry_timing.evaluate(action)
    # концепция 3 — distribution days: изчислени по-горе (след термометъра), за да ограничат режима
    # чисто информационен флаг — не променя избора на Action, виж correlation_check.py
    correlation_flags = (correlation_check.fetch_correlation_flags(action)
                         if config.ENABLE_CORRELATION_CHECK else [])

    # v2 · допълнителни dashboard данни (Секции 3.3, 3.4, 6) — кеширани за деня
    unusual_today = unusual_options.fetch_unusual_options(10) if config.ENABLE_UNUSUAL_OPTIONS else []
    splits_month = splits_calendar.fetch_upcoming_splits() if config.ENABLE_SPLITS_CALENDAR else []
    superinvestor_moves = dataroma.fetch_superinvestor_buys() if config.ENABLE_DATAROMA else []
    # FIX 2026-08-17: high-conviction нови позиции (>DATAROMA_MIN_NEW_POSITION_PCT%
    # от портфейл) и major exits (>DATAROMA_MAJOR_EXIT_PCT%, explicit разделени от
    # "мениджър спрял да подава" — виж dataroma.py docstring-а). От 2026-10-03 новите
    # позиции не са секция, а маркер SI✓ (данните остават в брифа за маркерите и историята).
    superinvestor_new_positions = dataroma.fetch_new_position_highlights() if config.ENABLE_DATAROMA else []
    superinvestor_exits = (dataroma.fetch_major_exits() if config.ENABLE_DATAROMA
                           else {"exits": [], "stopped_managers": []})
    superinvestor_status = dataroma.fetch_status() if config.ENABLE_DATAROMA else {}
    insider_buys = insider_buying.fetch_insider_buying() if config.ENABLE_INSIDER_BUYING else []
    insider_status = dict(insider_buying.LAST_STATUS) if config.ENABLE_INSIDER_BUYING else {}
    # конвергенция: тикър и в CANSLIM скрийнъра (action+watchlist), и в insider buying — виж insider_buying.py docstring
    our_tickers = {c["ticker"] for c in action} | {c["ticker"] for c in watchlist}
    for row in insider_buys:
        row["in_screener"] = row["ticker"] in our_tickers
    # (superinvestor_exits конвергенцията се изчислява в темплейта, "s.ticker in
    # our_tickers" — same паттърн като superinvestor_moves, не precomputed поле тук;
    # новите позиции вече не са секция — виж SI✓ маркерите в enrich и по-долу)
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
    # Global-vs-regional context (Аспект 2) — СПРЯН на 2026-10-03 (config.ENABLE_SHORT_AI_CONTEXT=0):
    # резултатът не се визуализира. Виж _short_global_context().
    global_context = _short_global_context(short_candidates, laggards, news)
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

    # FIX 2026-09-12 (findings log 04-11.09, т.3): GLB кандидатите нямаха
    # cross-reference срещу Track Record отворени позиции — потвърден gap
    # (FCFS едновременно GLB Classic кандидат И отворена позиция, всичките
    # 4 проверени дни, без никакъв визуален сигнал за конвергенцията/
    # дублирането). Mirror на in_screener badge механизма по-горе — трябва
    # да живее ТУК, след backtest_summary изчислението (open_positions не е
    # наличен по-рано, при самия GLB блок).
    # FIX 2026-10-03 (пакет 4а т.2): SI✓ върху v2 позициите (отворени и чакащи buy-stop), когато
    # мениджър от списъка е открил нова позиция в тикъра — вместо секцията-списък
    try:
        si_markers = dataroma.new_position_markers(superinvestor_new_positions)
        for p in (backtest_summary.get("open_positions", []) + backtest_summary.get("pending_positions", [])):
            if p["ticker"] in si_markers:
                p["markers"] = [si_markers[p["ticker"]]]
    except Exception as e:
        print(f"[main] SI✓ маркери за позициите пропуснати: {e}")
    open_position_tickers = {p["ticker"] for p in backtest_summary.get("open_positions", [])}
    for row in glb_candidates:
        row["already_open_position"] = row["ticker"] in open_position_tickers

    # short_tracker.py — prospective проследяване на short кандидатите, same
    # "ден+1" fix и graceful degradation дух като backtest блока по-горе.
    # Единственият начин да измерим реален hit rate занапред (виж
    # short_screener.py docstring-а за структурния лимит на историческата
    # валидация на survival-risk критериите).
    if config.ENABLE_SHORT_SCREENER:
        short_tracker.update_short_tracker(short_candidates, today)
    short_tracker_summary = (short_tracker.get_short_tracker_summary()
                             if config.ENABLE_SHORT_SCREENER else {})

    # 🔎 Наблюдавани тикъри — ръчно куриран per-ticker монитор (watch_monitor.py).
    # ТУК, а не по-рано: `theses`, `cot_with_theses` и `leaders` вече са готови
    # и се подават като market_context за cross-referencing-а — reuse на вече
    # наличното в паметта, не нов източник.
    #
    # "Нищо не се е случило" е CODE-ENFORCED: тих тикър (нула новини, нула
    # Form 4) изобщо не стига до AI-то — кодът му слага текста сам. Така
    # изричното "нищо" е гарантирано, не зависи от това дали моделът ще се
    # сети да го каже, и не се плащат токени за празен вход.
    watch_rows = []
    if config.ENABLE_WATCH_MONITOR:
        try:
            watch_rows = watch_monitor.collect()
            active = [r for r in watch_rows if not r["quiet"]]
            if active:
                market_context = {
                    "active_theses": [t["name"] for t in theses
                                      if t.get("status") in ("active", "structural")],
                    "cot_markets": [c["market"] for c in cot_with_theses][:10],
                    "leading_sectors": [s["sector"] for s in leaders],
                }
                active = ai_brief.watch_ticker_digest(active, market_context)
            by_ticker = {r["ticker"]: r for r in active}
            watch_rows = [by_ticker.get(r["ticker"], {**r, "ai": {}}) for r in watch_rows]
        except Exception as e:
            print(f"[watch] секцията се провали изцяло: {e}")
            watch_rows = []

    # FIX 2026-09-27: пълен отчет за сплитовете — секцията вече не се скрива
    # (ok / empty с фуния по филтри / source_failed), + сплитове на отворени
    # позиции и наблюдавани в целия хоризонт на източника, без филтри. ТУК,
    # след update_backtest_tracker(): днешните нови позиции вече са в tracker-а.
    splits_rep = None
    if config.ENABLE_SPLITS_CALENDAR:
        try:
            splits_rep = splits_calendar.splits_report(
                positions=set(_live_positions()) if config.ENABLE_BACKTEST else set(),
                watched=set(watch_monitor.load_watch_list()) if config.ENABLE_WATCH_MONITOR else set())
        except Exception as e:
            print(f"[splits] отчетът се провали: {e}")

    brief = {
        "date": today,
        "macro": macro,
        "thermometer": thermo,
        "rotation": rotation,
        # пакет 2 т.6: паднал Yahoo / празен универс — празният резултат не бива да се чете като "няма сетъпи"
        "data_warnings": data_warnings.collect(sector_layer.LAST_STATUS, screener.LAST_STATUS, rotation_count=len(rotation)),
        "ai_macro": ai_macro,
        "model_info": model_info,
        # FIX 2026-09-23: видимо предупреждение за отрязани AI отговори +
        # usage по извикване (единственият достъпен източник на реални token
        # числа — Actions логът иска автентикация)
        "ai_truncations": list(ai_brief.TRUNCATIONS),
        "ai_usage": list(ai_brief.AI_USAGE),
        "watch": watch_rows,
        "action": action,
        "watchlist": watchlist,
        # v2 нови блокове
        "theses": theses,
        "unusual_options": unusual_today,
        # FIX 2026-09-28: колко имат съотношение обем/OI, суров OI, час на fetch-а
        "unusual_options_diag": dict(unusual_options.LAST_DIAG),
        "splits": splits_month,
        "splits_report": splits_rep,
        "superinvestor_moves": superinvestor_moves,
        "superinvestor_new_positions": superinvestor_new_positions,
        "superinvestor_exits": superinvestor_exits,
        "insider_buying": insider_buys,
        # пакет 4а т.7: давност и причина при празен днешен резултат (легитимна нула срещу провал)
        "insider_buying_status": insider_status,
        "superinvestor_status": superinvestor_status,
        "glb_candidates": glb_candidates,
        "news": news,
        "cot": cot_with_theses,
        # пакет 2 т.7: давност на най-новия COT отчет (банер в секцията, ако е стар)
        "cot_status": dict(cot.LAST_STATUS) if config.ENABLE_COT else {},
        # FIX 2026-09-28: отхвърлени COT тези / противоречия / махнати тикъри за деня
        "cot_diag": dict(ai_brief.COT_DIAG),
        # FIX 2026-09-30: приети/отхвърлени маркирания от проверката на тезите
        # срещу новините — правило (G0–G3) и причина
        "thesis_check_diag": dict(ai_brief.THESIS_CHECK_DIAG),
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
