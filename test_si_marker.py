"""
Пакет 4а · т.2 (2026-10-03): секцията "High-Conviction New Positions" е махната; нова позиция на мениджър от
списъка е маркер SI✓ върху кандидатите (Action/Watchlist) и върху v2 позициите (отворени и чакащи buy-stop) —
hover (title) и клик (.marker-tip): кой мениджър и от коя дата е filing-ът.

Всички редове за нови позиции и кандидатите са СИНТЕТИЧНИ (тестов вход, не реален 13F); шаблонът е реалният.
Пускане: python test_si_marker.py
"""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import dataroma, enrich, render, thermometer

NEW = [
    {"ticker": "ABCD", "company": "ABCD Corp", "manager": "Бил Акман · Pershing Square", "value": 420_000_000.0,
     "pct_of_portfolio": 4.2, "period": "13F · 2026-08-14", "filing_date": "2026-08-14", "_resolved": True},
    {"ticker": "ABCD", "company": "ABCD Corp", "manager": "Сет Кларман · Baupost Group", "value": 60_000_000.0,
     "pct_of_portfolio": 2.5, "period": "13F · 2026-08-12", "filing_date": "2026-08-12", "_resolved": True},
    {"ticker": "EFGH", "company": "EFGH Inc", "manager": "Мониш Пабрай · Dalal Street", "value": 6_500_000.0,
     "pct_of_portfolio": 2.0, "period": "13F · 2026-08-10", "_resolved": True},              # стар кеш: без filing_date
    {"ticker": "SOME COMPANY NAME", "company": "Some Company Name", "manager": "X", "value": 1.0,
     "pct_of_portfolio": 3.0, "period": "13F · 2026-08-10", "_resolved": False},               # нерезолвиран → без маркер
]

print("── dataroma.new_position_markers ──")
mk = dataroma.new_position_markers(NEW)
assert set(mk) == {"ABCD", "EFGH"}
assert mk["EFGH"]["tag"] == "SI✓" and "Мониш Пабрай · Dalal Street" in mk["EFGH"]["title"]
assert "13F filing от 2026-08-10" in mk["EFGH"]["title"]                        # датата е взета от period при стар кеш
assert mk["ABCD"]["tag"] == "SI✓×2"
t = mk["ABCD"]["title"]
assert "Бил Акман · Pershing Square — 4.2% от портфейла, $420.0 млн; 13F filing от 2026-08-14" in t
assert "Сет Кларман · Baupost Group — 2.5% от портфейла, $60.0 млн; 13F filing от 2026-08-12" in t
assert t.index("Акман") < t.index("Кларман")                                    # по-голямата позиция първа
print("  ✓ един маркер на тикър: SI✓ (един мениджър) / SI✓×2; заглавие = мениджър, % от портфейла, стойност, дата на filing-а;")
print("    стар кеш без filing_date → датата от period; нерезолвиран тикър (само име на емитент) се пропуска")
print()

print("── enrich: един SI✓ маркер върху кандидата ──")
row = {"ticker": "ABCD"}
enrich._apply_markers(row, {"mf": set(), "uov": {}, "splits": {}, "si": {}, "si_new": mk})
assert [m["tag"] for m in row["markers"]] == ["SI✓×2"] and "Pershing" in row["markers"][0]["title"]
row = {"ticker": "ABCD"}                                                       # същият тикър е и в общия Moves feed → пак ЕДИН маркер
enrich._apply_markers(row, {"mf": set(), "uov": {}, "splits": {}, "si_new": mk,
                            "si": {"ABCD": {"managers": ["Бил Акман · Pershing Square"], "value": 420e6, "action": "нова позиция", "count": 1}}})
assert [m["tag"] for m in row["markers"]] == ["SI✓×2"] and "Superinvestor покупка" in row["markers"][0]["title"] and "\n" in row["markers"][0]["title"]
row = {"ticker": "ZZZZ"}                                                        # само Moves feed → старото поведение
enrich._apply_markers(row, {"mf": set(), "uov": {}, "splits": {}, "si_new": {},
                            "si": {"ZZZZ": {"managers": ["М1", "М2"], "value": 5e7, "action": "Buy", "count": 2}}})
