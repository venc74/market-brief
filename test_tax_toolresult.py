"""
13.11.2026 (tax-real-fix, точка 3 от прегледа): файловете „Fiscal Year“ в папката с отчетите са РЕЗУЛТАТ на друга данъчна програма (колони Fiscal Year, Broker, Acquisition Date / Dividend Date …),
не отчет на брокер. Калкулаторът ги разпознава: покрити от прочетените отчети → само бележка „не се ползва“ (годината НЕ става непълна заради тях); с брокер или година без отчет тук → червено + „не е сметнато“.
Excel (.xlsx) → „не се чете“ (червено, не „непознат формат“ с боклук като първи ред).
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7 / 9 на CLAUDE.md):
  1 · ЗАГЛАВНИТЕ редове на tests/fixtures/tax/toolresult/*.csv са ДОСЛОВНО от реални файлове (13.11.2026); редовете под тях са ИЗМИСЛЕНИ (тикъри ZZZ…, суми от въображението);
      IBKR отчетите (календарни години 2019–2021) са СИНТЕТИЧНИ, във формата на реалните (построени тук — тестът не зависи от случайните дати на real_anon); Revolut — синтетичен (revolut_trading_synthetic.csv, 2023);
  2 · СИНТЕТИЧНИ изкривявания (друг брокер, година без отчет, Excel) — построени тук от горните.
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP. Пускане: python test_tax_toolresult.py
"""
import json, re, shutil, subprocess, sys, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
FX = ROOT / "tests" / "fixtures" / "tax"
TR = FX / "toolresult"
RATES = "Date,USD,JPY,GBP,CHF\n" + "".join(f"{(datetime.date(2019, 1, 1) + datetime.timedelta(days=i)).isoformat()},1.0,1.0,1.0,1.0\n" for i in range(0, 365 * 5))


def scenario(files, years=()):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files + [{"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": {}}),
                       capture_output=True, text=True, timeout=240)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    o["de"] = {int(y): v for y, v in o["de"].items()}
    return o


rd = lambda p: {"name": p.name, "text": p.read_text(encoding="utf-8")}
def stmt(year):                                                                           # СИНТЕТИЧЕН IBKR отчет за календарна година (формат — като в реалните отчети): покупка и продажба на AAA
    L = ["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement", f'Statement,Data,Period,"January 1, {year} - December 31, {year}"',
         "Account Information,Header,Field Name,Field Value", "Account Information,Data,Account,U7000001", "Account Information,Data,Base Currency,EUR",
         "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code",
         f'Trades,Data,Order,Stocks,USD,AAA,"{year}-03-02, 10:00:00",10,10,10,-100,0,100,0,0,O', f'Trades,Data,Order,Stocks,USD,AAA,"{year}-09-02, 10:00:00",-10,12,12,120,0,-100,20,0,C']
    return {"name": f"ibkr_{year}.csv", "text": "\n".join(L) + "\n"}


ibkr = [stmt(y) for y in (2019, 2020, 2021)]
tools = [rd(f) for f in sorted(TR.glob("toolresult_*.csv"))]
byname = lambda o, n: next(f for f in o["files"] if f["name"] == n)

print("── 1. реалните заглавия се разпознават (3 вида: дивиденти 14 колони, продажби 17 и 21 колони) ──")
assert all(t["text"].startswith("﻿") for t in tools), "фикстурите пазят BOM-а като в оригинала"
o = scenario(tools, years=[2021])
assert [f["format"] for f in o["files"] if f["name"].startswith("toolresult")] == ["taxtool_result"] * 3, [f["format"] for f in o["files"]]
assert o["records"] == [] and not any(f["format"] == "unknown" for f in o["files"])
d = byname(o, "toolresult_sales_21col.csv")
assert d["notSource"] is True and d["tool"]["kind"] == "sales" and d["tool"]["rows"] == 4 and d["tool"]["years"] == [2019, 2020, 2021], d["tool"]
assert d["tool"]["pairs"] == [{"year": 2019, "broker": "IBKR", "n": 1}, {"year": 2020, "broker": "IBKR", "n": 1}, {"year": 2021, "broker": "IBKR", "n": 2}], d["tool"]["pairs"]
d17 = byname(o, "toolresult_sales_17col.csv")
assert d17["tool"]["kind"] == "sales" and d17["tool"]["rows"] == 3 and {p["broker"] for p in d17["tool"]["pairs"]} == {"ibkr"}                 # малки букви в по-стария файл — както в реалния
dd = byname(o, "toolresult_dividends.csv")
assert dd["tool"]["kind"] == "dividends" and dd["tool"]["rows"] == 3 and dd["tool"]["years"] == [2019, 2021]
print("  ✓ формат taxtool_result за трите файла; брокер и години по колоните; записи 0 (резултатът не е източник на лотове)")

