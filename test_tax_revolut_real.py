"""
14.11.2026 (tax-real-fix, Revolut): РЕАЛНИТЕ формати на двата отчета на Revolut — „Trading account statement“ (Date, Ticker, Type, Quantity, Price per share, Total Amount, Currency, FX Rate; дати ДД/ММ/ГГГГ ЧЧ:ММ:СС;
видове BUY, SELL, DIVIDEND, CASH TOP-UP, CASH WITHDRAWAL, CUSTODY_FEE, MERGER - STOCK, MERGER - CASH) и „Profit and loss“ (Date acquired, Date sold, Symbol, Quantity, Cost basis, Amount, Realised PnL — по ред на ПРОДАДЕН лот).
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7 / 9 на CLAUDE.md): tests/fixtures/tax/revolut_real/*.csv — ЗАГЛАВНИТЕ редове са дословно от реалните отчети на потребителя (14.11.2026), редовете са ИЗМИСЛЕНИ (тикъри ZZZ…, суми, дати 2018–2019);
синтетични изкривявания (ММ/ДД, непарно сливане, втори отчет на сделките, ACATS в IBKR) — построени тук. Курс на USD — 1,0 за всеки ден (EUR = USD), за да се сравнява резултатът с „Realised PnL“.
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP. Пускане: python test_tax_revolut_real.py
"""
import json, shutil, subprocess, sys, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
FX = ROOT / "tests" / "fixtures" / "tax" / "revolut_real"
RATES = "Date,USD,JPY,GBP\n" + "".join(f"{(datetime.date(2017, 1, 1) + datetime.timedelta(days=i)).isoformat()},1.0,1.0,1.0\n" for i in range(0, 365 * 4))
TRADING = (FX / "revolut_trading_real_format.csv").read_text(encoding="utf-8")
PNL = (FX / "revolut_pnl_real_format.csv").read_text(encoding="utf-8")


