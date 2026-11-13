"""
14.11.2026 (tax-real-fix, точка 2 от прегледа): прехвърляне „In“ от друг брокер → калкулаторът търси покупката във FIFO на ДРУГИТЕ брокери (по тикър, до датата на прехвърлянето) и пренася цената и датата.
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7 / 9 на CLAUDE.md): ВСИЧКО Е СИНТЕТИЧНО — построено тук (измислени тикъри AAA…, сметки, цени и дати; курс 1,0).
  · IBKR редовете са във формата на РЕАЛНИТЕ отчети (Transfers: …,ACATS,In,…; Trades) — виж test_tax_real_anon.py;
  · отчетът на Revolut е по ПУБЛИЧНОТО описание на формата (Date, Ticker, Type, Quantity, Price per share, Total Amount, Currency, FX Rate) и НЕ Е проверен с реален файл на потребителя
    (до 14.11.2026 реален отчет на Revolut в папката с отчетите няма) — когато се появи, трябва да се пусне tools/tax_diagnose.js върху него.
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP. Пускане: python test_tax_xfer_link.py
"""
import json, shutil, subprocess, sys, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
RATES = "Date,USD,JPY,GBP\n" + "".join(f"{(datetime.date(2019, 1, 1) + datetime.timedelta(days=i)).isoformat()},1.0,1.0,1.0\n" for i in range(0, 365 * 5 + 2))
MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
txt = lambda d: f"{MON[int(d[5:7]) - 1]} {int(d[8:])}, {d[:4]}"


