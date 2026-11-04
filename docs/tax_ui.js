// tax_ui.js — логиката на docs/tax.html (05.11.2026: изнесена от страницата, за да е CSP script-src 'self' — без вграден скрипт). Сметките — в tax_core.js.
'use strict';
const TC = window.TaxCore, esc = TC.esc, fmt = TC.fmt;
const SHOW_BG = false;                       // 04.11.2026: българската част е скрита (кодът е в TaxCore.computeBG)
const S = { files: [], ing: null, rates: {}, rateSource: {}, fifo: null, fundTypes: {}, vorab: {}, persons: {} };
const $ = id => document.getElementById(id);

// ─── файлове ───
function addFiles(list) {
  const reads = Array.from(list).map(f => f.text().then(text => ({ name: f.name, text })));
  Promise.all(reads).then(fs => {
    fs.forEach(f => { const i = S.files.findIndex(x => x.name === f.name && x.text === f.text); if (i < 0) S.files.push(f); });
    S.ing = TC.ingest(S.files); renderFiles(); recalc();
  });
}
// 05.11.2026: махане на файл → наново ingest и сметка (старото число не остава на екрана)
function removeFile(i) { S.files.splice(i, 1); S.ing = S.files.length ? TC.ingest(S.files) : null; renderFiles(); recalc(); }
function renderFiles() {
  const ing = S.ing;
  if (!ing) { $('files').innerHTML = ''; return; }
  $('files').innerHTML = '<tr><th></th><th>Файл</th><th>Чий</th><th>Разпознат като</th><th>Сметка</th><th>Период в данните</th><th class="n">Записи</th><th class="n">Дубликати</th><th>Бележка</th></tr>' +
    ing.files.map((f, i) => `<tr><td><button class="btn" data-rm="${i}" title="махни файла">×</button></td><td>${esc(f.name)}</td>
      <td>${f.format === 'ecb_rates' ? '' : `<select data-owner="${i}"><option value="A">аз</option><option value="B"${f.owner === 'B' ? ' selected' : ''}>съпруг/а</option></select>`}</td><td>${esc({ ibkr: 'IBKR', standard: 'стандартен CSV', ecb_rates: 'курсове на ЕЦБ', revolut_stocks: 'Revolut — акции*', revolut_crypto: 'Revolut — крипто*', revolut_crypto_old: 'Revolut — стар формат', unknown: '—' }[f.format] || f.format)}</td>
      <td>${esc(f.broker)} ${esc(f.account)}</td><td class="mono">${esc(f.from)}${f.to ? ' … ' + esc(f.to) : ''}</td><td class="n">${f.records}</td><td class="n">${f.duplicates || ''}</td>
      <td class="${f.error ? 'neg' : 'mut'}">${esc(f.error || f.period || '')}</td></tr>`).join('');
  // чий е файлът (05.11.2026): за Revolut определя сметката (отчетът няма номер), за всички — човека за крипто §23
  $('files').querySelectorAll('[data-owner]').forEach(el => el.addEventListener('change', () => { S.files[Number(el.dataset.owner)].owner = el.value; S.ing = TC.ingest(S.files); renderFiles(); recalc(); }));
  $('files').querySelectorAll('[data-rm]').forEach(el => el.addEventListener('click', () => removeFile(Number(el.dataset.rm))));
  const years = [...new Set(ing.records.map(r => Number(r.date.slice(0, 4))))].sort((a, b) => b - a);
  const cur = new Date().getFullYear(), sel = $('year'), old = sel.value;
  const all = [...new Set([cur, cur - 1, ...years])].sort((a, b) => b - a);
  sel.innerHTML = all.map(y => `<option value="${y}">${y}</option>`).join('');
  sel.value = old && all.includes(Number(old)) ? old : String(years.includes(cur - 1) ? cur - 1 : years[0] || cur - 1);
}

