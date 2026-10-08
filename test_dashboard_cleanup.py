"""
Пакет 4а (2026-10-03): махане на мъртво/ненадеждно съдържание от dashboard-а — проверки върху РЕАЛНИЯ
шаблон с СИНТЕТИЧЕН вход (мок кандидат, мок режим).
  т.3 — widget-ът "Borrow Rate · търсене на тикър" (CORS proxy) е махнат; Borrow редът върху картите остава.
  т.4 — опционният блок на картите е махнат от enrich, от AI payload-а и от шаблона (OI снимката за Unusual
        Options не е пипана).
Пускане: python test_dashboard_cleanup.py
"""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import render, thermometer, enrich, ai_brief, borrow_data


def render_brief(**over):
    brief = {"date": "2026-10-05", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")),
             "action": [], "watchlist": [],
             "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
    brief.update(over)
    with tempfile.TemporaryDirectory() as docs:
        orig = config.DOCS_DIR
        config.DOCS_DIR = pathlib.Path(docs)
        try:
            return render.render_dashboard(brief)
        finally:
            config.DOCS_DIR = orig


def action_card(**over):
    c = {"ticker": "ABCD", "company": "ABCD Corp", "sector": "Tech", "price": 100.0, "pivot": 99.0, "pct_from_pivot": 1.0,
         "base_type": "база 12% дълбочина", "base_depth_pct": 12.0, "weinstein_stage": 2, "rs_status": "new_high", "ma50": 90.0,
         "ma200": 80.0, "volume_ratio": 2.0, "breakout_volume": True, "eps_growth_yoy": 30, "revenue_growth_yoy": 25, "roe": 20,
         "inst_ownership_pct": 70, "earnings": {}, "options": {}, "short_view": {"interpretation": "тест"}, "markers": [],
         "ai": {"classification": "Action", "why_now": "тест", "catalysts": [], "risks": []},
         "plan": {"valid": True, "method": "v2", "buy_stop": 99.0, "max_chase": 103.95, "valid_through": "2026-10-09",
                  "window_sessions": 5, "stop_loss": 92.0, "stop_basis": "структурен", "risk_pct": 7.0, "max_risk_usd": 1000,
                  "sizing_factor": 1.0, "shares": 140, "total_investment": 14000, "pct_of_portfolio": 14.0, "target_1": 114.0,
                  "target_1_fraction": 0.5, "target_2": "тест", "time_horizon": "4–8 седмици", "entry_range": [99.0, 103.95],
                  "entry_mid": 100.0}}
    c.update(over)
    return c


if __name__ == "__main__":
    print("── т.3: widget-ът за търсене на Borrow Rate е махнат ──")
    html = render_brief()
    for gone in ("Borrow Rate · търсене на тикър", "borrow-input", "borrow-btn", "borrow-result", "allorigins", "iborrowdesk"):
        assert gone not in html, gone
    # Пакет 4б т.ж: редът "Borrow:" върху картите също е махнат (дори ако стар бриф още носи short_view.borrow)
    card = action_card(short_view={"interpretation": "Нисък short interest", "borrow": "Borrow 0.8% — евтино за шортиране"})
    html = render_brief(action=[card])
    assert "Borrow:" not in html and "Borrow 0.8%" not in html and "<h3>Short Interest</h3>" in html and "Нисък short interest" in html
    print("  ✓ няма секция, поле за тикър, скрипт и CORS proxy (allorigins); редът 'Borrow:' върху картата също е махнат (Short Interest интерпретацията остава)")

    print()
    print("── т.4: опционният блок на картите е махнат ──")
    html = render_brief(action=[action_card()])                       # картата няма "options" ключ изобщо
    for gone in ("<h3>Опции</h3>", "IV / IVR", "P/C ratio", "Стратегия"):
        assert gone not in html, gone
    assert "<h3>Short Interest</h3>" in html and "<h3>Техническа картина</h3>" in html     # съседните блокове са си на място
    assert not hasattr(enrich, "options_info") and not hasattr(config, "IV_HISTORY_FILE")
    # enrich() не вика опции и не слага "options" на реда
    enrich.earnings_info = lambda sym: {"next_earnings": None, "days_to_earnings": None, "in_blackout": False}
    enrich._build_crosscheck_sets = lambda tickers: {"mf": set(), "uov": {}, "splits": {}, "si": {}, "si_new": {}}
    borrow_data.borrow_info = lambda sym: (_ for _ in ()).throw(AssertionError("borrow не се тегли за кандидатите (пакет 4б т.ж)"))
    row = {"ticker": "ABCD", "price": 100.0}
    out = enrich.enrich([row])[0]
    assert "options" not in out and out["earnings"]["in_blackout"] is False and "short_view" in out and "borrow" not in out and "borrow" not in out["short_view"]
    # AI payload-ът не носи опции
    seen = []
    ai_brief._narratives_for_batch = lambda batch, sector_logic, regime, label: seen.extend(batch) or []
    ai_brief.ticker_narratives([{**row, "options": {"iv": 38.5, "iv_rank": 22.0, "strategy": "long call"}, "short_view": {}}], [], "Offensive")
    assert seen and all("options" not in s for s in seen)
    print("  ✓ картата няма 'Опции' (IV/IVR, P/C, Стратегия); enrich() не слага options; AI payload-ът ги няма; Short Interest и")
    print("    Техническа картина са на място; следобедната OI снимка (oi_snapshot.py/unusual_options.py) не е пипана")

    print()
    print("Всички тестове минаха.")
