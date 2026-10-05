"""
Пакет 2 (2026-10-05) · AI why_now не тълкува "too_wide" по дълбочината на базата — промптът получава setup.trigger_text (причината от кода) като
"setup_reason" и изрична инструкция да я цитира, без собствено тълкуване.

РЕАЛНО: картите от брифа на 05.10.2026 (tests/fixtures/brief_2026-10-05.json): FTNT (база 18.1% дълбочина, структурен риск 12.62%), AMD (33.4% / 25.58%),
EXPD (below_pivot) с реалните setup полета и реалните AI текстове, в които "too_wide" е обяснен с base_depth. СИНТЕТИЧНО: подменените _call_claude и
предишните trigger-и, кандидат без setup.
Пускане: python test_setup_reason.py
"""
import sys, json, pathlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import ai_brief

BRIEF = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
CARDS = {w["ticker"]: w for w in BRIEF["watchlist"]}

print("── РЕАЛНОТО поведение на 05.10: too_wide, обяснен с дълбочината на базата ──")
for t, depth in (("FTNT", "18"), ("AMD", "33"), ("AVT", "25"), ("ARW", "21")):
    txt = CARDS[t]["ai"]["why_now"] + " " + CARDS[t]["ai"]["watchlist_trigger"]
    assert CARDS[t]["setup"]["kind"] == "too_wide", t
    assert re.search(rf"too_wide['\"]?\s*\(?\s*base_depth\s*{depth}|base_depth\s*{depth}", txt), t        # "base_depth 18…" и т.н. в реалния текст
assert (CARDS["FTNT"]["base_depth_pct"], CARDS["FTNT"]["setup"]["struct_risk_pct"], CARDS["AMD"]["base_depth_pct"], CARDS["AMD"]["setup"]["struct_risk_pct"]) == (18.1, 12.62, 33.4, 25.58)
print("  ✓ реалните AI текстове на FTNT, AMD, AVT, ARW казват \"too_wide (base_depth …)\", докато кодът го определя по риска до стопа (FTNT 12.62%, AMD 25.58%)")

print()
print("── промптът носи причината от кода ──")
seen = {}
def fake(system, user, max_tokens=0):
    seen["user"] = user
    return json.dumps({"tickers": []})
ai_brief._call_claude = fake
ai_brief._load_prior_watchlist_triggers = lambda *a, **k: {}
cands = [dict(CARDS[t]) for t in ("FTNT", "AMD", "EXPD")]
ai_brief.ticker_narratives(cands, [], "Defensive")
u = seen["user"]
m = re.search(r"КАНДИДАТИ: (\[.*?\])\n", u, re.S)
slim = {x["ticker"]: x for x in json.loads(m.group(1))}
for t in ("FTNT", "AMD", "EXPD"):
    assert slim[t]["setup_reason"] == CARDS[t]["setup"]["trigger_text"] and slim[t]["setup"] == CARDS[t]["setup"]["kind"]
assert "е 12.6% под входа (> 10%)" in slim["FTNT"]["setup_reason"] and "е 25.6% под входа (> 10%)" in slim["AMD"]["setup_reason"]
assert "buy-stop $194.59" in slim["EXPD"]["setup_reason"]
assert "ПРИЧИНАТА за сетъпа, изчислена и написана от кода" in u and 'НЕ се определя от дълбочината на базата' in u and "НЕ измисляй собствено обяснение" in u
print("  ✓ FTNT: \"…е 12.6% под входа (> 10%)\", AMD: \"…е 25.6% под входа\", EXPD: \"buy-stop $194.59…\" — точно текстът на кода; \"setup\" остава kind-ът")
print("  ✓ инструкцията: цитирай причината и числата ѝ, не тълкувай \"too_wide\" с base_depth (с реалния пример FTNT 18.1% срещу 12.6%)")

print()
print("── кандидат без setup ──")
nosetup = {"ticker": "ZZZ", "company": "Z", "price": 10.0}
seen.clear()
ai_brief.ticker_narratives([nosetup], [], "Defensive")
slim2 = {x["ticker"]: x for x in json.loads(re.search(r"КАНДИДАТИ: (\[.*?\])\n", seen["user"], re.S).group(1))}
assert slim2["ZZZ"]["setup"] is None and slim2["ZZZ"]["setup_reason"] is None
print("  ✓ без setup → setup и setup_reason са None, без изключение")
print()
print("Всички тестове минаха.")
