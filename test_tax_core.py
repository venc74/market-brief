"""
04.11.2026 (tax-fixes): данъчният калкулатор docs/tax.html — сметките в docs/tax_core.js, през `node` (tests/tax_driver.js). Очакваните числа са сметнати НА РЪКА тук (Python), не взети от JS.
ВСИЧКИ входове са СИНТЕТИЧНИ — tests/fixtures/tax/ (бележката в README.md там): измислени сметки, тикъри, суми и курсове (ЕЦБ форматът, постоянен курс за година).
Без node — изрично SKIP с причината и код 0 (в CI node има).
Пускане: python test_tax_core.py
"""
import sys, json, shutil, pathlib, subprocess
ROOT = pathlib.Path(__file__).parent
FX = ROOT / "tests" / "fixtures" / "tax"
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node — tax_core.js не е изпълнен (в CI node има)")
    sys.exit(0)


def run(step, files, settings=None):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), step, json.dumps(settings or {})] + [str(FX / f) for f in files],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


IBKR = ["U1111111_2020.csv", "U1111111_2021.csv", "U1111111_2022.csv", "U1111111_2023.csv", "U1111111_2023 (1).csv", "U1111111_Q4_2023.csv", "U1111111_2026.csv"]
ALL = IBKR + ["broker2_export.csv", "crypto_me.csv", "crypto_spouse.csv", "loss_div.csv", "ecb_rates_synthetic.csv"]

print("── 1. разпознаване по съдържание (имената не значат нищо), дедупликация, „не е сметнато“ ──")
ing = run("ingest", list(reversed(ALL)))                                   # произволен ред
fmt = {f["name"]: (f["format"], f["account"]) for f in ing["files"]}
assert fmt["U1111111_2023 (1).csv"] == ("ibkr", "U1111111") and fmt["broker2_export.csv"] == ("standard", "B2") and fmt["ecb_rates_synthetic.csv"][0] == "ecb_rates", fmt
assert ing["rateCurrencies"] == ["USD", "JPY"] or set(ing["rateCurrencies"]) == {"USD", "JPY"}
recs = ing["records"]
trades = [r for r in recs if r["kind"] == "trade"]
# сделки: ACME ×4 (IBKR) + SPLT ×2 + XWLD ×2 + опция ×2 + Broker2 ×3 + крипто 5 + 2 + loss_div 4 + OLDCO ×1 (13.11: сливане с пари = продажба) — всяка ВЕДНЪЖ въпреки 2023 ×2 и Q4 2023
key = lambda r: (r["account"], r["sym"], r["date"], r["qty"])
assert len(trades) == len({key(r) for r in trades}) == 4 + 2 + 2 + 2 + 3 + 5 + 2 + 4 + 1, (len(trades), sorted({key(r) for r in trades}))
dup = {f["name"]: f["duplicates"] for f in ing["files"]}
assert sum(dup.values()) == 13 + 1 + 1, dup                                     # целият 2023 отчет повторен (13 записа: 6 сделки, 2 дивидента, 2 удържани, 3 лихви) + XWLD продажбата от Q4
assert [r["date"] for r in recs] == sorted(r["date"] for r in recs)          # подредба по дата
acme = [r for r in trades if r["sym"] == "ACME" and r["account"] == "U1111111"]
assert [(r["date"], r["qty"], r["price"], r["fee"], r["currency"]) for r in acme] == \
    [("2020-03-02", 10, 100, 1, "USD"), ("2021-05-03", 10, 150, 1, "USD"), ("2023-06-01", -15, 200, 2, "USD"), ("2026-02-02", -5, 120, 1, "USD")]
split = [r for r in recs if r["kind"] == "split"]
assert [(r["sym"], r["date"], r["ratio"]) for r in split] == [("SPLT", "2022-06-01", 4)]
assert [r["fundHint"] for r in trades if r["sym"] == "XWLD"] == [True, True]     # типът ETF от „Financial Instrument Information“
print(f"  ✓ {len(ing['files'])} файла по съдържание; {len(trades)} сделки — всяка веднъж (14 дубликата махнати); подредба по дата; сплитът и ETF типът — разпознати")

