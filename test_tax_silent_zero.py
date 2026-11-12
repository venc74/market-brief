"""
12.11.2026 (tax-real-fix, Цел 2): НИКОГА ТИХА НУЛА — калкулаторът винаги казва защо резултатът е такъв (docs/tax_core.js; страницата — в test_tax_silent_zero_page.py).
ВСИЧКИ входове са СИНТЕТИЧНИ (написани тук или от tests/fixtures/tax/ — измислени сметки, тикъри и суми); очакваните числа — сметнати на ръка в коментарите.
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP.
Пускане: python test_tax_silent_zero.py
"""
import json, shutil, subprocess, sys, pathlib
ROOT = pathlib.Path(__file__).parent
FX = ROOT / "tests" / "fixtures" / "tax"
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)


def scenario(files, years=(), mask=(), **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files, "years": list(years), "settings": settings, "mask": list(mask)}),
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    for k in ("de", "summary", "whyZero"):
        out[k] = {int(y): v for y, v in out[k].items()}
    return out


HEAD = ["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement",
        'Statement,Data,Period,"January 1, 2026 - November 11, 2026"',
        "Account Information,Header,Field Name,Field Value", "Account Information,Data,Name,Test Person", "Account Information,Data,Account,U1111111", "Account Information,Data,Base Currency,EUR"]
TRH = "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code"
DIV = ["Dividends,Header,Currency,Date,Description,Amount", "Dividends,Data,EUR,2026-03-16,ACME(US00000000A1) Cash Dividend EUR 1.00 per Share (Ordinary Dividend),40", "Dividends,Data,Total,,,40"]
def ib(*rows): return "\n".join(HEAD + list(rows)) + "\n"
close = lambda a, b: a is not None and abs(a - b) < 1e-6

print("── 1. всеки ред с данни има сметка: записи + „не е сметнато“ + обобщения = редовете в секцията (синтетичните отчети) ──")
names = ["U1111111_2020.csv", "U1111111_2021.csv", "U1111111_2022.csv", "U1111111_2023.csv", "U1111111_Q4_2023.csv", "U1111111_2026.csv"]
r = scenario([{"name": n, "text": (FX / n).read_text(encoding="utf-8")} for n in names])
n_secs = 0
for f in r["files"]:
    assert f["format"] == "ibkr" and f["sections"], f["name"]
    for s in f["sections"]:
        assert s["data"] == s["records"] + s["skipped"] + s["ignored"], (f["name"], s)
        assert s["ignored"] == sum(s["why"].values()), (f["name"], s)
        n_secs += 1
f23 = next(f for f in r["files"] if f["name"] == "U1111111_2023.csv")
sec = {s["name"]: s for s in f23["sections"]}
# Trades 2023: 8 реда = 6 сделки (4 акции + 2 опции) + 1 Forex (не е сметнато) + 1 ClosedLot (обобщение)
assert (sec["Trades"]["data"], sec["Trades"]["records"], sec["Trades"]["skipped"], sec["Trades"]["ignored"]) == (8, 6, 1, 1), sec["Trades"]
assert sec["Trades"]["why"] == {"ClosedLot — лот към сделка, която е броена от реда „Order“": 1} and sec["Trades"]["disc"]["Order × Stocks"] == 4
assert (sec["Dividends"]["data"], sec["Dividends"]["records"], sec["Dividends"]["ignored"]) == (3, 2, 1) and sec["Dividends"]["why"] == {"обобщение (Total)": 1}
assert (sec["Withholding Tax"]["records"], sec["Withholding Tax"]["skipped"], sec["Withholding Tax"]["ignored"]) == (2, 1, 1)
assert sec["Cash Report"]["why"] == {"информативна секция — без сделки и доходи": 1} and sec["Fees"]["skipped"] == 1
assert f23["kinds"] == {"trade": 6, "buy": 2, "sell": 4, "dividend": 2, "withholding": 2, "interest": 3, "split": 0}, f23["kinds"]
assert f23["accountMasked"] == "U••••111" and f23["problems"] == [] and f23["period"] == "January 1, 2023 - December 31, 2023"
print(f"  ✓ {n_secs} секции в {len(r['files'])} файла: нито един ред без следа; за файла — видовете записи, маскираната сметка (U••••111) и периодът")

print("── 2. отчет без нито една сделка → „В този файл не намерих сделки“ + какво е видяно и какво се очаква ──")
r = scenario([{"name": "no_trades.csv", "text": ib(*DIV)}], years=[2026])
f = r["files"][0]
assert f["kinds"]["trade"] == 0 and f["kinds"]["dividend"] == 1 and len(f["problems"]) == 1, f["problems"]
p = f["problems"][0]
assert p["level"] == "err" and p["title"] == "В този файл не намерих сделки", p
assert p["lines"][0] == "Видях секциите (редове с данни): Statement (3), Account Information (3), Dividends (2)."
assert p["lines"][1] == "Очаквах: секция „Trades“ с редове „Data“ от вид „Order“ и колони Asset Category, Currency, Symbol, Date/Time, Quantity, Proceeds или T. Price."
assert p["lines"][2].startswith("Секция „Trades“ в този отчет няма.") and "свали Activity Statement с включена секция Trades" in p["lines"][2]
assert close(r["de"][2026]["headline"], 40) and r["whyZero"][2026] == []                    # дивидентът 40 EUR е сметнат; числото не е 0 → без „защо“
print("  ✓ без секция Trades: секциите, които има; какво се очаква; дивидентът (40 €) е сметнат отделно")

