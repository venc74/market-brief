#!/usr/bin/env node
/*
 * tools/tax_diagnose.js — диагноза на брокерски отчет през СТАРАТА (docs/tax-v1.html) и НОВАТА (docs/tax_core.js) логика на данъчния калкулатор (12.11.2026).
 *
 * Печата САМО структура и броеве: имена на секции, заглавните редове (етикетите на брокера), видове редове, ВИДА на клетките (дата / цяло число / текст…, не стойността),
 * броеве по причина, години. НЕ печата суми, количества, тикъри, номер на сметка, имена, описания и името на файла — изходът може да се покаже / постави в чат.
 * Сравнението стара ↔ нова е в брой и в проценти (новата като % от старата), без суми.
 *
 * Употреба:  node tools/tax_diagnose.js [--core път/tax_core.js] [--v1 път/tax-v1.html] [--rates път/eurofxref-hist.csv] [--year 2026] отчет.csv [още.csv …]
 *   --core   коя версия на новата логика (по подразбиране docs/tax_core.js; за „новата преди поправката“: git show main:docs/tax_core.js > /tmp/core_main.js)
 *   --rates  курсове на ЕЦБ от файл (по подразбиране docs/eurofxref-hist.csv) — без мрежа; старата логика получава същите курсове през подменен fetch
 *   --year   годината за сметката (по подразбиране — най-новата година с данни във файловете)
 * Отчетът остава където е — скриптът само чете; нищо не се записва и не се праща.
 */
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = path.join(__dirname, '..');
const args = process.argv.slice(2);
const opt = { core: path.join(ROOT, 'docs', 'tax_core.js'), v1: path.join(ROOT, 'docs', 'tax-v1.html'), rates: path.join(ROOT, 'docs', 'eurofxref-hist.csv'), year: null };
const files = [];
for (let i = 0; i < args.length; i++) {
  if (['--core', '--v1', '--rates', '--year'].includes(args[i])) opt[args[i].slice(2)] = args[++i];
  else files.push(args[i]);
}
if (!files.length) { console.error('Употреба: node tools/tax_diagnose.js [--core tax_core.js] [--rates eurofxref-hist.csv] [--year ГГГГ] отчет.csv …'); process.exit(2); }
const out = s => process.stdout.write(s + '\n');

