"""
16.10.2026 · В7 + т. 6 (трети преглед): паднал AI batch за наративите — класификацията остава на кода (потвърден пробив → Action), картата казва "без AI текст днес", банер source "ai";
един лош елемент в отговора на модела (без тикър / не е обект / поле в лош формат) се прескача с ред в лога, вместо да свали run-а (KeyError в merge_narratives; main без try).

РЕАЛНО: tests/fixtures/brief_2026-10-16.json — Action картата на EXPD (потвърден пробив: цена $198.64 над pivot $195.32, обем 1.61×) и Watchlist картите (ZBRA, HUM, …) с техните
AI наративи (отговорът на модела от 16.10 — като "върнат" наратив); на 10.07.2026 NBIX, INCY, AMG, EXEL, AIZ останаха без наратив без банер (виж ai_brief.NARRATIVES_LOST).
СИНТЕТИЧНО (маркирано): подмененият _call_claude (провал / отговор с лош елемент), лошите елементи.
Пускане: python test_ai_lost_narratives.py
"""
import sys, json, copy, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
config.ENABLE_BACKTEST = False
from src import ai_brief, data_warnings, main as brief_main

B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
EXPD = next(c for c in B["action"] if c["ticker"] == "EXPD")
assert EXPD["setup"]["kind"] == "confirmed" and EXPD["setup"]["eligible"] and EXPD["ai"]["classification"] == "Action"
CARDS = [copy.deepcopy(EXPD)] + [copy.deepcopy(c) for c in B["watchlist"] if (c.get("setup") or {}).get("kind") in config.AI_NARRATIVE_SETUPS][:3]
REAL_AI = {c["ticker"]: {k: v for k, v in c["ai"].items() if k not in ("watchlist_trigger", "watchlist_reason_type")} | {"ticker": c["ticker"]} for c in CARDS}
fresh = lambda: [{k: v for k, v in copy.deepcopy(c).items() if k != "ai"} for c in CARDS]
quiet = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. всички batch-ове падат (СИНТЕТИЧНО) → класификацията е от кода ──")
real_call = ai_brief._call_claude
ai_brief._call_claude = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("API 529 overloaded (СИНТЕТИЧНО)"))
try:
    cands = fresh()
    with quiet():
        nar = ai_brief.ticker_narratives(cands, [], "Offensive")
        merged = ai_brief.merge_narratives(cands, nar)
finally:
    ai_brief._call_claude = real_call
assert nar == [] and ai_brief.NARRATIVES_LOST == [c["ticker"] for c in CARDS]
e = next(c for c in merged if c["ticker"] == "EXPD")
assert e["ai"] == {"classification": "Action", "why_now": ai_brief.NO_AI_TEXT, "ai_missing": True}
assert all(c["ai"]["classification"] == "Watchlist" and c["ai"]["ai_missing"] for c in merged if c["ticker"] != "EXPD")
with quiet():
    action, watch = brief_main.apply_hard_rules(copy.deepcopy(merged), 1.0, "Offensive")
assert [c["ticker"] for c in action] == ["EXPD"] and action[0]["ai"]["why_now"] == ai_brief.NO_AI_TEXT
w = data_warnings.collect(None, None, ai_lost=list(ai_brief.NARRATIVES_LOST))
assert len(w) == 1 and w[0]["source"] == "ai" and w[0]["message"].startswith(f"AI наративи: моделът не върна текст за {len(CARDS)} тикъра (EXPD, ")
print("  ✓ EXPD (потвърден пробив) остава Action по кода; останалите → Watchlist; картата — 'Без AI текст днес …'; банер source 'ai' с изгубените тикъри")

print()
print("── 2. отговор с РЕАЛНИТЕ наративи + лоши елементи (СИНТЕТИЧНИ) ──")
bad = list(REAL_AI.values()) + ["низ вместо обект", {"why_now": "без тикър"}, None]
bad[1] = {**bad[1], "why_now": ["списък", "вместо текст"], "risks": "текст вместо списък"}
ai_brief._call_claude = lambda *a, **k: json.dumps({"tickers": bad}, ensure_ascii=False)
try:
    cands = fresh()
    with quiet() as out:
        nar = ai_brief.ticker_narratives(cands, [], "Offensive")
        merged = ai_brief.merge_narratives(cands, nar)
finally:
    ai_brief._call_claude = real_call
log = out.getvalue()
assert ai_brief.NARRATIVES_LOST == [] and "прескочен" in log and "не е текст" in log and "не е списък" in log
assert next(c for c in merged if c["ticker"] == "EXPD")["ai"]["why_now"] == REAL_AI["EXPD"]["why_now"]
t1 = CARDS[1]["ticker"]
assert "why_now" not in next(c for c in merged if c["ticker"] == t1)["ai"] and "risks" not in next(c for c in merged if c["ticker"] == t1)["ai"]
print("  ✓ низ / без тикър / None — прескочени с ред в лога; поле в лош формат — махнато; реалните наративи — непокътнати")

print()
print("── 3. модел пропуска тикър в успешен batch (СИНТЕТИЧНО) ──")
part = [v for t, v in REAL_AI.items() if t != CARDS[-1]["ticker"]]
ai_brief._call_claude = lambda *a, **k: json.dumps({"tickers": part}, ensure_ascii=False)
try:
    cands = fresh()
    with quiet():
        merged = ai_brief.merge_narratives(cands, ai_brief.ticker_narratives(cands, [], "Offensive"))
finally:
    ai_brief._call_claude = real_call
assert ai_brief.NARRATIVES_LOST == [CARDS[-1]["ticker"]] and next(c for c in merged if c["ticker"] == CARDS[-1]["ticker"])["ai"]["ai_missing"]
print(f"  ✓ пропуснатият {CARDS[-1]['ticker']} → изгубен, без AI текст; останалите — с наратива си")

print()
print("── 4. main: стъпките са в try ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
i = src.index("narratives = ai_brief.ticker_narratives(")
assert src.rfind("try:", 0, i) > i - 200 and "candidates = ai_brief.merge_narratives(candidates, narratives)" in src and "сливането на наративите пропадна" in src
assert "ai_lost=list(ai_brief.NARRATIVES_LOST)" in src
print("  ✓ ticker_narratives и merge_narratives — всяка в try; при срив класификацията е от кода; банерът получава изгубените")
print("\n✅ test_ai_lost_narratives: всичко мина")
