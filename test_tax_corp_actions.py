"""
13.11.2026 (tax-real-fix, част В): корпоративни действия на IBKR — ОБЩО разпознаване на вида, ясно правило за всеки, СПОРНОТО като настройка, непознатото — червено + ръчно потвърждение (docs/tax_core.js).
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7/9 на CLAUDE.md): ВСИЧКО Е СИНТЕТИЧНО (построено тук; измислени тикъри, ISIN, цени, дати; курсът на EUR е 1,0 → EUR = USD). РЕАЛЕН ФОРМАТ е проверен САМО за
обикновен сплит („СИМВОЛ(ISIN) Split N for M (СИМВОЛ, ИМЕ, ISIN)“ — 2 реда в реалните отчети) и за „Merged(Acquisition) FOR USD x PER SHARE“ (tests/fixtures/tax/U1111111_2023.csv е по публично описание). Описанията на
останалите видове (размяна, отделяне, дивидент в акции, права, делистинг…) са по публичното описание на IBKR — НЕ са проверени с реален отчет; затова непознатото описание е червено, а не тихо.
Смяната на тикъра без ред в отчета (случаят от реалните отчети на потребителя) се хваща по един и същ Conid във „Financial Instrument Information“ (раздел 11).
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP. Пускане: python test_tax_corp_actions.py
"""
import json, shutil, subprocess, sys, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
txt = lambda d: f"{MON[int(d[5:7]) - 1]} {int(d[8:])}, {d[:4]}"
RATES = "Date,USD,JPY,GBP\n" + "".join(f"{(datetime.date(2022, 1, 1) + datetime.timedelta(days=i)).isoformat()},1.0,1.0,1.0\n" for i in range(0, 365 * 5 + 2))


