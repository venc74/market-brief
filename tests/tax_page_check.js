// Проверка на docs/tax.html в Chromium (Playwright): страницата + docs/tax_core.js върху СИНТЕТИЧНИТЕ файлове от tests/fixtures/tax/. Всяка мрежова заявка се спира и записва;
// „ЕЦБ“ и „frankfurter“ се отговарят от синтетичната таблица (ecb_rates_synthetic.csv) — режим ecb | frankfurter. Резултатът — JSON на stdout за test_tax_page.py.
const path = require('path'), fs = require('fs');
const { chromium } = require('playwright');
const ROOT = path.join(__dirname, '..'), FX = path.join(__dirname, 'fixtures', 'tax');
const RATES = {};                                                     // синтетичната таблица: USD за 1 EUR по дата
fs.readFileSync(path.join(FX, 'ecb_rates_synthetic.csv'), 'utf8').split(/\r?\n/).slice(1).forEach(l => { const p = l.split(','); if (p[1]) RATES[p[0]] = Number(p[1]); });

async function scenario(files, opts) {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const reqs = [], errors = [];
  page.on('pageerror', e => errors.push(String(e.message)));
  await page.route('**/*', route => {
    const u = route.request().url();
    if (u.startsWith('file://')) return route.continue();
    reqs.push(u);
    const url = new URL(u);
    if (u.includes('data-api.ecb.europa.eu') && opts.mode === 'ecb') {
      const from = url.searchParams.get('startPeriod'), to = url.searchParams.get('endPeriod');
      const ds = Object.keys(RATES).filter(d => d >= from && d <= to).sort();
      const obs = {}; ds.forEach((d, i) => { obs[String(i)] = [RATES[d]]; });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ dataSets: [{ series: { '0:0:0:0:0': { observations: obs } } }],
        structure: { dimensions: { observation: [{ id: 'TIME_PERIOD', values: ds.map(d => ({ id: d })) }] } } }) });
    }
    if (u.includes('api.frankfurter.app') && opts.mode === 'frankfurter') {
      const [from, to] = url.pathname.slice(1).split('..');
      const rates = {}; Object.keys(RATES).filter(d => d >= from && d <= to).forEach(d => { rates[d] = { USD: RATES[d] }; });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ amount: 1, base: 'EUR', rates }) });
    }
    return route.fulfill({ status: 503, body: 'blocked in test' });
  });
  await page.goto('file://' + path.join(ROOT, 'docs', 'tax.html'));
  const atLoad = reqs.length;
  await page.setInputFiles('#fi', files);
  await page.waitForFunction(() => !document.getElementById('calc').disabled, null, { timeout: 10000 });
  await page.evaluate(o => { if (o.year) document.getElementById('year').value = String(o.year); if (o.joint) document.getElementById('joint').value = '1';
                              if (o.kirche) document.getElementById('kirche').value = o.kirche; }, opts);
  await page.click('#calc');
  await page.waitForFunction(() => document.getElementById('out').style.display !== 'none', null, { timeout: 15000 });
  const res = await page.evaluate(() => ({ headline: S.de.headline, total: S.de.total, unmatched: S.de.unmatched.map(u => u.sym), big: document.querySelector('#headline .big').textContent,
    warnings: document.getElementById('warnings').innerText, rateSource: S.rateSource, bgVisible: document.getElementById('bg').style.display !== 'none',
    xss: window.__xss || null, sales: document.querySelectorAll('#sales tr').length - 1, estimate: S.de.estimate }));
  await browser.close();
  return { ...res, atLoad, requests: reqs, errors };
}

(async () => {
  const f = n => path.join(FX, n);
  const IB = ['U1111111_2020.csv', 'U1111111_2021.csv', 'U1111111_2022.csv', 'U1111111_2023.csv', 'U1111111_2023 (1).csv', 'U1111111_Q4_2023.csv', 'U1111111_2026.csv', 'broker2_export.csv'].map(f);
  const out = {};
  out.withEcbFile = await scenario([...IB, f('ecb_rates_synthetic.csv')], { year: 2023, mode: 'none' });
  out.ecbApi = await scenario(IB, { year: 2023, mode: 'ecb' });
  out.frankfurter = await scenario(IB, { year: 2023, mode: 'frankfurter' });
  out.noRates = await scenario(IB, { year: 2023, mode: 'none' });
  // XSS: опасно име на файла и тикър (СИНТЕТИЧНО)
  const tmp = fs.mkdtempSync(path.join(require('os').tmpdir(), 'taxxss-'));
  const evil = path.join(tmp, '<img src=x onerror=window.__xss=1>.csv');
  fs.writeFileSync(evil, 'type,asset_type,ticker,date,quantity,price,currency\nbuy,stock,"<img src=x onerror=window.__xss=2>",2023-01-10,1,10,EUR\nsell,stock,"<img src=x onerror=window.__xss=2>",2023-02-10,1,12,EUR\n');
  out.xss = await scenario([evil], { year: 2023, mode: 'none' });
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
