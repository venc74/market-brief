"""
12.11.2026 (tax-real-fix, Цел 2): НИКОГА ТИХА НУЛА — страницата docs/tax.html в Chromium (Playwright през node — tests/tax_zero_check.js).
ВСИЧКИ входове са СИНТЕТИЧНИ (построени в tests/tax_zero_check.js и от tests/fixtures/tax/). Проверява това, което потребителят вижда: годината не остава на година без данни;
година без записи → „няма данни“, не „0,00 €“; голямото червено съобщение за файл без сделки / непознат файл / липсваща колона; резюмето „Прочетени: …“; продажба без покупка — ред с
броя и датата; сметката е маскирана; „не е сметнато“ се вижда и когато няма нито един запис. Без node или без playwright — изрично SKIP с причината и код 0.
Пускане: python test_tax_silent_zero_page.py
"""
import sys, json, shutil, pathlib, subprocess
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
if subprocess.run([NODE, "-e", "require('playwright')"], capture_output=True).returncode != 0:
    print("SKIP: няма playwright за node — страницата не е проверена в браузър (сметките — в test_tax_silent_zero)"); sys.exit(0)
p = subprocess.run([NODE, str(ROOT / "tests" / "tax_zero_check.js")], capture_output=True, text=True, timeout=300)
if p.returncode != 0 and "Executable doesn't exist" in p.stderr:
    print("SKIP: playwright няма браузър в тази среда"); sys.exit(0)
assert p.returncode == 0, p.stderr[-2000:]
d = json.loads(p.stdout)
Y = d.pop("thisYear")
for k, v in d.items():
    assert not v["errors"] and v["requests"] == [], (k, v["errors"], v["requests"])          # без грешки в страницата и без заявки навън
RED = "rgb(127, 29, 29)"
norm = lambda s: s.replace(" ", " ").replace("\xa0", " ")

print("── 1. отчет само за текущата година: страницата не остава на миналата (до 12.11 — „0.00 €“ без обяснение) ──")
a = d["onlyThisYear"]["first"]
# ръчно (СИНТЕТИЧНО, в EUR): купени 10 × 100 + 1, продадени 10 × 120 − 1 → 1199 − 1001 = 198.00 EUR
assert a["year"] == str(Y) and norm(a["big"]) == "198.00 €" and a["sales"] == f"Продажби {Y} (1)" and a["complete"] is True, (a["year"], a["big"])
assert a["yearLabels"][:2] == [str(Y), f"{Y - 1} — няма данни"], a["yearLabels"]
assert a["summary"].startswith("Прочетени: 1 файл, 2 сделки (1 покупка, 1 продажба), 0 дивидента, 0 лихви; не са сметнати: 0; липсващи покупки: 0."), a["summary"]
assert f"За {Y}: 2 сделки (1 покупка, 1 продажба), продажби с резултат: 1, 0 дивидента, 0 лихви; не са сметнати: 0; липсващи покупки: 0." in a["summary"]
assert a["accountCells"] == ["U••••111"] and a["sectionTables"] == 1 and "U1111111" not in a["filesTable"]
assert a["periods"] == [f"период: January 1, 2026 - November 11, 2026 · данни: {Y}-02-02 … {Y}-03-02"], a["periods"]      # периодът от отчета (синтетичен) и датите на записите
print(f"  ✓ избрана е {Y} (198.00 €, 1 продажба); {Y - 1} е означена „няма данни“; резюмето „Прочетени: 1 файл, 2 сделки …“; сметката — U••••111")

print("── 2. ръчно избрана година без нито един запис → „няма данни“, не „0,00 €“; изборът се пази при добавяне на файл ──")
b = d["onlyThisYear"]["second"]
assert b["year"] == str(Y - 1) and b["big"] == f"няма данни за {Y - 1}" and "0.00" not in b["big"], b["big"]
assert b["whyZero"] == f"Това не е „0,00 €“: в качените файлове няма нито един запис за {Y - 1} — данните са за {Y}; смени годината горе.", b["whyZero"]
assert f"За {Y - 1} няма нито един запис в качените файлове — данните са за {Y}. Смени годината горе." in b["summary"]
c = d["onlyThisYear"]["third"]                                                # добавен е синтетичният отчет за 2020 (една покупка) — потребителят е избрал миналата година и тя остава
assert c["year"] == str(Y - 1) and c["big"] == f"няма данни за {Y - 1}" and f"данните са за 2020, {Y}" in c["whyZero"], (c["year"], c["whyZero"])
assert c["summary"].startswith("Прочетени: 2 файла, 3 сделки (2 покупки, 1 продажба), 0 дивидента, 0 лихви; не са сметнати: 0; липсващи покупки: 0."), c["summary"]
print(f"  ✓ „няма данни за {Y - 1}“ + „Това не е „0,00 €“ … данните са за {Y}“; след още един файл изборът остава, резюмето брои и двата файла")

