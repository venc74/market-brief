"""
В1 (втори преглед, 10.10.2026) · прозорецът преди отчет (EARNINGS_BLACKOUT_DAYS) е БЕЗУСЛОВЕН. До 10.10 merge_narratives имаше условие "in_blackout and not warning", а промптът
разрешаваше "Action с изрично предупреждение … поле warning" → моделът можеше да държи Action 0–7 дни преди отчет. Латентно: в историята (docs/data) 40 карти в прозореца,
всичките Watchlist, нито една с warning. Сега правилото е и в merge_narratives, и в main.apply_hard_rules (кодът има последната дума), без изключение.

РЕАЛНО: tests/fixtures/brief_2026-10-05.json — Watchlist картата на EXPD (below_pivot, buy-stop) с цена/pivot/сетъп/отчет от брифа; текстът на промпта.
СИНТЕТИЧНО (маркирано): отчетът в прозореца (in_blackout=True) върху реалната карта, отговорът на модела (Action + warning), потвърденият сетъп в т.3.
Пускане: python test_earnings_blackout.py
"""
import sys, json, pathlib, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
config.ENABLE_BACKTEST = False          # не чети реалния tracker
from src import ai_brief, main as brief_main

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
EXPD = next(c for c in B05["watchlist"] if c["ticker"] == "EXPD")
assert EXPD["setup"]["kind"] == "below_pivot" and EXPD["setup"].get("buy_stop")
BLACKOUT = {"next_earnings": "2026-10-09", "days_to_earnings": 4, "in_blackout": True}         # СИНТЕТИЧНО: отчет след 4 дни

print("── 1. промптът няма изключение ──")
p = ai_brief._build_ticker_user_prompt([{"ticker": "AAA"}], [], "Offensive")
assert 'поле "warning"' not in p and "Action с \\\nизрично предупреждение" not in p and "Action с изрично предупреждение" not in p
assert "Кодът го налага безусловно" in p and "няма изключение" in p
print("  ✓ промптът вече не позволява Action с поле \"warning\"; казва, че кодът налага Watchlist безусловно")

print()
print("── 2. merge_narratives: Action + warning от модела → Watchlist ──")
c = copy.deepcopy(EXPD); c.pop("ai", None); c["earnings"] = dict(BLACKOUT)
out = ai_brief.merge_narratives([c], [{"ticker": "EXPD", "classification": "Action", "warning": "изключителен setup (СИНТЕТИЧЕН отговор)", "why_now": "x"}])
assert out[0]["ai"]["classification"] == "Watchlist" and out[0]["ai"]["watchlist_reason_type"] == "earnings_blackout"
c = copy.deepcopy(EXPD); c.pop("ai", None); c["earnings"] = dict(BLACKOUT)
out = ai_brief.merge_narratives([c], [{"ticker": "EXPD", "classification": "Action", "why_now": "x"}])
assert out[0]["ai"]["classification"] == "Watchlist"
print("  ✓ реалната карта EXPD (05.10) + СИНТЕТИЧЕН отчет след 4 дни: Action с warning → Watchlist / earnings_blackout; без warning — също")

print()
print("── 3. apply_hard_rules: последната дума е на кода, дори ако merge е заобиколен ──")
c = copy.deepcopy(EXPD); c["earnings"] = dict(BLACKOUT)
c["setup"] = {**c["setup"], "kind": "confirmed", "eligible": True}                            # СИНТЕТИЧНО: потвърден пробив (иначе техническият gate би го върнал и без отчета)
c["ai"] = {"classification": "Action", "warning": "изключителен setup", "why_now": "x"}        # СИНТЕТИЧНО: AI решение, което не е минало през merge
action, watch = brief_main.apply_hard_rules([c], 1.0, "Offensive")
assert not action and watch and watch[0]["ticker"] == "EXPD" and watch[0]["ai"]["watchlist_reason_type"] == "earnings_blackout"
assert watch[0]["ai"]["watchlist_trigger"].startswith("Отчет на 2026-10-09 (4 дни) — нов Action най-рано след отчета.")
c2 = copy.deepcopy(EXPD); c2["earnings"] = {"next_earnings": "2026-11-20", "days_to_earnings": 30, "in_blackout": False}      # наново от реалната карта (apply_hard_rules пипа c на място)
c2["setup"] = {**c2["setup"], "kind": "confirmed", "eligible": True}; c2["ai"] = {"classification": "Action", "why_now": "x"}
action, watch = brief_main.apply_hard_rules([c2], 1.0, "Offensive")
assert watch == [] or watch[0]["ai"].get("watchlist_reason_type") != "earnings_blackout"
print("  ✓ потвърден пробив + Action + warning, отчет след 4 дни → Watchlist / earnings_blackout, текстът започва с «Отчет на … — нов Action най-рано след отчета.»;"
      " отчет след 30 дни → правилото не се намесва")
print()
print("── 4. С7: текстът на картата е от кода (отчет + buy-stop + режим), не «След earnings на …» ──")
c = copy.deepcopy(EXPD); c.pop("ai", None); c["earnings"] = dict(BLACKOUT)
ai_brief.merge_narratives([c], [{"ticker": "EXPD", "classification": "Watchlist", "why_now": "x"}])
assert "watchlist_trigger" not in c["ai"]                                                     # до 10.10: setdefault("След earnings на 2026-10-09")
_, watch = brief_main.apply_hard_rules([c], 1.0, "Defensive")
t = watch[0]["ai"]["watchlist_trigger"]
assert t.startswith("Отчет на 2026-10-09 (4 дни) — нов Action най-рано след отчета.") and EXPD["setup"]["trigger_text"] in t and "$194.59" in t and "Режим Defensive" in t
assert "След earnings на" not in t
print("  ✓ реалната EXPD (05.10) + СИНТЕТИЧЕН отчет: текстът пази buy-stop $194.59 и режима (до 10.10 беше само «След earnings на 2026-10-09»)")
print("    " + t[:200] + "…")
print()
print("Всички тестове минаха.")