// ─── курсове (05.11.2026): качен файл на ЕЦБ → файлът до страницата (docs/eurofxref-hist.csv, обновява го daily_brief.yml) → ЕЦБ API по години → frankfurter.dev ───
// Към ЕЦБ / frankfurter — само ако файлът до страницата липсва или не стига; всяка заявка с таймаут и един повторен опит.
const FETCH_TIMEOUT_MS = 15000;
async function getJSON(url) {
  let last;
  for (let i = 0; i < 2; i++) {
    const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), FETCH_TIMEOUT_MS);
    try { const r = await fetch(url, { signal: ctl.signal }); if (!r.ok) throw new Error('HTTP ' + r.status); return await r.json(); }
    catch (e) { last = e.name === 'AbortError' ? new Error('таймаут ' + FETCH_TIMEOUT_MS / 1000 + ' s') : e; }
    finally { clearTimeout(t); }
  }
  throw last;
}
let siteRates;                                  // undefined — още не е четен; null — липсва
async function loadSiteRates() {
  if (siteRates !== undefined) return siteRates;
  try { const r = await fetch('eurofxref-hist.csv', { cache: 'no-cache' }); if (!r.ok) throw new Error('HTTP ' + r.status); siteRates = TC.parseECBcsv(await r.text()); }
  catch (e) { siteRates = null; }
  return siteRates;
}
async function ensureRates() {
  const rates = JSON.parse(JSON.stringify(S.ing.rates || {})); const source = {};
  const need = TC.ratesNeeded(S.ing.records);
  for (const [cur, p] of Object.entries(need)) {
    if (TC.ratesCover(rates, cur, p)) { source[cur] = 'качения файл на ЕЦБ'; continue; }
    const site = await loadSiteRates();
    if (site && site[cur]) {
      TC.mergeRates(rates, cur, site[cur]);
      const last = site[cur][site[cur].length - 1][0];
      if (TC.ratesCover(rates, cur, p)) { source[cur] = `файла на ЕЦБ до страницата (eurofxref-hist.csv, до ${last})`; continue; }
    }
    const src = { ecb: 0, fr: 0, fail: [] };
    for (const [a, b] of TC.yearChunks(p.from, p.to)) {
      $('status').textContent = `Курсове ${cur} ${a.slice(0, 4)}…`;
      try { const pairs = TC.parseECBjson(await getJSON(TC.ecbUrl(cur, a, b))); if (!pairs.length) throw new Error('празен отговор'); TC.mergeRates(rates, cur, pairs); src.ecb++; continue; }
      catch (e) { /* към резервата */ }
      try { const pairs = TC.parseFrankfurter(await getJSON(TC.frankfurterUrl(cur, a, b)), cur); if (!pairs.length) throw new Error('празен отговор'); TC.mergeRates(rates, cur, pairs); src.fr++; }
      catch (e) { src.fail.push(`${a.slice(0, 4)} (${e.message})`); }
    }
    source[cur] = [src.ecb ? `ЕЦБ API (${src.ecb} г.)` : '', src.fr ? `frankfurter.dev — курсовете на ЕЦБ (${src.fr} г.)` : '',
                         src.fail.length ? `не се изтеглиха: ${src.fail.join(', ')} — качи eurofxref-hist.csv` : ''].filter(Boolean).join(' · ');
  }
  return { rates, source };
}

// 05.11.2026: сметката тръгва сама при добавяне / махане на файл; докато върви, резултатът е скрит (никога старо число). По-стара сметка, свършила след
// по-нова смяна на файловете, се изхвърля (calcToken). Смяната на година и настройките — само render() върху готовото FIFO.
let calcToken = 0;
const fifoOpts = () => ({ stillhalter: $('stillhalter').value });
async function recalc() {
  const my = ++calcToken;
  S.fifo = null; S.de = null; $('out').style.display = 'none';
  if (!S.ing || !S.ing.records.length) { $('status').textContent = S.ing ? 'Няма записи за смятане — виж бележките във файловете.' : ''; return; }
  $('status').textContent = 'Смята се…';
  try {
    const r = await ensureRates();
    if (my !== calcToken) return;
    S.rates = r.rates; S.rateSource = r.source;
    S.fifo = TC.fifo(S.ing.records, TC.rateLookup(S.rates), fifoOpts()); render(); $('out').style.display = '';
    $('status').textContent = `${S.ing.records.length} записа от ${S.ing.files.length} файла; „не е сметнато“: ${S.ing.skipped.length}`;
  } catch (e) { if (my === calcToken) $('status').innerHTML = `<span class="neg">${esc(e.message)}</span>`; }
}

// ─── резултат ───
function settings() {
  return { year: Number($('year').value), joint: $('joint').value === '1', kirche: $('kirche').value || null, carriedShareLoss: Number($('carryS').value) || 0,
           carriedOtherLoss: Number($('carryO').value) || 0, creditRate: ($('credit').value === '' ? 15 : Number($('credit').value)) / 100,
           fundTypes: S.fundTypes, vorab: S.vorab, persons: S.persons, records: S.ing.records, info: S.ing.info, skipped: S.ing.skipped,
           offsetOrder: $('offsetOrder').value, creditPerItem: $('creditPerItem').value === '1', nonIbkrDefault: $('nonIbkrDefault').value };
}
const cls = v => v > 0 ? 'pos' : v < 0 ? 'neg' : 'mut';