print("── 2. дивиденти, удържан данък, лихви от IBKR ──")
div = [(r["date"], r["amount"]) for r in recs if r["kind"] == "dividend" and r["sym"] == "ACME"]
wh = [(r["date"], r["amount"]) for r in recs if r["kind"] == "withholding"]
intr = [(r["date"], r["amount"], r["currency"]) for r in recs if r["kind"] == "interest"]
assert div == [("2023-03-15", 50), ("2023-04-20", -10)], div                 # сторното (−10) остава — до 04.11 се пропускаше
assert wh == [("2023-03-15", -7.5), ("2023-04-20", 1.5)], wh                  # върнатият данък (+1.5) е плюс, не минус; описанието без интервал („ACME(US…)“) — разпознато
assert intr == [("2023-07-05", 12.34, "EUR"), ("2023-08-03", 5, "USD"), ("2023-09-05", -3, "EUR")], intr
print("  ✓ сторното −10 и върнатият данък +1.5 — със знака си; „ACME(US…)“ без интервал — разпознато; лихвите (кредитна и дебитна)")

print("── 3. „не е сметнато“ — нищо не се пропуска тихо ──")
sk = ing["skipped"]
why = {(s["section"], s["what"]) for s in sk}
assert ("Trades", "EUR.USD") in why                                         # Forex
assert ("Fees", "NYSE Market Data") in why
assert not any(s["section"] == "Corporate Actions" for s in sk)            # 13.11.2026: сливането с пари (OLDCO) вече е продажба — не е в „не е сметнато“
assert [(r["qty"], r["price"]) for r in recs if r["kind"] == "trade" and r["sym"] == "OLDCO"] == [(-10, 50)], [r for r in recs if r.get("sym") == "OLDCO"]
assert any(s["section"] == "Withholding Tax" and "Interest" in s["what"] for s in sk)  # данък върху лихва — без тикър
assert not any(s["section"] in ("Mark-to-Market Performance Summary", "Cash Report") for s in sk)   # обобщенията не са сделки
assert sum(1 for s in sk if (s["section"], s["what"]) == ("Trades", "EUR.USD")) == 1                # и в „не е сметнато“ — веднъж (не за всеки дубликат на файла)
print(f"  ✓ {len(sk)} реда в „не е сметнато“: Forex, такси извън сделките, данък върху лихва; обобщенията — не (сливането с пари от 13.11 е продажба)")
print("── 4. курсове: ЕЦБ (JSON и файл), frankfurter в същата посока, уикенд → предишният ден ──")
assert run("ecbjson", ["ecb_usd_synthetic.json"]) == [["2024-06-13", 1.0712], ["2024-06-14", 1.0815]]
assert run("frankfurter", ["frankfurter_usd_synthetic.json"]) == [["2024-06-13", 1.0712], ["2024-06-14", 1.0815]]     # USD за 1 EUR — до 04.11 беше обърнато
lk = run("lookup", ["ecb_rates_synthetic.csv"], {"dates": ["2023-06-01", "2023-06-03", "2023-06-04", "2023-06-05", "2019-11-01"]})
assert lk == {"2023-06-01": 1.08, "2023-06-03": 1.08, "2023-06-04": 1.08, "2023-06-05": 1.08, "2019-11-01": None}, lk     # събота/неделя → петък; преди таблицата → None
print("  ✓ ЕЦБ JSON и frankfurter — една и съща посока (USD за 1 EUR); уикенд → петък; без курс → None (предупреждение, не NaN)")

