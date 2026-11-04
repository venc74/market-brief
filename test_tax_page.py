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

print("── 1. числото най-горе по всички пътища за курсовете ──")
for k in ("withEcbFile", "site", "ecbApi", "ecbRetry", "frankfurter"):
    s = d[k]
    assert abs(s["headline"] - total23) < 1e-6 and s["big"].replace("\u202f", " ") == "2 178.57 €", (k, s["headline"], s["big"])
    assert s["unmatched"] == ["GHOST"] and "Липсва покупката: за GHOST" in s["warnings"] and not s["errors"] and not s["bgVisible"], k
print(f"  ✓ 2023: {total23:.2f} € — качен файл на ЕЦБ, файлът до страницата, ЕЦБ API, ЕЦБ API с повторен опит, frankfurter.dev (синтетични отговори); GHOST — „липсва покупката“")

print("── 2. мрежата и откъде са курсовете (05.11.2026) ──")
assert all(d[k]["atLoad"] == 0 for k in d)                                                     # нито една заявка при отваряне (без Google Fonts)
assert d["withEcbFile"]["requests"] == [] and d["withEcbFile"]["site"] == [] and "качения файл на ЕЦБ" in d["withEcbFile"]["warnings"]
assert d["site"]["requests"] == [] and len(d["site"]["site"]) == 1 and "файла на ЕЦБ до страницата (eurofxref-hist.csv, до 2026-12-31)" in d["site"]["warnings"]
ecb = d["ecbApi"]["requests"]
assert len(ecb) == 7 and all("data-api.ecb.europa.eu" in u for u in ecb) and "startPeriod=2020-02-21&endPeriod=2020-12-31" in ecb[0], ecb   # по година: 2020 … 2026
assert all(u[u.index("startPeriod=") + 12:][:4] == u[u.index("endPeriod=") + 10:][:4] for u in ecb) and "ЕЦБ API (7 г.)" in d["ecbApi"]["warnings"]
assert set(d["ecbRetry"]["tries"].values()) == {2} and len(d["ecbRetry"]["tries"]) == 7 and "ЕЦБ API (7 г.)" in d["ecbRetry"]["warnings"]   # първият опит 503 → повторен
fr = [u for u in d["frankfurter"]["requests"] if "frankfurter" in u]
assert len(fr) == 7 and all(u.startswith("https://api.frankfurter.dev/v1/") and "base=EUR&symbols=USD" in u for u in fr), fr     # не .app (пренасочва без CORS)
assert not any("frankfurter.app" in u for k in d for u in d[k]["requests"]) and "frankfurter.dev — курсовете на ЕЦБ (7 г.)" in d["frankfurter"]["warnings"]
print("  ✓ 0 заявки при отваряне; качен файл → 0 заявки; файлът до страницата → 0 заявки навън; ЕЦБ по година (7), повторен опит при 503; frankfurter.dev base=EUR; страницата казва източника")

print("── 3. без курсове; XSS ──")
nr = d["noRates"]
assert abs(nr["headline"] - (200 + 298 * 0.7 + 12.34)) < 1e-6 and "Липсва курс" in nr["warnings"] and "NaN" not in nr["big"], nr["big"]
assert "не се изтеглиха: 2020" in nr["warnings"] and "качи eurofxref-hist.csv" in nr["warnings"]
assert d["xss"]["xss"] is None and not d["xss"]["errors"] and abs(d["xss"]["headline"] - 2) < 1e-9
print("  ✓ без курсове — „Липсва курс“ и само записите в EUR (420.94 €), не NaN; опасно име на файл и тикър — показани като текст, не изпълнени")
print("\n✅ test_tax_page: всичко мина")
