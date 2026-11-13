"""
13.11.2026 (tax-real-fix, части А и Б): контроли по началните / крайните позиции на всеки отчет по сметка и прехвърляния (Inter-Company, ACATS „In“ / „Out“) — docs/tax_core.js.
ВСИЧКИ входове са СИНТЕТИЧНИ (построени тук; измислени сметки, тикъри AAA…, цени и дати; курсът на EUR е 1,0 за всеки ден, така че EUR = USD); очакваните числа — сметнати на ръка в коментарите.
Формата на секциите (Mark-to-Market Performance Summary, Open Positions, Transfers) е по РЕАЛНИТЕ отчети (tests/fixtures/tax/real_anon/) — виж test_tax_real_anon.py.
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP.
Пускане: python test_tax_controls.py
"""
import json, shutil, subprocess, sys, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)

MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
def txt(d):
    y, m, dd = d.split("-"); return f"{MON[int(m) - 1]} {int(dd)}, {y}"
RATES = "Date,USD,JPY,GBP\n" + "".join(f"{(datetime.date(2022, 1, 1) + datetime.timedelta(days=i)).isoformat()},1.0,1.0,1.0\n" for i in range(0, 365 * 5 + 2))      # 1 USD = 1 EUR всеки ден 2022–2026 (формат като eurofxref-hist.csv)