assert [m["tag"] for m in row["markers"]] == ["SI✓×2"] and row["markers"][0]["title"].startswith("Superinvestor покупка (Buy)")
row = {"ticker": "NONE"}
enrich._apply_markers(row, {"mf": set(), "uov": {}, "splits": {}, "si": {}, "si_new": mk})
assert row["markers"] == []
print("  ✓ нова позиция → SI✓ върху кандидата; ако тикърът е и в Moves feed — пак един маркер с двата реда; без нова позиция — старото поведение")
print()

print("── dashboard: секцията я няма; маркерът е на Action, Watchlist и v2 позициите ──")
def cand(t, cls):
    return {"ticker": t, "company": t + " Corp", "sector": "Tech", "price": 100.0, "pivot": 99.0, "pct_from_pivot": 1.0,
            "base_type": "база 10.0% дълбочина", "base_depth_pct": 10.0, "weinstein_stage": 2, "rs_status": "new_high", "ma50": 90.0, "ma200": 80.0,
            "volume_ratio": 2.0, "breakout_volume": True, "eps_growth_yoy": 30, "revenue_growth_yoy": 25, "roe": 20, "inst_ownership_pct": 70,
            "earnings": {}, "options": {}, "short_view": {}, "markers": [mk[t]] if t in mk else [],
            "ai": {"classification": cls, "why_now": "тест", "catalysts": [], "risks": [], "watchlist_trigger": "тест"},
            "plan": {"valid": True, "method": "v2", "buy_stop": 99.0, "max_chase": 103.95, "valid_through": "2026-10-09", "window_sessions": 5,
                     "stop_loss": 92.0, "stop_basis": "структурен", "risk_pct": 7.0, "max_risk_usd": 1000, "sizing_factor": 1.0, "shares": 140,
                     "total_investment": 14000, "pct_of_portfolio": 14.0, "target_1": 114.0, "target_1_fraction": 0.5, "target_2": "тест",
                     "time_horizon": "4–8 седмици", "entry_range": [99.0, 103.95], "entry_mid": 100.0}}
backtest = {"total_resolved": 0, "open_positions": [{"ticker": "ABCD", "entry_date": "2026-10-01", "entry_price": 50.0, "current_price": 51.0,
                                                    "unrealized_pct": 2.0, "earnings_recap": None, "markers": [mk["ABCD"]]}],
            "pending_positions": [{"ticker": "EFGH", "entry_date": "2026-10-02", "buy_stop": 10.0, "max_chase": 10.5, "stop_loss": 9.0,
                                   "target_1": 12.0, "valid_through": "2026-10-08", "markers": [mk["EFGH"]]}], "pending": 1}
brief = {"date": "2026-10-05", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")),
         "action": [cand("ABCD", "Action")], "watchlist": [cand("EFGH", "Watchlist")], "backtest": backtest,
         "superinvestor_new_positions": NEW,                                          # данните остават в брифа, но не се рисуват като секция
         "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
with tempfile.TemporaryDirectory() as docs:
    orig = config.DOCS_DIR
    config.DOCS_DIR = pathlib.Path(docs)
    try:
        html = render.render_dashboard(brief)
    finally:
        config.DOCS_DIR = orig
assert "High-Conviction New Positions" not in html and "Съвсем НОВА позиция" not in html
assert html.count('class="marker"') == 4                                           # Action, Watchlist, отворена и чакаща позиция
assert html.count("SI✓×2<span") == 2 and html.count("SI✓<span") == 2             # ABCD: Action + отворена позиция; EFGH: Watchlist + чакаща
assert 'onclick="this.classList.toggle(\'open\')"' in html and 'class="marker-tip"' in html
assert "Мониш Пабрай · Dalal Street — 2.0% от портфейла, $6.5 млн; 13F filing от 2026-08-10" in html
print("  ✓ няма 'High-Conviction New Positions'; SI✓ е върху Action картата, Watchlist картата, отворената и чакащата v2 позиция,")
print("    с hover (title) и клик (.marker-tip), който казва мениджъра и датата на filing-а")

print()
print("Всички тестове минаха.")
