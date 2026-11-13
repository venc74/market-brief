#!/usr/bin/env node
/*
 * tools/tax_diagnose.js — диагноза на брокерски отчет през логиката на данъчния калкулатор (docs/tax_core.js) (12.11.2026; от 15.11.2026 без сравнение със старата версия — docs/tax-v1.html е махната).
 *
 * Печата САМО структура и броеве: имена на секции, заглавните редове (етикетите на брокера), видове редове, ВИДА на клетките (дата / цяло число / текст…, не стойността),
 * броеве по причина, години. НЕ печата суми, количества, тикъри, номер на сметка, имена, описания и името на файла — изходът може да се покаже / постави в чат.
 *
 * Употреба:  node tools/tax_diagnose.js [--core път/tax_core.js] [--rates път/eurofxref-hist.csv] [--year 2026] отчет.csv [още.csv …]
 *   --core   коя версия на логиката (по подразбиране docs/tax_core.js; за друга версия: git show main:docs/tax_core.js > /tmp/core_main.js)
 *   --rates  курсове на ЕЦБ от файл (по подразбиране docs/eurofxref-hist.csv) — без мрежа
 *   --year   годината, която се отбелязва в заглавието (сметката е за всички години с данни)
 * Отчетът остава където е — скриптът само чете; нищо не се записва и не се праща.
 */
'use strict';
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '..');
const args = process.argv.slice(2);
const opt = { core: path.join(ROOT, 'docs', 'tax_core.js'), rates: path.join(ROOT, 'docs', 'eurofxref-hist.csv'), year: null };
const files = [];
for (let i = 0; i < args.length; i++) {
  if (['--core', '--rates', '--year'].includes(args[i])) opt[args[i].slice(2)] = args[++i];
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
    if (!s) { s = by[sec] = { name: sec, types: {}, headers: [], disc: {}, cells: {}, enums: {}, widths: {}, fields: [], headerWidthMismatch: 0, accounts: new Set(), accShapes: {} }; sections.push(s); }
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
    if (h.includes('Account') && !/^Total/i.test(cells[0] ? cells[0].v : '')) { const a = r['Account']; s.accounts.add(a); inc(s.accShapes, a === '' ? '(празно)' : shape(a)); }
    h.forEach((name, k) => {
      const key = name === '' ? `(без име, колона ${k + 1})` : name;
      if (ENUM_COLS.has(name)) inc(s.enums[key] = s.enums[key] || {}, safeEnum(cells[k] ? cells[k].v : ''));
      if (DETAIL.has(sec) && !ENUM_COLS.has(name)) inc(s.cells[key] = s.cells[key] || {}, cellType(cells[k] ? cells[k].v : '') + (cells[k] && cells[k].q ? ' (в кавички)' : ''));
    });
  });
  return { bom, crlf, lines: lines.length, blank, sections, dataNoHeader };
}

