"""
Пакет 2 (2026-10-05) · Watchlist картите с buy-stop показват план — стоп, риск %, цел 1 (2R), брой акции и сума при ТЕКУЩИЯ sizing на режима, като
Action картата (sizing.buy_stop_preview; само показване, не променя класификацията).

РЕАЛНО: картата на EXPD от брифа на 05.10.2026 (tests/fixtures/brief_2026-10-05.json): цена 192.47, pivot/buy-stop 194.59, структурен low 183.36,
стоп 181.53 (−6.71%), режим Defensive (sizing ×0.5). СИНТЕТИЧНО: sizing 1.0 (Offensive), липсващ struct_low, твърде разтегнат кандидат
(реалната FTNT карта, но тя е без buy-stop), режим Cash.
Пускане: python test_watch_plan.py
"""
import sys, json, pathlib, copy, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import sizing, render
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
assert p["risk_per_share"] == rps and p["max_risk_usd"] == config.PORTFOLIO_SIZE * config.RISK_PER_TRADE_PCT / 100 * 0.5 == 500
assert p["shares"] == int(500 // rps) == 38 and p["total_investment"] == round(38 * 194.59) and p["pct_of_portfolio"] == round(38 * 194.59 / config.PORTFOLIO_SIZE * 100, 1)
assert p["target_1"] == round(194.59 + 2 * rps, 2) == 220.71 and p["target_1_fraction"] == 0.5 and p["sizing_factor"] == 0.5
print(f"  ✓ вход buy-stop $194.59, стоп $181.53 (−6.71%, като в setup), риск/акция ${rps}; при Defensive ×0.5: риск $500 → {p['shares']} акции (${p['total_investment']:,.0f}, {p['pct_of_portfolio']}% от портфейла); цел 1 (2R) $220.71")
p1 = sizing.buy_stop_preview(EXPD, 1.0, "2026-10-05")
assert p1["max_risk_usd"] == 1000 and p1["shares"] == int(1000 // rps) == 76 and p1["stop_loss"] == p["stop_loss"] and p1["target_1"] == p["target_1"]
print("  ✓ СИНТЕТИЧНО: при Offensive (×1.0) — риск $1000 → 76 акции; стопът и целта са същите, сменя се само размерът")
# планът е със същия референтен вход като Action плана на същия сетъп, когато цената е точно на buy-stop
act = sizing.position_plan_v2({**EXPD, "price": 194.59}, 0.5, "2026-10-05")
assert all(act[k] == p[k] for k in ("stop_loss", "risk_pct", "shares", "total_investment", "target_1", "max_risk_usd"))
print("  ✓ числата са идентични с position_plan_v2 за същия кандидат при цена = buy-stop (един и същ код за стоп/риск/цел/размер)")

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
for regime, factor, shares in (("Defensive", 0.5, 38), ("Offensive", 1.0, 76), ("Cash", 0.5, 38)):
    action, watch = brief_main.apply_hard_rules([copy.deepcopy(cand)], factor, regime)
    assert not action and [x["ticker"] for x in watch] == ["EXPD"]                                    # нищо не става Action заради прегледа (под pivot)
    pv = watch[0]["plan_preview"]
    assert pv["valid"] and pv["shares"] == shares and pv["sizing_factor"] == factor
print("  ✓ кандидатът остава във Watchlist при Defensive/Offensive/Cash (прегледът не го прави Action); брой акции 38 / 76 / 38 според sizing-а на режима")
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
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2 = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        page = htmllib.unescape(render.render_dashboard(brief))
        brief["thermometer"] = {**brief["thermometer"], "regime": "Cash"}
        page_cash = htmllib.unescape(render.render_dashboard(brief))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2
line = ("Ако се задейства (вход ≈ $194.59): Stop $181.53 (−6.71%) · Цел 1 (2R, 50% от позицията) $220.71 · риск $500 (Defensive ×0.5) → 38 акции ($7,394, 7.4% от портфейла)")
flat = " ".join(page.split())
assert line in flat, [l for l in flat.split("📐")[1:2]]
assert flat.count("Ако се задейства") == 1 and "режим Cash" not in flat
assert "режим Cash: нов Action не се дава, планът е само ориентир" in " ".join(page_cash.split())
print("  ✓ картата на EXPD показва: Stop $181.53 (−6.71%) · Цел 1 (2R) $220.71 · риск $500 (Defensive ×0.5) → 38 акции ($7,394, 7.4% от портфейла); при Cash — бележка, че е само ориентир;")
print("    останалите Watchlist карти (без buy-stop) нямат такъв ред")
print()
print("Всички тестове минаха.")
