"""
12.11.2026 (tax-real-fix): tools/tax_diagnose.js — диагнозата на отчет през старата (docs/tax-v1.html) и новата (docs/tax_core.js) логика.
Най-важното: изходът е САМО структура и броеве — без тикъри, сметки, имена, описания и суми от файла (ще се пуска върху истински отчет и изходът ще се показва).
ВСИЧКИ входове са СИНТЕТИЧНИ: tests/fixtures/tax/ и един файл, построен тук, с колона Account след Currency — подредбата, която чете tax-v1 по позиция
([5] между Currency и Symbol; [3] между Currency и Date при дивидентите). Това е извод от кода на tax-v1, НЕ от реален отчет.
Без node — SKIP. Пускане: python test_tax_diagnose.py
"""
import sys, shutil, pathlib, subprocess, tempfile
ROOT = pathlib.Path(__file__).parent
FX = ROOT / "tests" / "fixtures" / "tax"
NODE = shutil.which("node")
if not NODE:
    print("SKIP: няма node — tools/tax_diagnose.js не е изпълнен (в CI node има)")
    sys.exit(0)


def run(files, *opts):
    p = subprocess.run([NODE, str(ROOT / "tools" / "tax_diagnose.js"), "--rates", str(FX / "ecb_rates_synthetic.csv"), *opts] + [str(f) for f in files],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]
    return p.stdout


print("── 1. стандартната подредба (синтетичните файлове): само структура, без лични данни ──")
out = run([FX / "U1111111_2020.csv", FX / "U1111111_2021.csv", FX / "U1111111_2023.csv"], "--year", "2023")
SECRET = ["ACME", "XWLD", "SPLT", "OLDCO", "U1111111", "Test Person", "NYSE Market Data", "Cash Dividend", "Credit Interest", "US00000000A1", "SYNTH WORLD",
          "12.34", "248.95", "1080", "2998", "1234.56", "U1111111_2023"]
leaked = [s for s in SECRET if s in out]
assert not leaked, leaked
assert "[Trades] редове: Data ×8 · Header ×2" in out and "Order × Stocks ×4 · Order × Equity and Index Options ×2 · ClosedLot × Stocks ×1 · Order × Forex ×1" in out, out[:3000]
assert "заглавен ред 1 (14 колони): DataDiscriminator | Asset Category | Currency | Symbol | Date/Time | Quantity | T. Price" in out
assert "вид на клетките „Date/Time“: дата и час „YYYY-MM-DD, HH:MM:SS“ (в кавички) ×7 · дата YYYY-MM-DD ×1" in out
assert "вид на клетките „Quantity“: цяло число ×7 · цяло с хилядни запетаи (в кавички) ×1" in out
assert "Period = January 1, 2023 - December 31, 2023" in out and "Account = (маскирано; форма „A9“)" in out and "Base Currency = EUR" in out
# старата чете по позиция: в тази подредба Symbol е на [5], а тя го търси на [6] → нито една сделка
assert out.count("няма намерени сделки с акции") == 3 and "[5] = Symbol · [6] = Date/Time · [7] = Quantity · [8] = T. Price" in out
assert "Trades: Data редове 8 → „Order“ 7 → Stocks / ETF 4 → с количество, цена и дата 0" in out
# новата: по име; всеки Data ред има сметка — запис / „не е сметнато“ / без следа
assert "записи по вид: сделки 7 (покупки 2, продажби 5; по клас: stock ×5 · option ×2) · дивиденти 2 · удържан данък 2 · лихви 3 · сплитове 0" in out
assert "[Trades] Data 8 → записи 6 · „не е сметнато“ 1 · без следа 1" in out and "не е сметнато ×1: [Trades] обмяна на валута (Forex)" in out
# 13.11.2026: продажбата на SPLT без покупка (файлът за 2022 липсва) е покрита от начална позиция по отчета (Prior Quantity) без покупки → „лот без покупна цена“, не „без покупка\nassert "2023: продажби 5 (без курс: 0) · лот без покупна цена 1 · без покупка 0 · числото най-горе: положително · НЕПЪЛНО" in out
assert "Старата логика не намери нито една сделка — сравнение няма." in out
print("  ✓ секции, заглавни редове, видове редове и клетки, броеве по причина; нито един тикър / сметка / име / сума от файловете в изхода")