print("── 5. FIFO: частична продажба през години, два брокера с един актив, сплит, комисионни, продажба без покупка, опции ──")
fifo = run("fifo", list(reversed(ALL)))
R = lambda acct, sym, date: [x for x in fifo["realized"] if x["account"] == acct and x["sym"] == sym and x["date"] == date]
close = lambda a, b: abs(a - b) < 1e-6
# ACME @ IBKR: купени 10 @ 100 USD + 1 (02.03.2020, курс 1.10) и 10 @ 150 + 1 (03.05.2021, курс 1.20); продадени 15 @ 200 − 2 (01.06.2023, 1.08) и 5 @ 120 − 1 (02.02.2026, 1.15)
lot1, lot2 = 1001 / 1.10, 1501 / 1.20
s23 = R("U1111111", "ACME", "2023-06-01")[0]
assert close(s23["proceedsEUR"], 2998 / 1.08) and close(s23["costEUR"], lot1 + lot2 / 2) and close(s23["gainEUR"], 2998 / 1.08 - lot1 - lot2 / 2), s23
s26 = R("U1111111", "ACME", "2026-02-02")[0]
assert close(s26["costEUR"], lot2 / 2) and close(s26["gainEUR"], 599 / 1.15 - lot2 / 2), s26                   # остатъкът от лота от 2021 — не лотът от 2020
# ACME @ Broker2 — отделно FIFO: 5 @ 160 (05.01.2022, 1.10) → 5 @ 210 (01.06.2023, 1.08)
b2 = R("B2", "ACME", "2023-06-01")[0]
assert close(b2["gainEUR"], 1050 / 1.08 - 800 / 1.10), b2
# SPLT: 10 @ 400 EUR, сплит 4:1 (01.06.2022) → 40 акции за 4 000; продадени 20 @ 110 → 2 200 − 2 000
sp = R("U1111111", "SPLT", "2023-03-01")[0]
assert close(sp["costEUR"], 2000) and close(sp["gainEUR"], 200), sp
# XWLD (ETF): 10 @ 100 + 1 → 10 @ 130 − 1 → 1 299 − 1 001 = 298 (комисионните — и двете)
xw = R("U1111111", "XWLD", "2023-11-01")[0]
assert close(xw["gainEUR"], 298) and xw["fundHint"] is True, xw
# опция (Stillhalter): продадена 1 @ 250 USD − 1.05 (02.05.2023, 1.08), изтекла (16.06.2023) → премията
op = [x for x in fifo["realized"] if x["assetClass"] == "option"]
# 05.11.2026: по подразбиране два записа — премията на 02.05 (доход в годината на получаване) и изтичането на 16.06 (обратно изкупуване за 0)
assert [(x["date"], bool(x.get("premium")), bool(x.get("buyback"))) for x in op] == [("2023-05-02", True, False), ("2023-06-16", False, True)], op
assert close(op[0]["gainEUR"], 248.95 / 1.08) and close(op[1]["gainEUR"], 0), op
# продажба без покупка — предупреждение, без резултат
# 13.11.2026: + OLDCO — сливането с пари (10 бр. за 500) е продажба, а в синтетичните отчети няма покупка на OLDCO
assert sorted((u["sym"], u["account"], u["qty"]) for u in fifo["unmatched"]) == [("GHOST", "B2", 3), ("OLDCO", "U1111111", 10)], fifo["unmatched"]
assert not R("B2", "GHOST", "2023-02-01")
# крипто: годишнината (01.03.2024 за покупка 01.03.2023) е още в срока; 04.03.2024 — освободено
c1 = R("crypto-me", "BTC", "2024-03-01")[0]; c2 = R("crypto-me", "BTC", "2024-03-04")[0]
assert close(c1["taxableGainEUR"], 2000) and close(c1["exemptGainEUR"], 0) and close(c2["exemptGainEUR"], 2050) and close(c2["taxableGainEUR"], 0), (c1, c2)
assert not [x for x in fifo["realized"] if x["gainEUR"] is None] and not fifo["missingRates"]
print("  ✓ ACME 2023: +%.2f € (лот 2020 + половината от 2021); 2026: %.2f € (остатъкът от 2021); Broker2 — отделно; сплит; комисионни; опция; GHOST — предупреждение; крипто — годишнината" % (s23["gainEUR"], s26["gainEUR"]))

print("── 6. доходи в EUR; липсващ курс → предупреждение ──")
inc = [(x["kind"], x["date"], round(x["eur"], 6)) for x in fifo["incomes"] if x["account"] == "U1111111"]
assert inc == [("dividend", "2023-03-15", round(50 / 1.08, 6)), ("withholding", "2023-03-15", round(-7.5 / 1.08, 6)), ("dividend", "2023-04-20", round(-10 / 1.08, 6)),
               ("withholding", "2023-04-20", round(1.5 / 1.08, 6)), ("interest", "2023-07-05", 12.34), ("interest", "2023-08-03", round(5 / 1.08, 6)), ("interest", "2023-09-05", -3.0)], inc
