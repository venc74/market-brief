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

from src.macro_layer import collect_macro_layer
from src.thermometer import build_thermometer, thermometer_unavailable, apply_distribution_cap, apply_market_rule
from src.sector_layer import sector_rotation, leading_sectors
from src.screener import run_screen
from src import screener, sector_layer, data_warnings
from src.enrich import enrich
from src import enrich as enrich_mod
from src.sizing import position_plan_v2, buy_stop_preview
from src import trade_levels
from src import data_rhythm
from src import crypto_news
from src import sessions
from src import ai_brief
from src import splits_calendar, news_aggregator, sec_names
from src import insider_buying
from src import correlation_check
from src import backtest
from src import spinoff_watch
from src import regime_claims
from src import bar_freshness
from src import tracker_switch
from src import entry_timing
from src import setup_rules
from src import earnings_move
from src import glb_screener
from src import data_canary
from src import health_monitor
from src import watchlist_exits
from src import corp_actions
from src import qm_breakout
from src import qm_ep
from src import watchlist_expiry
from src import watch_monitor
from src import model_selector
from src import steps
from src.render import render_dashboard, render_email
from src.emailer import send_brief, send_once


def _live_positions() -> dict[str, dict]:
    """
    FIX 2026-07-15: тикър → запис за живите (open/trailing) позиции от
    backtest tracker-а. Скрийнърът нямаше представа какво вече държиш —
    на 2026-07-15 и трите ACTION тикъра (AMG, EXEL, ALL) бяха отворени
    позиции от седмици, представени като нови входове с нов риск $1000.
    """
    try:
        # пакет 1, т.7: само v2 позиции — v1 е архив, не „държа" и не пречи на нов вход; пакет 1б: само Action книгата — buy-stop кандидатите не са позиции
        return {rec["ticker"]: rec for rec in backtest.book_records(backtest.CATEGORY_ACTION, statuses=backtest.POSITION)}
    except Exception as e:
        print(f"[main] live positions check failed: {e}")
        return {}


def _pending_action_plans() -> dict[str, dict]:
    """
    Втори преглед (10.10.2026): тикър → v2 Action запис, който ЧАКА buy-stop (status pending — прозорецът още тече). Не е позиция (COT контекстът
    и "вече в портфейла" не го броят), но нов Action план за същия тикър би дублирал чакащия — apply_hard_rules го връща във Watchlist.
    """
    try:
        return {rec["ticker"]: rec for rec in backtest.book_records(backtest.CATEGORY_ACTION, statuses=("pending",))}
    except Exception as e:
        print(f"[main] pending plans check failed: {e}")
        return {}


def attach_qm_markers(rows: list[dict], qm_by_ticker: dict[str, dict]) -> int:
    """Qullamaggie: слага QM✓ върху редовете (Action/Watchlist карти, позиции), чийто тикър е и кандидат за пробив (ВСИЧКИ кандидати, не само показаните 8). Връща броя маркирани."""
    n = 0
    for r in rows:
        q = qm_by_ticker.get(r.get("ticker"))
        if q:
            r.setdefault("markers", []).append(qm_breakout.qm_marker(q))
            n += 1
    return n


def attach_position_insider(rows: list[dict]) -> dict:
    """Пакет 4б т.в: слага INS✓ върху редовете на позициите (по ЕДНО теглене за всички тикъри). Връща статуса на тегленето."""
    tickers = sorted({r["ticker"] for r in rows if r.get("ticker")})
    if not tickers:
        return {}
    ins, status = insider_buying.insider_for(tickers)
    for r in rows:
        if r.get("ticker") in ins:
            r.setdefault("markers", []).append(insider_buying.insider_marker(ins[r["ticker"]]))
    return status


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
        # т.7: v1 историята е архив; пакет 1б: затворен buy-stop кандидат не е "предишна позиция" — само v2 записите на Action книгата
        return backtest.latest_by_ticker([r for r in backtest.book_records(backtest.CATEGORY_ACTION)
                                          if r.get("realized_r") is not None and r.get("resolution_date")], key="resolution_date")
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


def _watchlist_trigger_text(c: dict, regime: str | None) -> str:
    """
    Текстът "Trigger" на Watchlist картата, сглобен от КОДА (08.10.2026, 2б) — моделът не пише watchlist_trigger. Части, в ред: отчет (earnings.in_blackout / дни до отчета),
    сетъпът (setup.trigger_text — buy-stop, обем, extended, твърде разтегнато), режимният gate (_regime_gate).
    Без нито една част → кратко пояснение, че потвърденият сетъп не е избран. Чиста функция.
    """
    parts: list[str] = []
    e = c.get("earnings") or {}
    days = e.get("days_to_earnings")
    if (e.get("recent_report") or {}).get("text"):                 # 16.10.2026 (В1): отчет в последната сесия — нивата са отпреди реакцията
        parts.append(e["recent_report"]["text"])
    elif e.get("earnings_status") == "failed":                        # 16.10.2026 (В1): датата е неизвестна, защото тегленето не успя
        parts.append(enrich_mod.UNKNOWN_EARNINGS_TEXT)
    if e.get("in_blackout") or (isinstance(days, (int, float)) and 0 <= days <= 7):
        ne = enrich_mod.earnings_dm(e.get("next_earnings"), e.get("earnings_estimate"))       # 16.10.2026: ДД.ММ, не ISO; 03.11.2026: прогнозна → „~ДД.ММ (прогноза)“
        when = "ДНЕС" if days == 0 else (f"на {ne} ({int(days)} дни)" if isinstance(days, (int, float)) and ne else f"на {ne or 'неизвестна дата'}")
        parts.append(f"Отчет {when} — нов Action най-рано след отчета.")
    setup = c.get("setup") or {}
    if setup.get("trigger_text"):
        parts.append(setup["trigger_text"])
    gate = _regime_gate(c, regime)
    if gate:
        parts.append(gate)
    if not parts:
        parts.append("Не е избран за Action днес — виж „Защо точно сега“.")
    return " ".join(parts)


def _code_reason_type(c: dict, regime: str | None) -> str:
    """
    В2 (10.10.2026): причината на Watchlist картата от кода, за картите без код-наложена причина в apply_hard_rules. Отчет в прозореца →
    earnings_blackout; потвърден сетъп, спрян от режима (_regime_gate) → regime_gate (само той участва в 10-сесийното изтичане); непотвърден
    сетъп → technical_gate; иначе → other. Чиста функция. 30.10.2026 (т. 9–10): класът е на кода — потвърден пробив стига дотук само принудено (позиция, отчет,
    режим → regime_block, лимит); клонът regime_gate (до 30.10 — потвърден пробив, който AI е нарекъл Watchlist при режимен gate) вече не се достига.
    """
    e = c.get("earnings") or {}
    if e.get("in_blackout"):
        return "earnings_blackout"
    if e.get("recent_report"):                                          # 16.10.2026 (В1)
        return "earnings_recent"
    if e.get("earnings_status") == "failed":
        return "earnings_unknown"
    setup = c.get("setup") or {}
    if setup.get("kind") == "confirmed" and _regime_gate(c, regime):
        return "regime_gate"
    if setup and not setup.get("eligible"):
        return "technical_gate"
    return "other"