print("── 2. покрит от отчетите на брокера → бележка, годината НЕ става непълна заради файла ──")
base = scenario(ibkr, years=[2019, 2020, 2021])
o = scenario(ibkr + tools, years=[2019, 2020, 2021])
for t in tools:
    d = byname(o, t["name"])
    assert "error" in d and d["error"] is None and d["problems"] == [] and "не се ползва" in d["note"] and "брокер: " in d["note"], d
assert not [s for s in o["skipped"] if s["section"] == "файл"], [s for s in o["skipped"] if s["section"] == "файл"]
for y in (2019, 2020, 2021):
    assert o["de"][y]["complete"] == base["de"][y]["complete"] and o["de"][y]["headline"] == base["de"][y]["headline"], y
    assert [n["text"] for n in o["de"][y]["notes"] if n["level"] == "err"] == [n["text"] for n in base["de"][y]["notes"] if n["level"] == "err"], y   # същите червени бележки — нито една повече
    assert o["de"][y]["unreadFiles"] == []
assert o["summary"]["2021"]["all"]["files"] == base["summary"]["2021"]["all"]["files"], "покритият резултат не е „прочетен отчет“"
print("  ✓ 2019–2021: същото число, същата пълнота, същите червени бележки с и без трите файла; в „не е сметнато“ няма ред „файл“; бележката казва, че не е източник")

print("── 3. брокер или година без отчет тук → червено, „не е сметнато“, годината непълна ──")
sales = next(t for t in tools if t["name"] == "toolresult_sales_21col.csv")
for what, text, need in [
        ("друг брокер без отчет (Revolut)", sales["text"].replace("IBKR", "Revolut"), "Revolut 2019"),
        ("година без отчет (2017)", sales["text"].replace("2019,STOCK,ZZZA,2019-03-14", "2017,STOCK,ZZZA,2017-03-14", 1), "IBKR 2017")]:
    o = scenario(ibkr + [{"name": "tool.csv", "text": text}], years=[2021])
    d = byname(o, "tool.csv")
    assert d["error"] and d["problems"][0]["level"] == "err" and need in d["problems"][0]["lines"][1], d
    sk = [s for s in o["skipped"] if s["section"] == "файл"]
    assert len(sk) == 1 and sk[0]["taxable"] and need in sk[0]["reason"], sk
    assert o["de"][2021]["complete"] is False and any("НЕПЪЛНО" in n["text"] and "tool.csv" in n["text"] for n in o["de"][2021]["notes"] if n["level"] == "err"), o["de"][2021]["notes"]
    print(f"  ✓ {what}: червено съобщение, ред в „не е сметнато“, 2021 е НЕПЪЛНО")
o = scenario([{"name": "tool.csv", "text": sales["text"]}], years=[2021])                       # самият резултат без никакъв отчет — нищо не го покрива
assert byname(o, "tool.csv")["error"] and o["de"][2021]["complete"] is False
print("  ✓ резултат без нито един отчет на брокера: червено (нищо не го покрива)")
rev = rd(FX / "revolut_trading_synthetic.csv")
o = scenario(ibkr + [rev, {"name": "tool.csv", "text": re.sub(r"(?m)^(2019|2020|2021),STOCK", "2023,STOCK", sales["text"].replace("IBKR", "Revolut"))}], years=[2021])
assert byname(o, "tool.csv")["error"] is None and "Revolut" in byname(o, "tool.csv")["note"], byname(o, "tool.csv")
print("  ✓ Revolut 2023 в резултата е покрит от прочетения отчет на Revolut за 2023 (синтетичен) — само бележка")
bad = sales["text"].replace("2021,STOCK,ZZZB", "x,STOCK,ZZZB", 1)
o = scenario(ibkr + [{"name": "tool.csv", "text": bad}], years=[2021])
assert byname(o, "tool.csv")["error"] and "без валидна" in byname(o, "tool.csv")["problems"][0]["lines"][1]
print("  ✓ ред без валидна „Fiscal Year“ → червено (не се пропуска тихо)")

print("── 4. Excel (.xlsx): не се чете, казва се какво е ──")
zipish = "PK\u0003\u0004\u0014\u0000\u0006\u0000\u0008\u0000\u0000\u0000!\u0000�[Content_Types].xml�"
o = scenario(ibkr + [{"name": "interest_x.xlsx", "text": zipish}], years=[2021])
d = byname(o, "interest_x.xlsx")
assert d["format"] == "xlsx" and "Excel" in d["error"] and d["problems"][0]["level"] == "err"
assert any(s["section"] == "файл" and s["taxable"] and "Excel" in s["reason"] for s in o["skipped"]) and o["de"][2021]["complete"] is False
print("  ✓ формат xlsx → червено „Excel файл — нищо от него не е сметнато“, ред в „не е сметнато“, годината НЕПЪЛНО (не „непознат формат“)")
print("test_tax_toolresult: ВСИЧКО ОК")