chf = run("fifo", ["chf_no_rate.csv", "ecb_rates_synthetic.csv"])
assert {(m["kind"], m["sym"], m["currency"]) for m in chf["missingRates"]} == {("trade", "NESX", "CHF"), ("dividend", "NESX", "CHF"), ("withholding", "NESX", "CHF")}, chf["missingRates"]
assert all(x["gainEUR"] is None for x in chf["realized"])
print("  ✓ дивидент, сторно, удържан, върнат, лихви — в EUR по датата; CHF без курс → в „липсващ курс“, резултатът е null (не NaN, не 0)")

print("── 7. параметри по години ──")
P = run("params", ["ecb_rates_synthetic.csv"], {"years": [2020, 2022, 2023, 2024, 2026, 2031]})
assert [(p["pauschbetrag"], p["freigrenze23"], p["extrapolated"]) for p in P] == [(801, 600, False), (801, 600, False), (1000, 600, False), (1000, 1000, False), (1000, 1000, False), (1000, 1000, True)], P
assert P[0]["teilfreistellung"]["equity"] == 0.3 and P[0]["abgeltung"] == 0.25 and P[0]["soli"] == 0.055
print("  ✓ Pauschbetrag 801 → 1 000 (2023); Freigrenze §23 600 → 1 000 (2024); 2031 — последните известни + бележка")

print("── 8. Германия 2023: всички отчети, сам — ръчна сметка ──")
de = run("de", list(reversed(ALL)), {"year": 2023})
acme_ib = 2998 / 1.08 - lot1 - lot2 / 2                 # 1 240.51
acme_b2 = 1050 / 1.08 - 800 / 1.10                      # 244.95
shares = acme_ib + acme_b2 + 200                        # + SPLT
fund = 298 * 0.7                                        # XWLD — ETF (подсказката от IBKR → акционерен фонд, 30% освободени)
option = 248.95 / 1.08
dividends = (50 - 10) / 1.08                            # със сторното
interest = 12.34 + 5 / 1.08                             # дебитната лихва (−3) не се приспада
total = shares + fund + option + dividends + interest
assert close(de["shareGains"], shares) and close(de["shareLosses"], 0) and close(de["otherPos"], fund + option + dividends + interest), de
assert close(de["total"], total) and close(de["headline"], total), (de["total"], total)
cred = min(6 / 1.08, 0.15 * dividends)                  # удържани 7.5 − 1.5 върнати = 6 USD; таван 15% от 37.04 €
assert close(de["withheld"], 6 / 1.08) and close(de["creditable"], cred)
e = total - 1000
assert close(de["estimate"]["abgeltung"], (e - 4 * cred) / 4) and close(de["estimate"]["soli"], (e - 4 * cred) / 4 * 0.055)
assert sorted(u["sym"] for u in de["unmatched"]) == ["GHOST", "OLDCO"] and not de["complete"]      # 13.11: OLDCO — сливане с пари без покупка в синтетичните отчети
assert any("USD" in n["text"] for n in de["notes"]) and any("Дебитна лихва" in n["text"] for n in de["notes"])
print(f"  ✓ числото най-горе {de['headline']:.2f} € = акции {shares:.2f} + ETF {fund:.2f} (след 30%) + опция {option:.2f} + дивиденти {dividends:.2f} + лихви {interest:.2f}; GHOST и OLDCO (сливане с пари) без покупка — непълно")

print("── 9. съвместно и църковен данък (Бавария 8%) ──")
dj = run("de", list(reversed(ALL)), {"year": 2023, "joint": True})
assert close(dj["estimate"]["pauschbetrag"], 2000) and close(dj["estimate"]["abgeltung"], (total - 2000 - 4 * cred) / 4)
dk = run("de", list(reversed(ALL)), {"year": 2023, "kirche": "BY"})
tk = (e - 4 * cred) / 4.08
assert close(dk["estimate"]["abgeltung"], tk) and close(dk["estimate"]["kirche"], tk * 0.08) and close(dk["estimate"]["soli"], tk * 0.055), dk["estimate"]
d9 = run("de", list(reversed(ALL)), {"year": 2023, "kirche": "other"})
assert close(d9["estimate"]["abgeltung"], (e - 4 * cred) / 4.09)
print(f"  ✓ съвместно — Pauschbetrag 2 000; Бавария: (e − 4q) / 4.08 = {tk:.2f} €, KiSt 8% = {tk*0.08:.2f} €; другаде — / 4.09")

