"""
04.11.2026 · четвърти преглед, С4: проверката на числата в макро разказа и датите. На 03.11 „(-0.31% за четири седмици към 28 октомври — в мъртвата зона)“ стана „… към — в мъртвата
зона“: narrative_sources оставя от ISO датите само годината, „28“ мина за число без опора, а датата беше вярна (Net Liquidity as_of 2026-10-28). Сега: дата с името на месеца, която
я има във входа (narrative_dates), не се проверява като число; дата без опора пада заедно с предлога.

РЕАЛНО: tests/fixtures/macro_story_2026-11-03.json — входовете на разказа и текстът на модела от брифа на 03.11 (бележката — вътре); това беше единствената поправка на числата
от въвеждането на проверката (30.10) до 03.11 — и тя беше фалшива.
СИНТЕТИЧНО (означено): изреченията в т. 3 (дата, която я няма във входа; число без опора до дата от входа).
Пускане: python test_macro_dates.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import ai_brief as ab

FX = json.loads((ROOT / "tests" / "fixtures" / "macro_story_2026-11-03.json").read_text(encoding="utf-8"))
args = (FX["macro"], FX["rotation"], FX["thermometer"], FX["news"], FX["crypto"])
vals, dates = ab.narrative_sources(*args), ab.narrative_dates(*args)

print("── 1. датите от входа ──")
assert (28, 10) in dates and (30, 10) in dates, sorted(dates)                    # Net Liquidity 2026-10-28, SOFR − IORB 2026-10-30
print(f"  ✓ {len(dates)} дати във входа, сред тях 28.10 (Net Liquidity) и 30.10 (SOFR − IORB)")

print("── 2. РЕАЛНИЯТ разказ от 03.11 ──")
old_text, old_fixed = ab.check_narrative_numbers(FX["macro_brief_model"], vals)           # както до 04.11 (без датите)
assert [f["removed"] for f in old_fixed] == [["28 октомври"]] and "към — в мъртвата зона" in old_text                     # възпроизвежда живото 03.11
new_text, fixed = ab.check_narrative_numbers(FX["macro_brief_model"], vals, dates)
assert fixed == [] and new_text == FX["macro_brief_model"].replace("\n\n", "\n\n"), fixed
assert "(-0.31% за четири седмици към 28 октомври — в мъртвата зона)" in new_text
print("  ✓ до 04.11 — „към — в мъртвата зона“ (възпроизведено); сега — 0 поправки, изречението остава цяло")

print("── 3. дата без опора — пада с предлога; числото до дата от входа — проверява се както досега ──")
t, f = ab.check_narrative_numbers("Ликвидността на Фед е практически непроменена (-0.31% за четири седмици към 27 октомври — в мъртвата зона).", vals, dates)
assert t == "Ликвидността на Фед е практически непроменена (-0.31% за четири седмици — в мъртвата зона).", t
assert f[0]["removed"] == ["към 27 октомври"], f
t, f = ab.check_narrative_numbers("SOFR − IORB стои на +7.7 б.п. към 30 октомври, на 93-ти перцентил.", vals, dates)
assert f and "7.7" in f[0]["removed"][0] and (t is None or "30 октомври" in (f[0]["kept"] or "30 октомври")), (t, f)
print("  ✓ „към 27 октомври“ (няма такава дата във входа) — махнато цяло; „+7.7 б.п.“ (без опора) — махнато, датата 30 октомври не се брои")
print("\n✅ test_macro_dates: всичко мина")