def scenario(files, years=(), **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files + [{"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": settings}),
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    for k in ("de", "summary", "whyZero"):
        o[k] = {int(y): v for y, v in o[k].items()}
    return o


F = lambda name, text, owner="A": {"name": name, "text": text, "owner": owner}
tr = lambda o: [r for r in o["records"] if r["kind"] == "trade"]
gains = lambda o, y: [x for x in o["fifo"]["realized"] if x["year"] == y]
f2 = lambda x: round(x, 6)

print("── 1. „Trading account statement“: реалният формат (дати ДД/ММ/ГГГГ ЧЧ:ММ:СС, плоски числа, видове BUY / SELL / MERGER …) ──")
assert TRADING.splitlines()[0] == "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate"                     # дословно от реалния файл
o = scenario([F("trading.csv", TRADING)], years=[2018])
f = o["files"][0]
assert f["format"] == "revolut_stocks" and f["broker"] == "Revolut" and f["kinds"]["buy"] == 4 and f["kinds"]["sell"] == 2 and f["kinds"]["dividend"] == 1, f
t = {(r["sym"], r["qty"] > 0): r for r in tr(o)}
a = t[("ZZZA", True)]
assert (a["date"], a["time"]) == ("2018-03-05", "14:07:54") and a["qty"] == 10 and a["currency"] == "USD", a                        # ДД/ММ: 05/03/2018 е 5 март, часът се пази
assert [r for r in o["records"] if r["kind"] == "dividend"][0]["date"] == "2018-10-16"
c = t[("ZZZC", True)]
assert c["qty"] == 0.620395 and abs(c["qty"] * c["price"] - 8.39) < 1e-9 and c["total"] == 8.39, c                                  # сумата е точната; цената = сума ÷ брой (в отчета е закръглена)
print("  ✓ формат revolut_stocks; 05/03/2018 14:07:54 → 2018-03-05 14:07:54 (ДД/ММ, часът се пази); дробен брой 0,620395 с цена = сума ÷ брой (8,39 — не „такса“ от закръгляването)")
sk = [s for s in o["skipped"]]
assert [(s["what"], s["taxable"]) for s in sk] == [("CUSTODY_FEE", False)], sk                                                       # такса за съхранение — не облагаемо, не се приспада; пари (вноска / тегляне) — нищо
print("  ✓ „CUSTODY_FEE“ → „не е сметнато“ (не облагаемо, не се приспада); „CASH TOP-UP“ и „CASH WITHDRAWAL“ са движение на пари — не са доход")
# ММ/ДД: ако второто число е > 12 — американски ред
mdy = TRADING.replace("05/03/2018 14:07:54,ZZZA", "03/25/2018 14:07:54,ZZZA")
o2 = scenario([F("trading.csv", mdy.replace("25/06/2018", "06/25/2018").replace("13/07/2018", "07/13/2018").replace("20/09/2018", "09/20/2018").replace("16/10/2018", "10/16/2018").replace("30/11/2018", "11/30/2018").replace("15/12/2018", "12/15/2018").replace("03/04/2018", "04/03/2018").replace("06/03/2018", "03/06/2018").replace("07/03/2018", "03/07/2018"))])
assert {(r["sym"], r["date"]) for r in tr(o2) if r["qty"] > 0 and r["sym"] in ("ZZZA", "ZZZB")} == {("ZZZA", "2018-03-25"), ("ZZZB", "2018-03-06")}, tr(o2)[:3]
print("  ✓ ако второто число е > 12 (ММ/ДД/ГГГГ) — редът се определя по целия файл: 03/25/2018 → 25 март")

print("── 2. сливане срещу пари: „MERGER - STOCK“ (излизат акции) + „MERGER - CASH“ (пари) = продажба ──")
sell = [r for r in tr(o) if r["sym"] == "ZZZD" and r["qty"] < 0][0]
assert sell["qty"] == -30 and sell["total"] == 220.5 and sell["date"] == "2018-09-20" and sell["viaMerger"] is True, sell
g = gains(o, 2018)
assert [x for x in g if x["sym"] == "ZZZD"][0]["gainEUR"] == f2(220.5 - 193.2) or round([x for x in g if x["sym"] == "ZZZD"][0]["gainEUR"], 6) == 27.3
print("  ✓ 30 бр. излизат, пари 220,50 → продажба на 20.09.2018; резултат 220,50 − 193,20 = 27,30 (като при IBKR — частта в пари е продажба)")
no_cash = "\n".join(l for l in TRADING.splitlines() if "MERGER - CASH" not in l) + "\n"
o3 = scenario([F("trading.csv", no_cash)])
assert any(s["taxable"] and "без парите" in s["reason"] for s in o3["skipped"]) and not [r for r in tr(o3) if r["sym"] == "ZZZD" and r["qty"] < 0]
far = TRADING.replace("20/09/2018 08:17:12,ZZZD,MERGER - CASH", "29/09/2018 08:17:12,ZZZD,MERGER - CASH")
o4 = scenario([F("trading.csv", far)])
assert any(s["taxable"] and "без парите" in s["reason"] for s in o4["skipped"]) and any(s["taxable"] and "MERGER - CASH“ без съответно" in s["reason"] for s in o4["skipped"])
print("  ✓ непарно (няма пари или са над 3 дни по-късно) → червено „не е сметнато“ (облагаемо), в двете посоки — не се гадае")

print("── 3. „Profit and loss“: реалният формат; лотовете се сверяват с отчета на сделките, нищо не се брои два пъти ──")
assert PNL.splitlines()[0] == "Date acquired,Date sold,Symbol,Quantity,Cost basis,Amount,Realised PnL"
o = scenario([F("trading.csv", TRADING), F("pnl.csv", PNL)], years=[2018, 2019])
p = o["files"][1]
assert p["format"] == "revolut_pnl" and p["duplicates"] == 2 and p["kinds"]["buy"] == 1 and p["kinds"]["sell"] == 3, p                  # 2 от 3 покупки вече са в отчета на сделките (ZZZA, ZZZB); добавена е само ZZZE; 3 продажби
assert any("печалби и загуби" in w and "покупки, които вече са в отчета на сделките: 2, добавени: 1" in w and "САМО продадените лотове" in w and "приета е USD" in w for w in o["warnings"]), o["warnings"]
g19 = gains(o, 2019)
assert sorted((x["sym"], round(x["gainEUR"], 6)) for x in g19) == [("ZZZA", 11.52), ("ZZZB", 10.0), ("ZZZE", -30.0)], [(x["sym"], x["gainEUR"]) for x in g19]
assert round(sum(x["gainEUR"] for x in g19), 6) == -8.48                                                                             # = Σ „Realised PnL“ (11,52 + 10,00 − 30,00); курс 1,0
print("  ✓ формат revolut_pnl; покупките от 2018 (вече в отчета на сделките) не се дублират, ZZZE (купена 2019, няма я никъде другаде) се добавя; резултатът на трите продажби = Σ Realised PnL = −8,48")
za = [x for x in g19 if x["sym"] == "ZZZA"][0]
assert [(l["date"], l["qty"]) for l in za["lots"]] == [("2018-03-05", 6)]
print("  ✓ нашият FIFO избира същия лот като „Date acquired“ (ZZZA: 6 бр. от 05.03.2018 — след продадените 4 в отчета на сделките)")
second = "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n15/01/2019 15:00:00,ZZZA,SELL,6,16.00,96.00,USD,1.15\n15/01/2019 15:01:00,ZZZB,SELL,20,26.00,520.00,USD,1.15\n04/02/2019 10:00:00,ZZZE,BUY,3,100.00,300.00,USD,1.14\n18/03/2019 10:00:00,ZZZE,SELL,3,90.00,270.00,USD,1.13\n"
o5 = scenario([F("trading.csv", TRADING), F("trading2019.csv", second), F("pnl.csv", PNL)], years=[2019])
p5 = o5["files"][2]
assert p5["duplicates"] == 6 and p5["kinds"]["buy"] == 0 and p5["kinds"]["sell"] == 0, p5                                              # всичко е вече в отчета на сделките (3 покупки + 3 продажби) → нищо не се добавя
assert sorted((x["sym"], round(x["gainEUR"], 6)) for x in gains(o5, 2019)) == [("ZZZA", 11.52), ("ZZZB", 10.0), ("ZZZE", -30.0)] and len(gains(o5, 2019)) == 3
assert any("покупки, които вече са в отчета на сделките: 3, добавени: 0" in w and "продажби, които вече са в отчета на сделките: 3, добавени: 0" in w for w in o5["warnings"])
print("  ✓ когато и отчетът на сделките за 2019 е качен — всичките 6 реда на „Profit and loss“ са покрити (дубликати 6): нищо не се брои два пъти, резултатът е същият")
bad = PNL.replace("2018-03-06,2019-01-15,ZZZB,20,510.00,520.00,10.00", "2018-03-06,2019-01-15,ZZZB,20,0,520.00,10.00")
o6 = scenario([F("pnl.csv", bad)])
assert any(s["taxable"] and "невалидно" in s["reason"] for s in o6["skipped"])
print("  ✓ лот без цена на придобиване → червено „не е сметнато“ (не нула)")

print("── 4. ACATS „In“ в IBKR се свързва с покупките от отчета на Revolut в РЕАЛНИЯ формат ──")
TRH = "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code"
TRF = "Transfers,Header,Asset Category,Currency,Symbol,Date,Type,Direction,Xfer Company,Xfer Account,Qty,Xfer Price,Market Value,Realized P/L,Cash Amount,Code"
ib = "\n".join(["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement", 'Statement,Data,Period,"January 1, 2019 - December 31, 2019"',
                "Account Information,Header,Field Name,Field Value", "Account Information,Data,Account,U9100001", "Account Information,Data,Base Currency,EUR",
                TRH, 'Trades,Data,Order,Stocks,USD,ZZZB,"2019-05-02, 10:00:00",-20,26,26,520,0,-510,10,0,C', TRF, "Transfers,Data,Stocks,USD,ZZZB,2019-02-01,ACATS,In,--,--,20,--,0,0,0,"]) + "\n"
o7 = scenario([F("trading.csv", TRADING), F("ibkr.csv", ib)], years=[2019])
f7 = o7["fifo"]
assert f7["pending"] == [] and f7["xferLinks"][0]["linked"] == 20 and f7["xferLinks"][0]["parts"][0]["lots"] == [{"date": "2018-03-06", "qty": 20, "unknown": False}], f7["xferLinks"]
assert round(gains(o7, 2019)[0]["gainEUR"], 6) == 10.0 and o7["de"][2019]["complete"] is True
print("  ✓ 20 бр. ZZZB, прехвърлени на 01.02.2019, са купени при Revolut на 06.03.2018 (510,00): свързани с оригиналната дата и цена; продажбата в IBKR дава 520 − 510 = 10; годината е пълна")
print("test_tax_revolut_real: ВСИЧКО ОК")
