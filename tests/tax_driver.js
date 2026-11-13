// Драйвер за test_tax_core.py: зарежда docs/tax_core.js в Node и пуска стъпките върху СИНТЕТИЧНИТЕ файлове от tests/fixtures/tax/ (без мрежа).
// Употреба: node tests/tax_driver.js <стъпка> '<json с настройките>' файл1 файл2 …   → JSON на stdout
const fs = require('fs'), path = require('path');
const TC = require(path.join(__dirname, '..', 'docs', 'tax_core.js'));
const [, , step, cfg, ...names] = process.argv;
// 05.11.2026: стъпка scenario — СИНТЕТИЧНИ файлове като JSON на stdin {files: [{name, text, owner}], years: [..], settings: {..}} → ingest + fifo + computeDE по години
if (step === 'scenario') {
  const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
  const ing = TC.ingest(sc.files);
  const st = sc.settings || {};
  const res = TC.fifo(ing.records, TC.rateLookup(ing.rates), { ...st, controls: st.noControls ? [] : ing.controls, corp: st.corp });   // 13.11.2026: и контролите по началните / крайните позиции (noControls — само за теста „без контроли“)
  const de = {}; (sc.years || []).forEach(y => { de[y] = TC.computeDE(res, { ...st, year: y, records: ing.records, info: ing.info, warnings: ing.warnings, skipped: ing.skipped, corpEvents: ing.corpEvents }); });
  // 12.11.2026: резюмето „Прочетени: …“ и причината за 0 — по години
  const summary = {}, whyZero = {}; (sc.years || []).forEach(y => { summary[y] = TC.summary(ing, res, y); whyZero[y] = TC.whyZero(de[y], summary[y]); });
  const yearsTable = TC.yearsTable(res, { ...st, records: ing.records, info: ing.info, warnings: ing.warnings, skipped: ing.skipped, corpEvents: ing.corpEvents });   // 14.11.2026: по години, БЕЗ пренасяне
  process.stdout.write(JSON.stringify({ files: ing.files, warnings: ing.warnings, skipped: ing.skipped, records: ing.records, fifo: res, de, summary, whyZero, yearsTable, masked: (sc.mask || []).map(TC.maskAccount) }), () => process.exit(0));   // 13.11.2026: излизане СЛЕД записа — при изход над ~64 KB (истинският формат, 4 отчета) process.exit режеше JSON-а в тръбата
  return;                                                                                // (модулът е CommonJS — return спира останалите стъпки; излизането идва от обратното повикване)
}
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
  const res = TC.fifo(ing.records, TC.rateLookup(ing.rates), { controls: ing.controls });
  out = { realized: res.realized, unmatched: res.unmatched, missingRates: res.missingRates, open: res.open, incomes: res.incomes, notes: res.notes, needed: TC.ratesNeeded(ing.records) };
} else if (step === 'de') {
  const res = TC.fifo(ing.records, TC.rateLookup(ing.rates), { controls: ing.controls });
  out = TC.computeDE(res, { ...settings, records: ing.records, info: ing.info });
} else if (step === 'params') {
  out = (settings.years || []).map(y => TC.deParams(y));
} else throw new Error('непозната стъпка ' + step);
process.stdout.write(JSON.stringify(out));