function render() {
  if (!S.fifo) return;
  const st = settings(), de = TC.computeDE(S.fifo, st), y = st.year;
  S.de = de;
  // голямото число
  const loss = de.total === 0 && (de.shareCarry || de.otherCarry);
  $('headline').innerHTML = `<h2>Доходи от капитал ${y} — за Anlage KAP / KAP-INV</h2>
    <div class="big ${cls(de.headline)}">${fmt(de.headline)}</div>
    <div class="small">${loss ? 'загуба — пренася се (Finanzamt я установява с решение)' : 'след прихващането на загубите, преди Sparer-Pauschbetrag' + (de.estimate ? ' (' + fmt(de.estimate.pauschbetrag) + ')' : '')}
      ${de.complete ? '' : ' · <span class="neg">НЕПЪЛНО — виж предупрежденията</span>'}</div>
    ${de.crypto.length ? `<div style="margin-top:10px">Крипто — частни продажби (§23, Anlage SO): ${de.crypto.map(c => `<b class="${cls(c.result)}">${fmt(c.result)}</b> ${st.joint ? (c.person === 'B' ? 'съпруг/а' : 'аз') : ''}
      <span class="small">(облагаеми ${fmt(c.taxable)}${c.underFreigrenze ? ' — под Freigrenze ' + fmt(c.freigrenze) + ' → 0' : ''}; над година — освободени ${fmt(c.exempt)})</span>`).join(' · ')}</div>` : ''}`;
  // предупреждения
  const w = [];
  if (de.unmatched.length) w.push(`<div class="msg err"><b>Липсва покупката:</b> ${de.unmatched.map(u => `за ${esc(u.sym)} (${esc(u.broker)} ${esc(u.account)}, продажба ${esc(u.date)}, ${+u.qty.toFixed(6)} бр.)`).join('; ')} — качи по-стар отчет. Тези продажби НЕ са в числото.</div>`);
  (S.ing.warnings || []).forEach(t => w.push(`<div class="msg warn small">${esc(t)}</div>`));
  if (de.missingRates.length) w.push(`<div class="msg err"><b>Липсва курс:</b> ${[...new Set(de.missingRates.map(m => `${esc(m.currency)} ${esc(m.date)}`))].join(', ')} — записите не са в числото. Качи eurofxref-hist.csv от ЕЦБ.</div>`);
  Object.entries(S.rateSource).forEach(([c, s]) => w.push(`<div class="msg ${/не се изтеглиха/.test(s) ? 'warn' : 'info'} small">Курсове ${esc(c)} — от ${esc(s)}</div>`));
  de.notes.forEach(n => w.push(`<div class="msg ${n.level === 'err' ? 'err' : n.level === 'warn' ? 'warn' : 'info'} small">${esc(n.text)}</div>`));
  const sk = S.ing.skipped;
  if (sk.length) w.push(`<div class="card"><details${sk.length < 6 ? ' open' : ''}><summary><b class="yel">Не е сметнато: ${sk.length} реда</b> (всички години; виж дали някой засяга ${y})</summary><div class="scroll"><table>
    <tr><th>Файл</th><th>Ред</th><th>Секция</th><th>Какво</th><th>Дата</th><th>Защо</th></tr>
    ${sk.map(s => `<tr><td>${esc(s.src)}</td><td class="n">${s.line || ''}</td><td>${esc(s.section)}</td><td>${esc(s.what)}</td><td class="mono">${esc(s.date)}</td><td>${s.taxable ? '<b class="neg">може да е облагаем</b> · ' : ''}${esc(s.reason)}</td></tr>`).join('')}</table></div></details></div>`);
  $('warnings').innerHTML = w.join('');
  // разбивка
  const L = TC.LABELS, sum = c => de.items.filter(i => i.cat === c).reduce((s, i) => s + i.eur, 0), gross = c => de.items.filter(i => i.cat === c).reduce((s, i) => s + i.gross, 0);
  const rows = [
    ['shareGains', de.shareGains], ['shareLosses', -de.shareLosses], ['dividends', sum('dividends')], ['interest', sum('interest')], ['pil', sum('pil')],
    ['options', sum('options')], ['optionLosses', sum('optionLosses')], ['funds', sum('funds'), gross('funds')], ['fundLosses', sum('fundLosses'), gross('fundLosses')], ['otherNeg', sum('otherNeg')],
  ].filter(r => Math.abs(r[1]) > 0.004);
  $('breakdown').innerHTML = '<tr><th>Категория</th><th class="n">EUR</th><th>Към</th></tr>' +
    rows.map(([c, v, g]) => `<tr><td>${esc(L[c].bg)}${g != null && Math.abs(g - v) > 0.004 ? `<div class="small">преди освобождаването: ${fmt(g)}</div>` : ''}</td><td class="n ${cls(v)}">${fmt(v)}</td><td class="small">${esc(L[c].form)}</td></tr>`).join('') +
    (de.carriedShareLoss ? `<tr><td>Пренесена загуба от акции</td><td class="n neg">${fmt(-de.carriedShareLoss)}</td><td class="small">решение на Finanzamt</td></tr>` : '') +
    (de.carriedOtherLoss ? `<tr><td>Пренесена друга загуба</td><td class="n neg">${fmt(-de.carriedOtherLoss)}</td><td class="small">решение на Finanzamt</td></tr>` : '') +
    `<tr><td><b>= Доходи от капитал след прихващането</b></td><td class="n"><b class="${cls(de.total)}">${fmt(de.total)}</b></td><td class="small">загубите от акции — само срещу печалби от акции</td></tr>` +
    (de.shareCarry ? `<tr><td>Загуба от акции за пренасяне</td><td class="n neg">${fmt(-de.shareCarry)}</td><td class="small">Anlage KAP — загуби от акции; не намалява другите доходи</td></tr>` : '') +
    (de.otherCarry ? `<tr><td>Друга загуба за пренасяне</td><td class="n neg">${fmt(-de.otherCarry)}</td><td class="small">Anlage KAP — загуби без загубите от акции</td></tr>` : '') +
    `<tr><td>${esc(L.withholding.bg)} <div class="small">удържани ${fmt(de.withheld)}</div></td><td class="n">${fmt(de.creditable)}</td><td class="small">${esc(L.withholding.form)}</td></tr>` +
    de.crypto.map(c => `<tr><td>${esc(L.crypto.bg)}${st.joint ? ' — ' + (c.person === 'B' ? 'съпруг/а' : 'аз') : ''}<div class="small">облагаеми ${fmt(c.taxable)} · над година (освободени) ${fmt(c.exempt)} · Freigrenze ${fmt(c.freigrenze)} на човек</div></td><td class="n ${cls(c.result)}">${fmt(c.result)}</td><td class="small">${esc(L.crypto.form)}</td></tr>`).join('');
  renderFunds(de); renderPersons(st);
  // продажби и доходи за годината
  const R = S.fifo.realized.filter(x => x.year === y);
  $('salesTitle').textContent = `Продажби ${y} (${R.length})`;
  $('sales').innerHTML = '<tr><th>Дата</th><th>Брокер / сметка</th><th>Инструмент</th><th class="n">Бр.</th><th class="n">Приходи €</th><th class="n">Цена на придобиване €</th><th class="n">Резултат €</th><th>Купено</th></tr>' +
    R.map(x => `<tr><td class="mono">${esc(x.date)}</td><td>${esc(x.broker)} ${esc(x.account)}</td><td>${esc(x.sym)} <span class="small">${esc(x.assetClass)}${x.premium ? ' · премия (Stillhalter)' : x.buyback ? ' · обратно изкупуване' : x.short ? ' · къса' : ''}</span></td><td class="n">${+x.qty.toFixed(6)}</td>
      <td class="n">${x.proceedsEUR == null ? '—' : fmt(x.proceedsEUR)}</td><td class="n">${x.costEUR == null ? '—' : fmt(x.costEUR)}</td><td class="n ${cls(x.gainEUR || 0)}">${x.gainEUR == null ? 'няма курс' : fmt(x.gainEUR)}</td>
      <td class="small">${(x.lots || []).map(l => `${esc(l.date)} × ${+l.qty.toFixed(6)}${l.exempt ? ' (над година)' : ''}`).join('<br>')}</td></tr>`).join('');
  const I = S.fifo.incomes.filter(x => x.year === y);
  $('incTitle').textContent = `Дивиденти, удържан данък, лихви ${y} (${I.length})`;
  $('incomes').innerHTML = '<tr><th>Дата</th><th>Вид</th><th>Инструмент / описание</th><th class="n">Сума</th><th class="n">EUR</th></tr>' +
    I.map(x => `<tr><td class="mono">${esc(x.date)}</td><td>${esc({ dividend: x.pil ? 'вместо дивидент' : 'дивидент', withholding: 'удържан данък', interest: 'лихва' }[x.kind])}</td><td>${esc(x.sym)} <span class="small">${esc(x.desc)}</span></td>
      <td class="n">${esc(x.amount)} ${esc(x.currency)}</td><td class="n ${cls(x.eur)}">${fmt(x.eur)}</td></tr>`).join('');
  // ориентировъчен данък
  const e = de.estimate;
  if (!e) $('estimate').innerHTML = `<h2>Ориентировъчно — Abgeltungsteuer</h2><div class="small">Преди 2009 няма Abgeltungsteuer — не е сметнато.</div>`;
  else $('estimate').innerHTML = `<h2>Ориентировъчно — Abgeltungsteuer (Finanzamt смята окончателно)</h2><table>
    <tr><td>Доходи от капитал след прихващането</td><td class="n">${fmt(de.total)}</td></tr>
    <tr><td>− Sparer-Pauschbetrag ${st.joint ? '(съвместно)' : ''}</td><td class="n">${fmt(-Math.min(de.total, e.pauschbetrag))}</td></tr>
    <tr><td>= Облагаеми</td><td class="n">${fmt(e.taxableAfterPausch)}</td></tr>
    <tr><td>Abgeltungsteuer${e.kircheRate ? ` с църковния данък — (e − 4q) / (4 + ${e.kircheRate})` : ' 25% − зачетен чужд данък'}</td><td class="n">${fmt(e.abgeltung)}</td></tr>
    <tr><td>Solidaritätszuschlag 5,5%</td><td class="n">${fmt(e.soli)}</td></tr>
    ${e.kircheRate ? `<tr><td>Църковен данък ${e.kircheRate * 100}%</td><td class="n">${fmt(e.kirche)}</td></tr>` : ''}
    <tr><td>Зачетен чужд данък (q)</td><td class="n">${fmt(e.creditUsed)}</td></tr>
    <tr><td><b>Общо (без крипто)</b></td><td class="n"><b>${fmt(e.total)}</b></td></tr></table>
    <div class="small" style="margin-top:6px">Крипто по §23 се облага с личната ставка заедно с другите доходи — не е сметнато тук. Параметри ${y}: ${esc(de.params.notes.join(' · '))}${de.params.extrapolated ? ' — <b>непроверени за тази година</b>' : ''}.</div>`;
  if (SHOW_BG) { const bg = TC.computeBG(S.fifo, y); $('bg').style.display = ''; $('bg').innerHTML = `<h2>България</h2><pre class="small">${esc(JSON.stringify(bg, null, 1))}</pre>`; }
}

