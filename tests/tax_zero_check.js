// 12.11.2026 (Цел 2 — никога тиха нула): docs/tax.html в Chromium върху СИНТЕТИЧНИ отчети (построени тук и от tests/fixtures/tax/). Без мрежа: страницата се сервира като
// http://tax.test/, eurofxref-hist.csv до нея е синтетичната таблица; всичко друго се спира. Резултатът — JSON на stdout за test_tax_silent_zero_page.py.
// По желание: node tests/tax_zero_check.js --shot папка  → снимки на сценариите (за преглед на ръка).
const path = require('path'), fs = require('fs'), os = require('os');
const { chromium } = require('playwright');
const ROOT = path.join(__dirname, '..'), FX = path.join(__dirname, 'fixtures', 'tax');
const shotDir = process.argv.includes('--shot') ? process.argv[process.argv.indexOf('--shot') + 1] : null;
const HEAD = ['Statement,Header,Field Name,Field Value', 'Statement,Data,BrokerName,Interactive Brokers Ireland Limited', 'Statement,Data,Title,Activity Statement',
  'Statement,Data,Period,"January 1, 2026 - November 11, 2026"', 'Account Information,Header,Field Name,Field Value', 'Account Information,Data,Name,Test Person',
  'Account Information,Data,Account,U1111111', 'Account Information,Data,Base Currency,EUR'];
const TRH = 'Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code';
const BUY = 'Trades,Data,Order,Stocks,USD,ACME,"2026-02-02, 10:00:00",10,100,100,-1000,-1,1001,0,0,O', SELL = 'Trades,Data,Order,Stocks,USD,ACME,"2026-03-02, 10:00:00",-10,120,120,1200,-1,-1001,198,0,C';
const DIV = ['Dividends,Header,Currency,Date,Description,Amount', 'Dividends,Data,EUR,2026-03-16,ACME(US00000000A1) Cash Dividend EUR 1.00 per Share (Ordinary Dividend),40', 'Dividends,Data,Total,,,40'];
const NOW = new Date().getFullYear();
const FILES = {
  // покупка и продажба в ТЕКУЩАТА година (в EUR — без курсове), нищо за миналата: тестът не зависи от това коя година е днес
  'only_this_year.csv': [...HEAD, TRH, BUY.replace('2026-', NOW + '-').replace(',USD,', ',EUR,'), SELL.replace('2026-', NOW + '-').replace(',USD,', ',EUR,')],
  'no_trades.csv': [...HEAD, ...DIV],                                         // отчет без секция Trades
  'sell_only.csv': [...HEAD, TRH, SELL],                                      // продажба без покупка
  'unknown.csv': ['Datum;Betrag;Text', '01.02.2026;12,50;abc'],               // непознат формат
  'renamed.csv': [...HEAD, TRH.replace('Date/Time', 'Trade Time'), BUY, SELL], // колоната с датата е с друго име → нито една сделка, нито един запис
};

async function scenario(browser, names, opts) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [], reqs = [];
  page.on('pageerror', e => errors.push(String(e.message)));
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.host !== 'tax.test') { reqs.push(url.href); return route.fulfill({ status: 503, body: 'blocked in test' }); }
    if (url.pathname.endsWith('/eurofxref-hist.csv')) return route.fulfill({ status: 200, contentType: 'text/csv', path: path.join(FX, 'ecb_rates_synthetic.csv') });
    const f = path.join(ROOT, 'docs', url.pathname.replace(/^\//, ''));
    return fs.existsSync(f) ? route.fulfill({ status: 200, path: f, contentType: f.endsWith('.js') ? 'text/javascript' : 'text/html; charset=utf-8' }) : route.fulfill({ status: 404, body: 'no' });
  });
  await page.goto('http://tax.test/tax.html');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'taxzero-'));
  const paths = names.map(n => { if (!FILES[n]) return path.join(FX, n); const p = path.join(tmp, n); fs.writeFileSync(p, FILES[n].join('\n') + '\n'); return p; });
  await page.setInputFiles('#fi', paths);
  await page.waitForFunction(() => document.getElementById('status').textContent && !/Смята се|Курсове/.test(document.getElementById('status').textContent), null, { timeout: 15000 });
  const snap = () => page.evaluate(() => { const t = id => (document.getElementById(id) || {}).innerText || ''; const big = document.querySelector('#headline .big');
    return { year: document.getElementById('year').value, yearLabels: [...document.getElementById('year').options].map(o => o.textContent), outVisible: document.getElementById('out').style.display !== 'none',
             big: big ? big.textContent : null, headline: t('headline'), whyZero: t('whyZero'), summary: t('summary'), fileMsgs: t('fileMsgs'), noout: t('noout'), warnings: t('warnings'), status: t('status'),
             filesTable: t('files'), bigMsgs: [...document.querySelectorAll('#fileMsgs .bigmsg, #noout .bigmsg')].map(e => ({ title: e.querySelector('b.t').textContent, border: getComputedStyle(e).borderTopColor, size: getComputedStyle(e.querySelector('b.t')).fontSize })),
             accountCells: [...document.querySelectorAll('#files td[data-acc]')].map(c => c.textContent), sectionTables: document.querySelectorAll('#files details').length, periods: [...document.querySelectorAll('#files [data-period]')].map(c => c.textContent), sales: document.getElementById('salesTitle').textContent,
             complete: typeof S !== 'undefined' && S.de ? S.de.complete : null }; });
  const first = await snap();
  if (shotDir) await page.screenshot({ path: path.join(shotDir, opts.shot + '.png'), fullPage: true });
  let second = null;
  if (opts.year) { await page.selectOption('#year', String(opts.year)); second = await snap(); if (shotDir) await page.screenshot({ path: path.join(shotDir, opts.shot + '_' + opts.year + '.png'), fullPage: true }); }
  let third = null;
  if (opts.addAfter) {                                                        // още един файл след ръчния избор на година — изборът се пази
    const p = path.join(FX, opts.addAfter); await page.setInputFiles('#fi', [p]);
    await page.waitForFunction(n => S.files.length === n, names.length + 1, { timeout: 15000 });
    await page.waitForFunction(() => document.getElementById('out').style.display !== 'none', null, { timeout: 15000 });
    third = await snap();
  }
  await page.close();
  fs.rmSync(tmp, { recursive: true, force: true });
  return { first, second, third, errors, requests: reqs };
}

(async () => {
  const browser = await chromium.launch();
  const out = {};
  out.onlyThisYear = await scenario(browser, ['only_this_year.csv'], { shot: 'only_this_year', year: NOW - 1, addAfter: 'U1111111_2020.csv' });
  out.noTrades = await scenario(browser, ['no_trades.csv'], { shot: 'no_trades' });
  out.sellOnly = await scenario(browser, ['sell_only.csv'], { shot: 'sell_only' });
  out.unknown = await scenario(browser, ['unknown.csv'], { shot: 'unknown' });
  out.renamed = await scenario(browser, ['renamed.csv'], { shot: 'renamed' });
  out.many = await scenario(browser, ['U1111111_2020.csv', 'U1111111_2021.csv', 'U1111111_2023.csv', 'broker2_export.csv'], { shot: 'many', year: 2023 });
  out.thisYear = new Date().getFullYear();
  await browser.close();
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