// ─── основното ───────────────────────────────────────────────────────────────
(async () => {
  const TC = require(path.resolve(opt.core));
  const ratesText = fs.existsSync(opt.rates) ? fs.readFileSync(opt.rates, 'utf8') : '';
  const table = ratesText ? TC.parseECBcsv(ratesText) : {};
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
      if (sec.accounts.size) out(`   колона „Account“: ${sec.accounts.size} различни стойности (форма: ${counts(sec.accShapes)})`);
      Object.entries(sec.enums).forEach(([c, v]) => { const e = Object.entries(v); out(`   стойности на „${c}“: ${e.slice(0, 24).map(([k, n]) => `${k} ×${n}`).join(' · ')}${e.length > 24 ? ` · … още ${e.length - 24}` : ''}`); });
      if (DETAIL.has(sec.name)) Object.entries(sec.cells).forEach(([c, v]) => out(`   вид на клетките „${c}“: ${counts(v)}`));
    });
    out('');
  });

  // 3) новата логика
  out('════ ЛОГИКАТА НА КАЛКУЛАТОРА (tax_core.js) — чете по ИМЕ на колоната от заглавния ред');
  const ing = TC.ingest(texts.map(f => ({ name: f.name, text: f.text })));
  const rate = TC.rateLookup(table);
  ing.files.forEach((f, i) => {
    const recs = ing.records.filter(r => r.src === f.name), sk = ing.skipped.filter(s => s.src === f.name);
    const k = {}; recs.forEach(r => inc(k, r.kind));
    const tr = recs.filter(r => r.kind === 'trade'), cls = {}; tr.forEach(r => inc(cls, r.assetClass));
    out(`${f.name}: формат „${f.format}“${f.error ? ' · ГРЕШКА: ' + f.error : ''} · записи ${f.records} (след дубликати: ${recs.length}) · „не е сметнато“ ${sk.length}`);
    out(`   записи по вид: сделки ${k.trade || 0} (покупки ${tr.filter(r => r.qty > 0).length}, продажби ${tr.filter(r => r.qty < 0).length}; по клас: ${counts(cls)}) · дивиденти ${k.dividend || 0} · удържан данък ${k.withholding || 0} · лихви ${k.interest || 0} · сплитове ${k.split || 0}`);
    const yr = {}; recs.forEach(r => inc(yr, r.date.slice(0, 4))); out(`   записи по години: ${Object.keys(yr).sort().map(y => `${y}: ${yr[y]}`).join(' · ') || '—'}`);
    // само този файл през новата логика (както ако е качен сам): какво става с продажбите му
    try { const one = TC.ingest([{ name: f.name, text: texts[i].text }]), r1 = TC.fifo(one.records, rate, { controls: one.controls }), sells = one.records.filter(r => r.kind === 'trade' && r.qty < 0).length;
      out(`   САМ ЗА СЕБЕ СИ (само този файл): продажби във файла ${sells} → с резултат ${r1.realized.filter(x => !x.short || x.premium).length} (без курс: ${r1.realized.filter(x => x.gainEUR == null).length}) · без покупка ${r1.unmatched.length} · записи без курс ${r1.missingRates.length}`);
    } catch (e) { out('   САМ ЗА СЕБЕ СИ: грешка — ' + String(e.message).slice(0, 80)); }
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

  // 4) сметката по години
  const res = TC.fifo(ing.records, rate, { controls: ing.controls });
  // сметките в записите — FIFO се води по брокер / сметка / инструмент
  const T = ing.records.filter(r => r.kind === 'trade');
  const accIdx = {}; T.forEach(r => { const k = r.broker + '|' + r.account; if (!(k in accIdx)) accIdx[k] = Object.keys(accIdx).length + 1; });
  const accLine = Object.entries(accIdx).map(([k, n]) => { const a = T.filter(r => r.broker + '|' + r.account === k); const d = a.map(r => r.date).sort();
    return `сметка ${n} (${k.split('|')[0]}, форма „${shape(k.split('|')[1])}“): покупки ${a.filter(r => r.qty > 0).length}, продажби ${a.filter(r => r.qty < 0).length}, ${d[0].slice(0, 7)} … ${d[d.length - 1].slice(0, 7)}`; });   // само година-месец
  const stmtAcc = new Set((ing.info || []).map(i => i.account).filter(Boolean));
  const rowsOther = T.filter(r => r.broker === 'IBKR' && stmtAcc.size && !stmtAcc.has(r.account)).length;
  const symAcc = {}; T.forEach(r => { (symAcc[r.sym] = symAcc[r.sym] || new Set()).add(r.broker + '|' + r.account); });
  const un = res.unmatched.map(u => {
    const same = T.filter(r => r.sym === u.sym && r.qty > 0), mine = same.filter(r => r.broker === u.broker && r.account === u.account), other = same.filter(r => !(r.broker === u.broker && r.account === u.account));
    if (mine.some(r => r.date <= u.date)) return 'в същата сметка има по-ранна покупка, но по-малко от продаденото (или вече изразходвана)';
    if (other.some(r => r.date <= u.date)) return 'по-ранна покупка на същия инструмент има САМО В ДРУГА СМЕТКА';
    if (same.length) return 'покупка на същия инструмент има само ПО-КЪСНО';
    return 'покупка на този инструмент няма никъде в качените файлове';
  });
  const unWhy = {}; un.forEach(w => inc(unWhy, w));
  const transfers = ing.skipped.filter(x => x.section === 'Transfers').length;
  const years = [...new Set(ing.records.map(r => Number(r.date.slice(0, 4))))].sort();
  const nowY = new Date().getFullYear();
  out(`\n════ СМЕТКАТА (всички файлове заедно) — години с данни: ${years.join(', ') || 'няма'}${opt.year ? '; избрана година: ' + opt.year : ''}`);
  out(`сметки със сделки (FIFO се води по сметка): ${Object.keys(accIdx).length}`);
  accLine.forEach(l => out('   ' + l));
  out(`   сделки, чиято сметка (колона Account) е различна от тази в Account Information на отчетите: ${rowsOther} · инструменти със сделки в повече от една сметка: ${Object.values(symAcc).filter(x => x.size > 1).length} от ${Object.keys(symAcc).length} · редове в секция Transfers: ${transfers}`);
  out(`FIFO: продажби с резултат ${res.realized.length} · продажби без покупка ${res.unmatched.length} · записи без курс ${res.missingRates.length} · отворени позиции в края ${res.open.length}`);
  Object.entries(unWhy).forEach(([w, n]) => out(`   без покупка ×${n}: ${w}`));
  out(`   покупки, които покриха по-ранна непокрита продажба и НЕ станаха лот: ${(res.notes || []).filter(n => /покрива/.test(n.text)).length} · позиции, белязани като несигурни след непокрита продажба: ${(res.tainted || []).length}`);
  const xl = res.xferLinks || [], acatsOpen = (res.pending || []).filter(p => p.kind === 'acats' && !p.filled);   // 14.11.2026: прехвърляне от друг брокер — свързано с покупките при другия брокер или без цена (само броеве)
  out(`   прехвърляния „In“ от друг брокер, свързани с покупки в отчет на другия брокер: ${xl.length} (${xl.reduce((a, x) => a + x.linked, 0)} от ${xl.reduce((a, x) => a + x.qty, 0)} бр.) · лотове без намерена покупка (за ръчно въвеждане): ${acatsOpen.length}`);
  years.forEach(y => {
    const de = TC.computeDE(res, { year: y, records: ing.records, info: ing.info, skipped: ing.skipped });
    const R = res.realized.filter(x => x.year === y);
    out(`   ${y}: продажби ${R.length} (без курс: ${R.filter(x => x.gainEUR == null && !x.unknownLots).length})${R.some(x => x.unknownLots) ? ` · лот без покупна цена ${R.filter(x => x.unknownLots).length}` : ''} · без покупка ${de.unmatched.length} · числото най-горе: ${de.headline === 0 ? 'НУЛА' : de.headline > 0 ? 'положително' : 'отрицателно'} · ${de.complete ? 'пълно' : 'НЕПЪЛНО'}` +
        ` · грешки: ${de.notes.filter(n => n.level === 'err').length} · разлики с Open Positions: ${(de.reconcile || []).length}`);
  });
  const dflt = years.includes(nowY - 1) ? nowY - 1 : null;
  out(`   годината, с която страницата тръгва днес (main): ${nowY - 1} — записи за нея: ${ing.records.filter(r => r.date.startsWith(String(nowY - 1))).length}${dflt == null ? '  ← няма данни за тази година: числото е 0, докато годината не се смени на ръка' : ''}`);

})().catch(e => { console.error('ГРЕШКА: ' + (e && e.stack || e)); process.exit(1); });
