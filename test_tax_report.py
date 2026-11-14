"""
13.11.2026 (tax-report): отчетът за Finanzamt и подредбата на „Не е сметнато“ в данъчния калкулатор (docs/tax_core.js, docs/tax_report.js, docs/tax_ui.js, docs/tax.html).
  1) „Не е сметнато“ на групи: ИЗКЛЮЧЕНО ПО ЗАКОН (такси — § 20 ал. 9 EStG: котировки, ADR, други) и редове без данъчно значение — информация, НЕ прави годината НЕПЪЛНО; ЗА ПРОВЕРКА (Forex, данък върху лихви) — също не;
     ЛИПСВАЩИ ДАННИ (облагаемо / нечетимо — напр. ред без четима дата или нечетим вид инструмент) — единственото, което прави годината НЕПЪЛНО.
  CYEP / SYEP (14.11): положителните редове на „CYEP/Broker Fees“ са доход, който НЕ е в секция Interest — смята се като „други доходи от капитал“ (Zeile 19) с етикет; „За проверка“ (Forex, данък върху лихви) е САМО в калкулатора, не в отчета.
  2) Отчетът (TC.reportModel + TC.reportHTML): цял на НЕМСКИ (без кирилица), сумите му = сумите на страницата, при НЕПЪЛНО — червена рамка с причините, без външни библиотеки и без мрежа.
  3) Бутоните и печатът: статични проверки на docs/tax.html и docs/tax_ui.js (Playwright тук няма — оформлението е проверено в браузъра ръчно, виж доклада).
  4) ОТЧЕТЪТ Е САМО ЗА ИЗБРАНАТА ГОДИНА (14.11): продажби, доходи и такси с дата в нея; „Besondere Vorgänge“ само за лотове, продадени в нея (събитието може да е от по-ранна година); „Offene Punkte“ само за нея; „Quellen“ само файловете, от които идват данни за нея (вкл. по-стар файл с покупката).
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7 / 9 на CLAUDE.md): СИНТЕТИЧНИ — CSV и IBKR редове, построени тук (тикъри AAA…, сметка U9300001, суми и дати от въображението; курсът на USD е различен за всеки ден, за да личи къде е ползван кой курс).
ЗАГЛАВНИТЕ редове на IBKR секциите Fees, CYEP/Broker Fees, SYEP Fee Details, Withholding Tax са дословно от РЕАЛНИТЕ отчети на потребителя (13.11.2026, само имената на колоните); редовете под тях са измислени.
РЕАЛЕН ФОРМАТ с анонимни стойности: tests/fixtures/tax/real_anon/ibkr_summary_202107_202205.csv и tests/fixtures/tax/revolut_real/revolut_trading_real_format.csv (виж README там).
Без мрежа; node — tests/tax_driver.js scenario (sc.report). Без node — SKIP. Пускане: python test_tax_report.py
"""
import json, shutil, subprocess, sys, pathlib, datetime, re
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
START = datetime.date(2017, 1, 1)
rate = lambda d: 1.0 + ((datetime.date.fromisoformat(d) - START).days % 7) / 100                      # курсът на USD е различен за всеки ден (1,00 … 1,06) — ЕЦБ има курс и в събота / неделя в тази таблица
RATES = "Date,USD,JPY,GBP\n" + "".join(f"{(START + datetime.timedelta(days=i)).isoformat()},{rate((START + datetime.timedelta(days=i)).isoformat()):.2f},1.0,1.0\n" for i in range(0, 365 * 10))
CYR = re.compile("[Ѐ-ӿ]")


def scenario(files, years, ecb=True, **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files + ([{"name": "ecb.csv", "text": RATES}] if ecb else []), "years": list(years), "settings": settings,
                       "report": True, "name": "Erika Mustermann (Test)", "now": "2026-01-02", "rateSource": {"USD": "файла на ЕЦБ до страницата (eurofxref-hist.csv, до 2026-10-29)"}}), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    for k in ("de", "decl", "report", "groups"):
        o[k] = {int(y): v for y, v in o[k].items()}
    return o


def dfmt(x):                                                                                       # 1.234,56 € (с неразделим интервал) — както TC.fmtDE
    s = f"{abs(x):,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return ("−" if x < 0 else "") + s + " €"


H = "type,ticker,date,quantity,price,currency,broker,account,asset_type,withholding_tax\n"
rw = lambda t, k, d, q, p, w="": f"{t},{k},{d},{q},{p},USD,CSV,main,stock,{w}\n"
BASE = H + rw("buy", "AAA", "2025-02-15", 10, 10) + rw("sell", "AAA", "2025-02-16", 10, 30) + rw("buy", "BBB", "2025-03-08", 10, 100) + rw("sell", "BBB", "2025-04-05", 10, 50) \
    + rw("dividend", "CCC", "2025-04-06", 100, "", 15) + rw("interest", "INT", "2025-05-03", 20, "") + rw("dividend", "EEE", "2025-05-04", -10, "")
HEAD = ["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", 'Statement,Data,Period,"March 10, 2025 - November 27, 2025"',
        "Account Information,Header,Field Name,Field Value", "Account Information,Data,Account,U9300001", "Account Information,Data,Base Currency,EUR"]
FEES = ["Fees,Header,Subtitle,Currency,Account,Date,Description,Amount",
        "Fees,Data,Other Fees,EUR,U9300001,2025-03-12,v1234567:NASDAQ Level I for Mar 2025,-1.5", "Fees,Data,Other Fees,EUR,U9300001,2025-04-12,v1234567:NYSE Level I for Apr 2025,-1.5",
        "Fees,Data,Other Fees,EUR,U9300001,2025-05-12,Cancel[v1234567:NYSE Level I for Apr 2025] FOR APR 2025,1",
        "Fees,Data,Other Fees,USD,U9300001,2025-06-13,ZZZ(US0000000001) ADR Fee USD 0.02 per Share,-2", "Fees,Data,Other Fees,USD,U9300001,2025-06-14,XXX(US0000000002) Cash Dividend USD 0.1 per Share - FEE,-3",
        "Fees,Data,Other Fees,USD,U9300001,2025-07-14,Platform fee,-4", "Fees,Data,Total,,,,,-9"]
