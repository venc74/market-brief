"""
Пакет 1, т.3 (2026-10-03): структурен стоп (най-ниският Low на 15 бара −1%, макс. 8% под
входа), структурен риск >10% → не е Action ("твърде разтегнато"), нов план position_plan_v2.

РЕАЛНИ данни (tests/fixtures/ohlc_*.csv — дневни барове от Yahoo, свалени на 02.10.2026;
сигналните барове са тези на брифовете от 22.09 и 29.06):
  AMD, TWLO  — бриф 22.09.2026 (сигнален бар 21.09)
  LNTH, EXEL — бриф 29.06.2026 (сигнален бар 26.06)
Граничните случаи (10.00% / 8.00%, дегенерирани входове, приоритет на причините) са
СИНТЕТИЧНИ — маркирани като такива. Пускане: python test_stop_plan.py
"""
import sys, re, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import screener, setup_rules, sizing, thermometer, render
from src import main as brief_main

FIX = ROOT / "tests" / "fixtures"


def row_at(sym, last_bar):
    df = pd.read_csv(FIX / f"ohlc_{sym}.csv", index_col=0, parse_dates=True).loc[:last_bar]
    spy = pd.read_csv(FIX / "ohlc_SPY.csv", index_col=0, parse_dates=True)["Close"].loc[:last_bar]
    r = screener._evaluate_technicals(sym, df, spy)
    assert r is not None, f"{sym} {last_bar}: не мина технически филтър"
    return r


D_SEP, D_JUN = dt.date(2026, 9, 22), dt.date(2026, 6, 29)
amd, twlo = row_at("AMD", "2026-09-21"), row_at("TWLO", "2026-09-21")
lnth, exel = row_at("LNTH", "2026-06-26"), row_at("EXEL", "2026-06-26")

print("── РЕАЛНИ: struct_low от screener (15 бара, сигналният включен) ──")
assert (amd["struct_low"], twlo["struct_low"], lnth["struct_low"], exel["struct_low"]) == (440.50, 221.86, 97.99, 50.80)
print("  ✓ AMD 440.50 · TWLO 221.86 · LNTH 97.99 · EXEL 50.80")
print()

print("── РЕАЛНИ: структурен риск и класификация ──")
cases = [("AMD 22.09", amd, D_SEP, 29.15, "too_wide"), ("TWLO 22.09", twlo, D_SEP, 17.45, "too_wide"),
         ("LNTH 29.06", lnth, D_JUN, 11.65, "too_wide"), ("EXEL 29.06", exel, D_JUN, 8.18, "confirmed")]
for name, r, day, risk, kind in cases:
    s = setup_rules.classify_setup(r, day)
    print(f"  {name}: close {r['price']} low15 {r['struct_low']} → структурен риск {s['struct_risk_pct']}% → {s['kind']}")
    assert abs(s["struct_risk_pct"] - risk) < 0.006, (name, s["struct_risk_pct"])
    assert s["kind"] == kind and s["eligible"] == (kind == "confirmed")
s_amd = setup_rules.classify_setup(amd, D_SEP); s_twlo = setup_rules.classify_setup(twlo, D_SEP)
assert "Твърде разтегнато" in s_amd["trigger_text"] and "Също extended" in s_amd["trigger_text"]
assert "Твърде разтегнато" in s_twlo["trigger_text"] and "Също без обем" in s_twlo["trigger_text"]
s_exel = setup_rules.classify_setup(exel, D_JUN)
assert s_exel["stop"] == 50.39 and s_exel["risk_pct"] == 8.0 and s_exel["struct_stop"] == 50.29
print("  ✓ AMD (+ extended) и TWLO (+ без обем) и LNTH са твърде разтегнати; EXEL е потвърден със стоп $50.39 (таван 8%)")
print()

