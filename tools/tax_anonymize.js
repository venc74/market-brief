#!/usr/bin/env node
/*
 * tools/tax_anonymize.js — анонимно копие на ИСТИНСКИ IBKR Activity Statement CSV (13.11.2026) за tests/fixtures/tax/real_anon/.
 * Правило 9 (CLAUDE.md): тестът ползва реалния ФОРМАТ, не синтетичния; правило 10: в репото няма лични числа (сметка, брой акции, суми, тикъри, имена, дати на сделки).
 *
 * ПО БЯЛ СПИСЪК — остава само:
 *   · имената на секциите, заглавните редове, видовете редове (Header / Data / SubTotal / Total / Notes) и броят клетки на ред (изместените колони остават изместени);
 *   · етикетите на брокера: колоните DataDiscriminator, Asset Category, Currency, Code, Type, Field Name, Subtitle, Currency Summary, Listing Exch… — стойността
 *     остава само ако е „чист етикет“ (букви и знаци, без цифри), иначе става „REMOVED“;
 *   · множителят на договора (Mult / Multiplier) и цената на опцията (Strike).
 * Всичко останало се ПОДМЕНЯ:
 *   · ДАТИ (14.11.2026): ВСИЧКИ дати (ГГГГ-ММ-ДД, периодът на отчета, месецът в „Interest for Дек-ГГГГ“) се изместват с ЕДИН общ случаен отместител в ЦЕЛИ МЕСЕЦИ назад (15–60 месеца, не кратно на 12;
 *     денят от месеца се пази, а ако в целевия месец го няма — последният ден). Отместителят се тегли от crypto и НЕ се пази. Месец-ът (не броят дни) е нарочно: така сумите на SYEP по месец,
 *     подредбата и разстоянията между отчетите (±3 дни) и месечните етикети остават. Часът в „Date/Time“ се подменя с 09:30:00 + пореден номер през (изместения) ден (редът на сделките в деня се пази).
 *   · СПЛИТОВЕ: коефициентът „Split A for B“ (A/B — цяло число ≥ 2) се умножава по случайно цяло 2–9 (10 за 1 → 20 … 90 за 1); количествата след сплита (сделки, Open Positions, Mark-to-Market) и
 *     цените преди / след него се мащабират съответно (количество × m, цена ÷ m) — всички събирания и сверки остават точни. Датата на сплита се измества и ДОПЪЛНИТЕЛНО на случаен ден между последната
 *     сделка с инструмента преди него и първата след него (в рамките на периода на отчета; ако няма място — само общото изместване). Дивидент на акция в описанието — случайно число (суми — отделно).
 *   · сметка → X0000001, X0000002 … (по реда на срещане); име → „Anonymous Person“; адрес → „REMOVED“;
 *   · тикър / Underlying → измислен „Zxxx“ (случайна подредба, една и съща във всички файлове); ISIN, Conid, описание на инструмента → измислени по тикъра;
 *   · брой (Quantity …) × цяло число за тикъра (2–6) × натрупаните сплитове; цена (T. Price, Close Price …) × число за тикъра (0,4–2,5) ÷ натрупаните сплитове; Proceeds = брой × цена (с множителя на реда);
 *     комисионна = малка част от сумата; Basis от тях; Realized / MTM P/L → 0; всички други числа (дивиденти, лихви, такси, NAV, Cash Report …) × случаен общ множител за секцията;
 *   · свободен текст (описания, бележки, адреси, прехвърляния) → „REMOVED“ / „TEXT“; описанията на дивидент / данък / лихва — по шаблон с измисления тикър.
 * Множителите, отместителят и новите коефициенти се теглят от crypto и НЕ се пазят — копието не може да се върне към оригинала. (--seed N, --shift-months K — само за теста на самия инструмент.)
 * Секциите, които калкулаторът не чете (обобщения, …), се режат до 3 реда Data (+ всички Total / SubTotal); секциите, от които калкулаторът чете, остават цели.
 * Употреба: node tools/tax_anonymize.js <входна папка с .csv> <изходна папка> [--seed N] [--shift-months K]   — файл, който не е IBKR отчет, се пропуска (казва се броят).
 */
'use strict';
const fs = require('fs'), path = require('path'), crypto = require('crypto');

