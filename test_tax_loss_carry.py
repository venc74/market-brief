"""
14.11.2026 (tax-real-fix): загубите НЕ се пренасят автоматично — всяка година се смята самостоятелно; пренесеното е само ръчно въведеното „verbleibender Verlustvortrag“ (от решение на Finanzamt);
годината със загуба дава ясен ред „Загуба от акции X / други загуби Y — декларирай я в Anlage KAP за ГГГГ, за да се пренесе“ (никога 0); таблица по години без пренасяне.
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7): ВСИЧКО Е СИНТЕТИЧНО — стандартен CSV на калкулатора, построен тук (тикъри AAA…, суми от въображението, дати 2014–2017, курс 1,0 за USD).
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP. Пускане: python test_tax_loss_carry.py
"""
import json, shutil, subprocess, sys, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
RATES = "Date,USD,JPY,GBP\n" + "".join(f"{(datetime.date(2013, 1, 1) + datetime.timedelta(days=i)).isoformat()},1.0,1.0,1.0\n" for i in range(0, 365 * 5 + 5))
H = "type,ticker,date,quantity,price,currency,broker,account,asset_type\n"


def row(t, tk, d, q, p):
    return f"{t},{tk},{d},{q},{p},USD,CSV,main,stock\n"


def scenario(text, years, **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": [{"name": "s.csv", "text": text}, {"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": settings}),
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    o["de"] = {int(y): v for y, v in o["de"].items()}
    return o


r2 = lambda x: round(x, 2)
nb = lambda x: x.replace("\u202f", " ")                                                                                              # TC.fmt слага тясно непрекъсваемо разстояние пред „€“
# 2015: загуба от акции 500 (купени 10 × 100, продадени 10 × 50) и дивидент 20; 2016: печалба от акции 200 (10 × 10 → 10 × 30) и дивидент 30; 2017: само загуба от акции 100 и нищо друго;
# 2014: други загуби — отрицателен дивидент −50 (сторно) и нищо друго
TXT = H + row("buy", "AAA", "2015-02-01", 10, 100) + row("sell", "AAA", "2015-06-03", 10, 50) + row("dividend", "AAA", "2015-07-01", "", "").replace(",,,", ",20,,") \
    + row("buy", "BBB", "2016-02-03", 10, 10) + row("sell", "BBB", "2016-06-01", 10, 30) \
    + row("buy", "CCC", "2017-02-01", 10, 20) + row("sell", "CCC", "2017-06-01", 10, 10)
TXT = TXT.replace("dividend,AAA,2015-07-01,20,,USD", "dividend,AAA,2015-07-01,20,,USD") + "dividend,DDD,2016-08-03,30,,USD,CSV,main,stock\n" + "dividend,EEE,2014-05-02,-50,,USD,CSV,main,stock\n"
o = scenario(TXT, [2014, 2015, 2016, 2017])
de = o["de"]
print("── 1. всяка година самостоятелно: НЯМА автоматично пренасяне ──")
assert r2(de[2015]["shareLosses"]) == 500 and r2(de[2015]["shareGains"]) == 0 and r2(de[2015]["otherPos"]) == 20
assert r2(de[2016]["shareGains"]) == 200 and r2(de[2016]["shareLosses"]) == 0 and r2(de[2016]["carriedShareLoss"]) == 0 and r2(de[2016]["shareNet"]) == 200            # 2015 НЕ намалява 2016
assert r2(de[2016]["headline"]) == 230                                                                                             # 200 печалба от акции + 30 дивидент — без 500 от 2015
print("  ✓ 2015 със загуба от акции 500 → 2016 е 200 (акции) + 30 (дивидент) = 230, без никакво пренасяне")
yt = {r["year"]: r for r in o["yearsTable"]}
assert sorted(yt) == [2014, 2015, 2016, 2017]
assert (r2(yt[2015]["shareGains"]), r2(yt[2015]["shareLosses"]), r2(yt[2015]["otherPos"]), r2(yt[2015]["headline"])) == (0, 500, 20, 20)
assert (r2(yt[2016]["shareNet"]), r2(yt[2016]["otherPos"]), r2(yt[2016]["headline"])) == (200, 30, 230) and yt[2016]["lossLine"] == ""
assert (r2(yt[2017]["shareLosses"]), r2(yt[2017]["headline"])) == (100, -100)                                                          # единствена загуба → число −100, не 0
print("  ✓ таблицата по години (TC.yearsTable): 2014 / 2015 / 2016 / 2017 — печалби и загуби от акции, други доходи, число без пренасяне")

print("── 2. година със загуба: ясен ред, никога 0 ──")
assert nb(de[2015]["lossLine"]) == "Загуба от акции 500.00 € / други загуби 0.00 € — декларирай я в Anlage KAP за 2015, за да се пренесе (Finanzamt я установява с Verlustfeststellungsbescheid; иначе се губи)."
assert nb(de[2017]["lossLine"]).startswith("Загуба от акции 100.00 € / други загуби 0.00 € — декларирай я в Anlage KAP за 2017") and r2(de[2017]["headline"]) == -100 and de[2017]["headline"] != 0
assert nb(de[2014]["lossLine"]).startswith("Загуба от акции 0.00 € / други загуби 50.00 € — декларирай я в Anlage KAP за 2014") and r2(de[2014]["otherLossOwn"]) == 50 and r2(de[2014]["headline"]) == -50
assert de[2016]["lossLine"] == ""
print("  ✓ 2015: «Загуба от акции 500,00 € / други загуби 0,00 € — декларирай я в Anlage KAP за 2015, за да се пренесе»; 2017: същото със 100 и число −100 (не 0); 2014: други загуби 50; 2016 (печалба) — без ред")

print("── 3. ръчно въведен Verlustvortrag (от решение на Finanzamt) — само за годината, за която е въведен ──")
o2 = scenario(TXT, [2016, 2017], carriedShareLoss=150)
assert r2(o2["de"][2016]["shareNet"]) == 50 and r2(o2["de"][2016]["headline"]) == 80 and r2(o2["de"][2016]["carriedShareLoss"]) == 150      # 200 − 150 = 50, плюс дивидент 30
assert [r2(r["headline"]) for r in o2["yearsTable"] if r["year"] == 2016] == [230]                                                      # таблицата по години е винаги БЕЗ пренасяне
o3 = scenario(TXT, [2016], carriedShareLoss=300)
assert r2(o3["de"][2016]["shareNet"]) == 0 and r2(o3["de"][2016]["shareCarry"]) == 100 and r2(o3["de"][2016]["headline"]) == 30 and o3["de"][2016]["lossLine"] == ""   # 200 − 300 → остават 100 за пренасяне; собствена загуба на годината няма
print("  ✓ въведен 150 € → 2016: 200 − 150 = 50 + 30 = 80; таблицата „По години“ остава 230 (без пренасяне); въведен 300 € → 100 € остават за пренасяне, а собствената загуба на годината е 0 (без ред за декларация)")
print("test_tax_loss_carry: ВСИЧКО ОК")
