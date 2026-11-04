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
print("\n✅ test_tax_fixes: всичко мина")