// ─── клетка → ВИД (никога стойност) ─────────────────────────────────────────
function cellType(v) {
  const t = String(v == null ? '' : v);
  if (t === '') return 'празно';
  if (/^-{1,2}$/.test(t)) return '„--“';
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) return 'дата YYYY-MM-DD';
  if (/^\d{4}-\d{2}-\d{2}, \d{2}:\d{2}:\d{2}$/.test(t)) return 'дата и час „YYYY-MM-DD, HH:MM:SS“';
  if (/^\d{4}-\d{2}-\d{2}[ T;]\s*\d{2}:\d{2}/.test(t)) return 'дата и час (друг разделител)';
  if (/^\d{8}$/.test(t)) return '8 цифри (дата YYYYMMDD?)';
  if (/^\d{8};\d{6}$/.test(t)) return 'дата и час YYYYMMDD;HHMMSS';
  if (/^\d{1,2}\/\d{1,2}\/\d{2,4}/.test(t)) return 'дата с наклонени черти';
  if (/^\d{1,2}\.\d{1,2}\.\d{4}/.test(t)) return 'дата с точки (DD.MM.YYYY)';
  if (/^[A-Za-z]{3,9}\.? \d{1,2}, \d{4}/.test(t)) return 'дата с име на месец';
  if (/^[-+]?\d+$/.test(t)) return 'цяло число';
  if (/^[-+]?\d*\.\d+$/.test(t)) return 'десетично (точка)';
  if (/^[-+]?\d{1,3}(,\d{3})+$/.test(t)) return 'цяло с хилядни запетаи';
  if (/^[-+]?\d{1,3}(,\d{3})+\.\d+$/.test(t)) return 'десетично с хилядни запетаи';
  if (/^[-+]?\d+,\d+$/.test(t)) return 'десетична ЗАПЕТАЯ';
  if (/^[-+]?\d{1,3}(\.\d{3})+,\d+$/.test(t)) return 'десетична запетая с хилядни точки';
  if (/^\([\d.,]+\)$/.test(t)) return 'число в скоби';
  if (/^[-+]?[\d.,]+[eE][-+]?\d+$/.test(t)) return 'експоненциален запис';
  if (/^[-+]?[\d.,]+\s*%$/.test(t)) return 'процент';
  return 'текст';
}
// CSV ред → [{v, q}] (q — клетката е била в кавички)
function splitRaw(line) {
  const res = []; let cur = '', q = false, was = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++; } else { q = !q; was = true; } continue; }
    if (c === ',' && !q) { res.push({ v: cur.trim(), q: was }); cur = ''; was = false; continue; }
    cur += c;
  }
  res.push({ v: cur.trim(), q: was });
  return res;
}
const inc = (o, k, n) => { o[k] = (o[k] || 0) + (n == null ? 1 : n); return o; };
const counts = o => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ×${n}`).join(' · ') || '—';
// колони, чиито стойности са етикети на брокера (не лични данни) — печатат се самите стойности, ако са само букви / знаци (без цифри → без номера на сметки)
const ENUM_COLS = new Set(['DataDiscriminator', 'Asset Category', 'Currency', 'Type', 'Code', 'Field Name', 'Currency Summary', 'Subtitle']);
const safeEnum = v => /^[A-Za-z&/;.,()\- ]{0,48}$/.test(v) ? (v === '' ? '(празно)' : v) : '(друго)';
// стойности на полета, които не са лични: заглавието, периодът и основната валута
const SAFE_FIELDS = { 'Statement': ['Title', 'Period'], 'Account Information': ['Base Currency', 'Account Type', 'Customer Type'] };
const shape = v => String(v).replace(/[A-Za-zÀ-ɏЀ-ӿ]+/g, 'A').replace(/\d+/g, '9');   // „U1234567 (Xyz)“ → „A9 (A)“
// секции, по които се гледа и форматът на клетките
const DETAIL = new Set(['Trades', 'Dividends', 'Withholding Tax', 'Interest', 'Fees', 'Corporate Actions', 'Open Positions', 'Financial Instrument Information', 'Transfers',
  'Payment In Lieu Of Dividends', 'Deposits & Withdrawals', 'Transaction Fees', 'Sales Tax Details', 'Borrow Fee Details', 'Stock Yield Enhancement Program Securities Lent Interest Details']);

// ─── суровата структура на файла (независимо от двете логики) ─────────────────
function structure(text) {
  const bom = text.charCodeAt(0) === 0xFEFF;
  const crlf = /\r\n/.test(text);
  const lines = text.replace(/^﻿/, '').split(/\r?\n/);
  const sections = [], by = {}, cur = {};
  let dataNoHeader = 0, blank = 0;
  lines.forEach(line => {
    if (!line.trim()) { blank++; return; }
    const p = splitRaw(line), sec = p[0].v, typ = p[1] ? p[1].v : '';
    let s = by[sec];
    if (!s) { s = by[sec] = { name: sec, types: {}, headers: [], disc: {}, cells: {}, enums: {}, widths: {}, fields: [], headerWidthMismatch: 0 }; sections.push(s); }
    inc(s.types, typ || '(празно)');
    if (typ === 'Header') { const h = p.slice(2).map(x => x.v); cur[sec] = h; if (!s.headers.some(x => x.join('\u0001') === h.join('\u0001'))) s.headers.push(h); return; }
    if (typ !== 'Data') return;
    const h = cur[sec];
    if (!h) { dataNoHeader++; return; }
    const cells = p.slice(2);
    if (cells.length !== h.length) s.headerWidthMismatch++;
    inc(s.widths, cells.length);
    const r = {}; h.forEach((name, k) => { r[name] = cells[k] ? cells[k].v : ''; });
    if (sec === 'Trades' || sec === 'Open Positions') inc(s.disc, `${safeEnum(r['DataDiscriminator'] || '')} × ${safeEnum(r['Asset Category'] || '')}`);
    if ((SAFE_FIELDS[sec] || []).includes(r['Field Name'])) s.fields.push(`${r['Field Name']} = ${r['Field Value']}`);
    else if (sec === 'Account Information' && r['Field Name'] === 'Account') s.fields.push(`Account = (маскирано; форма „${shape(r['Field Value'])}“)`);
    h.forEach((name, k) => {
      const key = name === '' ? `(без име, колона ${k + 1})` : name;
      if (ENUM_COLS.has(name)) inc(s.enums[key] = s.enums[key] || {}, safeEnum(cells[k] ? cells[k].v : ''));
      if (DETAIL.has(sec) && !ENUM_COLS.has(name)) inc(s.cells[key] = s.cells[key] || {}, cellType(cells[k] ? cells[k].v : '') + (cells[k] && cells[k].q ? ' (в кавички)' : ''));
    });
  });
  return { bom, crlf, lines: lines.length, blank, sections, dataNoHeader };
}

// ─── старата логика: функциите от вградения скрипт на docs/tax-v1.html, с празен DOM и fetch от файла с курсовете ─────────────────
function loadV1(ratesTable) {
  const html = fs.readFileSync(opt.v1, 'utf8');
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!m) throw new Error('в tax-v1.html няма вграден скрипт');
  const el = new Proxy(function () {}, { get: (t, k) => (k === Symbol.toPrimitive ? () => '' : k === 'then' ? undefined : el), set: () => true, apply: () => el, construct: () => el });
  const rateOn = (cur, d) => { const a = ratesTable[cur] || []; const hit = a.find(x => x[0] === d); return hit ? hit[1] : null; };
  const fetchStub = async url => {                                   // ЕЦБ: ?startPeriod=D&endPeriod=D — точно за деня (старата сама върви до 6 дни назад); frankfurter — няма
    const u = new URL(url), cur = (u.pathname.match(/D\.([A-Z]{3})\.EUR/) || [])[1], d = u.searchParams.get('startPeriod');
    const r = cur && d ? rateOn(cur, d) : null;
    if (r == null) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ({ dataSets: [{ series: { '0:0:0:0:0': { observations: { 0: [r] } } } }] }) };
  };
  const ctx = { document: el, window: {}, console: { log() {}, warn() {}, error() {} }, fetch: fetchStub, setTimeout, URL, FileReader: function () {}, Blob: function () {} };
  vm.createContext(ctx);
  vm.runInContext(m[1], ctx);
  ['isIBKR', 'parseIBKR', 'parseStd', 'splitCSVLine', 'enrichRates', 'calcFIFO', 'calcDE'].forEach(f => { if (typeof ctx[f] !== 'function') throw new Error('tax-v1.html: липсва функцията ' + f); });
  return ctx;
}
// кои редове спира всеки филтър на старата (тя чете по ПОЗИЦИЯ) и какво стои в истинския заглавен ред на позициите, които чете
function v1Trace(text, v1) {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/);
  const t = { rows: 0, order: 0, cat: 0, valid: 0, short: 0 }, heads = { Trades: [], Dividends: [], 'Withholding Tax': [] };
  const div = { rows: 0, valid: 0, nonPositive: 0 }, wh = { rows: 0, valid: 0 };
  lines.forEach(line => {
    const p = v1.splitCSVLine(line);
    if (heads[p[0]] && p[1] === 'Header') heads[p[0]].push(p);
    if (p[0] === 'Trades' && p[1] === 'Data') {
      t.rows++;
      if (p.length < 10) { t.short++; return; }
      if (p[2] !== 'Order') return; t.order++;
      if (!['Stocks', 'ETF'].includes(p[3])) return; t.cat++;
      const q = parseFloat(p[8].replace(/[",]/g, '')), px = parseFloat(p[9].replace(/[",]/g, '')), d = p[7].replace(/"/g, '').trim().substring(0, 10);
      if (isNaN(q) || q === 0 || isNaN(px) || !/^\d{4}-\d{2}-\d{2}$/.test(d)) return; t.valid++;
    }
    if (p[0] === 'Dividends' && p[1] === 'Data' && p.length >= 6) {
      div.rows++; const a = parseFloat(p[6]), d = (p[4] || '').trim().substring(0, 10);
      if (!isNaN(a) && a <= 0) div.nonPositive++;
      if (!isNaN(a) && a > 0 && /^\d{4}-\d{2}-\d{2}$/.test(d)) div.valid++;
    }
    if (p[0] === 'Withholding Tax' && p[1] === 'Data' && p.length >= 6) { wh.rows++; if (!isNaN(Math.abs(parseFloat(p[6])))) wh.valid++; }
  });
  const at = (h, idx) => idx.map(i => `[${i}] = ${h[i] === undefined ? '(няма такава колона)' : (h[i] === '' ? '(без име)' : h[i])}`).join(' · ');
  return { t, div, wh, pos: { Trades: heads.Trades.map(h => at(h, [2, 3, 4, 5, 6, 7, 8, 9])), Dividends: heads.Dividends.map(h => at(h, [2, 3, 4, 5, 6])), 'Withholding Tax': heads['Withholding Tax'].map(h => at(h, [2, 3, 4, 5, 6])) } };
}

// ─── основното ───────────────────────────────────────────────────────────────
(async () => {
  const TC = require(path.resolve(opt.core));
  const ratesText = fs.existsSync(opt.rates) ? fs.readFileSync(opt.rates, 'utf8') : '';
  const table = ratesText ? TC.parseECBcsv(ratesText) : {};
  const v1 = loadV1(table);
  const texts = files.map((f, i) => ({ name: `файл ${i + 1}`, text: fs.readFileSync(f, 'utf8') }));
  out(`ДИАГНОЗА — ${texts.length} файл(а); новата логика: ${path.relative(ROOT, path.resolve(opt.core)) || opt.core}; курсове: ${ratesText ? 'ЕЦБ от файл (' + Object.keys(table).length + ' валути)' : 'НЯМА файл с курсове'}`);
  out('Само структура и броеве — без суми, тикъри, сметки и имена.\n');

  // 1) структурата на всеки файл
  texts.forEach(f => {
    const s = structure(f.text);
    out(`════ ${f.name}: ${s.lines} реда (${s.blank} празни) · BOM: ${s.bom ? 'да' : 'не'} · край на реда: ${s.crlf ? 'CRLF' : 'LF'} · секции: ${s.sections.length}${s.dataNoHeader ? ` · Data редове без заглавен ред: ${s.dataNoHeader}` : ''}`);
    s.sections.forEach(sec => {
      out(`\n[${sec.name}] редове: ${counts(sec.types)}`);
      sec.headers.forEach((h, i) => out(`   заглавен ред ${i + 1} (${h.length} колони): ${h.map(x => x === '' ? '(без име)' : x).join(' | ')}`));
      if (sec.headerWidthMismatch) out(`   ! ${sec.headerWidthMismatch} Data реда с различен брой клетки от заглавния ред (клетки на ред: ${counts(sec.widths)})`);
      if (sec.fields.length) out(`   полета: ${sec.fields.join(' · ')}`);
      if (Object.keys(sec.disc).length) out(`   Data по DataDiscriminator × Asset Category: ${counts(sec.disc)}`);
      Object.entries(sec.enums).forEach(([c, v]) => { const e = Object.entries(v); out(`   стойности на „${c}“: ${e.slice(0, 24).map(([k, n]) => `${k} ×${n}`).join(' · ')}${e.length > 24 ? ` · … още ${e.length - 24}` : ''}`); });
      if (DETAIL.has(sec.name)) Object.entries(sec.cells).forEach(([c, v]) => out(`   вид на клетките „${c}“: ${counts(v)}`));
    });
    out('');
  });

  // 2) старата логика (tax-v1)
  out('════ СТАРАТА ЛОГИКА (docs/tax-v1.html) — чете по ПОЗИЦИЯ в реда');
  let v1tx = [];
  texts.forEach(f => {
    const is = v1.isIBKR(f.text);
    let txs = [], err = '';
    try { txs = is ? v1.parseIBKR(f.text, f.name) : v1.parseStd(f.text, f.name); } catch (e) { err = String(e.message).replace(/^.*?:\s*/, ''); }
    v1tx = v1tx.concat(txs);
    out(`${f.name}: разпознат като IBKR: ${is ? 'да' : 'не'}${err ? ' · ГРЕШКА: ' + err : ''}`);
    if (is) {
      const tr = v1Trace(f.text, v1);
      tr.pos.Trades.forEach((p, i) => out(`   Trades, заглавен ред ${i + 1} — на позициите, които чете (иска [2]=вид ред, [3]=Asset Category, [4]=Currency, [6]=Symbol, [7]=Date/Time, [8]=Quantity, [9]=T. Price): ${p}`));
      tr.pos.Dividends.forEach((p, i) => out(`   Dividends, заглавен ред ${i + 1} (иска [2]=Currency, [4]=Date, [5]=Description, [6]=Amount): ${p}`));
      tr.pos['Withholding Tax'].forEach((p, i) => out(`   Withholding Tax, заглавен ред ${i + 1} (иска [2]=Currency, [4]=Date, [5]=Description, [6]=Amount): ${p}`));
      out(`   Trades: Data редове ${tr.t.rows} → „Order“ ${tr.t.order} → Stocks / ETF ${tr.t.cat} → с количество, цена и дата ${tr.t.valid}${tr.t.short ? ` (под 10 клетки: ${tr.t.short})` : ''}`);
      out(`   Dividends: Data редове ${tr.div.rows} → положителни с дата ${tr.div.valid} (нулеви / отрицателни — сторно, изхвърлени: ${tr.div.nonPositive}) · Withholding Tax: ${tr.wh.rows} реда`);
    }
    out(`   сделки в сметката: покупки ${txs.filter(t => t.type === 'buy').length} · продажби ${txs.filter(t => t.type === 'sell').length} · дивиденти ${txs.filter(t => t.type === 'dividend').length}`);
  });

  // 3) новата логика
  out('\n════ НОВАТА ЛОГИКА (tax_core.js) — чете по ИМЕ на колоната от заглавния ред');
  const ing = TC.ingest(texts.map(f => ({ name: f.name, text: f.text })));
  ing.files.forEach((f, i) => {
    const recs = ing.records.filter(r => r.src === f.name), sk = ing.skipped.filter(s => s.src === f.name);
    const k = {}; recs.forEach(r => inc(k, r.kind));
    const tr = recs.filter(r => r.kind === 'trade'), cls = {}; tr.forEach(r => inc(cls, r.assetClass));
    out(`${f.name}: формат „${f.format}“${f.error ? ' · ГРЕШКА: ' + f.error : ''} · записи ${f.records} (след дубликати: ${recs.length}) · „не е сметнато“ ${sk.length}`);
    out(`   записи по вид: сделки ${k.trade || 0} (покупки ${tr.filter(r => r.qty > 0).length}, продажби ${tr.filter(r => r.qty < 0).length}; по клас: ${counts(cls)}) · дивиденти ${k.dividend || 0} · удържан данък ${k.withholding || 0} · лихви ${k.interest || 0} · сплитове ${k.split || 0}`);
    const yr = {}; recs.forEach(r => inc(yr, r.date.slice(0, 4))); out(`   записи по години: ${Object.keys(yr).sort().map(y => `${y}: ${yr[y]}`).join(' · ') || '—'}`);
    const why = {}; sk.forEach(s => inc(why, `[${s.section}] ${String(s.reason).replace(/„[^“]*“/g, '„…“')}${s.taxable ? ' (може да е облагаем)' : ''}`));
    Object.entries(why).forEach(([r, n]) => out(`   не е сметнато ×${n}: ${r}`));
    // редове, които нямат следа: Data редове в секцията − записи − „не е сметнато“ (обобщения, ClosedLot, тихо изпуснати)
    const st = structure(texts[i].text);
    const bySec = {}; recs.forEach(r => { const line = texts[i].text.replace(/^﻿/, '').split(/\r?\n/)[r.line - 1] || ''; inc(bySec, splitRaw(line)[0].v); });
    const skSec = {}; sk.forEach(s => inc(skSec, s.section));
    st.sections.filter(s => (s.types.Data || 0) > 0).forEach(s => {
      const data = s.types.Data || 0, used = bySec[s.name] || 0, skp = skSec[s.name] || 0, rest = data - used - skp;
      if (used || skp || DETAIL.has(s.name)) out(`   [${s.name}] Data ${data} → записи ${used} · „не е сметнато“ ${skp} · без следа ${rest}${rest > 0 && s.name === 'Trades' ? ' (ClosedLot / обобщения — виж DataDiscriminator горе)' : ''}`);
    });
    const unknown = st.sections.filter(s => (s.types.Data || 0) > 0 && !(bySec[s.name] || skSec[s.name]) && !DETAIL.has(s.name)).map(s => `${s.name} (${s.types.Data})`);
    if (unknown.length) out(`   секции с Data редове, които новата логика не чете и не отбелязва: ${unknown.join(' · ')}`);
    if (f.sections) out(`   собствената сметка на редовете (tax_core): ${f.sections.map(s => `${s.name}: ${s.data} = ${s.records} записа + ${s.skipped} не е сметнато + ${s.ignored} обобщения`).join(' · ')}`);
  });

  // 4) сметката по години, стара ↔ нова
  const rate = TC.rateLookup(table);
  const res = TC.fifo(ing.records, rate);
  const years = [...new Set(ing.records.map(r => Number(r.date.slice(0, 4))))].sort();
  const year = opt.year ? Number(opt.year) : years[years.length - 1];
  const nowY = new Date().getFullYear();
  out(`\n════ СМЕТКАТА — години с данни: ${years.join(', ') || 'няма'}; сравнението е за ${year}`);
  out(`FIFO (нова): продажби с резултат ${res.realized.length} · продажби без покупка ${res.unmatched.length} · записи без курс ${res.missingRates.length} · отворени позиции в края ${res.open.length}`);
  years.forEach(y => {
    const de = TC.computeDE(res, { year: y, records: ing.records, info: ing.info, skipped: ing.skipped });
    const R = res.realized.filter(x => x.year === y);
    out(`   ${y}: продажби ${R.length} (без курс: ${R.filter(x => x.gainEUR == null).length}) · без покупка ${de.unmatched.length} · числото най-горе: ${de.headline === 0 ? 'НУЛА' : de.headline > 0 ? 'положително' : 'отрицателно'} · ${de.complete ? 'пълно' : 'НЕПЪЛНО'}` +
        ` · грешки: ${de.notes.filter(n => n.level === 'err').length} · разлики с Open Positions: ${(de.reconcile || []).length}`);
  });
  const dflt = years.includes(nowY - 1) ? nowY - 1 : null;
  out(`   годината, с която страницата тръгва днес (main): ${nowY - 1} — записи за нея: ${ing.records.filter(r => r.date.startsWith(String(nowY - 1))).length}${dflt == null ? '  ← няма данни за тази година: числото е 0, докато годината не се смени на ръка' : ''}`);

  if (v1tx.length) {
    const enriched = await v1.enrichRates(v1tx, () => {});
    const noRate = enriched.filter(t => t.rateError).length;
    const { breakdown, dividends } = v1.calcFIFO(enriched, year);
    const de1 = v1.calcDE(breakdown, dividends, 0, false, 30);
    // продажби, за които старата няма (цялата) покупка — тя ги смята с цена на придобиване 0 за липсващата част
    const q = {}; let uncovered = 0;
    enriched.filter(t => t.type === 'buy').sort((a, b) => a.date.localeCompare(b.date)).forEach(t => { if (t.date <= `${year}-12-31`) q[t.ticker] = (q[t.ticker] || 0) + t.quantity; });
    enriched.filter(t => t.type === 'sell' && t.date.startsWith(String(year))).forEach(t => { const have = q[t.ticker] || 0; if (have + 1e-9 < t.quantity) uncovered++; q[t.ticker] = Math.max(0, have - t.quantity); });
    const de2 = TC.computeDE(res, { year, records: ing.records, info: ing.info, skipped: ing.skipped });
    const R2 = res.realized.filter(x => x.year === year && x.assetClass !== 'crypto' && x.assetClass !== 'option');
    const new2 = { sales: R2.length, gain: R2.filter(x => x.gainEUR != null).reduce((s, x) => s + x.gainEUR, 0), div: res.incomes.filter(x => x.year === year && x.kind === 'dividend').reduce((s, x) => s + x.eur, 0),
                   divN: res.incomes.filter(x => x.year === year && x.kind === 'dividend').length, wh: de2.withheld, interestN: res.incomes.filter(x => x.year === year && x.kind === 'interest').length };
    const pct = (a, b) => (!isFinite(a) || !isFinite(b)) ? 'не се сравнява (NaN)' : Math.abs(b) < 0.005 ? (Math.abs(a) < 0.005 ? 'и двете са 0' : 'старата е 0, новата не е') : (a / b * 100).toFixed(2) + '% от старата';
    out(`\n════ СТАРА ↔ НОВА за ${year} (брой и проценти, без суми)`);
    out(`   сделки за сметката (всички години): стара ${v1tx.filter(t => t.type !== 'dividend').length} · нова ${ing.records.filter(r => r.kind === 'trade').length}`);
    out(`   продажби в ${year}: стара ${breakdown.length} (от тях без пълна покупка — с цена 0 за липсващото: ${uncovered}) · нова ${new2.sales} + без покупка ${res.unmatched.filter(u => u.year === year).length}`);
    out(`   резултат от продажбите на акции / фондове (преди освобождаване): новата е ${pct(new2.gain, de1.stockGain)}  [разликата идва от: комисионните (старата не ги брои), продажби без покупка, сторно, ETF]`);
    out(`   дивиденти: стара ${dividends.length} бр. · нова ${new2.divN} бр.; сумата — новата е ${pct(new2.div, de1.totalDivs)}  [старата изхвърля сторното и отрицателните]`);
    out(`   лихви: стара — не ги чете · нова ${new2.interestN} бр.`);
    out(`   сделки без курс: стара ${noRate} · нова ${res.missingRates.length}`);
  } else out('\nСтарата логика не намери нито една сделка — сравнение няма.');
})().catch(e => { console.error('ГРЕШКА: ' + (e && e.stack || e)); process.exit(1); });