print("── 3. секция Trades с друго име на колоната → липсващи колони; редовете са в „не е сметнато“, всяка година е НЕПЪЛНО ──")
bad_head = TRH.replace("Date/Time", "Trade Time")                          # СИНТЕТИЧНО изкривяване: колоната с датата е преименувана
t = ib(bad_head, 'Trades,Data,Order,Stocks,EUR,ACME,"2026-02-02, 10:00:00",10,100,100,-1000,-1,1001,0,0,O', 'Trades,Data,Order,Stocks,EUR,ACME,"2026-03-02, 10:00:00",-10,120,120,1200,-1,-1001,198,0,C')
r = scenario([{"name": "renamed.csv", "text": t}], years=[2025, 2026])
f = r["files"][0]
titles = [p["title"] for p in f["problems"]]
assert titles == ["В секцията „Trades“ липсват колони: Date/Time", "В този файл не намерих сделки"], titles
assert any("Заглавен ред 1 в отчета: DataDiscriminator | Asset Category | Currency | Symbol | Trade Time | Quantity" in l for l in f["problems"][0]["lines"])
assert "Секцията „Trades“ има 2 реда с данни, но нито един не стана сделка: сделка без дата или количество ×2." in f["problems"][1]["lines"]
assert "Редове по вид (DataDiscriminator × Asset Category): Order × Stocks ×2." in f["problems"][1]["lines"]
assert len(r["skipped"]) == 2 and all(s["taxable"] and s["reason"] == "сделка без дата или количество" for s in r["skipped"])
for y in (2025, 2026):                                                     # годината на редовете не се знае → и двете са НЕПЪЛНО
    assert not r["de"][y]["complete"] and len(r["de"][y]["skippedUndated"]) == 2 and any("без четима дата" in n["text"] for n in r["de"][y]["notes"]), y
print("  ✓ „липсват колони: Date/Time“ със заглавния ред от файла; 2 реда в „не е сметнато“; 2025 и 2026 — НЕПЪЛНО")

print("── 4. непознат файл → „Не разпознах файла“ с първия ред; всяка година е НЕПЪЛНО ──")
good = ib(TRH, 'Trades,Data,Order,Stocks,EUR,ACME,"2026-02-02, 10:00:00",10,100,100,-1000,-1,1001,0,0,O', 'Trades,Data,Order,Stocks,EUR,ACME,"2026-03-02, 10:00:00",-10,120,120,1200,-1,-1001,198,0,C')
r = scenario([{"name": "what.csv", "text": "Datum;Betrag;Text\n01.02.2026;12,50;abc\n"}, {"name": "good.csv", "text": good}], years=[2026])
u = r["files"][0]
assert u["format"] == "unknown" and u["problems"][0]["title"] == "Не разпознах файла — нищо от него не е сметнато"
assert u["problems"][0]["lines"][0] == "Първият ред на файла (3 колони): Datum | Betrag | Text" and "Statement,Header," in u["problems"][0]["lines"][1]
d = r["de"][2026]
assert close(d["headline"], (1200 - 1) - (1000 + 1)) and not d["complete"] and len(d["unreadFiles"]) == 1      # 1199 − 1001 = 198 EUR, но НЕПЪЛНО — единият файл не е прочетен
assert any("Файлът „what.csv“ не е прочетен" in n["text"] and n["level"] == "err" for n in d["notes"])
print("  ✓ непознатият файл: колоните от първия ред + какво се чете; числото от другия файл (198 €) е НЕПЪЛНО")

print("── 5. година без нито един запис → „няма данни“, не „0,00 €“; резюмето „Прочетени: …“ ──")
r = scenario([{"name": "good.csv", "text": good}], years=[2025, 2026])
s25, s26 = r["summary"][2025], r["summary"][2026]
assert s25["empty"] and s25["years"] == [2026] and not s26["empty"]
assert r["whyZero"][2025] == ["в качените файлове няма нито един запис за 2025 — данните са за 2026; смени годината горе"], r["whyZero"][2025]
assert r["whyZero"][2026] == [] and close(r["de"][2026]["headline"], 198)
a = s26["all"]
assert (a["files"], a["trades"], a["buys"], a["sells"], a["dividends"], a["interest"], a["skipped"], a["unmatched"]) == (1, 2, 1, 1, 0, 0, 0, 0), a
assert (s26["year"]["trades"], s26["year"]["sales"], s26["year"]["salesNoRate"], s26["year"]["unmatched"]) == (2, 1, 0, 0)
print("  ✓ 2025: „няма нито един запис … данните са за 2026“; 2026: 198 €; резюме — 1 файл, 2 сделки (1 покупка, 1 продажба), 0 не са сметнати, 0 липсващи покупки")

