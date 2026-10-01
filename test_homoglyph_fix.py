"""
Тест за т.4 от прегледа на 01.10: самотен ASCII буква-двойник (_fix_homoglyphs)
+ "по-" суфикс извън историята (_check_po_suffix), в ai_brief.py.

Реални примери: самотното "e" и "по-ата" са КОПИРАНИ буквално от
data/2026-10-01.json. Останалото е синтетично (гранични случаи), маркирано.

Пускане: python test_homoglyph_fix.py
"""
import sys, io, pathlib, contextlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src import ai_brief as ai

print("── РЕАЛЕН пример (01.10.2026, самотно 'e') ──")
REAL_E_TEXT = ("се доходности при нормална крива (2s10s +0.41%, steepening) e "
               "характерна за demand-shock среда.")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out = ai._fix_homoglyphs(REAL_E_TEXT)
log = buf.getvalue()
assert out == REAL_E_TEXT, f"не трябваше да поправи (съседната дума 'steepening)' не е чисто кирилска): {out!r}"
print(f"  вход непроменен: {out == REAL_E_TEXT}")
print(f"  лог: {log.strip() or '(няма — виж бележка)'}")
# самото 'e' влиза в _HYBRIDS, не се печата директно ред за него тук (само
# обобщен ред от _fix_text/_parse_json) — проверяваме директно, че е в _HYBRIDS
ai._HYBRIDS.clear()
ai._fix_homoglyphs(REAL_E_TEXT)
assert "e" in ai._HYBRIDS, f"самотното 'e' трябваше да влезе в _HYBRIDS (лог), получено {ai._HYBRIDS}"
print("  ✓ 'e' между 'steepening)' (не чисто кирилска) и 'характерна' → НЕ се поправя, влиза в _HYBRIDS (лог)")
ai._HYBRIDS.clear()
print()

print("── СИНТЕТИЧЕН пример: 'e' между ДВЕ чисто кирилски думи → авто-поправка ──")
SYNTH_TEXT = "спредът се разкривява e директно положително за сектора"
out = ai._fix_homoglyphs(SYNTH_TEXT)
assert out == "спредът се разкривява е директно положително за сектора", out
print(f"  '{SYNTH_TEXT}'")
print(f"  → '{out}'")
print("  ✓ 'e' → 'е' (двете съседни думи 'разкривява'/'директно' са чисто кирилски)")
print()

print("── СИНТЕТИЧНИ гранични случаи ──")

# тикър до кирилска дума — НЕ се пипа (съседна дума не е кирилска)
ai._HYBRIDS.clear()
out = ai._fix_homoglyphs("анализ на AAPL e положителен")
assert out == "анализ на AAPL e положителен"
assert "e" in ai._HYBRIDS
print("  ✓ 'AAPL e положителен' (тикър до 'e') → не се пипа, само лог")
ai._HYBRIDS.clear()

# в началото на изречението (няма предходна дума) — не се пипа
out = ai._fix_homoglyphs("e важно да отбележим това")
assert out == "e важно да отбележим това"
print("  ✓ 'e' в началото на низа (без предходна дума) → не се пипа")

# многосимволна ASCII 'дума' (легитимен тикър/термин) — поведението от преди, непроменено
out = ai._fix_homoglyphs("анализ на NVDA е положителен")
assert out == "анализ на NVDA е положителен"
print("  ✓ многосимволен ASCII токен (NVDA) остава непипнат, както досега")

# съществуващият hybrid-случай (напр. 'benefitват') остава непроменен от преди
out = ai._fix_homoglyphs("компанията benefitват от това")
assert out == "компанията benefitват от това"
print("  ✓ стар случай 'benefitват' (наставка, не буква-двойник) остава непипнат")

# РЕГРЕСИОНЕН тест — открито при прогон на цялата история (виж commit):
# "x"/"P"/"E"/"A"/"M"/"O" допрени до цифра или /&-'. НЕ са буква-двойници,
# а multiplier нотация или английски абревиатури. Първи вариант на фикса
# (без този guard) чупеше "1.5x" на "1.5х" навсякъде в историята.
for text in (
    "обем >1.5x среден — технически пробив",       # multiplier, не буква
    "EPS +87% YoY при P/E 13.4 е изключително",      # P/E ratio
    "Convenience store M&A consolidation trend",     # M&A
    "класически O'Neil setup в правилния сектор",    # O'Neil (апостроф)
    "J.B. Hunt е един от най-големите",               # инициали с точки
):
    out = ai._fix_homoglyphs(text)
    assert out == text, f"регресия — текстът не трябваше да се пипа: {text!r} → {out!r}"
print("  ✓ регресия: '1.5x'/'P/E'/'M&A'/\"O'Neil\"/'J.B.' остават непипнати (не са буква-двойници)")
print()

print("── РЕАЛЕН пример (01.10.2026, 'по-ата') — с monkeypatch-нат корпус ──")
# _bg_vocab() е @lru_cache и ЧЕТЕ от docs/data/, което ВЕЧЕ съдържа днешния
# 01.10 файл (committed) — значи "ата" там вече е count=1 (самото случило се
# веднъж произшествие). За да тестваме детерминирано РЕАЛНИЯ момент на
# проверка (корпус от ВСИЧКИ ПРЕДИШНИ дни, преди днешния да съществува),
# monkeypatch-ваме _bg_vocab с фиксиран корпус — "високата" позната (симулира
# реалната история), "ата" отсъства (симулира първата поява, какъвто е и
# реалният случай, измерено в прегледа: cyr.get('ата', без 01.10 файла) == 0).
orig_bg_vocab = ai._bg_vocab
ai._bg_vocab = lambda: ({"високата": 37, "доходност": 120, "директно": 44}, {})
try:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ai._check_po_suffix("реинвестират премийния float и по-ата доходност директно разширява")
    log = buf.getvalue()
    assert "по-ата" in log, f"не хвана 'по-ата': {log!r}"
    print(f"  {log.strip()}")
    print("  ✓ 'по-ата' флагнат (суфиксът 'ата' не е в корпуса)")
    print()

    print("── СИНТЕТИЧЕН 'по-' граничен случай: позната дума → без лог ──")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ai._check_po_suffix("риск за по-високата доходност")
    log = buf.getvalue()
    assert log == "", f"позната дума не трябваше да флагне: {log!r}"
    print("  ✓ 'по-високата' (позната дума, count=37 в monkeypatch-натия корпус) → без лог")
finally:
    ai._bg_vocab = orig_bg_vocab

print()
print("Всички тестове минаха.")
