"""
15.11.2026 (tax-declaration-block): блокът „Какво попълваш в декларацията“ — за всяко ПОЛЕ на формуляра: точният немски текст (какво търсиш в ELSTER) + кратко обяснение на български; номерът на реда е само подсказка в скоби
„(в бланката за 2025: Zeile 19 — провери)“; колона „Защо“ с формулата с думи и числа; Zeile 20 / 22 / 23 са „от тях“ (вече в Zeile 19); контролен ред; информативни редове (Sparer-Pauschbetrag; как ще смята Finanzamt; удържан данък върху лихви).
Текстовете и номерата са за Anlage KAP 2025 (Stand 10.2025) по ВТОРИЧЕН източник (smartsteuer.de) — да се сравнят с ELSTER.
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7): ВСИЧКО Е СИНТЕТИЧНО — стандартен CSV и къс IBKR отчет, построени тук (тикъри AAA…, суми от въображението, дати — почивни дни на 2025; курс 1,0 за USD).
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
IBKR = "\n".join(["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement", 'Statement,Data,Period,"February 22, 2025 - November 29, 2025"',
                  "Account Information,Header,Field Name,Field Value", "Account Information,Data,Account,U9300001", "Account Information,Data,Base Currency,EUR",
                  "Withholding Tax,Header,Currency,Date,Description,Amount,Code",
                  "Withholding Tax,Data,USD,2025-02-22,Withholding @ 20% on Credit Interest for Jan-2025,-1.5,", "Withholding Tax,Data,USD,2025-02-23,Withholding @ 20% on Credit Interest for Feb-2025,-2.5,"]) + "\n"


def scenario(files, years, **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files + [{"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": settings}), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    o["de"] = {int(y): v for y, v in o["de"].items()}
    o["decl"] = {int(y): v for y, v in o["decl"].items()}
    return o


r2 = lambda x: round(x, 2)
nb = lambda x: x.replace(" ", " ")
o = scenario([{"name": "s.csv", "text": BASE}], [2025], joint=True)
d = o["decl"][2025]
by = {r["field"]: r for r in d["rows"]}
print("── 1. всеки ред: точният немски текст на полето + обяснение на български; номерът — само подсказка в скоби ──")
F19, F20 = "Ausländische Kapitalerträge (ohne Beträge laut den Zeilen 26a und 52)", "In den Zeilen 18 und 19 enthaltene Gewinne aus Aktienveräußerungen i. S. d. § 20 Abs. 2 Satz 1 Nr. 1 EStG"
F22, F23, F41 = "In den Zeilen 18 und 19 enthaltene Verluste ohne Verluste aus der Veräußerung von Aktien", "In den Zeilen 18 und 19 enthaltene Verluste aus der Veräußerung von Aktien", "Anrechenbare noch nicht angerechnete ausländische Steuern"
assert [r["field"] for r in d["rows"]] == [F19, F20, F22, F23, F41], [r["field"] for r in d["rows"]]
assert [r["hint"] for r in d["rows"]] == [f"(в бланката за 2025: Zeile {z} — провери)" for z in (19, 20, 22, 23, 41)]
assert [r["kind"] for r in d["rows"]] == ["total", "part", "part", "part", "total"] and d["verified"] is True and d["complete"] is True
assert all(r["bg"] and r["form"] == "Anlage KAP" for r in d["rows"])
print("  ✓ полетата са с немския текст (Ausländische Kapitalerträge …, In den Zeilen 18 und 19 enthaltene Gewinne / Verluste …, Anrechenbare noch nicht angerechnete ausländische Steuern) и БГ обяснение; Zeile — само „(в бланката за 2025: Zeile N — провери)“")
print("── 2. суми и колона „Защо“ с формулата ──")
assert (r2(by[F19]["eur"]), r2(by[F20]["eur"]), r2(by[F22]["eur"]), r2(by[F23]["eur"]), r2(by[F41]["eur"])) == (-190, 200, 10, 500, 15), [(r["field"][:20], r["eur"]) for r in d["rows"]]
w19 = nb(by[F19]["why"])
assert "печалби от акции 200.00 € − загуби от акции 500.00 € + дивиденти 100.00 € + лихви 20.00 € − други загуби 10.00 € = −190.00 €" in w19 and "трите реда по-долу са „от тях“" in w19, w19
for f, n in ((F20, "1 продажба с печалба = 200.00 €"), (F23, "1 продажба със загуба = 500.00 €")):
    w = nb(by[f]["why"]); assert n in w and "от тях“ — вече е вътре в общия ред (Zeile 19) и НЕ се добавя и НЕ се изважда втори път" in w, w
assert "загуби от опции 0.00 € + сторно на дивиденти и други загуби 10.00 € = 10.00 €" in nb(by[F22]["why"]) and "от тях" in by[F22]["why"]
assert "удържан по дивиденти 15.00 €; зачита се до 15% от брутния дивидент" in nb(by[F41]["why"]) and "Данъкът върху ЛИХВИ не е тук" in by[F41]["why"]
print("  ✓ Zeile 19 = 200 − 500 + 100 + 20 − 10 = −190 с думи и числа; 20 / 22 / 23 — „от тях“ (вече в 19, не се добавят и не се изваждат втори път); 41 = 15 (15% от дивидент 100)")
print("── 3. контролен ред ──")
c = d["control"]
assert c["ok"] is True and abs(c["diff"]) < 1e-9 and "съвпада с разбивката ✓" in c["text"] and "−190.00" in nb(c["text"]).replace("−", "−"), c
print("  ✓ Zeile 19 (−190) = печалби акции 200 − загуби акции 500 + други доходи 120 − други загуби 10 — съвпада с разбивката ✓")
print("── 4. информативни редове: Sparer-Pauschbetrag и как ще го сметне Finanzamt ──")
tt = {i["title"]: nb(i["text"]) for i in d["info"]}
sp = tt["Sparer-Pauschbetrag"]
assert "НЕ се пише в нито един от тези редове" in sp and "2 000.00 €" in sp and "при съвместно подаване" in sp and "съвместно)" in sp, sp
fa = tt["Как ще го сметне Finanzamt (приблизително)"]
assert "печалби 200.00 € − загуби 500.00 € = −300.00 € → загуба от акции: пренася се" in fa and "НЕ намалява другите доходи" in fa and "Дивиденти, лихви и др. 110.00 € се облагат отделно" in fa, fa
assert "преди Sparer-Pauschbetrag 110.00 € → след него 0.00 € → приблизителен данък 0.00 € (25%)" in fa, fa                                          # 110 < 2 000 → без данък
o2 = scenario([{"name": "s.csv", "text": BASE.replace("dividend,CCC,2025-04-06,100", "dividend,CCC,2025-04-06,4100")}], [2025], joint=True)
fa2 = nb({i["title"]: i["text"] for i in o2["decl"][2025]["info"]}["Как ще го сметне Finanzamt (приблизително)"])
assert "преди Sparer-Pauschbetrag 4 110.00 € → след него 2 110.00 € → приблизителен данък 512.50 € (25%) + Soli 28.19 € = 540.69 €" in fa2, fa2         # 2 110 × 25% − 15 зачетен чужд данък = 512,50; Soli 5,5% = 28,19
print("  ✓ Sparer-Pauschbetrag: „не се пише“, 2 000 € при съвместно; Finanzamt: загуба от акции се пренася и не намалява другите доходи, дивиденти / лихви — отделно, с приблизителен данък")
print("── 5. удържан данък върху лихви — не се слага тихо ──")
o3 = scenario([{"name": "s.csv", "text": BASE}, {"name": "ibkr.csv", "text": IBKR}], [2025])
d3 = o3["decl"][2025]
ih = [i for i in d3["info"] if i["title"].startswith("Удържан данък върху лихви")]
assert len(ih) == 1 and ih[0]["level"] == "warn", d3["info"]
t3 = nb(ih[0]["title"] + " " + ih[0]["text"])
assert "2 реда, 4.00 USD ≈ 4.00 €" in t3 and "провери" in t3 and "20%" in t3 and "ирландски данък при източника" in t3 and "31.12.2029" in t3 and "НЕ Е ЯСНО" in t3 and "НЕ е в Zeile 41" in t3, t3
assert r2(by[F41]["eur"]) == 15 and r2(d3["rows"][4]["eur"]) == 15 and o3["de"][2025]["interestWithholding"] and len(o3["de"][2025]["interestWithholding"]) == 2
assert not [i for i in d["info"] if i["title"].startswith("Удържан данък върху лихви")]                                                                    # без такива редове в отчета — няма ред
print("  ✓ 2 реда без тикър („Withholding @ 20% on Credit Interest …“): 4,00 USD ≈ 4,00 € — предупреждение: ирландски данък при източника, дали се зачита — НЕ Е ЯСНО, провери; НЕ е в Zeile 41 и не е в числата")
print("── 6. година без проверени текстове; НЕПЪЛНА година ──")
o4 = scenario([{"name": "s.csv", "text": BASE.replace("2025-", "2024-")}], [2024])
d4 = o4["decl"][2024]
assert d4["verified"] is False and all(r["hint"] == "" for r in d4["rows"]) and any("по бланката за 2025" in n for n in d4["notes"]) and r2(d4["z19"]) == -190
o5 = scenario([{"name": "s.csv", "text": BASE + rw("sell", "DDD", "2025-05-10", 5, 10)}], [2025])
assert o5["decl"][2025]["complete"] is False
print("  ✓ 2024: същите суми без подсказка за ред и с бележка „по бланката за 2025“; продажба без покупка → НЕПЪЛНО")
print("test_tax_declaration: ВСИЧКО ОК")
