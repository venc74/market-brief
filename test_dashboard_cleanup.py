"""
Пакет 4а (2026-10-03): махане на мъртво/ненадеждно съдържание от dashboard-а — проверки върху РЕАЛНИЯ
шаблон с СИНТЕТИЧЕН вход (мок кандидат, мок режим).
  т.3 — widget-ът "Borrow Rate · търсене на тикър" (CORS proxy) е махнат; Borrow редът върху картите остава.
Пускане: python test_dashboard_cleanup.py
"""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import render, thermometer


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
    # Borrow данните върху картите остават
    card = action_card(short_view={"interpretation": "Нисък short interest", "borrow": "Borrow 0.8% — евтино за шортиране"})
    html = render_brief(action=[card])
    assert '<div class="borrow"><b>Borrow:</b> Borrow 0.8% — евтино за шортиране</div>' in html
    print("  ✓ няма секция, поле за тикър, скрипт и CORS proxy (allorigins); реда 'Borrow:' върху картата остава")

    print()
    print("Всички тестове минаха.")