NAV = ["Change in NAV,Data,Starting Value,1000", "Change in NAV,Data,Ending Value,1100", "Change in NAV,Data,Other Fees,-9"]        # без заглавен ред — както в реалните отчети за 2025 и 2026
DISC = ["Disclaimer,Header,Field Name,Field Value", "Disclaimer,Data,Disclaimer,Synthetic text"]
FX = ["Trades,Header,DataDiscriminator,Asset Category,Currency,Account,Symbol,Date/Time,Quantity,T. Price,Proceeds,Comm/Fee,Code", 'Trades,Data,Order,Forex,USD,U9300001,EUR.USD,"2025-03-13, 10:00:00",1000,1.08,-1080,-2,']
WHT = ["Withholding Tax,Header,Currency,Account,Date,Description,Amount,Code", "Withholding Tax,Data,USD,U9300001,2025-05-16,Withholding @ 20% on Credit Interest for Apr-2025,-0.5,"]
CYEP = lambda *rows: ["CYEP/Broker Fees,Header,Currency,Date,Description,Amount,Code"] + [f"CYEP/Broker Fees,Data,{r}" for r in rows]
SYEP_DET = lambda *rows: ["Stock Yield Enhancement Program Securities Lent Fee Details,Header,Currency,Value Date,Symbol,Start Date,Quantity,Collateral Amount,Market-based Fee Rate (%),Net Lend Fee Rate (%) Paid to Customer,Net Lend Fee Paid to Customer,Code"] \
    + [f"Stock Yield Enhancement Program Securities Lent Fee Details,Data,USD,{d},AAA,{d},10,1000,5,3,{a}," for d, a in rows]
ibkr = lambda *parts: "\n".join(sum(parts, HEAD)) + "\n"
F = lambda name, text: {"name": name, "text": text}
kind = lambda g, grp, k: next((x for x in g[grp] if x["kind"] == k), None)
SUM_FIELDS = ["Ausländische Kapitalerträge (ohne Beträge laut den Zeilen 26a und 52)", "In den Zeilen 18 und 19 enthaltene Gewinne aus Aktienveräußerungen i. S. d. § 20 Abs. 2 Satz 1 Nr. 1 EStG",
              "In den Zeilen 18 und 19 enthaltene Verluste ohne Verluste aus der Veräußerung von Aktien", "In den Zeilen 18 und 19 enthaltene Verluste aus der Veräußerung von Aktien", "Anrechenbare noch nicht angerechnete ausländische Steuern"]

print("── 1. „Не е сметнато“ на групи: такси и обобщения са информация; Forex и данък върху лихви — за проверка; годината остава ПЪЛНА ──")
o = scenario([F("s.csv", BASE), F("ibkr.csv", ibkr(FEES, NAV, DISC, FX, WHT))], [2025], joint=True)
g, d = o["groups"][2025], o["de"][2025]
assert g["missing"] == [] and d["complete"] is True and o["decl"][2025]["complete"] is True, (g["missing"], d["notes"])
q, a, ot = kind(g, "law", "fee_quote"), kind(g, "law", "fee_adr"), kind(g, "law", "fee_other")
assert (q["year"]["n"], round(q["year"]["totals"]["EUR"], 6), round(q["year"]["eur"], 6)) == (3, -2.0, -2.0), q["year"]            # 2 такси + 1 сторно (положително) = нето −2,00 EUR
assert (a["year"]["n"], round(a["year"]["totals"]["USD"], 6)) == (2, -5.0) and abs(a["year"]["eur"] - (-2 / rate("2025-06-13") - 3 / rate("2025-06-14"))) < 1e-9, a["year"]   # ADR такса и „Cash Dividend … – FEE“ — всяка по курса на своя ден
assert (ot["year"]["n"], round(ot["year"]["totals"]["USD"], 6)) == (1, -4.0) and abs(ot["year"]["eur"] + 4 / rate("2025-07-14")) < 1e-9
assert all("§ 20 ал. 9 EStG" in x["basisBg"] and "§ 20 Abs. 9 EStG" in x["basisDe"] for x in (q, a, ot))
sm = kind(g, "info", "summary")
assert sm["all"]["n"] == 4 and sm["year"]["n"] == 0 and sm["noDate"] == 4, sm["all"]                                                         # 3 реда „Change in NAV“ без заглавен ред + „Disclaimer“ — без дата, не облагаеми
fx, iw = kind(g, "review", "fx"), kind(g, "review", "interest_withholding")
assert "§ 23 EStG (Fremdwährung, в рамките на 1 година) — провери" in fx["basisBg"] and fx["byYear"]["2025"]["n"] == 1 and abs(fx["byYear"]["2025"]["totals"]["USD"] - 1080) < 1e-9 and abs(fx["byYear"]["2025"]["eur"] - 1080 / rate("2025-03-13")) < 1e-9, fx["byYear"]   # оборот (Σ |Proceeds|) по години
assert fx["year"]["n"] == 1 and iw["year"]["n"] == 1 and abs(iw["year"]["totals"]["USD"] + 0.5) < 1e-9 and abs(iw["year"]["eur"] + 0.5 / rate("2025-05-16")) < 1e-9
assert [x["kind"] for x in g["law"]] == ["fee_quote", "fee_adr", "fee_other"] and [x["kind"] for x in g["info"]] == ["summary"] and sorted(x["kind"] for x in g["review"]) == ["fx", "interest_withholding"]
print("  ✓ изключено по закон (§ 20 ал. 9 EStG): котировки 3 реда нето −2,00 €; ADR 2 реда (−5,00 USD, всеки по курса на деня си); други такси 1 ред (−4,00 USD); обобщения 4 реда (3 × Change in NAV без заглавен ред + Disclaimer, без дата);")
print("    за проверка: Forex 1, данък върху лихви 1 (−0,50 USD) — липсващи данни: 0, 2025 е ПЪЛНА; суми и основание по вид, не ред по ред")
print("── 2. CYEP / SYEP: положителните редове са ДОХОД, който не е в секция Interest → „други доходи от капитал“ с етикет; отрицателните — такса ──")
INT = ["Interest,Header,Currency,Account,Date,Description,Amount", "Interest,Data,USD,U9300001,2025-08-29,USD Credit Interest for Aug-2025,40"]
o = scenario([F("s.csv", BASE), F("ibkr.csv", ibkr(CYEP("USD,2025-08-20,USD CYEP Income for Aug-2025,5,", "USD,2025-10-09,USD IBKR Managed Securities (SYEP) Fees Adjustment for Oct-2025,-1.5,"), INT))], [2025])
g, d, dc = o["groups"][2025], o["de"][2025], o["decl"][2025]
y5 = [r for r in o["records"] if r["kind"] == "yield"]
assert len(y5) == 1 and y5[0]["amount"] == 5 and y5[0]["currency"] == "USD" and y5[0]["date"] == "2025-08-20" and y5[0]["desc"] == "USD CYEP Income for Aug-2025"
assert g["missing"] == [] and d["complete"] is True and d["skippedTaxable"] == [], (g["missing"], d["notes"])
oi = [i for i in d["items"] if i["cat"] == "otherIncome"]
assert len(oi) == 1 and abs(oi[0]["eur"] - 5 / rate("2025-08-20")) < 1e-9 and oi[0]["sym"] == "USD CYEP Income for Aug-2025"                       # по курса на деня на реда
intr = [i for i in d["items"] if i["cat"] == "interest" and i["date"] == "2025-08-29"]
assert len(intr) == 1 and abs(intr[0]["eur"] - 40 / rate("2025-08-29")) < 1e-9 and len([i for i in d["items"] if i["cat"] == "interest"]) == 2                                                                         # Interest е отделно — не се смесва и не се брои двойно
z19 = dc["rows"][0]["eur"]
exp19 = (300 / rate("2025-02-16") - 100 / rate("2025-02-15")) - (1000 / rate("2025-03-08") - 500 / rate("2025-04-05")) + 100 / rate("2025-04-06") + 20 / rate("2025-05-03") + oi[0]["eur"] + intr[0]["eur"] - 10 / rate("2025-05-04")
assert abs(z19 - exp19) < 1e-9 and dc["control"]["ok"] is True and "+ CYEP / SYEP доход" in dc["rows"][0]["why"], (z19, exp19)                  # Zeile 19 = ръчна сметка (с CYEP + Interest)
assert dc["parts"]["yld"] == oi[0]["eur"] and "otherIncome" in json.dumps(o["de"][2025]["items"])
assert kind(g, "law", "fee_other")["year"]["n"] == 1 and abs(kind(g, "law", "fee_other")["year"]["totals"]["USD"] + 1.5) < 1e-9                  # отрицателният ред е такса — информация
print("  ✓ „CYEP Income“ +5,00 USD (20.08.2025) → запис „yield“ → „Други доходи от капитал“ по курса на деня; Interest (40 USD) е отделен — не се брои двойно; Zeile 19 = ръчната сметка; годината е ПЪЛНА (не е „липсващи данни“); отрицателният ред — такса")
o = scenario([F("s.csv", BASE), F("ibkr.csv", ibkr(CYEP("USD,2025-07-31,USD IBKR Managed Securities (SYEP) Fees for Jul-2025,4.5,"), SYEP_DET(("2025-07-22", 1.0), ("2025-07-24", 1.5), ("2025-07-25", 2.0))))], [2025])
g = o["groups"][2025]
assert kind(g, "info", "detail")["all"]["n"] == 3 and g["missing"] == [] and [r["amount"] for r in o["records"] if r["kind"] == "yield"] == [4.5], (g["info"], g["missing"])   # подробностите съвпадат с месечния ред (4,5) → „вече включени“; месечният ред — доход
o = scenario([F("s.csv", BASE), F("ibkr.csv", ibkr(SYEP_DET(("2025-07-22", 1.0), ("2025-07-24", 1.5), ("2025-07-25", 2.0))))], [2025])
g = o["groups"][2025]
assert kind(g, "info", "detail") is None and len(g["missing"]) == 3 and o["de"][2025]["complete"] is False                                       # без съвпадащ месечен ред — всеки ред е облагаем
print("  ✓ SYEP: 3 дневни реда със сума 4,50 = месечния ред → „подробности, вече включени“ (информация); месечният ред 4,50 е доход; без месечен ред → и трите дневни са липсващи данни, годината е НЕПЪЛНО")
# липсващи данни: нечетим вид инструмент
FUT = ["Trades,Header,DataDiscriminator,Asset Category,Currency,Account,Symbol,Date/Time,Quantity,T. Price,Proceeds,Comm/Fee,Code", 'Trades,Data,Order,Futures,USD,U9300001,ESZ5,"2025-06-12, 10:00:00",1,100,-100,-1,']
o = scenario([F("s.csv", BASE), F("ibkr.csv", ibkr(FUT))], [2025])
g, d = o["groups"][2025], o["de"][2025]
assert len(g["missing"]) == 1 and g["missing"][0]["section"] == "Trades" and g["missing"][0]["taxable"] is True and d["complete"] is False and len(d["skippedTaxable"]) == 1
print("  ✓ фючърс в Trades (не се смята) → липсващи данни (червено), 2025 е НЕПЪЛНО — единственото, което прави годината непълна")