def scenario(files, years=(), **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files + [{"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": settings}),
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    for k in ("de", "summary", "whyZero"):
        o[k] = {int(y): v for y, v in o[k].items()}
    return o


def revolut(rows, owner="A"):
    # Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate — „BUY - MARKET“ / „SELL - MARKET“ (сумата = брой × цена, без такси)
    L = ["Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate"]
    for d, tk, q, p in rows:
        L.append(f"{d}T10:00:00.000Z,{tk},{'BUY' if q > 0 else 'SELL'} - MARKET,{abs(q)},USD {p},USD {abs(q) * p},USD,1.0")
    return {"name": f"revolut_{owner}.csv", "text": "\n".join(L) + "\n", "owner": owner}


def ibkr(acct, start, end, trades=(), transfers=(), owner="A"):
    TRH = "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code"
    TRF = "Transfers,Header,Asset Category,Currency,Symbol,Date,Type,Direction,Xfer Company,Xfer Account,Qty,Xfer Price,Market Value,Realized P/L,Cash Amount,Code"
    L = ["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement", f'Statement,Data,Period,"{txt(start)} - {txt(end)}"',
         "Account Information,Header,Field Name,Field Value", f"Account Information,Data,Account,{acct}", "Account Information,Data,Base Currency,EUR"]
    if trades: L += [TRH] + [f'Trades,Data,Order,Stocks,USD,{s},"{d}, 10:00:00",{q},{p},{p},{-q * p},0,{q * p},0,0,{"O" if q > 0 else "C"}' for s, d, q, p in trades]
    if transfers: L += [TRF] + [f"Transfers,Data,Stocks,USD,{s},{d},ACATS,In,--,--,{q},--,0,0,0," for s, d, q in transfers]
    return {"name": f"ibkr_{acct}.csv", "text": "\n".join(L) + "\n", "owner": owner}


def gains(o, y=2021):
    return [x for x in o["fifo"]["realized"] if x["year"] == y]


R_BUYS = [("2020-03-01", "AAA", 4, 100), ("2020-06-01", "AAA", 6, 120)]                  # две покупки при Revolut: 4 × 100 и 6 × 120
print("── 1. Revolut: покупки; IBKR: ACATS „In“ 7 бр. и продажба на 7 — покупката се намира при Revolut и се пренася ──")
rv = revolut(R_BUYS)
ib = ibkr("U9000001", "2021-01-01", "2021-12-31", trades=[("AAA", "2021-05-02", -7, 150)], transfers=[("AAA", "2021-01-10", 7)])
o = scenario([rv, ib], years=[2021])
f = o["fifo"]
g = gains(o)
assert len(g) == 1 and g[0]["qty"] == 7 and [(l["date"], l["qty"]) for l in g[0]["lots"]] == [("2020-03-01", 4), ("2020-06-01", 3)], g
assert round(g[0]["gainEUR"], 6) == round(7 * 150 - (4 * 100 + 3 * 120), 6) == 290.0, g[0]["gainEUR"]            # продажба 1050 − (400 + 360) = 290
assert f["pending"] == [] and o["de"][2021]["complete"] is True and f["unmatched"] == []
assert len(f["xferLinks"]) == 1 and f["xferLinks"][0]["linked"] == 7 and f["xferLinks"][0]["rest"] == 0 and f["xferLinks"][0]["parts"][0]["broker"] == "Revolut"
assert [(l["date"], l["qty"]) for l in f["xferLinks"][0]["parts"][0]["lots"]] == [("2020-03-01", 4), ("2020-06-01", 3)]
assert any("са свързани с покупките при Revolut" in n["text"] and "4 бр. от 01.03.2020" in n["text"] and "3 бр. от 01.06.2020" in n["text"] and "предположение" in n["text"] for n in o["de"][2021]["notes"] if n["level"] == "info")
print("  ✓ лотовете 4 бр. от 01.03.2020 (по 100) и 3 бр. от 01.06.2020 (по 120) пренесени към IBKR с оригиналните дати и цени; продажба 7 × 150 → резултат 290 € (като при продажба, купена в IBKR); без „липсва покупна цена“; бележка с какво е свързано")
open_rev = [x for x in f["open"] if x["key"].startswith("Revolut")]
assert len(open_rev) == 1 and round(open_rev[0]["long"], 6) == 3, f["open"]
print("  ✓ при Revolut остават 3 бр. (от втората покупка) — прехвърлените лотове са излезли от неговия FIFO")

print("── 2. покупките при другия брокер СЛЕД датата на прехвърлянето не се вземат ──")
o = scenario([revolut(R_BUYS + [("2021-03-01", "AAA", 5, 130)]), ibkr("U9000001", "2021-01-01", "2021-12-31", trades=[("AAA", "2021-05-02", -12, 150)], transfers=[("AAA", "2021-01-10", 12)])], years=[2021])
f = o["fifo"]
assert f["xferLinks"][0]["linked"] == 10 and f["xferLinks"][0]["rest"] == 2 and [(p["kind"], p["qty"]) for p in f["pending"]] == [("acats", 2)], (f["xferLinks"], f["pending"])
assert [x for x in f["open"] if x["key"].startswith("Revolut")][0]["long"] == 5                # при Revolut е останала само покупката след прехвърлянето
print("  ✓ при ACATS 12 бр. на 10.01.2021 и покупки при Revolut: 4 + 6 до тази дата и 5 на 01.03.2021 → свързани са 10 (само до датата), 2 са без цена; покупката от 01.03.2021 остава при Revolut")

print("── 3. при другия брокер има по-малко: свързва се каквото има, останалото е лот без покупна цена (на ръка) ──")
o = scenario([revolut([("2020-03-01", "AAA", 5, 100)]), ibkr("U9000001", "2021-01-01", "2021-12-31", trades=[("AAA", "2021-05-02", -7, 150)], transfers=[("AAA", "2021-01-10", 7)])], years=[2021])
f = o["fifo"]
assert [(p["kind"], p["qty"]) for p in f["pending"]] == [("acats", 2)] and f["xferLinks"][0]["linked"] == 5 and f["xferLinks"][0]["rest"] == 2
g = gains(o)
assert len(g) == 2 and sorted((x["qty"], x["gainEUR"] is None) for x in g) == [(2, True), (5, False)], g                  # 5 бр. с резултат (5 × 150 − 500 = 250), 2 бр. без цена
assert round([x for x in g if x["gainEUR"] is not None][0]["gainEUR"], 6) == 250.0
assert o["de"][2021]["complete"] is False and any("НЕПЪЛНО" in n["text"] for n in o["de"][2021]["notes"] if n["level"] == "err")
print("  ✓ 5 бр. свързани с Revolut (резултат 250 €), 2 бр. — „липсва покупна цена“ (никога нула), годината НЕПЪЛНО до въвеждането; в бележката: „за останалите 2 бр. покупката не е намерена“")

print("── 4. няма отчет на другия брокер / друг тикър / друг собственик / ръчна покупка / настройката е изключена → както преди (лот без цена) ──")
sale = ibkr("U9000001", "2021-01-01", "2021-12-31", trades=[("AAA", "2021-05-02", -7, 150)], transfers=[("AAA", "2021-01-10", 7)])
for what, files, settings in [("няма отчет на Revolut", [sale], {}), ("друг тикър при Revolut", [revolut([("2020-03-01", "BBB", 10, 100)]), sale], {}),
                              ("Revolut е на другия съпруг (owner B)", [revolut(R_BUYS, owner="B"), ibkr("U9000001", "2021-01-01", "2021-12-31", trades=[("AAA", "2021-05-02", -7, 150)], transfers=[("AAA", "2021-01-10", 7)], owner="A")], {}),
                              ("настройката xferLink е изключена", [revolut(R_BUYS), sale], {"xferLink": False})]:
    o = scenario(files, years=[2021], **settings)
    assert [(p["kind"], p["qty"]) for p in o["fifo"]["pending"]] == [("acats", 7)] and o["fifo"]["xferLinks"] == [] and o["de"][2021]["complete"] is False, (what, o["fifo"]["pending"])
    print(f"  ✓ {what}: нищо не се свързва — лот без покупна цена (7 бр.), НЕПЪЛНО")
o = scenario([revolut(R_BUYS), sale], years=[2021], manual={"m|acats|IBKR|U9000001|AAA|2021-01-10|7": {"date": "2020-02-01", "price": 90, "currency": "USD"}})
g = gains(o)
assert o["fifo"]["xferLinks"] == [] and [(l["date"], l["qty"]) for l in g[0]["lots"]] == [("2020-02-01", 7)] and round(g[0]["gainEUR"], 6) == 7 * 150 - 7 * 90, g
print("  ✓ ръчно въведена покупка (дата и цена) има предимство пред търсенето — лотовете при Revolut не се пипат")

print("── 5. тикърът с различно изписване (BRK.B ↔ BRK B) се свързва; пренасянето е само за акции и фондове ──")
o = scenario([revolut([("2020-03-01", "BRK.B", 3, 300)]), ibkr("U9000001", "2021-01-01", "2021-12-31", trades=[("BRK B", "2021-05-02", -3, 350)], transfers=[("BRK B", "2021-01-10", 3)])], years=[2021])
assert o["fifo"]["pending"] == [] and round(gains(o)[0]["gainEUR"], 6) == 150.0, gains(o)
print("  ✓ BRK.B (Revolut) и „BRK B“ (IBKR) са един инструмент: 3 × 350 − 3 × 300 = 150 €")
print("── 6. Inter-Company (прехвърляне между собствени сметки на един брокер) не се търси при друг брокер ──")
ic = ibkr("U9000002", "2021-01-01", "2021-12-31", transfers=[("AAA", "2021-01-10", 5)])
ic["text"] = ic["text"].replace(",ACATS,In,", ",Inter-Company,In,")
o = scenario([revolut(R_BUYS), ic], years=[2021])
assert [(p["kind"], p["qty"]) for p in o["fifo"]["pending"]] == [("xfer", 5)] and o["fifo"]["xferLinks"] == []
print("  ✓ „Inter-Company In“ без съответен „Out“ във файловете остава лот без цена и не взема лотове от Revolut (търсенето е само за прехвърляне от друг брокер)")
o = scenario([revolut(R_BUYS), ibkr("U9000002", "2021-01-01", "2021-12-31", transfers=[("AAA", "2021-01-10", 5)])], years=[2021])
assert [(x["sym"], x["qty"], x["linked"]) for x in o["fifo"]["xferLinks"]] == [("AAA", 5, 5)] and o["fifo"]["pending"] == [] and any("свързани с покупките при Revolut" in n["text"] for n in o["de"][2021]["notes"])
print("  ✓ ACATS „In“ без продажба: свързва се още при прехвърлянето (бележката е в годината на прехвърлянето)")
print("test_tax_xfer_link: ВСИЧКО ОК")