def scenario(files, years=(), **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files + [{"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": settings}),
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    for k in ("de", "summary", "whyZero"):
        o[k] = {int(y): v for y, v in o[k].items()}
    return o


TRH = "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code"
MTH = "Mark-to-Market Performance Summary,Header,Asset Category,Symbol,Prior Quantity,Current Quantity,Prior Price,Current Price,Mark-to-Market P/L Position,Mark-to-Market P/L Transaction,Mark-to-Market P/L Commissions,Mark-to-Market P/L Other,Mark-to-Market P/L Total,Code"
OPH = "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Code"
TRFH = "Transfers,Header,Asset Category,Currency,Symbol,Date,Type,Direction,Xfer Company,Xfer Account,Qty,Xfer Price,Market Value,Realized P/L,Cash Amount,Code"


def t(sym, d, q, p):
    return f'Trades,Data,Order,Stocks,USD,{sym},"{d}, 10:00:00",{q},{p},{p},{-q * p},0,{q * p},0,0,{"O" if q > 0 else "C"}'


def xfer(sym, d, typ, direction, q):
    return f"Transfers,Data,Stocks,USD,{sym},{d},{typ},{direction},--,--,{q if direction == 'In' else -q},--,0,0,0,"


def stmt(acct, start, end, trades=(), mtm=None, openpos=None, transfers=()):
    """mtm: {sym: (prior, current)} — секцията Mark-to-Market (None → няма секция); openpos: {sym: qty} (None → няма секция Open Positions; {} → секция без редове)."""
    L = ["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement", f'Statement,Data,Period,"{txt(start)} - {txt(end)}"',
         "Account Information,Header,Field Name,Field Value", f"Account Information,Data,Account,{acct}", "Account Information,Data,Base Currency,EUR"]
    if mtm is not None:
        L += [MTH] + [f"Mark-to-Market Performance Summary,Data,Stocks,{s},{a},{b},1,1,0,0,0,0,0," for s, (a, b) in mtm.items()] + ["Mark-to-Market Performance Summary,Data,Total,,,,,,0,0,0,0,0,"]
    if openpos is not None:
        L += [OPH] + [f"Open Positions,Data,Summary,Stocks,USD,{s},{q},1,1,{q},1,{q},0," for s, q in openpos.items()]
    if trades:
        L += [TRH] + list(trades)
    if transfers:
        L += [TRFH] + list(transfers)
    return "\n".join(L) + "\n"


def gain(o, y, sym=None):
    return [x for x in o["fifo"]["realized"] if x["year"] == y and (sym is None or x["sym"] == sym)]


def notes(o, y, level=None):
    return [n["text"] for n in o["de"][y]["notes"] if level is None or n["level"] == level]


mk = lambda kind, acct, sym, date, qty: f"m|{kind}|IBKR|{acct}|{sym}|{date}|{qty}"

print("── 1. начало на отчета: излишъкът (най-старите лотове) не се ползва; липсваща година → видимо съобщение с тикърите (СИНТЕТИЧНО) ──")
s23 = stmt("U1000001", "2023-01-01", "2023-12-29", [t("AAA", "2023-02-01", 100, 10), t("AAA", "2023-03-01", 50, 20)], mtm={"AAA": (0, 150)}, openpos={"AAA": 150})
s25 = stmt("U1000001", "2025-01-01", "2025-11-11", [t("AAA", "2025-03-01", 10, 30), t("AAA", "2025-03-10", -10, 40)], mtm={"AAA": (0, 0)})
o = scenario([{"name": "s23.csv", "text": s23}, {"name": "s25.csv", "text": s25}], years=[2025])
assert [round(x["gainEUR"], 6) for x in gain(o, 2025)] == [100.0], gain(o, 2025)            # 10 × (40 − 30); без контрола лотът от 2023 (цена 10) даваше 300
assert [(c["type"], c["sym"], c["held"], c["reported"], c["dropped"], c["gapYears"]) for c in o["fifo"]["controlLog"]] == [("start", "AAA", 150, 0, 150, [2024])], o["fifo"]["controlLog"]
msg = [n for n in notes(o, 2025, "warn") if "Между отчетите липсва година 2024" in n]
assert msg and "започва без отворени позиции" in msg[0] and "AAA (FIFO 150 бр., отчет 0 бр." in msg[0] and "01.02.2023" in msg[0], notes(o, 2025)
assert o["de"][2025]["complete"] is True
o0 = scenario([{"name": "s23.csv", "text": s23}, {"name": "s25.csv", "text": s25}], years=[2025], noControls=True)
assert [round(x["gainEUR"], 6) for x in gain(o0, 2025)] == [300.0], gain(o0, 2025)          # без контролите — старото (грешно) поведение
print("  ✓ 2025: 10 × (40 − 30) = 100 (без контрола 300 — лотът от 2023); съобщение „Между отчетите липсва година 2024 … AAA (FIFO 150, отчет 0 → без 150 бр. от 01.02.2023, 01.03.2023)“")
s_b = stmt("U1000002", "2023-01-01", "2023-12-29", [t("BBB", "2023-02-01", 60, 10), t("BBB", "2023-03-01", 40, 20)], mtm={"BBB": (0, 100)}, openpos={"BBB": 100})
s_b2 = stmt("U1000002", "2024-01-01", "2024-12-31", [t("BBB", "2024-05-02", -30, 25)], mtm={"BBB": (30, 0)})
o = scenario([{"name": "b1.csv", "text": s_b}, {"name": "b2.csv", "text": s_b2}], years=[2024])
c = o["fifo"]["controlLog"]
assert len(c) == 1 and c[0]["dropped"] == 70 and [(l["date"], l["qty"]) for l in c[0]["lots"]] == [("2023-02-01", 60), ("2023-03-01", 10)] and c[0]["gapYears"] == [], c
assert [round(x["gainEUR"], 6) for x in gain(o, 2024)] == [150.0], gain(o, 2024)             # остават 30 бр. по 20 → 30 × (25 − 20)
assert any("Отчетът за 2024" in n and "лотовете отпреди 01.01.2024 над тях не се ползват" in n for n in notes(o, 2024, "warn")), notes(o, 2024)
print("  ✓ частично: държани 100 (60 + 40), отчетът започва с 30 → без 70 (60 от най-стария + 10 от втория); продажба на 30 → 30 × (25 − 20) = 150; без пропусната година — друго съобщение")

print("── 2. начална позиция без покупки → лот без цена, въвежда се на ръка; никога нулева цена (СИНТЕТИЧНО) ──")
s_c = stmt("U1000003", "2026-01-01", "2026-11-11", [t("CCC", "2026-02-01", -100, 50)], mtm={"CCC": (100, 0)})
o = scenario([{"name": "c.csv", "text": s_c}], years=[2026])
g = gain(o, 2026)
assert len(g) == 1 and g[0]["gainEUR"] is None and g[0]["unknownLots"][0]["key"] == mk("start", "U1000003", "CCC", "2026-01-01", 100), g
assert [(x["kind"], x["sym"], x["qty"], x["filled"]) for x in o["fifo"]["pending"]] == [("start", "CCC", 100, False)] and o["de"][2026]["complete"] is False
assert any("лот без покупна цена" in n and "НЕПЪЛНО" in n for n in notes(o, 2026, "err")) and any("въведи покупна цена и дата" in n for n in notes(o, 2026, "warn"))
assert o["de"][2026]["headline"] == 0 and not o["de"][2026]["items"], "резултатът не е в числото — не е 0 по цена"
print("  ✓ позиция 100 бр. в началото на 2026 без покупки: продажбата няма резултат (null, не нула), годината е НЕПЪЛНО, редът е в списъка за ръчно въвеждане")
o = scenario([{"name": "c.csv", "text": s_c}], years=[2026], manual={mk("start", "U1000003", "CCC", "2026-01-01", 100): {"date": "2024-06-01", "price": 30, "currency": "USD"}})
g = gain(o, 2026)
assert len(g) == 1 and round(g[0]["gainEUR"], 6) == 2000.0 and g[0]["lots"][0]["date"] == "2024-06-01" and o["de"][2026]["complete"] is True and o["fifo"]["pending"][0]["filled"] is True, g
print("  ✓ с въведена покупка (01.06.2024, 30 USD): 100 × (50 − 30) = 2 000; годината е пълна; редът е „попълнен“")

print("── 3. край на отчета: разлика с Open Positions се показва — нищо не се трие; затворена сметка ──")
s_d = stmt("U1000004", "2024-01-01", "2024-12-31", [t("DDD", "2024-02-01", 100, 10)], mtm={"DDD": (0, 90)}, openpos={"DDD": 90})
o = scenario([{"name": "d.csv", "text": s_d}], years=[2024])
assert [(e["sym"], e["reported"], e["computed"], e["closed"]) for e in o["fifo"]["endChecks"]] == [("DDD", 90, 100, False)] and o["de"][2024]["complete"] is False
assert any("отчетът на IBKR показва 90 бр., сметнатите сделки — 100 бр." in n for n in notes(o, 2024, "err"))
assert [x for x in o["fifo"]["open"] if x["key"].endswith("|DDD")][0]["long"] == 100, "лотовете не са изтрити"
print("  ✓ отчет 90, FIFO 100 → червено съобщение, НЕПЪЛНО; позицията във FIFO остава 100 (не се трие тихо)")
s_e = stmt("U1000005", "2024-01-01", "2024-12-31", [t("EEE", "2024-02-01", 40, 10)], mtm={"EEE": (0, 0)}, openpos={})
o = scenario([{"name": "e.csv", "text": s_e}], years=[2024])
assert [(e["sym"], e["reported"], e["computed"], e["closed"]) for e in o["fifo"]["endChecks"]] == [("EEE", 0, 40, True)]
assert any("затворена ли е" in n for n in notes(o, 2024, "err")) and o["de"][2024]["complete"] is False
print("  ✓ затворена сметка (Open Positions без редове), а FIFO държи 40 → „затворена ли е? Липсва прехвърляне, корпоративно действие или продажба?“")
s_f = stmt("U1000006", "2024-01-01", "2024-12-31", [t("FFF", "2024-02-01", 10, 10)], mtm={"FFF": (0, 5)})
o = scenario([{"name": "f.csv", "text": s_f}], years=[2024])
assert [(e["sym"], e["reported"], e["computed"], e["source"][:19]) for e in o["fifo"]["endChecks"]] == [("FFF", 5, 10, "Mark-to-Market Perf")]
print("  ✓ без секция Open Positions краят се сверява с Current Quantity от Mark-to-Market (както отчетът за 2026)")
s_g = stmt("U1000007", "2024-01-01", "2024-12-31", [t("GGG", "2024-02-01", 10, 10)], mtm=None, openpos=None)
o = scenario([{"name": "g.csv", "text": s_g}], years=[2024])
assert o["fifo"]["controlLog"] == [] and o["fifo"]["endChecks"] == [] and o["fifo"]["controlsApplied"] is False
print("  ✓ отчет без Mark-to-Market и без Open Positions — няма контрол (поведението е като преди)")

print("── 4. Inter-Company между собствените сметки: лотовете се пренасят с оригиналната дата и цена (СИНТЕТИЧНО) ──")
a1 = stmt("U2000001", "2024-01-01", "2024-12-31", [t("HHH", "2024-01-10", 100, 10)], mtm={"HHH": (0, 0)}, openpos={}, transfers=[xfer("HHH", "2024-06-03", "Inter-Company", "Out", 100)])
a2 = stmt("U2000002", "2024-01-01", "2024-12-31", [t("HHH", "2024-09-02", -100, 15)], mtm={"HHH": (0, 0)}, openpos={}, transfers=[xfer("HHH", "2024-06-03", "Inter-Company", "In", 100)])
o = scenario([{"name": "a1.csv", "text": a1}, {"name": "a2.csv", "text": a2}], years=[2024])
g = gain(o, 2024)
assert len(g) == 1 and g[0]["account"] == "U2000002" and round(g[0]["gainEUR"], 6) == 500.0 and [(l["date"], l["qty"]) for l in g[0]["lots"]] == [("2024-01-10", 100)], g
assert o["fifo"]["endChecks"] == [] and o["fifo"]["unmatched"] == [] and o["fifo"]["pending"] == [] and o["de"][2024]["complete"] is True
assert any("Inter-Company" in n and "пренесени с оригиналните дати и цени" in n for n in notes(o, 2024))
print("  ✓ купено в 1-ва сметка на 10.01.2024 по 10, пренесено на 03.06.2024, продадено във 2-ра на 02.09.2024 по 15: 100 × (15 − 10) = 500, лотът е от 10.01.2024; без разлики и без липсваща покупка; пълно")
a1b = stmt("U2000003", "2024-01-01", "2024-12-31", [t("HHH", "2024-01-10", 60, 10)], mtm={"HHH": (0, 0)}, openpos={}, transfers=[xfer("HHH", "2024-06-03", "Inter-Company", "Out", 100)])
a2b = stmt("U2000004", "2024-01-01", "2024-12-31", [t("HHH", "2024-09-02", -100, 15)], mtm={"HHH": (0, 0)}, openpos={}, transfers=[xfer("HHH", "2024-06-03", "Inter-Company", "In", 100)])
o = scenario([{"name": "a1.csv", "text": a1b}, {"name": "a2.csv", "text": a2b}], years=[2024])
g = gain(o, 2024)
known = [x for x in g if x["gainEUR"] is not None]; unk = [x for x in g if x["gainEUR"] is None]
assert len(known) == 1 and known[0]["qty"] == 60 and round(known[0]["gainEUR"], 6) == 300.0, g                      # 60 бр. с известна цена: 60 × (15 − 10)
assert len(unk) == 1 and unk[0]["qty"] == 40 and unk[0]["unknownLots"][0]["qty"] == 40 and [(x["kind"], x["qty"]) for x in o["fifo"]["pending"]] == [("xfer", 40)], (g, o["fifo"]["pending"])
assert any("във FIFO има само 60 — липсват покупки за 40" in n for n in notes(o, 2024, "warn"))
print("  ✓ изпратени 100, а в изпращащата сметка има покупки само за 60 → 40 бр. стават лот без цена (на ръка); продажбата се разделя: 60 бр. с резултат (+300), 40 бр. — null (не цена 0)")

print("── 5. ACATS „In“ от друг брокер: лот без цена (на ръка), „Out“ към друг брокер: лотовете излизат (СИНТЕТИЧНО) ──")
x1 = stmt("U3000001", "2024-01-01", "2024-12-31", [t("III", "2024-05-01", -50, 20)], mtm={"III": (0, 0)}, openpos={}, transfers=[xfer("III", "2024-02-01", "ACATS", "In", 50)])
o = scenario([{"name": "x1.csv", "text": x1}], years=[2024])
g = gain(o, 2024); key = mk("acats", "U3000001", "III", "2024-02-01", 50)
assert len(g) == 1 and g[0]["gainEUR"] is None and g[0]["unknownLots"][0]["key"] == key and o["fifo"]["pending"][0]["key"] == key and o["de"][2024]["complete"] is False, g
assert o["fifo"]["unmatched"] == [] and not o["de"][2024]["items"]
print("  ✓ ACATS „In“ 50 бр. на 01.02.2024 и продажба на 20.05.: резултат null (не 0), НЕПЪЛНО; не е „липсва покупка“, а „лот без покупна цена“ с ключ за ръчно въвеждане")
o = scenario([{"name": "x1.csv", "text": x1}], years=[2024], manual={key: {"date": "2023-05-01", "price": 12, "currency": "USD"}})
g = gain(o, 2024)
assert len(g) == 1 and round(g[0]["gainEUR"], 6) == 400.0 and g[0]["lots"][0]["date"] == "2023-05-01" and o["de"][2024]["complete"] is True
print("  ✓ с въведена покупна цена (01.05.2023, 12): 50 × (20 − 12) = 400; пълно")
x2 = stmt("U3000002", "2024-01-01", "2024-12-31", [], mtm={"JJJ": (0, 0)}, openpos={}, transfers=[xfer("JJJ", "2024-03-05", "ACATS", "In", 25)])
x2 = x2.replace("Open Positions,Header", "Open Positions,Header")      # (без продажба: само напомняне)
o = scenario([{"name": "x2.csv", "text": x2}], years=[2024])
assert any("JJJ: 25 бр. прехвърлени от друг брокер на 05.03.2024 — въведи покупна цена и дата" in n for n in notes(o, 2024, "warn")), notes(o, 2024)
print("  ✓ без продажба — съобщение „JJJ: 25 бр. прехвърлени от друг брокер на 05.03.2024 — въведи покупна цена и дата“")
x3 = stmt("U3000003", "2024-01-01", "2024-12-31", [t("KKK", "2024-01-10", 30, 10)], mtm={"KKK": (0, 0)}, openpos={}, transfers=[xfer("KKK", "2024-04-01", "ACATS", "Out", 30)])
o = scenario([{"name": "x3.csv", "text": x3}], years=[2024])
assert gain(o, 2024) == [] and o["fifo"]["endChecks"] == [] and o["fifo"]["open"] == [] and any("към друг брокер" in n and "не е продажба" in n for n in notes(o, 2024))
print("  ✓ ACATS „Out“ 30 бр.: няма продажба, лотовете излизат от FIFO, краят е 0 = отчета")
print("test_tax_controls: ВСИЧКО ОК")
