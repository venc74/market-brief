"""
Пакет 2 (2026-10-05) · Watchlist картите с buy-stop показват план — стоп, риск % и цел 1 (2R) при ТЕКУЩИЯ режимен фактор (без брой акции и сума — размерът е в браузъра, 07.10), като
Action картата (sizing.buy_stop_preview; само показване, не променя класификацията).

РЕАЛНО: картата на EXPD от брифа на 05.10.2026 (tests/fixtures/brief_2026-10-05.json): цена 192.47, pivot/buy-stop 194.59, структурен low 183.36,
стоп 181.53 (−6.71%), режим Defensive (sizing ×0.5). СИНТЕТИЧНО: sizing 1.0 (Offensive), липсващ struct_low, твърде разтегнат кандидат
(реалната FTNT карта, но тя е без buy-stop), режим Cash.
Пускане: python test_watch_plan.py
"""
import sys, re, json, pathlib, copy, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import sizing, render, trade_levels
from src import main as brief_main

config.ENABLE_BACKTEST = False
BRIEF = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
CARDS = {w["ticker"]: w for w in BRIEF["watchlist"]}
EXPD, FTNT = CARDS["EXPD"], CARDS["FTNT"]
assert (EXPD["setup"]["kind"], EXPD["setup"]["buy_stop"], EXPD["setup"]["stop"], EXPD["setup"]["risk_pct"]) == ("below_pivot", 194.59, 181.53, 6.71)
assert BRIEF["thermometer"]["regime"] == "Defensive" and BRIEF["thermometer"]["sizing_factor"] == 0.5

print("── EXPD (РЕАЛНА карта от 05.10): план при задействане ──")
p = sizing.buy_stop_preview(EXPD, 0.5, "2026-10-05")
rps = round(194.59 - 181.53, 2)                                                         # 13.06 риск на акция (независима сметка)
assert p["valid"] and p["preview"] and p["entry_mid"] == 194.59 and p["buy_stop"] == 194.59
assert p["stop_loss"] == EXPD["setup"]["stop"] == 181.53 and p["risk_pct"] == EXPD["setup"]["risk_pct"] == 6.71          # съвпада със setup (същият референтен вход)
assert p["risk_per_share"] == rps and not any(k in p for k in ("shares", "total_investment", "pct_of_portfolio", "max_risk_usd"))     # 07.10: размерът е в браузъра
assert p["target_1"] == round(194.59 + 2 * rps, 2) == 220.71 and p["target_1_fraction"] == 0.5 and p["sizing_factor"] == 0.5
print(f"  ✓ вход buy-stop $194.59, стоп $181.53 (−6.71%, като в setup), риск/акция ${rps}; режимен фактор ×0.5 (само фактор, без брой акции); цел 1 (2R) $220.71")
p1 = sizing.buy_stop_preview(EXPD, 1.0, "2026-10-05")
assert p1["sizing_factor"] == 1.0 and p1["stop_loss"] == p["stop_loss"] and p1["target_1"] == p["target_1"]
print("  ✓ СИНТЕТИЧНО: при Offensive (×1.0) стопът и целта са същите, сменя се само режимният фактор")
# планът е със същия референтен вход като Action плана на същия сетъп, когато цената е точно на buy-stop
act = sizing.position_plan_v2({**EXPD, "price": 194.59}, 0.5, "2026-10-05")
assert all(act[k] == p[k] for k in ("stop_loss", "risk_pct", "target_1", "sizing_factor"))
print("  ✓ числата са идентични с position_plan_v2 за същия кандидат при цена = buy-stop (един и същ код за стоп/риск/цел)")

