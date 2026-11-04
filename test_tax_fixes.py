"""
05.11.2026 (tax-fixes): поправките след двата прегледа на данъчния калкулатор (docs/tax_core.js) — по една секция за всяка поправка.
Входовете са СИНТЕТИЧНИ (написани тук, не реални отчети); очакваните числа — сметнати на ръка в коментарите. Без мрежа; node — tests/tax_driver.js scenario.
"""
import json, shutil, subprocess, sys, pathlib
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)

def scenario(files, years=(), **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files, "years": list(years), "settings": settings}),
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    out["de"] = {int(k): v for k, v in out["de"].items()}
    return out

STD = "type,asset_type,ticker,date,quantity,price,currency,fee,broker,account\n"
def std(*rows): return STD + "\n".join(rows) + "\n"
close = lambda a, b: a is not None and abs(a - b) < 1e-6

# ── 3. два файла с еднакво име и различно съдържание ──
print("── 3. еднакво име, различно съдържание ──")
a = std("buy,stock,AAA,2024-01-10,10,100,EUR,0,B,A", "sell,stock,AAA,2024-03-10,10,110,EUR,0,B,A")
b = std("buy,stock,AAA,2024-01-10,10,100,EUR,0,B,A", "sell,stock,AAA,2024-03-10,10,110,EUR,0,B,A", "buy,stock,BBB,2024-02-01,5,20,EUR,0,B,A", "sell,stock,BBB,2024-04-01,5,30,EUR,0,B,A")
r = scenario([{"name": "export.csv", "text": a}, {"name": "export.csv", "text": b}], years=[2024])
d = r["de"][2024]
assert close(d["shareGains"], 100 + 50), d["shareGains"]          # AAA: 10 × (110 − 100) = 100 веднъж (не 200); BBB: 5 × (30 − 20) = 50
assert [f["duplicates"] for f in r["files"]] == [0, 2], r["files"]   # двата AAA реда от втория файл — дубликати на първия
assert any("export.csv" in w and "различно съдържание" in w for w in r["warnings"]), r["warnings"]
print("  ✓ AAA +100 веднъж, BBB +50 → 150; предупреждение за еднаквото име")
# ── 4. Vorabpauschale: по тикър и година; за X → доход в X+1; приспада се при продажба (§19 InvStG) ──
print("── 4. Vorabpauschale ──")
f = std("buy,etf,XWD,2022-03-01,100,50,EUR,0,B,A", "sell,etf,XWD,2024-06-01,40,60,EUR,0,B,A", "sell,etf,XWD,2025-02-01,60,70,EUR,0,B,A")
r = scenario([{"name": "etf.csv", "text": f}], years=[2023, 2024, 2025], vorab={"XWD": {"2023": 60, "2024": 30}})
d23, d24, d25 = (r["de"][y] for y in (2023, 2024, 2025))
assert close(d23["total"], 0), d23["total"]                        # Vorab за 2023 НЕ е доход в 2023
# 2024: Vorab 2023 = 60 → 60 × 0.7 = 42; продажба 40 × (60 − 50) = 400 − 40 × 60/100 = 376 → × 0.7 = 263.2; общо 305.2
assert close(d24["total"], 42 + 263.2), d24["total"]
# 2025: Vorab 2024 = 30 → 21; продажба 60 × 20 = 1200 − 60 × 0.6 (2023) − 60 × 30/60 (2024) = 1134 → × 0.7 = 793.8; общо 814.8
assert close(d25["total"], 21 + 793.8), d25["total"]
assert any("приспаднати Vorabpauschalen" in n["text"] for n in d25["notes"]) and any("2 януари 2025" in n["text"] for n in d25["notes"])
print("  ✓ 2023: 0; 2024: 42 + 263.2 = 305.2; 2025: 21 + 793.8 = 814.8 (Vorab за X — доход в X+1, приспадната при продажбата)")

print("\n✅ test_tax_fixes: всичко мина")