def apply_hard_rules(candidates: list[dict], sizing_factor: float,
                     regime: str | None = None) -> tuple[list, list]:
    """
    Твърдите правила от Секция 8. 30.10.2026 (разходката, т. 9–10): класът е САМО на кода — потвърден пробив (setup.eligible) е кандидат за Action
    („Купува се днес“), всичко друго е Watchlist; AI не класифицира (до 30.10 отправната точка беше ai.classification: потвърден пробив, който моделът
    е нарекъл Watchlist, оставаше Watchlist — реално 1 път в 20 брифа с кодов сетъп, ROKU 23.10, цел на придобиване; от 26.10 кодът я прави "deal").
    `regime` (термометърът) включва и режимния gate (т.6); без него режимът не ограничава Action.
    """
    action, watchlist = [], []
    sector_count: dict[str, int] = {}
    live = _live_positions() if config.ENABLE_BACKTEST else {}
    pending = _pending_action_plans() if config.ENABLE_BACKTEST else {}
    closed = _last_resolved_positions() if config.ENABLE_BACKTEST else {}
    today = dt.date.today().isoformat()

    for c in candidates:
        forced = False          # В2: True, щом КОДЪТ е наложил watchlist_reason_type по-долу (позиция, отчет, технически/режимен gate, лимит, план)
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
            # FIX 2026-09-12 (findings log 04-11.09, т.2): explicit override, не
            # оставяй каквото AI-то е предложило (ако въобще) — watchlist_expiry.py
            # разчита на този таг да НЕ третира вече отворени позиции като
            # "regime_gate" (различен клас watchlist причина, не участва в
            # expiry механизма).
            c["ai"]["watchlist_reason_type"] = "existing_position"
            forced = True
            # 19.10.2026 (етап 2, т. 6): неутрално — това е запис в книгата (не портфейл), повторен пробив може и да няма (EXPD 19.10: no_volume), датата ДД.ММ.
            # До 19.10: "Вече в портфейла от 2026-10-16 (entry $199.77). Повторният breakout сигнал потвърждава тезата — …".
            ep = rec.get("entry_price")
            c["ai"]["watchlist_trigger"] = (
                f"Запис в книгата Action v2 от {setup_rules._dm(str(held_since))}"
                + (f" (вход ${float(ep):.2f})" if isinstance(ep, (int, float)) else "") + " — не е нов вход.")
        elif pending.get(c.get("ticker")):
            # втори преглед (10.10.2026): Action планът от предишен бриф още чака buy-stop → без втори план (рядко, но тогава картата показваше
            # нов вход с нов риск, докато старият е в сила)
            pr = pending[c["ticker"]]
            c.setdefault("markers", []).append({
                "tag": "ЧАКА BUY-STOP",
                "title": (f"Action планът от {pr.get('entry_date')} чака buy-stop ${pr.get('buy_stop')} "
                          f"до {pr.get('valid_through')} — не е нов вход."),
            })
            c.setdefault("ai", {})
            c["ai"]["watchlist_reason_type"] = "existing_position"
            forced = True
            c["ai"]["watchlist_trigger"] = (
                f"Action планът от {pr.get('entry_date')} е в сила: buy-stop ${pr.get('buy_stop')} (таван ${pr.get('max_chase')}), "
                f"валиден до {pr.get('valid_through')}. Нов план не се дава, докато този чака.")
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
                    c["ai"]["watchlist_reason_type"] = "other"
                    forced = True
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
        # 30.10.2026 (т. 9–10): сетъпът — преди класа (класът идва от него); принудените по-горе (позиция, чакащ план, затворена днес) са Watchlist
        setup = c.get("setup") or setup_rules.classify_setup(c, today)
        c["setup"] = setup
        c.setdefault("ai", {})
        cls = "Watchlist" if forced else ("Action" if setup.get("eligible") else "Watchlist")
        sector = c.get("sector", "Unknown")

        # В1 (втори преглед, 10.10.2026): прозорецът преди отчет (EARNINGS_BLACKOUT_DAYS) е БЕЗУСЛОВЕН — без изключение за AI поле
        # "warning" (до 10.10 merge_narratives го пропускаше). Текстът на картата не се задава тук — сглобява се от кода по-долу
        # (_watchlist_trigger_text: отчет + сетъп + режим), за да не се губи buy-stop нивото.
        if cls == "Action" and (c.get("earnings") or {}).get("in_blackout"):
            cls = "Watchlist"
            c["ai"]["watchlist_reason_type"] = "earnings_blackout"
            forced = True
        # 16.10.2026 (В1, трети преглед): отчет в ПОСЛЕДНАТА сесия (нивата са отпреди реакцията — ANET 05.08: Action по затварянето отпреди отчета от 04.08 след затварянето)
        # или неизвестна дата, защото тегленето не успя → не е Action. Текстът — в _watchlist_trigger_text.
        _e = c.get("earnings") or {}
        if cls == "Action" and (_e.get("recent_report") or _e.get("earnings_status") == "failed"):
            cls = "Watchlist"
            c["ai"]["watchlist_reason_type"] = "earnings_recent" if _e.get("recent_report") else "earnings_unknown"
            forced = True

        # FIX 2026-10-02 (пакет 1, т.1): технически Action gate — Action е допустим САМО при потвърден пробив (close над pivot, до +5%, обем ≥ 1.5×);
        # под pivot → buy-stop, над pivot без обем, extended, твърде разтегнато → Watchlist. От 30.10.2026 (т. 9–10) това е самият клас (по-горе), не поправка върху AI класа.

        # FIX 2026-10-03 (пакет 1, т.6): режимен gate СЛЕД техническия и ПРЕДИ лимитите —
        # блокиран кандидат не заема Action слот. reason_type "regime_block" е код-наложена
        # причина и НЕ участва в 10-дневното изтичане на "regime_gate" (watchlist_expiry).
        if cls == "Action":
            gate_text = _regime_gate(c, regime)
            if gate_text:
                cls = "Watchlist"
                c["ai"]["watchlist_reason_type"] = "regime_block"
                forced = True
                c["ai"]["watchlist_trigger"] = gate_text

        if cls == "Action":
            if len(action) >= config.MAX_ACTION_TICKERS:
                cls = "Watchlist"
                c["ai"]["watchlist_reason_type"] = "other"  # портфейлен лимит, не regime-gate
                forced = True
                c["ai"]["watchlist_trigger"] = "Лимит 5 Action тикъра — следващ по сила."
            elif sector_count.get(sector, 0) >= config.MAX_PER_SECTOR:
                cls = "Watchlist"
                c["ai"]["watchlist_reason_type"] = "other"
                forced = True
                c["ai"]["watchlist_trigger"] = f"Вече {config.MAX_PER_SECTOR} Action от {sector}."

        if cls == "Action":
            # FIX 2026-10-03 (пакет 1, т.3): структурен стоп (15-баров low, макс. 8% под
            # входа), buy-stop вход, цел 50% на 2R — виж sizing.position_plan_v2
            plan = position_plan_v2(c, sizing_factor, today)
            if not plan.get("valid"):
                cls = "Watchlist"
                c["ai"]["watchlist_reason_type"] = "other"
                forced = True
                c["ai"]["watchlist_trigger"] = plan.get("reason", "Невалиден риск план.")
            else:
                c["plan"] = plan
                c["levels"] = trade_levels.for_candidate(plan, c, sizing_factor, "референтен вход (сигнален close)")      # 07.10: вход/стоп/ADR/предупреждения; размерът е в браузъра
                sector_count[sector] = sector_count.get(sector, 0) + 1
                action.append(c)
                continue
        if not forced:
            # В2 (втори преглед, 10.10.2026): watchlist_reason_type е на КОДА, не на модела. До 10.10 AI етикетът "regime_gate" пускаше
            # 10-дневното изтичане (watchlist_expiry) и за карти, които кодът е класифицирал като below_pivot/too_wide (ZBRA too_wide 05–08.10,
            # EXPD below_pivot 09.10 с жив buy-stop запис); на другия ден "other" връщаше картата. regime_gate = само потвърден сетъп, спрян от режима.
            ai = c.setdefault("ai", {})
            code_reason = _code_reason_type(c, regime)
            if ai.get("watchlist_reason_type") and ai["watchlist_reason_type"] != code_reason:
                ai["watchlist_reason_type_ai"] = ai["watchlist_reason_type"]          # за проследимост; не се ползва
            ai["watchlist_reason_type"] = code_reason
        if not c["ai"].get("watchlist_trigger"):                                   # 08.10 (2б): не е наложен от по-ранно правило → сглобява се от кода (отчет + сетъп + режим)
            c["ai"]["watchlist_trigger"] = _watchlist_trigger_text(c, regime)
        # пакет 2: buy-stop кандидатите показват стоп, риск %, цел 1 и размер на позицията при sizing-а на режима (само показване)
        if (c.get("setup") or {}).get("buy_stop"):
            c["plan_preview"] = buy_stop_preview(c, sizing_factor, today)
            lv = trade_levels.for_candidate(c["plan_preview"], c, sizing_factor, "вход при задействане (buy-stop)")
            if lv:
                c["levels"] = lv
        watchlist.append(c)

    # Подредбата: потвърден пробив, спрян от лимит/режим/earnings, първи; после buy-stop кандидатите (най-близките до pivot), после "над pivot без
    # обем", extended / твърде разтегнато най-накрая. Стабилна сортировка — вътре в групата остава редът на скрийнъра. 31.10.2026 (т. 9–10): без таван
    # (до 31.10 — първите 10); „На радара“ показва всички, таванът на пълните карти „Чака пробив“ е в config.CANSLIM_WAITING_MAX (render.split_canslim).
    watchlist.sort(key=setup_rules.watchlist_sort_key)
    return action, watchlist


def _annotate_screener_exits(buystop_summary: dict, present: set) -> None:
    """
    Жив запис на buy-stop книгата (pending/open/trailing), чийто тикър го няма в днешния списък, получава "screener_exit" — първият филтър, който го е махнал, с числата
    ("RS линия 95.9% от 52-седмичния максимум < 97%"); редът в секцията на книгата остава независимо от скрийнъра. Graceful: провал → без причина, редът си стои.
    """
    try:
        rows = [r for r in (buystop_summary or {}).get("live", []) if r.get("ticker") and r["ticker"] not in present]
        if not rows:
            return
        reasons = screener.explain_exits(sorted({r["ticker"] for r in rows}))
        for r in rows:
            if r["ticker"] in reasons:
                r["screener_exit"] = reasons[r["ticker"]]
    except Exception as e:
        print(f"[main] причините за излизане от скрийнъра пропуснати: {type(e).__name__}: {e}")


def preopen_today(today: str, data_dir=None) -> dict | None:
    """04.11.2026 (четвърти преглед, Н7): data/preopen/<днес>.json, ако обновяването преди отварянето вече е минало днес (повторен сутрешен бриф); иначе / нечетим → None."""
    p = (data_dir or config.DATA_DIR) / "preopen" / f"{today}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except Exception as e:
        print(f"[main] data/preopen/{today}.json не се прочете ({type(e).__name__}) — страницата е без карето преди отварянето")
        return None


def _market_closed(today: str, data_dir=None) -> dict:
    """
    16.10.2026 (В2а, трети преглед): NYSE е затворена днес (празник от config.NYSE_HOLIDAYS или уикенд) → брифът НЕ върви: без AI, без имейл, без запис в книгите,
    състоянието и data/; страницата (само docs/index.html) показва последния бриф с банер "Борсата е затворена днес — последният бриф е от ДД.ММ". Досега брифът вървеше
    изцяло и в празници (РЕАЛНО: 19.06, 03.07, 07.09.2026 — run-ове "success", AI и записи с данните от предишната сесия). Без предишен бриф → само ред в лога.
    """
    d = pathlib.Path(data_dir or config.DATA_DIR)
    snaps = sorted(p for p in d.glob("20??-??-??.json") if p.stem < today)
    dm = lambda iso: f"{iso[8:10]}.{iso[5:7]}"
    if not snaps:
        print("[main] няма предишен бриф за показване — страницата не се пипа")
        return {"date": today, "market_closed": True, "last_brief": None}
    last = snaps[-1]
    try:
        b = json.loads(last.read_text(encoding="utf-8"))
        text = f"Борсата (NYSE) е затворена днес ({dm(today)}) — последният бриф е от {dm(last.stem)}."
        render_dashboard(b, closed_notice=text, publish=False, as_of=dt.date.fromisoformat(last.stem))
        print(f"[main] {text} Страницата е обновена само с банера.")
    except Exception as e:
        print(f"[main] страницата за затворена борса не се обнови: {type(e).__name__}: {e}")
    return {"date": today, "market_closed": True, "last_brief": last.stem}


def _reconcile_earnings_dates(week_calendar: dict | None, cards: list[dict]) -> None:
    """17.11.2026 (пакет 1, т. 8): календарът (Nasdaq) срещу картите (Yahoo) — при разминаване и двете дати, с етикет (card["earnings"]["date_conflict"]). Graceful."""
    try:
        from src import econ_calendar as _ec
        conf = _ec.reconcile_dates(week_calendar, {c["ticker"]: (c.get("earnings") or {}).get("next_earnings") for c in cards if (c.get("earnings") or {}).get("next_earnings")})
        for c in cards:
            if c.get("ticker") in conf:
                c.setdefault("earnings", {})["date_conflict"] = conf[c["ticker"]]
                print(f"[calendar] {c['ticker']}: {conf[c['ticker']]}")
    except Exception as e:
        print(f"[calendar] сверката на датите на отчетите пропусната: {type(e).__name__}: {e}")