print("── 3. отчетът: немски, заглавие, име, дата, раздели, подпис; без кирилица ──")
o = scenario([F("s.csv", BASE), F("ibkr.csv", ibkr(FEES, NAV, DISC, FX, WHT))], [2025], joint=True)
m, html = o["report"][2025]["model"], o["report"][2025]["html"]
assert m["title"] == "Aufstellung der Kapitalerträge 2025 — selbst erstellt" and f"<h1>{m['title']}</h1>" in html
assert "Erika Mustermann (Test)" in html and "Steuerjahr" in html and "02.01.2026" in html and "Zusammenveranlagung" in html
for h in ("Zusammenfassung — Anlage KAP", "Methode", "Veräußerungen 2025", "Dividenden 2025", "Zinsen 2025", "Quellensteuer 2025", "Besondere Vorgänge", "Nicht berücksichtigt — nicht abzugsfähig", "Offene Punkte", "Quellen — ausgewertete Dateien"):
    assert f"<h2>{h}</h2>" in html, h
assert "Selbst erstellte Aufstellung auf Grundlage der beigefügten Originalabrechnungen des Brokers. Keine Steuerberatung." in html
assert "§ 20 Abs. 4 Satz 1 EStG" in html and "Referenzkurs der Europäischen Zentralbank (EZB)" in html and "FIFO" in html and "§ 20 Abs. 4 Satz 7 EStG" in html and "zuletzt davor veröffentlichte Kurs" in html     # Methode
assert not CYR.search(html), CYR.search(html).group(0) + " … " + html[max(0, CYR.search(html).start() - 80):CYR.search(html).start() + 40]
assert re.search(r"U•+001", html) and "U9300001" not in html                                                                                     # сметката е маскирана и в отчета
assert "Wechselkurse: USD: EZB-Datei eurofxref-hist.csv (bis 29.10.2026)" in html                                                                      # откъде са курсовете — на немски (текстът на страницата е на български)
assert "https://" not in html and "http://" not in html and "<script" not in html and "<img" not in html                                                 # нищо външно, нищо изпълнимо
print("  ✓ „Aufstellung der Kapitalerträge 2025 — selbst erstellt“, име, данъчна година, дата на изготвяне (02.01.2026), съвместно подаване, брокер / сметка (U••••001); всички раздели; метод (FIFO § 20 ал. 4 изр. 7, курс на ЕЦБ § 20 ал. 4 изр. 1);")
print("    подписът „Selbst erstellte Aufstellung …“; без кирилица, без http, без <script> / <img>")

