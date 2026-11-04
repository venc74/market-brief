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

# ── 5. Stillhalter: премията в годината на получаване, обратното изкупуване — в годината на плащане (настройка) ──
print("── 5. Stillhalter ──")
f = std("sell,option,XYZ P50,2024-12-15,1,300,EUR,0,B,A", "buy,option,XYZ P50,2025-01-17,1,0,EUR,0,B,A",     # изтича без стойност
        "sell,option,XYZ C80,2024-11-01,1,500,EUR,0,B,A", "buy,option,XYZ C80,2025-01-10,1,200,EUR,0,B,A")     # обратно изкупена за 200
r = scenario([{"name": "opt.csv", "text": f}], years=[2024, 2025])
assert close(r["de"][2024]["total"], 300 + 500) and close(r["de"][2025]["total"], 0) and close(r["de"][2025]["otherCarry"], 200), (r["de"][2024]["total"], r["de"][2025])
assert any("годината на получаване" in n["text"] for n in r["de"][2024]["notes"])
r = scenario([{"name": "opt.csv", "text": f}], years=[2024, 2025], stillhalter="close")
assert close(r["de"][2024]["total"], 0) and close(r["de"][2025]["total"], 300 + 300), (r["de"][2024]["total"], r["de"][2025]["total"])   # старото: нетно при затваряне
print("  ✓ по подразбиране: 2024 = 300 + 500 = 800, 2025 = −200 (за пренасяне); настройка „при затварянето“: 2024 = 0, 2025 = 300 + 300 = 600")

# ── 6. непокрита продажба: без фантомен лот; „НЕПЪЛНО“ и за следващите години; сверка с Open Positions на IBKR ──
print("── 6. непокрита продажба, сверка ──")
f = std("sell,stock,XYZ,2023-03-01,100,50,EUR,0,B,A", "buy,stock,XYZ,2023-04-01,100,40,EUR,0,B,A",       # къса продажба и покритието ѝ
        "buy,stock,XYZ,2024-02-01,100,60,EUR,0,B,A", "sell,stock,XYZ,2024-05-01,100,70,EUR,0,B,A")
r = scenario([{"name": "short.csv", "text": f}], years=[2023, 2024])
d23, d24 = r["de"][2023], r["de"][2024]
assert close(d24["total"], 100 * (70 - 60)) and not d24["complete"], d24["total"]     # +1 000 (до 05.11: +3 000 от фантомния лот @ 40), НЕПЪЛНО
assert not d23["complete"] and [u["qty"] for u in d23["unmatched"]] == [100] and r["fifo"]["open"] == [], r["fifo"]["open"]
assert any("НЕПЪЛНО" in n["text"] and n["level"] == "err" for n in d24["notes"])
f = std("sell,stock,ABC,2023-03-01,50,150,EUR,0,B,A", "buy,stock,ABC,2023-12-01,50,200,EUR,0,B,A", "sell,stock,ABC,2024-05-01,50,210,EUR,0,B,A")
d24 = scenario([{"name": "old.csv", "text": f}], years=[2024])["de"][2024]
assert close(d24["total"], 0) and not d24["complete"] and [u["qty"] for u in d24["unmatched"]] == [50], d24   # липсващ стар отчет: 2024 — без резултат (до 05.11: +500, „пълно“)
IB = lambda *rows: "\n".join(["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers", "Statement,Data,Period,\"January 1, 2024 - December 31, 2024\"",
    "Account Information,Header,Field Name,Field Value", "Account Information,Data,Account,U7777777",
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code", *rows]) + "\n"
f = IB("Trades,Data,Order,Stocks,EUR,AAA,\"2024-03-01, 10:00:00\",100,10,10,-1000,0,1000,0,0,O", "Trades,Data,Order,Stocks,EUR,BBB,\"2024-03-01, 10:00:00\",10,20,20,-200,0,200,0,0,O",
       "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Code",
       "Open Positions,Data,Summary,Stocks,EUR,AAA,150,1,10,1500,10,1500,0,", "Open Positions,Data,Summary,Stocks,EUR,BBB,10,1,20,200,20,200,0,",
       "Open Positions,Data,Lot,Stocks,EUR,AAA,150,1,10,1500,10,1500,0,")
d24 = scenario([{"name": "U7777777_2024.csv", "text": f}], years=[2024])["de"][2024]
assert [(m["sym"], m["reported"], m["computed"], m["date"]) for m in d24["reconcile"]] == [("AAA", 150, 100, "2024-12-31")] and not d24["complete"], d24["reconcile"]
print("  ✓ къса продажба: 2024 = +1 000 (не +3 000), НЕПЪЛНО; липсващ стар отчет: 2024 без резултат; Open Positions: AAA 150 ≠ 100 → НЕПЪЛНО, BBB 10 = 10 — без бележка")

# ── 7. complete = false при потенциално облагаеми редове в „не е сметнато“ за годината ──
print("── 7. облагаеми редове в „не е сметнато“ ──")
rc = "Symbol,Type,Quantity,Price,Value,Fees,Date\n" + "\n".join(['BTC,Buy,1,€10000.00,€10000.00,€0.00,"Jan 2, 2024, 10:00:00 AM"', 'BTC,Exchange,1,€30000.00,€30000.00,€0.00,"Jun 3, 2024, 10:00:00 AM"']) + "\n"
r = scenario([{"name": "cx.csv", "text": rc}], years=[2023, 2024])
assert not r["de"][2024]["complete"] and len(r["de"][2024]["skippedTaxable"]) == 1 and r["de"][2023]["complete"] is True, r["de"][2024]["skippedTaxable"]
ca = IB("Corporate Actions,Header,Asset Category,Currency,Report Date,Date/Time,Description,Quantity,Proceeds,Value,Realized P/L,Code",
        "Corporate Actions,Data,Stocks,USD,2024-05-02,\"2024-05-01, 20:25:00\",\"TGT(US1234567890) Merged(Acquisition) FOR USD 50.00 PER SHARE (TGT, TARGET CO, US1234567890)\",-100,5000,0,1000,",
        "Trades,Data,Order,Forex,USD,EUR.USD,\"2024-03-01, 10:00:00\",1000,1.08,1.08,-1080,0,0,0,0,")
d = scenario([{"name": "ca.csv", "text": ca}], years=[2024])["de"][2024]
assert [x["section"] for x in d["skippedTaxable"]] == ["Corporate Actions"] and not d["complete"], d["skippedTaxable"]   # Forex — в списъка, но не прави годината непълна
print("  ✓ размяна BTC → ETH (2024) и сливане с пари (2024) → НЕПЪЛНО за 2024; 2023 — пълна; Forex не брои")

print("\n✅ test_tax_fixes: всичко мина")
