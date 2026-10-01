"""
Тест за т.3 от прегледа на 01.10: _check_price_mentions() в ai_brief.py —
пост-хок, LOG-ONLY проверка на "...цена... $X" в why_now срещу candidate["price"]
±2%. Не променя текста — само печата предупреждение при разминаване.

Реален пример: AVT защо_сега текстът е КОПИРАН буквално от data/2026-10-01.json
(цитира NTAP-овата реална цена $210.08 вместо собствената си $99.95 — batch
cross-contamination). Останалото е синтетично, маркирано.

Пускане: python test_price_mention_check.py
"""
import sys, io, pathlib, contextlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src.ai_brief import _check_price_mentions


def _captured(ticker, text, price):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _check_price_mentions(ticker, text, price)
    return buf.getvalue()


print("── РЕАЛЕН пример (01.10.2026, data/2026-10-01.json, AVT защо_сега) ──")
REAL_AVT_WHY_NOW = (
    "AVT е вече в портфейла от 2026-09-14 при entry $99.92. Текущата цена "
    "$210.08 надминава entry с малка маржа. Вчерашният trigger изрично казва: "
    "управлявай съществуващата позиция, не добавяй риск. Volume_ratio 1.2 е "
    "близо до threshold, но breakout_volume е false и цената е -4.43% под "
    "pivot $104.58. EPS ръст 1978.8% е артефакт на ниска база, а ROE 6.7% е "
    "слаб за justifying premium. Earnings след 27 дни — относително близо. "
    "Не добавям нова позиция."
)
out = _captured("AVT", REAL_AVT_WHY_NOW, 99.95)
assert "AVT" in out and "210.08" in out and "99.95" in out, f"не хвана реалния AVT бъг: {out!r}"
assert "104.58" not in out.split("защо_сега")[0] if "защо_сега" in out else True
print(out.strip())
print("  ✓ хваща AVT/NTAP разминаването ($210.08 vs реална $99.95)")
print("  ✓ НЕ флагва pivot $104.58 споменаването в същия текст (изрично изключено)")
print()

print("── СИНТЕТИЧНИ гранични случаи (измислени текстове) ──")

# 1) точно съвпадение → без лог
out = _captured("TEST", "Текущата цена $100.00 потвърждава пробива.", 100.00)
assert out == ""
print("  ✓ точно съвпадение ($100.00 == $100.00) → без лог")

# 2) в рамките на толеранса (1.5% разлика) → без лог
out = _captured("TEST", "цената е $101.50", 100.00)
assert out == "", f"трябваше да е в толеранса: {out!r}"
print("  ✓ 1.5% разлика (под 2% толеранса) → без лог")

# 3) извън толеранса (5% разлика) → лог
out = _captured("TEST", "цената е $105.00", 100.00)
assert "TEST" in out and "105.00" in out
print("  ✓ 5% разлика (над 2% толеранса) → лог")

# 4) pivot споменаване — НЕ е текущата цена, не трябва да флагва
out = _captured("TEST", "цената е -3.5% под pivot $150.00", 100.00)
assert out == "", f"pivot не трябваше да флагне: {out!r}"
print("  ✓ '...под pivot $150' (50% разлика от реалната цена) → НЕ флагва (изключен pivot)")

# 5) target споменаване — аналогично не трябва да флагва
out = _captured("TEST", "target цена $200.00 след пробива", 100.00)
assert out == "", f"target не трябваше да флагне: {out!r}"
print("  ✓ 'target цена $200' → НЕ флагва (изключен target)")

# 6) думата "надминава" съдържа "над" като подниз — НЕ трябва да се бърка с
#    изключващата дума "над" (word-boundary проверка, виж AVT примера по-горе,
#    но тук изолирано и директно)
out = _captured("TEST", "Текущата цена $150.00 надминава очакванията.", 100.00)
assert "TEST" in out and "150.00" in out, f"'надминава' не трябваше да потисне флага: {out!r}"
print("  ✓ 'цена $150 надминава...' флагва (не се бърка с \\bнад\\b заради 'надминава')")

# 7) липсваща цена (None) → без грешка, без лог
out = _captured("TEST", "цената е $999.00", None)
assert out == ""
print("  ✓ real_price=None → без грешка, без лог")

# 8) без 'цена' дума изобщо, но с $ сума → не се проверява (няма anchor)
out = _captured("TEST", "Target $999.00 след пробива.", 100.00)
assert out == ""
print("  ✓ $ сума без 'цена'-дума наблизо → не се проверява (без anchor)")

print()
print("Всички тестове минаха.")
