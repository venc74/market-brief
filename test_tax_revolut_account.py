"""
15.11.2026 (tax-crypto-account): „Account statement“ на Revolut за ЕДНА валута — РЕАЛНИЯТ формат на 17-те крипто файла на потребителя (колони Type, Product, Started Date, Completed Date, Description, Amount, Fee, Currency, State, Balance;
дата „ГГГГ-ММ-ДД ЧЧ:ММ:СС“; видове EXCHANGE „Exchanged to …“ и TRANSFER „Balance migration to another region or legal entity“). Само количества — без цена в евро. Калкулаторът го РАЗПОЗНАВА (не „непознат формат“), нищо не смята и
казва какво липсва; само годините, в които файлът има редове, стават НЕПЪЛНО.
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7 / 9): tests/fixtures/tax/revolut_real/revolut_crypto_account_real_format.csv — ЗАГЛАВНИЯТ ред е дословно от реалните файлове (15.11.2026), редовете са ИЗМИСЛЕНИ (валути ZZA / ZZB, количества, дати 2017–2018);
стандартният CSV с две акции (2017 и 2019) е СИНТЕТИЧЕН, построен тук. Курс 1,0.
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP. Пускане: python test_tax_revolut_account.py
"""
import json, shutil, subprocess, sys, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
FX = ROOT / "tests" / "fixtures" / "tax" / "revolut_real"
RATES = "Date,USD,JPY,GBP\n" + "".join(f"{(datetime.date(2013, 1, 1) + datetime.timedelta(days=i)).isoformat()},1.0,1.0,1.0\n" for i in range(0, 365 * 8))
CRYPTO = (FX / "revolut_crypto_account_real_format.csv").read_text(encoding="utf-8")
STD = "type,ticker,date,quantity,price,currency,broker,account,asset_type\n" + "".join(f"{t},{k},{d},{q},{p},USD,CSV,main,stock\n" for t, k, d, q, p in [
    ("buy", "AAA", "2017-02-01", 10, 10), ("sell", "AAA", "2017-06-01", 10, 12), ("buy", "BBB", "2019-02-01", 5, 10), ("sell", "BBB", "2019-03-01", 5, 11)])


def scenario(files, years=()):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files + [{"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": {}}), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    o["de"] = {int(y): v for y, v in o["de"].items()}
    return o


print("── 1. разпознаване на реалния формат ──")
assert CRYPTO.splitlines()[0] == "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance"            # дословно от реалния файл
o = scenario([{"name": "zza.csv", "text": CRYPTO}], years=[2017])
f = o["files"][0]
assert f["format"] == "revolut_account" and f["broker"] == "Revolut" and f["error"] is None and o["records"] == [], f
assert "само количества" in f["note"] and f["kinds"]["trade"] == 0
pr = f["problems"]
assert len(pr) == 1 and pr[0]["level"] == "warn" and "разпознат файл само с количества" in pr[0]["title"] and "5 реда" in pr[0]["lines"][0] and "2017: 3" in pr[0]["lines"][0] and "2018: 2" in pr[0]["lines"][0], pr
assert not any("не намерих сделки" in p["title"] or "Не разпознах" in p["title"] for p in pr)
print("  ✓ формат revolut_account (не „непознат формат“, не „няма сделки“): 5 реда — 2017: 3, 2018: 2; предупреждение, че са само количества; записи 0")
sk = o["skipped"]
assert [(s["date"], s["amount"], s["taxable"]) for s in sk] == [("2017-12-31", "3", True), ("2018-12-31", "2", True)] and "без цена в евро" in sk[0]["reason"] and "обмени 3" in sk[0]["what"] and "прехвърляния 1" in sk[1]["what"], sk
print("  ✓ по един ред „не е сметнато“ (облагаемо) за всяка година с редове — с броя на обмените и прехвърлянията и какво да се качи")

print("── 2. само годините с редове стават НЕПЪЛНО ──")
o = scenario([{"name": "std.csv", "text": STD}, {"name": "zza.csv", "text": CRYPTO}], years=[2017, 2018, 2019])
base = scenario([{"name": "std.csv", "text": STD}], years=[2017, 2018, 2019])
assert base["de"][2017]["complete"] and base["de"][2019]["complete"]
assert o["de"][2017]["complete"] is False and o["de"][2018]["complete"] is False and o["de"][2019]["complete"] is True, [o["de"][y]["complete"] for y in (2017, 2018, 2019)]
assert round(o["de"][2017]["headline"], 6) == round(base["de"][2017]["headline"], 6) == 20 and round(o["de"][2019]["headline"], 6) == 5     # числата на акциите не се променят
assert any("не е сметнато" in n["text"] or "облагаем" in n["text"] or "Revolut" in n["text"] for n in o["de"][2017]["notes"] if n["level"] == "err"), o["de"][2017]["notes"]
print("  ✓ 2017 и 2018 (има редове във файла) — НЕПЪЛНО с червено съобщение; 2019 (няма редове) — пълно; числата за акциите са същите (20 и 5)")
print("test_tax_revolut_account: ВСИЧКО ОК")