print("── РЕАЛНИ: position_plan_v2 ──")
p = sizing.position_plan_v2(exel, 1.0, D_JUN)
assert p["valid"] and p["method"] == "v2"
assert (p["buy_stop"], p["max_chase"], p["valid_through"]) == (53.93, 56.63, "2026-07-06")   # 03.07 е празник
assert (p["stop_loss"], p["stop_capped"], p["struct_stop"], p["risk_pct"]) == (50.39, True, 50.29, 8.0)
assert p["risk_per_share"] == 4.38 and p["target_1"] == 63.53 and p["entry_mid"] == 54.77
assert p["sizing_factor"] == 1.0 and not any(k in p for k in ("shares", "total_investment", "pct_of_portfolio", "max_risk_usd"))     # 07.10: размерът е в браузъра, не в плана
assert "таван 8% под входа" in p["stop_basis"] and "(структурният е 8.2%)" in p["stop_basis"]
pd_ = sizing.position_plan_v2(exel, 0.5, D_JUN)                                           # Defensive ×0.5
assert pd_["sizing_factor"] == 0.5 and all(pd_[k] == p[k] for k in ("stop_loss", "risk_pct", "target_1", "entry_mid"))   # режимният фактор не мести нивата
for name, r in (("LNTH", lnth), ("TWLO", twlo), ("AMD", amd)):
    bad = sizing.position_plan_v2(r, 1.0, D_JUN)
    assert not bad["valid"] and "Твърде разтегнато" in bad["reason"], (name, bad)
assert not sizing.position_plan_v2({**exel, "struct_low": None}, 1.0)["valid"]             # без low → невалиден
assert not sizing.position_plan_v2({"ticker": "X"}, 1.0)["valid"]                          # без цена/pivot
print("  ✓ EXEL: buy-stop $53.93, таван $56.63, до 06.07; стоп $50.39 (−8.0%), риск/акция $4.38, цел 1 $63.53,")
print("    режимен фактор 1.0 / 0.5 (нивата не се местят, без брой акции в плана); LNTH/TWLO/AMD → невалиден план")
print()

print("── СИНТЕТИЧНО: граници на stop_levels (вход $100.00) ──")
def sl(low, entry=100.0):
    return setup_rules.stop_levels(low, entry)
r = sl(90.91);  assert not r["too_wide"] and r["struct_risk_pct"] == 10.0 and r["stop"] == 92.0 and r["stop_capped"]
r = sl(90.90);  assert r["too_wide"] and r["struct_risk_pct"] == 10.01       # 10.009% → строго над прага
r = sl(95.0);   assert not r["too_wide"] and r["stop"] == 94.05 and not r["stop_capped"] and r["risk_pct"] == 5.95
r = sl(92.92);  assert r["stop"] == 92.0 and r["stop_capped"] and r["risk_pct"] == 8.0   # структурният 8.0092% → таван
r = sl(92.93);  assert r["stop"] == 92.0 and not r["stop_capped"]              # структурният 7.9993% още е под тавана
r = sl(93.0);   assert r["stop"] == 92.07 and not r["stop_capped"] and r["risk_pct"] == 7.93
assert sl(101.0) is None                                                       # low над входа — счупени данни
assert sl(None) is None and sl(-5) is None and sl(90.0, 0) is None and sl("90", 100) is None
orig = config.STOP_STRUCT_BUFFER_PCT
config.STOP_STRUCT_BUFFER_PCT = 0.0
assert sl(95.0)["struct_stop"] == 95.0 and sl(95.0)["risk_pct"] == 5.0           # без буфер
assert sl(100.0) is None                                                       # без буфер low == вход → стопът не е под входа
config.STOP_STRUCT_BUFFER_PCT = orig
print("  ✓ 9.9991% още е допустим (стоп на тавана $92.00), 10.009% → твърде разтегнато; структурен стоп под тавана")
print("    остава непокътнат; low над входа/нули → None; буферът е параметър")
print()

print("── СИНТЕТИЧНО: приоритет на причините в classify_setup ──")
base = {"ticker": "SYN", "pivot": 100.0, "breakout_volume": True, "volume_ratio": 2.0}
T = dt.date(2026, 9, 30)
def cs(**kw): return setup_rules.classify_setup({**base, **kw}, T)
assert cs(price=104.0, struct_low=98.0)["kind"] == "confirmed"                   # тесен → потвърден
s = cs(price=104.0, struct_low=88.0); assert s["kind"] == "too_wide" and not s["eligible"]   # чист пробив, но широк
assert cs(price=110.0, struct_low=105.0)["kind"] == "extended"                  # +10% над pivot, тесен стоп
assert cs(price=110.0, struct_low=80.0)["kind"] == "too_wide"                    # too_wide бие extended
s = cs(price=95.0, struct_low=70.0); assert s["kind"] == "too_wide" and s["buy_stop"] is None   # без реклама на buy-stop
s = cs(price=95.0, struct_low=92.0); assert s["kind"] == "below_pivot" and s["buy_stop"] == 100.0
assert cs(price=104.0)["kind"] == "confirmed"                                    # без struct_low проверката се пропуска
assert cs(price=104.0, struct_low=None)["struct_risk_pct"] is None
print("  ✓ too_wide има предимство пред extended/no_volume; под pivot с широка структура не рекламира buy-stop;")
print("    без struct_low проверката се пропуска (запасната проверка в плана връща невалиден план)")
print()