print("── 4. полетата и сумите на отчета = сумите на страницата (блокът „Какво попълваш“) ──")
d, dc = o["de"][2025], o["decl"][2025]
assert [r["field"] for r in m["summary"]["rows"]] == SUM_FIELDS == [r["field"] for r in dc["rows"]]
assert [round(r["eur"], 9) for r in m["summary"]["rows"]] == [round(r["eur"], 9) for r in dc["rows"]]
for r in m["summary"]["rows"]:
    assert dfmt(r["eur"]) in html and r["field"] in html, r["field"]                                                                                    # точният немски текст на полето + сумата в немски формат
assert [r["ref"] for r in m["summary"]["rows"]] == [f"Zeile {z}" for z in (19, 20, 22, 23, 41)] and m["summary"]["controlOk"] is True and m["checksOk"] is True and all(c["ok"] for c in m["checks"]), m["checks"]
r15, r16, r5, r8 = rate("2025-02-15"), rate("2025-02-16"), rate("2025-03-08"), rate("2025-04-05")
gA, lB = 300 / r16 - 100 / r15, 500 / r8 - 1000 / r5                                                                                                    # ръчно: AAA печалба, BBB загуба (всеки лот по курса на деня на покупката и на продажбата)
z = {x["field"]: x["eur"] for x in m["summary"]["rows"]}
assert abs(z[SUM_FIELDS[1]] - gA) < 1e-9 and abs(z[SUM_FIELDS[3]] + lB) < 1e-9, (z, gA, lB)
assert abs(m["incomes"]["dividends"]["total"] + m["incomes"]["pil"]["total"] - (100 / rate("2025-04-06") - 10 / rate("2025-05-04"))) < 1e-9
assert abs(m["incomes"]["interest"]["credits"] - 20 / rate("2025-05-03")) < 1e-9 and abs(sum(c["credited"] for c in m["incomes"]["credit"]) - dc["z41"]) < 1e-9
print("  ✓ Zeile 19 / 20 / 22 / 23 / 41 в отчета = блока на страницата (същите полета с немския текст, същите суми до 1e-9, подсказка „Zeile N — im Formular prüfen“); контролният ред и всички 10 вътрешни сверки са ✓;")
print("    ръчна сметка: AAA +", round(gA, 2), "€, BBB", round(lB, 2), "€ (по курса на деня на покупката и на продажбата) = числата в отчета; дивиденти, лихви, зачетен данък — също")

print("── 5. продажбите ред по ред (по лот): оригинална валута, курс на ЕЦБ, Anschaffungskosten, Veräußerungserlös, Gewinn / Verlust; междинни суми = страницата ──")
rows = m["sales"]["stocks"]["rows"]
assert [x["sym"] for x in rows] == ["AAA", "BBB"]
x = rows[0]
assert (x["buyDate"], x["sellDate"], x["qty"], x["buyPx"], x["buyAmt"], x["sellPx"], x["sellAmt"], x["buyCcy"], x["sellCcy"]) == ("2025-02-15", "2025-02-16", 10, 10, 100, 30, 300, "USD", "USD")
assert x["buyRate"] == r15 and x["sellRate"] == r16 and x["buyRateOn"] == "2025-02-15" and abs(x["ak"] - 100 / r15) < 1e-9 and abs(x["ve"] - 300 / r16) < 1e-9 and abs(x["gv"] - gA) < 1e-9
assert abs(m["sales"]["stocks"]["gv"] - (gA + lB)) < 1e-9 and abs(m["sales"]["stocks"]["gains"] - gA) < 1e-9 and abs(m["sales"]["stocks"]["losses"] + lB) < 1e-9
for col in ("Kaufkurs je Stück / Kaufbetrag (Währung)", "EZB-Kurs Kauf", "Anschaffungskosten EUR", "Verkaufskurs je Stück / Verkaufsbetrag (Währung)", "EZB-Kurs Verkauf", "Veräußerungserlös EUR", "Gewinn / Verlust EUR"):
    assert f"<th class=\"n\">{col}</th>" in html, col
assert dfmt(100 / r15) in html and dfmt(300 / r16) in html and f"{r15:.4f}".replace(".", ",") in html and "Zwischensumme Aktien" in html and "= 100,00\u00a0USD" in html and "= 300,00\u00a0USD" in html
print(f"  ✓ AAA: 15.02.2025 → 16.02.2025, 10 бр., 10 → 30 USD (100 → 300 USD), курс {r15:.2f} / {r16:.2f}, AK {100 / r15:.2f} €, VE {300 / r16:.2f} €, G/V {gA:.2f} €; междинната сума на акциите = Zeile 20 − Zeile 23")
# частично покупки на различни дати → по ред за лот; такса от сделката е в Kaufbetrag / Verkaufsbetrag
CSVF = H + "buy,FFF,2025-02-15,10,10,USD,CSV,main,stock,\n" + "buy,FFF,2025-02-20,10,12,USD,CSV,main,stock,\n" + "sell,FFF,2025-03-12,15,20,USD,CSV,main,stock,\n"
o = scenario([F("f.csv", CSVF)], [2025]); rows = o["report"][2025]["model"]["sales"]["stocks"]["rows"]
assert [(x["buyDate"], x["qty"]) for x in rows] == [("2025-02-15", 10), ("2025-02-20", 5)] and [x["first"] for x in rows] == [True, False]
assert abs(sum(x["ve"] for x in rows) - 300 / rate("2025-03-12")) < 1e-9 and abs(rows[1]["ak"] - 5 * 12 / rate("2025-02-20")) < 1e-9 and rows[1]["buyAmt"] == 60 and rows[1]["sellAmt"] == 100
print("  ✓ продажба на 15 бр. от два лота (10 по 10 и 10 по 12) → два реда: 10 бр. и 5 бр.; приходите се разпределят по бройки, AK на втория = 5 × 12 по курса от 20.02")

