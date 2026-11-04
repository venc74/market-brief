// Драйвер за test_tax_core.py: зарежда docs/tax_core.js в Node и пуска стъпките върху СИНТЕТИЧНИТЕ файлове от tests/fixtures/tax/ (без мрежа).
// Употреба: node tests/tax_driver.js <стъпка> '<json с настройките>' файл1 файл2 …   → JSON на stdout
const fs = require('fs'), path = require('path');
const TC = require(path.join(__dirname, '..', 'docs', 'tax_core.js'));
const [, , step, cfg, ...names] = process.argv;
const settings = cfg ? JSON.parse(cfg) : {};
const files = names.map(n => ({ name: path.basename(n), text: fs.readFileSync(n, 'utf8') }));
let out;
if (step === 'ecbjson') { out = TC.parseECBjson(JSON.parse(files[0].text)); process.stdout.write(JSON.stringify(out)); process.exit(0); }
if (step === 'frankfurter') { out = TC.parseFrankfurter(JSON.parse(files[0].text), 'USD'); process.stdout.write(JSON.stringify(out)); process.exit(0); }
const ing = TC.ingest(files);
if (step === 'lookup') {
  const look = TC.rateLookup(ing.rates);
  out = Object.fromEntries((settings.dates || []).map(d => [d, look(settings.currency || 'USD', d)]));
} else if (step === 'ingest') {
  out = { files: ing.files, records: ing.records.map(r => ({ kind: r.kind, broker: r.broker, account: r.account, sym: r.sym, cls: r.assetClass, date: r.date, qty: r.qty,
          price: r.price, fee: r.fee, amount: r.amount, ratio: r.ratio, currency: r.currency, pil: r.pil, fundHint: r.fundHint })), skipped: ing.skipped,
          info: ing.info, rateCurrencies: Object.keys(ing.rates) };
} else if (step === 'fifo') {
  const res = TC.fifo(ing.records, TC.rateLookup(ing.rates));
  out = { realized: res.realized, unmatched: res.unmatched, missingRates: res.missingRates, open: res.open, incomes: res.incomes, notes: res.notes, needed: TC.ratesNeeded(ing.records) };
} else if (step === 'de') {
  const res = TC.fifo(ing.records, TC.rateLookup(ing.rates));
  out = TC.computeDE(res, { ...settings, instruments: ing.instruments, info: ing.info });
} else throw new Error('непозната стъпка ' + step);
process.stdout.write(JSON.stringify(out));