print("── apply_hard_rules: реалните редове с AI 'Action' (AI решения — СИНТЕТИЧНИ) ──")
config.ENABLE_BACKTEST = False        # не чети реалния data/backtest_tracker.json


def cand(r, sector, day):
    c = dict(r)
    c.update({"company": r["ticker"] + " Corp", "sector": sector,
              "earnings": {"next_earnings": None, "days_to_earnings": None, "in_blackout": False},
              "options": {}, "short_view": {},
              "ai": {"classification": "Action", "why_now": "тест", "catalysts": [], "risks": []}})
    c["setup"] = setup_rules.classify_setup(c, day)
    return c


jun = [cand(lnth, "Healthcare", D_JUN), cand(exel, "Healthcare", D_JUN)]
sep = [cand(amd, "Technology", D_SEP), cand(twlo, "Technology", D_SEP)]
action, watch = brief_main.apply_hard_rules(jun + sep, 1.0)
assert [a["ticker"] for a in action] == ["EXEL"], [a["ticker"] for a in action]
assert [w["ticker"] for w in watch] == ["LNTH", "TWLO", "AMD"], [w["ticker"] for w in watch]   # по |pct_from_pivot|
for w in watch:
    assert w["ai"]["watchlist_reason_type"] == "technical_gate" and "Твърде разтегнато" in w["ai"]["watchlist_trigger"]
assert action[0]["plan"]["method"] == "v2" and action[0]["plan"]["stop_loss"] == 50.39
print("  ✓ от четирите реални кандидата само EXEL става Action (план v2); LNTH, TWLO, AMD → Watchlist 'Твърде разтегнато'")
print()

print("── dashboard и имейл (EXEL — РЕАЛНИ стойности; режим/макро — СИНТЕТИЧНО) ──")
brief = {"date": "2026-06-29", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")),
         "action": action, "watchlist": watch,
         "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
with tempfile.TemporaryDirectory() as tmp:
    orig_docs = config.DOCS_DIR
    config.DOCS_DIR = pathlib.Path(tmp)
    try:
        html = render.render_dashboard(brief)
        email = render.render_email(brief)
    finally:
        config.DOCS_DIR = orig_docs
# apply_hard_rules планира с РЕАЛНАТА днешна дата (валидността е от днес, не от 29.06)
vt = action[0]["plan"]["valid_through"]
assert vt == setup_rules.valid_through(dt.date.today()), vt
assert "Вход (buy-stop)" in html and "$53.93 · таван $56.63" in html and f"{vt} (5 сесии)" in html
txt = " ".join(re.sub(r"<[^>]+>", " ", html).split())
assert "източник на стопа: таван 8% под входа (структурният е 8.2%)" in txt and "$50.39 (−8.0%)" in txt and "Цел 1 (2:1) · 50%" in html and "$63.53" in html
assert 'data-strategy="canslim" data-entry="54.77" data-stop="50.39"' in html and not any(w in txt for w in ("Брой акции", "Инвестиция", "риск $"))
assert "риск/акция = цена − $50.39" in html
assert "Buy-stop $53.93 (таван $56.63)" in email and "Вход ≈ $54.77 · Stop $50.39 (−8.0%)" in email and "Цел $63.53 (50%)" in email and "акции" not in email.split("Action")[1].split("Watchlist")[0]
assert html.count("Твърде разтегнато") >= 3
print(f"  ✓ Action картата: 'Вход (buy-stop) $53.93 · таван $56.63', 'Валиден до {vt} (5 сесии)' (от днешната дата), стоп с процент,")
print("    'Цел 1 (2:1) · 50%'; блок с нивата: източник 'таван 8% под входа', стоп $50.39 (−8.0%); имейлът: 'Buy-stop $53.93 (таван $56.63) / Вход ≈ $54.77 · Stop $50.39 (−8.0%) / Цел $63.53 (50%)', без брой акции'")

config.ENABLE_BACKTEST = True
print()
print("Всички тестове минаха.")