print("── 3. файл без нито една сделка → голямо червено съобщение с видяното и очакваното ──")
n = d["noTrades"]["first"]
assert [m["title"] for m in n["bigMsgs"]] == ["no_trades.csv: В този файл не намерих сделки"] and n["bigMsgs"][0]["border"] == RED and n["bigMsgs"][0]["size"] == "17px", n["bigMsgs"]
assert "Видях секциите (редове с данни): Statement (3), Account Information (3), Dividends (2)." in n["fileMsgs"] and "Секция „Trades“ в този отчет няма." in n["fileMsgs"]
assert "Очаквах: секция „Trades“ с редове „Data“ от вид „Order“ и колони Asset Category, Currency, Symbol, Date/Time, Quantity, Proceeds или T. Price." in n["fileMsgs"]
assert norm(n["big"]) == "40.00 €" and n["summary"].startswith("Прочетени: 1 файл, 0 сделки (0 покупки, 0 продажби), 1 дивидент, 0 лихви;")     # дивидентът 40 EUR е сметнат
print("  ✓ „В този файл не намерих сделки“ (червено, 17px) + секциите във файла + какво се очаква; дивидентът (40.00 €) е в числото")

print("── 4. продажба без покупка → ред с броя и датата; числото 0 е с причината; НЕПЪЛНО ──")
s = d["sellOnly"]["first"]
assert norm(s["big"]) == "0.00 €" and s["complete"] is False and "НЕПЪЛНО" in s["headline"]
assert s["whyZero"] == "Числото е 0, защото: 1 продажба е без покупка в качените файлове — не е в числото; няма дивиденти и лихви.", s["whyZero"]
assert "Липсващи покупки: 1 — 2026 е НЕПЪЛНО" in s["warnings"]
assert "липсва покупка за ACME (продадени 10 бр. на 02.03.2026; IBKR U••••111) — качи отчета от годината на покупката" in s["warnings"], s["warnings"][:300]
assert "липсващи покупки: 1." in s["summary"]
print("  ✓ „липсва покупка за ACME (продадени 10 бр. на 02.03.2026; IBKR U••••111) — качи отчета от годината на покупката“; „Числото е 0, защото: …“")

print("── 5. непознат файл и отчет с преименувана колона: няма резултат (не „0,00 €“), причината и „не е сметнато“ се виждат ──")
u = d["unknown"]["first"]
assert u["outVisible"] is False and u["big"] is None
assert [m["title"] for m in u["bigMsgs"]] == ["unknown.csv: Не разпознах файла — нищо от него не е сметнато", "Няма резултат: от качените файлове не е прочетен нито един запис (сделка, дивидент или лихва)"]
assert "Първият ред на файла (3 колони): Datum | Betrag | Text" in u["fileMsgs"] and "Това НЕ е „0,00 €“" in u["noout"] and "Не е сметнато: 1 ред" in u["noout"]
r = d["renamed"]["first"]
assert r["outVisible"] is False and [m["title"] for m in r["bigMsgs"]][:2] == ["renamed.csv: В секцията „Trades“ липсват колони: Date/Time", "renamed.csv: В този файл не намерих сделки"]
assert "Заглавен ред 1 в отчета: DataDiscriminator | Asset Category | Currency | Symbol | Trade Time | Quantity" in r["fileMsgs"]
assert "Секцията „Trades“ има 2 реда с данни, но нито един не стана сделка: сделка без дата или количество ×2." in r["fileMsgs"]
assert "Не е сметнато: 2 реда" in r["noout"] and r["noout"].count("може да е облагаем · сделка без дата или количество") == 2
assert r["status"] == "Няма нито един запис за смятане — виж съобщенията под файловете."
print("  ✓ „Не разпознах файла“ с първия ред; „липсват колони: Date/Time“ със заглавния ред от файла; „Няма резултат … Това НЕ е „0,00 €““ + списъкът „не е сметнато“")

print("── 6. няколко файла: годината по подразбиране е най-новата с данни, когато за миналата няма ──")
m = d["many"]["first"]
expect = str(Y - 1) if Y - 1 in (2020, 2021, 2022, 2023) else "2023"
assert m["year"] == expect and m["accountCells"] == ["U••••111", "U••••111", "U••••111", "B2"] and m["sectionTables"] == 3, (m["year"], m["accountCells"])
assert m["summary"].startswith("Прочетени: 4 файла, 11 сделки (5 покупки, 6 продажби), 2 дивидента, 3 лихви, 2 реда удържан данък; не са сметнати: 4 (виж списъка); липсващи покупки: 2."), m["summary"]
assert "Не е сметнато: 4 реда — за 2023: 4 (може да са облагаеми: 1 → 2023 е НЕПЪЛНО)" in d["many"]["second"]["warnings"]
print(f"  ✓ 4 файла (3 от IBKR със сметка U••••111 и таблица по секции, 1 стандартен CSV) → годината {m['year']}; „не е сметнато“ казва колко реда са за годината")
print("\n✅ test_tax_silent_zero_page: всичко мина")
