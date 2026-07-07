"""
Тест на пълния pipeline с мок данни — без външни API-та.
Валидира: apply_hard_rules, position sizing, dashboard render, email render.
Пускане: python test_pipeline.py
"""
import sys, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src.main import apply_hard_rules
from src.render import render_dashboard, render_email

MOCK_THERMO = {
    "regime": "Offensive",
    "regime_reason": "5/8 индикатора зелени, нула червени",
    "sizing_factor": 1.0,
    "indicators": [
        {"name": "SPY тренд", "value": 612.4, "status": "green", "label": "SPY 612 | над 50DMA, над 200DMA"},
        {"name": "VIX", "value": 14.2, "status": "green", "label": "VIX 14.2 (risk-on)"},
        {"name": "NAAIM", "value": 78.0, "status": "yellow", "label": "NAAIM 78"},
        {"name": "Put/Call (SPY)", "value": 0.92, "status": "yellow", "label": "P/C 0.92"},
        {"name": "2Y/10Y спред", "value": 0.45, "status": "green", "label": "0.45% (нормален, steepening)"},
        {"name": "Fed Net Liquidity", "value": 6240.0, "status": "green", "label": "$6240 млрд (↑)"},
        {"name": "MOVE (Bond Vol)", "value": 82.0, "status": "green", "label": "MOVE 82 (-3/седмица)"},
        {"name": "VIX Term Structure", "value": 0.757, "status": "green",
         "label": "VIX9D 12.8 / VIX 14.2 / VIX3M 16.9 → ratio 0.76 (contango, нормално)"},
    ],
}

MOCK_AI_MACRO = {
    "macro_brief": ("Fed задържа лихвите, но dot plot показа две намаления до края на годината — "
                    "пазарът цени първото за септември. DXY отслабна 1.2% за седмицата, което е "
                    "директен tailwind за суровини и emerging markets. Петролът се стабилизира над $78 "
                    "след новите танкерни ограничения в Червено море. Net Liquidity расте трета поредна "
                    "седмица — исторически това е средата, в която breakout-ите работят."),
    "regime_comment": "Offensive е оправдан: ликвидността расте, VIX е под 15, RS лидерството е ясно.",
    "sector_logic": [
        {"sector": "Полупроводници", "etf": "SMH",
         "chain": "AI capex цикълът се разширява от hyperscalers към суверенни AI проекти → поръчки за advanced packaging → SMH RS на нов 6-месечен връх.",
         "horizon_weeks": "4-6"},
        {"sector": "Енергетика", "etf": "XLE",
         "chain": "Танкерни ограничения в Червено море → по-дълги маршрути → по-висок freight + premium за физически барел → рафинерии и E&P с margin expansion.",
         "horizon_weeks": "2-4"},
    ],
}

def mock_stock(ticker, sector, cls, **over):
    base = {
        "ticker": ticker, "company": f"{ticker} Corp", "sector": sector,
        "industry": "Semiconductors", "price": 142.30, "pivot": 145.00,
        "pct_from_pivot": -1.86, "base_type": "flat base", "base_depth_pct": 11.2,
        "weinstein_stage": 2, "rs_status": "new_high",
        "ma50": 134.20, "ma200": 118.50, "base_low": 128.80,
        "avg_volume_50d": 4_200_000, "volume_ratio": 1.8, "breakout_volume": True,
        "eps_growth_yoy": 41.0, "revenue_growth_yoy": 28.5, "roe": 24.3,
        "pe": 31.2, "forward_pe": 24.8, "inst_ownership_pct": 82.4,
        "earnings": {"next_earnings": "2026-07-28", "days_to_earnings": 46,
                     "in_blackout": False, "eps_estimate": 1.42},
        "options": {"iv": 38.5, "iv_rank": 22.0, "iv_rank_quality": "partial (14 дни история)",
                    "put_call_ratio": 0.64,
                    "strategy": "long call / bull call spread",
                    "strategy_reason": "IVR 22 е нисък — premium-ът е евтин, опциите дават по-добър leverage."},
        "short_view": {"short_pct_float": 4.2, "days_to_cover": 2.1,
                       "interpretation": "Нисък short interest (4.2%) — без squeeze динамика, но и без активна опозиция."},
        "ai": {"classification": cls,
               "why_now": "AI capex верига → advanced packaging поръчки → тази компания е с 60% пазарен дял в нишата. RS Line на нов връх потвърждава институционално акумулиране.",
               "business_bg": "Производител на тестово оборудване за полупроводници. Доминира нишата на high-bandwidth memory тестване.",
               "catalysts": ["Earnings 28 юли — guidance ревизия нагоре е вероятна",
                             "Нов контракт със суверенен AI проект (слухове, потвърждение до 4 седмици)"],
               "risks": ["Export ограничения към Китай — 18% от приходите",
                         "Extended пазар: пробив без обем би бил fakeout"],
               "earnings_call": "преди earnings — 46 дни буфер е достатъчен",
               "watchlist_trigger": "Пробив над $145 с 1.5x обем"},
    }
    base.update(over)
    return base

candidates = [
    mock_stock("AVGT", "Technology", "Action"),
    mock_stock("ENRX", "Energy", "Action", price=58.20, pivot=59.00, pct_from_pivot=-1.36,
               base_type="cup with handle", base_low=49.10, ma50=54.30, ma200=47.80),
    mock_stock("TECB", "Technology", "Action", price=88.00, pivot=89.50, base_low=78.40, ma50=83.10, ma200=72.00),
    mock_stock("TECC", "Technology", "Action", price=31.00, pivot=31.80, base_low=27.50, ma50=29.40, ma200=25.10),  # 3-ти tech → правилото го реже
    mock_stock("WTCH", "Healthcare", "Watchlist", price=72.10, pivot=76.00, pct_from_pivot=-5.1),
]

action, watchlist = apply_hard_rules(candidates, sizing_factor=1.0)
assert len([a for a in action if a["sector"] == "Technology"]) <= 2, "MAX_PER_SECTOR нарушен!"
assert all("plan" in a and a["plan"]["valid"] for a in action), "Action без валиден план!"
print(f"✓ Hard rules: Action={[a['ticker'] for a in action]}, "
      f"Watchlist={[w['ticker'] for w in watchlist]}")

brief = {"date": "2026-06-12", "thermometer": MOCK_THERMO, "ai_macro": MOCK_AI_MACRO,
         "action": action, "watchlist": watchlist, "macro": {}, "rotation": []}

html = render_dashboard(brief)
assert "AVGT" in html and "Offensive" in html and "термометър" in html.lower()
print(f"✓ Dashboard: {len(html):,} символа → docs/index.html")

email = render_email(brief)
assert "AVGT" in email and "OFFENSIVE" in email
pathlib.Path("docs/_test_email.html").write_text(email, encoding="utf-8")
print(f"✓ Email: {len(email):,} символа → docs/_test_email.html")
print("\nВсички тестове минаха.")