print("── 6. сплит: бройката × коефициента, цената за бройка ÷ коефициента, общата цена не се мени; „Besondere Vorgänge“ казва какво е направено и защо ──")
SPL = H + "buy,AAA,2025-02-15,10,10,USD,CSV,main,stock,\n" + "split,AAA,2025-02-20,2,,USD,,,stock,\n" + "sell,AAA,2025-03-10,20,8,USD,CSV,main,stock,\n"
o = scenario([F("sp.csv", SPL)], [2025]); mm, hh = o["report"][2025]["model"], o["report"][2025]["html"]
x = mm["sales"]["stocks"]["rows"][0]
assert (x["qty"], x["buyPx"], x["buyAmt"]) == (20, 5, 100) and abs(x["ak"] - 100 / rate("2025-02-15")) < 1e-9 and abs(x["ve"] - 160 / rate("2025-03-10")) < 1e-9, x
sp = [s for s in mm["special"] if s["title"] == "Aktiensplit"]
assert len(sp) == 1 and "Split 2 : 1" in sp[0]["text"] and "Gesamtanschaffungskosten und Kaufdaten bleiben unverändert" in sp[0]["text"] and "§ 20 Abs. 4a EStG" in sp[0]["text"] and sp[0]["date"] == "2025-02-20"
assert "Aktiensplit" in hh and not CYR.search(hh)
print("  ✓ 10 бр. по 10 USD + сплит 2:1 → 20 бр. по 5 USD (общо 100 USD, курсът — от деня на покупката); продажба 20 × 8 → 160 USD; ред „Aktiensplit · Split 2 : 1 …“ с обяснение")

print("── 7. НЕПЪЛНО: червена рамка с причините на първата страница; когато е пълно — няма рамка ──")
assert 'class="redframe"' not in html and "UNVOLLSTÄNDIG" not in html and m["complete"] is True and m["reasons"] == []
INC = BASE + rw("sell", "ZZZ", "2025-06-12", 5, 10)                                                                                                     # продажба без покупка
o = scenario([F("s.csv", INC), F("ibkr.csv", ibkr(FUT, FEES))], [2025])
mi, hi = o["report"][2025]["model"], o["report"][2025]["html"]
assert mi["complete"] is False and o["de"][2025]["complete"] is False and 'class="redframe"' in hi and "ACHTUNG: Diese Aufstellung ist UNVOLLSTÄNDIG." in hi
assert [r["type"] for r in mi["reasons"]] == ["unmatched", "skipped"], mi["reasons"]
assert "Verkauf ohne Kaufnachweis: ZZZ, 5 Stück am 12.06.2025 (CSV, Konto main)" in mi["reasons"][0]["text"] and "NICHT in den Beträgen enthalten" in mi["reasons"][0]["text"]
assert "Instrumentenart „Futures“ wird nicht berechnet" in mi["reasons"][1]["text"] and "Abschnitt „Trades“" in mi["reasons"][1]["text"]
assert hi.index('class="redframe"') < hi.index("<h2>Zusammenfassung") and hi.count("Verkauf ohne Kaufnachweis: ZZZ") == 2                                  # рамката е преди резюмето; същата причина е и в „Offene Punkte“
assert not CYR.search(hi) and mi["summary"]["rows"] and mi["checksOk"] is True
print("  ✓ продажба без покупка + фючърс (не се смята) → 2 причини в червената рамка (преди резюмето) и в „Offene Punkte“; при пълна година рамка няма; таксите (група „по закон“) не са причина")
# само информация (такси + обобщения + Forex + данък върху лихви) → пълна година, без рамка
o = scenario([F("s.csv", BASE), F("ibkr.csv", ibkr(FEES, NAV, DISC, FX, WHT, CYEP("USD,2025-08-20,USD CYEP Fee for Aug-2025,-2,")))], [2025])
assert o["report"][2025]["model"]["complete"] is True and 'class="redframe"' not in o["report"][2025]["html"] and o["de"][2025]["complete"] is True
print("  ✓ такси, обобщения, Forex, данък върху лихви и отрицателен CYEP ред (такса) → годината е ПЪЛНА, без червена рамка")

print("── 8. „Nicht berücksichtigt — nicht abzugsfähig“: по вид — брой, сума, основание; „За проверка“ САМО в калкулатора ──")
o = scenario([F("s.csv", BASE), F("ibkr.csv", ibkr(FEES, NAV, DISC, FX, WHT))], [2025]); mm, hh = o["report"][2025]["model"], o["report"][2025]["html"]
law = {x["kind"]: x for x in mm["excluded"]["law"]}
assert sorted(law) == ["fee_adr", "fee_other", "fee_quote"] and law["fee_quote"]["n"] == 3 and law["fee_adr"]["n"] == 2 and law["fee_other"]["n"] == 1 and "-2" not in law["fee_quote"]["totals"]
assert all("§ 20 Abs. 9 EStG" in x["basis"] for x in law.values()) and "Monatliche Gebühren für Börsen-Kursdaten" in hh and "ADR-Gebühren" in hh and "Sonstige Gebühren außerhalb der Trades" in hh
assert dfmt(-2.0) in hh and "−5,00 USD" in hh                                                                                                       # котировки: нето −2,00 €; ADR: −5,00 USD
assert "review" not in mm["excluded"] and "Hinweise" not in hh and "4× Zusammenfassungen und Textabschnitte" in hh
assert not re.search("Devisen|Währungsumtausch|Quellensteuer \\(ohne|einbehaltene Quellensteuer auf Zinsen|Auf Zinsen einbehaltene", hh) and "§ 23 EStG" not in hh, "Forex и данъкът върху лихви са само в калкулатора"
print("  ✓ котировки 3 × нето −2,00 €, ADR 2 × −5,00 USD (≈ в €), други такси 1 × −4,00 USD — с „§ 20 Abs. 9 EStG“; в отчета няма „Hinweise“, Forex и данък върху лихви (те са само в калкулатора); обобщенията — един ред „4× …“")

print("── 9. реални формати: анонимният IBKR отчет и фикстурата на Revolut — отчетът се генерира, цял на немски, сверен със страницата ──")
real = (ROOT / "tests" / "fixtures" / "tax" / "real_anon" / "ibkr_summary_202107_202205.csv").read_text(encoding="utf-8")
o = scenario([F("real_anon.csv", real)], [2021, 2022])
for y in (2021, 2022):
    mr, hr = o["report"][y]["model"], o["report"][y]["html"]
    assert hr.startswith('<div class="rp" lang="de">') and not CYR.search(hr), (y, CYR.search(hr))
    assert mr["complete"] == o["de"][y]["complete"] and mr["checksOk"] is True and mr["errors"] == [], (y, mr["checks"], mr["errors"])
    assert [round(r["eur"], 9) for r in mr["summary"]["rows"]] == [round(r["eur"], 9) for r in o["decl"][y]["rows"]]
    assert (not mr["complete"]) == ('class="redframe"' in hr)
