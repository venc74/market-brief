"""
Тест за т.2 от 02.10: подробен лог за смесени думи (латиница+кирилица в един
токен). 17.11.2026 (пакет 1, т. 7): и поправка — латинските букви → кирилица, ако така се получава позната дума („Zад“ → „Зад“); иначе изречението пада. РЕАЛНИ изречения: извлечени буквално от
data/2026-10-02.json (Cotton direct, news). Синтетичните са маркирани.

Пускане: python test_mixed_words_log.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, io, json, re, pathlib, contextlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from src import ai_brief as ai

REAL = json.load(open(pathlib.Path(__file__).parent / "tests" / "fixtures" / "brief_2026-10-02.json", encoding="utf-8"))


def strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)
    elif isinstance(o, str):
        yield o


def run(obj):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = ai._fix_text(obj)
    return out, buf.getvalue()


print("── РЕАЛНИ изречения (02.10.2026, data/2026-10-02.json) ──")
for word in ("directно", "неpubblично", "пolicymakers"):
    s = next(x for x in strings(REAL) if word in x)
    out, log = run({"x": s})
    assert word not in out["x"] and ("смесени букви в дума поправени" in log or "махнато цялото изречение" in log), word     # 17.11.2026 (т. 7): поправка или изречението пада
    line = next((l for l in log.splitlines() if "смесена дума" in l and f"'{word}'" in l), None)
    assert line, f"няма подробен лог за {word!r}:\n{log}"
    print("  " + line)
print("  ✓ и трите: подробен ред (форма + какво би дал auto-space + контекст); от 17.11 — „directно“ → „директно“, другите две — изречението пада")
print()

print("── СИНТЕТИЧНИ (измислени входове) ──")
out, log = run(["Само кирилица без смесване", "Pure English words only"])
assert "смесена дума" not in log and "смесено писмо" not in log
print("  ✓ чисти низове → без лог")

# една и съща дума два пъти → един подробен ред (dedup)
out, log = run(["това е directно добре", "и пак directно друго"])
assert log.count("смесена дума 'directно'") == 1 and out == ["това е директно добре", "и пак директно друго"]          # 17.11.2026: поправено („директно“ е в речника)
print("  ✓ повторена дума → един подробен ред")

# 'момentum' (кир+лат): форма
out, log = run(["силен момentum при пробив"])
assert "кир«мом»+лат«entum»" in log or "кир«мо»+лат«m»" in log or "смесена дума 'момentum'" in log
print("  ✓ 'момentum' → подробен ред")

# вече поправима дума (буква-двойник) → поправена, не е в подробния лог
out, log = run(["това секторa расте"])
assert out == ["това сектора расте"] and "смесена дума" not in log
print("  ✓ 'секторa' се поправя (стар клон), не влиза в подробния лог")
print()
print("Всички тестове минаха.")