def scenario(files, years=(), **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files + [{"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": settings}), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    for k in ("de", "summary", "whyZero"):
        o[k] = {int(y): v for y, v in o[k].items()}
    return o


TRH = "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code"
CAH = "Corporate Actions,Header,Asset Category,Currency,Report Date,Date/Time,Description,Quantity,Proceeds,Value,Realized P/L,Code"
MTH = "Mark-to-Market Performance Summary,Header,Asset Category,Symbol,Prior Quantity,Current Quantity,Prior Price,Current Price,Mark-to-Market P/L Position,Mark-to-Market P/L Transaction,Mark-to-Market P/L Commissions,Mark-to-Market P/L Other,Mark-to-Market P/L Total,Code"
FIH = "Financial Instrument Information,Header,Asset Category,Symbol,Description,Conid,Security ID,Underlying,Listing Exch,Multiplier,Type,Code"
OPH = "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Code"
t = lambda sym, d, q, p, h="10:00:00": f'Trades,Data,Order,Stocks,USD,{sym},"{d}, {h}",{q},{p},{p},{-q * p},0,{q * p},0,0,{"O" if q > 0 else "C"}'
def ca(d, desc, q, proceeds=0, value=0): return f'Corporate Actions,Data,Stocks,USD,{d},"{d}, 20:25:00","{desc}",{q},{proceeds},{value},0,'


def stmt(acct, start, end, trades=(), cas=(), mtm=None, fii=(), openpos=None):
    L = ["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement", f'Statement,Data,Period,"{txt(start)} - {txt(end)}"',
         "Account Information,Header,Field Name,Field Value", f"Account Information,Data,Account,{acct}", "Account Information,Data,Base Currency,EUR"]
    if mtm is not None:
        L += [MTH] + [f"Mark-to-Market Performance Summary,Data,Stocks,{s},{a},{b},1,1,0,0,0,0,0," for s, (a, b) in mtm.items()]
    if fii:
        L += [FIH] + [f"Financial Instrument Information,Data,Stocks,{s},{s} CORP,{cid},{isin},,NYSE,1,COMMON," for s, cid, isin in fii]
    if openpos is not None:
        L += [OPH] + [f"Open Positions,Data,Summary,Stocks,USD,{s},{q},1,1,{q},1,{q},0," for s, q in openpos.items()]
    if trades:
        L += [TRH] + list(trades)
    if cas:
        L += [CAH] + list(cas)
    return "\n".join(L) + "\n"


run = lambda text, years=(2024,), **kw: scenario([{"name": "s.csv", "text": text}], years=list(years), **kw)
sales = lambda o, y=2024: [x for x in o["fifo"]["realized"] if x["year"] == y]
g6 = lambda o, sym=None, y=2024: [round(x["gainEUR"], 6) if x["gainEUR"] is not None else None for x in sales(o, y) if sym is None or x["sym"] == sym]
notes = lambda o, y=2024, level=None: [n["text"] for n in o["de"][y]["notes"] if level is None or n["level"] == level]
ISIN = lambda c: f"US00000000{c}1"

print("── 1. сплит: часът решава реда в деня (сплитът е 20:25 — СЛЕД сделките на деня) (СИНТЕТИЧНО; описанието е като в реалните отчети) ──")
o = run(stmt("U4000001", "2024-01-01", "2024-12-31", [t("AAA", "2024-06-10", 10, 100), t("AAA", "2024-06-11", -40, 30)],
             [ca("2024-06-10", f"AAA({ISIN('A')}) Split 4 for 1 (AAA, AAA CORP, {ISIN('A')})", 30)]))
assert g6(o) == [200.0] and o["fifo"]["unmatched"] == [] and sales(o)[0]["lots"][0]["qty"] == 40, (g6(o), o["fifo"]["unmatched"])       # 40 × 30 − 1 000; до 13.11 сплитът беше ПРЕДИ покупката в същия ден → липсваха 30 бр.
print("  ✓ купени 10 по 100 на 10.06 в 10:00, сплит 4:1 на 10.06 в 20:25 → 40 бр. за 1 000; продадени 40 по 30 → +200 (без час сплитът се прилагаше преди покупката и 30 бр. оставаха без покупка)")

print("── 2. обратен сплит в два реда (нов ISIN) ──")
o = run(stmt("U4000002", "2024-01-01", "2024-12-31", [t("BBB", "2024-02-01", 100, 10), t("BBB", "2024-08-01", -10, 150)],
             [ca("2024-07-01", f"BBB({ISIN('B')}) Split 1 for 10 (BBB, BBB CORP, {ISIN('B')})", -100), ca("2024-07-01", f"BBB(US00000000B2) Split 1 for 10 (BBB, BBB CORP, US00000000B2)", 10)]))
s = sales(o)[0]
assert g6(o) == [500.0] and [(l["date"], l["qty"]) for l in s["lots"]] == [("2024-02-01", 10)] and o["fifo"]["unmatched"] == [] and not [x for x in o["skipped"] if x["section"] == "Corporate Actions"], (g6(o), s["lots"])
print("  ✓ 100 бр. по 10 → 10 бр. (коефициент 0,1 от количествата −100 / +10, не два пъти); датата 01.02.2024 и общата цена 1 000 остават; продадени 10 по 150 → +500")

print("── 3. смяна на тикър / ISIN ──")
o = run(stmt("U4000003", "2024-01-01", "2024-12-31", [t("OLDC", "2024-01-10", 50, 20), t("NEWC", "2024-05-01", -50, 30)],
             [ca("2024-04-01", f"OLDC({ISIN('C')}) CUSIP/ISIN Change to US00000000C2 (NEWC, NEW CORP, US00000000C2)", -50), ca("2024-04-01", "NEWC(US00000000C2) CUSIP/ISIN Change to US00000000C2 (NEWC, NEW CORP, US00000000C2)", 50)]))
s = sales(o)[0]
assert g6(o) == [500.0] and s["sym"] == "NEWC" and [(l["date"], l["qty"]) for l in s["lots"]] == [("2024-01-10", 50)] and any("OLDC → NEWC" in n for n in notes(o)), (g6(o), notes(o))
print("  ✓ OLDC → NEWC: лотът от 10.01.2024 (цена 20) продължава като NEWC; продажба на 50 по 30 → +500")

print("── 4. сливане акции срещу акции ──")
o = run(stmt("U4000004", "2024-01-01", "2024-12-31", [t("DDD", "2024-01-15", 100, 10), t("EEE", "2024-06-01", -50, 60)],
             [ca("2024-05-01", f"DDD({ISIN('D')}) Merged(Acquisition) with {ISIN('E')} 1 for 2 (DDD, DDD CORP, {ISIN('D')})", -100), ca("2024-05-01", f"EEE({ISIN('E')}) Merged(Acquisition) with {ISIN('E')} 1 for 2 (EEE, EEE CORP, {ISIN('E')})", 50)]))
assert g6(o) == [2000.0] and o["fifo"]["unmatched"] == [] and sales(o)[0]["lots"][0]["date"] == "2024-01-15", g6(o)                  # 3 000 − 1 000
print("  ✓ DDD 100 → EEE 50 (по количествата от отчета): общата цена 1 000 и датата 15.01.2024 остават; продадени 50 по 60 → +2 000")

print("── 5. сливане / изкупуване срещу пари ──")
o = run(stmt("U4000005", "2024-01-01", "2024-12-31", [t("FFF", "2024-02-01", 100, 10)], [ca("2024-06-03", f"FFF({ISIN('F')}) Merged(Acquisition) FOR USD 12.00 PER SHARE (FFF, FFF CORP, {ISIN('F')})", -100, 1200)]))
assert g6(o) == [200.0] and not [x for x in o["skipped"] if x["section"] == "Corporate Actions"] and o["de"][2024]["complete"] is True, g6(o)
print("  ✓ 100 бр. по 10, изкупени за 1 200 → продажба: +200; не е в „не е сметнато“, годината е пълна")

print("── 6. смесено (пари + акции): парите са продажба на дял от лотовете (по стойност), остатъкът — размяна (СПОРНО) ──")
o = run(stmt("U4000006", "2024-01-01", "2024-12-31", [t("GGG", "2024-01-10", 100, 20), t("HHH", "2024-09-02", -40, 50)],
             [ca("2024-07-01", f"GGG({ISIN('G')}) Merged(Acquisition) with {ISIN('H')} CASH AND STOCK (GGG, GGG CORP, {ISIN('G')})", -100, 300), ca("2024-07-01", f"HHH({ISIN('H')}) Merged(Acquisition) with {ISIN('H')} CASH AND STOCK (HHH, HHH CORP, {ISIN('H')})", 40, 0, 700)]))
assert g6(o, "GGG") == [-300.0] and g6(o, "HHH") == [600.0], g6(o)       # дял 300 / (300 + 700) = 30% → 30 бр. продадени за 300 при цена 600 → −300; 70 бр. → 40 HHH с цена 1 400 → 2 000 − 1 400 = +600
assert any("СПОРНО" in n and "парите (300 USD) са продажба на 30%" in n for n in notes(o, 2024, "warn")), notes(o)
print("  ✓ 100 GGG по 20 → 300 в пари + 40 HHH (стойност 700): 30% = 30 бр. продадени за 300 (цена 600 → −300); 70 бр. → 40 HHH с цена 1 400; продадени 40 по 50 → +600; бележка „СПОРНО“")

print("── 7. отделяне на компания: цена на ръка (по подразбиране) или 0 (настройка) — СПОРНО ──")
sp = stmt("U4000007", "2024-01-01", "2024-12-31", [t("PAR", "2024-01-10", 100, 10), t("SPN", "2024-06-05", -20, 15)], [ca("2024-05-02", f"SPN({ISIN('S')}) Spinoff 1 for 5 (SPN, SPN CORP, {ISIN('S')})", 20, 0, 200)])
o = run(sp)
assert g6(o, "SPN") == [None] and [(x["kind"], x["sym"], x["qty"], x["filled"]) for x in o["fifo"]["pending"]] == [("spinoff", "SPN", 20, False)] and o["de"][2024]["complete"] is False
key = o["fifo"]["pending"][0]["key"]
o = run(sp, manual={key: {"date": "2024-01-10", "price": 2, "currency": "USD"}})
assert g6(o, "SPN") == [260.0] and o["de"][2024]["complete"] is True                                                                       # 300 − 20 × 2
o = run(sp, corp={"spinoff": "zero"})
assert g6(o, "SPN") == [300.0] and any("СМЕТНАТА цена 0" in n for n in notes(o, 2024, "warn")) and o["fifo"]["pending"] == []
print("  ✓ по подразбиране новите акции са без цена: продажбата няма резултат (null, не нула), НЕПЪЛНО; с въведена цена 2 → +260; настройка „0 €“ → +300 с бележка „СМЕТНАТА цена 0“, а не тихо")

print("── 8. дивидент в акции: като безплатни акции (по подразбиране) или доход по пазарна стойност (настройка) — СПОРНО ──")
sd = stmt("U4000008", "2024-01-01", "2024-12-31", [t("III", "2024-01-10", 100, 10), t("III", "2024-05-02", -105, 12)], [ca("2024-04-01", f"III({ISIN('I')}) Stock Dividend {ISIN('I')} 1 for 20 (III, III CORP, {ISIN('I')})", 5, 0, 60)])
o = run(sd)
assert g6(o) == [260.0] and not [x for x in o["fifo"]["incomes"] if x["year"] == 2024] and any("като безплатни акции" in n for n in notes(o, 2024, "warn")), g6(o)       # 1 260 − 1 000
o = run(sd, corp={"stockDividend": "income"})
inc = [x for x in o["fifo"]["incomes"] if x["year"] == 2024]
assert g6(o) == [200.0] and len(inc) == 1 and inc[0]["kind"] == "dividend" and round(inc[0]["eur"], 6) == 60.0 and "дивидент в акции" in inc[0]["desc"], (g6(o), inc)    # 1 260 − (1 000 + 60); доход 60
print("  ✓ 100 бр. + 5 нови: „като безплатни акции“ → 105 бр. за 1 000, продадени по 12 → +260, без доход; „доход“ → доход 60 и цена на новите 60 → +200")

print("── 9. делистинг / безценност и фракции в брой — СПОРНО ──")
o = run(stmt("U4000009", "2024-01-01", "2024-12-31", [t("JJJ", "2024-01-10", 200, 5)], [ca("2024-09-01", f"JJJ({ISIN('J')}) Delisted (JJJ, JJJ CORP, {ISIN('J')})", -200)]))
assert g6(o) == [-1000.0] and any("СПОРНО" in n and "делистинг" in n for n in notes(o, 2024, "warn")), notes(o)
print("  ✓ делистинг на 200 бр. по 5: продажба за 0 → −1 000; бележка „СПОРНО“ (§20 ал. 6 EStG — да се потвърди)")
o = run(stmt("U4000010", "2024-01-01", "2024-12-31", [t("KKK", "2024-01-10", 10.5, 20)], [ca("2024-06-01", f"KKK({ISIN('K')}) Cash in Lieu of Fractional Shares (KKK, KKK CORP, {ISIN('K')})", -0.5, 7)]))
assert g6(o) == [-3.0] and any("СПОРНО" in n and "фракции" in n for n in notes(o, 2024, "warn")), (g6(o), notes(o))                          # 7 − 0,5 × 20
print("  ✓ фракция 0,5 бр. платена в брой (7): продажба −3 (цена 10); бележка „СПОРНО“")

print("── 10. непознато → червено с описанието от отчета + ръчно потвърждение; никога тихо ──")
rg = stmt("U4000011", "2024-01-01", "2024-12-31", [t("LLL", "2024-01-10", 10, 10)], [ca("2024-03-05", f"LLL.RTS({ISIN('R')}) Rights Issue 1 for 10 (LLL.RTS, LLL RIGHTS, {ISIN('R')})", 10),
                                                                                         'Corporate Actions,Data,Stocks,USD,2024-03-08,"2024-03-08, 20:25:00","SOMETHING ODD HAPPENED",5,0,0,0,'])
o = run(rg)
unk = [x for x in o["skipped"] if x["section"] == "Corporate Actions"]
assert len(unk) == 2 and all(x["taxable"] and x["ackKey"] for x in unk) and o["de"][2024]["complete"] is False
assert any("права (rights)" in n and "LLL.RTS" in n for n in notes(o, 2024, "err")) and any("SOMETHING ODD HAPPENED" in n for n in notes(o, 2024, "err")), notes(o, 2024, "err")
o = run(rg, manual={unk[0]["ackKey"]: {"ack": True}, unk[1]["ackKey"]: {"ack": True}})
assert o["de"][2024]["complete"] is True and o["de"][2024]["skippedTaxable"] == []
print("  ✓ „Rights Issue“ и описание без ISIN → 2 червени реда с описанието, годината НЕПЪЛНО; след ръчно потвърждение (ack) — пълна; редовете остават в „не е сметнато“")

print("── 11. смяна на тикъра БЕЗ ред в отчета: един и същ Conid в два отчета (както в реалните отчети) ──")
s23 = stmt("U4000012", "2023-01-01", "2023-12-29", [t("OLDX", "2023-03-01", 100, 10)], mtm={"OLDX": (0, 100)}, fii=[("OLDX", 555001, "US00000000X1")], openpos={"OLDX": 100})
s24 = stmt("U4000012", "2024-01-02", "2024-12-31", [t("NEWX", "2024-05-01", -100, 15)], mtm={"NEWX": (100, 0)}, fii=[("NEWX", 555001, "US00000000X1")], openpos={})
o = scenario([{"name": "a.csv", "text": s23}, {"name": "b.csv", "text": s24}], years=[2024])
assert g6(o) == [500.0] and o["fifo"]["controlLog"] == [] and o["fifo"]["endChecks"] == [] and o["fifo"]["pending"] == [], (g6(o), o["fifo"]["controlLog"], o["fifo"]["endChecks"])
assert any("OLDX → NEWX: един и същ инструмент (Conid 555001)" in w for w in o["warnings"]) and sales(o)[0]["lots"][0]["date"] == "2023-03-01"
print("  ✓ OLDX (отчет 2023) и NEWX (отчет 2024) са един инструмент (Conid 555001): продажба на 100 NEWX по 15 → +500 с лота от 01.03.2023; без излишък / липса при контролите; съобщение „OLDX → NEWX“")
o = scenario([{"name": "a.csv", "text": s23.replace("555001", "555001")}, {"name": "b.csv", "text": s24.replace("555001", "555002")}], years=[2024])
assert o["fifo"]["controlLog"] and not any("един и същ инструмент" in w for w in o["warnings"])
print("  ✓ различен Conid → НЕ е един инструмент: контролите показват излишък (OLDX) и липса (NEWX) — не се слива тихо")
print("test_tax_corp_actions: ВСИЧКО ОК")