fees = sum(x["year"]["n"] for gy in (2021, 2022) for x in o["groups"][gy]["law"])
assert fees > 0 and sum(1 for s in o["skipped"] if s.get("cat") == "fee") == sum(x["all"]["n"] for x in o["groups"][2022]["law"]), (fees,)                 # таксите от реалния отчет — в „по закон“
print(f"  ✓ ibkr_summary_202107_202205 (реален формат, анонимни стойности): отчети за 2021 и 2022 — немски, без кирилица, сумите = блока на страницата, червената рамка точно когато годината е НЕПЪЛНА; {fees} такси в групата „по закон“")
rev = (ROOT / "tests" / "fixtures" / "tax" / "revolut_real" / "revolut_trading_real_format.csv").read_text(encoding="utf-8")
o = scenario([F("trading.csv", rev)], [2018])
mr, hr = o["report"][2018]["model"], o["report"][2018]["html"]
assert not CYR.search(hr) and "Aktien" in hr and mr["checksOk"] is True and [x["kind"] for x in mr["excluded"]["law"]] == ["fee_other"] and "Revolut" in hr
print("  ✓ Revolut „Trading account statement“ (реален формат): сметката „акции“ → „Aktien“, описанията на български не влизат в отчета; „CUSTODY_FEE“ → изключено по закон; сумите са сверени")

# CYEP / SYEP в РЕАЛНИЯ формат (анонимни стойности): „CYEP/Broker Fees“ с положителни редове — доход, отделно от Interest; отчетът има раздел с етикет
cy = [F(n, (ROOT / "tests" / "fixtures" / "tax" / "real_anon" / n).read_text(encoding="utf-8")) for n in ("ibkr_statement_201807_201906.csv", "ibkr_statement_201907_202006_2accounts.csv")]
o = scenario(cy, [2019])
yl = [r for r in o["records"] if r["kind"] == "yield"]
assert len(yl) == 6 and all(r["amount"] > 0 for r in yl), len(yl)                                                                                       # 3 + 3 реда в двата файла
mc, hc = o["report"][2019]["model"], o["report"][2019]["html"]
assert abs(mc["incomes"]["yield"]["total"] - sum(r["amount"] / rate(r["date"]) for r in yl if r["date"].startswith("2019"))) < 1e-6 and mc["checksOk"] is True
assert "<h2>Sonstige Kapitalerträge — CYEP/SYEP 2019</h2>" in hc and "nicht in den Zinsen (Abschnitt „Interest“) enthalten" in hc and not CYR.search(hc)
assert "Erträge aus CYEP/SYEP" in mc["summary"]["rows"][0]["calc"] and all(r["kind"] != "yield" or r["amount"] > 0 for r in o["records"])
print("  ✓ реален формат (анонимни стойности): 6 положителни реда „CYEP/Broker Fees“ → „Други доходи от капитал“; в отчета — раздел „Sonstige Kapitalerträge — CYEP/SYEP“ с етикет и „+ Erträge aus CYEP/SYEP“ в Zeile 19; сумите сверени")

print("── 10. без курсове: отчетът не се чупи — липсващият курс е причина, годината е НЕПЪЛНА ──")
o = scenario([F("s.csv", BASE)], [2025], ecb=False)
mn, hn = o["report"][2025]["model"], o["report"][2025]["html"]
assert mn["complete"] is False and any(r["type"] == "rate" for r in mn["reasons"]) and "Kein EZB-Referenzkurs für USD" in hn and 'class="redframe"' in hn and not CYR.search(hn)
print("  ✓ без курсове на ЕЦБ: „Kein EZB-Referenzkurs für USD am …“ в червената рамка, отчетът е генериран (без NaN: " + str("NaN" not in hn) + ")")
assert "NaN" not in hn and "undefined" not in hn and "Infinity" not in hn
for hx in (html, hi, hh, hr, hn):
    assert "NaN" not in hx and "undefined" not in hx and "Infinity" not in hx and "[object" not in hx

print("── 11. XSS: име и текст от файла не се изпълняват в отчета ──")
p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": [{"name": "s.csv", "text": BASE}, {"name": "ecb.csv", "text": RATES}], "years": [2025], "settings": {}, "report": True, "name": "<img src=x onerror=alert(1)>", "now": "2026-01-02"}),
                   capture_output=True, text=True, timeout=120)
hx = json.loads(p.stdout)["report"]["2025"]["html"]
assert "<img" not in hx and "&lt;img src=x onerror=alert(1)&gt;" in hx
print("  ✓ „<img src=x onerror=…>“ като име → &lt;img …&gt; (текст, не елемент)")

print("── 12. страницата: бутоните, подписът под тях, оранжевият бутон при НЕПЪЛНО, печатът; без мрежа и без нови адреси ──")
page, ui, rep = [(ROOT / "docs" / n).read_text(encoding="utf-8") for n in ("tax.html", "tax_ui.js", "tax_report.js")]
assert page.index('id="declCard"') < page.index('id="reportCard"') < page.index('id="yearsCard"')                                                     # най-долу след блока „Какво попълваш“
assert "📄 Изтегли отчет за Finanzamt (PDF)" in page and "на немски · всички изчисления ред по ред · за <span id=\"repYear\"></span>" in page and 'id="repBtn"' in page
assert page.index('id="year"') < page.index('id="repTop"') < page.index('id="joint"')                                                                   # малкият бутон горе — до избора на година
assert "Изтегли отчет (НЕПЪЛЕН — виж червените редове)" in ui and "toggle('warnbtn', inc)" in ui and ".btn.warnbtn{background:#d97706" in page                 # оранжев при НЕПЪЛНО
assert "window.print()" in ui and "printing-report" in ui and "@media print" in page and "size:A4 landscape" in page and "document.title = `Aufstellung_Kapitalertraege_" in ui
assert page.index('<script src="tax_core.js">') < page.index('<script src="tax_report.js">') < page.index('<script src="tax_ui.js">')
csp = re.search(r'Content-Security-Policy" content="([^"]+)"', page).group(1)
assert csp == "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self' https://data-api.ecb.europa.eu https://api.frankfurter.dev; img-src 'self' data:; base-uri 'none'; form-action 'none'", csp   # без нови адреси
for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "window.open", "http://", "https://", "import(", "eval(", "new Function", "document.write", "localStorage.setItem(REP"):
    assert banned not in rep, banned