print("── 10. загуба от акции + дивидент + ETF (2025); пренесени загуби ──")
d25 = run("de", ["loss_div.csv"], {"year": 2025})
loss = 3995 - 5005                                       # LOSSCO: 100 @ 50 + 5 → 100 @ 40 − 5
assert close(d25["shareLosses"], -loss) and close(d25["shareCarry"], 1010) and close(d25["total"], 3000 + 500 * 0.7) and close(d25["headline"], 3350), d25
c25 = run("de", ["loss_div.csv"], {"year": 2025, "carriedShareLoss": 200, "carriedOtherLoss": 300})
assert close(c25["shareCarry"], 1210) and close(c25["total"], 3050), c25
m25 = run("de", ["loss_div.csv"], {"year": 2025, "fundTypes": {"EQETF": "mixed"}})
assert close(m25["total"], 3000 + 500 * 0.85)
print("  ✓ загубата от акции (−1 010) НЕ намалява дивидента и ETF-а → пренася се; пренесени 200 (акции) / 300 (други); смесен фонд — 15%")

print("── 11. крипто §23 (2024): годишнината, Freigrenze 1 000 на човек ──")
cs = run("de", ["crypto_me.csv", "crypto_spouse.csv"], {"year": 2024})
assert len(cs["crypto"]) == 1 and close(cs["crypto"][0]["taxable"], 2000 + 600 + 800) and close(cs["crypto"][0]["exempt"], 2050) and close(cs["crypto"][0]["result"], 3400), cs["crypto"]
cj = run("de", ["crypto_me.csv", "crypto_spouse.csv"], {"year": 2024, "joint": True, "persons": {"Revolut|crypto-spouse": "B"}})
a, b = cj["crypto"]
assert close(a["result"], 2600) and close(b["taxable"], 800) and b["underFreigrenze"] and close(b["result"], 0), cj["crypto"]
assert close(cj["total"], 0) and close(cj["headline"], 0)
print("  ✓ сам: 3 400 € облагаеми (2 050 € — над година); съвместно: аз 2 600 €, съпругата 800 € < 1 000 € Freigrenze → 0")

print("── 12. Revolut (СИНТЕТИЧНИ файлове по публичния формат — не са проверени с реален отчет) ──")
rv = run("fifo", ["revolut_trading_synthetic.csv", "revolut_crypto_synthetic.csv", "ecb_rates_synthetic.csv"])
st = [x for x in rv["realized"] if x["sym"] == "ACME"][0]
assert close(st["costEUR"], 401 / 1.08) and close(st["proceedsEUR"], 519 / 1.08) and close(st["gainEUR"], 118 / 1.08), st     # комисионната = общо − бр. × цена
assert [round(x["eur"], 6) for x in rv["incomes"]] == [round(2 / 1.08, 6)]
sol = sorted([x for x in rv["realized"] if x["sym"] == "SOL"], key=lambda x: x["date"])
assert close(sol[0]["taxableGainEUR"], 119 - 80.8) and close(sol[1]["exemptGainEUR"], 209 - 121.2), sol                     # годишнината 01.02.2025 — още в срока
ing = run("ingest", ["revolut_trading_synthetic.csv", "revolut_crypto_synthetic.csv"])
assert {f["format"] for f in ing["files"]} == {"revolut_stocks", "revolut_crypto"}
why = " | ".join(s["reason"] for s in ing["skipped"])
assert "сплит в Revolut" in why and "такса извън сделките" in why and "стейкинг" in why, why
d25 = run("de", ["revolut_crypto_synthetic.csv"], {"year": 2025})
assert d25["crypto"][0]["underFreigrenze"] and close(d25["crypto"][0]["result"], 0) and close(d25["crypto"][0]["exempt"], 87.8)
print("  ✓ акции: комисионната от „Total Amount“; дивидент; такса, сплит — в „не е сметнато“; крипто: годишнината, стейкинг — в „не е сметнато“; 2025: 38.20 € < Freigrenze → 0")
print("\n✅ test_tax_core: всичко мина")