def _display_names() -> dict:
    """16.11.2026 (пакет 16.11, т. 14): имената за „R · Ryder“ навсякъде с тикър — таблиците на Wikipedia + имената на наблюдаваните. Graceful: провал → {}."""
    try:
        out = dict(screener.LAST_UNIVERSE_NAME)
        if config.ENABLE_WATCH_MONITOR:
            out.update({t: n for t, n in (watch_monitor.load_watch_names() or {}).items() if n and t not in out})
        return out
    except Exception as e:
        print(f"[names] {type(e).__name__}: {e}")
        return {}


def run() -> dict:
    today = dt.date.today().isoformat()
    print(f"═══ AI Инвестиционен Бриф · {today} ═══")
    if config.ENABLE_MARKET_CLOSED_SKIP and not setup_rules.is_session(dt.date.fromisoformat(today)):
        print(f"[main] NYSE е затворена днес ({today}) — брифът не върви: без AI, без имейл, без записи в книгите и състоянието")
        return _market_closed(today)
    steps.reset()                                                      # 20.10.2026 (етап 3б): обвивката на стъпките — ok / частично / провал / пропусната + банер (src/steps.py)

    # Кой Claude модел ползваме днес — ВЕДНЪЖ, преди всяка AI стъпка. Резултатът
    # се присвоява на config.CLAUDE_MODEL и се наследява от всички извиквания,
    # защото _call_claude чете конфигурацията при всяко извикване. Виж
    # model_selector.resolve_model() за escape hatch / probe / fallback реда.
    # FIX 2026-09-23: чисти записи за отрязвания и usage за ТОЗИ run.
    ai_brief.TRUNCATIONS.clear()
    ai_brief.FIELD_DROPS.clear()                                                 # 16.11.2026 (т. 3)
    ai_brief.FIELD_SUBS.clear()                                                  # 17.11.2026 (т. 3б)
    ai_brief.MIXED_DROPS.clear()                                                 # 17.11.2026 (т. 7)
    ai_brief.AI_USAGE.clear()
    model_info = {"model": config.CLAUDE_MODEL, "source": "static",
                  "rejected": None, "rejected_reason": "", "banner": {}}
    def _model():
        info = model_selector.resolve_model(today)
        config.CLAUDE_MODEL = info["model"]
        return info
    model_info = steps.step("model", _model, fallback=model_info, label="Изборът на Claude модел",
                            consequence=f"ползва се моделът по подразбиране {config.CLAUDE_MODEL}")

    # 16.10.2026: застоял дневен бар — в 6 от 60 брифа Yahoo нямаше бара за последната сесия в 07:30; изчакване и нов опит ПРЕДИ първото теглене (виж src/bar_freshness.py)
    steps.step("bar_freshness", lambda: bar_freshness.wait_for_fresh(dt.date.fromisoformat(today)), enabled=config.ENABLE_BAR_FRESHNESS,
               label="Проверката за свеж дневен бар", consequence="ако Yahoo не е обновил последната сесия, картите може да са върху стария бар без предупреждение")

    print("[1/7] Слой 1: макро контекст…")
    macro = collect_macro_layer()

    print("[2/7] Пазарен термометър…")
    # термометърът не бива да сваля целия бриф (класът KeyError при скрит индикатор в хистерезис) — Defensive по подразбиране, виж thermometer_unavailable
    thermo = steps.step("thermometer", lambda: build_thermometer(macro), on_fail=thermometer_unavailable, trace=True, label="Пазарният термометър",
                        consequence="режимът е Defensive по подразбиране, индикаторите не са изчислени")
    # Допълнение към пакет 2 (2026-10-05): distribution days (пазарно-глобален сигнал, SPY + QQQ) се смятат ТУК, преди
    # макро брифа и режимния gate на Action — червени → режимът е най-много Defensive (виж apply_distribution_cap).
    # Преди се смятаха по-надолу, само за информативна карта; сега се ползва същият резултат (един fetch).
    distribution_days = None
    if config.ENABLE_ENTRY_TIMING:
        distribution_days = steps.step("distribution_days", entry_timing.evaluate_distribution_days, fallback=None, label="Distribution days (SPY / QQQ)",
                                       consequence="броят и блокът на Offensive не са проверени днес (липсата не е нечервен ден)",
                                       failed_if=lambda v: "нито SPY, нито QQQ" if entry_timing.LAST_STATUS.get("status") == "failed" else None,
                                       partial=lambda v: (f"липсва {', '.join(entry_timing.LAST_STATUS.get('missing') or [])}", {}) if entry_timing.LAST_STATUS.get("status") == "partial" else None)
        thermo = steps.step("distribution_cap", lambda: apply_distribution_cap(thermo, distribution_days, history=lambda: entry_timing.distribution_history(config.DISTRIBUTION_SEED_SESSIONS)),
                            fallback=thermo, label="Ограничението на режима от distribution days",
                            consequence="режимът днес е без този блок; може да е по-висок, отколкото правилото позволява")
    # 17.11.2026 (пакет 3): ЕДНОТО пазарно правило (SPY над растяща 50DMA, няма override, distribution days не са червени) и несиметричният престой
    prev_for_regime = data_rhythm.previous_brief(today) or {}
    thermo = steps.step("market_rule", lambda: apply_market_rule(thermo, distribution_days, prev_for_regime.get("thermometer"), dt.date.fromisoformat(today),
                                                                  history=lambda: entry_timing.distribution_history(config.DISTRIBUTION_SEED_SESSIONS)),
                        fallback=thermo, label="Пазарното правило за режима", consequence="режимът днес е по правилото без престоя и без реда с условията")
    print(f"      Режим: {thermo['regime']} — {thermo['regime_reason']}")
    # 15.10.2026: "Запас до смяна на режима" от кода (карта на термометъра + макро промпт) — след distribution days, преди макро брифа
    thermo["regime_margin"] = regime_claims.margin(thermo, distribution_days, dict(entry_timing.LAST_STATUS))
    if thermo["regime_margin"]["text"]:
        print(f"      {thermo['regime_margin']['text']}")
    # 04.11.2026 (прегледът, т. 3): какво промени режима спрямо предишния бриф — от кода, само при смяна
    thermo["regime_change"] = regime_claims.regime_change(prev_for_regime.get("thermometer"), thermo, prev_for_regime.get("date"))
    if thermo["regime_change"]:
        print(f"      Какво промени режима: {thermo['regime_change']['text']}")

    print("[3/7] Слой 2: секторна ротация…")
    # FIX 2026-10-03 (пакет 2 т.6): паднал Yahoo не сваля run-а — sector_rotation() връща [] и записва причината
    # в sector_layer.LAST_STATUS; в брифа излиза предупреждение (data_warnings), а не тих празен резултат.
    def _rotation_failed(e):
        sector_layer.LAST_STATUS.clear()
        sector_layer.LAST_STATUS.update(ok=False, reason=f"{type(e).__name__}: {e}")
        return []
    _ss = sector_layer.LAST_STATUS
    rotation = steps.step("sector_rotation", sector_rotation, on_fail=_rotation_failed, trace=True, label="Секторната ротация",
                          consequence="секторната карта, водещите сектори и SECT✓ са празни днес",
                          failed_if=lambda v: (_ss.get("reason") or "Yahoo не върна данни") if not _ss.get("ok", True) else None,
                          partial=lambda v: (f"{_ss.get('etfs_ok')} от {_ss['etfs_total']} ETF-а", {}) if _ss.get("etfs_total") and (_ss.get("etfs_ok") or 0) < _ss["etfs_total"] else None)
    leaders = leading_sectors(rotation)

    # 09.11.2026 (спешна поправка, ROKU): приключилите сделки — ПРЕДИ скрийнинга, за да излязат от универса (build_universe), от лидерите на секторите и от картите.
    # ROKU: Fox приключи придобиването на 06.11 след затварянето, а брифът от 09.11 я даде като единствения „Купува се днес“ — маркерът изчезна при приключването, тикърът остана.
    deals = steps.step("deals_closed", lambda: spinoff_watch.refresh_deals(today, extra=backtest.live_deal_tickers() if config.ENABLE_BACKTEST else [],
                                                                                     name_lookup=lambda t: ai_brief._verified_company_name(t)["name"]), fallback={},
                       enabled=bool(config.ENABLE_SPINOFF_WATCH and config.ENABLE_MERGER_MARKER), label="Приключилите сделки (EDGAR и новините, преди скрийнинга)",
                       consequence="приключила сделка може да остане в универса, картите и книгите днес",
                       failed_if=lambda v: (v.get("error") or "EDGAR не отговори") if isinstance(v, dict) and v.get("ok") is False else None)

    print("[4/7] Слой 3: скрининг…")
    def _screen_failed(e):
        screener.LAST_STATUS.clear()
        screener.LAST_STATUS.update(ok=False, kind="crashed", reason=f"{type(e).__name__}: {e}")
        return []

    def _screen_partial(v):
        sc = screener.LAST_STATUS
        parts = ([f"{sc['batches_failed']} от {sc.get('batches')} партиди"] if sc.get("batches_failed") else []) \
            + ([f"{sc['no_bars_n']} тикъра без бар"] if (sc.get("no_bars_n") or 0) >= config.PARTIAL_DATA_WARN_SHARE * (sc.get("universe") or 0) > 0 else []) \
            + ([f"фундаменти: {', '.join(sc['fundamentals_unavailable'][:5])}"] if sc.get("fundamentals_unavailable") else [])
        return ("; ".join(parts), {}) if parts else None
    candidates = steps.step("screener", lambda: run_screen([s["sector"] for s in leaders], leaders=leaders), on_fail=_screen_failed, trace=True,
                            label="Скрийнърът", consequence="празните Action/Watchlist днес НЕ значат 'няма сетъпи'",
                            failed_if=lambda v: (screener.LAST_STATUS.get("reason") or screener.LAST_STATUS.get("kind")) if screener.LAST_STATUS.get("kind") in ("spy_failed", "no_history", "universe_empty") else None,
                            partial=_screen_partial)
    # 30.10.2026 (разходката, т. 7): секторната карта — таблица с 11-те секторни ETF-а по сила, лидерите им от универса (данните на скрийнинга току-що), подсекторите
    sector_board = steps.step("sector_board", lambda: sector_layer.sector_board(universe_sector=screener.LAST_UNIVERSE_SECTOR, trend=screener.LAST_TREND,
                                                                                ratings=screener.rs_ratings(screener.LAST_RS_SCORES), rotation=rotation), fallback={},      # 04.11.2026 (Н2): водещите по is_leader
                              label="Секторната карта", consequence="секторната карта липсва днес",
                              failed_if=lambda v: "Yahoo не върна цените на секторните ETF-и" if not v else None)

    print(f"[5/7] Обогатяване на {len(candidates)} кандидата…")
    candidates = enrich(candidates)
    # 13.10.2026: корпоративно действие с нецял коефициент (отделяне) в прозореца на скрийнъра (52 седмици) → кандидатът отпада ПРЕДИ AI синтеза и книгите (corp_actions.exclude)
    corp_actions.reset()
    candidates, corp_ex_screener = corp_actions.exclude(candidates, "screener", today)
    # 12.10.2026: ранната резолюция на книгите (виж FIX 2026-09-17 по-долу) е ПРЕДИ setup_rules.annotate — картата в Watchlist чете
    # състоянието на buy-stop книгата (live_buystop_by_ticker), а до 12.10 го четеше от диска преди резолюцията: EXPD беше "open, вход 09.10
    # по $194.59" в книгата и "чака buy-stop" на картата в същия бриф. Резолюцията чете само tracker-а и цените (без кандидатите) — нищо
    # между двете места не зависи от реда.
    if config.ENABLE_BACKTEST:
        # FIX 2026-10-03 (пакет 1, т.7): еднократен чист старт на Track Record-а — v1 записите се
        # архивират, отворените се затварят по последния Close ("v1_closed"). ПРЕДИ резолюцията
        # и преди каквото и да четe _live_positions() (OPEN✓/RE-ENTRY/COT гледат само v2).
        # Идемпотентно и graceful — провал оставя v1 до следващия run, без загуба на данни.
        tracker_switch.ensure_v2_methodology()
        # 10.11.2026: ПРЕДИ резолюцията — тя прескача приключилите тикъри (след делистването Yahoo връща орязана история); цената — от дневните бари до датата на приключването
        _closed_bt = spinoff_watch.closed_tickers()
        backtest.reopen_deal_records((deals or {}).get("reopened") or [])           # CART 09.11: затворена само по едно заглавие — връща се
        backtest.close_deal_records(_closed_bt, dt.date.fromisoformat(today), bars=backtest.daily_bars_for(backtest.live_closed_tickers(_closed_bt)))
        backtest.resolve_positions_only()
    # техническа класификация (потвърден пробив / buy-stop / extended) — ПРЕДИ AI
    # синтеза, за да я вижда и промптът; apply_hard_rules() я налага след него
    # 26.10.2026 (етап 4б, т. 1): цел на придобиване сред кандидатите — ПРЕДИ класификацията: такава карта е сделка (setup.kind "deal" — без buy-stop, план, Action и AI текст).
    # ROKU 21–26.10: маркерът беше на картата, а сетъпът — "confirmed", eligible, "купува се до $167.88"; от Action я спираше само моделът. Списъците с подавания се споделят с
    # проверката на картите по-долу (edgar_subs) — тегли се веднъж.
    edgar_subs: dict = {}

    def _merger_pre():
        ts = [c.get("ticker") for c in candidates if c.get("ticker")]
        spinoff_watch.check(ts, today, budget_sec=config.SPINOFF_BUDGET_SEC, merger_tickers=ts, subs=edgar_subs)
        return spinoff_watch.annotate_mergers([candidates])
    steps.step("merger_pre", _merger_pre, fallback=0, enabled=bool(config.ENABLE_SPINOFF_WATCH and config.ENABLE_MERGER_MARKER and candidates),
               label="Целите на придобиване сред кандидатите (EDGAR 8-K, преди класификацията)",
               consequence="цел на придобиване се класифицира по цената (маркерът идва по-късно, само върху картата)",
               failed_if=lambda v: (spinoff_watch.LAST_DIAG.get("error") or "EDGAR не отговори") if not spinoff_watch.LAST_DIAG.get("ok", True) else None)
    _closed_now = spinoff_watch.closed_tickers()                              # 09.11.2026 (ROKU): приключила сделка, засечена едва при кандидатите — вън
    if _closed_now and any(c.get("ticker") in _closed_now for c in candidates):
        print(f"[deal] вън от кандидатите (приключила сделка / делистване): {sorted(c['ticker'] for c in candidates if c.get('ticker') in _closed_now)}")
        candidates = [c for c in candidates if c.get("ticker") not in _closed_now]
    candidates = setup_rules.annotate(candidates, today, backtest.live_buystop_by_ticker())     # 1б (б): прозорецът на чакащия запис / състоянието на задействания, не нов от днес
    screener_universe = [{"ticker": c["ticker"], "sector": c.get("sector"),
                          "industry": c.get("industry")} for c in candidates]
    print("[6/7] AI синтез (Claude API)…")
    # FIX 2026-10-03 (пакет 2 т.4): значимите новини (RSS + nitter → Claude филтър) се подбират ПРЕДИ макро
    # брифа и му се подават с обяснението защо са значими — преди брифът се пишеше без тях, а NewsAPI
    # заглавията бяха празни във всичките 78 брифа. Graceful: провал на новините → празен списък.
    # 02.11.2026 (поправки след брифа, т. 4): прозорците на новините — от предишния бриф (07:30 Берлин в деня на последната сесия): понеделник 72 ч, след празник 48 ч,
    # иначе 24 ч; крипто — не по-малко от config.CRYPTO_NEWS_HOURS. До 02.11 — фиксирани 24 / 24 / 30 ч (в понеделник 02.11 разказът не видя петъка).
    news_since = sessions.news_window_start()
    news_hours, crypto_hours = sessions.news_window_hours(), sessions.news_window_hours(min_hours=config.CRYPTO_NEWS_HOURS)
    print(f"[news] прозорец за новините: от {news_since:%d.%m %H:%M} UTC — {news_hours:g} ч (крипто {crypto_hours:g} ч)")
    news = steps.step("news", lambda: news_aggregator.significant_news(since=news_since), fallback=[], enabled=config.ENABLE_NEWS, label="Значимите новини",
                      consequence="макро текстът, тезите и проверката на AI текста са без новинарски фон; това НЕ значи, че няма новини")
    # 22.10.2026 (етап 4): крипто секцията — Cointelegraph и от 29.10 CoinDesk (AI подбор, дословни заглавия), COIN / HOOD / CRCL / BLSH. 29.10.2026 (разходката, т. 5): ПРЕДИ
    # макро брифа — разказът за нощта я вижда (17.11.2026: без COT за Bitcoin — COT е махнат).
    crypto = steps.step("crypto", lambda: crypto_news.build(today, hours=crypto_hours), fallback={},
                        enabled=config.ENABLE_CRYPTO_SECTION, label="Крипто секцията", consequence="крипто новините и цените на COIN / HOOD липсват днес",
                        failed_if=lambda v: (v.get("reason") or "не се изпълни") if not v.get("ok") else None)
    # 06.11.2026 (пакет 05–06.11, т. 8): дневната промяна на 11-те сектора, SPY, RSP, Russell и Nasdaq и спадът от 52-седмичния връх — за разказа и проверката на думите му
    market_day = steps.step("market_day", lambda: sector_layer.market_day(sector_board), fallback={}, label="Денят на пазара за макро разказа",
                            consequence="разказът е без дневните промени и спада от върха; думите „корекция“ и „мечи пазар“ се проверяват само срещу процента в изречението")
    news_terms_fixed = ai_brief.check_news_why_terms(news, market_day)         # 06.11.2026 (т. 8): „защо“ на новините — преди разказа, който ги чете
    ai_macro = ai_brief.macro_and_sector_brief(macro, rotation, thermo, news=news, crypto=crypto, day=market_day)
    # 17.11.2026 (пакет 1, т. 2а — решение след стратегическия преглед): AI абзацът на картите („защо сега / бизнес / катализатори / рискове“) — махнат; редът
    # „Защо е тук“ е от кода (render.why_here — RS, RS линия, Stage 2, EPS, сектор). card["ai"] остава контейнер за класа от кода (apply_hard_rules).
    for c in candidates:
        c["ai"] = {}
        c["tier"] = setup_rules.canslim_tier(c)                     # 17.11.2026 (пакет 2, т. 1 — А5): „CANSLIM“ (C: EPS от отчета ≥ 25%) / „Тренд без ръст“
    # 17.11.2026 (пакет 1, т. 2д — решение след стратегическия преглед): COT (екстремумите, потвърждението от цената, всички 40 пазара) — махнат изцяло
    action, watchlist = apply_hard_rules(candidates, thermo["sizing_factor"], thermo["regime"])
    # FIX 2026-09-12 (findings log 04-11.09, т.2): code-enforced regime-gate
    # expiry — виж watchlist_expiry.py docstring за пълния rationale (преди:
    # чист AI prose, датата "измисляна" наново всеки ден).
    watchlist_before_expiry = list(watchlist)     # В2: buy-stop книгата се захранва ПРЕДИ изтичането (иначе изтичането решава кои кандидати се измерват)
    if config.REGIME_GATE_EXPIRY:                 # 31.10.2026 (т. 9–10): изключено — без отделно изтичане; „Дни“ в „На радара“ казва колко дълго стои
        watchlist = watchlist_expiry.apply_regime_gate_expiry(watchlist, thermo["regime"], today)
    # пакет 4б т.д: отчет в следващите ~20 сесии → предупреждение върху картата с датата и очакваното движение от опциите (само информация)
    def _earnings_warnings():
        n_warn = earnings_move.annotate(action + watchlist)
        print(f"      Предупреждения за отчет: {n_warn} ({sum(1 for c in action + watchlist if (c.get('earnings_warning') or {}).get('implied_move_pct') is not None)} с очаквано движение)")
    steps.step("earnings_warnings", _earnings_warnings, label="Предупрежденията за отчет (Action / Watchlist)",
               consequence="картите днес може да нямат ред за предстоящ отчет; провери датата сам")
    print(f"      Action: {[a['ticker'] for a in action]}")
    print(f"      Watchlist: {[w['ticker'] for w in watchlist]}")
    # 09.10: "Излязоха от вчера" — тикърите от Watchlist на предишния бриф, които днес ги няма, с причината от кода (само информация)
    wl_exits = watchlist_exits.run(today, action, watchlist, candidates, explain=screener.explain_exits,
                                   expired=watchlist_expiry.LAST_EXPIRED,       # В2: изтекъл прозорец → тази причина, не "извън 10-те карти"
                                   corp_excluded={e["ticker"]: e["text"] for e in corp_ex_screener})   # 13.10.2026: изключен заради корпоративно действие — тази причина
    print(f"      Излязоха от Watchlist ({wl_exits.get('from', 'няма предишен бриф')}): {[r['ticker'] for r in wl_exits.get('rows', [])]}")
    # 30.10.2026 (разходката, т. 9–10): „от колко дни е на радара“ — поредните брифове в Action / Watchlist (за реда в „На радара“; само показване)
    _days = watchlist_exits.radar_days([c["ticker"] for c in action + watchlist], today)
    for c in action + watchlist:
        if c["ticker"] in _days:
            c["radar_days"] = _days[c["ticker"]]
    # чисто информационен badge на картата — не пипа classification/plan/sizing,
    # screening и timing остават разделени, виж entry_timing.py docstring-а
    if config.ENABLE_ENTRY_TIMING:
        action = entry_timing.evaluate(action)
    # концепция 3 — distribution days: изчислени по-горе (след термометъра), за да ограничат режима
    # чисто информационен флаг — не променя избора на Action, виж correlation_check.py
    correlation_flags = (correlation_check.fetch_correlation_flags(action)
                         if config.ENABLE_CORRELATION_CHECK else [])

    # v2 · допълнителни dashboard данни (Секции 3.3, 3.4, 6) — кеширани за деня
    # 17.11.2026 (пакет 1, т. 2в): опционният стек (UOV✓, очакваното движение при отчет, OI снимката, записът на опциите) — махнат
    splits_month = splits_calendar.fetch_upcoming_splits() if config.ENABLE_SPLITS_CALENDAR else []
    # 17.11.2026 (пакет 1, т. 2г — решение след стратегическия преглед): 13F (Superinvestor) — махнат изцяло: секцията, редът в имейла, маркерът SI✓
    # пакет 4б т.в: списъкът "Insider Buying" (скенер на целия S&P500+NDX100) отпадна — маркерът INS✓ идва от enrich (кандидатите) и от позициите (по-долу);
    # статусът на тегленето за кандидатите се взима веднага след enrich, преди извикването за позициите да го презапише
    insider_status = dict(insider_buying.LAST_MARKER_STATUS) if config.ENABLE_INSIDER_BUYING else {}
    our_tickers = {c["ticker"] for c in action} | {c["ticker"] for c in watchlist}
    # GLB (Green Line Breakout) — независим механичен скрийнър, изцяло
    # извън CANSLIM/Weinstein pipeline-а (собствен universe fetch, виж
    # glb_screener.py docstring). Explicit try/except тук, въпреки че
    # screen() вече е graceful вътрешно (batch+per-ticker) — не искаме и
    # неочакван bug в нов модул да чупи целия дневен run.
    glb_wish_signals: list[dict] = []            # книгата "GLB — наш вариант (close)": свежите пробиви на последния цял бар (измерване, не препоръка)
    glb_wish_high_signals: list[dict] = []       # 21.10.2026: книгата "GLB по Уиш" (линия по месечния High) — същото
    def _glb_failed(e):
        glb_screener.LAST_STATUS = {"ok": False, "error": f"{type(e).__name__}: {e}"}      # С3: банер + ред в секцията вместо тишина
        return [], [], []
    _gs = lambda: glb_screener.LAST_STATUS or {}
    glb_candidates, glb_wish_signals, glb_wish_high_signals = steps.step(
        "glb", lambda: (glb_screener.screen(), list(glb_screener.LAST_WISH_SIGNALS), list(glb_screener.LAST_WISH_HIGH_SIGNALS)), fallback=([], glb_wish_signals, glb_wish_high_signals),
                                                  enabled=config.ENABLE_GLB_SCREENER, on_fail=_glb_failed, label="GLB скрийнърът",
                                                  consequence=f"празният списък и липсващите сигнали за книгата „{config.GLB_WISH_BOOK_NAME}“ днес НЕ значат, че няма пробиви",
                                                  failed_if=lambda v: (_gs().get("error") or "не се изпълни") if _gs().get("ok") is False else None,
                                                  partial=lambda v: (f"{_gs()['batches_failed']} от {_gs().get('batches')} партиди", {}) if _gs().get("batches_failed") else None)
    # 13.10.2026: GLB карта / сигнал на книгата "GLB по Уиш", чиято линия е от месец ПРЕДИ отделяне (нецял коефициент) → не се показва и не се записва (CTVA 13.10)
    glb_candidates, corp_ex_glb = corp_actions.exclude(glb_candidates, "glb", today)
    glb_wish_signals, corp_ex_gw = corp_actions.exclude(glb_wish_signals, "glb_wish", today)
    glb_wish_high_signals, corp_ex_gwh = corp_actions.exclude(glb_wish_high_signals, "glb_wish_high", today)
    for row in glb_candidates:
        row["in_screener"] = row["ticker"] in our_tickers

    # Qullamaggie breakout скенер (06.10.2026) — ОТДЕЛНА стратегия: механичен (без AI), собствено теглене на данни, независим от CANSLIM и GLB. Не е препоръка — измерване.
    # Explicit try/except, същият дух като GLB блока: неочакван провал не чупи брифа (празният списък се придружава от предупреждение в data_warnings).
    qm_rows, qm_diag, qm_cards, qm_ep_out = [], {}, [], {}
    corp_ex_qm: list[dict] = []
    qm_universe: list[str] = []
    # 20.10.2026 (етап 3б, обвивката — стъпка 2): универсът, скенерът и EP — в обвивката; статусът (qm_diag / qm_ep_out) е същият като досега, банерът — собственият (data_warnings)
    qm_universe = steps.step("qm_universe", lambda: screener.scan_universe(today), fallback=[], enabled=bool(config.ENABLE_QM or config.ENABLE_QM_EP), source="qm_breakout",
                             label="Универсът за Qullamaggie", consequence="без скан за пробив и без EP наблюдение днес")     # същият универс като скрийнъра; един път за скенера и за EP
    if steps.result("qm_universe").status == "failed":
        qm_diag = {"ok": False, "error": f"универсът не се зареди ({steps.result('qm_universe').error_type})"}
    qm = {"rows": qm_rows, "diag": qm_diag, "cards": qm_cards, "corp_ex": corp_ex_qm}       # частично изпълненото остава при провал по-късно в стъпката (както в try блока до 20.10)

    def _qm_scan():
        qm_rows, qm_diag = qm_breakout.scan(universe=qm_universe)
        qm.update(rows=qm_rows, diag=qm_diag)
        qm_rows, corp_ex_qm = corp_actions.exclude(qm_rows, "qm", today)      # 13.10.2026: отделяне в прозореца на 6-месечния ръст → не е кандидат (нито карта, нито запис)
        qm.update(rows=qm_rows, corp_ex=corp_ex_qm)
        qm_cards = qm_breakout.cards(qm_rows, name_lookup=lambda t: ai_brief._verified_company_name(t)["name"])
        qm.update(cards=qm_cards)

        def _qm_earnings():                                      # 08.10: предупреждение за отчет и върху QM картите (като Watchlist): дата + очаквано движение от опциите, ако тикърът е в следобедната снимка
            import yfinance as _yf
            d0 = dt.date.today()
            for c in qm_cards:
                c["earnings"] = {"next_earnings": earnings_move.next_earnings_date(c["ticker"], _yf, d0)}
            n_qm_warn = earnings_move.annotate(qm_cards, d0)
            print(f"      QM карти с отчет в следващите ~{config.EARNINGS_WARNING_SESSIONS} сесии: {n_qm_warn}")
        steps.step("earnings_warnings_qm", _qm_earnings, label="Предупрежденията за отчет върху картите по Kullamägi",
                   consequence="QM картите днес може да нямат ред за предстоящ отчет; провери датата сам")

    steps.step("qm_scan", _qm_scan, enabled=bool(config.ENABLE_QM and qm_universe), source="qm_breakout",
               on_fail=lambda e: qm.__setitem__("diag", {"ok": False, "error": f"{type(e).__name__}: {e}"}),
               partial=lambda _: (f"{qm['diag']['batches_failed']} от {qm['diag'].get('batches')} партиди не се изтеглиха", {}) if (qm["diag"] or {}).get("batches_failed") else None,
               label="Скенерът за пробиви по Kullamägi", consequence="празният списък НЕ значи, че няма кандидати за пробив днес")
    qm_rows, qm_diag, qm_cards, corp_ex_qm = qm["rows"], qm["diag"], qm["cards"], qm["corp_ex"]
    # 03.11.2026 (разходката, т. 11, 2): пазарът по правилото на Kullamägi — QQQ над / под SMA10 и SMA20 (последното затваряне); само информация, записва се в новите QM записи
    qm_market = steps.step("qm_market", qm_breakout.fetch_nasdaq_trend, fallback=None, enabled=bool(config.ENABLE_QM), source="qm_market",
                           failed_if=lambda v: "QQQ не се изтегли" if v is None else None,
                           label="Редът „Nasdaq спрямо 10/20 DMA“ в секцията по Kullamägi", consequence="редът липсва днес и новите QM записи са без него")
    qm_by_ticker = {r["ticker"]: r for r in qm_rows}
    attach_qm_markers(action + watchlist, qm_by_ticker)             # QM✓ върху нашите карти, ако са и кандидати за пробив
    # EP наблюдение (САМО информация, без Track Record): after-hours гапове ≥ 10% при "пренебрегване"; AI само класифицира катализатора от заглавията; дневник на AH гап срещу реалния гап
    qm_ep_out = steps.step("qm_ep", lambda: qm_ep.run(qm_universe, name_lookup=lambda t: ai_brief._verified_company_name(t)["name"]), fallback=qm_ep_out,
                           enabled=bool(config.ENABLE_QM_EP and qm_universe), source="qm_ep",
                           on_fail=lambda e: {"ok": False, "notes": [f"{type(e).__name__}: {e}"], "rows": []},
                           partial=lambda v: (f"{(v.get('diag') or {})['batches_failed']} партиди не се изтеглиха", {}) if (v.get("diag") or {}).get("batches_failed") else None,
                           label="EP наблюдението (after-hours гапове)", consequence="празният списък НЕ значи, че няма гапове след затваряне")

    # 17.11.2026 (пакет 1, т. 2е): short / Stage 4 скрийнърът (замразен от 19.10) — махнат с кода
    # 03.11.2026 (разходката, т. 17): бележките за обратен залог (cot_opposites) отпаднаха заедно с тикърите на COT тезите — нямат вход

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
    # 13.10.2026: предупреждение за ПРЕДСТОЯЩО отделяне от EDGAR 8-K (spinoff_watch) — само нашите тикъри (карти първо, после живите записи в книгите); преди книгите, защото
    # нов вход между датата на запис и разпределението не се записва (прозорците — от дневника data/spinoff_log.json, за да важат и за повторния ingest на snapshot-и)
    spinoff_active: dict = {}

    def _spinoff():
        nonlocal spinoff_active                                            # частично изпълненото (check преди провал в annotate) остава — както в try блока до 20.10
        card_tickers = [c.get("ticker") for grp in (action, watchlist, qm_cards, glb_candidates) for c in (grp or [])]
        live_t = backtest.live_tickers() if config.ENABLE_BACKTEST else []
        spinoff_active = spinoff_watch.check(card_tickers + live_t, today, budget_sec=config.SPINOFF_BUDGET_SEC,
                                             merger_tickers=card_tickers + live_t,     # 21.10.2026: цел на придобиване за картите; 26.10.2026 (етап 4б, т. 1): и за живите записи (етикет "deal")
                                             subs=edgar_subs)
        n_sp = spinoff_watch.annotate([action, watchlist, qm_cards, glb_candidates], spinoff_active)
        n_mg = spinoff_watch.annotate_mergers([action, watchlist, qm_cards, glb_candidates])     # само маркер — картата остава (решение на Венци, 21.10)
        backtest.SPINOFF_WINDOWS = spinoff_watch.windows()
        print(f"      Предстоящо отделяне (EDGAR 8-K): проверени {spinoff_watch.LAST_DIAG.get('checked', 0)} тикъра, нови 8-K прочетени {spinoff_watch.LAST_DIAG.get('fetched', 0)}, "
              f"активни {sorted(spinoff_active)}, карти с предупреждение {n_sp}; цели на придобиване {sorted(spinoff_watch.LAST_MERGERS)} (карти {n_mg})")
    _sd = spinoff_watch.LAST_DIAG
    steps.step("spinoff", _spinoff, on_fail=lambda e: _sd.update(ok=False, error=f"{type(e).__name__}: {e}"), label="Предупреждението за предстоящо отделяне (EDGAR 8-K)",
               consequence="липсата на предупреждение днес НЕ значи, че няма предстоящо отделяне",
               failed_if=lambda v: (_sd.get("error") or "EDGAR не отговори") if not _sd.get("ok", True) else None,
               partial=lambda v: (f"непроверени {len(_sd.get('unchecked') or []) + len(_sd.get('errors') or [])}", {}) if (_sd.get("unchecked") or _sd.get("errors")) else None)
    # 16.11.2026 (пакет 16.11, т. 15): купувач във висяща сделка (BKH купува NWE) — етикет, без изключване
    deal_buyers: dict = {}
    def _deal_buyers():
        nonlocal deal_buyers
        deal_buyers = spinoff_watch.buyer_marks(spinoff_watch.pending_tickers(), screener.LAST_UNIVERSE_NAME, sec_names.ticker_map())
        spinoff_watch.annotate_buyers([action, watchlist, qm_cards, glb_candidates, (qm_ep_out or {}).get("rows")], deal_buyers)
        return deal_buyers
    steps.step("deal_buyers", _deal_buyers, fallback={}, enabled=config.ENABLE_SPINOFF_WATCH, label="Етикетът „купувач в сделка“",
               consequence="етикетът „купувач в сделка“ липсва днес")

    # 16.11.2026 (пакет 16.11, т. 13): емисии на акции (EDGAR 424B* / S-1 / S-3) — картите, книгите, наблюдаваните; списъците от EDGAR — общите с отделянето (edgar_subs)
    offering_found: dict = {}
    def _offering():
        nonlocal offering_found
        from src import offering_watch
        card_t = [c.get("ticker") for grp in (action, watchlist, qm_cards, glb_candidates) for c in (grp or [])]
        live_t = backtest.live_tickers() if config.ENABLE_BACKTEST else []
        watch_t = watch_monitor.load_watch_list() if config.ENABLE_WATCH_MONITOR else []
        offering_found = offering_watch.check(card_t + live_t + watch_t, today, subs=edgar_subs)
        offering_watch.annotate([action, watchlist, qm_cards, glb_candidates], offering_found)
        return offering_found
    from src import offering_watch as _ow
    steps.step("offering", _offering, enabled=config.ENABLE_OFFERING_WATCH, label="Проверката за емисии на акции (EDGAR 424B / S-3)",
               consequence="липсата на ред днес НЕ значи, че няма емисия",
               failed_if=lambda v: (_ow.LAST_DIAG.get("error") or "EDGAR не отговори") if not _ow.LAST_DIAG.get("ok", True) else None,
               partial=lambda v: (f"непроверени {len(_ow.LAST_DIAG.get('unchecked') or []) + len(_ow.LAST_DIAG.get('errors') or [])}", {}) if (_ow.LAST_DIAG.get("unchecked") or _ow.LAST_DIAG.get("errors")) else None)
    if config.ENABLE_BACKTEST:
        backtest.update_backtest_tracker(action, today, watchlist_before_expiry, thermo.get("regime"), qm_cards, glb_wish_signals, glb_wish_high_signals,
                                         today_context={"nasdaq": qm_market, "hy_oas": backtest.entry_hy_oas(thermo)})     # 03.11.2026: + HY OAS в деня на входа (т. 5)     # пакет 1б: + buy-stop кандидатите; Qullamaggie: + qm_breakout кандидатите (отделни книги)
        backtest.apply_spinoff_notes(spinoff_active, dt.date.fromisoformat(today))      # 13.10.2026: само бележка върху живите записи; ръчният преглед — от деня на отделянето
        backtest.apply_deal_labels(spinoff_watch.LAST_MERGERS, dt.date.fromisoformat(today))   # 26.10.2026 (етап 4б, т. 1): етикет "deal" върху живите записи на цели на придобиване
        backtest.close_deal_records(spinoff_watch.closed_tickers(), dt.date.fromisoformat(today))     # 09.11.2026: и засечените при картите / живите записи
        backtest.qm_open_marks(qm_cards, today)                                         # 22.10.2026: QM карта с жив запис в книгата → „вече отворена“ (RVTY 22.10)
    # 26.10.2026 (етап 4б, т. 2): етикет „събитие/M&A“ (скок ≥ 8% при ≥ 3× обем + заглавие за продажба / придобиване) — преди обобщенията на книгите (с и без етикетираните)
    steps.step("event_labels", lambda: backtest.apply_event_labels(today, name_lookup=lambda t: ai_brief._verified_company_name(t)["name"]), fallback={},
               enabled=bool(config.ENABLE_BACKTEST and config.ENABLE_EVENT_LABEL), label="Етикетът „събитие/M&A“ върху записите в книгите",
               consequence="днешните нови записи не са проверени за скок с новина за сделка — статистиката „без тях“ може да ги съдържа",
               failed_if=lambda v: (v.get("reason") or "не се изпълни") if v.get("ok") is False else None)
    # 06.11.2026 (пакет 05–06.11, т. 4): етикет „преди реакцията на отчета“ — отчет след затварянето на сигналния ден (MNST 06.11); статистиката на книгите — с и без
    steps.step("pre_reaction_labels", lambda: backtest.apply_pre_reaction_labels(today), fallback={}, enabled=bool(config.ENABLE_BACKTEST),
               label="Етикетът „преди реакцията на отчета“ върху записите в книгите",
               consequence="новите записи не са проверени за отчет след затварянето — статистиката „без тях“ може да ги съдържа",
               failed_if=lambda v: (v.get("reason") or "не се изпълни") if v.get("ok") is False else None)
    backtest_summary = backtest.get_backtest_summary() if config.ENABLE_BACKTEST else {}
    def _book_buystop():                                                       # пакет 1б: отделната книга на buy-stop кандидатите (чисто локално четене)
        backtest_summary["buystop"] = backtest.get_buystop_summary()
        _annotate_screener_exits(backtest_summary["buystop"], {c.get("ticker") for c in candidates})      # защо жив запис е излязъл от скрийнъра
    _book_consequence = "секцията е празна днес; записите на диска са непокътнати"
    steps.step("book_buystop", _book_buystop, enabled=bool(config.ENABLE_BACKTEST and config.TRACK_BUYSTOP), label="Обобщението на книгата на buy-stop кандидатите",
               consequence=_book_consequence)
    def _book_qm():                                                            # Qullamaggie: отделната книга qm_breakout (чисто локално четене)
        backtest_summary["qm_breakout"] = backtest.get_qm_summary()
        earnings_move.book_marks((backtest_summary["qm_breakout"] or {}).get("live"), dt.date.fromisoformat(today),      # 26.10.2026 (етап 4б, т. 10): отворените позиции
                                 lookup=earnings_move.yahoo_lookup(dt.date.fromisoformat(today)))                       # с отчет в следващите сесии (CBOE, UTHR); не вдига
    steps.step("book_qm", _book_qm, enabled=bool(config.ENABLE_BACKTEST and config.TRACK_QM),
               label="Обобщението на книгата на пробивите по Kullamägi", consequence=_book_consequence)
    def _book_glb_wish():                                                      # "GLB — наш вариант (close)": отделната книга glb_wish (чисто локално четене)
        backtest_summary["glb_wish"] = backtest.get_glb_wish_summary()
    steps.step("book_glb_wish", _book_glb_wish, enabled=bool(config.ENABLE_BACKTEST and config.TRACK_GLB_WISH),
               label=f"Обобщението на книгата „{config.GLB_CLOSE_BOOK_NAME}“", consequence=_book_consequence)
    def _book_glb_wish_high():                                                 # 21.10.2026: "GLB по Уиш" — книгата glb_wish_high (линия по месечния High)
        backtest_summary["glb_wish_high"] = backtest.get_glb_wish_summary(backtest.CATEGORY_GLB_WISH_HIGH)
    steps.step("book_glb_wish_high", _book_glb_wish_high, enabled=bool(config.ENABLE_BACKTEST and config.TRACK_GLB_WISH_HIGH),
               label=f"Обобщението на книгата „{config.GLB_WISH_BOOK_NAME}“", consequence=_book_consequence)

    # FIX 2026-09-12 (findings log 04-11.09, т.3): GLB кандидатите нямаха
    # cross-reference срещу Track Record отворени позиции — потвърден gap
    # (FCFS едновременно GLB Classic кандидат И отворена позиция, всичките
    # 4 проверени дни, без никакъв визуален сигнал за конвергенцията/
    # дублирането). Mirror на in_screener badge механизма по-горе — трябва
    # да живее ТУК, след backtest_summary изчислението (open_positions не е
    # наличен по-рано, при самия GLB блок).
    ins_pos_status: dict = {}
    pos_rows = (backtest_summary.get("open_positions", []) + backtest_summary.get("pending_positions", [])
                + (backtest_summary.get("buystop") or {}).get("live", []))
    ins_pos_status = steps.step("ins_positions", lambda: attach_position_insider(pos_rows), fallback=ins_pos_status, enabled=bool(config.ENABLE_INSIDER_BUYING and pos_rows),
                                source="insider", on_fail=lambda e: {"kind": "failed", "note": f"проверката не се изпълни ({type(e).__name__})"},      # 19.10.2026 (т. 12): видимо, не тихо {}
                                partial=lambda v: (v.get("note") or "частично", {}) if (v or {}).get("kind") == "ok_partial" else None,
                                label="INS✓ върху позициите в книгите", consequence="липсата на маркер днес не значи, че няма insider покупки")
    steps.step("qm_positions", lambda: attach_qm_markers(pos_rows, qm_by_ticker), enabled=bool(qm_by_ticker and pos_rows),       # QM✓ и върху позициите (v2 отворени/чакащи и buy-stop книгата)
               label="QM✓ върху позициите в книгите", consequence="липсата на маркер днес не значи, че тикърът не е кандидат за пробив")
    open_position_tickers = {p["ticker"] for p in backtest_summary.get("open_positions", [])}
    for row in glb_candidates:
        row["already_open_position"] = row["ticker"] in open_position_tickers


    # 🔎 Наблюдавани тикъри — ръчно куриран per-ticker монитор (watch_monitor.py).
    # ТУК, а не по-рано: `leaders` вече са готови и се подават като market_context — reuse на вече
    # наличното в паметта, не нов източник (17.11.2026: без COT пазарите — COT е махнат).
    #
    # "Нищо не се е случило" е CODE-ENFORCED: тих тикър (нула новини, нула
    # Form 4) изобщо не стига до AI-то — кодът му слага текста сам. Така
    # изричното "нищо" е гарантирано, не зависи от това дали моделът ще се
    # сети да го каже, и не се плащат токени за празен вход.
    def _watch():
        rows = watch_monitor.collect(window_hours=news_hours)                # 02.11.2026: от предишния бриф
        # 29.10.2026 (разходката, т. 6): маркер, ако тикърът е и в наш скрийнър / книга (Action, Watchlist, QM, GLB, EP, отворените записи в книгите)
        watch_monitor.attach_markers(rows, {"Action": action, "Watchlist": watchlist, "QM": qm_cards, "GLB": glb_candidates, "EP": (qm_ep_out or {}).get("rows")},
                                     books=config.ENABLE_BACKTEST)
        active = [r for r in rows if r.get("event")]                    # 03.11.2026 (т. 5): AI само при новина или нов Form 4 (подаден от предишния бриф)
        if active:
            market_context = {
                "leading_sectors": [s["sector"] for s in leaders],
            }
            active = ai_brief.watch_ticker_digest(active, market_context, window_hours=news_hours)
        by_ticker = {r["ticker"]: r for r in active}
        return [by_ticker.get(r["ticker"], {**r, "ai": {}}) for r in rows]
    watch_rows = steps.step("watch", _watch, fallback=[], enabled=config.ENABLE_WATCH_MONITOR, label="Секцията „Наблюдавани тикъри“",
                            consequence="секцията е празна днес; това НЕ значи, че при тикърите няма новини",     # 03.11.2026: без .info → без следата за нея
                            partial=lambda v: (watch_monitor.status_note(), {}) if watch_monitor.status_note() else None)   # 04.11.2026 (В1): новини / цени / Form 4, които не се провериха
    # 03.11.2026 (поправки след брифа, т. 6): редът „Form 4: … покупки ≥ $100 000“ — и за наблюдаваните (същите правила като за картите и позициите)
    def _ins_watch():
        groups, st = insider_buying.insider_for([r["ticker"] for r in watch_rows])
        for r in watch_rows:                                         # INS✓ и на реда на наблюдавания (както на картите)
            if r["ticker"] in groups:
                r.setdefault("in_brief", []).append("INS✓")
        return {**st, "tickers_found": sorted(groups)}
    ins_watch_status = steps.step("ins_watch", _ins_watch, fallback={},
                                  enabled=bool(config.ENABLE_INSIDER_BUYING and watch_rows), source="insider",
                                  on_fail=lambda e: {"kind": "failed", "note": f"проверката не се изпълни ({type(e).__name__})"},
                                  label="Form 4 покупките за наблюдаваните", consequence="редът „Form 4“ днес не казва нищо за наблюдаваните")

    # FIX 2026-09-27: пълен отчет за сплитовете — секцията вече не се скрива
    # (ok / empty с фуния по филтри / source_failed), + сплитове на отворени
    # позиции и наблюдавани в целия хоризонт на източника, без филтри. ТУК,
    # след update_backtest_tracker(): днешните нови позиции вече са в tracker-а.
    splits_rep = steps.step("splits_report", lambda: splits_calendar.splits_report(
                                positions=set(_live_positions()) if config.ENABLE_BACKTEST else set(),
                                watched=set(watch_monitor.load_watch_list()) if config.ENABLE_WATCH_MONITOR else set()),
                            enabled=config.ENABLE_SPLITS_CALENDAR, label="Отчетът за сплитовете", consequence="секцията за сплитове е без отчет днес")

    # 16.11.2026 (пакет 16.11, т. 8): календарът на седмицата — отчетите на компаниите > 2% в S&P 500 и на нашите (карти, книги, наблюдавани), Fed, основните данни с консенсуса
    def _week_calendar():
        from src import econ_calendar, preopen as _po
        w = _po.fetch_weights(today)
        big = {c["ticker"]: f"тегло {c['weight']:.1f}% в S&P 500" for c in (w.get("companies") or [])}
        ours = {}
        for label, grp in (("CANSLIM", action), ("CANSLIM", watchlist), ("Kullamägi", qm_cards), ("GLB", glb_candidates), ("EP", (qm_ep_out or {}).get("rows"))):
            for c in grp or []:
                if c.get("ticker"):
                    ours.setdefault(c["ticker"], f"карта {label}")
        if config.ENABLE_BACKTEST:
            for rec in backtest.book_records(None, statuses=("pending", "open", "trailing")):
                if rec.get("ticker"):
                    ours.setdefault(rec["ticker"], "в книгите")
        for t in (watch_monitor.load_watch_list() if config.ENABLE_WATCH_MONITOR else []):
            ours.setdefault(t, "наблюдаван")
        out = econ_calendar.build_week(dt.date.fromisoformat(today), big, ours)
        out["weights_note"] = (f"теглата — {w.get('source')}, към {w['as_of'][8:10]}.{w['as_of'][5:7]}" if w.get("as_of") else None) if w.get("companies") else f"теглата не се изтеглиха ({w.get('error')})"
        return out
    week_calendar = steps.step("week_calendar", _week_calendar, fallback={"ok": False, "errors": ["стъпката пропадна"], "days": []}, enabled=config.ENABLE_WEEK_CALENDAR,
                               label="Календарът на седмицата (Nasdaq)", consequence="календарът на седмицата липсва днес — червен ред на страницата")
    _reconcile_earnings_dates(week_calendar, action + watchlist + (qm_cards or []))      # 17.11.2026 (пакет 1, т. 8): една дата на отчета за страницата
    # 17.11.2026 (пакет 2, т. 2 — А4): „Чака пробив“ → аларма с обем (нужният обем по часове по собствения профил на акцията; иначе по общия, с етикет)
    def _volume_alarm():
        from src import volume_alarm
        waiting_t = [c["ticker"] for c in watchlist if (c.get("setup") or {}).get("kind") == "below_pivot" and (c.get("setup") or {}).get("buy_stop")
                     and not (c.get("setup") or {}).get("triggered")]
        return volume_alarm.annotate(watchlist, volume_alarm.fetch_profiles(waiting_t))
    steps.step("volume_alarm", _volume_alarm, fallback=0, label="Алармата с обем на „Чака пробив“", consequence="картите „Чака пробив“ са без нужния обем по часове днес")

    # 09.10: маркер "корпоративно действие" (отделяне / нецял сплит коефициент в последните ~60 сесии) върху Action, Watchlist, GLB и QM картите — само информация (виж corp_actions.py)
    # 13.10.2026: изключване вместо маркер (решението от 09.10 отпада) — изключените са по-горе (скрийнър, GLB, "GLB по Уиш", QM); тук само диагностиката и редовете под секциите
    corp_diag = dict(corp_actions.LAST_DIAG)
    # 13.10.2026 (праг на същественост): събитие с нецял коефициент ПОД config.CORP_ACTION_MATERIAL_RATIO не изключва — картата остава с маркера от 09.10 (последните 60 сесии)
    corp_marker = corp_actions.annotate([action, watchlist, glb_candidates, qm_cards], today)
    corp_diag.update(flagged=corp_marker.get("flagged", []), ok=bool(corp_diag.get("ok", True) and corp_marker.get("ok", True)),
                     error=corp_diag.get("error") or corp_marker.get("error"))
    _gx = corp_ex_glb + [e for e in corp_ex_gw if e["ticker"] not in {x["ticker"] for x in corp_ex_glb}]
    corp_excluded = {"screener": corp_ex_screener, "glb": _gx + [e for e in corp_ex_gwh if e["ticker"] not in {x["ticker"] for x in _gx}], "qm": corp_ex_qm}
    print(f"      Корпоративни действия: проверени {corp_diag.get('checked', 0)} тикъра, изключени {[(e['ticker'], e['module']) for e in corp_diag.get('excluded', [])]}, "
          f"маркирани (под прага) {[f['ticker'] for f in corp_diag.get('flagged', [])]}"
          + ("" if corp_diag.get("ok", True) else f" — ПРОВАЛ: {corp_diag.get('error')}"))

    # С5 (втори преглед, 10.10.2026): канарче за split корекцията на Yahoo — една заявка; провал на тегленето → неизвестно, без банер
    canary = data_canary.check() if config.ENABLE_DATA_CANARY else None
    # Здравен монитор (втори преглед, 10.10.2026): очакваните артефакти — OI снимка, предишен бриф, книги, GLB състояние, дневни кешове
    def _health():
        if config.ENABLE_BAR_FRESHNESS and screener.LAST_BAR_DATES:       # 16.10.2026: делът на универса със стар бар + засегнатите карти
            bar_freshness.universe(screener.LAST_BAR_DATES, [c.get("ticker") for grp in (action, watchlist, qm_cards, glb_candidates) for c in (grp or [])], dt.date.fromisoformat(today))
        health = health_monitor.check(today, resolution=backtest.LAST_RESOLUTION, glb_status=glb_screener.LAST_STATUS if config.ENABLE_GLB_SCREENER else None,
                                      freshness=dict(bar_freshness.LAST_DIAG) if config.ENABLE_BAR_FRESHNESS else None)
        print(f"[health] {len(health)} проблема" + (": " + " | ".join(h["check"] for h in health) if health else " — всичко очаквано е налице"))
        return health
    # 19.10.2026 (т. 12): паднал монитор не е "всичко е наред" — ред в банера (source "health:health_monitor")
    health = steps.step("health", _health, source="health:health_monitor", label="Здравният монитор", consequence="липсата на други редове днес НЕ значи, че всичко очаквано е налице",
                        on_fail=lambda e: [{"check": "health_monitor", "message": f"мониторът не се изпълни ({type(e).__name__}: {e}) — липсата на други редове тук днес НЕ значи, че всичко очаквано е налице."}])
    if canary:
        print(f"[canary] {canary['ticker']} {canary['date']}: close {canary['close']} (очаквано ≈{canary['expected']}) → "
              f"{'OK' if canary['ok'] else 'ГРЕШНО' if canary['ok'] is False else 'неизвестно: ' + str(canary['error'])}")
    data_warns = data_warnings.collect(sector_layer.LAST_STATUS, screener.LAST_STATUS, rotation_count=len(rotation),
                                       insider_status=insider_status, qm_diag=qm_diag, qm_ep=qm_ep_out,
                                       corp_diag=corp_diag, spinoff_diag=dict(spinoff_watch.LAST_DIAG),
                                       dd_status=dict(entry_timing.LAST_STATUS) if config.ENABLE_ENTRY_TIMING else None,
                                       glb_status=(glb_screener.LAST_STATUS if config.ENABLE_GLB_SCREENER else None),
                                       canary=canary, health=health,
                                       ins_pos_status=ins_pos_status,                                     # 19.10.2026 (т. 12): INS✓ за позициите
                                       news_status=dict(news_aggregator.LAST_STATUS) if config.ENABLE_NEWS else None,
                                       fred_key_missing=not config.FRED_API_KEY, universe_sources=dict(screener.LAST_UNIVERSE_SOURCES),   # 30.10.2026: Nasdaq-100 липсваше тихо от 10.07
                                       breadth=next((i for i in thermo.get("indicators") or [] if str(i.get("name", "")).startswith("Market Breadth")), None))   # 20.10.2026: частичен провал
    data_warns += steps.warnings({w.get("source") for w in data_warns})          # 20.10.2026 (етап 3б): провалена стъпка без собствен банер → един ред
    print(steps.log_line())
    brief = {
        "date": today,
        "macro": macro,
        "thermometer": thermo,
        "rotation": rotation,
        "market_day": market_day,                                       # 06.11.2026 (т. 8)
        "deals_closed": [r for r in spinoff_watch.closed_tickers().values() if (r.get("date") or "") >= (dt.date.fromisoformat(today) - dt.timedelta(days=10)).isoformat()],     # 09.11.2026 (ROKU)
        "deals_pending_scan": [{"ticker": t, "buyer": v.get("buyer"), "announced": v.get("announced")} for t, v in sorted(screener.LAST_SCAN_EXCLUDED.items())],   # 11.11.2026 (т. 1)
        "universe_day": dict(screener.LAST_DAY_UNIVERSE),               # 11.11.2026 (т. 2): универсът за деня (записан / построен)
        "news_terms_fixed": news_terms_fixed,                           # 06.11.2026 (т. 8): какво е махнато от „защо“ на новините
        "sector_board": sector_board,                                   # 30.10.2026 (разходката, т. 7): секторната карта от кода (до 30.10 — "sector_card": водещите по кода, веригите — от модела)
        # пакет 2 т.6: паднал Yahoo / празен универс — празният резултат не бива да се чете като "няма сетъпи"
        "data_warnings": data_warns,
        "universe_sources": dict(screener.LAST_UNIVERSE_SOURCES),       # 30.10.2026: тикъри по източник на универса (S&P 500 / Nasdaq-100 / S&P 400) — до 30.10 липсата на Nasdaq-100 не се виждаше
        "run_steps": steps.summary(),                                    # 20.10.2026 (етап 3б): ok / частично / провал / пропусната за всяка стъпка в обвивката
        "health": health,                                                # здравният монитор (10.10)
        "screener_status": dict(screener.LAST_STATUS),                  # 19.10.2026 (т. 12): с история / универс / партиди — нормата за прага на банера
        "news_diag": dict(news_aggregator.LAST_DIAG) if config.ENABLE_NEWS else None,     # 29.10.2026: какво махнаха проверките на новините (празното "защо" на 29.10 не се виждаше)
        "market_calendar_note": setup_rules.market_calendar_note(dt.date.fromisoformat(today)),     # 16.10.2026 (В2б): утре / в понеделник NYSE не работи или затваря рано
        "bar_freshness": dict(bar_freshness.LAST_DIAG),                 # 16.10.2026: застоял дневен бар (изчакване, дял на универса, засегнати карти)
        "data_canary": canary,                                           # С5: split корекцията на Yahoo (NVDA 07.06.2024)
        "glb_status": dict(glb_screener.LAST_STATUS) if config.ENABLE_GLB_SCREENER else None,     # С3: изпълнен ли е, колко партиди/тикъра
        "corp_actions": corp_diag,
        "corp_excluded": corp_excluded,
        "spinoff": {**spinoff_watch.LAST_DIAG, "skipped_entries": list(backtest.LAST_SPINOFF_SKIPS)},     # 13.10.2026: предстоящо отделяне (EDGAR 8-K) + пропуснатите нови записи в книгите
        "ai_macro": ai_macro,
        "model_info": model_info,
        # FIX 2026-09-23: видимо предупреждение за отрязани AI отговори +
        # usage по извикване (единственият достъпен източник на реални token
        # числа — Actions логът иска автентикация)
        "ai_truncations": list(ai_brief.TRUNCATIONS),
        "ai_field_drops": list(ai_brief.FIELD_DROPS),                    # 16.11.2026 (т. 3): махнатите изречения с имена на полета
        "ai_field_subs": list(ai_brief.FIELD_SUBS),                      # 17.11.2026 (т. 3б): познатите имена на полета — подменени с български термин
        "ai_mixed_drops": list(ai_brief.MIXED_DROPS),                    # 17.11.2026 (т. 7): изречения с дума от смесени букви, която не се поправя
        "ai_usage": list(ai_brief.AI_USAGE),
        "watch": watch_rows,
        "watch_status": dict(watch_monitor.LAST_STATUS),                 # 04.11.2026 (В1): какво не се провери при наблюдаваните (брояч и причина)
        "action": action,
        "watchlist": watchlist,
        "watchlist_exits": wl_exits,
        "splits": splits_month,
        "week_calendar": week_calendar if config.ENABLE_WEEK_CALENDAR else None,     # 16.11.2026 (т. 8)
        "offering_warnings": {t: h["text"] for t, h in (offering_found or {}).items()},   # 16.11.2026 (т. 13): емисии на акции — по тикър (книгите и наблюдаваните на страницата)
        "names": _display_names(),                                       # 16.11.2026 (т. 14): тикър → името на компанията (Wikipedia; наблюдаваните — техните имена)
        "deal_buyers": {t: v["text"] for t, v in (deal_buyers or {}).items()},   # 16.11.2026 (т. 15): купувач във висяща сделка — радарът, наблюдаваните
        "splits_report": splits_rep,
        # пакет 4б т.в: статус на тегленето на Form 4 за кандидатите/позициите (kind: ok|ok_partial|legit_zero|failed; stale/data_date от 4а)
        "insider_buying_status": insider_status,
        "insider_buying_positions_status": ins_pos_status,
        "insider_buying_watch_status": ins_watch_status,              # 03.11.2026 (т. 6): Form 4 покупките за наблюдаваните
        "glb_candidates": glb_candidates,
        "glb_wish": glb_wish_signals,        # свежите пробиви за книгата "GLB по Уиш" — snapshot-ът ги пази, за да се възстанови пропуснат run
        "glb_wish_high": glb_wish_high_signals,   # 21.10.2026: същото за книгата "GLB по Уиш" по неговата линия (месечен High)
        # Qullamaggie (отделна стратегия — измерване, не препоръка): до 8 карти за пробив + диагностика на скана
        "qm_breakout": qm_cards,
        "qm_diag": qm_diag,
        "qm_market": qm_market,                                        # 03.11.2026 (т. 11, 2): QQQ спрямо SMA10 / SMA20
        "qm_ep": qm_ep_out,
        "news": news,
        "news_window": {**dict(news_aggregator.LAST_WINDOW), "since": news_since.isoformat(), "hours": news_hours, "crypto_hours": crypto_hours},   # 02.11.2026 (т. 4)
        "crypto": crypto,                                              # 22.10.2026 (етап 4): крипто секцията   # 21.10 (етап 4): цялата секция само в първия бриф след нов отчет
        "correlation_flags": correlation_flags,
        "distribution_days": distribution_days,
        "distribution_days_status": dict(entry_timing.LAST_STATUS) if config.ENABLE_ENTRY_TIMING else None,     # 16.10.2026 (В8): ok / partial / failed
        "backtest": backtest_summary,
    }

    # 04.11.2026 (четвърти преглед, Н7): повторен сутрешен бриф СЛЕД обновяването преди отварянето (ръчно, в същия ден) пази карето — до 04.11 страницата се рендерираше без него,
    # макар data/preopen/<дата>.json да го имаше. В обичайния сутрешен run файлът за деня още не съществува.
    pre = preopen_today(today)
    if pre:
        brief["preopen"] = pre

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
    sent = send_once(email_html, subject, today)          # 19.10.2026 (т. 13): повторен run в същия ден не праща втори имейл
    if not sent["sent"] and not sent["skipped"]:
        # 19.10.2026 (т. 12): неуспешно изпращане — банер на днешната страница (тя е рендерирана преди изпращането) и в JSON-а на брифа
        try:
            brief["data_warnings"].append({"source": "email", "level": "warn",
                                           "message": "Имейл: брифът не беше изпратен днес (SMTP / SendGrid не прие — причината е в лога на run-а); страницата е актуална."})
            (config.DATA_DIR / f"{today}.json").write_text(json.dumps(brief, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            render_dashboard(brief)
        except Exception as e:
            print(f"[email] банерът за неизпратения имейл не се записа: {type(e).__name__}: {e}")

    print("═══ Готово ═══")
    return brief


if __name__ == "__main__":
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