print()
print("── граници ──")
assert sizing.buy_stop_preview(FTNT, 0.5)["valid"] is False and "buy-stop" in sizing.buy_stop_preview(FTNT, 0.5)["reason"]       # РЕАЛНАТА FTNT (too_wide) е без buy-stop
no_low = copy.deepcopy(EXPD); no_low.pop("struct_low")
bad = sizing.buy_stop_preview(no_low, 0.5)
assert bad["valid"] is False and "структурен low" in bad["reason"]
wide = copy.deepcopy(EXPD); wide["struct_low"] = 150.0                                                 # СИНТЕТИЧНО: структурният стоп е над 10% под входа
w = sizing.buy_stop_preview(wide, 0.5)
assert w["valid"] is False and "Твърде разтегнато" in w["reason"]
print("  ✓ без buy-stop (реалната FTNT, too_wide) → без план; без struct_low → без план с причина; структурен риск > 10% → 'Твърде разтегнато'")

print()
print("── през apply_hard_rules (РЕАЛНАТА карта влиза като кандидат) ──")
cand = copy.deepcopy(EXPD)
cand.pop("plan_preview", None)
for regime, factor in (("Defensive", 0.5), ("Offensive", 1.0), ("Cash", 0.5)):
    action, watch = brief_main.apply_hard_rules([copy.deepcopy(cand)], factor, regime)
    assert not action and [x["ticker"] for x in watch] == ["EXPD"]                                    # нищо не става Action заради прегледа (под pivot)
    pv = watch[0]["plan_preview"]
    assert pv["valid"] and pv["sizing_factor"] == factor and "shares" not in pv
    lv = watch[0]["levels"]                                                                           # нивата се четат от прегледа: същият стоп, режимният фактор — на картата
    assert (lv["entry"], lv["stop"], lv["stop_pct"], lv["regime_factor"], lv["stop_source"]) == (194.59, 181.53, 6.71, factor, "structural")
print("  ✓ кандидатът остава във Watchlist при Defensive/Offensive/Cash (прегледът не го прави Action); нивата (вход $194.59, стоп $181.53, −6.71%, структурен) са едни и същи, режимният фактор 0.5 / 1.0 / 0.5 е върху картата")
too = copy.deepcopy(FTNT)
action, watch = brief_main.apply_hard_rules([too], 0.5, "Defensive")
assert "plan_preview" not in watch[0]
print("  ✓ карта без buy-stop (FTNT) не получава plan_preview")

print()
print("── в страницата ──")
brief = json.loads(json.dumps(BRIEF))
for card in brief["watchlist"]:
    if card["ticker"] == "EXPD":
        card["plan_preview"] = p
        card["levels"] = trade_levels.for_candidate(p, {**card, "adr_pct": 2.01}, 0.5, "вход при задействане (buy-stop)")      # 2.01 = РЕАЛНИЯТ ADR20 на EXPD към 02.10 от реалните барове
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2 = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        page = htmllib.unescape(render.render_dashboard(brief))
        brief["thermometer"] = {**brief["thermometer"], "regime": "Cash"}
        page_cash = htmllib.unescape(render.render_dashboard(brief))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2
line = ("Ако се задейства: Цел 1 (2R, 50% от позицията) $220.71 · режимен фактор Defensive ×0.5")
flat = " ".join(page.split())
assert line in flat, [l for l in flat.split("📐")[1:2]]
assert flat.count("Ако се задейства") == 1 and "режим Cash" not in flat
assert "акции" not in line and "риск $" not in line and "от портфейла" not in line
txt = " ".join(re.sub(r"<[^>]+>", " ", page).split())
assert 'data-entry="194.59" data-stop="181.53" data-adr="2.01" data-factor="0.5"' in page
assert "източник на стопа: структурен: 15-барен low −1%" in txt and "ADR (20 бара) 2.0%" in txt and "$181.53 (−6.7%)" in txt and "въведи баланса в настройките" in txt
assert "режим Cash: нов Action не се дава, планът е само ориентир" in " ".join(page_cash.split())
print("  ✓ картата на EXPD показва: Цел 1 (2R) $220.71 · режимен фактор ×0.5; блокът с нивата: вход $194.59, стоп $181.53 (−6.7%), източник структурен, ADR 2.0% — без брой акции; при Cash — бележка, че е само ориентир;")
print("    останалите Watchlist карти (без buy-stop) нямат такъв ред")
print()
print("Всички тестове минаха.")