assert "<script" not in page.split("</head>")[1].replace('<script src="tax_core.js"></script>', "").replace('<script src="tax_report.js"></script>', "").replace('<script src="tax_ui.js"></script>', "")   # без вграден скрипт
assert "localStorage" in ui and "tax_report_name_v1" in ui and "try { localStorage.setItem(REP_NAME_KEY" in ui                                           # името — само в браузъра, в try / catch
print("  ✓ картата „Отчет за Finanzamt“ е след „Какво попълваш“ и преди „По години“, с подпис „на немски · всички изчисления ред по ред · за ГГГГ“; малък бутон до годината; оранжев „Изтегли отчет (НЕПЪЛЕН — виж червените редове)“;")
print("    печат: A4 пейзаж, window.print(), име на PDF „Aufstellung_Kapitalertraege_ГГГГ“; tax_report.js без fetch / XHR / window.open / адреси; CSP непроменен; името — само в localStorage (try / catch)")
print("── 13. ОТЧЕТЪТ Е САМО ЗА ГОДИНАТА: файлове за 2022–2026, 2026 започва от нула позиции → отчетът за 2026 няма нищо от 2022–2025 ──")
CS = lambda *rows: H + "".join(rows)
Y22 = CS(rw("buy", "AAA22", "2022-06-08", 10, 10), rw("sell", "AAA22", "2022-06-09", 10, 20), rw("dividend", "DDD22", "2022-06-20", 50, ""), rw("interest", "INT22", "2022-07-06", 5, ""))
Y23 = CS(rw("buy", "SPL23", "2023-04-12", 10, 10), "split,SPL23,2023-05-02,2,,USD,,,stock,\n", rw("sell", "SPL23", "2023-06-14", 20, 8), rw("sell", "GHOST23", "2023-07-10", 3, 5))   # продажба без покупка (2023)
Y24 = CS(rw("buy", "BBB24", "2024-03-12", 5, 10), rw("sell", "BBB24", "2024-03-13", 5, 12), "foo,ZZZ24,2024-04-11,1,1,USD,CSV,main,stock,\n")                  # непознат тип → облагаем пропуснат ред (2024)
Y25 = CS(rw("buy", "CCC25", "2025-05-13", 4, 10), rw("sell", "CCC25", "2025-06-03", 4, 9), rw("dividend", "EEE25", "2025-06-10", 30, "", 4.5))
Y26 = CS(rw("buy", "NEW26", "2026-02-16", 10, 10), rw("sell", "NEW26", "2026-02-24", 10, 11), rw("dividend", "DDD26", "2026-03-10", 20, "", 3), rw("interest", "INT26", "2026-03-12", 4, ""))
HEADY = lambda per: ["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", f'Statement,Data,Period,"{per}"', "Account Information,Header,Field Name,Field Value", "Account Information,Data,Account,U9300001", "Account Information,Data,Base Currency,EUR"]
FEEH = "Fees,Header,Subtitle,Currency,Account,Date,Description,Amount"
IB23 = "\n".join(HEADY("February 13, 2023 - December 21, 2023") + [FEEH, "Fees,Data,Other Fees,EUR,U9300001,2023-06-13,v1234567:NASDAQ Level I for Jun 2023,-1.5", "Change in NAV,Data,Starting Value,500", "Change in NAV,Data,Ending Value,600"]) + "\n"
IB26 = "\n".join(HEADY("January 9, 2026 - November 24, 2026") + [FEEH, "Fees,Data,Other Fees,EUR,U9300001,2026-03-13,v1234567:NASDAQ Level I for Mar 2026,-2.5", "Fees,Data,Other Fees,USD,U9300001,2026-04-14,ZZZ(US0000000001) ADR Fee USD 0.02 per Share,-1",
                                    "Change in NAV,Data,Starting Value,700", "Change in NAV,Data,Ending Value,800", "Change in NAV,Data,Other Fees,-3.5"] + DISC) + "\n"
YEARS = [2022, 2023, 2024, 2025, 2026]
o = scenario([F("y2022.csv", Y22), F("y2023.csv", Y23), F("ibkr_2023.csv", IB23), F("y2024.csv", Y24), F("y2025.csv", Y25), F("y2026.csv", Y26), F("ibkr_2026.csv", IB26)], YEARS)
m6, h6 = o["report"][2026]["model"], o["report"][2026]["html"]
assert m6["complete"] is True and m6["reasons"] == [] and o["de"][2026]["complete"] is True and 'class="redframe"' not in h6                       # 2026 е чиста; проблемите на 2023 и 2024 не се носят в нея
assert not re.search(r"\b\d{2}\.\d{2}\.(2022|2023|2024|2025)\b", h6), re.search(r"\b\d{2}\.\d{2}\.(2022|2023|2024|2025)\b", h6).group(0)         # никоя дата от 2022–2025
for gone in ("AAA22", "DDD22", "INT22", "SPL23", "GHOST23", "BBB24", "ZZZ24", "CCC25", "EEE25", "y2022", "y2023", "y2024", "y2025", "ibkr_2023", "Aktiensplit", "Verkauf ohne Kaufnachweis", "Nicht ausgewertete Zeile"):
    assert gone not in h6, gone
for here in ("NEW26", "DDD26", "y2026.csv", "ibkr_2026.csv"):
    assert here in h6, here
