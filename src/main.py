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
from src.thermometer import build_thermometer
from src.sector_layer import sector_rotation, leading_sectors
from src.screener import run_screen
from src.enrich import enrich
from src.sizing import position_plan
from src import ai_brief
from src.render import render_dashboard, render_email
from src.emailer import send_brief


def apply_hard_rules(candidates: list[dict], sizing_factor: float) -> tuple[list, list]:
    """
    Твърдите правила от Секция 8, наложени СЛЕД AI класификацията —
    кодът има последната дума, не моделът.
    """
    action, watchlist = [], []
    sector_count: dict[str, int] = {}

    for c in candidates:
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

    print("[3/7] Слой 2: секторна ротация…")
    rotation = sector_rotation()
    leaders = leading_sectors(rotation)

    print("[4/7] Слой 3: скрининг…")
    candidates = run_screen([s["sector"] for s in leaders])

    print(f"[5/7] Обогатяване на {len(candidates)} кандидата…")
    candidates = enrich(candidates)

    print("[6/7] AI синтез (Claude API)…")
    ai_macro = ai_brief.macro_and_sector_brief(macro, rotation, thermo)
    narratives = ai_brief.ticker_narratives(
        candidates, ai_macro.get("sector_logic", []), thermo["regime"])
    candidates = ai_brief.merge_narratives(candidates, narratives)

    action, watchlist = apply_hard_rules(candidates, thermo["sizing_factor"])
    print(f"      Action: {[a['ticker'] for a in action]}")
    print(f"      Watchlist: {[w['ticker'] for w in watchlist]}")

    brief = {
        "date": today,
        "macro": macro,
        "thermometer": thermo,
        "rotation": rotation,
        "ai_macro": ai_macro,
        "action": action,
        "watchlist": watchlist,
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