function renderFunds(de) {
  const syms = [...new Set(S.fifo.realized.concat(S.ing.records).filter(x => (x.assetClass === 'stock' || x.assetClass === 'fund') && x.sym).map(x => x.sym))].sort();
  const hint = sym => S.ing.records.some(r => r.sym === sym && r.fundHint);
  const opts = (sym) => Object.entries(TC.FUND_TYPES).map(([k, v]) => `<option value="${k}"${(S.fundTypes[sym] || (hint(sym) || ($('nonIbkrDefault').value === 'equity' && !S.ing.records.some(r => r.sym === sym && r.broker === 'IBKR')) ? 'equity' : 'stock')) === k ? ' selected' : ''}>${esc(v)}</option>`).join('');
  $('fundsBox').innerHTML = `<div class="small" style="margin-bottom:6px"><b>Акции и фондове</b> — отбележи кои са фондове (ETF) и какви; частичното освобождаване зависи от вида (акционерен 30%, смесен 15%, имотен 60% / 80%). Предложението „фонд“ идва от типа в отчета на IBKR — провери го.</div>
    <div class="scroll"><table><tr><th>Инструмент</th><th>Вид</th><th>Vorabpauschale за ${esc(de.year - 1)} (доход в ${esc(de.year)}), € — натрупващи фондове</th></tr>
    ${syms.map(s => `<tr><td>${esc(s)}${de.heldFunds.includes(s) ? ` <span class="small yel">държан в края на ${esc(de.year - 1)}</span>` : ''}</td><td><select data-fund="${esc(s)}">${opts(s)}</select></td>
      <td><input type="number" min="0" step="0.01" data-vorab="${esc(s)}" value="${esc((S.vorab[s] || {})[de.year - 1] || '')}"></td></tr>`).join('')}</table></div>`;
  $('fundsBox').querySelectorAll('[data-fund]').forEach(el => el.addEventListener('change', () => { S.fundTypes[el.dataset.fund] = el.value; render(); }));
  $('fundsBox').querySelectorAll('[data-vorab]').forEach(el => el.addEventListener('change', () => { (S.vorab[el.dataset.vorab] = S.vorab[el.dataset.vorab] || {})[de.year - 1] = el.value; render(); }));   // по тикър И година
}

