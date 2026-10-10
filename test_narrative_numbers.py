"""
Втори преглед (10.10.2026) · числата в AI наративите срещу кода (ai_brief.verify_narrative_numbers, вика се от merge_narratives).

Сума в $, която я няма сред числата на самия тикър, но е точно ключово ниво на ДРУГ тикър от същия бриф → изречението (why_now) / точката (risks, catalysts) се маха.
Измерено върху историята (679 карти, 2 241 суми в $): правилото удря точно 2 пъти, и двата истински — AVT 01.10 (цената на NTAP $210.08) и NTAP 09.10 (стопът на FTNT
$164.43); по-широкото "няма го в картата" би махнало ~185 легитимни изречения (разлики, макро, закръглени цели).
РЕАЛНО: tests/fixtures/narrative_numbers_2026-10.json — картите от брифовете на 01.10 и 09.10 (цени, нива, сетъп и публикуваният AI текст).
СИНТЕТИЧНО: нищо (освен подменения контрол в т.3).
Пускане: python test_narrative_numbers.py
"""
import sys, json, pathlib, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "narrative_numbers_2026-10.json").read_text(encoding="utf-8"))


def run(day):
    cards = copy.deepcopy(FX["briefs"][day])
    with contextlib.redirect_stdout(io.StringIO()) as log:
        diag = list(ai_brief.verify_narrative_numbers(cards))
    return cards, diag, log.getvalue()


print("── 1. РЕАЛНИЯТ 01.10: AVT цитира цената на NTAP ──")
orig = {c["ticker"]: c for c in FX["briefs"]["2026-10-01"]}
cards, diag, log = run("2026-10-01")
assert [(d["ticker"], d["field"], d["amount"], d["from"]) for d in diag] == [("AVT", "why_now", 210.08, ["NTAP"])], diag
avt = next(c for c in cards if c["ticker"] == "AVT")
assert "$210.08" not in avt["ai"]["why_now"] and "$210.08" in orig["AVT"]["ai"]["why_now"] and len(avt["ai"]["why_now"]) > 50
assert all(c["ai"] == orig[c["ticker"]]["ai"] for c in cards if c["ticker"] != "AVT")
assert "AVT: чуждо число $210.08 (ниво на NTAP) в why_now" in log
print("  ✓ изречението с «Текущата цена $210.08» (цената на NTAP) е махнато от why_now на AVT, останалото остава; другите 4 карти — непроменени")

print()
print("── 2. РЕАЛНИЯТ 09.10: NTAP цитира стопа на FTNT ──")
orig = {c["ticker"]: c for c in FX["briefs"]["2026-10-09"]}
cards, diag, log = run("2026-10-09")
assert [(d["ticker"], d["field"], d["amount"], d["from"]) for d in diag] == [("NTAP", "risks", 164.43, ["FTNT"])], diag
ntap = next(c for c in cards if c["ticker"] == "NTAP")
assert len(ntap["ai"]["risks"]) == len(orig["NTAP"]["ai"]["risks"]) - 1 and not any("164.43" in r for r in ntap["ai"]["risks"])
assert next(c for c in cards if c["ticker"] == "FTNT")["ai"] == orig["FTNT"]["ai"]                  # FTNT си цитира собствения стоп — не се пипа
assert all(c["ai"] == orig[c["ticker"]]["ai"] for c in cards if c["ticker"] != "NTAP")
print("  ✓ рискът «стопът ($164.43 — wait, $188.98)…» на NTAP е махнат; FTNT (собственият му стоп $164.43) и останалите 5 карти — непроменени")

print()
print("── 3. собствено число и чуждо число, което съвпада и със собственото → не се маха ──")
c1 = {"ticker": "AAA", "price": 100.0, "pivot": 98.0, "ai": {"why_now": "Цена $100.00 над pivot $98.00.", "risks": ["стоп $98.00"]}}
c2 = {"ticker": "BBB", "price": 98.0, "ai": {"why_now": "x"}}
with contextlib.redirect_stdout(io.StringIO()):
    d = ai_brief.verify_narrative_numbers([c1, c2])
assert d == [] and c1["ai"]["why_now"] == "Цена $100.00 над pivot $98.00." and c1["ai"]["risks"] == ["стоп $98.00"]
print("  ✓ СИНТЕТИЧНО: $98.00 е и pivot на AAA, и цена на BBB → не се маха (числото е и собствено)")

src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert '"narrative_checks": list(ai_brief.NARRATIVE_DIAG)' in src
print("  ✓ брифът записва narrative_checks")
print()
print("Всички тестове минаха.")
