"""
04.11.2026 (tax-fixes): данъчният калкулатор docs/tax.html — сметките в docs/tax_core.js, през `node` (tests/tax_driver.js). Очакваните числа са сметнати НА РЪКА тук (Python), не взети от JS.
ВСИЧКИ входове са СИНТЕТИЧНИ — tests/fixtures/tax/ (бележката в README.md там): измислени сметки, тикъри, суми и курсове (ЕЦБ форматът, постоянен курс за година).
Без node — изрично SKIP с причината и код 0 (в CI node има).
Пускане: python test_tax_core.py
"""
import sys, json, shutil, pathlib, subprocess
ROOT = pathlib.Path(__file__).parent
FX = ROOT / "tests" / "fixtures" / "tax"
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node — tax_core.js не е изпълнен (в CI node има)")
    sys.exit(0)


def run(step, files, settings=None):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), step, json.dumps(settings or {})] + [str(FX / f) for f in files],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


IBKR = ["U1111111_2020.csv", "U1111111_2021.csv", "U1111111_2022.csv", "U1111111_2023.csv", "U1111111_2023 (1).csv", "U1111111_Q4_2023.csv", "U1111111_2026.csv"]
ALL = IBKR + ["broker2_export.csv", "crypto_me.csv", "crypto_spouse.csv", "loss_div.csv", "ecb_rates_synthetic.csv"]

print("── 1. разпознаване по съдържание (имената не значат нищо), дедупликация, „не е сметнато“ ──")
ing = run("ingest", list(reversed(ALL)))                                   # произволен ред
fmt = {f["name"]: (f["format"], f["account"]) for f in ing["files"]}
assert fmt["U1111111_2023 (1).csv"] == ("ibkr", "U1111111") and fmt["broker2_export.csv"] == ("standard", "B2") and fmt["ecb_rates_synthetic.csv"][0] == "ecb_rates", fmt
assert ing["rateCurrencies"] == ["USD", "JPY"] or set(ing["rateCurrencies"]) == {"USD", "JPY"}
recs = ing["records"]
trades = [r for r in recs if r["kind"] == "trade"]
# сделки: ACME ×4 (IBKR) + SPLT ×2 + XWLD ×2 + опция ×2 + Broker2 ×3 + крипто 5 + 2 + loss_div 4 — всяка ВЕДНЪЖ въпреки 2023 ×2 и Q4 2023
key = lambda r: (r["account"], r["sym"], r["date"], r["qty"])
assert len(trades) == len({key(r) for r in trades}) == 4 + 2 + 2 + 2 + 3 + 5 + 2 + 4, (len(trades), sorted({key(r) for r in trades}))
dup = {f["name"]: f["duplicates"] for f in ing["files"]}
assert sum(dup.values()) == 13 + 1, dup                                     # целият 2023 отчет повторен (13 записа: 6 сделки, 2 дивидента, 2 удържани, 3 лихви) + XWLD продажбата от Q4
assert [r["date"] for r in recs] == sorted(r["date"] for r in recs)          # подредба по дата
acme = [r for r in trades if r["sym"] == "ACME" and r["account"] == "U1111111"]
assert [(r["date"], r["qty"], r["price"], r["fee"], r["currency"]) for r in acme] == \
    [("2020-03-02", 10, 100, 1, "USD"), ("2021-05-03", 10, 150, 1, "USD"), ("2023-06-01", -15, 200, 2, "USD"), ("2026-02-02", -5, 120, 1, "USD")]
split = [r for r in recs if r["kind"] == "split"]
assert [(r["sym"], r["date"], r["ratio"]) for r in split] == [("SPLT", "2022-06-01", 4)]
assert [r["fundHint"] for r in trades if r["sym"] == "XWLD"] == [True, True]     # типът ETF от „Financial Instrument Information“
print(f"  ✓ {len(ing['files'])} файла по съдържание; {len(trades)} сделки — всяка веднъж (14 дубликата махнати); подредба по дата; сплитът и ETF типът — разпознати")

print("── 2. дивиденти, удържан данък, лихви от IBKR ──")
div = [(r["date"], r["amount"]) for r in recs if r["kind"] == "dividend" and r["sym"] == "ACME"]
wh = [(r["date"], r["amount"]) for r in recs if r["kind"] == "withholding"]
intr = [(r["date"], r["amount"], r["currency"]) for r in recs if r["kind"] == "interest"]
assert div == [("2023-03-15", 50), ("2023-04-20", -10)], div                 # сторното (−10) остава — до 04.11 се пропускаше
assert wh == [("2023-03-15", -7.5), ("2023-04-20", 1.5)], wh                  # върнатият данък (+1.5) е плюс, не минус; описанието без интервал („ACME(US…)“) — разпознато
assert intr == [("2023-07-05", 12.34, "EUR"), ("2023-08-03", 5, "USD"), ("2023-09-05", -3, "EUR")], intr
print("  ✓ сторното −10 и върнатият данък +1.5 — със знака си; „ACME(US…)“ без интервал — разпознато; лихвите (кредитна и дебитна)")

print("── 3. „не е сметнато“ — нищо не се пропуска тихо ──")
sk = ing["skipped"]
why = {(s["section"], s["what"]) for s in sk}
assert ("Trades", "EUR.USD") in why                                         # Forex
assert ("Fees", "NYSE Market Data") in why
assert any(s["section"] == "Corporate Actions" and "OLDCO" in s["what"] for s in sk)
assert any(s["section"] == "Withholding Tax" and "Interest" in s["what"] for s in sk)  # данък върху лихва — без тикър
assert not any(s["section"] in ("Mark-to-Market Performance Summary", "Cash Report") for s in sk)   # обобщенията не са сделки
assert sum(1 for s in sk if (s["section"], s["what"]) == ("Trades", "EUR.USD")) == 1                # и в „не е сметнато“ — веднъж (не за всеки дубликат на файла)
print(f"  ✓ {len(sk)} реда в „не е сметнато“: Forex, такси извън сделките, сливане (не сплит), данък върху лихва; обобщенията — не")
print("\n✅ test_tax_core: всичко мина")
