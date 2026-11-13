"""
13.11.2026 (tax-real-fix, част Г): лихвата от даване на акции назаем (SYEP) — „Securities Lent Interest Details“ е дневната разбивка на месечните редове „(SYEP) Interest for Mon-YYYY“ в секция Interest;
включва се като „подробности, вече включени“ САМО когато сумата по дни за месеца = месечния ред; иначе — „не е сметнато“ (облагаемо), не се губи и не се брои двойно (docs/tax_core.js).
ПРОИЗХОД: раздел 1 — СИНТЕТИЧНИ редове (построени тук); раздел 2 — РЕАЛЕН формат с анонимни стойности (tests/fixtures/tax/real_anon/; в оригиналите сумите по месец съвпадат до цент за всички месеци).
Без мрежа; node — tests/tax_driver.js scenario. Без node — SKIP. Пускане: python test_tax_syep.py
"""
import json, shutil, subprocess, sys, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node"); sys.exit(0)
RATES = "Date,USD,JPY,GBP\n" + "".join(f"{(datetime.date(2025, 1, 1) + datetime.timedelta(days=i)).isoformat()},1.0,1.0,1.0\n" for i in range(0, 365 * 2))


def scenario(files, years=()):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files + [{"name": "ecb.csv", "text": RATES}], "years": list(years), "settings": {}}), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    o = json.loads(p.stdout)
    o["de"] = {int(y): v for y, v in o["de"].items()}
    return o


HEAD = ["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement", 'Statement,Data,Period,"January 1, 2026 - December 31, 2026"',
        "Account Information,Header,Field Name,Field Value", "Account Information,Data,Account,U5000001", "Account Information,Data,Base Currency,EUR",
        "Interest,Header,Currency,Account,Date,Description,Amount"]
DH = "Stock Yield Enhancement Program Securities Lent Interest Details,Header,Currency,Account,Value Date,Symbol,Start Date,Quantity,Collateral Amount,Market-based Rate (%),Interest Rate on Customer Collateral (%),Interest Paid to Customer,Code"
SY = "Stock Yield Enhancement Program Securities Lent Interest Details,Data,USD,U5000001"
sec = lambda o, name: next(s for s in o["files"][0]["sections"] if s["name"].endswith(name))

print("── 1. синтетично: дневните редове = месечния ред → „вече включени“; несъвпадение и месец без ред → „не е сметнато“ (облагаемо) ──")
txt = "\n".join(HEAD + [
    "Interest,Data,USD,U5000001,2026-02-04,USD Credit Interest for Jan-2026,10.00",
    "Interest,Data,USD,U5000001,2026-02-04,USD IBKR Managed Securities (SYEP) Interest for Jan-2026,0.30",       # януари: 0,10 + 0,20 = 0,30 ✓
    "Interest,Data,USD,U5000001,2026-03-04,USD IBKR Managed Securities (SYEP) Interest for Feb-2026,0.05",       # февруари: 0,07 ≠ 0,05 ✗
    "Interest,Data,Total,,,,10.35", DH,
    f"{SY},2026-01-12,AAA,2026-01-10,100,500,5.0,4.0,0.10,Po", f"{SY},2026-01-20,AAA,2026-01-10,100,500,5.0,4.0,0.20,Po",
    f"{SY},2026-02-12,AAA,2026-02-10,100,500,5.0,4.0,0.03,Po", f"{SY},2026-02-20,AAA,2026-02-10,100,500,5.0,4.0,0.04,Po",
    f"{SY},2026-03-12,AAA,2026-03-10,100,500,5.0,4.0,0.50,Po",                                                    # март: няма месечен ред във файла ✗
    "Stock Yield Enhancement Program Securities Lent Interest Details,Data,Total,,,,,,,,,0.87,"]) + "\n"
o = scenario([{"name": "s.csv", "text": txt}], years=[2026])
s = sec(o, "Interest Details")
assert s["data"] == 6 and s["ignored"] == 3 and s["skipped"] == 3, s                    # 2 (януари) + Total включени; 3 (февруари ×2, март ×1) — „не е сметнато“
sk = [x for x in o["skipped"] if x["section"].endswith("Interest Details")]
assert len(sk) == 3 and all(x["taxable"] for x in sk) and "2026-02" in sk[0]["reason"] and "0.07" in sk[0]["reason"] and "месечен ред 0.05" in sk[0]["reason"] and "2026-03" in sk[2]["reason"] and "няма" in sk[2]["reason"], sk
inc = [x for x in o["fifo"]["incomes"] if x["kind"] == "interest"]
assert round(sum(x["eur"] for x in inc), 6) == 10.35, inc                                  # самите месечни редове са в лихвите (10,00 + 0,30 + 0,05); детайлите — не
assert o["de"][2026]["complete"] is False and any("НЕПЪЛНО" in n["text"] for n in o["de"][2026]["notes"] if n["level"] == "err")
assert any(n["level"] == "info" and "SYEP" in n["text"] and "2026-01: 0.30" in n["text"] and "без двойно броене" in n["text"] for n in o["de"][2026]["notes"]), [n["text"] for n in o["de"][2026]["notes"]]
print("  ✓ януари (0,10 + 0,20 = 0,30 = месечния ред) → включени, без двойно броене (бележка със сумата по месец); февруари (0,07 ≠ 0,05) и март (без месечен ред) → „не е сметнато“, облагаемо, годината НЕПЪЛНО; лихвите са 10,35 — детайлите не се добавят")
ok = txt.replace("0.03,Po", "0.01,Po")                                                    # февруари: 0,01 + 0,04 = 0,05 = месечния ред
o = scenario([{"name": "s.csv", "text": ok.replace(f"{SY},2026-03-12,AAA,2026-03-10,100,500,5.0,4.0,0.50,Po\n", "")}], years=[2026])
assert [x for x in o["skipped"] if x["section"].endswith("Interest Details")] == [] and o["de"][2026]["complete"] is True, o["skipped"]
print("  ✓ когато всички месеци съвпадат (януари 0,10 + 0,20 = 0,30; февруари 0,01 + 0,04 = 0,05; март — без детайлите) — нищо не е „не е сметнато“, годината е пълна")

print("── 2. реален формат (анонимни стойности): дневните редове са включени във всички отчети ──")
FX = ROOT / "tests" / "fixtures" / "tax" / "real_anon"
files = [{"name": f.name, "text": f.read_text(encoding="utf-8")} for f in sorted(FX.glob("*.csv"))]
o = scenario(files, years=list(range(2016, 2026)))                                  # 14.11.2026: датите в копието са изместени с цели месеци — годините са на КОПИЕТО
n = 0
for f in o["files"]:
    for s in (f["sections"] or []):
        if s["name"].endswith("Lent Interest Details"):
            assert s["skipped"] == 0 and s["ignored"] == s["data"] and s["data"] > 0, (f["name"], s)
            n += 1
assert n == 2
yrs = [y for y in o["de"] if any("SYEP" in x["text"] and "без двойно броене" in x["text"] for x in o["de"][y]["notes"])]
assert len(yrs) >= 2, yrs                                                               # SYEP е в два от отчетите (по месеци — в повече от една календарна година на копието)
print("  ✓ двата отчета със SYEP: всички редове на „Securities Lent Interest Details“ са „вече включени“ (0 „не е сметнато“); бележка по година със сумата по месец и „без двойно броене“")
print("test_tax_syep: ВСИЧКО ОК")
