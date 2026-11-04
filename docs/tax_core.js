/*
 * tax_core.js — сметките на данъчния калкулатор (docs/tax.html). Чисти функции, без DOM и без мрежа: страницата подава текста на файловете и курсовете,
 * получава записите, FIFO резултатите и германската разбивка. Същият файл се тества в Node (test_tax_core.py → tests/tax_driver.js).
 * 04.11.2026 (tax-fixes): разпознаване по СЪДЪРЖАНИЕ (брокер, сметка, дати), дедупликация на застъпващи се отчети, FIFO по сметка от най-старата покупка,
 * продажба без покупка → предупреждение (никога цена 0), сплитове, комисионни, дивиденти със сторно / върнат данък, лихви, „не е сметнато“ — нищо не се пропуска тихо.
 * Само информация — не е данъчна консултация; правилата, в които няма сигурност, са настройки с бележка „да се потвърди“.
 */
(function (root) {
  'use strict';
  const TC = {};

  // ─── Параметри по години (Германия) ──────────────────────────────────────────
  // Всеки запис важи от годината `from` до следващия запис. Нова година без промяна в правилата → нищо не се пипа (важи последният запис); промяна → нов ред.
  TC.DE_PARAMS = [
    { from: 2009, abgeltung: 0.25, soli: 0.055, pauschbetrag: 801, freigrenze23: 600, teilfreistellung: null,
      note: 'Abgeltungsteuer от 2009; Sparer-Pauschbetrag 801 € (1 602 € съвместно); Freigrenze по §23 EStG — 600 € на човек' },
    { from: 2018, teilfreistellung: { equity: 0.30, mixed: 0.15, realestate: 0.60, realestate_foreign: 0.80, other: 0 },
      note: 'InvStG 2018: частично освобождаване (Teilfreistellung) за фондове' },
    { from: 2023, pauschbetrag: 1000, note: 'Sparer-Pauschbetrag 1 000 € (2 000 € съвместно)' },
    { from: 2024, freigrenze23: 1000, note: 'Freigrenze по §23 EStG — 1 000 € на човек (Wachstumschancengesetz)' },
  ];
  TC.DE_PARAMS_CHECKED_UNTIL = 2026;            // до тази година параметрите са проверени при писането; след нея — последният запис + бележка в страницата
  TC.KIRCHE_RATES = { BY: 0.08, BW: 0.08, other: 0.09 };
  TC.FUND_TYPES = { stock: 'акция (не фонд)', equity: 'акционерен фонд (≥ 51% акции)', mixed: 'смесен фонд (≥ 25% акции)', realestate: 'имотен фонд',
                    realestate_foreign: 'имотен фонд, чужди имоти', other: 'друг фонд (без освобождаване)' };

  TC.deParams = function (year) {
    const out = { year, extrapolated: year > TC.DE_PARAMS_CHECKED_UNTIL, notes: [] };
    TC.DE_PARAMS.filter(p => p.from <= year).forEach(p => { Object.keys(p).forEach(k => { if (k !== 'from' && k !== 'note') out[k] = p[k]; }); if (p.note) out.notes.push(p.from + ': ' + p.note); });
    return out;
  };

  // ─── Помощни ────────────────────────────────────────────────────────────────
  TC.esc = s => String(s == null ? '' : s).replace(/[&<>"'`]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' }[c]));

  TC.splitCSV = function (line) {
    const out = []; let cur = '', q = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++; } else q = !q; continue; }
      if (c === ',' && !q) { out.push(cur); cur = ''; continue; }
      cur += c;
    }
    out.push(cur);
    return out.map(s => s.trim());
  };

  // числа във формата на брокера: "1,234.56" (хиляди със запетая) → 1234.56; празно / нечисло → NaN
  TC.num = function (s) {
    if (s == null) return NaN;
    const t = String(s).replace(/["\s]/g, '').replace(/,(?=\d{3}(\D|$))/g, '');
    return t === '' || t === '--' ? NaN : Number(t);
  };

  // дата/час: "2024-01-10, 10:00:00", "2024-01-10;10:00:00", "20240110;100000", "2024-01-10" → {date, time}
  TC.parseDateTime = function (s) {
    const m = String(s || '').match(/(\d{4})-?(\d{2})-?(\d{2})(?:[,;T ]+\s*(\d{2}):?(\d{2}):?(\d{2})?)?/);
    if (!m) return null;
    return { date: `${m[1]}-${m[2]}-${m[3]}`, time: m[4] ? `${m[4]}:${m[5]}:${m[6] || '00'}` : '' };
  };

  TC.addDays = function (date, n) { const d = new Date(date + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };

  // годишнината по §108 AO / §188 BGB: същата дата година по-късно; 29.02 → 28.02 (последният ден на месеца)
  TC.anniversary = function (date) {
    const [y, m, d] = date.split('-').map(Number);
    const last = new Date(Date.UTC(y + 1, m, 0)).getUTCDate();
    return `${y + 1}-${String(m).padStart(2, '0')}-${String(Math.min(d, last)).padStart(2, '0')}`;
  };

  // ─── Разпознаване по съдържание ─────────────────────────────────────────────
  TC.detect = function (text) {
    const t = String(text || '').replace(/^﻿/, '');
    const first = t.split(/\r?\n/).find(l => l.trim()) || '';
    if (/^Statement,Header,/.test(first) || /Statement,Data,BrokerName,Interactive Brokers/.test(t)) return 'ibkr';
    const h = TC.splitCSV(first).map(x => x.toLowerCase());
    if (h[0] === 'date' && h.length > 3 && h.slice(1).filter(x => x).every(x => /^[a-z]{3}$/.test(x))) return 'ecb_rates';
    if (['type', 'ticker', 'date', 'quantity', 'currency'].every(c => h.includes(c)) && h.includes('price') && !h.includes('price per share')) return 'standard';
    if (h.includes('ticker') && h.includes('price per share') && h.includes('total amount')) return 'revolut_stocks';
    if (h.includes('symbol') && h.includes('type') && h.includes('quantity') && h.includes('price') && h.includes('value') && h.includes('fees')) return 'revolut_crypto';
    if (h.includes('type') && h.includes('product') && h.includes('started date') && h.includes('fiat amount')) return 'revolut_crypto_old';
    return 'unknown';
  };

  // ─── IBKR Activity Statement (CSV) — по заглавните редове на всяка секция, не по позиции ─────────────────────
  const IBKR_ASSET = { 'Stocks': 'stock', 'Equity and Index Options': 'option', 'Forex': 'forex', 'Crypto': 'crypto', 'Bonds': 'other', 'Futures': 'other',
                       'Options On Futures': 'other', 'Warrants': 'other', 'Structured Products': 'other', 'CFDs': 'other', 'Mutual Funds': 'fund' };
  // секции без сделки (обобщения) — не носят нищо за сметката; всичко друго с Data редове и без обработка излиза в „не е сметнато“
  const IBKR_INFO = new Set(['Statement', 'Account Information', 'Net Asset Value', 'Change in NAV', 'Mark-to-Market Performance Summary', 'Realized & Unrealized Performance Summary',
    'Cash Report', 'Open Positions', 'Forex Balances', 'Codes', 'Notes/Legal Notes', 'Notes', 'Base Currency Exchange Rate', 'Change in Dividend Accruals', 'Interest Accruals',
    'Month & Year to Date Performance Summary', 'Location of Customer Assets, Positions and Money', 'Net Stock Position Summary', 'Disclosures', 'Legal Notes',
    'Change in Position Value', 'Dividend Accruals', 'Complex Position Summary', 'Trade Summary by Asset', 'Commission Details']);

  // тикърът в началото на описание на IBKR: "AAPL(US0378331005) Cash Dividend…" и "AAPL (US0378331005) …"
  TC.ibkrDescSymbol = function (desc) { const m = String(desc || '').match(/^\s*([A-Z0-9][A-Z0-9.\- ]*?)\s*\(([A-Z]{2}[A-Z0-9]{9}\d)\)/); return m ? { sym: m[1].trim(), isin: m[2] } : null; };

  TC.parseIBKR = function (text, src) {
    const lines = String(text).replace(/^﻿/, '').split(/\r?\n/);
    const head = {}, recs = [], skipped = [], info = { broker: 'IBKR', account: '', period: '', periodEnd: '', baseCurrency: '', nonBaseCash: [], openPositions: null };
    const instruments = {};
    const rows = [];
    lines.forEach((line, i) => {
      if (!line.trim()) return;
      const p = TC.splitCSV(line);
      const sec = p[0], typ = p[1];
      if (typ === 'Header') { head[sec] = p.slice(2); return; }
      if (typ !== 'Data' || !head[sec]) return;
      const r = {}; head[sec].forEach((h, k) => { r[h] = p[k + 2] !== undefined ? p[k + 2] : ''; });
      rows.push({ sec, r, line: i + 1, raw: line });
    });
    if (head['Open Positions']) info.openPositions = [];
    rows.forEach(({ sec, r }) => {
      if (sec === 'Statement' && r['Field Name'] === 'BrokerName') info.brokerName = r['Field Value'];
      if (sec === 'Statement' && r['Field Name'] === 'Period') { info.period = r['Field Value']; const e = TC.parseLooseDate(String(r['Field Value'] || '').split(/\s+-\s+/).pop()); info.periodEnd = e ? e.date : ''; }
      // 05.11.2026: наличностите в края на периода — за сверка с FIFO (липсващ по-стар отчет, пропуснат ред); само обобщените редове (Summary), не лотовете
      if (sec === 'Open Positions' && (!r['DataDiscriminator'] || r['DataDiscriminator'] === 'Summary') && IBKR_ASSET[r['Asset Category']] && !['forex', 'other'].includes(IBKR_ASSET[r['Asset Category']])) {
        const q = TC.num(r['Quantity']); if (isFinite(q)) info.openPositions.push({ account: r['Account'] || '', sym: r['Symbol'], qty: q });
      }
      if (sec === 'Account Information' && r['Field Name'] === 'Account') info.account = (r['Field Value'] || '').split(/\s/)[0];
      if (sec === 'Account Information' && r['Field Name'] === 'Base Currency') info.baseCurrency = r['Field Value'];
      if (sec === 'Financial Instrument Information' && r['Symbol']) instruments[r['Symbol']] = { type: r['Type'] || '', category: r['Asset Category'] || '', desc: r['Description'] || '' };
      if (sec === 'Cash Report' && /Ending Cash/i.test(r['Currency Summary'] || '') && r['Currency'] && r['Currency'] !== 'Base Currency Summary' && r['Currency'] !== (info.baseCurrency || 'EUR')) {
        const v = TC.num(r['Total']); if (v && Math.abs(v) > 0.005) info.nonBaseCash.push({ currency: r['Currency'], amount: v });
      }
    });
    const acct = r => r['Account'] || info.account || '?';
    (info.openPositions || []).forEach(o => { o.account = o.account || info.account || '?'; });
    const base = (r, line, src) => ({ broker: 'IBKR', account: acct(r), src, line });
    // taxable (05.11.2026): редът може да е облагаем доход / продажба — годината му става „НЕПЪЛНО“ (не само ред в списъка)
    const skip = (sec, r, line, reason, taxable) => skipped.push({ src, line, broker: 'IBKR', account: acct(r), section: sec, what: r['Symbol'] || r['Description'] || '', date: (TC.parseDateTime(r['Date/Time'] || r['Date'] || r['Report Date']) || {}).date || '', reason, taxable: !!taxable });
    rows.forEach(({ sec, r, line }) => {
      if (IBKR_INFO.has(sec) || sec === 'Financial Instrument Information') return;
      if (sec === 'Trades') {
        const disc = r['DataDiscriminator'];
        if (disc && disc !== 'Order' && disc !== 'Trade') return;               // ClosedLot / SubTotal / Total — обобщения на същите сделки
        const cat = IBKR_ASSET[r['Asset Category']];
        const dt = TC.parseDateTime(r['Date/Time']);
        const qty = TC.num(r['Quantity']), proceeds = TC.num(r['Proceeds']), fee = TC.num(r['Comm/Fee']), tprice = TC.num(r['T. Price']);
        if (!cat) return skip(sec, r, line, `непознат вид инструмент „${r['Asset Category']}“`, true);
        if (!dt || !qty) return skip(sec, r, line, 'сделка без дата или количество', true);
        if (cat === 'forex') return skip(sec, r, line, 'обмяна на валута (Forex) — курсовата разлика не се смята (виж предупреждението за валута)');
        if (cat === 'other') return skip(sec, r, line, `${r['Asset Category']} — не се смята от калкулатора`, true);
        const price = isFinite(proceeds) && proceeds !== 0 ? Math.abs(proceeds / qty) : tprice;
        if (!isFinite(price)) return skip(sec, r, line, 'сделка без цена', true);
        recs.push({ ...base(r, line, src), kind: 'trade', sym: r['Symbol'], assetClass: cat, date: dt.date, time: dt.time, qty, price, currency: r['Currency'],
                    fee: isFinite(fee) ? Math.abs(fee) : 0, code: r['Code'] || '' });
        return;
      }
      if (sec === 'Dividends' || sec === 'Payment In Lieu Of Dividends') {
        const dt = TC.parseDateTime(r['Date']), amt = TC.num(r['Amount']), s = TC.ibkrDescSymbol(r['Description']);
        if (!dt || !isFinite(amt)) return;                                     // Total / празни редове
        if (!s) return skip(sec, r, line, 'дивидент без разпознаваем тикър в описанието', true);
        recs.push({ ...base(r, line, src), kind: 'dividend', sym: s.sym, isin: s.isin, date: dt.date, amount: amt, currency: r['Currency'], desc: r['Description'],
                    pil: sec !== 'Dividends' });
        return;
      }
      if (sec === 'Withholding Tax') {
        const dt = TC.parseDateTime(r['Date']), amt = TC.num(r['Amount']), s = TC.ibkrDescSymbol(r['Description']);
        if (!dt || !isFinite(amt)) return;
        if (!s) return skip(sec, r, line, 'удържан данък без тикър (напр. върху лихва) — не е сметнат');
        recs.push({ ...base(r, line, src), kind: 'withholding', sym: s.sym, date: dt.date, amount: amt, currency: r['Currency'], desc: r['Description'] });
        return;
      }
      if (sec === 'Interest') {
        const dt = TC.parseDateTime(r['Date']), amt = TC.num(r['Amount']);
        if (!dt || !isFinite(amt)) return;
        recs.push({ ...base(r, line, src), kind: 'interest', date: dt.date, amount: amt, currency: r['Currency'], desc: r['Description'] });
        return;
      }
      if (sec === 'Corporate Actions') {
        const dt = TC.parseDateTime(r['Date/Time'] || r['Report Date']);
        const m = String(r['Description'] || '').match(/Split\s+(\d+(?:\.\d+)?)\s+for\s+(\d+(?:\.\d+)?)/i);
        const s = TC.ibkrDescSymbol(r['Description']);
        if (!dt) return;
        if (m && s) { recs.push({ ...base(r, line, src), kind: 'split', sym: s.sym, date: dt.date, ratio: Number(m[1]) / Number(m[2]), desc: r['Description'] }); return; }
        return skip(sec, r, line, 'корпоративно действие, което не е сплит (сливане, отделяне, замяна…) — лотовете не са коригирани; сливане с пари е продажба', true);
      }
      if (sec === 'Fees') return skip(sec, r, line, 'такса извън сделките — не се приспада от доходите от капитал (§20 ал. 9 EStG; да се потвърди)');
      if (sec === 'Transfers') return skip(sec, r, line, 'прехвърляне на позиция — цената на придобиване е в отчета на другия брокер');
      skip(sec, r, line, `секцията „${sec}“ не се смята`);
    });
    return { format: 'ibkr', info, records: recs, skipped, instruments };
  };

  // ─── Стандартен CSV (собственият формат на калкулатора) ─────────────────────────────────────────────
  // type: buy | sell | dividend | withholding | interest | split · asset_type: stock | etf | crypto | option | other · по желание: broker, account, fee, eu_exempt, withholding_tax
  TC.parseStandard = function (text, src) {
    const lines = String(text).replace(/^﻿/, '').split(/\r?\n/);
    const recs = [], skipped = [];
    let head = null;
    lines.forEach((line, i) => {
      if (!line.trim() || line.trim().startsWith('#')) return;
      const p = TC.splitCSV(line);
      if (!head) { head = p.map(h => h.toLowerCase()); return; }
      const r = {}; head.forEach((h, k) => { r[h] = p[k] !== undefined ? p[k] : ''; });
      const type = (r.type || '').toLowerCase(), at = (r.asset_type || 'stock').toLowerCase();
      const dt = TC.parseDateTime(r.date), qty = TC.num(r.quantity), price = TC.num(r.price), fee = TC.num(r.fee);
      const b = { broker: r.broker || 'CSV', account: r.account || 'default', src, line: i + 1, currency: (r.currency || 'EUR').toUpperCase(), sym: (r.ticker || '').toUpperCase() };
      const bad = reason => skipped.push({ src, line: i + 1, broker: b.broker, account: b.account, section: 'CSV', what: b.sym, date: dt ? dt.date : r.date, reason, taxable: true });
      if (!dt) return bad('невалидна дата (YYYY-MM-DD)');
      const cls = { stock: 'stock', etf: 'stock', fund: 'stock', crypto: 'crypto', option: 'option' }[at];
      if (type === 'buy' || type === 'sell') {
        if (!cls) return bad(`непознат asset_type „${at}“`);
        if (!(qty > 0) || !isFinite(price)) return bad('невалидно количество или цена');
        recs.push({ ...b, kind: 'trade', assetClass: cls, date: dt.date, time: dt.time, qty: type === 'buy' ? qty : -qty, price, fee: isFinite(fee) ? Math.abs(fee) : 0,
                    fundHint: at === 'etf' || at === 'fund', euExempt: (r.eu_exempt || '').toLowerCase() === 'true' });
      } else if (type === 'dividend') {
        if (!isFinite(qty)) return bad('невалидна сума на дивидента');
        recs.push({ ...b, kind: 'dividend', date: dt.date, amount: qty });
        const wh = TC.num(r.withholding_tax);
        if (wh) recs.push({ ...b, kind: 'withholding', date: dt.date, amount: -Math.abs(wh), line: i + 1 });
      } else if (type === 'withholding') {
        if (!isFinite(qty)) return bad('невалидна сума');
        recs.push({ ...b, kind: 'withholding', date: dt.date, amount: -qty });
      } else if (type === 'interest') {
        if (!isFinite(qty)) return bad('невалидна сума на лихвата');
        recs.push({ ...b, kind: 'interest', date: dt.date, amount: qty, desc: 'interest' });
      } else if (type === 'split') {
        if (!(qty > 0)) return bad('сплит без коефициент (quantity = нови акции за една стара)');
        recs.push({ ...b, kind: 'split', date: dt.date, ratio: qty });
      } else bad(`непознат тип „${r.type}“`);
    });
    if (!head) throw new Error(`${src}: празен файл`);
    return { format: 'standard', info: { broker: 'CSV' }, records: recs, skipped };
  };

  // ─── Курсове на ЕЦБ от файл (eurofxref-hist.csv: Date,USD,JPY,… — единици валута за 1 EUR) ─────────────────────────
  TC.parseECBcsv = function (text) {
    const lines = String(text).replace(/^﻿/, '').split(/\r?\n/).filter(l => l.trim());
    const head = TC.splitCSV(lines[0]).map(h => h.toUpperCase());
    const out = {};
    lines.slice(1).forEach(l => {
      const p = TC.splitCSV(l); const dt = TC.parseDateTime(p[0]); if (!dt) return;
      head.forEach((c, k) => { if (k === 0 || !/^[A-Z]{3}$/.test(c)) return; const v = Number(p[k]); if (v > 0) (out[c] = out[c] || []).push([dt.date, v]); });
    });
    Object.values(out).forEach(a => a.sort((x, y) => x[0].localeCompare(y[0])));
    return out;
  };

  // ─── Всички файлове → записи: разпознаване, дедупликация на застъпващи се отчети ─────────────────────────────────
  TC.recordKey = function (r) {
    const n = v => (v == null || !isFinite(v)) ? '' : Number(v).toFixed(6);
    if (r.kind === 'trade') return ['T', r.broker, r.account, r.sym, r.date, r.time, n(r.qty), n(r.price), r.currency].join('|');
    return [r.kind[0].toUpperCase(), r.broker, r.account, r.sym || '', r.date, n(r.amount), n(r.ratio), r.currency || '', r.desc || ''].join('|');
  };

  // files: [{name, text}] → {files: [описание], records, skipped, rates, warnings}
  // Дедупликация: еднакъв запис в няколко файла (застъпващи се отчети) се брои веднъж; повторение в ЕДИН файл (две еднакви сделки) остава — броят се = максимума по файловете.
  TC.ingest = function (files) {
    const out = { files: [], records: [], skipped: [], rates: {}, info: [], instruments: {}, warnings: [] };
    const perFile = [];
    files.forEach((f, fileIdx) => {
      const fmt = TC.detect(f.text);
      const desc = { name: f.name, format: fmt, broker: '', account: '', from: '', to: '', records: 0, duplicates: 0, skipped: 0, error: null };
      try {
        if (fmt === 'ecb_rates') {
          const r = TC.parseECBcsv(f.text);
          Object.entries(r).forEach(([c, a]) => { out.rates[c] = (out.rates[c] || []).concat(a).sort((x, y) => x[0].localeCompare(y[0])); });
          desc.broker = 'ЕЦБ курсове'; const any = Object.values(r)[0] || []; desc.from = any.length ? any[0][0] : ''; desc.to = any.length ? any[any.length - 1][0] : '';
          desc.records = Object.keys(r).length;
        } else if (fmt === 'ibkr' || fmt === 'standard' || (TC.parsers && TC.parsers[fmt])) {
          const res = fmt === 'ibkr' ? TC.parseIBKR(f.text, f.name) : fmt === 'standard' ? TC.parseStandard(f.text, f.name) : TC.parsers[fmt](f.text, f.name);
          perFile.push({ idx: fileIdx, recs: res.records });
          out.skipped.push(...res.skipped);
          Object.assign(out.instruments, res.instruments || {});
          if (res.info) out.info.push({ file: f.name, ...res.info });
          const dates = res.records.map(r => r.date).sort();
          const accts = [...new Set(res.records.map(r => r.account))];
          Object.assign(desc, { broker: (res.info && res.info.broker) || fmt, account: accts.join(', ') || (res.info && res.info.account) || '', from: dates[0] || '', to: dates[dates.length - 1] || '',
                                records: res.records.length, skipped: res.skipped.length, period: res.info && res.info.period });
        } else {
          desc.error = 'непознат формат — файлът не е сметнат';
          out.skipped.push({ src: f.name, line: 0, section: 'файл', what: f.name, date: '', reason: 'непознат формат (не е IBKR, Revolut, стандартен CSV или курсове на ЕЦБ)' });
        }
      } catch (e) { desc.error = e.message; out.skipped.push({ src: f.name, line: 0, section: 'файл', what: f.name, date: '', reason: 'грешка при четенето: ' + e.message }); }
      out.files.push(desc);
    });
    // дедупликация — по поредния номер на файла, не по името (05.11.2026: два различни файла с едно име се сливаха в един „файл“ и общите записи се броеха двойно)
    const counts = {};                                                         // key → {номер на файла → [records]}
    perFile.forEach(({ idx, recs }) => recs.forEach(r => { const k = TC.recordKey(r); ((counts[k] = counts[k] || {})[idx] = counts[k][idx] || []).push(r); }));
    Object.values(counts).forEach(byFile => {
      const lists = Object.entries(byFile).sort((a, b) => b[1].length - a[1].length || a[0] - b[0]);
      out.records.push(...lists[0][1]);
      lists.slice(1).forEach(([idx, l]) => { out.files[idx].duplicates += l.length; });
    });
    const byName = {};
    files.forEach(f => { (byName[f.name] = byName[f.name] || new Set()).add(f.text); });
    Object.entries(byName).filter(([, t]) => t.size > 1).forEach(([n]) =>
      out.warnings.push(`${t_count(files, n)} файла с име „${n}“ и различно съдържание — сметнати са поотделно; записите, които се повтарят в тях, са броени веднъж (виж колоната „Дубликати“).`));
    // типът на инструмента от IBKR („Financial Instrument Information“ — ETF) важи за всички файлове: застъпващ се отчет без тази секция не губи подсказката
    out.records.forEach(x => { if (x.kind === 'trade' && out.instruments[x.sym] && /ETF|FUND/i.test(out.instruments[x.sym].type)) x.fundHint = true; });
    // „не е сметнато“ — също веднъж за застъпващи се отчети (ключ без името на файла)
    const seenSkip = new Set();
    out.skipped = out.skipped.filter(x => { const k = [x.broker, x.account, x.section, x.what, x.date, x.reason].join('|'); if (x.line && seenSkip.has(k)) return false; seenSkip.add(k); return true; });
    out.records.sort((a, b) => (a.date + (a.time || '')).localeCompare(b.date + (b.time || '')) || (a.kind === 'split' ? -1 : 0) - (b.kind === 'split' ? -1 : 0));
    return out;
  };

  const t_count = (files, n) => files.filter(f => f.name === n).length;

  // ─── Revolut (ПРОВЕРЕН САМО СЪС СИНТЕТИЧЕН ФАЙЛ — по публичното описание на формата; реален отчет може да се различава) ─────────────────────
  // суми с валута: "USD 150.23", "$1,234.56", "€20,000.00", "-€5.00", "150.23" → {v, cur}
  TC.money = function (s, dflt) {
    const t = String(s == null ? '' : s).trim();
    const sym = { '$': 'USD', '€': 'EUR', '£': 'GBP' };
    let cur = dflt || '', m = t.match(/[A-Z]{3}/);
    if (m) cur = m[0]; else { const c = Object.keys(sym).find(k => t.includes(k)); if (c) cur = sym[c]; }
    const v = TC.num(t.replace(/[A-Z]{3}|[$€£]/g, ''));
    return { v, cur };
  };
  const MON = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
  // "2024-01-10T14:32:11.123Z" / "Jan 10, 2024, 10:00:00 AM" / "10 Jan 2024"
  TC.parseLooseDate = function (s) {
    const iso = TC.parseDateTime(s); if (iso) return iso;
    let m = String(s || '').match(/([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})(?:,?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP]M)?)?/);
    if (!m) { const n = String(s || '').match(/(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})/); if (n) m = [n[0], n[2], n[1], n[3]]; }
    if (!m || !MON[m[1].toLowerCase()]) return null;
    let h = Number(m[4] || 0); if (m[7] === 'PM' && h < 12) h += 12; if (m[7] === 'AM' && h === 12) h = 0;
    return { date: `${m[3]}-${String(MON[m[1].toLowerCase()]).padStart(2, '0')}-${String(m[2]).padStart(2, '0')}`, time: m[4] ? `${String(h).padStart(2, '0')}:${m[5]}:${m[6] || '00'}` : '' };
  };
  const rowsOf = text => { const L = String(text).replace(/^﻿/, '').split(/\r?\n/).filter(l => l.trim()); const H = TC.splitCSV(L[0]);
                           return L.slice(1).map((l, i) => { const p = TC.splitCSV(l), r = {}; H.forEach((h, k) => { r[h.trim().toLowerCase()] = p[k] || ''; }); return { r, line: i + 2 }; }); };
  TC.parsers = {
    // акции: Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate
    revolut_stocks(text, src) {
      const recs = [], skipped = [], b = { broker: 'Revolut', account: 'акции', src };
      rowsOf(text).forEach(({ r, line }) => {
        const dt = TC.parseLooseDate(r['date']), type = (r['type'] || '').toUpperCase(), cur = (r['currency'] || '').toUpperCase() || 'USD';
        const price = TC.money(r['price per share'], cur), total = TC.money(r['total amount'], cur), qty = TC.num(r['quantity']);
        const skip = (reason, taxable) => skipped.push({ src, line, broker: 'Revolut', account: 'акции', section: 'Revolut', what: `${r['ticker'] || ''} ${r['type'] || ''}`.trim(), date: dt ? dt.date : r['date'], reason, taxable: !!taxable });
        if (!dt) return skip('без дата', true);
        if (/^(BUY|SELL)/.test(type)) {
          if (!(qty > 0)) return skip('невалидно количество', true);
          const px = isFinite(price.v) && price.v > 0 ? price.v : Math.abs(total.v / qty);
          const fee = isFinite(total.v) && isFinite(price.v) ? Math.max(0, /^BUY/.test(type) ? Math.abs(total.v) - qty * px : qty * px - Math.abs(total.v)) : 0;
          recs.push({ ...b, line, kind: 'trade', assetClass: 'stock', sym: r['ticker'], date: dt.date, time: dt.time, qty: /^BUY/.test(type) ? qty : -qty, price: px,
                      currency: price.cur || total.cur || cur, fee: fee > 1e-6 ? fee : 0 });
        } else if (type === 'DIVIDEND') {
          if (!isFinite(total.v)) return skip('дивидент без сума', true);
          recs.push({ ...b, line, kind: 'dividend', sym: r['ticker'], date: dt.date, amount: total.v, currency: total.cur || cur, desc: 'Revolut DIVIDEND (сумата в отчета — да се провери дали е брутна)' });
        } else if (/CASH TOP-UP|CASH WITHDRAWAL|TRANSFER/.test(type)) {
          return;                                                                 // движение на пари — не е доход
        } else if (/SPLIT/.test(type)) skip('сплит в Revolut — коефициентът не е в отчета; въведи го като ред „split“ в стандартен CSV');
        else if (/FEE/.test(type)) skip('такса извън сделките — не се приспада (§20 ал. 9 EStG; да се потвърди)');
        else skip(`непознат тип „${r['type']}“`, true);
      });
      return { format: 'revolut_stocks', info: { broker: 'Revolut' }, records: recs, skipped };
    },
    // крипто: Symbol,Type,Quantity,Price,Value,Fees,Date
    revolut_crypto(text, src) {
      const recs = [], skipped = [], b = { broker: 'Revolut', account: 'крипто', src };
      rowsOf(text).forEach(({ r, line }) => {
        const dt = TC.parseLooseDate(r['date']), type = (r['type'] || '').toLowerCase(), qty = TC.num(r['quantity']);
        const price = TC.money(r['price'], 'EUR'), value = TC.money(r['value'], price.cur || 'EUR'), fee = TC.money(r['fees'], price.cur || 'EUR');
        const skip = (reason, taxable) => skipped.push({ src, line, broker: 'Revolut', account: 'крипто', section: 'Revolut', what: `${r['symbol'] || ''} ${r['type'] || ''}`.trim(), date: dt ? dt.date : r['date'], reason, taxable: !!taxable });
        if (!dt) return skip('без дата', true);
        if (type === 'buy' || type === 'sell') {
          if (!(qty > 0)) return skip('невалидно количество', true);
          const px = isFinite(price.v) && price.v > 0 ? price.v : Math.abs(value.v / qty);
          recs.push({ ...b, line, kind: 'trade', assetClass: 'crypto', sym: r['symbol'], date: dt.date, time: dt.time, qty: type === 'buy' ? qty : -qty, price: px,
                      currency: price.cur || 'EUR', fee: isFinite(fee.v) ? Math.abs(fee.v) : 0 });
        } else if (/reward|staking|learn/.test(type)) skip('награда / стейкинг — друг доход (§22 т. 3 EStG?), не се смята; да се потвърди', true);
        else if (/send|receive|transfer/.test(type)) skip('прехвърляне между портфейли — цената на придобиване е в другия портфейл');
        else if (/exchange|swap|convert/.test(type)) skip('размяна крипто ↔ крипто — продажба по §23 EStG, не се смята', true);
        else skip(`непознат тип „${r['type']}“`, true);
      });
      return { format: 'revolut_crypto', info: { broker: 'Revolut' }, records: recs, skipped };
    },
    // стар формат на Revolut (Type,Product,Started Date,…) — не се чете; изрично в „не е сметнато“
    revolut_crypto_old(text, src) {
      return { format: 'revolut_crypto_old', info: { broker: 'Revolut' }, records: [], skipped: [{ src, line: 0, broker: 'Revolut', account: '', section: 'файл', what: src, date: '',
               reason: 'старият формат на извлечението на Revolut (Type, Product, Started Date…) не се чете — свали отчета „Crypto account statement“ / „Trading account statement“ (CSV)' }] };
    },
  };

  // ─── Курсове ───────────────────────────────────────────────────────────────
  // таблица {CUR: [[дата, курс], …]} — курс = единици валута за 1 EUR (както ЕЦБ и eurofxref-hist.csv). Сумата в EUR = сума ÷ курс.
  // Ден без курс (уикенд, празник на TARGET) → последният публикуван курс преди него, до maxBack дни назад; по-стар → null (липсва — предупреждение, не NaN).
  TC.rateLookup = function (table, maxBack) {
    const back = maxBack == null ? 10 : maxBack;
    return function (cur, date) {
      if (!cur || cur === 'EUR') return 1;
      const a = (table || {})[cur]; if (!a || !a.length) return null;
      let lo = 0, hi = a.length - 1, ans = -1;
      while (lo <= hi) { const m = (lo + hi) >> 1; if (a[m][0] <= date) { ans = m; lo = m + 1; } else hi = m - 1; }
      if (ans < 0 || a[ans][0] < TC.addDays(date, -back)) return null;
      return a[ans][1];
    };
  };
  // валутите и периодите, за които трябват курсове (всички години — FIFO стига до най-старата покупка)
  TC.ratesNeeded = function (records) {
    const out = {};
    records.forEach(r => { if (!r.currency || r.currency === 'EUR') return; const o = out[r.currency] = out[r.currency] || { from: r.date, to: r.date };
                           if (r.date < o.from) o.from = r.date; if (r.date > o.to) o.to = r.date; });
    Object.values(out).forEach(o => { o.from = TC.addDays(o.from, -10); });
    return out;
  };
  TC.mergeRates = function (table, cur, pairs) {
    const m = new Map((table[cur] || []).map(x => [x[0], x[1]]));
    pairs.forEach(([d, v]) => { if (v > 0) m.set(d, v); });
    table[cur] = [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    return table;
  };
  TC.ecbUrl = (cur, from, to) => `https://data-api.ecb.europa.eu/service/data/EXR/D.${encodeURIComponent(cur)}.EUR.SP00.A?startPeriod=${from}&endPeriod=${to}&format=jsondata`;
  // ECB SDMX-JSON: датите са в structure.dimensions.observation[0].values (по индекс), стойностите — в series[…].observations[индекс][0]
  TC.parseECBjson = function (j) {
    const dates = ((((j || {}).structure || {}).dimensions || {}).observation || [])[0];
    const series = (((j || {}).dataSets || [])[0] || {}).series || {};
    const s = series[Object.keys(series)[0]]; if (!dates || !s) return [];
    return Object.entries(s.observations || {}).map(([i, v]) => [String((dates.values[Number(i)] || {}).id || ''), Number(v[0])]).filter(x => /^\d{4}-\d{2}-\d{2}$/.test(x[0]) && x[1] > 0);
  };
  // frankfurter — ?base=EUR&symbols=CUR → единици CUR за 1 EUR (същата посока като ЕЦБ). До 04.11 посоката беше обърната (сумите — × курс²).
  // 05.11.2026: api.frankfurter.dev — .app пренасочва без CORS заглавия (проверено в истински Chrome) и браузърът спира отговора.
  TC.frankfurterUrl = (cur, from, to) => `https://api.frankfurter.dev/v1/${from}..${to}?base=EUR&symbols=${encodeURIComponent(cur)}`;
  // периодът по календарни години — заявките към ЕЦБ / frankfurter са по година (кратки отговори, повторен опит само за неуспешната година)
  TC.yearChunks = function (from, to) {
    const out = [];
    for (let y = Number(from.slice(0, 4)); y <= Number(to.slice(0, 4)); y++) out.push([y === Number(from.slice(0, 4)) ? from : `${y}-01-01`, y === Number(to.slice(0, 4)) ? to : `${y}-12-31`]);
    return out;
  };
  // покрива ли таблицата периода (последният курс — до 10 дни преди последната дата: уикенд / празници)
  TC.ratesCover = (table, cur, p) => { const a = (table || {})[cur]; return !!(a && a.length && a[0][0] <= p.from && a[a.length - 1][0] >= TC.addDays(p.to, -10)); };
  TC.parseFrankfurter = function (j, cur) {
    const r = (j || {}).rates || {};
    return Object.entries(r).map(([d, o]) => [d, Number((o || {})[cur])]).filter(x => x[1] > 0);
  };

  // ─── FIFO ──────────────────────────────────────────────────────────────────
  // По брокер / сметка / инструмент (крипто — отделно по портфейл); от най-старата покупка, през всички години; комисионните — в цената на покупката и намаляват продажбата.
  // Продажба без покупка (акции, фондове, крипто) → unmatched, без резултат за непокритата част (никога цена 0). Опции: продажба без позиция отваря къса позиция (Stillhalter).
  // Сплит: отворените лотове ×коефициента (цената общо не се мени). Курсът — по датата на всяка сделка (покупка — към деня на покупката, продажба — към деня на продажбата).
  TC.positionKey = r => [r.broker, r.account, r.assetClass === 'crypto' ? 'crypto' : 'sec', r.sym].join('|');

  // opts.stillhalter (05.11.2026): 'receipt' (по подразбиране) — премията е доход в годината на получаване, обратното изкупуване — отрицателен доход в годината на плащане
  // (§20 ал. 1 т. 11 EStG, принципът на изтичане / Zufluss; да се потвърди); 'close' — нетно при затваряне / изтичане (поведението до 05.11).
  TC.fifo = function (records, rate, opts) {
    const stillhalter = ((opts || {}).stillhalter) === 'close' ? 'close' : 'receipt';
    const pos = {}, realized = [], unmatched = [], missingRates = [], incomes = [], notes = [];
    const P = k => (pos[k] = pos[k] || { long: [], short: [], deficit: 0, taintedFrom: null });
    const tainted = {};                                                            // ключ → първата непокрита продажба (резултатите след нея — несигурни)
    const eps = 1e-9;
    records.forEach(r => {
      if (r.kind === 'split') {
        Object.keys(pos).forEach(k => {
          const [b, a, , sym] = k.split('|');
          if (b === r.broker && a === r.account && sym === r.sym) pos[k].long.concat(pos[k].short).forEach(l => { l.qty *= r.ratio; });
        });
        return;
      }
      const fx = rate(r.currency, r.date);
      if (r.kind !== 'trade') {
        if (fx == null) { missingRates.push({ kind: r.kind, sym: r.sym || '', date: r.date, currency: r.currency, src: r.src }); return; }
        incomes.push({ kind: r.kind, broker: r.broker, account: r.account, sym: r.sym || '', date: r.date, year: Number(r.date.slice(0, 4)), currency: r.currency, amount: r.amount,
                       eur: r.amount / fx, rate: fx, desc: r.desc || '', pil: !!r.pil, src: r.src });
        return;
      }
      const k = TC.positionKey(r), p = P(k);
      const qAbs = Math.abs(r.qty);
      if (fx == null) missingRates.push({ kind: 'trade', sym: r.sym, date: r.date, currency: r.currency, src: r.src });
      const eur = v => fx == null ? null : v / fx;
      if (/(^|;)(A|Ex)(;|$)/.test(r.code || '')) notes.push({ sym: r.sym, date: r.date, text: 'упражнена / възложена опция — премията и акциите са сметнати отделно; да се потвърди' });
      const base = { broker: r.broker, account: r.account, sym: r.sym, assetClass: r.assetClass, date: r.date, year: Number(r.date.slice(0, 4)), currency: r.currency,
                     fundHint: !!r.fundHint, euExempt: !!r.euExempt, src: r.src };
      if (r.qty > 0) {                                                             // покупка: първо затваря къси позиции (опции), остатъкът — нов лот
        let q = qAbs;
        // 05.11.2026: след непокрита продажба (акции, фондове, крипто) покупката първо покрива дефицита — не става лот (иначе фантомен лот: при къса продажба
        // покритието ставаше „покупка“ за следващата продажба). Без резултат — непокритата продажба е в unmatched.
        if (p.deficit > eps) { const c = Math.min(p.deficit, q); p.deficit -= c; q -= c; notes.push({ sym: r.sym, date: r.date, text: `покупката покрива ${+c.toFixed(6)} бр. от непокрита продажба — не е лот (без резултат); да се потвърди` }); }
        const feeEUR = eur(r.fee || 0);
        const closed = [];
        while (q > eps && p.short.length) {
          const l = p.short[0], used = Math.min(l.qty, q);
          const recv = l.proceedsEUR == null ? null : l.proceedsEUR * used / l.qty;
          const pay = fx == null ? null : (used * r.price + (r.fee || 0) * used / qAbs) / fx;
          closed.push({ date: l.date, qty: used, proceedsEUR: recv, costEUR: pay });
          if (l.proceedsEUR != null) l.proceedsEUR -= recv;
          l.qty -= used; q -= used;
          if (l.qty <= eps) p.short.shift();
        }
        if (closed.length) {
          const pr = closed.some(c => c.proceedsEUR == null || c.costEUR == null) ? null : closed.reduce((s, c) => s + c.proceedsEUR, 0);
          const co = pr == null ? null : closed.reduce((s, c) => s + c.costEUR, 0);
          realized.push({ ...base, short: true, buyback: stillhalter === 'receipt', qty: qAbs - q, proceedsEUR: pr, costEUR: co, gainEUR: pr == null ? null : pr - co,
                          lots: closed.map(c => ({ date: c.date, qty: c.qty })), openDate: closed[0].date });
        }
        if (q > eps) p.long.push({ qty: q, costEUR: fx == null ? null : (q * r.price + (r.fee || 0) * q / qAbs) / fx, date: r.date, feeEUR: feeEUR == null ? null : feeEUR * q / qAbs });
        return;
      }
      // продажба
      let q = qAbs;
      const proceedsAll = fx == null ? null : (qAbs * r.price - (r.fee || 0)) / fx;
      const lots = [];
      while (q > eps && p.long.length) {
        const l = p.long[0], used = Math.min(l.qty, q);
        const cost = l.costEUR == null ? null : l.costEUR * used / l.qty;
        lots.push({ date: l.date, qty: used, costEUR: cost });
        if (l.costEUR != null) l.costEUR -= cost;
        l.qty -= used; q -= used;
        if (l.qty <= eps) p.long.shift();
      }
      const matched = qAbs - q;
      if (matched > eps) {
        const pr = proceedsAll == null ? null : proceedsAll * matched / qAbs;
        const co = lots.some(x => x.costEUR == null) || pr == null ? null : lots.reduce((s, x) => s + x.costEUR, 0);
        const rec = { ...base, short: false, qty: matched, proceedsEUR: pr, costEUR: co, gainEUR: co == null ? null : pr - co, lots, tainted: !!tainted[k] };
        if (r.assetClass === 'crypto' && co != null) {                             // §23: над една година — освободено; годишнината (същата дата) е още в срока
          let ex = 0, tx = 0;
          lots.forEach(x => { const g = pr * x.qty / matched - x.costEUR; x.exempt = r.date > TC.anniversary(x.date); if (x.exempt) ex += g; else tx += g; });
          rec.exemptGainEUR = ex; rec.taxableGainEUR = tx;
        }
        realized.push(rec);
      }
      if (q > eps) {
        if (r.assetClass === 'option') {                                           // Stillhalter: продажба без позиция отваря къса позиция
          const prem = proceedsAll == null ? null : proceedsAll * q / qAbs;
          if (stillhalter === 'receipt') {                                          // премията — сега; при затварянето остава само цената на обратното изкупуване
            realized.push({ ...base, short: true, premium: true, qty: q, proceedsEUR: prem, costEUR: prem == null ? null : 0, gainEUR: prem, lots: [] });
            p.short.push({ qty: q, proceedsEUR: 0, date: r.date });
          } else p.short.push({ qty: q, proceedsEUR: prem, date: r.date });
        } else {
          unmatched.push({ broker: r.broker, account: r.account, sym: r.sym, date: r.date, year: Number(r.date.slice(0, 4)), qty: q, src: r.src });
          p.deficit += q;
          if (!tainted[k]) tainted[k] = { key: k, broker: r.broker, account: r.account, sym: r.sym, from: r.date };
        }
      }
    });
    const open = Object.entries(pos).map(([k, p]) => ({ key: k, long: p.long.reduce((s, l) => s + l.qty, 0), short: p.short.reduce((s, l) => s + l.qty, 0) }))
      .filter(o => o.long > eps || o.short > eps);
    return { realized, unmatched, missingRates, incomes, open, notes, stillhalter, tainted: Object.values(tainted) };
  };

  // ─── Сверка с наличностите от отчета на IBKR (Open Positions в края на периода) ─────────────────────
  // info: от ingest ([{file, broker, account, periodEnd, openPositions}]); records — всички записи. → [{account, sym, date, year, reported, computed, file}]
  TC.reconcile = function (records, info) {
    const out = [];
    (info || []).filter(i => i.broker === 'IBKR' && i.periodEnd && Array.isArray(i.openPositions)).forEach(i => {
      const held = {};
      (records || []).forEach(r => {
        if (r.broker !== 'IBKR' || r.date > i.periodEnd) return;
        if (r.kind === 'trade' && r.account === i.account) held[r.sym] = (held[r.sym] || 0) + r.qty;
        if (r.kind === 'split' && r.account === i.account && held[r.sym] != null) held[r.sym] *= r.ratio;
      });
      const rep = {}; i.openPositions.filter(o => o.account === i.account).forEach(o => { rep[o.sym] = (rep[o.sym] || 0) + o.qty; });
      [...new Set(Object.keys(held).concat(Object.keys(rep)))].forEach(sym => {
        const a = rep[sym] || 0, b = held[sym] || 0;
        if (Math.abs(a - b) > 1e-6) out.push({ account: i.account, sym, date: i.periodEnd, year: Number(i.periodEnd.slice(0, 4)), reported: a, computed: +b.toFixed(6), file: i.file });
      });
    });
    const seen = new Set();                                                        // застъпващи се отчети с един край — веднъж
    return out.filter(m => { const k = [m.account, m.sym, m.date, m.reported, m.computed].join('|'); if (seen.has(k)) return false; seen.add(k); return true; });
  };

  // ─── Германия: разбивката за декларацията ────────────────────────────────────
  // Не е целият данък: числото най-горе е доходът от капитал за Anlage KAP / KAP-INV след прихващането на загубите (преди Sparer-Pauschbetrag); крипто по §23 — отделно (Anlage SO).
  // Прихващане: загубите от акции — само срещу печалби от акции (отделна „кутия“); другите загуби — срещу всичко. Пренесените загуби (решение на Finanzamt) — по същите правила.
  // settings: year, joint, kirche (null | 'BY' | 'BW' | 'other'), carriedShareLoss, carriedOtherLoss, fundTypes {тикър: вид}, vorab {тикър: EUR}, creditRate (0.15),
  //           persons {"брокер|сметка": 'A' | 'B'}, records (всички записи — за позициите в края на годината), info (от ingest — валутата в сметките)
  TC.LABELS = {
    shareGains: { bg: 'Печалби от продажба на акции', form: 'Anlage KAP — доходи от капитал без германски данък; от тях печалби от акции' },
    shareLosses: { bg: 'Загуби от продажба на акции', form: 'Anlage KAP — загуби от продажба на акции (прихващат се само с печалби от акции)' },
    dividends: { bg: 'Дивиденти (нето след сторно)', form: 'Anlage KAP — доходи от капитал без германски данък' },
    interest: { bg: 'Лихви от брокера (кредитни)', form: 'Anlage KAP — доходи от капитал без германски данък' },
    options: { bg: 'Опции — печалби (вкл. премии на Stillhalter)', form: 'Anlage KAP — доходи от капитал без германски данък (Termingeschäfte / Stillhalterprämien)' },
    optionLosses: { bg: 'Опции — загуби', form: 'Anlage KAP — загуби без загубите от акции' },
    pil: { bg: 'Плащания вместо дивидент (Payment in Lieu)', form: 'Anlage KAP — доходи от капитал без германски данък' },
    funds: { bg: 'Фондове (ETF) — след частичното освобождаване', form: 'Anlage KAP-INV — сумите преди освобождаването, по вид фонд (Finanzamt прилага освобождаването)' },
    fundLosses: { bg: 'Фондове (ETF) — загуби след частичното освобождаване', form: 'Anlage KAP-INV' },
    otherNeg: { bg: 'Други отрицателни (сторно на дивиденти от минала година и др.)', form: 'Anlage KAP — загуби без загубите от акции' },
    withholding: { bg: 'Удържан чужд данък — за зачитане', form: 'Anlage KAP — чужди данъци за зачитане (до 15% от дивидента)' },
    crypto: { bg: 'Крипто — частни продажби (§23 EStG)', form: 'Anlage SO — частни продажби (на човек)' },
  };

  TC.computeDE = function (fifoRes, settings) {
    const st = settings || {};
    const year = Number(st.year);
    const par = TC.deParams(year);
    const tfRates = par.teilfreistellung;                                          // null преди 2018
    const fundType = (sym, hint) => (st.fundTypes || {})[sym] || (hint ? 'equity' : 'stock');
    const tfOf = t => (t === 'stock' || !tfRates) ? 0 : (tfRates[t] || 0);
    const R = fifoRes.realized.filter(x => x.year === year);
    // Vorabpauschale (05.11.2026): st.vorab = {тикър: {година X: EUR}} — сумата за X (всички дялове в края на X) се смята за получена на първия работен ден на X+1
    // (§18 ал. 3 InvStG) → доход в X+1; при продажба печалбата се намалява с Vorabpauschalen за годините, в чийто край продаденият лот е бил държан (§19 ал. 1),
    // пропорционално на броя дялове (сумата ÷ дяловете в края на X; сплит след X — превърнат). Да се потвърди за дялове, купени през годината (там се смята по месеци).
    const recs = st.records || [];
    const unitsAt = (sym, d) => { let q = 0; recs.forEach(r => { if (r.sym !== sym || r.date > d || r.assetClass === 'crypto') return; if (r.kind === 'trade') q += r.qty; else if (r.kind === 'split') q *= r.ratio; }); return q; };
    const splitFactor = (sym, after, upTo) => recs.filter(r => r.kind === 'split' && r.sym === sym && r.date > after && r.date <= upTo).reduce((f, r) => f * r.ratio, 1);
    const vorabOf = sym => { const v = (st.vorab || {})[sym]; return v && typeof v === 'object' ? v : {}; };
    const vorabDeduction = x => {
      let red = 0;
      Object.entries(vorabOf(x.sym)).forEach(([X, amt]) => {
        const end = `${X}-12-31`, a = Number(amt); if (!(a > 0) || !(x.date > end)) return;
        const units = unitsAt(x.sym, end); if (!(units > 1e-9)) return;
        (x.lots || []).forEach(l => { if (l.date <= end) red += a / units * l.qty / splitFactor(x.sym, end, x.date); });
      });
      return red;
    };
    const I = fifoRes.incomes.filter(x => x.year === year);
    const items = [];                                                              // всеки ред от разбивката: {cat, sym, date, eur, gross, note}
    const notes = [];
    const fundsSeen = {};
    R.forEach(x => {
      if (x.gainEUR == null) return;                                               // без курс — в предупрежденията
      if (x.assetClass === 'crypto') return;
      if (x.assetClass === 'option') { items.push({ cat: x.gainEUR >= 0 ? 'options' : 'optionLosses', sym: x.sym, date: x.date, eur: x.gainEUR, gross: x.gainEUR, account: x.account }); return; }
      const ft = fundType(x.sym, x.fundHint);
      if (ft === 'stock') { items.push({ cat: x.gainEUR >= 0 ? 'shareGains' : 'shareLosses', sym: x.sym, date: x.date, eur: x.gainEUR, gross: x.gainEUR, account: x.account }); return; }
      fundsSeen[x.sym] = ft;
      const tf = tfOf(ft);
      const red = vorabDeduction(x);                                               // §19 ал. 1 InvStG: печалбата − Vorabpauschalen за времето на държане
      const g = x.gainEUR - red;
      if (red > 0) notes.push({ level: 'info', text: `${x.sym} (${x.date}): от печалбата при продажбата са приспаднати Vorabpauschalen ${TC.fmt(red)} (§19 ал. 1 InvStG; да се потвърди).` });
      items.push({ cat: g >= 0 ? 'funds' : 'fundLosses', sym: x.sym, date: x.date, eur: g * (1 - tf), gross: g, fundType: ft, tf, account: x.account, vorabDeducted: red });
    });
    // доходи: дивиденти по тикър (нето със сторното), удържан данък по тикър, лихви
    const div = {}, wh = {};
    I.forEach(x => {
      if (x.kind === 'dividend') { const o = div[x.sym + '|' + (x.pil ? 'pil' : 'div')] = div[x.sym + '|' + (x.pil ? 'pil' : 'div')] || { sym: x.sym, pil: x.pil, eur: 0, account: x.account }; o.eur += x.eur; }
      if (x.kind === 'withholding') wh[x.sym] = (wh[x.sym] || 0) + x.eur;
    });
    const instrHint = sym => (fifoRes.realized.find(r => r.sym === sym) || {}).fundHint || ((st.records || []).find(r => r.sym === sym && r.fundHint) ? true : false);
    Object.values(div).forEach(o => {
      if (o.pil) { items.push({ cat: o.eur >= 0 ? 'pil' : 'otherNeg', sym: o.sym, eur: o.eur, gross: o.eur }); return; }
      const ft = fundType(o.sym, instrHint(o.sym));
      if (ft !== 'stock') { fundsSeen[o.sym] = ft; const tf = tfOf(ft); items.push({ cat: o.eur >= 0 ? 'funds' : 'fundLosses', sym: o.sym, eur: o.eur * (1 - tf), gross: o.eur, fundType: ft, tf, distribution: true }); return; }
      items.push({ cat: o.eur >= 0 ? 'dividends' : 'otherNeg', sym: o.sym, eur: o.eur, gross: o.eur });
    });
    const debit = [];
    I.filter(x => x.kind === 'interest').forEach(x => {
      if (x.eur >= 0) items.push({ cat: 'interest', sym: x.desc || 'лихва', date: x.date, eur: x.eur, gross: x.eur });
      else debit.push(x);
    });
    if (debit.length) notes.push({ level: 'info', text: `Дебитна лихва ${TC.fmt(-debit.reduce((s, x) => s + x.eur, 0))} — не се приспада от доходите от капитал (§20 ал. 9 EStG; да се потвърди).` });
    Object.keys(st.vorab || {}).forEach(sym => {                                    // Vorabpauschale за предходната година → доход в тази
      const amt = Number(vorabOf(sym)[year - 1]); if (!(amt > 0)) return;
      const ft = fundType(sym, true); const tf = tfOf(ft); fundsSeen[sym] = ft;
      items.push({ cat: 'funds', sym, date: `${year}-01-02`, eur: amt * (1 - tf), gross: amt, fundType: ft, tf, vorab: true, vorabFor: year - 1 });
    });
    // удържан чужд данък: до creditRate (15%) от брутния дивидент на същия тикър
    const rate = st.creditRate == null ? 0.15 : Number(st.creditRate);
    let withheld = 0, creditable = 0;
    Object.entries(wh).forEach(([sym, v]) => {
      const w = Math.max(0, -v);
      const gross = Object.values(div).filter(o => o.sym === sym && !o.pil).reduce((s, o) => s + o.eur, 0);
      withheld += w; creditable += Math.min(w, Math.max(0, gross) * rate);
    });
    const sum = cat => items.filter(i => i.cat === cat).reduce((s, i) => s + i.eur, 0);
    const shareGains = sum('shareGains'), shareLosses = -sum('shareLosses');
    const otherPos = ['dividends', 'interest', 'options', 'pil', 'funds'].reduce((s, c) => s + sum(c), 0);
    const otherNeg = -['optionLosses', 'fundLosses', 'otherNeg'].reduce((s, c) => s + sum(c), 0);
    const cS = Math.max(0, Number(st.carriedShareLoss) || 0), cO = Math.max(0, Number(st.carriedOtherLoss) || 0);
    let shareNet = shareGains - shareLosses - cS, shareCarry = 0;
    if (shareNet < 0) { shareCarry = -shareNet; shareNet = 0; }
    let total = shareNet + otherPos - otherNeg - cO, otherCarry = 0;
    if (total < 0) { otherCarry = -total; total = 0; }
    // крипто §23 — по човек (сметките, отбелязани като на съпруга / съпругата → 'B')
    const persons = {};
    R.filter(x => x.assetClass === 'crypto').forEach(x => {
      const who = (st.persons || {})[x.broker + '|' + x.account] || 'A';
      const o = persons[who] = persons[who] || { person: who, taxable: 0, exempt: 0, sales: 0, unknown: 0 };
      o.sales++;
      if (x.gainEUR == null) { o.unknown++; return; }
      o.taxable += x.taxableGainEUR || 0; o.exempt += x.exemptGainEUR || 0;
    });
    Object.values(persons).forEach(o => {
      o.freigrenze = par.freigrenze23;
      o.result = o.taxable > 0 && o.taxable < par.freigrenze23 ? 0 : o.taxable;           // Freigrenze (не Freibetrag): под нея — 0; на или над нея — цялата сума
      o.underFreigrenze = o.taxable > 0 && o.taxable < par.freigrenze23;
      o.lossCarry = o.taxable < 0 ? -o.taxable : 0;
    });
    // ориентировъчно: Sparer-Pauschbetrag, Abgeltungsteuer с църковния данък по формулата (e − 4q) / (4 + k), Soli
    const pausch = par.pauschbetrag * (st.joint ? 2 : 1);
    const e = Math.max(0, total - pausch);
    const k = st.kirche ? (TC.KIRCHE_RATES[st.kirche] || TC.KIRCHE_RATES.other) : 0;
    const q = Math.min(creditable, e / 4);
    const tax = Math.max(0, (e - 4 * q) / (4 + k));
    const est = { pauschbetrag: pausch, taxableAfterPausch: e, creditUsed: q, kircheRate: k, abgeltung: tax, soli: tax * par.soli, kirche: tax * k, total: tax * (1 + par.soli + k) };
    // предупреждения
    const yEnd = `${year - 1}-12-31`;                                               // за Vorabpauschale, която е доход в тази година — държаните в края на предходната
    const held = {};
    (st.records || []).forEach(r => {
      if (r.date > yEnd) return;
      const key = TC.positionKey(r);
      if (r.kind === 'trade') held[key] = { sym: r.sym, qty: ((held[key] || {}).qty || 0) + r.qty, hint: r.fundHint, cls: r.assetClass, broker: r.broker, account: r.account };
      if (r.kind === 'split') Object.keys(held).forEach(k2 => { const h = held[k2]; if (h.sym === r.sym && h.broker === r.broker && h.account === r.account) h.qty *= r.ratio; });
    });
    const heldFunds = [...new Set(Object.values(held).filter(h => h.qty > 1e-9 && h.cls === 'stock' && fundType(h.sym, h.hint) !== 'stock').map(h => h.sym))];
    if (heldFunds.length && tfRates && year - 1 >= 2018) notes.push({ level: 'warn', text: `Фондове, държани в края на ${year - 1}: ${heldFunds.join(', ')}. Ако са натрупващи (без изплащане), Vorabpauschale за ${year - 1} се смята за получена на 2 януари ${year} (§18 ал. 3 InvStG) — доход в ${year}; сметни я и я въведи в таблицата с фондовете (колона „за ${year - 1}“). При продажба тя се приспада от печалбата (§19 InvStG). Да се потвърди.` });
    if (!tfRates && Object.keys(fundsSeen).length) notes.push({ level: 'warn', text: `Преди 2018 фондовете се облагат по стария InvStG — частичното освобождаване не е приложено (да се потвърди).` });
    const fx = new Set();
    (st.info || []).forEach(i => (i.nonBaseCash || []).forEach(c => fx.add(c.currency)));
    (st.records || []).forEach(r => { if (r.year === year || (r.date || '').startsWith(String(year))) { if (r.currency && r.currency !== 'EUR') fx.add(r.currency); } });
    if (fx.size) notes.push({ level: 'warn', text: `В сметките има суми във валута (${[...fx].join(', ')}). Курсовите разлики при обмяна или теглене на валута може да са облагаеми (частни продажби по §23 EStG при държане под година) — калкулаторът не ги смята; да се потвърди със счетоводител.` });
    if (items.some(i => i.cat === 'options' || i.cat === 'optionLosses')) notes.push({ level: 'info', text: fifoRes.stillhalter === 'close'
      ? 'Stillhalter: премиите са сметнати нетно при затварянето / изтичането (настройка) — по закона премията е доход в годината на получаване; да се потвърди от счетоводител.'
      : 'Stillhalter: премията е доход в годината на получаване, обратното изкупуване — отрицателен доход в годината на плащане (§20 ал. 1 т. 11 EStG; да се потвърди от счетоводител).' });
    if (items.some(i => i.cat === 'options' || i.cat === 'optionLosses')) notes.push({ level: 'info', text: 'Опции (Termingeschäfte): премиите на Stillhalter и резултатите от затворени / изтекли опции са в „друго“; загубите се прихващат с другите доходи от капитал (ограничението до 20 000 € от 2021 г. е отменено — да се потвърди за годината). Упражнени / възложени опции — виж бележките.' });
    if (par.extrapolated) notes.push({ level: 'warn', text: `Параметрите за ${year} не са проверени (таблицата е до ${TC.DE_PARAMS_CHECKED_UNTIL}) — ползвани са последните известни; провери ги.` });
    if ((fifoRes.notes || []).some(n => n.date.startsWith(String(year)))) fifoRes.notes.filter(n => n.date.startsWith(String(year))).forEach(n => notes.push({ level: 'warn', text: `${n.sym} (${n.date}): ${n.text}` }));
    const unmatched = (fifoRes.unmatched || []).filter(u => u.year === year);
    // 05.11.2026: несигурни резултати — продажби след непокрита продажба на същата позиция (и в следващите години) и разлики с наличностите в отчета на IBKR
    const taintedSales = R.filter(x => x.tainted);
    [...new Set(taintedSales.map(x => x.sym))].forEach(sym => {
      const t = (fifoRes.tainted || []).find(z => z.sym === sym);
      notes.push({ level: 'err', text: `${sym}: продажби в ${year} след непокрита продажба (${t ? t.from : '?'}) — цената на придобиване може да е грешна (липсващ по-стар отчет?). НЕПЪЛНО.` });
    });
    const mism = TC.reconcile(st.records, st.info).filter(m => m.year === year || (m.year < year && R.some(x => x.broker === 'IBKR' && x.account === m.account && x.sym === m.sym)));
    // 05.11.2026: редове от „не е сметнато“ в тази година, които може да са облагаеми (размяна на крипто, сливане с пари, фючърси, нечетим ред…)
    const skippedTaxable = (st.skipped || []).filter(x => x.taxable && String(x.date || '').startsWith(String(year)));
    if (skippedTaxable.length) notes.push({ level: 'err', text: `В „не е сметнато“ има ${skippedTaxable.length} ред(а) от ${year}, които може да са облагаеми (${[...new Set(skippedTaxable.map(x => x.what))].slice(0, 6).join(', ')}) — сметни ги отделно. НЕПЪЛНО.` });
    mism.forEach(m => notes.push({ level: 'err', text: `${m.sym} (${m.account}): в края на ${m.date} отчетът на IBKR показва ${m.reported} бр., сметнатите сделки — ${m.computed} бр. (липсва отчет или ред?). НЕПЪЛНО.` }));
    const missing = (fifoRes.missingRates || []).filter(m => m.date.startsWith(String(year)) || (R.some(x => x.gainEUR == null && x.sym === m.sym)));
    return {
      year, params: par, headline: total > 0 ? total : -(shareCarry + otherCarry), total, shareGains, shareLosses, shareNet, shareCarry, otherPos, otherNeg, otherCarry,
      carriedShareLoss: cS, carriedOtherLoss: cO, withheld, creditable, items, crypto: Object.values(persons).sort((a, b) => a.person.localeCompare(b.person)),
      estimate: est, notes, unmatched, missingRates: missing, funds: fundsSeen, heldFunds,
      complete: !unmatched.length && !missing.length && !taintedSales.length && !mism.length && !skippedTaxable.length, reconcile: mism, skippedTaxable,
    };
  };

  // ─── България (изключена в страницата — SHOW_BG = false; кодът остава от старата версия, само върху новите записи) ─────────────────────
  TC.computeBG = function (fifoRes, year) {
    const R = fifoRes.realized.filter(x => x.year === year && x.gainEUR != null), I = fifoRes.incomes.filter(x => x.year === year);
    const taxableStock = R.filter(x => x.assetClass !== 'crypto' && !x.euExempt).reduce((s, x) => s + x.gainEUR, 0);
    const exemptStock = R.filter(x => x.assetClass !== 'crypto' && x.euExempt).reduce((s, x) => s + x.gainEUR, 0);
    const cryptoGain = R.filter(x => x.assetClass === 'crypto').reduce((s, x) => s + x.gainEUR, 0);
    const div = I.filter(x => x.kind === 'dividend').reduce((s, x) => s + x.eur, 0), wh = -I.filter(x => x.kind === 'withholding').reduce((s, x) => s + x.eur, 0);
    const divRaw = Math.max(0, div) * 0.05, divCredit = Math.min(Math.max(0, wh), divRaw);
    return { taxableStock, exemptStock, cryptoGain, dividends: div, stockTax: Math.max(0, taxableStock) * 0.10, cryptoTax: Math.max(0, cryptoGain) * 0.10, divTax: divRaw - divCredit };
  };

  TC.fmt = n => (n < 0 ? '−' : '') + Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' €';

  root.TaxCore = TC;
  if (typeof module !== 'undefined' && module.exports) module.exports = TC;
})(typeof window !== 'undefined' ? window : globalThis);