assert sorted(s["name"] for s in m6["sources"]) == ["ibkr_2026.csv", "y2026.csv"] and [x["sym"] for x in m6["sales"]["stocks"]["rows"]] == ["NEW26"] and m6["special"] == []          # Quellen: само файловете на 2026
assert [b["broker"] for b in m6["brokers"]] == ["CSV", "IBKR"] and all(b["files"] == 1 for b in m6["brokers"])
inf = {x["kind"]: x for x in m6["excluded"]["info"]}
law = {x["kind"]: x for x in m6["excluded"]["law"]}
assert inf["summary"]["n"] == 4 and law["fee_quote"]["n"] == 1 and law["fee_adr"]["n"] == 1 and "-2,50" in law["fee_quote"]["totals"].replace("−", "-").replace(" ", " ").replace(" EUR", ""), (inf, law)   # обобщенията и таксите — само от 2026 (не и тези на ibkr_2023.csv)
r10, r11, r310, r312 = rate("2026-02-16"), rate("2026-02-24"), rate("2026-03-10"), rate("2026-03-12")
z = {x["field"]: x["eur"] for x in m6["summary"]["rows"]}
assert abs(z[SUM_FIELDS[0]] - ((110 / r11 - 100 / r10) + 20 / r310 + 4 / r312)) < 1e-9 and abs(z[SUM_FIELDS[4]] - 3 / r310) < 1e-9 and m6["checksOk"] is True       # сумите са само на 2026 (ръчна сметка)
# същото за другите години — всяка има своето; проблемите на годината са в отчета ѝ и само там
m3, h3 = o["report"][2023]["model"], o["report"][2023]["html"]
assert m3["complete"] is False and any("Verkauf ohne Kaufnachweis: GHOST23" in r["text"] for r in m3["reasons"]) and "GHOST23" in h3 and "AAA22" not in h3 and "SPL23" in h3 and "Aktiensplit" in h3 and "y2022" not in h3
m4, h4 = o["report"][2024]["model"], o["report"][2024]["html"]
assert m4["complete"] is False and any("ZZZ24" in r["text"] for r in m4["reasons"]) and "GHOST23" not in h4 and "ibkr_2023" not in h4 and "y2024.csv" in h4
m2, h2 = o["report"][2022]["model"], o["report"][2022]["html"]
assert m2["complete"] is True and "GHOST23" not in h2 and "y2023" not in h2 and "AAA22" in h2 and not CYR.search(h2 + h3 + h4 + h6)
print("  ✓ файлове за 2022–2026 (2026 започва от нула позиции): отчетът за 2026 няма нито една дата от 2022–2025, нито тикър, файл, сплит, непокрита продажба и пропуснат ред от тях; 2026 е пълна, без червена рамка;")
print("    Quellen = само y2026.csv и ibkr_2026.csv; брокери — само от тях; такси и „обобщения“ — само от 2026 (1 + 1 такси, 4 реда, не и от ibkr_2023.csv); Zeile 19 / 41 = ръчна сметка само за 2026")
print("    същите файлове: отчетът за 2023 има GHOST23, сплита и ibkr_2023 (и нищо от 2022), за 2024 — пропуснатия ред; всяка година носи само своите проблеми")
print("── 14. лот, продаден през 2026, има връзки назад: сплит от 2025, покупка от 2024, прехвърляне от друг брокер — влизат (с файловете им); несвързани събития — не ──")
UA = CS(rw("buy", "UNREL22", "2022-06-08", 10, 10), rw("sell", "UNREL22", "2022-06-09", 10, 12))
UB = CS(rw("buy", "UNREL", "2023-04-18", 10, 10), "split,UNREL,2023-05-03,2,,USD,,,stock,\n", rw("sell", "UNREL", "2023-06-15", 20, 6))
C24 = CS(rw("buy", "CARRY", "2024-03-14", 10, 10))
C25 = CS("split,CARRY,2025-04-15,2,,USD,,,stock,\n", rw("buy", "HELD", "2025-05-15", 5, 10))
OTH = H + "buy,XFS,2025-06-10,10,10,USD,OTHER,acc,stock,\n"
TRFH = "Transfers,Header,Asset Category,Currency,Symbol,Date,Type,Direction,Xfer Company,Xfer Account,Qty,Xfer Price,Market Value,Realized P/L,Cash Amount,Code"
TRH = "Trades,Header,DataDiscriminator,Asset Category,Currency,Account,Symbol,Date/Time,Quantity,T. Price,Proceeds,Comm/Fee,Code"
IBX = "\n".join(HEADY("January 9, 2026 - November 24, 2026") + [TRFH, "Transfers,Data,Stocks,USD,XFS,2026-03-16,ACATS,In,--,--,10,--,0,0,0,", "Transfers,Data,Stocks,USD,UNSOLD,2026-03-17,ACATS,In,--,--,5,--,0,0,0,",
                                     TRH, 'Trades,Data,Order,Stocks,USD,U9300001,XFS,"2026-04-15, 10:00:00",-10,12,120,-1,']) + "\n"
C26 = CS(rw("sell", "CARRY", "2026-03-12", 20, 8), "split,HELD,2026-02-20,2,,USD,,,stock,\n")
o = scenario([F("uA_2022.csv", UA), F("uB_2023.csv", UB), F("c2024.csv", C24), F("c2025.csv", C25), F("other_2025.csv", OTH), F("ib26.csv", IBX), F("c2026.csv", C26)], [2026])
mx, hx = o["report"][2026]["model"], o["report"][2026]["html"]
assert mx["complete"] is True and mx["reasons"] == [], mx["reasons"]
rows = mx["sales"]["stocks"]["rows"]
assert sorted(r["sym"] for r in rows) == ["CARRY", "XFS"], [r["sym"] for r in rows]
cr = next(r for r in rows if r["sym"] == "CARRY")
assert (cr["buyDate"], cr["qty"], cr["buyPx"], cr["buyAmt"]) == ("2024-03-14", 20, 5, 100)                                                                # покупка от 2024, сплитът от 2025 е приложен
xr = next(r for r in rows if r["sym"] == "XFS")
assert xr["buyDate"] == "2025-06-10" and xr["qty"] == 10, xr                                                                                                  # покупката е при другия брокер (2025) — свързана с прехвърлянето
titles = sorted((s["sym"], s["title"], s["date"]) for s in mx["special"])
assert titles == [("CARRY", "Aktiensplit", "2025-04-15"), ("XFS", "Einlieferung von einem anderen Broker (Eingang)", "2026-03-16")], titles                  # сплитът (2025) и прехвърлянето (2026) на ПРОДАДЕНИ лотове; без UNREL (2023), HELD (2026, непродаден), UNSOLD (прехвърляне, непродаден)
for gone in ("UNREL", "HELD", "UNSOLD", "uA_2022", "uB_2023"):
    assert gone not in hx, gone
assert sorted(s["name"] for s in mx["sources"]) == ["c2024.csv", "c2025.csv", "c2026.csv", "ib26.csv", "other_2025.csv"], [s["name"] for s in mx["sources"]]      # вкл. по-стари файлове: c2024 (покупката на CARRY), c2025 (сплитът), other_2025 (покупката на XFS)
assert "15.04.2025" in hx and "14.03.2024" in hx and "10.06.2025" in hx and "Aktiensplit" in hx and "Einlieferung von einem anderen Broker" in hx and "verkauft wurden (auch aus früheren Jahren)" in hx and not CYR.search(hx)
print("  ✓ продажба през 2026 на лот от 2024 със сплит от 2025: в отчета са покупката (14.03.2024), сплитът (15.04.2025) и файловете c2024 / c2025; продажба на акция, прехвърлена от друг брокер: покупката при него (10.06.2025) и файлът other_2025;")
print("    няма сплита на UNREL (2023, продаден през 2023), сплита на HELD през 2026 (непродаден), прехвърлянето на UNSOLD (непродаден) и файловете uA_2022 / uB_2023")

print("\nOK test_tax_report")
