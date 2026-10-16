"""
16.10.2026 · т. 5 (трети преглед): регресия в regime_claims от 15.10 — ВЯРНОТО "само 1 червен индикатор е достатъчен за преход към Defensive (сега 0 червени)" беше заменено като
"твърди 1 червени, а кодът брои 0". Хипотетичен брой (последван от "е достатъчен / за преход / би / ще", предшестван от "ако / при / още") не е днешният; "(сега N червени)" се сверява.

РЕАЛНО: tests/fixtures/brief_2026-10-16.json — изречението от regime_claims_fixed (единствената записана поправка в историята) и термометърът (0 червени);
tests/fixtures/ai_macro_texts_2026-06-13_10-15.json — всичките 173 текста: флаговете остават точно петте верни (23.07, 20.08, 10.09, 08.10 ×2 … 15.10 ×2).
СИНТЕТИЧНО (маркирано): граничните изречения.
Пускане: python test_regime_hypothetical.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import regime_claims as rc

B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
FX = json.loads((ROOT / "tests" / "fixtures" / "ai_macro_texts_2026-06-13_10-15.json").read_text(encoding="utf-8"))["briefs"]
f = rc.facts(B["thermometer"])
assert len(f["groups"]["red"]) == 0

print("── 1. РЕАЛНОТО изречение от 16.10 ──")
fixed = B["ai_macro"]["regime_claims_fixed"]
assert [(x["code"], x["why"]) for x in fixed] == [("count", "твърди 1 червени, а кодът брои 0")]
sent = fixed[0]["sentence"]
assert sent == "Запасът до смяна е ограничен: само 1 червен индикатор е достатъчен за преход към Defensive (сега 0 червени)."
assert rc.check_sentence(sent, f) == [] and rc.clean(sent, f) == (sent, [])
print("  ✓ '…само 1 червен индикатор е достатъчен за преход към Defensive (сега 0 червени)' — вярно, остава")

print()
print("── 2. историята: 173 РЕАЛНИ текста ──")
hits = [(d, p["code"]) for d, b in FX.items() for fld in ("macro_brief", "regime_comment") if b.get(fld)
        for p in rc.check(b[fld], rc.facts({"indicators": b["indicators"]}))]
assert hits == [("2026-07-23", "rule"), ("2026-08-20", "rule"), ("2026-09-10", "rule"), ("2026-10-08", "member"), ("2026-10-08", "solo"), ("2026-10-15", "rule"), ("2026-10-15", "rule")], hits
print("  ✓ флаговете — непроменени (правилото 23.07/20.08/10.09/15.10, броенето 08.10)")

print()
print("── 3. граници (СИНТЕТИЧНИ изречения) ──")
codes = lambda s: [p["code"] for p in rc.check_sentence(s, f)]
assert codes("Запасът е малък: 1 червен индикатор е достатъчен за преход (сега 2 червени).") == ["count"]            # днешният брой в скобите се сверява
assert codes("Днес 1 червен индикатор (MOVE) държи режима.") == ["count"]                                              # днешен брой — грешен
assert codes("Ако се появи 1 червен индикатор, режимът ще стане Defensive.") == []
assert codes("При още 2 червени режимът би бил Cash.") == []
assert codes("Нов 1 червен би стигнал за Defensive.") == []
print("  ✓ '(сега 2 червени)' и 'днес 1 червен' — сверяват се; 'ако / при още / нов … би / ще' — хипотетични")
print("\n✅ test_regime_hypothetical: всичко мина")