// ─── случайност: crypto (или --seed за теста) ───────────────────────────────
function makeRng(seed) {
  if (seed == null) return () => crypto.randomInt(0, 2 ** 32) / 2 ** 32;
  let s = (Number(seed) >>> 0) || 1;                                              // mulberry32
  return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// ─── CSV ────────────────────────────────────────────────────────────────────
function splitCSV(line) {
  const r = []; let c = '', q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') { if (q && line[i + 1] === '"') { c += '"'; i++; } else q = !q; continue; }
    if (ch === ',' && !q) { r.push(c); c = ''; continue; }
    c += ch;
  }
  r.push(c); return r;
}
const cell = v => (/[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v);

// ─── числа ──────────────────────────────────────────────────────────────────
const NUM = /^([-+]?)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(%?)$/;
function parseNum(s) {
  const m = NUM.exec(String(s).trim()); if (!m) return null;
  const dec = m[3] || '';
  return { v: Number(m[2].replace(/,/g, '') + (dec ? '.' + dec : '')) * (m[1] === '-' ? -1 : 1), d: dec.length, commas: m[2].includes(','), pct: m[4] === '%' };
}
function fmt(v, d, o) {
  o = o || {};
  const unit = Math.pow(10, -d);
  let a = Math.abs(v); a = Math.round(a / unit) * unit;
  if (a === 0 && v !== 0 && !o.allowZero) a = unit;                               // не превръщай ненулево в нула
  let s = a.toFixed(d);
  if (o.commas) s = s.replace(/^(\d+)/, x => x.replace(/\B(?=(\d{3})+(?!\d))/g, ','));
  return ((v < 0 && a !== 0) ? '-' : '') + s + (o.pct ? '%' : '');
}

// ─── дати: отместване в цели месеци ─────────────────────────────────────────
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const MON3 = MONTHS.map(m => m.slice(0, 3));
const p2 = n => String(n).padStart(2, '0');
function shiftISO(iso, K) {                                                       // ГГГГ-ММ-ДД → K месеца напред (K < 0 — назад); денят се пази, ако го има в целевия месец, иначе — последният
  const [y, m, d] = iso.split('-').map(Number), t = y * 12 + (m - 1) + K, ny = Math.floor(t / 12), nm = t - ny * 12 + 1;
  return `${ny}-${p2(nm)}-${p2(Math.min(d, new Date(Date.UTC(ny, nm, 0)).getUTCDate()))}`;
}
const addDaysISO = (iso, n) => { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const diffDays = (a, b) => Math.round((new Date(b + 'T12:00:00Z') - new Date(a + 'T12:00:00Z')) / 86400000);
const longDate = iso => { const [y, m, d] = iso.split('-').map(Number); return `${MONTHS[m - 1]} ${d}, ${y}`; };
const parseLong = s => { const m = /([A-Z][a-z]+) (\d{1,2}), (\d{4})/.exec(s || ''), i = m ? MONTHS.indexOf(m[1]) : -1; return i < 0 ? null : `${m[3]}-${p2(i + 1)}-${p2(Number(m[2]))}`; };
const shiftPeriod = (v, K) => String(v).replace(/([A-Z][a-z]+) (\d{1,2}), (\d{4})/g, s => { const iso = parseLong(s); return iso ? longDate(shiftISO(iso, K)) : s; });

// ─── бял списък ─────────────────────────────────────────────────────────────
const LABEL_COLS = new Set(['DataDiscriminator', 'Asset Category', 'Asset Class', 'Currency', 'Code', 'Code (Cont.)', 'Type', 'Field Name', 'Subtitle', 'Currency Summary', 'Listing Exch', 'Delivery Month',
  'Direction', 'Meaning', 'Meaning (Cont.)']);
const safeLabel = v => /^[A-Za-z&/;.,()\- ]{0,48}$/.test(v);
const QTY = new Set(['Quantity', 'Qty', 'Prior Quantity', 'Current Quantity', 'Shares at IB', 'Shares Borrowed', 'Shares Lent', 'Net Shares']);
const PRICE = new Set(['T. Price', 'C. Price', 'Cost Price', 'Close Price', 'Prior Price', 'Current Price', 'Xfer Price']);
const KEEP_NUM = new Set(['Mult', 'Multiplier', 'Strike']);
const KEEP_ALL = new Set(['Statement', 'Account Information', 'Account Summary', 'Trades', 'Open Positions', 'Dividends', 'Withholding Tax', 'Interest', 'Corporate Actions', 'Transfers', 'Fees',
  'Financial Instrument Information', 'Payment In Lieu Of Dividends', 'Cash Report', 'Deposits & Withdrawals', 'Deposits And Withdrawals', 'Forex Balances', 'Net Asset Value', 'Change in NAV',
  'Change in Combined NAV', 'Base Currency Exchange Rate', 'Mark-to-Market Performance Summary', 'Stock Yield Enhancement Program Securities Lent Interest Details']);   // 13.11: MTM е ИЗТОЧНИК на началните / крайните позиции (контролите) — цял
const MAX_DATA_ROWS_OTHER = 3;
const CODES_ROWS = [['A', 'Assignment'], ['C', 'Closing Trade'], ['O', 'Opening Trade']];               // легендата на IBKR (обща за всички клиенти)
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DT = /^(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})$/;
const SPLIT_RE = /Split\s+(\d+(?:\.\d+)?)\s+for\s+(\d+(?:\.\d+)?)/i;
const DESC_SYM = /^\s*([A-Z0-9][A-Z0-9.\- ]*?)\s*\(([A-Z]{2}[A-Z0-9]{9}\d)\)/;

function anonymizeAll(files, opts) {
  const rnd = makeRng(opts && opts.seed);
  const ri = (a, b) => a + Math.floor(rnd() * (b - a + 1));
  const rf = (a, b) => a + rnd() * (b - a);
  // общото изместване на датите: цели месеци НАЗАД (курсовете на ЕЦБ свършват с последния ден от данните — напред няма курсове), не кратно на 12 (иначе денят от годината се пази)
  let K = opts && opts.shiftMonths != null ? Number(opts.shiftMonths) : null;
  if (K == null) { do { K = -ri(15, 60); } while (K % 12 === 0); }
  // тикъри: случайна подредба на „Zxxx“
  const pool = []; for (let a = 0; a < 26; a++) for (let b = 0; b < 26; b++) for (let c = 0; c < 26; c++) pool.push('Z' + String.fromCharCode(65 + a, 65 + b, 65 + c));
  for (let i = pool.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [pool[i], pool[j]] = [pool[j], pool[i]]; }
  const syms = new Map(), accts = new Map(), secG = {};
  // 13.11.2026: тикъри с ЕДИН И СЪЩ Conid в отчетите (смяна на тикъра: един инструмент) — една група: еднакви брой / цена / Conid / ISIN; имената на тикърите са различни
  const conidFirst = new Map(), groupOfSym = new Map();
  files.forEach(f => { let head = {}; f.text.replace(/^﻿/, '').split(/\r?\n/).forEach(line => { const p = splitCSV(line);
    if (p[1] === 'Header') { head[p[0]] = p.slice(2); return; }
    if (p[0] === 'Financial Instrument Information' && p[1] === 'Data' && head[p[0]]) { const h = head[p[0]], sy = p[2 + h.indexOf('Symbol')], cid = p[2 + h.indexOf('Conid')];
      if (sy && cid) { if (!conidFirst.has(cid)) conidFirst.set(cid, sy); groupOfSym.set(sy, conidFirst.get(cid)); } } }); });
  let poolIdx = 0, groupN = 0;
  const symOf = v => {
    if (!syms.has(v)) {
      const g = groupOfSym.get(v) || v;
      if (g !== v) { const base = symOf(g); syms.set(v, { n: base.n, name: pool[poolIdx++], k: base.k, pf: base.pf }); }
      else syms.set(v, { n: ++groupN, name: pool[poolIdx++], k: ri(2, 6), pf: rf(0.4, 2.5) });
    }
    return syms.get(v);
  };
  const isin = s => 'US' + 'Z' + String(s.n).padStart(8, '0') + '0';
  const acctOf = v => { if (!accts.has(v)) accts.set(v, 'X' + String(accts.size + 1).padStart(7, '0')); return accts.get(v); };
  const gOf = sec => (secG[sec] = secG[sec] || rf(0.35, 2.7));
  const syepK = ri(2, 6);                                                         // 13.11: един ЦЯЛ множител за SYEP лихвата — дневните редове и месечният ред „(SYEP) Interest for …“ остават с еднакви суми по месец

  // ─── предварителен преглед на всички файлове: периоди, сделки по тикър, сплитове (за новите коефициенти, прозореца на датата и натрупания множител) ───
  const parsed = files.map(f => {
    const text = f.text.replace(/^﻿/, '');
    const lines = text.split(/\r?\n/); if (lines.length && lines[lines.length - 1] === '') lines.pop();
    return { f, text, bom: f.text.charCodeAt(0) === 0xFEFF, crlf: /\r\n/.test(text), rows: lines.map(l => splitCSV(l)) };
  });
  const tradeDT = new Map();                                                      // оригинален тикър → [„ГГГГ-ММ-ДД ЧЧ:ММ:СС“] (всички Order редове във всички файлове)
  const splitsBySym = new Map();                                                  // оригинален тикър → [{key, eff, effDate, rep, A, B, m, ...}]
  parsed.forEach(P => {
    if (!P.rows.length || P.rows[0][0] !== 'Statement') { P.skip = true; return; }
    const per = P.rows.find(p => p[0] === 'Statement' && p[1] === 'Data' && p[2] === 'Period');
    const ds = (per ? String(per[3]).match(/[A-Z][a-z]+ \d{1,2}, \d{4}/g) || [] : []).map(parseLong).filter(Boolean);
    let h = {}; const allDates = [];
    P.rows.forEach(p => {
      if (p[1] === 'Header') { h[p[0]] = p.slice(2); return; }
      if (p[1] !== 'Data' || !h[p[0]]) return;
      const g = n => { const i = h[p[0]].indexOf(n); return i >= 0 ? p[i + 2] : undefined; };
      p.slice(2).forEach(v => { const m = DATE.test(v) ? [0, v] : DT.exec(v); if (m) allDates.push(m[1]); });
      if (p[0] === 'Trades' && g('DataDiscriminator') === 'Order' && g('Symbol') && g('Date/Time')) { const m = DT.exec(g('Date/Time')); if (m) (tradeDT.get(g('Symbol')) || tradeDT.set(g('Symbol'), []).get(g('Symbol'))).push(`${m[1]} ${m[2]}`); }
    });
    allDates.sort(); P.S = ds[0] || allDates[0] || '0000-01-01'; P.E = ds[1] || allDates[allDates.length - 1] || '9999-12-31';
  });
  parsed.forEach(P => {
    if (P.skip) return;
    let h = {};
    P.rows.forEach(p => {
      if (p[1] === 'Header') { h[p[0]] = p.slice(2); return; }
      if (p[0] !== 'Corporate Actions' || p[1] !== 'Data' || !h[p[0]]) return;
      const g = n => { const i = h[p[0]].indexOf(n); return i >= 0 ? p[i + 2] : undefined; };
      const d = g('Description') || '', sp = SPLIT_RE.exec(d), hd = DESC_SYM.exec(d), dt = DT.exec(g('Date/Time') || '');
      if (!sp || !hd || !dt) return;
      const sym = hd[1].trim(), key = `${sym}|${dt[1]} ${dt[2]}`;
      const list = splitsBySym.get(sym) || splitsBySym.set(sym, []).get(sym);
      if (list.some(s => s.key === key)) return;
      const A = Number(sp[1]), B = Number(sp[2]), r = A / B;
      const m = (Number.isInteger(r) && r >= 2) ? ri(2, 9) : 1;                    // нов коефициент A·m за B — само за цял коефициент ≥ 2 (иначе количествата след сплита не остават цели); 2–9: от новия коефициент не се познава старият (при 2–3 „40 за 1“ можеше да е само 20)
      list.push({ key, sym, eff: `${dt[1]} ${dt[2]}`, effDate: dt[1], effTime: dt[2], rep: g('Report Date') || dt[1], A, B, m, file: P });
    });
  });
  // прозорецът на датата на сплита: между последната сделка с тикъра преди него и първата след него, в рамките на периода на отчета; няма място → само общото изместване
  let splitsMoved = 0, splitsKept = 0, splitsRatio = 0;
  splitsBySym.forEach((list, sym) => list.forEach(s => {
    const T = (tradeDT.get(sym) || []).slice().sort(), before = T.filter(x => x < s.eff).pop(), after = T.find(x => x > s.eff);
    const P = s.file, lo = before && before.slice(0, 10) > P.S ? before.slice(0, 10) : P.S, hi = after && after.slice(0, 10) < P.E ? after.slice(0, 10) : P.E;
    s.lowSame = !!before && before.slice(0, 10) >= lo; s.highSame = !!after && after.slice(0, 10) <= hi;
    const span = diffDays(lo, hi);
    if (s.m > 1) splitsRatio++;
    if (span >= 1) { s.newDate = addDaysISO(lo, ri(0, span)); s.timeMode = s.newDate === lo && s.lowSame ? 'late' : (s.newDate === hi && s.highSame ? 'early' : 'mid'); splitsMoved++; }
    else { s.newDate = s.effDate; s.timeMode = 'keep'; splitsKept++; }
    s.newRep = s.rep === s.effDate ? s.newDate : addDaysISO(s.newDate, Math.max(0, Math.min(diffDays(s.effDate, s.rep), diffDays(s.newDate, P.E))));
  }));
  const splitAt = (sym, dtKey) => (splitsBySym.get(sym) || []).filter(s => s.eff < dtKey).reduce((a, s) => a * s.m, 1);          // натрупан множител към момента (строго след сплита)
  const splitBeforeDate = (sym, iso) => (splitsBySym.get(sym) || []).filter(s => s.effDate < iso).reduce((a, s) => a * s.m, 1);   // в началото на деня (позиция в началото на периода)
  const splitByDate = (sym, iso) => (splitsBySym.get(sym) || []).filter(s => s.effDate <= iso).reduce((a, s) => a * s.m, 1);       // в края на деня (позиция в края на периода)
  const splitFor = (sym, eff) => (splitsBySym.get(sym) || []).find(s => s.key === `${sym}|${eff}`);

  const out = [];
  parsed.forEach(P => {
    const f = P.f;
    if (P.skip) { out.push({ name: f.name, skipped: true }); return; }
    const rows = P.rows;
    // час в „Date/Time“: по ИЗМЕСТЕНАТА дата, подредени по оригиналния момент, 09:30:00 + номер
    const slots = {};
    let h0 = {};
    rows.forEach(p => { if (p[1] === 'Header') h0[p[0]] = p.slice(2); else if (p[1] === 'Data' && h0[p[0]]) { const i = h0[p[0]].indexOf('Date/Time'); if (i >= 0 && p[i + 2]) { const m = DT.exec(p[i + 2]); if (m) (slots[shiftISO(m[1], K)] = slots[shiftISO(m[1], K)] || new Set()).add(`${m[1]} ${m[2]}`); } } });
    Object.keys(slots).forEach(d => { slots[d] = [...slots[d]].sort(); });
    const newTime = (d, t) => { const i = (slots[shiftISO(d, K)] || []).indexOf(`${d} ${t}`); const s = 9 * 3600 + 30 * 60 + Math.max(0, i); return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map(x => String(x).padStart(2, '0')).join(':'); };
    const head = {}, kept = {}, outRows = [];
    rows.forEach(p => {
      const sec = p[0], typ = p[1];
      if (typ === 'Header') { head[sec] = p.slice(2); outRows.push(p.slice()); return; }
      if (typ !== 'Data' && !/^(SubTotal|Total)$/i.test(typ || '')) { outRows.push([sec, typ, ...p.slice(2).map(() => 'REMOVED')]); return; }
      if (typ === 'Data' && !KEEP_ALL.has(sec)) { kept[sec] = (kept[sec] || 0) + 1; if (kept[sec] > MAX_DATA_ROWS_OTHER) return; }
      if (sec === 'Codes' && typ === 'Data') { const k = (kept['Codes#'] = (kept['Codes#'] || 0) + 1); if (k > CODES_ROWS.length) return; outRows.push(['Codes', 'Data', ...CODES_ROWS[k - 1]]); return; }
      const h = head[sec] || [];
      const get = n => { const i = h.indexOf(n); return i >= 0 ? p[i + 2] : undefined; };
      const isTotal = p.slice(2, 4).some(v => /^Total\b/i.test(String(v || '').trim())) || /^(SubTotal|Total)$/i.test(typ);
      const r = p.slice(0, 2);
      // тикърът на реда (за множителите на брой и цена)
      const symRaw = get('Symbol'), descSym = (DESC_SYM.exec(get('Description') || '') || [])[1];
      const assetCat = get('Asset Category');
      const forexPair = symRaw && /^[A-Z]{3}\.[A-Z]{3}$/.test(symRaw);
      const rowSym = (assetCat === 'Forex' || forexPair || isTotal) ? null : (symRaw ? symOf(symRaw) : (descSym ? symOf(descSym) : null));
      const origSym = rowSym ? (symRaw || (descSym && descSym.trim())) : null;
      const g = gOf(sec + (assetCat === 'Forex' ? '#fx' : ''));
      const fv = {};                                                              // Field Name / Field Value двойки
      if (h.includes('Field Name') && h.includes('Field Value')) fv.name = get('Field Name');
      const disc = get('DataDiscriminator'), isOrder = sec === 'Trades' && typ === 'Data' && disc === 'Order' && rowSym && h.includes('Proceeds') && h.includes('T. Price');
      // натрупаните сплитове за реда: сделка — към момента й; Transfers — началото на деня; Prior … — началото на периода; всичко друго — края на периода
      const dtm = DT.exec(get('Date/Time') || ''), tdate = get('Date') && DATE.test(get('Date')) ? get('Date') : null;
      const Mrow = !origSym ? 1 : dtm ? splitAt(origSym, `${dtm[1]} ${dtm[2]}`) : (sec === 'Transfers' && tdate) ? splitBeforeDate(origSym, addDaysISO(tdate, 1)) : splitByDate(origSym, P.E);
      const Mstart = origSym ? splitBeforeDate(origSym, P.S) : 1, Mend = origSym ? splitByDate(origSym, P.E) : 1;
      // Order редовете: коефициентите от оригинала (множител на договора), нови брой / цена / сума / комисионна
      let trade = null;
      if (isOrder) {
        const q0 = parseNum(get('Quantity') || ''), p0 = parseNum(get('T. Price') || ''), pr0 = parseNum(get('Proceeds') || '');
        if (q0 && p0 && q0.v !== 0 && p0.v !== 0) {
          const mult = pr0 && pr0.v !== 0 ? Math.round((-pr0.v / (q0.v * p0.v)) * 1000) / 1000 : 1;
          const q = q0.v * rowSym.k * Mrow, pr = Math.round(p0.v * rowSym.pf / Mrow * Math.pow(10, Math.max(2, p0.d))) / Math.pow(10, Math.max(2, p0.d));
          // комисионната расте със същия коефициент като сумата (брой × цена) — печалбата на всяка продажба се мащабира точно и знакът й се пази (13.11: фиксирана комисионна обръщаше знака на 2 малки сделки)
          const f0 = parseNum(get('Comm/Fee') || ''), proceeds = -mult * q * pr, fee = f0 ? Math.sign(f0.v) * Math.max(0.01, Math.abs(f0.v) * rowSym.k * rowSym.pf) : 0;
          trade = { q, q0, pr, p0, proceeds, fee, mult };
        }
      }
      // ред на сплит: новият коефициент, новата дата и новото количество (добавените акции = натрупаните преди × (A·m − B) / B)
      const sp = sec === 'Corporate Actions' && typ === 'Data' ? SPLIT_RE.exec(get('Description') || '') : null;
      const ev = sp && origSym && dtm ? splitFor(origSym, `${dtm[1]} ${dtm[2]}`) : null;
      for (let i = 0; i < p.length - 2; i++) {
        const name = h[i] !== undefined ? h[i] : '(без име)', v = p[i + 2];
        let o = v;
        if (v === '') { r.push(''); continue; }
        if (name === 'Account' && sec !== 'Account Information') o = /^Total\b/i.test(v) ? v : (/^[A-Z]{1,2}\d{5,}/.test(v) ? acctOf(v.replace(/\s*\(.*\)\s*$/, '')) : symOf(v).name);   // в редовете SubTotal на Trades тук стои ТИКЪРЪТ (клетките са изместени)
        else if (name === 'Account Alias') o = 'Alias';
        else if (name === 'Name') o = 'Anonymous Person';
        else if (name === 'Symbol' || name === 'Underlying') o = (/^(Total|SubTotal)\b/i.test(v) || /^[A-Z]{3}\.[A-Z]{3}$/.test(v)) ? v : symOf(v).name;   // 13.11: SubTotal носи ТИКЪР — подменя се
        else if (name === 'Conid') { const s = symRaw ? symOf(symRaw) : null; o = s ? String(100000 + s.n) : String(900000 + i); }
        else if (name === 'Security ID') { const s = symRaw ? symOf(symRaw) : null; o = s ? isin(s) : 'REMOVED'; }
        else if (name === 'Description') o = describe(sec, v, h, get, symOf, isin, { dps: () => (rf(0.05, 0.95)).toFixed(2), ev, K });
        else if (name === 'Date/Time') {
          const m = DT.exec(v);
          if (m && ev && ev.timeMode !== 'keep') o = `${shiftISO(ev.newDate, K)}, ${ev.timeMode === 'late' ? '23:59:58' : ev.timeMode === 'early' ? '00:00:01' : '20:00:00'}`;
          else if (m) o = `${shiftISO(m[1], K)}, ${newTime(m[1], m[2])}`;
          else o = DATE.test(v) ? shiftISO(v, K) : 'REMOVED';
        }
        else if (name === 'Report Date' && ev && DATE.test(v)) o = shiftISO(ev.newRep, K);
        else if (DATE.test(v)) o = shiftISO(v, K);
        else if (sec === 'Statement' && name === 'Field Value') o = fieldValue(fv.name, v, K);
        else if (sec === 'Account Information' && name === 'Field Value') o = acctInfo(fv.name, v, acctOf);
        else if (LABEL_COLS.has(name)) o = safeLabel(v) ? v : 'REMOVED';
        else if (KEEP_NUM.has(name) && parseNum(v)) o = v;
        else if (trade && name === 'Quantity') o = fmt(trade.q, trade.q0.d, { commas: trade.q0.commas || Math.abs(trade.q) >= 1000 });
        else if (trade && name === 'T. Price') o = fmt(trade.pr, Math.max(2, trade.p0.d));
        else if (trade && name === 'C. Price') { const c = parseNum(v); o = c ? fmt(c.v * rowSym.pf / Mend, Math.max(2, c.d)) : 'REMOVED'; }
        else if (trade && name === 'Proceeds') o = fmt(trade.proceeds, 2);
        else if (trade && name === 'Comm/Fee') o = fmt(trade.fee, 2);
        else if (trade && name === 'Basis') o = fmt(-(trade.proceeds + trade.fee), 2);
        else if (trade && /^(Realized P\/L|MTM P\/L)$/.test(name)) o = '0';
        else if (parseNum(v)) {
          const n = parseNum(v);
          if ((sec === 'Stock Yield Enhancement Program Securities Lent Interest Details' && name === 'Interest Paid to Customer') || (sec === 'Interest' && name === 'Amount' && /\(SYEP\)/.test(get('Description') || ''))) o = fmt(n.v * syepK, n.d);
          else if (ev && ev.A !== ev.B && name === 'Quantity') {                                    // ред на сплит: добавените акции = (преди сплита) × (A·m − B) / B; преди сплита = стойността в отчета × B / (A − B)
            const pre = n.v * ev.B / (ev.A - ev.B);
            o = fmt(pre * rowSym.k * Mrow * (ev.A * ev.m - ev.B) / ev.B, n.d, { commas: n.commas });         // Mrow е натрупаният множител ПРЕДИ този сплит (строго преди момента му)
          }
          else if (rowSym && QTY.has(name)) o = fmt(n.v * rowSym.k * (name === 'Prior Quantity' ? Mstart : Mrow), n.d, { commas: n.commas });
          else if (rowSym && PRICE.has(name)) o = fmt(n.v * rowSym.pf / (name === 'Prior Price' ? Mstart : Mrow), Math.max(2, n.d));
          else o = fmt(n.v * g, n.d, { commas: n.commas, pct: n.pct });
        }
        else o = /^-{1,2}$/.test(v) ? v : 'TEXT';                                 // всичко друго със свободен текст е подменено (бял списък: само етикетните колони по-горе)
        r.push(o);
      }
      // Open Positions: стойност / основа от новите брой и цена (с множителя на реда)
      if (sec === 'Open Positions' && rowSym) {
        const ix = n => h.indexOf(n) + 2, m0 = parseNum(get('Mult') || '1'), mult = m0 ? m0.v : 1;
        const q = parseNum(r[ix('Quantity')] || ''), cp = parseNum(r[ix('Cost Price')] || ''), cl = parseNum(r[ix('Close Price')] || '');
        if (q && cp && cl) { const basis = q.v * cp.v * mult, val = q.v * cl.v * mult;
          if (ix('Cost Basis') > 1) r[ix('Cost Basis')] = fmt(basis, 2); if (ix('Value') > 1) r[ix('Value')] = fmt(val, 2); if (ix('Unrealized P/L') > 1) r[ix('Unrealized P/L')] = fmt(val - basis, 2, { allowZero: true }); }
      }
      outRows.push(r);
    });
    out.push({ name: f.name, text: (P.bom ? '﻿' : '') + outRows.map(r => r.map(cell).join(',')).join(P.crlf ? '\r\n' : '\n') + (P.crlf ? '\r\n' : '\n'), skipped: false });
  });
  return { files: out, symbols: syms.size, accounts: accts.size, shiftMonths: K, splits: { total: splitsMoved + splitsKept, moved: splitsMoved, kept: splitsKept, ratioChanged: splitsRatio } };
}

// описание по секция: само шаблони с измисления тикър
function describe(sec, v, h, get, symOf, isin, ctx) {
  const m = /^\s*([A-Z0-9][A-Z0-9.\- ]*?)\s*\(([A-Z]{2}[A-Z0-9]{9}\d)\)\s*(.*)$/.exec(v);
  if (sec === 'Dividends' || sec === 'Withholding Tax' || sec === 'Payment In Lieu Of Dividends') {
    if (!m) return 'REMOVED';
    const s = symOf(m[1]), pil = /Payment in Lieu/i.test(m[3]), tax = sec === 'Withholding Tax';
    return `${s.name}(${isin(s)}) ${pil ? 'Payment in Lieu of Dividend (Ordinary Dividend)' : 'Cash Dividend USD ' + ctx.dps() + ' per Share' + (tax ? ' - US Tax' : ' (Ordinary Dividend)')}`;   // дивидент на акция — случаен (14.11.2026)
  }
  if (sec === 'Corporate Actions') {
    const sp = SPLIT_RE.exec(v);
    if (!m) return 'REMOVED';
    const s = symOf(m[1]);
    const A = sp ? (ctx.ev ? ctx.ev.A * ctx.ev.m : Number(sp[1])) : null;                // нов коефициент: A·m за B (m = 1, когато не е цял коефициент ≥ 2)
    return sp ? `${s.name}(${isin(s)}) Split ${A} for ${sp[2]} (${s.name}, SYNTHETIC INSTRUMENT ${s.n}, ${isin(s)})` : `${s.name}(${isin(s)}) Corporate action REMOVED`;
  }
  if (sec === 'Interest') {
    const d = get('Date') || '', cur = get('Currency') || 'USD', amt = parseNum(get('Amount') || '0');
    // месецът е този от ОРИГИНАЛНОТО описание („… Interest for Dec-2025“ се плаща през януари) — не месецът на датата на плащането (иначе сверката SYEP ↔ дневните редове се разваля); изместен със същите месеци като датите
    const orig = /for\s+([A-Za-z]{3})[a-z]*-(\d{4})/.exec(v);
    const lab = (m3, y) => { const i = MON3.findIndex(x => x.toLowerCase() === m3.toLowerCase()); if (i < 0) return 'REMOVED'; const t = Number(y) * 12 + i + ctx.K; return `${MON3[t - Math.floor(t / 12) * 12]}-${Math.floor(t / 12)}`; };
    const mon = orig ? lab(orig[1], orig[2]) : (DATE.test(d) ? lab(MON3[Number(d.slice(5, 7)) - 1], d.slice(0, 4)) : 'REMOVED');
    if (/\(SYEP\)/.test(v)) return `${/^[A-Z]{3}$/.test(cur) ? cur : 'USD'} IBKR Managed Securities (SYEP) Interest for ${mon}`;      // месечният SYEP ред — етикет на брокера
    return `${/^[A-Z]{3}$/.test(cur) ? cur : 'USD'} ${amt && amt.v < 0 ? 'Debit' : 'Credit'} Interest for ${mon}`;
  }
  if (sec === 'Financial Instrument Information') { const sy = get('Symbol'); return sy ? 'SYNTHETIC INSTRUMENT ' + symOf(sy).n : 'REMOVED'; }
  return 'REMOVED';
}
function fieldValue(name, v, K) {
  if (name === 'Period') return shiftPeriod(v, K);                                              // периодът на отчета — изместен със същите месеци (14.11.2026)
  if (name === 'Title' || name === 'BrokerName') return v;                                      // етикет на отчета, брокер
  if (name === 'WhenGenerated') return '2000-01-01, 00:00:00';
  return 'REMOVED';
}
function acctInfo(name, v, acctOf) {
  if (name === 'Name') return 'Anonymous Person';
  if (name === 'Account') { const m = /^(\S+)(\s*\(.*\))?$/.exec(v); return m ? acctOf(m[1]) + (m[2] ? ' (Anonymous Person)' : '') : 'REMOVED'; }
  if (name === 'Accounts Included') return (v.match(/[A-Z]\d{5,}/g) || []).map(a => acctOf(a)).join(', ') || 'REMOVED';   // само номерата (без имената в скоби)
  if (/^(Account Type|Customer Type|Base Currency|Account Capabilities)$/.test(name)) return safeLabel(v) ? v : 'REMOVED';
  return 'REMOVED';
}

// ─── CLI ────────────────────────────────────────────────────────────────────
// името на файла — по ИЗМЕСТЕНИЯ период на копието (месец и година на началото и края), не по оригиналния
function slugOf(text) {
  const t = (/^Statement,Data,Title,([^\r\n,]*)/m.exec(text.replace(/^﻿/, '')) || [])[1] || '';
  const per = (/^Statement,Data,Period,"?([^\r\n"]*)/m.exec(text.replace(/^﻿/, '')) || [])[1] || '';
  const ds = (per.match(/[A-Z][a-z]+ \d{1,2}, \d{4}/g) || []).map(parseLong).filter(Boolean);
  const span = ds.length === 2 ? `${ds[0].slice(0, 7).replace('-', '')}_${ds[1].slice(0, 7).replace('-', '')}` : 'xxxx';
  const n = new Set((text.match(/^Account Information,Data,Account,[^\r\n]*/gm) || [])).size;
  return `ibkr_${/Summary/i.test(t) ? 'summary' : 'statement'}_${span}${n > 1 ? '_' + n + 'accounts' : ''}.csv`;
}
if (require.main === module) {
  const args = process.argv.slice(2); let seed = null, shift = null;
  const si = args.indexOf('--seed'); if (si >= 0) { seed = Number(args[si + 1]); args.splice(si, 2); }
  const mi = args.indexOf('--shift-months'); if (mi >= 0) { shift = Number(args[mi + 1]); args.splice(mi, 2); }
  if (args.length !== 2) { console.error('Употреба: node tools/tax_anonymize.js <входна папка с .csv> <изходна папка> [--seed N] [--shift-months K]'); process.exit(2); }
  const [inDir, outDir] = args;
  const names = fs.readdirSync(inDir).filter(f => f.toLowerCase().endsWith('.csv')).sort();
  const res = anonymizeAll(names.map(n => ({ name: n, text: fs.readFileSync(path.join(inDir, n), 'utf8') })), { seed, shiftMonths: shift });
  fs.mkdirSync(outDir, { recursive: true });
  let written = 0, skipped = 0; const used = new Set();
  res.files.forEach(f => {
    if (f.skipped) { skipped++; return; }
    let dst = slugOf(f.text), k = 2; while (used.has(dst)) dst = slugOf(f.text).replace(/\.csv$/, `_${k++}.csv`); used.add(dst);
    fs.writeFileSync(path.join(outDir, dst), f.text); written++;
  });
  // САМО броеве — нито отместителят, нито новите коефициенти се печатат (не се пазят)
  console.log(`записани ${written} анонимни файла в изходната папка · пропуснати (не са IBKR отчет): ${skipped} · измислени тикъри: ${res.symbols} · сметки: ${res.accounts} · сплитове: ${res.splits.total} (нов коефициент ${res.splits.ratioChanged}, датата изместена допълнително ${res.splits.moved}, само общото изместване ${res.splits.kept})`);
}
module.exports = { anonymizeAll, splitCSV, parseNum, shiftISO, slugOf };