print("── 2. подредбата с колона Account (тази, която tax-v1 чете): двете логики върху един вход, сравнение без суми ──")
ACCT = "﻿" + "\r\n".join([
    "Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement",
    'Statement,Data,Period,"January 1, 2026 - November 11, 2026"',
    "Account Information,Header,Field Name,Field Value", "Account Information,Data,Name,Test Person", "Account Information,Data,Account,U2222222", "Account Information,Data,Base Currency,EUR",
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Account,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code",
    'Trades,Data,Order,Stocks,USD,U2222222,ZZTOP,"2026-02-02, 10:00:00","1,000",100,100,"-100,000",-1,"100,001",0,0,O',
    'Trades,Data,Order,Stocks,USD,U2222222,ZZTOP,"2026-03-02, 10:00:00","-1,000",120,120,"120,000",-1,"-100,001","19,998",0,C',
    'Trades,SubTotal,,Stocks,USD,U2222222,ZZTOP,,0,,,"20,000",-2,0,"19,998",0,',
    "Dividends,Header,Currency,Account,Date,Description,Amount",
    "Dividends,Data,USD,U2222222,2026-03-16,ZZTOP (US00000000Z1) Cash Dividend USD 0.77 per Share (Ordinary Dividend),77",
    "Dividends,Data,Total,,,,77",
    "Withholding Tax,Header,Currency,Account,Date,Description,Amount,Code",
    "Withholding Tax,Data,USD,U2222222,2026-03-16,ZZTOP (US00000000Z1) Cash Dividend USD 0.77 per Share - US Tax,-11.55,",
])
with tempfile.TemporaryDirectory() as tmp:
    f = pathlib.Path(tmp) / "U2222222_20260101_20261111.csv"
    f.write_text(ACCT, encoding="utf-8")
    out2 = run([f])
leaked = [s for s in ["ZZTOP", "U2222222", "Test Person", "100,000", "120,000", "19,998", "11.55", "0.77", "US00000000Z1"] if s in out2]
assert not leaked, leaked
assert "BOM: да · край на реда: CRLF" in out2
assert "[5] = Account · [6] = Symbol · [7] = Date/Time · [8] = Quantity · [9] = T. Price" in out2 and "[3] = Account · [4] = Date · [5] = Description · [6] = Amount" in out2
assert "Trades: Data редове 2 → „Order“ 2 → Stocks / ETF 2 → с количество, цена и дата 2" in out2 and "сделки в сметката: покупки 1 · продажби 1 · дивиденти 1" in out2
assert "записи по вид: сделки 2 (покупки 1, продажби 1; по клас: stock ×2) · дивиденти 1 · удържан данък 1 · лихви 0 · сплитове 0" in out2
assert "сравнението стара ↔ нова е за: 2026" in out2 and "── 2026 ──" in out2 and "продажби: стара 1 (от тях без пълна покупка — с цена 0 за липсващото: 0) · нова 1 + без покупка 0" in out2
assert "САМ ЗА СЕБЕ СИ (само този файл): продажби във файла 1 → с резултат 1 (без курс: 0) · без покупка 0 · записи без курс 0" in out2
# ръчно: старата — 1000 × 120 − 1000 × 100 = 20 000 USD (без комисионни, по курса на продажбата и на покупката: 1.15 през 2026 в синтетичната таблица);
# новата — (120 000 − 1) − (100 000 + 1) = 19 998 USD → 19 998 / 20 000 = 99.99%
assert "резултат от продажбите на акции / фондове (преди освобождаване): новата е 99.99% от старата" in out2, out2[-1500:]
assert "дивиденти: стара 1 бр. · нова 1 бр.; сумата — новата е 100.00% от старата" in out2
assert "годината, с която страницата тръгва днес (main):" in out2
assert "колона „Account“: 1 различни стойности (форма: A9 ×2)" in out2 and "сметки със сделки (новата води FIFO по сметка, старата — само по тикър): 1" in out2

print("  ✓ старата намира сделките (Account на [5]); новата — същите по име; сравнението е в брой и проценти (99.99% — комисионните), без суми")

print("── 3. покупката в една сметка, продажбата — в друга (СИНТЕТИЧНО): старата смята по тикър, новата — „липсва покупката“ ──")
TWO = ACCT.replace('Trades,Data,Order,Stocks,USD,U2222222,ZZTOP,"2026-03-02', 'Trades,Data,Order,Stocks,USD,U3333333,ZZTOP,"2026-03-02')
with tempfile.TemporaryDirectory() as tmp:
    f = pathlib.Path(tmp) / "two_accounts.csv"
    f.write_text(TWO, encoding="utf-8")
    out3 = run([f])
assert not [s for s in ["ZZTOP", "U2222222", "U3333333", "two_accounts"] if s in out3]
assert "колона „Account“: 2 различни стойности" in out3 and "сметки със сделки (новата води FIFO по сметка, старата — само по тикър): 2" in out3
assert "сделки, чиято сметка (колона Account) е различна от тази в Account Information на отчетите: 1 · инструменти със сделки в повече от една сметка: 1 от 1" in out3
assert "без покупка ×1: по-ранна покупка на същия инструмент има САМО В ДРУГА СМЕТКА" in out3
assert "продажби: стара 1 (от тях без пълна покупка — с цена 0 за липсващото: 0) · нова 0 + без покупка 1" in out3
assert "САМ ЗА СЕБЕ СИ (само този файл): продажби във файла 1 → с резултат 0 (без курс: 0) · без покупка 1" in out3
assert "2026: продажби 0 (без курс: 0) · без покупка 1 · числото най-горе: положително · НЕПЪЛНО" in out3      # само дивидентът; продажбата не е в числото
print("  ✓ две сметки в един отчет: старата намира покупката (по тикър), новата я търси в същата сметка → „без покупка“; инструментът казва къде е покупката, без номера")
print("\n✅ test_tax_diagnose: всичко мина")
