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

  TC.splitCSV = function (line, delim) {
    const d = delim || ',';
    const out = []; let cur = '', q = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++; } else q = !q; continue; }
      if (c === d && !q) { out.push(cur); cur = ''; continue; }
      cur += c;
    }
    out.push(cur);
    return out.map(s => s.trim());
  };

  // числа: "1,234.56" / "1,234" (хиляди със запетая — форматът на брокерите) → 1234.56 / 1234; 05.11.2026: десетична запетая — "0,125" → 0.125 (до 05.11 → 125),
  // "1,5" → 1.5, "1.234,56" → 1234.56; decimalComma (файл с „;“ — немски Excel) — запетаята винаги е десетична. Двусмислено остава само "1,234" (= 1234). Празно / нечисло → NaN
  TC.num = function (s, decimalComma) {
    if (s == null) return NaN;
    let t = String(s).replace(/["\s\u00a0]/g, '');
    if (t === '' || t === '--') return NaN;
    if (decimalComma) t = t.replace(/\./g, '').replace(',', '.');
    else if (/^[-+]?[1-9]\d{0,2}(,\d{3})+(\.\d+)?$/.test(t)) t = t.replace(/,/g, '');
    else if (/^[-+]?\d{1,3}(\.\d{3})+,\d+$/.test(t)) t = t.replace(/\./g, '').replace(',', '.');
    else if (/^[-+]?\d+,\d+$/.test(t)) t = t.replace(',', '.');
    return Number(t);
  };
  TC.delimOf = first => (first.includes(';') && !first.includes(',')) ? ';' : ',';

  // дата/час: "2024-01-10, 10:00:00", "2024-01-10;10:00:00", "20240110;100000", "2024-01-10" → {date, time}
  TC.parseDateTime = function (s) {
    const m = String(s || '').match(/(\d{4})-?(\d{2})-?(\d{2})(?:[,;T ]+\s*(\d{2}):?(\d{2}):?(\d{2})?(?:\.(\d{1,6}))?)?/);
    if (!m) return null;                                                          // милисекундите (Revolut) остават в часа — две поръчки в една секунда не са дубликат
    return { date: `${m[1]}-${m[2]}-${m[3]}`, time: m[4] ? `${m[4]}:${m[5]}:${m[6] || '00'}${m[7] ? '.' + m[7] : ''}` : '' };
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
    if (/^PK\u0003\u0004/.test(t)) return 'xlsx';                                 // 13.11.2026: Excel (zip) — не е текст; не се чете, но се казва какво е (преди: „непознат формат“ с боклук като първи ред)
    const first = t.split(/\r?\n/).find(l => l.trim()) || '';
    if (/^Statement,Header,/.test(first) || /Statement,Data,BrokerName,Interactive Brokers/.test(t)) return 'ibkr';
    const h = TC.splitCSV(first, TC.delimOf(first)).map(x => x.toLowerCase());
    // 13.11.2026: резултат на ДРУГА данъчна програма („Fiscal Year“, Broker, Acquisition Date / Dividend Date …) — не е отчет на брокер; реален формат от файловете на потребителя
    if (h.includes('fiscal year') && h.includes('broker') && (h.includes('acquisition date') || h.includes('dividend date'))) return 'taxtool_result';
    if (h[0] === 'date' && h.length > 3 && h.slice(1).filter(x => x).every(x => /^[a-z]{3}$/.test(x))) return 'ecb_rates';
    if (['type', 'ticker', 'date', 'quantity', 'currency'].every(c => h.includes(c)) && h.includes('price') && !h.includes('price per share')) return 'standard';
    if (h.includes('ticker') && h.includes('price per share') && h.includes('total amount')) return 'revolut_stocks';
    if (h.includes('date acquired') && h.includes('date sold') && h.includes('cost basis') && h.includes('realised pnl')) return 'revolut_pnl';   // 14.11.2026: „Profit and loss“ на Revolut — РЕАЛЕН формат (заглавният ред е от файл на потребителя)
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
    'Change in Position Value', 'Dividend Accruals', 'Complex Position Summary', 'Trade Summary by Asset', 'Commission Details',
    'Deposits & Withdrawals', 'Deposits And Withdrawals']);                    // вноски / тегления на пари — не са доход (05.11.2026: бяха шум в „не е сметнато“)

  // 12.11.2026: секциите, от които идват сделките и доходите, и колоните, по които се четат (по ИМЕ от заглавния ред) — за съобщението „не намерих сделки“
  // (какво очаквах) и за проверката „липсват колони“. [a, b] = поне едната от двете.
  TC.IBKR_EXPECTED = {
    'Trades': ['Asset Category', 'Currency', 'Symbol', 'Date/Time', 'Quantity', ['Proceeds', 'T. Price']],
    'Dividends': ['Currency', 'Date', 'Description', 'Amount'],
    'Withholding Tax': ['Currency', 'Date', 'Description', 'Amount'],
    'Interest': ['Currency', 'Date', 'Description', 'Amount'],
  };
  // номер на сметка → маскиран за показване: „U1234567“ → „U••••567“ (първият знак и последните три); име без поне 4 цифри (Revolut „акции“, „default“) остава
  TC.maskAccount = function (a) { const t = String(a == null ? '' : a); return (t.match(/\d/g) || []).length < 4 ? t : t[0] + '•'.repeat(Math.max(1, t.length - 4)) + t.slice(-3); };

  // тикърът в началото на описание на IBKR: "AAPL(US0378331005) Cash Dividend…" и "AAPL (US0378331005) …"
  TC.ibkrDescSymbol = function (desc) { const m = String(desc || '').match(/^\s*([A-Z0-9][A-Z0-9.\- ]*?)\s*\(([A-Z]{2}[A-Z0-9]{9}\d)\)/); return m ? { sym: m[1].trim(), isin: m[2] } : null; };

  // ─── Корпоративни действия на IBKR (13.11.2026) ───
  // Описанието: „СИМВОЛ(ISIN) текст (СИМВОЛ2, ИМЕ, ISIN2)“. ФОРМАТЪТ Е ПРОВЕРЕН САМО ЗА СПЛИТ (реални отчети); останалите видове са по публичното описание на IBKR — непознато → червено + ръчно потвърждение.
  TC.parseCA = function (desc) {
    const d = String(desc || '').trim(), head = TC.ibkrDescSymbol(d);
    if (!head) return null;
    let body = d.replace(/^\s*[A-Z0-9][A-Z0-9.\- ]*?\s*\([A-Z]{2}[A-Z0-9]{9}\d\)\s*/, ''), sym2 = '', isin2 = '';
    const t = body.match(/\(([^(),]+),\s*(.+?),\s*([A-Z]{2}[A-Z0-9]{9}\d)\)\s*$/);
    if (t) { sym2 = t[1].trim(); isin2 = t[3]; body = body.slice(0, t.index).trim(); }
    return { sym: head.sym, isin: head.isin, body, sym2, isin2 };
  };
  TC.caType = function (body, qty, proceeds) {
    const b = String(body || '');
    if (/\bSplit\s+\d/i.test(b)) return 'split';
    if (/Stock\s+Dividend/i.test(b)) return 'stockdiv';
    if (/Spin[\s-]?off/i.test(b)) return 'spinoff';
    if (/\bRights?\b|Subscri/i.test(b)) return 'rights';
    if (/Delist|Worthless|Bankrupt|Expir/i.test(b) && !(proceeds > 0)) return 'delist';
    if (/Cash\s+Merger|Cash\s+in\s+Lieu|Fractional|Tender|Buy-?out|Redemption|Cash\s+Payment/i.test(b) || (/Merge|Acqui/i.test(b) && proceeds > 0)) return 'cash';
    if (/Merge|Acqui|Name\s+Change|Symbol\s+Change|ISIN\s+Change|CUSIP|Exchange|Conversion|Reorg|Redenom/i.test(b)) return 'exchange';
    return 'unknown';
  };
  // Редовете на едно събитие (същата сметка, дата и час): стар инструмент (количество < 0) ↔ нов (количество > 0) → размяна; пари → продажба; само нов → отделяне / дивидент в акции;
  // непознат вид → „не е сметнато“ (червено) с ключ за ръчно потвърждение. → {records, skipped, events}; events — за бележките (спорното е отбелязано).
  TC.resolveCorp = function (rows) {
    const out = [], skipped = [], events = [], groups = {};
    rows.forEach(r => { (groups[[r.broker, r.account, r.date, r.time].join('|')] = groups[[r.broker, r.account, r.date, r.time].join('|')] || []).push(r); });
    const base = r => ({ broker: r.broker, account: r.account, src: r.src, line: r.line, date: r.date, time: r.time, currency: r.currency, owner: r.owner });
    const unknown = (r, why) => skipped.push({ src: r.src, line: r.line, broker: r.broker, account: r.account, section: 'Corporate Actions', what: r.sym, date: r.date, amount: String(r.qty), taxable: true, reason: why,
                                                  ackKey: ['ack', r.broker, r.account, r.sym, r.date, r.qty].join('|'), desc: r.desc });
    const ev = (type, r, extra) => events.push({ type, sym: r.sym, date: r.date, account: r.account, desc: r.desc, ...(extra || {}) });
    Object.values(groups).forEach(g => {
      const used = new Set(), rem = g.filter(r => r.qty < 0), add = g.filter(r => r.qty > 0);
      // двуредов (обратен) сплит и размяна: ред със „Split“ без съответстващ ред — обикновен сплит (коефициент от текста)
      rem.forEach(r => {
        const a = add.find(x => !used.has(x) && (x.sym !== r.sym || x.isin !== r.isin) && ['split', 'exchange'].includes(x.ctype) && ['split', 'exchange', 'cash'].includes(r.ctype));
        if (a) {
          used.add(r); used.add(a);
          const N = -r.qty;
          if (r.proceeds > 0) {                                                  // смесено: парите — продажба на дял от лотовете (по стойност), остатъкът — към новите акции
            if (!(a.value > 0)) { unknown(r, 'сливане с пари и акции без стойност на новите акции в отчета — не може да се раздели; потвърди ръчно'); return; }
            const f = r.proceeds / (r.proceeds + a.value), sold = N * f, kept = N - sold;
            out.push({ ...base(r), kind: 'trade', sym: r.sym, assetClass: 'stock', qty: -sold, price: r.proceeds / sold, fee: 0, code: 'corp-cash', corpNote: r.desc });
            out.push({ ...base(r), kind: 'exchange', sym: r.sym, newSym: a.sym, qtyOld: kept, factor: a.qty / kept, desc: r.desc, ctype: 'mixed' });
            ev('mixed', r, { newSym: a.sym, disputed: true, why: `сливане с пари и акции: парите (${r.proceeds} ${r.currency}) са продажба на ${+(f * 100).toFixed(1)}% от лотовете (по стойност), остатъкът — размяна към ${a.sym}` });
          } else {
            out.push({ ...base(r), kind: 'exchange', sym: r.sym, newSym: a.sym, qtyOld: N, factor: a.qty / N, desc: r.desc, ctype: r.ctype === 'split' || a.ctype === 'split' ? 'reverse_split' : (r.sym2 === a.sym || a.sym2 === a.sym) && r.isin === a.isin ? 'rename' : 'merger' });
            ev(r.ctype === 'split' || a.ctype === 'split' ? 'reverse_split' : 'exchange', r, { newSym: a.sym, factor: +(a.qty / N).toFixed(8), disputed: false });
          }
        }
      });
      g.forEach(r => {
        if (used.has(r)) return;
        if (r.ctype === 'split') { out.push(r); return; }                          // обикновен сплит (kind 'split')
        if (r.qty < 0) {
          if (r.proceeds > 0 || r.ctype === 'cash') {
            if (!(r.proceeds > 0)) return unknown(r, 'сливане / изкупуване без пари в отчета — потвърди ръчно');
            const frac = /Lieu|Fractional/i.test(r.body);
            out.push({ ...base(r), kind: 'trade', sym: r.sym, assetClass: 'stock', qty: r.qty, price: r.proceeds / -r.qty, fee: 0, code: 'corp-cash', corpNote: r.desc });
            ev(frac ? 'cash_in_lieu' : 'cash', r, { disputed: frac, why: frac ? 'фракции, платени в брой (Spitzenausgleich) — смятани като продажба на тези акции' : '' });
          } else if (r.ctype === 'delist') {
            out.push({ ...base(r), kind: 'trade', sym: r.sym, assetClass: 'stock', qty: r.qty, price: 0, fee: 0, code: 'corp-worthless', corpNote: r.desc });
            ev('worthless', r, { disputed: true, why: 'делистинг / безценност — смятано като продажба за 0 (загуба = покупната цена); да се потвърди третирането (§20 ал. 6 EStG)' });
          } else unknown(r, `корпоративно действие „${r.body.slice(0, 40)}“ с намаление на позицията без съответстващ нов инструмент — потвърди ръчно`);
          return;
        }
        if (r.qty > 0) {
          if (r.ctype === 'spinoff') { out.push({ ...base(r), kind: 'spinoff', sym: r.sym, qty: r.qty, value: r.value, desc: r.desc }); ev('spinoff', r, { disputed: true, why: 'отделяне на компания — новите акции са без цена от отчета; покупната цена се въвежда на ръка или се смята 0 (настройка)' }); return; }
          if (r.ctype === 'stockdiv') { out.push({ ...base(r), kind: 'stockdiv', sym: r.sym, qty: r.qty, value: r.value, desc: r.desc }); ev('stockdiv', r, { disputed: true, why: 'дивидент в акции — по подразбиране като безплатни акции (без доход, цената общо не се мени); настройка: доход по пазарна стойност' }); return; }
          return unknown(r, r.ctype === 'rights' ? 'права (rights) — не се смятат; потвърди ръчно' : `корпоративно действие „${r.body.slice(0, 40)}“ — нов инструмент без съответстващо намаление на стария — потвърди ръчно`);
        }
        unknown(r, r.ctype === 'rights' ? 'права (rights) — не се смятат; потвърди ръчно' : `корпоративно действие „${r.body.slice(0, 40)}“ без количество — потвърди ръчно`);
      });
    });
    return { records: out, skipped, events };
  };

  TC.parseIBKR = function (text, src) {
    const lines = String(text).replace(/^﻿/, '').split(/\r?\n/);
    const head = {}, recs = [], skipped = [], info = { broker: 'IBKR', account: '', period: '', periodEnd: '', baseCurrency: '', nonBaseCash: [], openPositions: null };
    const instruments = {};
    const rows = [];
    // 12.11.2026 (никога тиха нула): сметка на ВСЕКИ ред с данни по секции — data = records + skipped + ignored (с причината в why); нищо не изчезва без следа.
    // headers — заглавните редове, както са във файла; rowTypes — видовете редове (Header / Data / SubTotal / Total …); disc — Trades по вид ред × вид инструмент.
    const secs = {}, order = [];
    let junk = 0;
    const S = name => { if (!secs[name]) { secs[name] = { name, data: 0, records: 0, skipped: 0, ignored: 0, why: {}, headers: [], rowTypes: {}, disc: {}, missing: [], wider: 0, narrower: 0, widths: {} }; order.push(name); } return secs[name]; };
    const bump = (o, k) => { o[k] = (o[k] || 0) + 1; };
    const ign = (sec, why) => { const st = S(sec); st.ignored++; bump(st.why, why); };
    lines.forEach((line, i) => {
      if (!line.trim()) return;
      const p = TC.splitCSV(line);
      if (p.length < 2 || !p[0]) { junk++; return; }                             // ред извън формата „секция,вид,…“
      const sec = p[0], typ = p[1];
      const st = S(sec); bump(st.rowTypes, typ || '(празно)');
      if (typ === 'Header') { head[sec] = p.slice(2); if (!st.headers.some(h => h.join('\u0001') === head[sec].join('\u0001'))) st.headers.push(head[sec]); return; }
      if (typ !== 'Data') return;                                                // SubTotal / Total / Notes — обобщения (броят се в rowTypes)
      st.data++;
      if (!head[sec]) { rows.push({ sec, r: {}, line: i + 1, raw: line, noHeader: true }); return; }
      // ред с данни с различен брой клетки от заглавния ред (без обобщенията Total): повече клетки → стойностите попадат под грешно име (изместени колони)
      const nCells = p.length - 2, hLen = head[sec].length;
      if (nCells !== hLen && !p.slice(2, 4).some(v => /^Total\b/i.test(String(v || '').trim()))) { if (nCells > hLen) st.wider++; else st.narrower++; bump(st.widths, `${nCells} вместо ${hLen}`); }
      const r = {}; head[sec].forEach((h, k) => { r[h] = p[k + 2] !== undefined ? p[k + 2] : ''; });
      rows.push({ sec, r, line: i + 1, raw: line });
    });
    Object.entries(TC.IBKR_EXPECTED).forEach(([sec, need]) => { const st = secs[sec]; if (!st) return;
      st.headers.forEach(h => { const miss = need.filter(c => !(Array.isArray(c) ? c.some(x => h.includes(x)) : h.includes(c))).map(c => Array.isArray(c) ? c.join(' или ') : c); if (miss.length) st.missing.push(...miss.filter(m => !st.missing.includes(m))); }); });
    if (head['Open Positions']) info.openPositions = [];
    // 13.11.2026 (истински комбиниран отчет за 2024): в един файл има няколко блока „Statement“, всеки със СВОЯ „Account Information“, а в Trades / Open Positions
    // няма колона Account. Сметката на реда е тази от последния „Account Information“ ПРЕДИ него във файла (до 13.11 — последната във файла за всички редове → 45 сделки
    // на едната сметка отиваха към другата). info.accounts — сметките по ред на срещане (за сверката с Open Positions по сметка).
    let blockAcct = '';
    info.accounts = [];
    // 13.11.2026 (контроли по началните / крайните позиции): началото на периода и позициите по сметка от „Mark-to-Market Performance Summary“ (Prior / Current Quantity) — само акции и фондове
    info.periodStart = ''; info.hasMTM = false; info.hasPrior = false; info.hasCurrent = false; info.startPositions = {}; info.currentPositions = {};
    rows.forEach(({ sec, r }) => {
      if (sec === 'Statement' && r['Field Name'] === 'BrokerName') info.brokerName = r['Field Value'];
      if (sec === 'Statement' && r['Field Name'] === 'Period') { const s0 = TC.parseLooseDate(String(r['Field Value'] || '').split(/\s+-\s+/)[0]); info.periodStart = s0 ? s0.date : info.periodStart; info.period = r['Field Value']; const e = TC.parseLooseDate(String(r['Field Value'] || '').split(/\s+-\s+/).pop()); info.periodEnd = e ? e.date : ''; }
      // 05.11.2026: наличностите в края на периода — за сверка с FIFO (липсващ по-стар отчет, пропуснат ред); само обобщените редове (Summary), не лотовете
      if (sec === 'Open Positions' && (!r['DataDiscriminator'] || r['DataDiscriminator'] === 'Summary') && IBKR_ASSET[r['Asset Category']] && !['forex', 'other'].includes(IBKR_ASSET[r['Asset Category']])) {
        const q = TC.num(r['Quantity']); if (isFinite(q)) info.openPositions.push({ account: r['Account'] || blockAcct, sym: r['Symbol'], qty: q });
      }
      if (sec === 'Mark-to-Market Performance Summary') {
        info.hasMTM = true;
        const mc = IBKR_ASSET[r['Asset Category']], ma = blockAcct || '?';
        if ((mc === 'stock' || mc === 'fund') && r['Symbol']) {
          // само ако колоната я има в заглавния ред: без „Prior Quantity“ няма начален контрол, без „Current Quantity“ — краен (липсваща колона НЕ е нула)
          const sp = (info.startPositions[ma] = info.startPositions[ma] || {}), cp = (info.currentPositions[ma] = info.currentPositions[ma] || {});
          if ('Prior Quantity' in r) { info.hasPrior = true; const pq = TC.num(r['Prior Quantity']); sp[r['Symbol']] = (sp[r['Symbol']] || 0) + (isFinite(pq) ? pq : 0); }
          if ('Current Quantity' in r) { info.hasCurrent = true; const cq = TC.num(r['Current Quantity']); cp[r['Symbol']] = (cp[r['Symbol']] || 0) + (isFinite(cq) ? cq : 0); }
        }
      }
      if (sec === 'Account Information' && r['Field Name'] === 'Account') {
        info.account = (r['Field Value'] || '').split(/\s/)[0];
        blockAcct = info.account;
        if (blockAcct && !info.accounts.includes(blockAcct)) info.accounts.push(blockAcct);
      }
      if (sec === 'Account Information' && r['Field Name'] === 'Base Currency') info.baseCurrency = r['Field Value'];
      if (sec === 'Financial Instrument Information' && r['Symbol']) instruments[r['Symbol']] = { type: r['Type'] || '', category: r['Asset Category'] || '', desc: r['Description'] || '', conid: r['Conid'] || '', isin: r['Security ID'] || '' };
      if (sec === 'Cash Report' && /Ending Cash/i.test(r['Currency Summary'] || '') && r['Currency'] && r['Currency'] !== 'Base Currency Summary' && r['Currency'] !== (info.baseCurrency || 'EUR')) {
        const v = TC.num(r['Total']); if (v && Math.abs(v) > 0.005) info.nonBaseCash.push({ currency: r['Currency'], amount: v });
      }
    });
    if (info.hasMTM) info.accounts.forEach(a => { info.startPositions[a] = info.startPositions[a] || {}; info.currentPositions[a] = info.currentPositions[a] || {}; });
    let cur = '';                                                                  // сметката на текущия блок — сменя се от реда „Account Information“ (виж по-горе)
    const acct = r => r['Account'] || cur || info.account || '?';
    (info.openPositions || []).forEach(o => { o.account = o.account || info.account || '?'; });
    const base = (r, line, src) => ({ broker: 'IBKR', account: acct(r), src, line });
    // taxable (05.11.2026): редът може да е облагаем доход / продажба — годината му става „НЕПЪЛНО“ (не само ред в списъка)
    const skip = (sec, r, line, reason, taxable, extra) => { S(sec).skipped++;
      skipped.push({ src, line, broker: 'IBKR', account: acct(r), section: sec, what: r['Symbol'] || r['Description'] || '', date: (TC.parseDateTime(r['Date/Time'] || r['Date'] || r['Report Date']) || {}).date || '', reason, taxable: !!taxable,
                     amount: r['Amount'] || r['Quantity'] || r['Proceeds'] || r['Qty'] || '', ...(extra || {}) }); };
    const push = (sec, o) => { S(sec).records++; recs.push(o); };
    // 13.11.2026: SYEP (даване на акции назаем) — „Securities Lent Interest Details“ е дневната разбивка на месечните редове „… (SYEP) Interest for Mon-YYYY“ от секция Interest (проверено върху реални отчети:
    // сумите по месец съвпадат до цент). Включва се като „подробности, вече включени“ САМО за месец, чиято сума по дни = месечния ред (±0,02); иначе — „не е сметнато“ (облагаемо) — без двойно броене и без тихо изпускане.
    const SYEP_DET = 'Stock Yield Enhancement Program Securities Lent Interest Details', SYEP_ACT = 'Stock Yield Enhancement Program Securities Lent Activity';
    const MON3 = { jan: '01', feb: '02', mar: '03', apr: '04', may: '05', jun: '06', jul: '07', aug: '08', sep: '09', oct: '10', nov: '11', dec: '12' };
    const notTotal = x => !Object.values(x).slice(0, 2).some(v => /^Total\b/i.test(String(v || '').trim()));
    const syepLine = {}, syepDet = {};
    rows.forEach(({ sec, r, noHeader }) => {
      if (noHeader) return;
      if (sec === 'Interest' && notTotal(r)) { const m = /\(SYEP\)\s+Interest\s+for\s+([A-Za-z]{3})[a-z]*-(\d{4})/i.exec(r['Description'] || ''), a = TC.num(r['Amount']); if (m && isFinite(a)) { const k = m[2] + '-' + MON3[m[1].toLowerCase()]; syepLine[k] = (syepLine[k] || 0) + a; } }
      if (sec === SYEP_DET && notTotal(r)) { const d = TC.parseDateTime(r['Value Date']), a = TC.num(r['Interest Paid to Customer']); if (d && isFinite(a)) { const k = d.date.slice(0, 7); syepDet[k] = (syepDet[k] || 0) + a; } }
    });
    const syepOk = new Set(Object.keys(syepDet).filter(k => syepLine[k] != null && Math.abs(syepLine[k] - syepDet[k]) <= 0.02));
    info.syep = Object.keys(syepDet).sort().map(k => ({ month: k, details: +syepDet[k].toFixed(4), line: syepLine[k] == null ? null : +syepLine[k].toFixed(4), ok: syepOk.has(k) }));
    rows.forEach(({ sec, r, line, noHeader }) => {
      if (!noHeader && sec === 'Account Information' && r['Field Name'] === 'Account') cur = (r['Field Value'] || '').split(/\s/)[0] || cur;
      if (noHeader) return skip(sec, r, line, 'ред с данни без заглавен ред на секцията — не може да се прочете', !IBKR_INFO.has(sec));
      if (sec === 'Trades') bump(S(sec).disc, `${r['DataDiscriminator'] || '(празно)'} × ${r['Asset Category'] || '(празно)'}`);
      if (IBKR_INFO.has(sec) || sec === 'Financial Instrument Information') return ign(sec, 'информативна секция — без сделки и доходи');
      if (Object.values(r).slice(0, 2).some(v => /^Total\b/i.test(String(v || '').trim()))) return ign(sec, 'обобщение (Total)');   // „Total“ / „Total in EUR“ — обобщения на същите редове
      if (sec === 'Trades') {
        const disc = r['DataDiscriminator'];
        if (disc === 'ClosedLot') return ign(sec, 'ClosedLot — лот към сделка, която е броена от реда „Order“');
        if (/^(SubTotal|Total)$/i.test(disc || '')) return ign(sec, 'обобщение (SubTotal / Total)');
        if (disc && disc !== 'Order' && disc !== 'Trade') return skip(sec, r, line, `непознат вид ред „${disc}“ в Trades (чета „Order“ / „Trade“)`, true);   // до 12.11 — изчезваше тихо
        const cat = IBKR_ASSET[r['Asset Category']];
        const dt = TC.parseDateTime(r['Date/Time']);
        const qty = TC.num(r['Quantity']), proceeds = TC.num(r['Proceeds']), fee = TC.num(r['Comm/Fee']), tprice = TC.num(r['T. Price']);
        if (!cat) return skip(sec, r, line, `непознат вид инструмент „${r['Asset Category']}“`, true);
        if (!dt || !qty) return skip(sec, r, line, 'сделка без дата или количество', true);
        if (cat === 'forex') return skip(sec, r, line, 'обмяна на валута (Forex) — курсовата разлика не се смята (виж предупреждението за валута)');
        if (cat === 'other') return skip(sec, r, line, `${r['Asset Category']} — не се смята от калкулатора`, true);
        const price = isFinite(proceeds) && proceeds !== 0 ? Math.abs(proceeds / qty) : tprice;
        if (!isFinite(price)) return skip(sec, r, line, 'сделка без цена', true);
        push(sec, { ...base(r, line, src), kind: 'trade', sym: r['Symbol'], assetClass: cat, date: dt.date, time: dt.time, qty, price, currency: r['Currency'],
                    fee: isFinite(fee) ? Math.abs(fee) : 0, code: r['Code'] || '' });
        return;
      }
      if (sec === 'Dividends' || sec === 'Payment In Lieu Of Dividends') {
        const dt = TC.parseDateTime(r['Date']), amt = TC.num(r['Amount']), s = TC.ibkrDescSymbol(r['Description']);
        if (!dt || !isFinite(amt)) return skip(sec, r, line, 'ред без четима дата или сума (очаквам Date = ГГГГ-ММ-ДД и Amount = число)', true);   // до 12.11 — изчезваше тихо
        if (!s) return skip(sec, r, line, 'дивидент без разпознаваем тикър в описанието', true);
        push(sec, { ...base(r, line, src), kind: 'dividend', sym: s.sym, isin: s.isin, date: dt.date, amount: amt, currency: r['Currency'], desc: r['Description'],
                    pil: sec !== 'Dividends' });
        return;
      }
      if (sec === 'Withholding Tax') {
        const dt = TC.parseDateTime(r['Date']), amt = TC.num(r['Amount']), s = TC.ibkrDescSymbol(r['Description']);
        if (!dt || !isFinite(amt)) return skip(sec, r, line, 'ред без четима дата или сума (очаквам Date = ГГГГ-ММ-ДД и Amount = число)', true);
        if (!s) return skip(sec, r, line, 'удържан данък без тикър (напр. върху лихва) — не е сметнат');
        push(sec, { ...base(r, line, src), kind: 'withholding', sym: s.sym, date: dt.date, amount: amt, currency: r['Currency'], desc: r['Description'] });
        return;
      }
      if (sec === 'Interest') {
        const dt = TC.parseDateTime(r['Date']), amt = TC.num(r['Amount']);
        if (!dt || !isFinite(amt)) return skip(sec, r, line, 'ред без четима дата или сума (очаквам Date = ГГГГ-ММ-ДД и Amount = число)', true);
        push(sec, { ...base(r, line, src), kind: 'interest', date: dt.date, amount: amt, currency: r['Currency'], desc: r['Description'] });
        return;
      }
      if (sec === 'Corporate Actions') {
        // 13.11.2026: ОБЩО разпознаване на вида (TC.parseCA / TC.caType); сплит с коефициент — както досега (kind 'split'), с часа (сплитът е след сделките на деня); всичко друго —
        // kind 'corp' с количество, пари и стойност, които TC.resolveCorp (в ingest) свързва по двойки (стар ↔ нов инструмент) в размяна / продажба / отделяне / дивидент в акции / безценност.
        const dt = TC.parseDateTime(r['Date/Time'] || r['Report Date']);
        const ca = TC.parseCA(r['Description']);
        if (!dt) return skip(sec, r, line, 'корпоративно действие без четима дата', true);
        if (!ca) return skip(sec, r, line, 'корпоративно действие с описание, което не се разпознава („СИМВОЛ(ISIN) … (СИМВОЛ, ИМЕ, ISIN)“) — виж описанието; потвърди ръчно, че няма ефект върху лотовете', true, { ackKey: ['ack', 'IBKR', acct(r), (r['Description'] || '').slice(0, 40), dt.date].join('|'), desc: r['Description'] || '' });
        const qty = TC.num(r['Quantity']), proceeds = TC.num(r['Proceeds']), value = TC.num(r['Value']), type = TC.caType(ca.body, qty, proceeds);
        const row = { ...base(r, line, src), sym: ca.sym, isin: ca.isin, sym2: ca.sym2, isin2: ca.isin2, date: dt.date, time: dt.time || '', qty: isFinite(qty) ? qty : 0, proceeds: isFinite(proceeds) ? proceeds : 0,
                      value: isFinite(value) ? value : 0, currency: r['Currency'] || '', desc: r['Description'], ctype: type, body: ca.body, fromCA: true };
        if (type === 'split') { const m = ca.body.match(/Split\s+(\d+(?:\.\d+)?)\s+for\s+(\d+(?:\.\d+)?)/i); push(sec, { ...row, kind: 'split', ratio: Number(m[1]) / Number(m[2]) }); return; }
        push(sec, { ...row, kind: 'corp' });
        return;
      }
      if (sec === 'Fees') return skip(sec, r, line, 'такса извън сделките — не се приспада от доходите от капитал (§20 ал. 9 EStG; да се потвърди)');
      if (sec === 'Transfers') {
        // 13.11.2026: прехвърлянията са записи (kind 'xfer'): Inter-Company между собствените сметки пренася лотовете с оригиналните дати и цени; ACATS / друго „In“ — лот без покупна цена,
        // която се въвежда на ръка (никога нулева цена); „Out“ към друг брокер — лотовете излизат от FIFO (не е продажба). Само акции и фондове — останалото е „не е сметнато“, както досега.
        const dtx = TC.parseDateTime(r['Date']), cx = IBKR_ASSET[r['Asset Category']], qx = TC.num(r['Qty']);
        if (!dtx || !isFinite(qx) || !qx) return skip(sec, r, line, 'прехвърляне без четима дата или количество', true);
        if (cx !== 'stock' && cx !== 'fund') return skip(sec, r, line, `прехвърляне на ${r['Asset Category']} — не се смята (цената на придобиване е в отчета на другия брокер)`, true);
        const dirx = /^out$/i.test(r['Direction'] || '') ? 'Out' : /^in$/i.test(r['Direction'] || '') ? 'In' : (qx < 0 ? 'Out' : 'In');
        const xp = TC.num(r['Xfer Price']);
        return push(sec, { ...base(r, line, src), kind: 'xfer', sym: r['Symbol'], assetClass: cx, date: dtx.date, dir: dirx, xtype: r['Type'] || '', qty: Math.abs(qx), currency: r['Currency'] || '',
                           xprice: isFinite(xp) ? xp : null, xco: r['Xfer Company'] || '' });
      }
      if (sec === SYEP_ACT) return ign(sec, 'движения на заемите (без пари) — информативна секция');
      if (sec === SYEP_DET) {
        const dd = TC.parseDateTime(r['Value Date']), mk = dd ? dd.date.slice(0, 7) : '';
        if (syepOk.has(mk)) return ign(sec, 'подробности — дневна разбивка на месечния SYEP ред от секция Interest (вече включена; без двойно броене)');
        return skip(sec, r, line, `SYEP лихва за ${mk || 'месец без дата'} без съвпадащ месечен ред „(SYEP) Interest for …“ в секция Interest (сума по дни ${syepDet[mk] != null ? syepDet[mk].toFixed(2) : '?'}, месечен ред ${syepLine[mk] != null ? syepLine[mk].toFixed(2) : 'няма'}) — провери`, true);
      }
      skip(sec, r, line, `секцията „${sec}“ не се смята`);
    });
    if (junk) skipped.push({ src, line: 0, broker: 'IBKR', account: info.account || '?', section: 'файл', what: `${junk} реда`, date: '', reason: 'редове извън формата „секция,вид,…“ — не са прочетени', taxable: false });
    return { format: 'ibkr', info, records: recs, skipped, instruments, stats: { sections: order.map(n => secs[n]), junk } };
  };

  // ─── Стандартен CSV (собственият формат на калкулатора) ─────────────────────────────────────────────
  // type: buy | sell | dividend | withholding | interest | split · asset_type: stock | etf | crypto | option | other · по желание: broker, account, fee, eu_exempt, withholding_tax
  TC.parseStandard = function (text, src) {
    const lines = String(text).replace(/^﻿/, '').split(/\r?\n/);
    const recs = [], skipped = [];
    let head = null;
    const delim = TC.delimOf(lines.find(l => l.trim() && !l.trim().startsWith('#')) || ''), dc = delim === ';';   // „;“ → немски Excel: десетична запетая
    const num = v => TC.num(v, dc);
    lines.forEach((line, i) => {
      if (!line.trim() || line.trim().startsWith('#')) return;
      const p = TC.splitCSV(line, delim);
      if (!head) { head = p.map(h => h.toLowerCase()); return; }
      const r = {}; head.forEach((h, k) => { r[h] = p[k] !== undefined ? p[k] : ''; });
      const type = (r.type || '').toLowerCase(), at = (r.asset_type || 'stock').toLowerCase();
      const dt = TC.parseDateTime(r.date), qty = num(r.quantity), price = num(r.price), fee = num(r.fee);
      const b = { broker: r.broker || 'CSV', account: r.account || 'default', src, line: i + 1, currency: (r.currency || 'EUR').toUpperCase(), sym: (r.ticker || '').toUpperCase() };
      const bad = reason => skipped.push({ src, line: i + 1, broker: b.broker, account: b.account, section: 'CSV', what: b.sym, date: dt ? dt.date : r.date, reason, taxable: true, amount: r.quantity || '' });
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
        const wh = num(r.withholding_tax);
        if (wh) recs.push({ ...b, kind: 'withholding', date: dt.date, amount: -Math.abs(wh), line: i + 1 });
      } else if (type === 'withholding') {
        if (!isFinite(qty)) return bad('невалидна сума');
        recs.push({ ...b, kind: 'withholding', date: dt.date, amount: -qty });
      } else if (type === 'interest') {
        if (!isFinite(qty)) return bad('невалидна сума на лихвата');
        recs.push({ ...b, kind: 'interest', date: dt.date, amount: qty, desc: 'interest' });
      } else if (type === 'split') {
        if (!(qty > 0)) return bad('сплит без коефициент (quantity = нови акции за една стара)');
        recs.push({ ...b, broker: r.broker || '*', account: r.account || '*', kind: 'split', date: dt.date, ratio: qty });
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
    if (r.kind === 'trade') return ['T', r.broker, r.account, r.sym, r.date, r.time, n(r.qty), n(r.price), r.currency, n(r.fee), n(r.total)].join('|');   // + такса и сума (05.11.2026)
    if (r.kind === 'xfer') return ['X', r.broker, r.account, r.sym, r.date, r.dir, n(r.qty), r.xtype].join('|');                  // 13.11.2026
    if (r.kind === 'corp' || r.fromCA) return ['C', r.broker, r.account, r.sym, r.date, r.time || '', n(r.qty), n(r.proceeds), r.desc || ''].join('|');   // ред на корпоративно действие: със количеството и часа
    return [r.kind[0].toUpperCase(), r.broker, r.account, r.sym || '', r.date, n(r.amount), n(r.ratio), r.currency || '', r.desc || ''].join('|');
  };

  // files: [{name, text}] → {files: [описание], records, skipped, rates, warnings}
  // Дедупликация: еднакъв запис в няколко файла (застъпващи се отчети) се брои веднъж; повторение в ЕДИН файл (две еднакви сделки) остава — броят се = максимума по файловете.
  TC.ingest = function (files) {
    const out = { files: [], records: [], skipped: [], rates: {}, info: [], instruments: {}, warnings: [], aliases: [], corpEvents: [] };
    const perFile = [], instByFile = [];
    files.forEach((f, fileIdx) => {
      const fmt = TC.detect(f.text);
      const desc = { name: f.name, owner: f.owner === 'B' ? 'B' : 'A', format: fmt, broker: '', account: '', accountMasked: '', from: '', to: '', records: 0, duplicates: 0, skipped: 0, error: null,
                     kinds: { trade: 0, buy: 0, sell: 0, dividend: 0, withholding: 0, interest: 0, split: 0 }, sections: null, problems: [] };
      try {
        if (fmt === 'ecb_rates') {
          const r = TC.parseECBcsv(f.text);
          Object.entries(r).forEach(([c, a]) => { out.rates[c] = (out.rates[c] || []).concat(a).sort((x, y) => x[0].localeCompare(y[0])); });
          desc.broker = 'ЕЦБ курсове'; const any = Object.values(r)[0] || []; desc.from = any.length ? any[0][0] : ''; desc.to = any.length ? any[any.length - 1][0] : '';
          desc.records = Object.keys(r).length;
        } else if (fmt === 'taxtool_result') {
          // 13.11.2026: резултат на друга програма — НЕ е източник на сметката (няма лотове, а готови печалби); записите не влизат. Какво е: брокер и години от колоните „Broker“ / „Fiscal Year“.
          // Дали е покрит от отчетите на брокера, се проверява след всички файлове (по-долу) — тогава или е бележка „не се ползва“, или червено (брокер / година без отчет тук).
          const t = TC.parseToolResult(f.text);
          Object.assign(desc, { broker: 'резултат на друга програма', notSource: true, tool: t, from: t.years.length ? String(t.years[0]) : '', to: t.years.length ? String(t.years[t.years.length - 1]) : '' });
        } else if (fmt === 'xlsx') {
          desc.error = 'Excel файл (.xlsx) — не се чете; запиши листа като CSV';
          desc.problems = [{ level: 'err', title: 'Excel файл — нищо от него не е сметнато', lines: ['Калкулаторът чете само текстови CSV файлове; .xlsx не се отваря. Ако в него има сделки или доходи, свали отчета на брокера като CSV (или запиши листа като CSV).', TC.FORMAT_HINT] }];
          out.skipped.push({ src: f.name, line: 0, section: 'файл', what: f.name, date: '', reason: 'Excel файл (.xlsx) — не се чете; нужен е CSV', taxable: true });
        } else if (fmt === 'ibkr' || fmt === 'standard' || (TC.parsers && TC.parsers[fmt])) {
          const res = fmt === 'ibkr' ? TC.parseIBKR(f.text, f.name) : fmt === 'standard' ? TC.parseStandard(f.text, f.name) : TC.parsers[fmt](f.text, f.name, f.owner);
          res.records.forEach(r => { r.owner = f.owner === 'B' ? 'B' : 'A'; });       // чий е файлът (05.11.2026) — по подразбиране за крипто §23 на човек
          perFile.push({ idx: fileIdx, recs: res.records });
          out.skipped.push(...res.skipped.map(x => ({ ...x, _f: fileIdx })));
          Object.assign(out.instruments, res.instruments || {});
          if (res.info) out.info.push({ file: f.name, ...res.info });
          if (fmt === 'ibkr') instByFile.push({ end: (res.info && res.info.periodEnd) || '', inst: res.instruments || {} });
          const dates = res.records.map(r => r.date).sort();
          const accts = [...new Set(res.records.map(r => r.account))];
          Object.assign(desc, { broker: (res.info && res.info.broker) || fmt, account: accts.join(', ') || (res.info && res.info.account) || '', from: dates[0] || '', to: dates[dates.length - 1] || '',
                                records: res.records.length, skipped: res.skipped.length, period: res.info && res.info.period });
          // 12.11.2026 (никога тиха нула): какво точно е прочетено от файла — по вид запис, по секции, и защо няма сделки, ако няма
          res.records.forEach(r => { if (r.kind === 'corp') return; desc.kinds[r.kind] = (desc.kinds[r.kind] || 0) + 1; if (r.kind === 'trade') desc.kinds[r.qty > 0 ? 'buy' : 'sell']++; });   // 13.11: „corp“ (неразрешени редове на корпоративни действия) — не е вид запис за таблицата
          desc.accountMasked = (accts.length ? accts : [(res.info && res.info.account) || '']).map(TC.maskAccount).join(', ');
          desc.sections = res.stats ? res.stats.sections : null;
          desc.problems = TC.fileProblems(desc, res, f.text);
        } else {
          desc.error = 'непознат формат — файлът не е сметнат';
          desc.problems = TC.fileProblems(desc, null, f.text);
          out.skipped.push({ src: f.name, line: 0, section: 'файл', what: f.name, date: '', reason: 'непознат формат (не е IBKR, Revolut, стандартен CSV или курсове на ЕЦБ)', taxable: true });
        }
      } catch (e) { desc.error = e.message; desc.problems = [{ level: 'err', title: 'Файлът не се прочете', lines: ['Грешка при четенето: ' + e.message] }];
                    out.skipped.push({ src: f.name, line: 0, section: 'файл', what: f.name, date: '', reason: 'грешка при четенето: ' + e.message, taxable: true }); }
      out.files.push(desc);
    });
    // 13.11.2026: резултат на друга програма — покрит ли е от прочетените отчети на брокера? Покрит (всеки брокер и всяка година в него има отчет тук) → само бележка „не се ползва като източник“, годината НЕ става
    // непълна заради него. Не е покрит (друг брокер или година без отчет) → червено + „не е сметнато“ (тогава в него има данни, които калкулаторът няма).
    const toolFiles = out.files.filter(d => d.format === 'taxtool_result');
    if (toolFiles.length) {
      const normB = b => { const s = String(b || '').toLowerCase().replace(/[^a-z0-9]/g, ''); return /^(ibkr|interactivebrokers.*)$/.test(s) ? 'ibkr' : s; };
      const cov = {}, add = (b, y0, y1) => { for (let y = y0; y <= y1; y++) (cov[normB(b)] = cov[normB(b)] || new Set()).add(y); };
      out.info.forEach(i => { if (i.broker === 'IBKR' && i.periodStart && i.periodEnd) add('IBKR', Number(i.periodStart.slice(0, 4)), Number(i.periodEnd.slice(0, 4))); });
      out.files.forEach(d => { if (d.format !== 'taxtool_result' && d.format !== 'ibkr' && d.format !== 'ecb_rates' && d.records && d.from && d.to) add(d.broker, Number(d.from.slice(0, 4)), Number(d.to.slice(0, 4))); });
      toolFiles.forEach(d => {
        const t = d.tool, miss = t.pairs.filter(p => !(cov[normB(p.broker)] && cov[normB(p.broker)].has(p.year)));
        const brokers = [...new Set(t.pairs.map(p => p.broker))].join(', ') || '—', yrs = t.years.length ? (t.years[0] === t.years[t.years.length - 1] ? t.years[0] : t.years[0] + '–' + t.years[t.years.length - 1]) : '—';
        const what = t.kind === 'sales' ? 'продажби' : 'дивиденти';
        if (!miss.length && !t.badRows) {
          d.note = `резултат на друга програма (${what}; брокер: ${brokers}; години ${yrs}) — не е отчет на брокер и не е източник; покрит е от прочетените отчети, затова не се ползва`;
        } else {
          const why = [...(miss.length ? [`няма прочетен отчет за: ${miss.map(p => `${p.broker || '(без брокер)'} ${p.year} (${p.n} ${p.n === 1 ? 'ред' : 'реда'})`).join(', ')}`] : []), ...(t.badRows ? [`${t.badRows} реда без валидна „Fiscal Year“`] : [])].join('; ');
          d.error = 'резултат на друга програма с редове без отчет тук — не са сметнати';
          d.problems = [{ level: 'err', title: 'Резултат на друга програма съдържа данни, за които няма отчет на брокера', lines: [
            `Файлът е резултат на друга данъчна програма (${what}), не отчет на брокер; сам по себе си не е източник за лотове и не се ползва.`, `Но в него има редове, които не са покрити от прочетените отчети: ${why}. Ако са реални, качи отчета на брокера за тях — иначе годината е непълна.`] }];
          out.skipped.push({ src: d.name, line: 0, section: 'файл', what: d.name, date: '', reason: 'резултат на друга програма с редове без отчет на брокера тук: ' + why, taxable: true });
        }
      });
    }
    // 13.11.2026: смяна на тикъра = същият инструмент (един и същ Conid в „Financial Instrument Information“ на различни отчети) — лотовете продължават под новото (най-късното) име
    const byConid = {};
    instByFile.forEach(({ end, inst }) => Object.entries(inst).forEach(([sym, d]) => { if (d.conid && /^(Stocks|Mutual Funds)$/.test(d.category)) (byConid[d.conid] = byConid[d.conid] || []).push({ sym, end }); }));
    const alias = {};
    Object.entries(byConid).forEach(([cid, list]) => { const syms = [...new Set(list.map(x => x.sym))]; if (syms.length < 2) return;
      const canon = list.slice().sort((a, b) => a.end.localeCompare(b.end)).pop().sym; syms.filter(x => x !== canon).forEach(x => { alias[x] = { to: canon, conid: cid }; }); });
    out.aliases = Object.entries(alias).map(([from, a]) => ({ from, to: a.to, conid: a.conid }));
    if (out.aliases.length) {
      perFile.forEach(({ recs }) => recs.forEach(r => { if (r.sym && alias[r.sym]) { r.symOrig = r.sym; r.sym = alias[r.sym].to; } if (r.sym2 && alias[r.sym2]) r.sym2 = alias[r.sym2].to; }));
      out.info.forEach(i => {
        (i.openPositions || []).forEach(o => { if (alias[o.sym]) o.sym = alias[o.sym].to; });
        ['startPositions', 'currentPositions'].forEach(k => Object.keys(i[k] || {}).forEach(a => { const m = {}; Object.entries(i[k][a]).forEach(([sy, q]) => { const t = alias[sy] ? alias[sy].to : sy; m[t] = (m[t] || 0) + q; }); i[k][a] = m; }));
      });
      out.aliases.forEach(a => out.warnings.push(`${a.from} → ${a.to}: един и същ инструмент (Conid ${a.conid}) в отчетите — смяна на тикъра; лотовете на ${a.from} продължават като ${a.to} с оригиналните дати и цени.`));
    }
    // 14.11.2026: „Profit and loss“ на Revolut — всеки продаден лот дава покупка (дата на придобиване) и продажба; ако отчетът на сделките (Trading account statement) вече има същата покупка / продажба
    // (същата сметка, тикър и ден, количество поне колкото в лота), тя НЕ се брои втори път; останалото се добавя (покупки и продажби след края на отчета на сделките). Частично покритие → добавя се разликата.
    const pnlRecs = perFile.flatMap(pf => pf.recs.filter(r => r.pnl));
    if (pnlRecs.length) {
      const real = perFile.flatMap(pf => pf.recs.filter(r => !r.pnl && r.kind === 'trade' && r.broker === 'Revolut'));
      const kd = r => [r.account, r.sym, r.date].join('|'), have = { B: {}, S: {} };
      real.forEach(r => { const side = r.qty > 0 ? 'B' : 'S'; have[side][kd(r)] = (have[side][kd(r)] || 0) + Math.abs(r.qty); });
      const groups = {}; pnlRecs.forEach(r => { const k = (r.qty > 0 ? 'B' : 'S') + '|' + kd(r); (groups[k] = groups[k] || []).push(r); });
      const st = { rows: pnlRecs.length / 2, coveredB: 0, coveredS: 0, addedB: 0, addedS: 0 };
      Object.entries(groups).forEach(([k, g]) => {
        const side = k[0], h = have[side][k.slice(2)] || 0, need = g.reduce((a, r) => a + Math.abs(r.qty), 0);
        if (h >= need - 1e-6) { g.forEach(r => { r.drop = true; }); st['covered' + side] += g.length; }
        else { if (h > 1e-6) { const f = (need - h) / need; g.forEach(r => { r.qty *= f; r.total *= f; }); } st['added' + side] += g.length; }
      });
      perFile.forEach(pf => { const d = out.files[pf.idx]; const dropped = pf.recs.filter(r => r.drop); if (!dropped.length) return;
        d.duplicates += dropped.length; d.records -= dropped.length; dropped.forEach(r => { d.kinds.trade--; d.kinds[r.qty > 0 ? 'buy' : 'sell']--; }); pf.recs = pf.recs.filter(r => !r.drop); });
      const names = [...new Set(perFile.filter(pf => out.files[pf.idx].format === 'revolut_pnl').map(pf => out.files[pf.idx].name))].join(', ');
      out.warnings.push(`Revolut — печалби и загуби (${names}): ${st.rows} продадени лота; покупки, които вече са в отчета на сделките: ${st.coveredB}, добавени: ${st.addedB}; продажби, които вече са в отчета на сделките: ${st.coveredS}, добавени: ${st.addedS}. ` +
        'В този отчет има САМО продадените лотове — покупките от същия период, които още не са продадени, и дивидентите липсват; за тях е нужен отчетът на сделките (Trading account statement) за периода. Валутата не е в отчета — приета е USD. Лотовете се подбират по FIFO, не по колоната „Date acquired“.');
    }
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
    // Mutual Funds на IBKR (клас 'fund') — винаги фонд (05.11.2026: смятаха се като акции и не бяха в таблицата с видовете фондове)
    out.records.forEach(x => { if (x.kind === 'trade' && (x.assetClass === 'fund' || (out.instruments[x.sym] && /ETF|FUND/i.test(out.instruments[x.sym].type)))) x.fundHint = true; });
    // „не е сметнато“ — също веднъж за застъпващи се отчети (ключ без името на файла)
    // 05.11.2026: ключът е със сумата, а повторенията в ЕДИН файл остават (две еднакви такси в един ден — два реда); между файловете — максимумът, както при записите
    const skCounts = {}, skOut = [];
    out.skipped.forEach(x => { if (!x.line) { skOut.push(x); return; } const k = [x.broker, x.account, x.section, x.what, x.date, x.reason, x.amount || ''].join('|');
                               ((skCounts[k] = skCounts[k] || {})[x._f] = skCounts[k][x._f] || []).push(x); });
    Object.values(skCounts).forEach(byFile => skOut.push(...Object.values(byFile).sort((a, b) => b.length - a.length)[0]));
    out.skipped = skOut.map(({ _f, ...x }) => x);
    // 13.11.2026: корпоративните действия — по двойки (стар ↔ нов инструмент) → размяна / продажба / отделяне / дивидент в акции / безценност; непознатото — „не е сметнато“ (червено) с ключ за ръчно потвърждение
    const isCA = r => r.kind === 'corp' || (r.kind === 'split' && r.fromCA);
    const caRows = out.records.filter(isCA);
    if (caRows.length) { const rc = TC.resolveCorp(caRows); out.records = out.records.filter(r => !isCA(r)).concat(rc.records); out.skipped.push(...rc.skipped); out.corpEvents = rc.events; }
    // при еднакъв момент (часът липсва): сплитът първи, после покупките, после продажбите (05.11.2026: отчет с най-новите отгоре даваше „липсва покупката“ за дневна сделка)
    const tie = r => r.kind === 'split' ? 0 : r.kind === 'xfer' ? (r.dir === 'Out' ? 1 : /inter-?company|internal|intra/i.test(r.xtype || '') ? 2 : 3.5) : r.kind === 'trade' ? (r.qty > 0 ? 3 : 4) : 5;   // 13.11: прехвърлянията — преди сделките, „Out“ преди „In“; 14.11: „In“ от друг брокер — СЛЕД покупките на деня (за да види и покупка на същия ден при другия брокер) и преди продажбите
    out.records.sort((a, b) => (a.date + (a.time || '')).localeCompare(b.date + (b.time || '')) || tie(a) - tie(b));
    // 13.11.2026 (контроли по началните / крайните позиции): за всеки IBKR отчет и всяка негова сметка — позициите в първия ден на периода (Mark-to-Market → Prior Quantity) и в последния
    // (Open Positions; ако секцията я няма — Current Quantity). TC.fifo ги прилага по дата: излишъкът от лотове в началото не се ползва, разлика в края се показва — никога тихо.
    const ctl = [], seenCtl = new Set();
    out.info.forEach(i => {
      if (i.broker !== 'IBKR') return;
      (i.accounts || []).forEach(a => {
        const add = c => { const k = [c.type, c.account, c.date].join('|'); if (!seenCtl.has(k)) { seenCtl.add(k); ctl.push(c); } };
        if (i.hasPrior && i.periodStart) add({ type: 'start', broker: 'IBKR', account: a, date: i.periodStart, positions: (i.startPositions || {})[a] || {}, file: i.file, period: i.period || '' });
        if (!i.periodEnd) return;
        if (Array.isArray(i.openPositions)) { const m = {}; i.openPositions.filter(o => o.account === a).forEach(o => { m[o.sym] = (m[o.sym] || 0) + o.qty; }); add({ type: 'end', broker: 'IBKR', account: a, date: i.periodEnd, positions: m, scope: 'all', source: 'Open Positions', file: i.file }); }
        else if (i.hasCurrent) add({ type: 'end', broker: 'IBKR', account: a, date: i.periodEnd, positions: (i.currentPositions || {})[a] || {}, scope: 'stocks', source: 'Mark-to-Market Performance Summary (Current Quantity)', file: i.file });
      });
    });
    ctl.filter(c => c.type === 'start').forEach(c => { const prev = ctl.filter(e => e.type === 'end' && e.broker === c.broker && e.account === c.account && e.date < c.date).map(e => e.date).sort().pop(); c.prevEnd = prev || ''; });
    out.controls = ctl;
    return out;
  };

  const t_count = (files, n) => files.filter(f => f.name === n).length;

  // 13.11.2026: файл „Fiscal Year“ от друга данъчна програма (колони Fiscal Year, Broker, Acquisition Date / Dividend Date …) — само БРОЕВЕ по брокер и година; без лотове и без суми
  // (форматът е от реални файлове на потребителя — заглавните редове в tests/fixtures/tax/real_anon/toolresult_*.csv; редовете там са измислени)
  TC.parseToolResult = function (text) {
    const L = String(text).replace(/^﻿/, '').split(/\r?\n/).filter(l => l.trim());
    const H = TC.splitCSV(L[0] || '').map(h => h.trim().toLowerCase()), iy = H.indexOf('fiscal year'), ib = H.indexOf('broker');
    const pairs = {}, years = new Set(); let badRows = 0;
    L.slice(1).forEach(l => { const p = TC.splitCSV(l), y = String(p[iy] || '').trim(), b = String(p[ib] || '').trim();
      if (!/^\d{4}$/.test(y)) { badRows++; return; } years.add(Number(y)); pairs[y + '|' + b] = (pairs[y + '|' + b] || 0) + 1; });
    return { kind: H.includes('acquisition date') ? 'sales' : 'dividends', rows: Math.max(0, L.length - 1), badRows, years: [...years].sort((a, b) => a - b),
             pairs: Object.entries(pairs).map(([k, n]) => { const [y, b] = k.split('|'); return { year: Number(y), broker: b, n }; }).sort((a, b) => a.year - b.year || a.broker.localeCompare(b.broker)) };
  };

  // ─── Никога тиха нула (12.11.2026) ─────────────────────────────────────────────
  // Какво не е наред с файла, казано така, че да се вижда причината: [{level: 'err' | 'warn', title, lines: [текст]}] — страницата го показва с червено под файловете.
  //  · непознат формат → първият ред на файла (колоните) и какво се очаква;
  //  · разпознат файл без нито една сделка → кои секции / колони има, кои се очакват и къде са спрели редовете от Trades;
  //  · очаквана колона липсва в заглавния ред на секция (тогава всеки ред от нея е в „не е сметнато“).
  TC.FORMAT_HINT = 'Чета: IBKR Activity Statement (CSV — първият ред започва със „Statement,Header,“); Revolut (колони Date, Ticker, Type, Quantity, Price per share, Total Amount, Currency — акции; ' +
    'Symbol, Type, Quantity, Price, Value, Fees, Date — крипто; Date acquired, Date sold, Symbol, Quantity, Cost basis, Amount, Realised PnL — печалби и загуби); стандартен CSV (type, ticker, date, quantity, price, currency); курсове на ЕЦБ (eurofxref-hist.csv).';
  const cnt = o => Object.entries(o || {}).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ×${n}`).join(' · ');
  const colsOf = need => need.map(c => Array.isArray(c) ? c.join(' или ') : c).join(', ');
  TC.fileProblems = function (desc, res, text) {
    const out = [];
    const first = (String(text || '').replace(/^﻿/, '').split(/\r?\n/).find(l => l.trim()) || '');
    const firstCols = TC.splitCSV(first, TC.delimOf(first)).map(c => c === '' ? '(празно)' : c);
    if (!res) {
      out.push({ level: 'err', title: 'Не разпознах файла — нищо от него не е сметнато', lines: [
        first ? `Първият ред на файла (${firstCols.length} колони): ${firstCols.slice(0, 20).join(' | ')}${firstCols.length > 20 ? ' | …' : ''}` : 'Файлът е празен.', TC.FORMAT_HINT] });
      return out;
    }
    const secs = desc.sections || [], sk = res.skipped || [];
    if (desc.format === 'ibkr') {
      Object.entries(TC.IBKR_EXPECTED).forEach(([name, need]) => { const st = secs.find(x => x.name === name);
        if (st && st.missing.length) out.push({ level: 'err', title: `В секцията „${name}“ липсват колони: ${st.missing.join(', ')}`, lines: [
          `Чета по името на колоната от заглавния ред; очаквам: ${colsOf(need)}.`, ...st.headers.map((h, i) => `Заглавен ред ${i + 1} в отчета: ${h.map(c => c === '' ? '(без име)' : c).join(' | ')}`),
          `Редовете от секцията, които не се прочетоха, са в „не е сметнато“ (${st.skipped} от ${st.data}).`] }); });
      // редове с повече клетки от заглавния ред — колоните са изместени спрямо имената; червено, ако от секцията не е излязъл нито един запис
      Object.keys(TC.IBKR_EXPECTED).forEach(name => { const st = secs.find(x => x.name === name);
        if (st && st.wider) out.push({ level: st.records ? 'warn' : 'err', title: `В секцията „${name}“ ${st.wider} ${st.wider === 1 ? 'ред с данни има' : 'реда с данни имат'} повече клетки от заглавния ред (${cnt(st.widths)})`, lines: [
          'Чета по името на колоната от заглавния ред: когато в реда има клетка, която я няма в заглавния ред, стойностите след нея попадат под грешно име (изместени колони).',
          ...st.headers.map((h, i) => `Заглавен ред ${i + 1} в отчета (${h.length} колони): ${h.map(c => c === '' ? '(без име)' : c).join(' | ')}`),
          st.records ? `От секцията са прочетени ${st.records} записа — провери ги по отчета.` : `От секцията не е прочетен нито един запис (${st.skipped} реда са в „не е сметнато“).`] }); });
    }
    if (desc.kinds.trade > 0) return out;
    const lines = [];
    if (desc.format === 'ibkr') {
      const withData = secs.filter(x => x.data > 0);
      lines.push(`Видях секциите (редове с данни): ${withData.map(x => `${x.name} (${x.data})`).join(', ') || 'нито една с данни'}` + (secs.length > withData.length ? `; без данни: ${secs.filter(x => !x.data).map(x => x.name).join(', ')}` : '') + '.');
      lines.push(`Очаквах: секция „Trades“ с редове „Data“ от вид „Order“ и колони ${colsOf(TC.IBKR_EXPECTED.Trades)}.`);
      const tr = secs.find(x => x.name === 'Trades');
      if (!tr) lines.push('Секция „Trades“ в този отчет няма. Ако през периода не си купувал и продавал, това е вярно; иначе отчетът е свален без сделките — свали Activity Statement с включена секция Trades.');
      else if (!tr.data) lines.push(`Секцията „Trades“ е в отчета, но няма нито един ред с данни (видове редове: ${cnt(tr.rowTypes)}).`);
      else {
        const why = {}; Object.entries(tr.why).forEach(([k, n]) => { why[k] = n; });
        sk.filter(x => x.section === 'Trades').forEach(x => { why[x.reason] = (why[x.reason] || 0) + 1; });
        lines.push(`Секцията „Trades“ има ${tr.data} реда с данни, но нито един не стана сделка: ${cnt(why)}.`);
        lines.push(`Редове по вид (DataDiscriminator × Asset Category): ${cnt(tr.disc)}.`);
        tr.headers.forEach((h, i) => lines.push(`Заглавен ред ${i + 1} на „Trades“ в отчета: ${h.map(c => c === '' ? '(без име)' : c).join(' | ')}`));
      }
    } else {
      lines.push(`Форматът е разпознат като „${desc.format}“; колони в първия ред: ${firstCols.slice(0, 20).join(' | ')}.`);
      lines.push(`Прочетени записи: ${desc.records} (дивиденти ${desc.kinds.dividend}, лихви ${desc.kinds.interest}); в „не е сметнато“: ${sk.length}${sk.length ? ' — ' + cnt(sk.reduce((o, x) => { o[x.reason] = (o[x.reason] || 0) + 1; return o; }, {})) : ''}.`);
      lines.push('Очаквах редове от вид покупка / продажба (buy / sell) с дата, количество и цена.');
    }
    out.push({ level: 'err', title: 'В този файл не намерих сделки', lines });
    return out;
  };

  // Резюмето над резултата: какво е прочетено общо и за избраната година. fifoRes може да липсва (още не е сметнато / няма записи).
  // → {all: {files, records, trades, buys, sells, dividends, withholding, interest, splits, skipped, skippedNoDate, unmatched}, year: {… + sales, salesNoRate}, years: [години с данни], empty}
  TC.summary = function (ing, fifoRes, year) {
    const Y = String(year), recs = (ing && ing.records) || [], sk = (ing && ing.skipped) || [];
    const count = list => { const o = { records: list.length, trades: 0, buys: 0, sells: 0, dividends: 0, withholding: 0, interest: 0, splits: 0 };
      list.forEach(r => { if (r.kind === 'trade') { o.trades++; o[r.qty > 0 ? 'buys' : 'sells']++; } else if (r.kind === 'dividend') o.dividends++; else if (r.kind === 'withholding') o.withholding++;
                          else if (r.kind === 'interest') o.interest++; else if (r.kind === 'split') o.splits++; else if (['exchange', 'spinoff', 'stockdiv'].includes(r.kind)) o.corp = (o.corp || 0) + 1; });
      return o; };
    const all = count(recs), yr = count(recs.filter(r => r.date.startsWith(Y)));
    const un = (fifoRes && fifoRes.unmatched) || [], R = ((fifoRes && fifoRes.realized) || []).filter(x => x.year === Number(year));
    all.files = ((ing && ing.files) || []).filter(f => f.format !== 'ecb_rates' && !(f.notSource && !f.error)).length;   // 13.11: покрит резултат на друга програма не е прочетен отчет
    all.skipped = sk.length; all.skippedNoDate = sk.filter(x => !x.date).length; all.unmatched = un.length;
    yr.skipped = sk.filter(x => String(x.date || '').startsWith(Y)).length; yr.skippedTaxable = sk.filter(x => x.taxable && String(x.date || '').startsWith(Y)).length;
    yr.unmatched = un.filter(u => u.year === Number(year)).length; yr.sales = R.length; yr.salesNoRate = R.filter(x => x.gainEUR == null).length;
    return { all, year: yr, years: [...new Set(recs.map(r => Number(r.date.slice(0, 4))))].sort((a, b) => a - b), empty: yr.records === 0 };
  };

  // Числото най-горе е 0 → защо (никога само „0,00 €“). → [текст, …]; празно, когато числото не е 0. de — от computeDE, sum — от summary за същата година.
  TC.whyZero = function (de, sum) {
    if (!de || !sum || Math.abs(de.headline) > 0.004) return [];
    const y = de.year, s = sum.year, out = [];
    if (sum.empty) return [`в качените файлове няма нито един запис за ${y}` + (sum.years.length ? ` — данните са за ${sum.years.join(', ')}; смени годината горе` : '')];
    if (!s.sells) out.push(`за ${y} няма продажби` + (s.buys ? ` (само покупки: ${s.buys})` : ''));
    if (s.unmatched) out.push(`${s.unmatched} ${s.unmatched === 1 ? 'продажба е' : 'продажби са'} без покупка в качените файлове — не ${s.unmatched === 1 ? 'е' : 'са'} в числото`);
    if (s.salesNoRate) out.push(`${s.salesNoRate} ${s.salesNoRate === 1 ? 'продажба е' : 'продажби са'} без курс — не ${s.salesNoRate === 1 ? 'е' : 'са'} в числото`);
    if (!s.dividends && !s.interest) out.push('няма дивиденти и лихви');
    if (s.skippedTaxable) out.push(`${s.skippedTaxable} реда от ${y} са в „не е сметнато“ и може да са облагаеми`);
    if ((de.items || []).length && !out.length) out.push('редовете в разбивката се събират точно до 0 (печалбите се покриват от загубите / пренесените загуби)');
    if ((de.crypto || []).length) out.push('крипто продажбите са отделно (§23, Anlage SO) — виж реда под числото');
    return out;
  };

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
  // 14.11.2026: „ДД/ММ/ГГГГ ЧЧ:ММ:СС“ (РЕАЛЕН формат на отчета на Revolut „Trading account statement“) — редът ден / месец се определя по целия файл (TC.slashOrder), по подразбиране ДД/ММ
  TC.slashOrder = vals => { let a = 0, b = 0; vals.forEach(v => { const m = /^\s*(\d{1,2})\/(\d{1,2})\/\d{4}/.exec(String(v || '')); if (m) { if (Number(m[1]) > 12) a++; if (Number(m[2]) > 12) b++; } }); return b > 0 && a === 0 ? 'mdy' : 'dmy'; };
  TC.parseLooseDate = function (s, order) {
    const sl = String(s || '').match(/^\s*(\d{1,2})\/(\d{1,2})\/(\d{4})(?:[ ,T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
    if (sl) { let d = Number(sl[1]), mo = Number(sl[2]); if (order === 'mdy') [d, mo] = [mo, d]; if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
      return { date: `${sl[3]}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`, time: sl[4] ? `${String(sl[4]).padStart(2, '0')}:${sl[5]}:${sl[6] || '00'}` : '' }; }
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
    // owner (05.11.2026): отчетите на Revolut нямат номер на сметка — сметката е „акции“ / „крипто“ + собственикът на файла, иначе двамата съпрузи ставаха една FIFO опашка
    revolut_stocks(text, src, owner) {
      const acc = 'акции' + (owner === 'B' ? ' · съпруг/а' : '');
      const recs = [], skipped = [], b = { broker: 'Revolut', account: acc, src };
      const rows = rowsOf(text), order = TC.slashOrder(rows.map(x => x.r['date']));
      // 14.11.2026: „MERGER - STOCK“ (акциите излизат, количество < 0) + „MERGER - CASH“ (парите) на същия тикър в рамките на 3 дни = сливане срещу пари = ПРОДАЖБА (като при IBKR); непарно → „не е сметнато“
      const dayNum = d => Math.round(new Date(d + 'T12:00:00Z') / 86400000);
      const mCash = rows.map((x, i) => ({ x, i })).filter(o => /^MERGER\s*-\s*CASH/i.test(o.x.r['type'] || ''));
      const pairOf = {}, usedCash = new Set();
      rows.forEach((x, i) => { if (!/^MERGER\s*-\s*STOCK/i.test(x.r['type'] || '') || !(TC.num(x.r['quantity']) < 0)) return; const d0 = TC.parseLooseDate(x.r['date'], order); if (!d0) return;
        let best = null; mCash.forEach(o => { const d1 = TC.parseLooseDate(o.x.r['date'], order); if (!d1 || usedCash.has(o.i) || o.x.r['ticker'] !== x.r['ticker'] || !(TC.num(o.x.r['total amount']) > 0)) return;
          const gap = Math.abs(dayNum(d1.date) - dayNum(d0.date)); if (gap <= 3 && (!best || gap < best.gap)) best = { o, gap }; });
        if (best) { pairOf[i] = best.o; usedCash.add(best.o.i); } });
      rows.forEach(({ r, line }, idx) => {
        const dt = TC.parseLooseDate(r['date'], order), type = (r['type'] || '').toUpperCase(), cur = (r['currency'] || '').toUpperCase() || 'USD';
        const price = TC.money(r['price per share'], cur), total = TC.money(r['total amount'], cur), qty = TC.num(r['quantity']);
        const skip = (reason, taxable) => skipped.push({ src, line, broker: 'Revolut', account: acc, section: 'Revolut', what: `${r['ticker'] || ''} ${r['type'] || ''}`.trim(), date: dt ? dt.date : r['date'], reason, taxable: !!taxable,
                                                       amount: r['quantity'] || r['total amount'] || '' });
        if (!dt) return skip('без дата', true);
        if (/^(BUY|SELL)/.test(type)) {
          if (!(qty > 0)) return skip('невалидно количество', true);
          // 14.11.2026: сумата (Total Amount) е точната; цената в отчета е закръглена до 2 знака (до 0,5% разлика) — цената е сума ÷ брой, без „такса“ от закръгляването
          const px = isFinite(total.v) && total.v !== 0 ? Math.abs(total.v) / qty : price.v;
          if (!(px > 0)) return skip('без цена и сума', true);
          recs.push({ ...b, line, kind: 'trade', assetClass: 'stock', sym: r['ticker'], date: dt.date, time: dt.time, qty: /^BUY/.test(type) ? qty : -qty, price: px,
                      currency: price.cur || total.cur || cur, fee: 0, total: Math.abs(total.v) });
        } else if (/^MERGER/.test(type)) {
          if (/^MERGER\s*-\s*CASH/.test(type)) { if (usedCash.has(idx)) return; return skip('„MERGER - CASH“ без съответно излизане на акции („MERGER - STOCK“ с отрицателно количество) — не е сметнато; потвърди ръчно', true); }
          const cash = pairOf[idx];
          if (cash) { const d1 = TC.parseLooseDate(cash.x.r['date'], order), tot = TC.num(cash.x.r['total amount']), q = Math.abs(qty);
            recs.push({ ...b, line, kind: 'trade', assetClass: 'stock', sym: r['ticker'], date: d1.date, time: d1.time, qty: -q, price: tot / q, currency: cur, fee: 0, total: tot, viaMerger: true }); return; }
          skip(qty < 0 ? '„MERGER - STOCK“ без парите („MERGER - CASH“) — сливане акции срещу акции или смесено; не е сметнато, потвърди ръчно' : '„MERGER - STOCK“ с постъпили акции — покупната цена е на старите акции; не е сметнато, потвърди ръчно', true);
        } else if (type === 'DIVIDEND') {
          if (!isFinite(total.v)) return skip('дивидент без сума', true);
          recs.push({ ...b, line, kind: 'dividend', sym: r['ticker'], date: dt.date, amount: total.v, currency: total.cur || cur, desc: 'Revolut DIVIDEND (сумата в отчета — да се провери дали е брутна)' });
        } else if (/CASH TOP-UP|CASH WITHDRAWAL|TRANSFER/.test(type)) {
          if (r['ticker'] && qty > 0) return skip('прехвърляне на акции — цената на придобиване не е в този отчет (при продажба — „липсва покупката“)');   // 05.11.2026: изчезваше тихо
          return;                                                                 // движение на пари — не е доход
        } else if (/SPLIT/.test(type)) skip(`сплит в Revolut — коефициентът не е в отчета; добави стандартен CSV с ред: type=split, ticker=${r['ticker'] || 'тикър'}, date, quantity = нови акции за една стара (без broker / account — важи за всички сметки)`);
        else if (/FEE/.test(type)) skip('такса извън сделките — не се приспада (§20 ал. 9 EStG; да се потвърди)');
        else skip(`непознат тип „${r['type']}“`, true);
      });
      return { format: 'revolut_stocks', info: { broker: 'Revolut' }, records: recs, skipped };
    },
    // 14.11.2026: „Profit and loss“ на Revolut: Date acquired, Date sold, Symbol, Quantity, Cost basis, Amount, Realised PnL — по един ред на ПРОДАДЕН лот (само продадените; валутата не е в отчета — USD).
    // Дава покупка (дата на придобиване, цена = Cost basis) и продажба (дата на продажбата, сума = Amount) на лот; в TC.ingest се сверява с отчета на сделките: каквото вече е там, не се брои втори път.
    revolut_pnl(text, src, owner) {
      const acc = 'акции' + (owner === 'B' ? ' · съпруг/а' : '');
      const recs = [], skipped = [], b = { broker: 'Revolut', account: acc, src, currency: 'USD', fee: 0, assetClass: 'stock', kind: 'trade', pnl: true };
      rowsOf(text).forEach(({ r, line }) => {
        const da = TC.parseLooseDate(r['date acquired']), ds = TC.parseLooseDate(r['date sold']), qty = TC.num(r['quantity']), cost = TC.num(r['cost basis']), amt = TC.num(r['amount']);
        const skip = reason => skipped.push({ src, line, broker: 'Revolut', account: acc, section: 'Revolut', what: `${r['symbol'] || ''} лот`.trim(), date: ds ? ds.date : r['date sold'], reason, taxable: true, amount: r['quantity'] || '' });
        if (!da || !ds) return skip('без дата на придобиване или продажба');
        if (!(qty > 0) || !(cost > 0) || !isFinite(amt)) return skip('невалидно количество, цена на придобиване или сума');
        recs.push({ ...b, line, sym: r['symbol'], date: da.date, time: '', qty, price: cost / qty, total: cost, pnlSide: 'buy' });
        recs.push({ ...b, line, sym: r['symbol'], date: ds.date, time: '', qty: -qty, price: amt / qty, total: amt, pnlSide: 'sell', realised: TC.num(r['realised pnl']) });
      });
      return { format: 'revolut_pnl', info: { broker: 'Revolut' }, records: recs, skipped };
    },
    // крипто: Symbol,Type,Quantity,Price,Value,Fees,Date
    revolut_crypto(text, src, owner) {
      const acc = 'крипто' + (owner === 'B' ? ' · съпруг/а' : '');
      const recs = [], skipped = [], b = { broker: 'Revolut', account: acc, src };
      rowsOf(text).forEach(({ r, line }) => {
        const dt = TC.parseLooseDate(r['date']), type = (r['type'] || '').toLowerCase(), qty = TC.num(r['quantity']);
        const price = TC.money(r['price'], 'EUR'), value = TC.money(r['value'], price.cur || 'EUR'), fee = TC.money(r['fees'], price.cur || 'EUR');
        const skip = (reason, taxable) => skipped.push({ src, line, broker: 'Revolut', account: acc, section: 'Revolut', what: `${r['symbol'] || ''} ${r['type'] || ''}`.trim(), date: dt ? dt.date : r['date'], reason, taxable: !!taxable,
                                                       amount: r['quantity'] || r['value'] || '' });
        if (!dt) return skip('без дата', true);
        if (type === 'buy' || type === 'sell') {
          if (!(qty > 0)) return skip('невалидно количество', true);
          const px = isFinite(price.v) && price.v > 0 ? price.v : Math.abs(value.v / qty);
          recs.push({ ...b, line, kind: 'trade', assetClass: 'crypto', sym: r['symbol'], date: dt.date, time: dt.time, qty: type === 'buy' ? qty : -qty, price: px,
                      currency: price.cur || 'EUR', fee: isFinite(fee.v) ? Math.abs(fee.v) : 0, total: Math.abs(value.v) });
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
               reason: 'старият формат на извлечението на Revolut (Type, Product, Started Date…) не се чете — свали отчета „Crypto account statement“ / „Trading account statement“ (CSV)', taxable: true }] };
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
  TC.ratesNeeded = function (records, manual) {
    const out = {};
    // 13.11.2026: и курсовете за датите на въведените на ръка покупки (lot без покупна цена) — те не са във файловете
    Object.values(manual || {}).forEach(m => { if (m && m.date && m.currency && m.currency !== 'EUR') records = records.concat([{ currency: m.currency, date: m.date }]); });
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
  // сплит → позиция: същият брокер и сметка; ред от стандартен CSV без брокер / сметка ('*') важи за тикъра във всички сметки (без крипто) — 05.11.2026,
  // за сплит в Revolut (отчетът няма коефициента; „не е сметнато“ казва как да се добави)
  TC.splitApplies = (sp, broker, account, cls) => (sp.broker === '*' ? cls !== 'crypto' : sp.broker === broker) && (sp.account === '*' || sp.account === account);
  TC.positionKey = r => [r.broker, r.account, r.assetClass === 'crypto' ? 'crypto' : 'sec', r.sym].join('|');

  // opts.stillhalter (05.11.2026): 'receipt' (по подразбиране) — премията е доход в годината на получаване, обратното изкупуване — отрицателен доход в годината на плащане
  // (§20 ал. 1 т. 11 EStG, принципът на изтичане / Zufluss; да се потвърди); 'close' — нетно при затваряне / изтичане (поведението до 05.11).
  // 13.11.2026: ключът за ръчно въведена покупка на лот без покупна цена (прехвърляне от друг брокер, начална позиция без покупки…) — settings.manual[ключ] = {date, price, currency}
  TC.manualKey = (kind, broker, account, sym, date, qty) => ['m', kind, broker, account, sym, date, +Number(qty).toFixed(6)].join('|');
  TC.dmy = d => /^\d{4}-\d{2}-\d{2}/.test(String(d)) ? `${String(d).slice(8, 10)}.${String(d).slice(5, 7)}.${String(d).slice(0, 4)}` : String(d || '');
  TC.fifo = function (records, rate, opts) {
    opts = opts || {};
    const stillhalter = opts.stillhalter === 'close' ? 'close' : 'receipt';
    const pos = {}, realized = [], unmatched = [], missingRates = [], incomes = [], notes = [];
    const P = k => (pos[k] = pos[k] || { long: [], short: [], deficit: 0, taintedFrom: null });
    const tainted = {};                                                            // ключ → първата непокрита продажба (резултатите след нея — несигурни)
    const eps = 1e-9;
    // ─── 13.11.2026: контроли по началните / крайните позиции, прехвърляния, лотове без покупна цена ───
    const manual = opts.manual || {}, transit = {}, controlLog = [], endChecks = [], pending = [];
    const longOf = p => p.long.reduce((a, l) => a + l.qty, 0), shortOf = p => p.short.reduce((a, l) => a + l.qty, 0);
    const takeOldest = (p, q) => {                                                 // най-старите лотове първо; цената — пропорционално
      const taken = [];
      while (q > eps && p.long.length) {
        const l = p.long[0], used = Math.min(l.qty, q), f = used / l.qty;
        taken.push({ ...l, qty: used, costEUR: l.costEUR == null ? null : l.costEUR * f, feeEUR: l.feeEUR == null ? null : l.feeEUR * f });
        if (l.costEUR != null) l.costEUR -= l.costEUR * f;
        if (l.feeEUR != null) l.feeEUR -= l.feeEUR * f;
        l.qty -= used; q -= used;
        if (l.qty <= eps) p.long.shift();
      }
      return taken;
    };
    // лот без покупна цена: цената и датата се въвеждат на ръка (settings.manual) — до тогава резултатът е null, НИКОГА цена 0
    const addUnknownLot = (p, kind, r, qty, desc) => {
      const key = TC.manualKey(kind, r.broker, r.account, r.sym, r.date, qty), m = manual[key];
      let lot;
      if (m && m.date && Number(m.price) > 0) {
        const cur = m.currency || r.currency || 'USD', fxm = rate(cur, m.date);
        if (fxm == null) missingRates.push({ kind: 'trade', sym: r.sym, date: m.date, currency: cur, src: r.src });
        lot = { qty, costEUR: fxm == null ? null : qty * Number(m.price) / fxm, date: m.date, feeEUR: 0, manual: true };
      } else lot = { qty, costEUR: null, date: r.date, feeEUR: null, unknown: { key, kind, desc, date: r.date } };
      p.long.push(lot); p.long.sort((x, y) => x.date.localeCompare(y.date));
      pending.push({ key, kind, broker: r.broker, account: r.account, sym: r.sym, date: r.date, qty: +qty.toFixed(6), desc, currency: r.currency || 'USD', filled: !!lot.manual });
    };
    const runStart = c => {                                                        // начало на отчета: FIFO срещу Prior Quantity на сметката
      const startYear = Number(c.date.slice(0, 4)), prevY = c.prevEnd ? Number(c.prevEnd.slice(0, 4)) : null, gapYears = [];
      if (prevY != null) for (let y = prevY + 1; y < startYear; y++) gapYears.push(y);
      // 14.11.2026: липсващ период, който не е цяла календарна година (отчетите не са по календарни години) — от деня след края на предишния отчет до деня преди началото на този; над 31 дни
      const gapDays = c.prevEnd ? Math.round((new Date(c.date + 'T12:00:00Z') - new Date(c.prevEnd + 'T12:00:00Z')) / 86400000) - 1 : 0;
      const gapPeriod = (!gapYears.length && gapDays > 31) ? { from: TC.addDays(c.prevEnd, 1), to: TC.addDays(c.date, -1) } : null;
      const nRep = Object.values(c.positions).filter(v => v > eps).length;
      Object.keys(pos).forEach(k => {
        const [b, a, kind, ...rest] = k.split('|'), sym = rest.join('|'), p = pos[k];
        if (b !== c.broker || a !== c.account || kind !== 'sec' || (p.cls !== 'stock' && p.cls !== 'fund')) return;
        const H = longOf(p), R = Math.max(0, c.positions[sym] || 0);
        if (H > R + eps) {                                                         // излишък: най-старите лотове не се ползват (продажбите им са в период, който няма отчет)
          const dropped = takeOldest(p, H - R);
          controlLog.push({ type: 'start', date: c.date, year: startYear, account: a, sym, held: +H.toFixed(6), reported: R, dropped: +(H - R).toFixed(6), lots: dropped.map(l => ({ date: l.date, qty: +l.qty.toFixed(6) })), gapYears, gapPeriod, prevEnd: c.prevEnd || '', positions: nRep, file: c.file });
        }
      });
      Object.entries(c.positions).forEach(([sym, R]) => {                          // липса: отчетът показва позиция, за която във файловете няма покупки → лот без цена (на ръка), не нула
        if (!(R > eps)) return;
        const k = [c.broker, c.account, 'sec', sym].join('|'), p = P(k); if (!p.cls) p.cls = 'stock';
        if (p.cls !== 'stock' && p.cls !== 'fund') return;
        const H = longOf(p);
        if (H < R - eps) {
          addUnknownLot(p, 'start', { broker: c.broker, account: c.account, sym, date: c.date, currency: 'USD', src: c.file }, R - H, 'начална позиция по отчета, за която във файловете няма покупки');
          controlLog.push({ type: 'start_short', date: c.date, year: startYear, account: c.account, sym, held: +H.toFixed(6), reported: R, missing: +(R - H).toFixed(6), gapYears, gapPeriod, prevEnd: c.prevEnd || '', positions: nRep, file: c.file });
        }
      });
    };
    const runEnd = c => {                                                          // край на отчета: FIFO срещу Open Positions / Current Quantity — само показва, нищо не трие
      const rep = c.positions || {}, syms = new Set(Object.keys(rep)), allZero = !Object.values(rep).some(v => Math.abs(v) > eps);
      Object.keys(pos).forEach(k => { const [b, a, kind, ...rest] = k.split('|'); if (b === c.broker && a === c.account && kind === 'sec') syms.add(rest.join('|')); });
      syms.forEach(sym => {
        const p = pos[[c.broker, c.account, 'sec', sym].join('|')];
        if (c.scope === 'stocks' && p && p.cls !== 'stock' && p.cls !== 'fund') return;
        const H = p ? longOf(p) - shortOf(p) : 0, R = rep[sym] || 0;
        if (Math.abs(H - R) > 1e-6) endChecks.push({ account: c.account, sym, date: c.date, year: Number(c.date.slice(0, 4)), reported: R, computed: +H.toFixed(6), file: c.file, source: c.source || '', closed: allZero });
      });
    };
    const ctls = (opts.controls || []).slice().sort((a, b) => a.date.localeCompare(b.date) || (a.type === 'end' ? -1 : 1));
    const flush = (d, final) => { while (ctls.length && (final || (ctls[0].type === 'start' ? ctls[0].date <= d : ctls[0].date < d))) { const c = ctls.shift(); if (c.type === 'start') runStart(c); else runEnd(c); } };
    // 14.11.2026: прехвърляне „In“ от друг брокер → покупката се търси във FIFO на ДРУГИТЕ брокери (същият тикър — главни букви, без интервали и точки; същият собственик; до датата на прехвърлянето:
    // записите се обработват по дата, така че при другия брокер са само покупките до нея). Намерените лотове се пренасят с оригиналните дата, количество и цена и излизат от другия брокер (който
    // лот е излязъл — по FIFO: предположение). Недостигът — лот без покупна цена (на ръка). Ръчно въведена покупка има предимство; настройка opts.xferLink = false изключва търсенето.
    const normSym = x => String(x || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    const xferLinks = [], ownerOf = {};
    const linkCross = (r, p, qty) => {                                             // → останалото количество, което не е намерено
      if (opts.xferLink === false) return qty;
      const m0 = manual[TC.manualKey('acats', r.broker, r.account, r.sym, r.date, qty)];
      if (m0 && m0.date && Number(m0.price) > 0) return qty;
      let need = qty; const parts = [];
      Object.keys(pos).sort().forEach(k => {
        if (need <= eps) return;
        const [b, a, kind, ...rest] = k.split('|'), sym = rest.join('|'), q0 = pos[k];
        if (b === r.broker || kind !== 'sec' || normSym(sym) !== normSym(r.sym) || (q0.cls !== 'stock' && q0.cls !== 'fund') || (ownerOf[k] || 'A') !== (r.owner || 'A')) return;
        const have = longOf(q0); if (have <= eps) return;
        const taken = takeOldest(q0, Math.min(have, need));
        taken.forEach(l => p.long.push(l)); p.long.sort((x, y) => x.date.localeCompare(y.date));
        parts.push({ broker: b, account: a, lots: taken.map(l => ({ date: l.date, qty: +l.qty.toFixed(6), unknown: !!l.unknown })) });
        need -= taken.reduce((sum, l) => sum + l.qty, 0);
      });
      if (parts.length) {
        const got = qty - Math.max(0, need);
        xferLinks.push({ sym: r.sym, date: r.date, broker: r.broker, account: r.account, qty: +qty.toFixed(6), linked: +got.toFixed(6), rest: +Math.max(0, need).toFixed(6), parts });
        notes.push({ sym: r.sym, date: r.date, level: 'info', text: `${+got.toFixed(6)} от ${+qty.toFixed(6)} бр., прехвърлени от друг брокер, са свързани с покупките при ${[...new Set(parts.map(x => x.broker))].join(', ')}: ${parts.map(x => x.lots.map(l => `${l.qty} бр. от ${TC.dmy(l.date)}${l.unknown ? ' (без цена)' : ''}`).join(', ')).join('; ')} — лотовете минават с оригиналните дати и цени; кои лотове са излезли от другия брокер — по FIFO (предположение)${need > eps ? `; за останалите ${+need.toFixed(6)} бр. покупката не е намерена` : ''}` });
      }
      return Math.max(0, need);
    };
    const handleXfer = r => {                                                      // Transfers: Inter-Company пренася лотовете; „In“ от друг брокер — лот без цена; „Out“ — лотовете излизат
      const k = TC.positionKey(r), p = P(k), q = r.qty, inter = /inter-?company|internal|intra/i.test(r.xtype || ''), tk = [r.broker, r.sym, r.date, +q.toFixed(6)].join('|');
      if (!p.cls) p.cls = r.assetClass;
      const mk = a => TC.maskAccount(a);
      if (r.dir === 'Out') {
        const taken = takeOldest(p, q), got = taken.reduce((a, l) => a + l.qty, 0);
        if (inter) (transit[tk] = transit[tk] || []).push({ lots: taken, from: r.account, got, q, date: r.date, sym: r.sym });
        else notes.push({ sym: r.sym, date: r.date, level: 'info', text: `прехвърлени ${q} бр. към друг брокер / сметка (${r.xtype || 'прехвърляне'}) — не е продажба; лотовете са махнати от FIFO` });
        if (got < q - eps) notes.push({ sym: r.sym, date: r.date, level: 'warn', text: `прехвърлени ${q} бр. от ${mk(r.account)}, а във FIFO има само ${+got.toFixed(6)} — липсват покупки за ${+(q - got).toFixed(6)} бр.` });
        return;
      }
      const tr = inter && transit[tk] && transit[tk].length ? transit[tk].shift() : null;
      if (tr) {
        tr.lots.forEach(l => p.long.push(l)); p.long.sort((x, y) => x.date.localeCompare(y.date));       // FIFO е по датата на ПОКУПКАТА — пренесените лотове запазват оригиналната си дата
        notes.push({ sym: r.sym, date: r.date, level: 'info', text: `Inter-Company: ${q} бр. от ${mk(tr.from)} към ${mk(r.account)} — лотовете са пренесени с оригиналните дати и цени (не е продажба)` });
        if (tr.got < q - eps) addUnknownLot(p, 'xfer', r, q - tr.got, `Inter-Company прехвърляне, за което в изпращащата сметка няма достатъчно покупки`);
        return;
      }
      let qIn = q;
      if (!inter) { qIn = linkCross(r, p, q); if (qIn <= eps) return; }                 // 14.11: покупката при другия брокер (ако отчетът му е качен)
      addUnknownLot(p, inter ? 'xfer' : 'acats', r, qIn, `${r.xtype || 'прехвърляне'} „In“ ${inter ? 'без съответен „Out“ във файловете' : 'от друг брокер'}${r.xco && r.xco !== '--' ? ' (' + r.xco + ')' : ''} — цената на придобиване е при другия брокер`);
    };
    const corp = Object.assign({ spinoff: 'manual', stockDividend: 'split' }, opts.corp || {});
    const sk = (b, a, sym) => [b, a, 'sec', sym].join('|');
    const handleCorp = r => {
      const fx0 = rate(r.currency, r.date);
      if (r.kind === 'exchange') {                                                  // смяна на тикър / ISIN, обратен сплит, сливане акции срещу акции: лотовете продължават (дата и обща цена се пазят), броят ×коефициента
        const po = P(sk(r.broker, r.account, r.sym)), pn = P(sk(r.broker, r.account, r.newSym));
        if (!po.cls) po.cls = 'stock'; if (!pn.cls) pn.cls = 'stock';
        const taken = takeOldest(po, r.qtyOld), got = taken.reduce((a, l) => a + l.qty, 0);
        taken.forEach(l => pn.long.push({ ...l, qty: l.qty * r.factor })); pn.long.sort((x, y) => x.date.localeCompare(y.date));
        if (got < r.qtyOld - eps) addUnknownLot(pn, 'corp', { broker: r.broker, account: r.account, sym: r.newSym, date: r.date, currency: r.currency, src: r.src }, (r.qtyOld - got) * r.factor, `${r.sym} → ${r.newSym}: във FIFO липсват покупки за ${+(r.qtyOld - got).toFixed(6)} бр.`);
        notes.push({ sym: r.newSym, date: r.date, level: 'info', text: `${r.sym} → ${r.newSym}${r.ctype === 'mixed' ? ' (сливане с пари и акции)' : r.ctype === 'reverse_split' ? ' (обратен сплит с нов ISIN)' : ''}: ${+r.qtyOld.toFixed(6)} бр. стават ${+(r.qtyOld * r.factor).toFixed(6)} бр.; датите и общата цена на лотовете остават` });
        return;
      }
      if (r.kind === 'spinoff') {                                                   // отделяне: новите акции на втора компания; цената — на ръка (по подразбиране) или 0 (настройка)
        const pn = P(sk(r.broker, r.account, r.sym)); if (!pn.cls) pn.cls = 'stock';
        if (corp.spinoff === 'zero') { pn.long.push({ qty: r.qty, costEUR: 0, date: r.date, feeEUR: 0, spinoffZero: true }); pn.long.sort((x, y) => x.date.localeCompare(y.date)); notes.push({ sym: r.sym, date: r.date, level: 'warn', text: `отделяне: ${r.qty} бр. нови акции със СМЕТНАТА цена 0 € (настройка „нула“) — печалбата при продажба е цялата сума; спорно, провери` }); }
        else addUnknownLot(pn, 'spinoff', r, r.qty, 'отделяне на компания — покупната цена на новите акции (разпределена от старите) се въвежда на ръка');
        return;
      }
      if (r.kind === 'stockdiv') {                                                  // дивидент в акции
        const p = P(sk(r.broker, r.account, r.sym)), H = longOf(p); if (!p.cls) p.cls = 'stock';
        if (corp.stockDividend === 'income' && r.value > 0) {                       // доход по пазарна стойност + нов лот с тази цена
          if (fx0 == null) { missingRates.push({ kind: 'dividend', sym: r.sym, date: r.date, currency: r.currency, src: r.src }); return; }
          incomes.push({ kind: 'dividend', broker: r.broker, account: r.account, sym: r.sym, date: r.date, year: Number(r.date.slice(0, 4)), currency: r.currency, amount: r.value, eur: r.value / fx0, rate: fx0, desc: 'дивидент в акции — ' + r.desc, pil: false, src: r.src });
          p.long.push({ qty: r.qty, costEUR: r.value / fx0, date: r.date, feeEUR: 0 }); p.long.sort((x, y) => x.date.localeCompare(y.date));
          notes.push({ sym: r.sym, date: r.date, level: 'warn', text: `дивидент в акции: ${r.qty} бр. по пазарна стойност ${r.value} ${r.currency} — доход и цена на новите акции (настройка „доход“); спорно, провери` });
        } else if (H > eps) {                                                       // безплатни акции: лотовете ×(H+нови)/H, общата цена не се мени
          const ratio = (H + r.qty) / H; p.long.forEach(l => { l.qty *= ratio; });
          notes.push({ sym: r.sym, date: r.date, level: 'warn', text: `дивидент в акции: ${r.qty} бр. нови акции към ${+H.toFixed(6)} бр. — като безплатни акции (без доход, общата цена не се мени; настройка „като безплатни акции“); спорно, провери` });
        } else addUnknownLot(p, 'stockdiv', r, r.qty, 'дивидент в акции върху позиция, която във FIFO е празна');
      }
    };
    records.forEach(r => {
      flush(r.date, false);
      if (r.kind === 'trade' || r.kind === 'xfer') { const k0 = TC.positionKey(r); if (!(k0 in ownerOf)) ownerOf[k0] = r.owner || 'A'; }   // чия е позицията (за свързването между брокери)
      if (r.kind === 'exchange' || r.kind === 'spinoff' || r.kind === 'stockdiv') { handleCorp(r); return; }
      if (r.kind === 'xfer') { handleXfer(r); return; }
      if (r.kind === 'split') {                                                    // веднъж на позиция: ред от IBKR за сметката и ред „за всички сметки“ от стандартен CSV не се натрупват
        Object.keys(pos).forEach(k => {
          const [b, a, c, sym] = k.split('|'), sk = r.date + '|' + r.ratio, P0 = pos[k];
          if (sym !== r.sym || !TC.splitApplies(r, b, a, c) || (P0.splits = P0.splits || new Set()).has(sk)) return;
          P0.splits.add(sk); P0.long.concat(P0.short).forEach(l => { l.qty *= r.ratio; });
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
      if (!p.cls) p.cls = r.assetClass;
      const qAbs = Math.abs(r.qty);
      if (fx == null) missingRates.push({ kind: 'trade', sym: r.sym, date: r.date, currency: r.currency, src: r.src });
      const eur = v => fx == null ? null : v / fx;
      if (/(^|;)(A|Ex)(;|$)/.test(r.code || '')) notes.push({ sym: r.sym, date: r.date, text: 'упражнена / възложена опция — премията и акциите са сметнати отделно; да се потвърди' });
      const base = { broker: r.broker, account: r.account, owner: r.owner, sym: r.sym, assetClass: r.assetClass, date: r.date, year: Number(r.date.slice(0, 4)), currency: r.currency,
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
        lots.push({ date: l.date, qty: used, costEUR: cost, ...(l.unknown ? { unknown: l.unknown } : {}) });
        if (l.costEUR != null) l.costEUR -= cost;
        l.qty -= used; q -= used;
        if (l.qty <= eps) p.long.shift();
      }
      const matched = qAbs - q;
      if (matched > eps) {
        // 13.11.2026: продажба от лотове с известна цена И от лот без покупна цена → ДВА реда: известната част има резултат, частта без цена — null (въвежда се на ръка); преди цялата продажба оставаше без резултат
        const mkRec = ls => {
          const m = ls.reduce((a, x) => a + x.qty, 0), pr = proceedsAll == null ? null : proceedsAll * m / qAbs;
          const co = ls.some(x => x.costEUR == null) || pr == null ? null : ls.reduce((a, x) => a + x.costEUR, 0);
          const rec = { ...base, short: false, qty: m, proceedsEUR: pr, costEUR: co, gainEUR: co == null ? null : pr - co, lots: ls, tainted: !!tainted[k] };
          if (ls.some(x => x.unknown)) rec.unknownLots = ls.filter(x => x.unknown).map(x => ({ key: x.unknown.key, kind: x.unknown.kind, desc: x.unknown.desc, qty: x.qty, from: x.unknown.date }));   // лот без покупна цена — резултат null
          if (r.assetClass === 'crypto' && co != null) {                           // §23: над една година — освободено; годишнината (същата дата) е още в срока
            let ex = 0, tx = 0;
            ls.forEach(x => { const g = pr * x.qty / m - x.costEUR; x.exempt = r.date > TC.anniversary(x.date); if (x.exempt) ex += g; else tx += g; });
            rec.exemptGainEUR = ex; rec.taxableGainEUR = tx;
          }
          return rec;
        };
        const unkL = lots.filter(x => x.unknown), knownL = lots.filter(x => !x.unknown);
        if (unkL.length && knownL.length) { realized.push(mkRec(knownL)); realized.push(mkRec(unkL)); } else realized.push(mkRec(lots));
      }
      if (q > eps) {
        if (r.assetClass === 'option') {                                           // Stillhalter: продажба без позиция отваря къса позиция
          const prem = proceedsAll == null ? null : proceedsAll * q / qAbs;
          if (stillhalter === 'receipt') {                                          // премията — сега; при затварянето остава само цената на обратното изкупуване
            realized.push({ ...base, short: true, premium: true, qty: q, proceedsEUR: prem, costEUR: prem == null ? null : 0, gainEUR: prem, lots: [] });
            p.short.push({ qty: q, proceedsEUR: 0, date: r.date });
          } else p.short.push({ qty: q, proceedsEUR: prem, date: r.date });
        } else {
          unmatched.push({ broker: r.broker, account: r.account, sym: r.sym, date: r.date, year: Number(r.date.slice(0, 4)), qty: q, sold: qAbs, src: r.src });   // sold — цялата продажба; qty — частта без покупка
          p.deficit += q;
          if (!tainted[k]) tainted[k] = { key: k, broker: r.broker, account: r.account, sym: r.sym, from: r.date };
        }
      }
    });
    flush('', true);
    Object.values(transit).forEach(l => l.forEach(t => notes.push({ sym: t.sym, date: t.date, level: 'warn', text: `Inter-Company „Out“ от ${TC.maskAccount(t.from)} (${+t.q.toFixed(6)} бр.) няма съответен „In“ във файловете — лотовете са махнати от FIFO` })));
    const open = Object.entries(pos).map(([k, p]) => ({ key: k, long: p.long.reduce((s, l) => s + l.qty, 0), short: p.short.reduce((s, l) => s + l.qty, 0) }))
      .filter(o => o.long > eps || o.short > eps);
    return { realized, unmatched, missingRates, incomes, open, notes, stillhalter, tainted: Object.values(tainted), controlLog, endChecks, pending, xferLinks, controlsApplied: !!(opts.controls || []).length };
  };

  // ─── Сверка с наличностите от отчета на IBKR (Open Positions в края на периода) ─────────────────────
  // info: от ingest ([{file, broker, account, periodEnd, openPositions}]); records — всички записи. → [{account, sym, date, year, reported, computed, file}]
  TC.reconcile = function (records, info) {
    const out = [];
    // 13.11.2026: комбиниран отчет с няколко сметки — всяка сметка се сверява отделно (info.accounts); отчет с една сметка — както досега
    const perAccount = [];
    (info || []).filter(i => i.broker === 'IBKR' && i.periodEnd && Array.isArray(i.openPositions))
      .forEach(i => ((i.accounts && i.accounts.length) ? i.accounts : [i.account]).forEach(a => perAccount.push({ ...i, account: a })));
    perAccount.forEach(i => {
      const held = {};
      (records || []).forEach(r => {
        if (r.broker !== 'IBKR' || r.date > i.periodEnd) return;
        if (r.kind === 'trade' && r.account === i.account) held[r.sym] = (held[r.sym] || 0) + r.qty;
        const sk = r.sym + '|' + r.date + '|' + r.ratio;
        if (r.kind === 'split' && TC.splitApplies(r, 'IBKR', i.account, 'sec') && held[r.sym] != null && !(held['\u0000' + sk])) { held[r.sym] *= r.ratio; held['\u0000' + sk] = 1; }
      });
      const rep = {}; i.openPositions.filter(o => o.account === i.account).forEach(o => { rep[o.sym] = (rep[o.sym] || 0) + o.qty; });
      [...new Set(Object.keys(held).concat(Object.keys(rep)))].filter(sym => sym[0] !== '\u0000').forEach(sym => {
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
    // nonIbkrDefault (05.11.2026, спорно — настройка): видът на тикър без подсказка извън IBKR (Revolut / CSV не казват акция ли е или ETF): 'stock' (по подразбиране) | 'equity'
    const ibkrSyms = new Set((st.records || []).filter(r => r.broker === 'IBKR').map(r => r.sym));
    const fundType = (sym, hint) => (st.fundTypes || {})[sym] || (hint ? 'equity' : (st.nonIbkrDefault === 'equity' && !ibkrSyms.has(sym) ? 'equity' : 'stock'));
    const tfOf = t => (t === 'stock' || !tfRates) ? 0 : (tfRates[t] || 0);
    const R = fifoRes.realized.filter(x => x.year === year);
    // Vorabpauschale (05.11.2026): st.vorab = {тикър: {година X: EUR}} — сумата за X (всички дялове в края на X) се смята за получена на първия работен ден на X+1
    // (§18 ал. 3 InvStG) → доход в X+1; при продажба печалбата се намалява с Vorabpauschalen за годините, в чийто край продаденият лот е бил държан (§19 ал. 1),
    // пропорционално на броя дялове (сумата ÷ дяловете в края на X; сплит след X — превърнат). Да се потвърди за дялове, купени през годината (там се смята по месеци).
    const recs = st.records || [];
    const uniqSplit = () => { const seen = new Set(); return r => { const k = r.date + '|' + r.ratio; if (seen.has(k)) return false; seen.add(k); return true; }; };   // сплитът — веднъж за тикъра
    const unitsAt = (sym, d) => { let q = 0; const once = uniqSplit(); recs.forEach(r => { if (r.sym !== sym || r.date > d || r.assetClass === 'crypto') return; if (r.kind === 'trade') q += r.qty; else if (r.kind === 'split' && once(r)) q *= r.ratio; }); return q; };
    const splitFactor = (sym, after, upTo) => { const once = uniqSplit(); return recs.filter(r => r.kind === 'split' && r.sym === sym && r.date > after && r.date <= upTo && once(r)).reduce((f, r) => f * r.ratio, 1); };
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
      // creditPerItem (05.11.2026, по подразбиране — да): §32d ал. 5 EStG — и до германския данък по ТОЗИ доход (25% от облагаемата част след частичното освобождаване);
      // за акции не мени нищо, за фондове с голямо освобождаване — по-малко. Да се потвърди от счетоводител.
      const tf = st.creditPerItem === false ? 0 : tfOf(fundType(sym, instrHint(sym)));
      const cap = Math.max(0, gross) * Math.min(rate, st.creditPerItem === false ? Infinity : (par.abgeltung || 0.25) * (1 - tf));
      withheld += w; creditable += Math.min(w, cap);
    });
    const sum = cat => items.filter(i => i.cat === cat).reduce((s, i) => s + i.eur, 0);
    const shareGains = sum('shareGains'), shareLosses = -sum('shareLosses');
    const otherPos = ['dividends', 'interest', 'options', 'pil', 'funds'].reduce((s, c) => s + sum(c), 0);
    const otherNeg = -['optionLosses', 'fundLosses', 'otherNeg'].reduce((s, c) => s + sum(c), 0);
    const cS = Math.max(0, Number(st.carriedShareLoss) || 0), cO = Math.max(0, Number(st.carriedOtherLoss) || 0);
    // offsetOrder (05.11.2026, спорно — настройка; да се потвърди от счетоводител):
    //  'carriedShareFirst' (по подразбиране, както до 05.11) — пренесената загуба от акции се прилага към печалбите от акции преди загубите от годината в „друго“;
    //  'currentFirst' — първо загубите от годината (и „друго“ срещу печалбите от акции), после пренесените загуби.
    let shareNet, shareCarry = 0, total, otherCarry = 0;
    if (st.offsetOrder === 'currentFirst') {
      let s1 = shareGains - shareLosses, o = otherPos - otherNeg;
      if (s1 < 0) { shareCarry = -s1; s1 = 0; }
      if (o < 0 && s1 > 0) { const use = Math.min(s1, -o); s1 -= use; o += use; }
      s1 -= cS; if (s1 < 0) { shareCarry += -s1; s1 = 0; }
      shareNet = s1; total = s1 + o - cO;
    } else {
      shareNet = shareGains - shareLosses - cS;
      if (shareNet < 0) { shareCarry = -shareNet; shareNet = 0; }
      total = shareNet + otherPos - otherNeg - cO;
    }
    if (total < 0) { otherCarry = -total; total = 0; }
    const unknownKind = [...new Set(R.filter(x => x.assetClass === 'stock' && x.gainEUR != null && !ibkrSyms.has(x.sym) && !x.fundHint && !(st.fundTypes || {})[x.sym]).map(x => x.sym))];
    if (unknownKind.length) notes.push({ level: 'warn', text: `Видът на ${unknownKind.join(', ')} не идва от брокера (Revolut / CSV) — сметнати като ${st.nonIbkrDefault === 'equity' ? 'акционерни фондове (30% освобождаване)' : 'акции'}; ако някой е ETF / акция, смени го в таблицата с фондовете. Да се потвърди.` });
    // крипто §23 — по човек (сметките, отбелязани като на съпруга / съпругата → 'B')
    const persons = {}, soloB = new Set();
    R.filter(x => x.assetClass === 'crypto').forEach(x => {
      const who0 = (st.persons || {})[x.broker + '|' + x.account] || x.owner || 'A';
      if (who0 === 'B' && !st.joint) soloB.add(x.broker + ' ' + x.account);
      const who = st.joint ? who0 : 'A';                                          // „сам“ — един човек, дори ако някоя сметка е отбелязана като на съпруга
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
    if (soloB.size) notes.push({ level: 'warn', text: `Подаването е „сам“, а ${[...soloB].join(', ')} е отбелязано като на съпруга — криптото е сметнато към теб; махни файла или избери „съвместно“.` });
    // ориентировъчно: Sparer-Pauschbetrag, Abgeltungsteuer с църковния данък по формулата (e − 4q) / (4 + k), Soli
    // 05.11.2026: стари покупки и стари години — правилата се различават; калкулаторът не ги смята, а казва (и годината е „НЕПЪЛНО“)
    const oldRules = [];
    if (year < 2009) oldRules.push(`${year} е преди Abgeltungsteuer (2009) — старото право (Halbeinkünfteverfahren, едногодишен срок за акциите); калкулаторът не смята тази година.`);
    const lotsBefore = (x, d) => (x.lots || []).filter(l => l.date < d).reduce((q, l) => q + l.qty, 0);
    R.filter(x => x.assetClass !== 'crypto' && x.assetClass !== 'option' && x.gainEUR != null).forEach(x => {
      const isFund = fundType(x.sym, x.fundHint) !== 'stock';
      const q09 = lotsBefore(x, '2009-01-01'), q18 = lotsBefore(x, '2018-01-01');
      if (!isFund && q09 > 0 && year >= 2009) oldRules.push(`${x.sym} (${x.date}): ${+q09.toFixed(6)} бр. са купени преди 2009 (Altbestand) — печалбата от тях по правило е освободена; калкулаторът я е сметнал като облагаема. Да се потвърди.`);
      if (isFund && q18 > 0 && year >= 2018) oldRules.push(`${x.sym} (${x.date}): ${+q18.toFixed(6)} дяла са купени преди 2018 — фиктивна продажба на 31.12.2017 (§56 InvStG): печалбата до тогава е по старото право, без частично освобождаване${q09 > 0 ? '; дялове отпреди 2009 — освободени до 31.12.2017, след това облагаеми над 100 000 € на човек' : ''}. Калкулаторът е приложил освобождаването към цялата печалба. Да се потвърди.`);
    });
    oldRules.forEach(t => notes.push({ level: 'err', text: t + ' НЕПЪЛНО.' }));
    const pausch = (par.pauschbetrag || 0) * (st.joint ? 2 : 1);
    const e = Math.max(0, total - pausch);
    const k = st.kirche ? (TC.KIRCHE_RATES[st.kirche] || TC.KIRCHE_RATES.other) : 0;
    const q = Math.min(creditable, e / 4);
    const tax = Math.max(0, (e - 4 * q) / (4 + k));
    par.soli = par.soli || 0;
    const est = year < 2009 ? null : { pauschbetrag: pausch, taxableAfterPausch: e, creditUsed: q, kircheRate: k, abgeltung: tax, soli: tax * par.soli, kirche: tax * k, total: tax * (1 + par.soli + k) };
    // предупреждения
    const yEnd = `${year - 1}-12-31`;                                               // за Vorabpauschale, която е доход в тази година — държаните в края на предходната
    const held = {};
    (st.records || []).forEach(r => {
      if (r.date > yEnd) return;
      const key = TC.positionKey(r);
      if (r.kind === 'trade') held[key] = { ...(held[key] || {}), sym: r.sym, qty: ((held[key] || {}).qty || 0) + r.qty, hint: r.fundHint, cls: r.assetClass, broker: r.broker, account: r.account };
      if (r.kind === 'split') Object.keys(held).forEach(k2 => { const h = held[k2], sk = r.date + '|' + r.ratio;
        if (h.sym === r.sym && TC.splitApplies(r, h.broker, h.account, h.cls) && !(h.splits = h.splits || new Set()).has(sk)) { h.splits.add(sk); h.qty *= r.ratio; } });
    });
    const heldFunds = [...new Set(Object.values(held).filter(h => h.qty > 1e-9 && (h.cls === 'stock' || h.cls === 'fund') && fundType(h.sym, h.hint) !== 'stock').map(h => h.sym))];
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
    if ((fifoRes.notes || []).some(n => n.date.startsWith(String(year)))) fifoRes.notes.filter(n => n.date.startsWith(String(year))).forEach(n => notes.push({ level: n.level || 'warn', text: `${n.sym} (${n.date}): ${n.text}` }));
    const unmatched = (fifoRes.unmatched || []).filter(u => u.year === year);
    // 05.11.2026: несигурни резултати — продажби след непокрита продажба на същата позиция (и в следващите години) и разлики с наличностите в отчета на IBKR
    const taintedSales = R.filter(x => x.tainted);
    [...new Set(taintedSales.map(x => x.sym))].forEach(sym => {
      const t = (fifoRes.tainted || []).find(z => z.sym === sym);
      notes.push({ level: 'err', text: `${sym}: продажби в ${year} след непокрита продажба (${t ? t.from : '?'}) — цената на придобиване може да е грешна (липсващ по-стар отчет?). НЕПЪЛНО.` });
    });
    const mism = (fifoRes.controlsApplied ? (fifoRes.endChecks || []) : TC.reconcile(st.records, st.info)).filter(m => m.year === year || (m.year < year && R.some(x => x.broker === 'IBKR' && x.account === m.account && x.sym === m.sym)));
    // 05.11.2026: редове от „не е сметнато“ в тази година, които може да са облагаеми (размяна на крипто, сливане с пари, фючърси, нечетим ред…)
    // 13.11.2026: непознато корпоративно действие (ackKey) — червено, докато потребителят не потвърди ръчно, че няма ефект върху лотовете (st.manual[ackKey].ack)
    const acked = x => !!(x.ackKey && st.manual && st.manual[x.ackKey] && st.manual[x.ackKey].ack);
    const skippedTaxable = (st.skipped || []).filter(x => x.taxable && String(x.date || '').startsWith(String(year)) && !acked(x));
    skippedTaxable.filter(x => x.ackKey).forEach(x => notes.push({ level: 'err', text: `Корпоративно действие ${TC.dmy(x.date)} (${TC.maskAccount(x.account)}), описание от отчета: „${x.desc || x.what}“ — ${x.reason}.` }));
    if (skippedTaxable.length) notes.push({ level: 'err', text: `В „не е сметнато“ има ${skippedTaxable.length} ред(а) от ${year}, които може да са облагаеми (${[...new Set(skippedTaxable.map(x => x.what))].slice(0, 6).join(', ')}) — сметни ги отделно. НЕПЪЛНО.` });
    // 12.11.2026: ред без четима дата, който може да е облагаем (сделка с непознат формат на датата, липсваща колона) — годината му не се знае → всяка година е НЕПЪЛНО
    const skippedUndated = (st.skipped || []).filter(x => x.taxable && x.line && !/^\d{4}-\d{2}-\d{2}/.test(String(x.date || '')) && !acked(x));
    if (skippedUndated.length) notes.push({ level: 'err', text: `В „не е сметнато“ има ${skippedUndated.length} ред(а) без четима дата, които може да са облагаеми — не се знае за коя година са; ако са от ${year}, не са в числото. НЕПЪЛНО.` });
    // 12.11.2026: файл, който не е прочетен (непознат формат, грешка при четенето, стар формат на Revolut) — не се знае какво има в него → всяка година е НЕПЪЛНО
    const unreadFiles = (st.skipped || []).filter(x => x.taxable && !x.line && x.section === 'файл');
    unreadFiles.forEach(x => notes.push({ level: 'err', text: `Файлът „${x.what}“ не е прочетен (${x.reason}) — ако в него има сделки или доходи за ${year}, те не са в числото. НЕПЪЛНО.` }));
    mism.forEach(m => notes.push({ level: 'err', text: `${m.sym} (${TC.maskAccount(m.account)}): в края на ${m.date} отчетът на IBKR показва ${m.reported} бр., сметнатите сделки — ${m.computed} бр. ${m.closed ? '(отчетът не показва позиции в тази сметка — затворена ли е? Липсва прехвърляне, корпоративно действие или продажба?)' : '(липсва отчет или ред?)'}. НЕПЪЛНО.` }));
    (st.corpEvents || []).filter(e => e.disputed && ['mixed', 'cash_in_lieu', 'worthless'].includes(e.type) && String(e.date).startsWith(String(year)))
      .forEach(e => notes.push({ level: 'warn', text: `СПОРНО — ${e.sym}${e.newSym ? ' → ' + e.newSym : ''} (${TC.dmy(e.date)}, ${TC.maskAccount(e.account)}): ${e.why}. Описание от отчета: „${e.desc}“.` }));
    (st.info || []).forEach(i => { const m = (i.syep || []).filter(x => x.month.startsWith(String(year)) && x.ok);
      if (m.length) notes.push({ level: 'info', text: `SYEP (даване на акции назаем): сумата на дневните редове по месец = месечния ред в секция Interest (${m.map(x => `${x.month}: ${x.details.toFixed(2)}`).join(', ')}) — подробностите са вече включени, без двойно броене.` }); });
    // 13.11.2026: контрол в началото на отчета — излишъкът от лотове не се ползва (видимо, с годината и тикърите); липса → лот без покупна цена (на ръка)
    const ctlGroups = {};
    (fifoRes.controlLog || []).filter(c => c.year === year || (c.gapYears || []).includes(year)).forEach(c => { (ctlGroups[[c.type, c.account, c.date].join('|')] = ctlGroups[[c.type, c.account, c.date].join('|')] || []).push(c); });
    Object.values(ctlGroups).forEach(g => {
      const c0 = g[0], acct = TC.maskAccount(c0.account), npos = `${c0.positions} ${c0.positions === 1 ? 'позиция' : 'позиции'}`;
      if (c0.type === 'start') {
        const why = (c0.gapYears || []).length ? `Между отчетите липсва ${c0.gapYears.length > 1 ? 'години' : 'година'} ${c0.gapYears.join(', ')} — лотовете отпреди ${TC.dmy(c0.date)} не се ползват, защото отчетът за ${c0.year} (${acct}) започва ${c0.positions ? 'с ' + npos : 'без отворени позиции'}`
          : c0.gapPeriod ? `Между отчетите липсва период от ${TC.dmy(c0.gapPeriod.from)} до ${TC.dmy(c0.gapPeriod.to)} — лотовете отпреди ${TC.dmy(c0.date)} не се ползват, защото отчетът за ${c0.year} (${acct}) започва ${c0.positions ? 'с ' + npos : 'без отворени позиции'}`
          : `Отчетът за ${c0.year} (${acct}) започва ${c0.positions ? 'с ' + npos : 'без отворени позиции'} — лотовете отпреди ${TC.dmy(c0.date)} над тях не се ползват`;
        notes.push({ level: 'warn', text: `${why}: ${g.map(c => `${c.sym} (FIFO ${c.held} бр., отчет ${c.reported} бр. → без ${c.dropped} бр. от ${c.lots.map(l => TC.dmy(l.date)).join(', ')})`).join('; ')}. Продажбите през липсващия период не са в данните.` });
      } else notes.push({ level: 'warn', text: `Отчетът за ${c0.year} (${acct}) започва с позиции, за които във файловете няма покупки: ${g.map(c => `${c.sym} ${c.reported} бр. (покупки за ${c.held} бр.)`).join('; ')} — въведи покупна цена и дата (таблица „Липсва покупна цена“); до тогава продажбите им нямат резултат.` });
    });
    // лот без покупна цена (прехвърлен от друг брокер и др.): продажба от него няма резултат — НЕПЪЛНО; без продажба — само напомняне
    const unknownSales = R.filter(x => x.unknownLots && x.unknownLots.length);
    unknownSales.forEach(x => notes.push({ level: 'err', text: `${x.sym} (${x.date}): продажба на ${+x.qty.toFixed(6)} бр., от които ${+x.unknownLots.reduce((a, u) => a + u.qty, 0).toFixed(6)} бр. са от лот без покупна цена (${x.unknownLots[0].desc}; ${TC.dmy(x.unknownLots[0].from)}) — резултатът не е в числото; въведи покупна цена и дата. НЕПЪЛНО.` }));
    (fifoRes.pending || []).filter(pn => !pn.filled && pn.kind !== 'start' && pn.date.startsWith(String(year)) && !unknownSales.some(x => x.unknownLots.some(u => u.key === pn.key)))
      .forEach(pn => notes.push({ level: 'warn', text: `${pn.sym}: ${pn.qty} бр. прехвърлени от друг брокер на ${TC.dmy(pn.date)} — въведи покупна цена и дата (таблица „Липсва покупна цена“); до тогава продажбите им нямат резултат.` }));
    const missing = (fifoRes.missingRates || []).filter(m => m.date.startsWith(String(year)) || (R.some(x => x.gainEUR == null && x.sym === m.sym)));
    return {
      year, params: par, headline: total > 0 ? total : -(shareCarry + otherCarry), total, shareGains, shareLosses, shareNet, shareCarry, otherPos, otherNeg, otherCarry,
      carriedShareLoss: cS, carriedOtherLoss: cO, withheld, creditable, items, crypto: Object.values(persons).sort((a, b) => a.person.localeCompare(b.person)),
      estimate: est, notes, unmatched, missingRates: missing, funds: fundsSeen, heldFunds,
      complete: !unmatched.length && !missing.length && !taintedSales.length && !mism.length && !skippedTaxable.length && !oldRules.length && !unreadFiles.length && !skippedUndated.length && !unknownSales.length,
      pending: fifoRes.pending || [], controlLog: fifoRes.controlLog || [], reconcile: mism, skippedTaxable, unreadFiles, skippedUndated,
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

  // клетка за изтегления CSV: в кавички; текст, започващ с = + - @ (формула в Excel / LibreOffice), получава ' отпред — числата (−12.50) остават числа (05.11.2026)
  TC.csvCell = v => { let t = String(v == null ? '' : v); if (/^[=+\-@\t\r]/.test(t) && !/^[-+]?\d+(\.\d+)?$/.test(t)) t = "'" + t; return `"${t.replace(/"/g, '""')}"`; };

  TC.fmt = n => (n < 0 ? '−' : '') + Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' €';

  root.TaxCore = TC;
  if (typeof module !== 'undefined' && module.exports) module.exports = TC;
})(typeof window !== 'undefined' ? window : globalThis);
