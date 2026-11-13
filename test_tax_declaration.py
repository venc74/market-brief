"""
15.11.2026 (tax-declaration-block): блокът „Какво попълваш в декларацията“ — сумите на годината по редовете на Anlage KAP 2025: Zeile 19 (ausländische Kapitalerträge — салдо), 20 (Gewinne aus Aktienveräußerungen), 22 (Verluste ohne
Aktienverluste), 23 (Aktienverluste), 41 (noch nicht angerechnete ausländische Steuer). Номерата на редовете са проверени САМО за 2025 (вторичен източник — smartsteuer.de, VZ 2025; да се сравни с формуляра в ELSTER); за другите години — суми без номера.
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7): ВСИЧКО Е СИНТЕТИЧНО — стандартен CSV, построен тук (тикъри AAA…, суми от въображението, дати — почивни дни на 2025; курс 1,0 за USD).
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP. Пускане: python test_tax_declaration.py
"""
import json, shutil, subprocess, sys, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
RATES = "Date,USD,JPY,GBP\n" + "".join(f"{(datetime.date(2023, 12, 1) + datetime.timedelta(days=i)).isoformat()},1.0,1.0,1.0\n" for i in range(0, 800))
H = "type,ticker,date,quantity,price,currency,broker,account,asset_type,withholding_tax\n"
rw = lambda t, k, d, q, p, w="": f"{t},{k},{d},{q},{p},USD,CSV,main,stock,{w}\n"
BASE = H + rw("buy", "AAA", "2025-02-15", 10, 10) + rw("sell", "AAA", "2025-02-16", 10, 30) + rw("buy", "BBB", "2025-03-08", 10, 100) + rw("sell", "BBB", "2025-04-05", 10, 50) \
    + rw("dividend", "CCC", "2025-04-06", 100, "", 15) + rw("interest", "INT", "2025-05-03", 20, "") + rw("dividend", "EEE", "2025-05-04", -10, "")


def scenario(text, years):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": [{"name": "s.csv", "text": text}, {"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": {}}), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    o["de"] = {int(y): v for y, v in o["de"].items()}
    o["decl"] = {int(y): v for y, v in o["decl"].items()}
    return o


r2 = lambda x: round(x, 2)
o = scenario(BASE, [2025])
d = o["decl"][2025]
print("── 1. Anlage KAP 2025: сумите по редовете ──")
rows = {r["zeile"]: r for r in d["rows"] if r["zeile"] is not None}
assert sorted(rows) == [19, 20, 22, 23, 41] and d["verified"] is True and d["complete"] is True, (sorted(rows), d["verified"], d["complete"])
assert r2(rows[20]["eur"]) == 200 and r2(rows[23]["eur"]) == 500 and r2(rows[22]["eur"]) == 10, [(z, r["eur"]) for z, r in rows.items()]                    # печалби 200 · загуби от акции 500 · други загуби 10 (сторно на дивидент)
assert r2(rows[19]["eur"]) == r2(200 - 500 + 100 + 20 - 10) == -190                                                                                        # салдо: акции 200 − 500, дивидент 100, лихва 20, сторно −10 → −190 (може да е отрицателно)
assert r2(rows[41]["eur"]) == 15, rows[41]                                                                                                                  # удържани 15 от дивидент 100 = 15% → зачитат се 15
assert [r["form"] for r in d["rows"]] == ["Anlage KAP"] * 5
print("  ✓ Zeile 19 = 200 − 500 + 100 + 20 − 10 = −190 (салдото може да е отрицателно); Zeile 20 = 200 (печалби от акции); Zeile 22 = 10 (други загуби); Zeile 23 = 500 (загуби от акции); Zeile 41 = 15 (удържан чужд данък до 15%)")
txt = " ".join(d["notes"])
assert "Zeile 21 е премахната" in txt and "Verlustfeststellungsbescheid" in txt and "Sparer-Pauschbetrag" in txt and "Verlustvortrag не се въвежда" in txt
print("  ✓ бележките: Zeile 21 е премахната; загубата се декларира в годината си (Verlustfeststellungsbescheid), Verlustvortrag не се въвежда; Sparer-Pauschbetrag — Finanzamt")
assert r2(o["de"][2025]["shareLossOwn"]) == 300 and "300.00" in d["lossLine"].replace(" ", " ")
print("── 2. година без проверени номера на редове ──")
o2 = scenario(BASE.replace("2025-", "2024-"), [2024])
d2 = o2["decl"][2024]
assert d2["verified"] is False and all(r["zeile"] is None for r in d2["rows"]) and any("проверени САМО за 2025" in n for n in d2["notes"]), d2["notes"]
assert r2(d2["z19"]) == -190 and r2(d2["z20"]) == 200 and r2(d2["z23"]) == 500
print("  ✓ 2024: същите суми, но БЕЗ номера на редове и с бележка „проверени САМО за 2025“")
print("── 3. НЕПЪЛНА година се маркира ──")
o3 = scenario(BASE + rw("sell", "DDD", "2025-05-10", 5, 10), [2025])
assert o3["decl"][2025]["complete"] is False and o3["de"][2025]["complete"] is False
print("  ✓ продажба без покупка → блокът е „НЕПЪЛНО“ (complete = false) — в страницата червен ред над таблицата")
print("test_tax_declaration: ВСИЧКО ОК")