print("── 6. числото е 0, а има записи → причината: само покупки / продажба без покупка ──")
only_buy = ib(TRH, 'Trades,Data,Order,Stocks,EUR,ACME,"2026-02-02, 10:00:00",10,100,100,-1000,-1,1001,0,0,O')
r = scenario([{"name": "buy.csv", "text": only_buy}], years=[2026])
assert close(r["de"][2026]["headline"], 0) and r["whyZero"][2026] == ["за 2026 няма продажби (само покупки: 1)", "няма дивиденти и лихви"], r["whyZero"][2026]
only_sell = ib(TRH, 'Trades,Data,Order,Stocks,EUR,ACME,"2026-03-02, 10:00:00",-10,120,120,1200,-1,-1001,198,0,C')
r = scenario([{"name": "sell.csv", "text": only_sell}], years=[2026])
d = r["de"][2026]
assert close(d["headline"], 0) and not d["complete"] and r["summary"][2026]["all"]["unmatched"] == 1
assert r["whyZero"][2026] == ["1 продажба е без покупка в качените файлове — не е в числото", "няма дивиденти и лихви"], r["whyZero"][2026]
assert [(u["sym"], u["date"], u["qty"], u["sold"]) for u in d["unmatched"]] == [("ACME", "2026-03-02", 10, 10)]
# частично покрита продажба: купени 4, продадени 10 → 4 бр. с резултат, 6 бр. без покупка (sold = 10, qty = 6)
part = ib(TRH, 'Trades,Data,Order,Stocks,EUR,ACME,"2026-02-02, 10:00:00",4,100,100,-400,0,400,0,0,O', 'Trades,Data,Order,Stocks,EUR,ACME,"2026-03-02, 10:00:00",-10,120,120,1200,0,-400,80,0,C')
r = scenario([{"name": "part.csv", "text": part}], years=[2026])
d = r["de"][2026]
assert [(u["qty"], u["sold"]) for u in d["unmatched"]] == [(6, 10)] and close(d["headline"], 4 * 120 - 400) and not d["complete"]     # 4 × (120 − 100) = 80 EUR; 6 бр. не са в числото
print("  ✓ само покупки → „няма продажби (само покупки: 1)“; продажба без покупка → не е в числото, НЕПЪЛНО; частична: 4 бр. с резултат (80 €), 6 от 10 без покупка")

print("── 7. редове, които до 12.11 изчезваха тихо: дивидент с нечетима дата, непознат вид ред в Trades, ред преди заглавния ред ──")
t = ib(TRH, 'Trades,Data,Order,Stocks,EUR,ACME,"2026-02-02, 10:00:00",10,100,100,-1000,-1,1001,0,0,O', 'Trades,Data,Allocation,Stocks,EUR,ACME,"2026-02-03, 10:00:00",5,100,100,-500,0,500,0,0,O',
       "Dividends,Header,Currency,Date,Description,Amount", "Dividends,Data,EUR,16/03/2026,ACME(US00000000A1) Cash Dividend EUR 1.00 per Share (Ordinary Dividend),40",
       "Interest,Data,EUR,2026-04-03,EUR Credit Interest for Mar-2026,5")
r = scenario([{"name": "quiet.csv", "text": t}], years=[2026])
why = {(s["section"], s["reason"]): s["taxable"] for s in r["skipped"]}
assert why == {("Trades", "непознат вид ред „Allocation“ в Trades (чета „Order“ / „Trade“)"): True,
               ("Dividends", "ред без четима дата или сума (очаквам Date = ГГГГ-ММ-ДД и Amount = число)"): True,
               ("Interest", "ред с данни без заглавен ред на секцията — не може да се прочете"): True}, why
d = r["de"][2026]
assert not d["complete"] and len(d["skippedTaxable"]) == 1 and len(d["skippedUndated"]) == 2       # Allocation — с дата (2026); дивидентът и лихвата — без четима дата
print("  ✓ трите реда са в „не е сметнато“ с причината и „може да е облагаем“; 2026 — НЕПЪЛНО")

print("── 8. маскиране на сметката ──")
r = scenario([{"name": "good.csv", "text": good}], mask=["U1111111", "U12345", "акции · съпруг/а", "default", "B2", ""])
assert r["masked"] == ["U••••111", "U••345", "акции · съпруг/а", "default", "B2", ""], r["masked"]
print("  ✓ U1111111 → U••••111; имена без номер (Revolut „акции“, „default“) остават")
print("\n✅ test_tax_silent_zero: всичко мина")