const personOf = a => S.persons[a] || ((S.ing.records.find(r => r.broker + '|' + r.account === a) || {}).owner) || 'A';
function renderPersons(st) {
  if (!st.joint) { $('personsBox').innerHTML = ''; return; }
  const accts = [...new Set(S.ing.records.filter(r => r.assetClass === 'crypto').map(r => r.broker + '|' + r.account))];
  $('personsBox').innerHTML = accts.length ? `<div class="small" style="margin-bottom:6px"><b>Чия е сметката</b> — Freigrenze по §23 е на човек (крипто); доходите от капитал са общи при съвместното подаване.</div>
    <table>${accts.map(a => `<tr><td>${esc(a.replace('|', ' '))}</td><td><select data-person="${esc(a)}"><option value="A"${personOf(a) !== 'B' ? ' selected' : ''}>аз</option><option value="B"${personOf(a) === 'B' ? ' selected' : ''}>съпруг/а</option></select></td></tr>`).join('')}</table>` : '';
  $('personsBox').querySelectorAll('[data-person]').forEach(el => el.addEventListener('change', () => { S.persons[el.dataset.person] = el.value; render(); }));
}

function doExport() {
  if (!S.de) return;
  const de = S.de, q = TC.csvCell, n = v => typeof v === 'number' ? v.toFixed(2) : v;   // csvCell — и защита от формули (= + - @)
  const rows = [[`Доходи от капитал ${de.year} (Anlage KAP / KAP-INV)`, n(de.headline)], [],
    ['Категория', 'EUR', 'EUR преди освобождаването', 'Инструмент', 'Дата']].concat(de.items.map(i => [TC.LABELS[i.cat].bg, n(i.eur), n(i.gross), i.sym, i.date || '']))
    .concat([[], ['Загуба от акции за пренасяне', n(de.shareCarry)], ['Друга загуба за пренасяне', n(de.otherCarry)], ['Удържан чужд данък — за зачитане', n(de.creditable)]])
    .concat(de.crypto.map(c => [`Крипто §23 (${c.person === 'B' ? 'съпруг/а' : 'аз'})`, n(c.result), `облагаеми ${n(c.taxable)}; освободени ${n(c.exempt)}`]))
    .concat([[], ['Липсва покупката'], ...de.unmatched.map(u => [u.sym, u.date, u.qty, u.broker, u.account])])
    .concat([[], ['Не е сметнато'], ...S.ing.skipped.map(s => [s.src, s.line, s.section, s.what, s.date, s.reason])]);
  const blob = new Blob(['﻿' + rows.map(r => r.map(q).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `kap_${de.year}.csv`; a.click(); URL.revokeObjectURL(a.href);
}

// ─── събития ───
const drop = $('drop');
drop.addEventListener('click', () => $('fi').click());
$('fi').addEventListener('change', e => { addFiles(e.target.files); e.target.value = ''; });
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); addFiles(e.dataTransfer.files); });
$('clear').addEventListener('click', () => { S.files = []; S.ing = null; renderFiles(); recalc(); });
['year', 'joint', 'kirche', 'carryS', 'carryO', 'credit', 'offsetOrder', 'creditPerItem', 'nonIbkrDefault'].forEach(id => $(id).addEventListener('change', render));
$('export').addEventListener('click', doExport);
$('stillhalter').addEventListener('change', () => { if (S.fifo) { S.fifo = TC.fifo(S.ing.records, TC.rateLookup(S.rates), fifoOpts()); render(); } });
renderFiles();
(function () { const y = new Date().getFullYear(); $('year').innerHTML = [y, y - 1, y - 2].map(v => `<option value="${v}">${v}</option>`).join(''); $('year').value = String(y - 1); })();
