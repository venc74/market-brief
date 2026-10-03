"""
Пакет 2 · т.4 (2026-10-03): макро брифът се генерира СЛЕД значимите новини и получава курираните заглавия с тяхното "why";
NewsAPI е махнат (macro.headlines беше празен във всичките 78 брифа).

РЕАЛНО: осемте новини (headline + why) от tests/fixtures/brief_2026-10-02.json (бриф от 02.10.2026, curated от
news_aggregator.significant_news през Claude); фактът, че macro.headlines е празен във всяка от петте фикстури (08.06 → 02.10).
СИНТЕТИЧНО: макро/термометър входовете на промпта (празни обекти), празният/счупеният списък с новини, отговорът на Claude
(подменен _call_claude — мрежа не се ползва).
Пускане: python test_macro_news.py
"""
import sys, pathlib, json, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import ai_brief, macro_layer

FIX = sorted((ROOT / "tests" / "fixtures").glob("brief_*.json"))
REAL = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-02.json").read_text(encoding="utf-8"))["news"]

print("── NewsAPI е махнат ──")
assert not hasattr(macro_layer, "recent_headlines") and not hasattr(config, "NEWS_API_KEY")
src_macro = (ROOT / "src" / "macro_layer.py").read_text(encoding="utf-8")
assert "newsapi.org" not in src_macro and '"headlines":' not in src_macro
for f in FIX:
    b = json.loads(f.read_text(encoding="utf-8"))
    assert not (b.get("macro") or {}).get("headlines"), f.name                  # РЕАЛНО: празно във всяка фикстура
print(f"  ✓ recent_headlines() и config.NEWS_API_KEY ги няма; macro.headlines е празно в {len(FIX)} РЕАЛНИ фикстури ({FIX[0].stem[6:]} → {FIX[-1].stem[6:]})")
print()

print("── редът в main.py: новини → макро бриф ──")
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
i_news = main_src.index("news_aggregator.significant_news()")
i_macro = main_src.index("ai_brief.macro_and_sector_brief(")
assert i_news < i_macro, "новините трябва да се подберат ПРЕДИ макро брифа"
assert "macro_and_sector_brief(macro, rotation, thermo, news=news)" in main_src
assert main_src.count("news_aggregator.significant_news()") == 1                  # не се вика втори път след брифа
seg = main_src[i_news - 400:i_macro]
assert "try:" in seg and "except Exception" in seg and "news = []" in seg         # graceful: провал → без новини
print("  ✓ significant_news() е преди macro_and_sector_brief(), вика се веднъж, в try/except (при провал news = [])")
print()

print("── промптът (подменен _call_claude, РЕАЛНИ новини от 02.10) ──")
seen = {}
def fake(system, user, max_tokens=0):
    seen["user"] = user
    return json.dumps({"macro_brief": "x", "sector_logic": [], "regime_comment": "y"})
ai_brief._call_claude = fake
th = {"regime": "Defensive", "indicators": []}

ai_brief.macro_and_sector_brief({}, [], th, news=REAL)
u = seen["user"]
assert "ЗНАЧИМИ НОВИНИ ЗА ДЕНЯ" in u
for n in REAL:
    assert n["headline"] in u and n["why"] in u, n["headline"]                  # всяко заглавие и неговото why
assert "НЕ измисляй други новини" in u
assert u.index("ЗНАЧИМИ НОВИНИ ЗА ДЕНЯ") > u.index("СЕКТОРНА РОТАЦИЯ") and u.index("ЗНАЧИМИ НОВИНИ ЗА ДЕНЯ") < u.index("ВАЖНО за числа")
assert len(REAL) == 8
print(f"  ✓ и осемте РЕАЛНИ новини (headline + why) са в промпта, след секторната ротация и преди правилата за числата")

for label, val in (("None", None), ("[]", []), ("без заглавие (СИНТЕТИЧНО)", [{"why": "само причина"}, {}])):
    seen.clear()
    r = ai_brief.macro_and_sector_brief({}, [], th, news=val)
    assert "няма подбрани новини" in seen["user"] and "не измисляй новини" in seen["user"], label
    assert "ЗНАЧИМИ НОВИНИ ЗА ДЕНЯ (подбрани" not in seen["user"], label
    assert r.get("macro_brief") == "x"
print("  ✓ СИНТЕТИЧНО: news=None / [] / елементи без заглавие → промптът казва 'няма подбрани новини, не измисляй', брифът излиза")

seen.clear()
ai_brief.macro_and_sector_brief({}, [], th)                                        # стар вик без news= (обратна съвместимост)
assert "няма подбрани новини" in seen["user"]
print("  ✓ старото извикване без news= още работи (същото като празен списък)")
print()
print("Всички тестове минаха.")
