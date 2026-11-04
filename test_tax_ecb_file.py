"""
05.11.2026 (tax-fixes): tools/ecb_rates.py — курсовете на ЕЦБ до данъчната страница (docs/eurofxref-hist.csv; daily_brief.yml го опреснява след брифа).
СИНТЕТИЧЕН архив (не реалният eurofxref-hist.zip — средата за разработка не стига ecb.europa.eu); без мрежа, без запис в docs/.
Проверява: пълен и свеж файл → текстът; стар (над 10 дни), кратък, без USD, два CSV в архива → отказ (старият файл остава); main() при провал → код 0, файлът непокътнат.
"""
import io, sys, zipfile, datetime, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT / "tools"))
import ecb_rates

TODAY = datetime.date(2026, 11, 5)
def make(days=6000, newest=datetime.date(2026, 11, 4), head="Date,USD,JPY,", files=1):
    rows = [head] + [f"{newest - datetime.timedelta(days=i)},1.1{i % 10},150.0," for i in range(days)]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k in range(files):
            z.writestr(f"eurofxref-hist{k or ''}.csv", "\n".join(rows) + "\n")
    return b.getvalue()

print("── 1. пълен и свеж файл ──")
t = ecb_rates.extract(make(), TODAY)
assert t.startswith("Date,USD,JPY,") and t.count("\n") == 6001
print("  ✓ 6000 дни до 04.11.2026 → приет")

print("── 2. отказ ──")
for name, data in [("стар", make(newest=datetime.date(2026, 10, 20))), ("кратък", make(days=100)), ("без USD", make(head="Date,JPY,GBP,")), ("два CSV", make(files=2))]:
    try:
        ecb_rates.extract(data, TODAY); raise AssertionError(name + " — приет")
    except ValueError as e:
        print(f"  ✓ {name}: {e}")

print("── 3. main() при провал (няма мрежа в тестовете) — код 0, файлът не се пипа ──")
with tempfile.TemporaryDirectory() as d:
    out = pathlib.Path(d) / "eurofxref-hist.csv"; out.write_text("стар файл", encoding="utf-8")
    assert ecb_rates.main(str(out)) == 0 and out.read_text(encoding="utf-8") == "стар файл" and not (pathlib.Path(d) / "eurofxref-hist.csv.tmp").exists()
yml = (ROOT / ".github" / "workflows" / "daily_brief.yml").read_text(encoding="utf-8")
i = yml.index("python tools/ecb_rates.py docs/eurofxref-hist.csv")
assert "continue-on-error: true" in yml[i - 200:i] and i < yml.index("git add docs/ data/")
print("  ✓ провал → код 0, старият файл остава; в daily_brief.yml — преди commit-а, continue-on-error")
print("\n✅ test_tax_ecb_file: всичко мина")
