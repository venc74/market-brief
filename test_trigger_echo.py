"""
13.10.2026 · why_now без преписания текст за задействан запис в buy-stop книгата — той е на картата от кода (setup.trigger_text) и се четеше два пъти.

Случаят (РЕАЛЕН, брифът от 13.10): EXPD — "… Setup е задействан на 09.10 по $194.59 · стоп $181.53 · цел 2R $220.71 · текущо -0.1R — изпълнен сигнал от книгата, не нов вход."; ANET —
"…директен бенефициент; setup-ът е задействан на 09.10 по $215.38 (buy-stop от 09.10) · стоп $197.70 …, не нов вход." В историята: 2 от 2 карти със задействан запис.

РЕАЛНО: tests/fixtures/trigger_echo_2026-10-13.json (setup и why_now на EXPD, ANET и ZBRA от 13.10). СИНТЕТИЧНО (означено): текстът без "не нов вход", картата без запис с подобна фраза.
Пускане: python test_trigger_echo.py
"""
import sys, json, copy, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import ai_brief

FX = {c["ticker"]: c for c in json.loads((ROOT / "tests" / "fixtures" / "trigger_echo_2026-10-13.json").read_text(encoding="utf-8"))["cards"]}

print("── 1. РЕАЛНИТЕ текстове от 13.10 ──")
e, a = FX["EXPD"]["why_now"], FX["ANET"]["why_now"]
ne, na = ai_brief.strip_trigger_echo(e), ai_brief.strip_trigger_echo(a)
assert ne == e[:e.index(" Setup е задействан")] and ne.endswith("ограничен upside консенсус.")
assert na == a[:a.index("; setup-ът е задействан")] + "." and na.endswith("е директен бенефициент.")
assert "задейств" not in ne + na and "не нов вход" not in ne + na
assert "Задействан на 09.10 по $194.59" in FX["EXPD"]["setup"]["trigger_text"]                          # кодовият текст на картата остава
print("  ✓ EXPD: …", ne[-60:])
print("  ✓ ANET: …", na[-60:])

print()
print("── 2. само картите със задействан запис; без повторение — без промяна ──")
cards = [{"ticker": t, "setup": FX[t]["setup"], "ai": {"why_now": FX[t]["why_now"]}} for t in ("EXPD", "ANET", "ZBRA")]
z = FX["ZBRA"]["why_now"]
fake = {"ticker": "XX", "setup": {"kind": "below_pivot", "triggered": None}, "ai": {"why_now": "Би бил задействан на 15.10 по $10.00, ако High стигне нивото."}}   # СИНТЕТИЧНО: без запис
done = ai_brief.strip_trigger_echo_in_narratives(cards + [fake])
assert done == ["EXPD", "ANET"] and cards[2]["ai"]["why_now"] == z and fake["ai"]["why_now"].startswith("Би бил задействан")
syn = "Добра база. Setup-ът е задействан на 09.10 по $194.59 и чака развитие. RS е висок."                     # СИНТЕТИЧНО: без "не нов вход" → до края на изречението
assert ai_brief.strip_trigger_echo(syn) == "Добра база. RS е висок."
assert ai_brief.strip_trigger_echo("Без повторение.") == "Без повторение."
print("  ✓ ZBRA (без запис) и карта без запис с подобна фраза — непроменени; без 'не нов вход' — маха се до края на изречението")

print()
print("── 3. main: след merge_narratives ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.index("ai_brief.merge_narratives(candidates, narratives)") < src.index("ai_brief.strip_trigger_echo_in_narratives(candidates)")
print("  ✓")
print()
print("Всички тестове минаха.")
