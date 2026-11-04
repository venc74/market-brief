"""
04.11.2026 (tax-fixes): страницата docs/tax.html в Chromium (Playwright през node — tests/tax_page_check.js) върху СИНТЕТИЧНИТЕ файлове от tests/fixtures/tax/.
Проверява: числото най-горе = ръчната сметка от test_tax_core (2023: 2 178.57 €) и по трите пътя за курсовете (файл на ЕЦБ, „ЕЦБ API“, „frankfurter“ — отговорите са от синтетичната
таблица); нула заявки при отваряне и нула с файла на ЕЦБ; без курсове — предупреждение и непълно число, не NaN; продажба без покупка — предупреждение; XSS — опасно име на файл
и тикър не се изпълняват; българската част е скрита. Без node или без playwright — изрично SKIP с причината и код 0.
Пускане: python test_tax_page.py
"""
import sys, json, shutil, pathlib, subprocess
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
if subprocess.run([NODE, "-e", "require('playwright')"], capture_output=True).returncode != 0:
    print("SKIP: няма playwright за node — страницата не е проверена в браузър (сметките — в test_tax_core)"); sys.exit(0)
p = subprocess.run([NODE, str(ROOT / "tests" / "tax_page_check.js")], capture_output=True, text=True, timeout=300)
if p.returncode != 0 and "Executable doesn't exist" in p.stderr:
    print("SKIP: playwright няма браузър в тази среда"); sys.exit(0)
assert p.returncode == 0, p.stderr[-2000:]
d = json.loads(p.stdout)
lot1, lot2 = 1001 / 1.10, 1501 / 1.20
total23 = (2998 / 1.08 - lot1 - lot2 / 2) + (1050 / 1.08 - 800 / 1.10) + 200 + 298 * 0.7 + 248.95 / 1.08 + 40 / 1.08 + 12.34 + 5 / 1.08    # ръчно — както в test_tax_core

print("── 1. числото най-горе по трите пътя за курсовете ──")
for k in ("withEcbFile", "ecbApi", "frankfurter"):
    s = d[k]
    assert abs(s["headline"] - total23) < 1e-6 and s["big"].replace(" ", " ") == "2 178.57 €", (k, s["headline"], s["big"])
    assert s["unmatched"] == ["GHOST"] and "Липсва покупката: за GHOST" in s["warnings"] and not s["errors"] and not s["bgVisible"], k
print(f"  ✓ 2023: {total23:.2f} € — с файла на ЕЦБ, през „ЕЦБ API“ и през „frankfurter“ (синтетични отговори); GHOST — „липсва покупката“; българската част — скрита")

print("── 2. мрежата ──")
assert all(d[k]["atLoad"] == 0 for k in d)                                                     # нито една заявка при отваряне (без Google Fonts)
assert d["withEcbFile"]["requests"] == []                                                      # с файла на ЕЦБ — нито една заявка
assert len(d["ecbApi"]["requests"]) == 1 and "startPeriod=2020-02-21" in d["ecbApi"]["requests"][0]   # една заявка на валута за целия период
assert all(("data-api.ecb.europa.eu" in u or "api.frankfurter.app" in u) and "from=EUR" in u or "data-api" in u for u in d["frankfurter"]["requests"])
print("  ✓ 0 заявки при отваряне; 0 с файла на ЕЦБ; 1 заявка към ЕЦБ за USD за целия период; frankfurter — from=EUR (правилната посока)")

print("── 3. без курсове; XSS ──")
nr = d["noRates"]
assert abs(nr["headline"] - (200 + 298 * 0.7 + 12.34)) < 1e-6 and "Липсва курс" in nr["warnings"] and "NaN" not in nr["big"], nr["big"]
assert d["xss"]["xss"] is None and not d["xss"]["errors"] and abs(d["xss"]["headline"] - 2) < 1e-9
print("  ✓ без курсове — „Липсва курс“ и само записите в EUR (420.94 €), не NaN; опасно име на файл и тикър — показани като текст, не изпълнени")
print("\n✅ test_tax_page: всичко мина")
