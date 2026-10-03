"""
Пакет 4а · т.5 (2026-10-03): AI извикванията за контекста на short кандидатите са спрени (няма визуализация);
скрийнърът, кандидатите и short_tracker остават. СИНТЕТИЧНИ кандидати и сектори; Claude е подменен с брояч.
Пускане: python test_short_ai.py
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import main as brief_main, ai_brief

calls = []
ai_brief.short_thesis_global_context = lambda sector, news: calls.append(sector) or {"summary": f"ctx {sector}"}
cands = [{"ticker": "AAA", "lagging_sector": "Energy"}, {"ticker": "BBB", "lagging_sector": "Utilities"},
         {"ticker": "CCC", "lagging_sector": "Materials"}]
laggards = [{"sector": s} for s in ("Energy", "Real Estate", "Utilities", "Materials", "Staples")]

print("── по подразбиране: нито едно платено извикване ──")
assert config.ENABLE_SHORT_AI_CONTEXT is False
assert brief_main._short_global_context(cands, laggards, []) == {} and calls == []
print("  ✓ ENABLE_SHORT_AI_CONTEXT=0 → 0 извиквания към Claude, празен контекст; кандидатите си остават")

print("── включен (за когато има визуализация): старото поведение е запазено ──")
config.ENABLE_SHORT_AI_CONTEXT = True
try:
    ctx = brief_main._short_global_context(cands, laggards, [])
finally:
    config.ENABLE_SHORT_AI_CONTEXT = False
# първите MAX_LAGGARD_SECTORS_FOR_AI_CONTEXT=3 лагиращи сектора, и то само тези с кандидати: Energy, Utilities (Real Estate няма)
assert calls == ["Energy", "Utilities"] and set(ctx) == {"Energy", "Utilities"}
assert brief_main._short_global_context([], laggards, []) == {}
print("  ✓ при включен превключвател — само capped лагиращите сектори с кандидати (Energy, Utilities), без кандидати → 0 извиквания")

src = (ROOT / "src/main.py").read_text(encoding="utf-8")
assert src.count("ai_brief.short_thesis_global_context(") == 1                 # единственото място — зад превключвателя
print("  ✓ short_thesis_global_context се вика от едно място — зад превключвателя")
print()
print("Всички тестове минаха.")
