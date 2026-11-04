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
    const head = {}, recs = [], skipped = [], info = { broker: 'IBKR', account: '', period: '', baseCurrency: '', nonBaseCash: [] };
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
    rows.forEach(({ sec, r }) => {
      if (sec === 'Statement' && r['Field Name'] === 'BrokerName') info.brokerName = r['Field Value'];
      if (sec === 'Statement' && r['Field Name'] === 'Period') info.period = r['Field Value'];
      if (sec === 'Account Information' && r['Field Name'] === 'Account') info.account = (r['Field Value'] || '').split(/\s/)[0];
      if (sec === 'Account Information' && r['Field Name'] === 'Base Currency') info.baseCurrency = r['Field Value'];
      if (sec === 'Financial Instrument Information' && r['Symbol']) instruments[r['Symbol']] = { type: r['Type'] || '', category: r['Asset Category'] || '', desc: r['Description'] || '' };
      if (sec === 'Cash Report' && /Ending Cash/i.test(r['Currency Summary'] || '') && r['Currency'] && r['Currency'] !== 'Base Currency Summary' && r['Currency'] !== (info.baseCurrency || 'EUR')) {
        const v = TC.num(r['Total']); if (v && Math.abs(v) > 0.005) info.nonBaseCash.push({ currency: r['Currency'], amount: v });
      }
    });
    const acct = r => r['Account'] || info.account || '?';
    const base = (r, line, src) => ({ broker: 'IBKR', account: acct(r), src, line });
    const skip = (sec, r, line, reason) => skipped.push({ src, line, broker: 'IBKR', account: acct(r), section: sec, what: r['Symbol'] || r['Description'] || '', date: (TC.parseDateTime(r['Date/Time'] || r['Date'] || r['Report Date']) || {}).date || '', reason });
    rows.forEach(({ sec, r, line }) => {
      if (IBKR_INFO.has(sec) || sec === 'Financial Instrument Information') return;
      if (sec === 'Trades') {
        const disc = r['DataDiscriminator'];
        if (disc && disc !== 'Order' && disc !== 'Trade') return;               // ClosedLot / SubTotal / Total — обобщения на същите сделки
        const cat = IBKR_ASSET[r['Asset Category']];
        const dt = TC.parseDateTime(r['Date/Time']);
        const qty = TC.num(r['Quantity']), proceeds = TC.num(r['Proceeds']), fee = TC.num(r['Comm/Fee']), tprice = TC.num(r['T. Price']);
        if (!cat) return skip(sec, r, line, `непознат вид инструмент „${r['Asset Category']}“`);
        if (!dt || !qty) return skip(sec, r, line, 'сделка без дата или количество');
        if (cat === 'forex') return skip(sec, r, line, 'обмяна на валута (Forex) — курсовата разлика не се смята (виж предупреждението за валута)');
        if (cat === 'other') return skip(sec, r, line, `${r['Asset Category']} — не се смята от калкулатора`);
        const price = isFinite(proceeds) && proceeds !== 0 ? Math.abs(proceeds / qty) : tprice;
        if (!isFinite(price)) return skip(sec, r, line, 'сделка без цена');
        recs.push({ ...base(r, line, src), kind: 'trade', sym: r['Symbol'], assetClass: cat, date: dt.date, time: dt.time, qty, price, currency: r['Currency'],
                    fee: isFinite(fee) ? Math.abs(fee) : 0, code: r['Code'] || '' });
        return;
      }
      if (sec === 'Dividends' || sec === 'Payment In Lieu Of Dividends') {
        const dt = TC.parseDateTime(r['Date']), amt = TC.num(r['Amount']), s = TC.ibkrDescSymbol(r['Description']);
        if (!dt || !isFinite(amt)) return;                                     // Total / празни редове
        if (!s) return skip(sec, r, line, 'дивидент без разпознаваем тикър в описанието');
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
        return skip(sec, r, line, 'корпоративно действие, което не е сплит (сливане, отделяне, замяна…) — лотовете не са коригирани');
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
      const bad = reason => skipped.push({ src, line: i + 1, broker: b.broker, account: b.account, section: 'CSV', what: b.sym, date: dt ? dt.date : r.date, reason });
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
    const out = { files: [], records: [], skipped: [], rates: {}, info: [], instruments: {} };
    const perFile = [];
    files.forEach(f => {
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
          perFile.push({ name: f.name, recs: res.records });
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
    // дедупликация
    const counts = {};                                                         // key → {file → [records]}
    perFile.forEach(({ name, recs }) => recs.forEach(r => { const k = TC.recordKey(r); ((counts[k] = counts[k] || {})[name] = counts[k][name] || []).push(r); }));
    Object.values(counts).forEach(byFile => {
      const lists = Object.values(byFile).sort((a, b) => b.length - a.length);
      out.records.push(...lists[0]);
      lists.slice(1).forEach(l => { const d = out.files.find(x => x.name === l[0].src); if (d) d.duplicates += l.length; });
    });
    // типът на инструмента от IBKR („Financial Instrument Information“ — ETF) важи за всички файлове: застъпващ се отчет без тази секция не губи подсказката
    out.records.forEach(x => { if (x.kind === 'trade' && out.instruments[x.sym] && /ETF|FUND/i.test(out.instruments[x.sym].type)) x.fundHint = true; });
    // „не е сметнато“ — също веднъж за застъпващи се отчети (ключ без името на файла)
    const seenSkip = new Set();
    out.skipped = out.skipped.filter(x => { const k = [x.broker, x.account, x.section, x.what, x.date, x.reason].join('|'); if (x.line && seenSkip.has(k)) return false; seenSkip.add(k); return true; });
    out.records.sort((a, b) => (a.date + (a.time || '')).localeCompare(b.date + (b.time || '')) || (a.kind === 'split' ? -1 : 0) - (b.kind === 'split' ? -1 : 0));
    return out;
  };

  root.TaxCore = TC;
  if (typeof module !== 'undefined' && module.exports) module.exports = TC;
})(typeof window !== 'undefined' ? window : globalThis);
