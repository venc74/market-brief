/*
 * tax_report.js — отчетът за Finanzamt (13.11.2026): „Aufstellung der Kapitalerträge“ на НЕМСКИ, като страница за печат (браузърът я записва като PDF). Чисти функции, без DOM и без мрежа;
 * разширяват TaxCore (зарежда се СЛЕД tax_core.js). Тук няма второ смятане: всички суми идват от същите computeDE / declaration / fifo резултати като страницата — отчетът само ги разпределя по редове.
 * Всеки раздел е в safe(): при грешка отчетът не се чупи, а годината в него е означена като НЕПЪЛНА с причината (graceful degradation).
 * Само информация — не е данъчна консултация.
 */
(function (root) {
  'use strict';
  const TC = root.TaxCore;
  if (!TC) throw new Error('tax_report.js: tax_core.js трябва да е зареден преди него');
  const esc = TC.esc, NB = ' ', dmy = TC.dmy;

  // ─── форматиране (немски: 1.234,56 €, ДД.ММ.ГГГГ) ───
  const money = n => (n < 0 ? '−' : '') + Math.abs(n).toFixed(2).replace('.', ',').replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  TC.fmtDE = n => money(n) + NB + '€';
  const qtyDE = q => String(+Number(q).toFixed(6)).replace('.', ',');
  const pxDE = p => { let s = Number(p).toFixed(4).replace(/0+$/, '').replace(/\.$/, ''); if (!/\./.test(s)) s += '.00'; else if (/\.\d$/.test(s)) s += '0'; return s.replace('.', ','); };
  const rateDE = r => Number(r).toFixed(4).replace('.', ',');
  const ccyDE = (v, c) => money(v) + NB + (c || '');
  const F = TC.fmtDE;

  // ЕЦБ курс за дата: същият избор като TC.rateLookup (последният публикуван ≤ датата, до maxBack дни назад), но с датата на курса → {rate, on} | null
  TC.rateInfo = function (table, cur, date, maxBack) {
    if (!cur || cur === 'EUR') return { rate: 1, on: date };
    const a = (table || {})[cur]; if (!a || !a.length) return null;
    const back = maxBack == null ? 10 : maxBack;
    let lo = 0, hi = a.length - 1, ans = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (a[m][0] <= date) { ans = m; lo = m + 1; } else hi = m - 1; }
    if (ans < 0 || a[ans][0] < TC.addDays(date, -back)) return null;
    return { rate: a[ans][1], on: a[ans][0] };
  };

  // откъде са курсовете — текстът на страницата е на български; в отчета: немски (структурирано от същите ключови фрази)
  TC.rateSourceDE = function (s) {
    const t = String(s || ''), parts = [], m = /eurofxref-hist\.csv, до (\d{4}-\d{2}-\d{2})/.exec(t);
    if (/качения файл/.test(t)) parts.push('hochgeladene EZB-Datei');
    if (/файла на ЕЦБ до страницата/.test(t)) parts.push('EZB-Datei eurofxref-hist.csv' + (m ? ' (bis ' + dmy(m[1]) + ')' : ''));
    if (/ЕЦБ API/.test(t)) parts.push('EZB-Datenportal (data-api.ecb.europa.eu)');
    if (/frankfurter/.test(t)) parts.push('frankfurter.dev (Referenzkurse der EZB)');
    if (/не се изтеглиха/.test(t)) parts.push('für einzelne Jahre keine Kurse verfügbar');
    return parts.join(' · ') || 'Referenzkurse der Europäischen Zentralbank (EZB)';
  };
  TC.REPORT_FORMATS = { ibkr: 'Interactive Brokers — Activity Statement (CSV)', standard: 'Standard-CSV', ecb_rates: 'EZB-Referenzkurse (CSV)', revolut_stocks: 'Revolut — Trading account statement (CSV)', revolut_pnl: 'Revolut — Profit and loss (CSV)',
    revolut_account: 'Revolut — Account statement (nur Mengen, ohne Preise)', revolut_crypto: 'Revolut — Krypto (CSV)', revolut_crypto_old: 'Revolut — älteres Format (nicht gelesen)', taxtool_result: 'Ergebnis eines anderen Programms (nicht als Quelle verwendet)', xlsx: 'Excel (nicht gelesen)', unknown: 'unbekanntes Format (nicht gelesen)' };
  TC.REPORT_FOOTER = 'Selbst erstellte Aufstellung auf Grundlage der beigefügten Originalabrechnungen des Brokers. Keine Steuerberatung.';

  // ─── моделът на отчета ───
  // ctx: {de (computeDE за годината), fifo (TC.fifo), ing (TC.ingest), st (настройките, с които е смятан de), rates (таблица на ЕЦБ), rateSource (текст), name, now ('ГГГГ-ММ-ДД'), manual}
  TC.reportModel = function (ctx) {
    const de = ctx.de, fifo = ctx.fifo, ing = ctx.ing, st = ctx.st || {}, table = ctx.rates || {}, year = de.year, Y = String(year), manual = ctx.manual || st.manual || {};
    const rateFn = TC.rateLookup(table), errors = [];
    // сметките на Revolut се казват „акции“ / „крипто“ (отчетът няма номер) — в немския отчет да няма кирилица; описанията на български също се пропускат
    const acctDE = s => String(s == null ? '' : s).replace('акции', 'Aktien').replace('крипто', 'Krypto').replace('фиат', 'Fiat').replace('съпруг/а', 'Ehegatte/Ehegattin');
    const mask = a => acctDE(TC.maskAccount(a)), noCyr = s => /[\u0400-\u04FF]/.test(s || '') ? '' : (s || '');
    const safe = (name, fn, dflt) => { try { return fn(); } catch (e) { errors.push(`${name}: ${e.message}`); return dflt; } };
    const maskFile = n => String(n == null ? '' : n).replace(/[A-Z]{1,2}\d{5,}/g, m => mask(m));
    const isin = {};
    Object.entries(ing.instruments || {}).forEach(([s, d]) => { if (d && d.isin) isin[s] = d.isin; });
    (ing.records || []).forEach(r => { if (r.sym && r.isin && !isin[r.sym]) isin[r.sym] = r.isin; });
    (ing.aliases || []).forEach(a => { if (isin[a.from] && !isin[a.to]) isin[a.to] = isin[a.from]; });
    const label = s => isin[s] ? `${s} (${isin[s]})` : String(s || '');
    const acked = x => !!(x.ackKey && manual[x.ackKey] && manual[x.ackKey].ack);
    const decl = TC.declaration(de, rateFn), P = decl.parts, L = decl.lines;
    const ref = k => L ? `Zeile ${L[k]}` : '';
    const sumCat = c => de.items.filter(i => i.cat === c).reduce((s, i) => s + i.eur, 0);
    const R = fifo.realized, near = (a, b) => Math.abs(a - b) < 0.005;
    const checks = [];                                                              // [{name, a (в отчета), b (на страницата), ok}] — отчетът се сверява сам със страницата
    const check = (name, a, b) => checks.push({ name, a, b, ok: near(a, b) });
    const n1 = (n, one, many) => `${n} ${n === 1 ? one : many}`;

    // ─── заглавие, брокери / сметки ───
    const brokers = safe('Broker', () => { const seen = {}; (ing.files || []).forEach(f => { if (f.format === 'ecb_rates' || f.notSource || f.error || !f.broker) return;
      const k = f.broker + '|' + (f.accountMasked || ''), o = seen[k] = seen[k] || { broker: f.broker, account: acctDE(f.accountMasked || ''), from: '', to: '', files: 0, records: 0 };
      o.files++; o.records += f.records; if (f.from && (!o.from || f.from < o.from)) o.from = f.from; if (f.to && (!o.to || f.to > o.to)) o.to = f.to; }); return Object.values(seen); }, []);

    // ─── Zusammenfassung — същите полета и суми като блока „Какво попълваш“ ───
    const overCredit = P.withheld - P.creditable, rate = st.creditRate == null ? 0.15 : Number(st.creditRate);
    const summary = safe('Zusammenfassung', () => {
      const rows = [
        { field: TC.DECL_FIELDS.z19, ref: ref('z19'), eur: decl.z19, signed: true,
          calc: `Gewinne aus Aktienveräußerungen ${F(P.shareG)} − Verluste aus Aktienveräußerungen ${F(P.shareL)} + Dividenden ${F(P.div)} + Zinsen ${F(P.intr)}${P.opt || P.pil ? ` + Optionsgeschäfte und Ersatzzahlungen ${F(P.opt + P.pil)}` : ''} − sonstige Verluste ${F(decl.z22)} = ${F(decl.z19)}. Der Saldo enthält Gewinne und Verluste; die Zeilen 20, 22 und 23 sind „davon“-Angaben.` },
        { field: TC.DECL_FIELDS.z20, ref: ref('z20'), eur: decl.z20, part: true,
          calc: `Summe der Gewinne aus ${n1(P.nG, 'Veräußerung', 'Veräußerungen')} von Aktien mit Gewinn = ${F(decl.z20)}. „Davon“-Angabe — bereits in Zeile 19 enthalten, nicht zusätzlich ansetzen.` },
        { field: TC.DECL_FIELDS.z22, ref: ref('z22'), eur: decl.z22, part: true,
          calc: `Verluste aus Optionsgeschäften ${F(P.optL)} + Rückbuchungen von Dividenden und sonstige Verluste ${F(P.othN)} = ${F(decl.z22)} (als positiver Betrag). „Davon“-Angabe — bereits in Zeile 19 enthalten.` },
        { field: TC.DECL_FIELDS.z23, ref: ref('z23'), eur: decl.z23, part: true,
          calc: `Summe der Verluste aus ${n1(P.nL, 'Veräußerung', 'Veräußerungen')} von Aktien mit Verlust = ${F(decl.z23)} (als positiver Betrag). „Davon“-Angabe — bereits in Zeile 19 enthalten; das Finanzamt verrechnet sie nur mit Gewinnen aus Aktienveräußerungen.` },
        { field: TC.DECL_FIELDS.z41, ref: ref('z41'), eur: decl.z41,
          calc: `Auf Dividenden einbehaltene ausländische Steuer ${F(P.withheld)}; angerechnet bis ${Math.round(rate * 100)} % der Bruttodividende und höchstens bis zur deutschen Steuer darauf = ${F(decl.z41)}${overCredit > 0.004 ? `; darüber hinaus ${F(overCredit)} nicht anrechenbar` : ''}. Auf Zinsen einbehaltene Steuer ist hier nicht enthalten.` },
      ];
      if (decl.funds != null) rows.push({ field: 'Anlage KAP-INV — Investmenterträge (nach Fondsart, vor Teilfreistellung)', ref: '', eur: decl.funds, signed: true, calc: 'Summe der Erträge und Gewinne aus Investmentfonds je Fondsart, vor Anwendung der Teilfreistellung (diese wendet das Finanzamt an).' });
      (de.crypto || []).forEach(c => rows.push({ field: `Anlage SO — Private Veräußerungsgeschäfte (Kryptowerte)${c.person === 'B' ? ' — Ehegatte/Ehegattin' : ''}`, ref: '', eur: c.result, signed: true,
        calc: `Steuerpflichtige Gewinne/Verluste (Haltedauer bis ein Jahr) ${F(c.taxable)}${c.underFreigrenze ? `; unter der Freigrenze ${F(c.freigrenze)} → 0` : ''}; nach mehr als einem Jahr veräußerte Anteile (steuerfrei) ${F(c.exempt)}.` }));
      const fundPos = sumCat('funds'), fundNeg = -sumCat('fundLosses'), op = de.otherPos - fundPos, on = de.otherNeg - fundNeg;
      check('Zeile 19', decl.z19, (de.shareGains - de.shareLosses) + op - on);
      check('Zeile 20', decl.z20, de.shareGains); check('Zeile 23', decl.z23, de.shareLosses); check('Zeile 41', decl.z41, de.creditable);
      return { rows, control: `Kontrolle: Zeile 19 (${F(decl.z19)}) = Gewinne aus Aktien ${F(de.shareGains)} − Verluste aus Aktien ${F(de.shareLosses)} + übrige Erträge ${F(op)} − übrige Verluste ${F(on)} = ${F(decl.control.recomputed)} — ${decl.control.ok ? 'stimmt überein ✓' : 'ABWEICHUNG ' + F(decl.control.diff) + ' ✗'}`,
               controlOk: decl.control.ok, pauschbetrag: de.estimate ? de.estimate.pauschbetrag : null, joint: !!st.joint, lines: !!L };
    }, { rows: [], control: '', controlOk: false, pauschbetrag: null, joint: !!st.joint, lines: !!L });

    // ─── Veräußerungen — по продажба и по лот (FIFO) ───
    const lotRows = (x, it) => {
      const lots = x.lots && x.lots.length ? x.lots : [{ date: '', qty: x.qty, costEUR: x.costEUR }], qtot = x.qty || 1;
      return lots.map((l, k) => {
        const share = l.qty / qtot, ccyB = l.ccy || x.currency, rb = l.date && ccyB && ccyB !== 'EUR' ? TC.rateInfo(table, ccyB, l.date) : null, rs = x.currency && x.currency !== 'EUR' ? TC.rateInfo(table, x.currency, x.date) : null;
        const feeShare = x.saleQty ? (x.saleFee || 0) * l.qty / x.saleQty : 0;
        return { sym: x.sym, label: label(x.sym), account: mask(x.account), broker: x.broker, buyDate: l.date, sellDate: x.date, qty: l.qty,
          buyPx: l.px == null ? null : l.px, buyCcy: ccyB, buyAmt: l.px == null ? null : l.qty * l.px + (l.feeO || 0), buyRate: rb && rb.rate, buyRateOn: rb && rb.on,
          sellPx: x.salePx == null ? null : x.salePx, sellCcy: x.currency, sellAmt: x.salePx == null ? null : l.qty * x.salePx - feeShare, sellRate: rs && rs.rate, sellRateOn: rs && rs.on,
          ak: l.costEUR, ve: x.proceedsEUR == null ? null : x.proceedsEUR * share, gv: l.costEUR == null || x.proceedsEUR == null ? null : x.proceedsEUR * share - l.costEUR,
          manual: !!l.manual, exempt: !!l.exempt, first: k === 0, note: k === 0 && it && it.fundType ? `Fondsart: ${({ equity: 'Aktienfonds', mixed: 'Mischfonds', realestate: 'Immobilienfonds', realestate_foreign: 'Immobilienfonds (Auslandsimmobilien)', other: 'sonstiger Fonds' })[it.fundType] || it.fundType}; Teilfreistellung ${Math.round((it.tf || 0) * 100)} % → G/V nach Teilfreistellung ${F(it.eur)}${it.vorabDeducted > 0 ? `; abzüglich Vorabpauschale ${F(it.vorabDeducted)}` : ''}` : '' };
      });
    };
    const block = (title, cats) => {
      const rows = []; de.items.filter(i => i.ri != null && cats.includes(i.cat)).forEach(it => rows.push(...lotRows(R[it.ri], it)));
      const sum = f => rows.reduce((s, r) => s + (r[f] || 0), 0);
      return { title, rows, ve: sum('ve'), ak: sum('ak'), gv: sum('gv') };
    };
    const sales = safe('Veräußerungen', () => {
      const stocks = block('Aktien', ['shareGains', 'shareLosses']), funds = block('Investmentfonds / ETF', ['funds', 'fundLosses']);
      stocks.gains = de.shareGains; stocks.losses = de.shareLosses;
      check('Aktien: Summe Gewinn/Verlust der Zeilen', stocks.gv, de.shareGains - de.shareLosses);
      // опции / Termingeschäfte — по запис (без лотове)
      const oitems = de.items.filter(i => i.ri != null && (i.cat === 'options' || i.cat === 'optionLosses'));
      const options = { title: 'Optionen / Termingeschäfte', rows: oitems.map(it => { const x = R[it.ri], lot0 = (x.lots || [])[0] || {};
        return { sym: x.sym, label: label(x.sym), account: mask(x.account), broker: x.broker, kind: x.premium ? 'Stillhalterprämie (Zufluss)' : x.short ? 'Glattstellung / Rückkauf' : 'Veräußerung',
          open: x.premium ? x.date : (x.openDate || lot0.date || ''), close: x.premium ? '' : x.date, qty: x.qty, ve: x.proceedsEUR, ak: x.costEUR, gv: x.gainEUR }; }) };
      options.gv = options.rows.reduce((s, r) => s + (r.gv || 0), 0);
      check('Optionen: Summe Gewinn/Verlust', options.gv, sumCat('options') + sumCat('optionLosses'));
      // крипто (Anlage SO)
      const cr = R.filter(x => x.year === year && x.assetClass === 'crypto' && x.gainEUR != null), crypto = { title: 'Kryptowerte (Anlage SO)', rows: [] };
      cr.forEach(x => crypto.rows.push(...lotRows(x, null).map(r => ({ ...r, taxable: !r.exempt }))));
      crypto.gv = crypto.rows.reduce((s, r) => s + (r.gv || 0), 0); crypto.taxable = cr.reduce((s, x) => s + (x.taxableGainEUR || 0), 0); crypto.exempt = cr.reduce((s, x) => s + (x.exemptGainEUR || 0), 0);
      return { stocks, funds, options, crypto };
    }, { stocks: { rows: [] }, funds: { rows: [] }, options: { rows: [] }, crypto: { rows: [] } });

    // ─── Dividenden, Zinsen, Quellensteuer — ред по ред ───
    const incRows = pred => fifo.incomes.filter(x => x.year === year && pred(x)).map(x => { const ri = x.currency && x.currency !== 'EUR' ? TC.rateInfo(table, x.currency, x.date) : null;
      return { date: x.date, label: x.sym ? label(x.sym) : '', desc: noCyr(x.desc), account: mask(x.account), broker: x.broker, amount: x.amount, ccy: x.currency, rate: ri && ri.rate, rateOn: ri && ri.on, eur: x.eur }; });
    const incomes = safe('Erträge', () => {
      const div = incRows(x => x.kind === 'dividend' && !x.pil), pil = incRows(x => x.kind === 'dividend' && x.pil), intr = incRows(x => x.kind === 'interest'), wh = incRows(x => x.kind === 'withholding');
      const sum = a => a.reduce((s, r) => s + r.eur, 0);
      const divItems = de.items.filter(i => ['dividends', 'otherNeg', 'pil'].includes(i.cat)).reduce((s, i) => s + i.eur, 0) + de.items.filter(i => i.distribution).reduce((s, i) => s + i.gross, 0);
      check('Dividenden (inkl. Ersatzzahlungen): Summe der Zeilen', sum(div) + sum(pil), divItems);
      check('Zinsen (Gutschriften): Summe der Zeilen', sum(intr.filter(r => r.eur >= 0)), sumCat('interest'));
      const bySym = {}; wh.forEach(r => { bySym[r.label] = (bySym[r.label] || 0) + r.eur; });
      check('Quellensteuer: einbehalten', Object.values(bySym).reduce((s, v) => s + Math.max(0, -v), 0), de.withheld);
      check('Quellensteuer: anrechenbar (Zeile 41)', (de.creditBySym || []).reduce((s, c) => s + c.credited, 0), de.creditable);
      return { dividends: { rows: div, total: sum(div) }, pil: { rows: pil, total: sum(pil) }, interest: { rows: intr, total: sum(intr), credits: sum(intr.filter(r => r.eur >= 0)), debits: sum(intr.filter(r => r.eur < 0)) },
               withholding: { rows: wh, total: sum(wh) }, credit: (de.creditBySym || []).map(c => ({ label: label(c.sym), withheld: c.withheld, gross: c.gross, cap: c.cap, credited: c.credited })), rate };
    }, { dividends: { rows: [], total: 0 }, pil: { rows: [], total: 0 }, interest: { rows: [], total: 0, credits: 0, debits: 0 }, withholding: { rows: [], total: 0 }, credit: [], rate });

    // ─── Besondere Vorgänge — какво е направено и защо ───
    const special = safe('Besondere Vorgänge', () => {
      const out = [], inY = d => String(d || '').startsWith(Y), A = a => `Konto ${mask(a)}`;
      const seen = new Set(), once = k => { if (seen.has(k)) return false; seen.add(k); return true; };
      const pend = fifo.pending || [], links = fifo.xferLinks || [];
      (ing.records || []).filter(r => r.kind === 'xfer' && inY(r.date)).forEach(r => {
        const inter = /inter-?company|internal|intra/i.test(r.xtype || ''), q = qtyDE(r.qty), what = `${q} Stück ${r.sym}`;
        if (r.dir === 'Out') out.push({ date: r.date, sym: r.sym, title: inter ? 'Übertrag zwischen eigenen Konten (Ausgang)' : 'Übertrag an einen anderen Broker / ein anderes Depot (Ausgang)',
          text: `${what} aus ${A(r.account)} übertragen (${r.xtype || 'Übertrag'}) — keine Veräußerung. ${inter ? 'Die Lots werden mit ihren ursprünglichen Kaufdaten und Anschaffungskosten in das Zielkonto übernommen.' : 'Die Lots wurden aus der FIFO-Berechnung dieses Kontos entfernt; die Anschaffungskosten gehen mit dem Übertrag auf das Zieldepot über.'}` });
        else if (inter) out.push({ date: r.date, sym: r.sym, title: 'Übertrag zwischen eigenen Konten (Eingang)', text: `${what} in ${A(r.account)} eingegangen (${r.xtype || 'Inter-Company'}) — keine Anschaffung. Die Lots wurden mit den ursprünglichen Kaufdaten und Anschaffungskosten des Ausgangskontos fortgeführt (FIFO nach dem Kaufdatum).` });
        else {
          const lk = links.find(l => l.sym === r.sym && l.date === r.date && l.account === r.account), pn = pend.find(p => p.sym === r.sym && p.date === r.date && p.account === r.account && p.kind === 'acats');
          out.push({ date: r.date, sym: r.sym, title: 'Einlieferung von einem anderen Broker (Eingang)',
            text: `${what} von einem anderen Broker in ${A(r.account)} eingeliefert (${r.xtype || 'Übertrag'}) — keine Anschaffung im Jahr ${year}. ` + (lk ? `${qtyDE(lk.linked)} Stück sind mit den Käufen in den Abrechnungen des anderen Brokers verknüpft (Kaufdatum und Anschaffungskosten übernommen; welche Lots ausgegangen sind, ist nach FIFO angenommen)${lk.rest > 1e-9 ? `; für ${qtyDE(lk.rest)} Stück wurde der Kauf nicht gefunden` : ''}.`
              : pn && pn.filled ? 'Kaufdatum und Kaufpreis vom Steuerpflichtigen angegeben (kein Kaufbeleg in den Abrechnungen) — Nachweis beifügen.' : 'Der Kauf ist in den Abrechnungen nicht enthalten — Anschaffungskosten fehlen (siehe „Offene Punkte“, soweit verkauft).') });
        }
      });
      (ing.records || []).filter(r => r.kind === 'split' && inY(r.date) && once(['s', r.sym, r.date, r.ratio].join('|'))).forEach(r => {
        const t = r.ratio >= 1 ? `${+r.ratio.toFixed(6)} : 1` : `1 : ${+(1 / r.ratio).toFixed(6)}`;
        out.push({ date: r.date, sym: r.sym, title: r.ratio >= 1 ? 'Aktiensplit' : 'Reverse Split', text: `${r.sym}: Split ${t} — die Stückzahl der offenen Lots wird mit dem Faktor multipliziert, die Gesamtanschaffungskosten und Kaufdaten bleiben unverändert (keine Veräußerung, kein Ertrag; § 20 Abs. 4a EStG sinngemäß).` });
      });
      const CT = { exchange: 'Umtausch / Namens- oder ISIN-Wechsel', reverse_split: 'Reverse Split mit neuer ISIN', mixed: 'Fusion gegen Bar und Aktien', cash: 'Barabfindung / Übernahme', cash_in_lieu: 'Spitzenausgleich in bar', worthless: 'Ausbuchung (Wertlosigkeit / Delisting)', spinoff: 'Abspaltung (Spin-off)', stockdiv: 'Aktiendividende' };
      (ing.corpEvents || []).filter(e => inY(e.date)).forEach(e => {
        const txt = {
          exchange: `${e.sym} → ${e.newSym}${e.factor && Math.abs(e.factor - 1) > 1e-9 ? ` (Faktor ${+Number(e.factor).toFixed(6)})` : ''}: Die Lots werden mit ursprünglichen Kaufdaten und Anschaffungskosten fortgeführt (Tausch von Anteilen, keine Veräußerung; § 20 Abs. 4a EStG sinngemäß).`,
          reverse_split: `${e.sym} → ${e.newSym} (Faktor ${+Number(e.factor).toFixed(6)}): Die Lots werden mit ursprünglichen Kaufdaten und Anschaffungskosten fortgeführt (keine Veräußerung).`,
          mixed: `${e.sym} → ${e.newSym}: Fusion mit Barabfindung und Aktien — der Barbetrag ist als Veräußerung eines wertmäßigen Anteils der Lots erfasst, der Rest als Umtausch. Steuerliche Behandlung zu prüfen.`,
          cash: `${e.sym}: Barabfindung — als Veräußerung erfasst.`,
          cash_in_lieu: `${e.sym}: Spitzenausgleich (Bruchteile in bar) — als Veräußerung dieser Anteile erfasst; zu prüfen.`,
          worthless: `${e.sym}: Ausbuchung wegen Wertlosigkeit bzw. Delisting — als Veräußerung zu 0 € erfasst (Verlust in Höhe der Anschaffungskosten); steuerliche Behandlung zu prüfen.`,
          spinoff: `${e.sym}: Abspaltung — Anschaffungskosten der neuen Aktien vom Steuerpflichtigen angegeben bzw. mit 0 € angesetzt (je nach Einstellung); zu prüfen.`,
          stockdiv: `${e.sym}: Aktiendividende — behandelt wie Gratisaktien (Gesamtanschaffungskosten unverändert) bzw. als Ertrag zum Marktwert, je nach Einstellung; zu prüfen.` }[e.type];
        if (txt) out.push({ date: e.date, sym: e.sym, title: CT[e.type] || e.type, text: txt + (e.desc ? ` Beschreibung laut Abrechnung: „${e.desc}“.` : ''), disputed: !!e.disputed });
      });
      (ing.aliases || []).forEach(a => { if ((ing.records || []).some(r => inY(r.date) && r.symOrig === a.from) && once(['a', a.from, a.to].join('|'))) out.push({ date: `${Y}-01-01`, sym: a.to, title: 'Ticker-Wechsel', text: `${a.from} → ${a.to}: dieselbe Wertpapier-ID (Conid ${a.conid}) in den Abrechnungen — die Lots von ${a.from} sind unter dem neuen Namen fortgeführt (Kaufdaten und Anschaffungskosten unverändert).` }); });
      R.filter(x => x.year === year).forEach(x => (x.lots || []).filter(l => l.manual).forEach(l => { if (once(['m', x.sym, l.date].join('|'))) out.push({ date: l.date, sym: x.sym, title: 'Anschaffungskosten manuell angegeben', text: `${x.sym}: Kaufdatum ${dmy(l.date)}${l.px != null ? `, Kaufpreis ${pxDE(l.px)} ${l.ccy || ''}` : ''} vom Steuerpflichtigen angegeben (kein Kaufbeleg in den Abrechnungen) — Nachweis beifügen.` }); }));
      const cg = {}; (fifo.controlLog || []).filter(c => c.year === year && c.type === 'start').forEach(c => { (cg[c.account + '|' + c.date] = cg[c.account + '|' + c.date] || []).push(c); });
      Object.values(cg).forEach(g => out.push({ date: g[0].date, sym: '', title: 'Anfangsbestand laut Abrechnung', text: `${A(g[0].account)}, Stand ${dmy(g[0].date)}: ${g.map(c => `${c.sym} — berechnet ${qtyDE(c.held)} Stück, laut Abrechnung ${qtyDE(c.reported)} Stück; ${qtyDE(c.dropped)} Stück der ältesten Lots wurden nicht verwendet`).join('; ')}. Für den Zeitraum davor liegt keine Abrechnung vor.` }));
      return out.sort((a, b) => String(a.date).localeCompare(String(b.date)));
    }, []);

    // ─── групите на „Не е сметнато“ (годината) ───
    const groups = safe('Nicht berücksichtigt', () => TC.skippedGroups(ing.skipped || [], { year, rate: rateFn, acked }), { law: [], info: [], review: [], missing: [] });
    const fmtTotals = g => Object.entries(g.year.totals).map(([c, v]) => ccyDE(v, c)).join(' + ');
    const kindRow = (g, useAll) => ({ title: g.de, basis: g.basisDe, n: useAll ? g.all.n : g.year.n, totals: g.sum ? fmtTotals(g) : '', eur: g.sum && g.year.n ? g.year.eur : null, eurMissing: g.year.eurMissing || 0, kind: g.kind });
    const excluded = { law: groups.law.filter(g => g.year.n).map(g => kindRow(g, false)), info: groups.info.filter(g => g.all.n).map(g => kindRow(g, true)), review: groups.review.filter(g => g.year.n || g.all.n).map(g => kindRow(g, g.kind === 'review' || g.kind === 'acked')).filter(r => r.n) };
    const debitInt = incomes.interest.debits;
    if (Math.abs(debitInt) > 0.004) excluded.law.push({ title: 'Sollzinsen (Debitzinsen)', basis: '§ 20 Abs. 9 EStG: Werbungskosten werden nicht abgezogen', n: incomes.interest.rows.filter(r => r.eur < 0).length, totals: '', eur: debitInt, eurMissing: 0, kind: 'debit_interest' });

    // ─── Offene Punkte: групата „липсващи данни“ + всичко, което прави годината НЕПЪЛНА ───
    const reasons = [];
    const rsn = (type, text) => reasons.push({ type, text });
    de.unmatched.forEach(u => { const sold = u.sold || u.qty; rsn('unmatched', `Verkauf ohne Kaufnachweis: ${u.sym}, ${qtyDE(sold)} Stück am ${dmy(u.date)} (${u.broker}, Konto ${mask(u.account)})${sold - u.qty > 1e-9 ? `, davon ${qtyDE(u.qty)} Stück ohne Kauf` : ''} — die Anschaffungskosten fehlen; dieser Verkauf (bzw. dieser Teil) ist NICHT in den Beträgen enthalten.`); });
    [...new Set((de.missingRates || []).map(m => `${m.currency}|${m.date}`))].forEach(k => { const [c, d] = k.split('|'); rsn('rate', `Kein EZB-Referenzkurs für ${c} am ${dmy(d)} — die betroffenen Buchungen sind NICHT in den Beträgen enthalten.`); });
    [...new Set((de.taintedSales || []).map(x => x.sym))].forEach(s => rsn('tainted', `${s}: Verkäufe im Jahr ${year} nach einem nicht gedeckten Verkauf — die Anschaffungskosten können falsch sein (fehlt eine ältere Abrechnung?).`));
    (de.reconcile || []).forEach(m => rsn('reconcile', `${m.sym} (Konto ${mask(m.account)}): Bestand laut Abrechnung zum ${dmy(m.date)} = ${qtyDE(m.reported)} Stück, berechnet = ${qtyDE(m.computed)} Stück — Abweichung${m.closed ? ' (die Abrechnung zeigt in diesem Konto keine Positionen)' : ''}.`));
    (de.unknownSales || []).forEach(u => rsn('unknown', `${u.sym} (${dmy(u.date)}): Verkauf von ${qtyDE(u.qty)} Stück, davon ${qtyDE(u.unknown)} Stück aus Lots ohne Anschaffungskosten — dieses Ergebnis ist NICHT in den Beträgen enthalten.`));
    (de.oldRulesData || []).forEach(o => rsn('oldrules', o.type === 'pre2009' ? `${o.year} liegt vor der Einführung der Abgeltungsteuer (2009) — altes Recht, nicht berechnet.`
      : o.type === 'altbestand' ? `${o.sym} (${dmy(o.date)}): ${qtyDE(o.qty)} Stück vor 2009 angeschafft (Altbestand) — der Gewinn daraus ist grundsätzlich steuerfrei, hier aber als steuerpflichtig berechnet; prüfen.`
      : `${o.sym} (${dmy(o.date)}): ${qtyDE(o.qty)} Anteile vor 2018 angeschafft — fiktive Veräußerung zum 31.12.2017 (§ 56 InvStG), hier nicht berücksichtigt; prüfen.`));
    const skipText = x => `Nicht ausgewertete Zeile — Abschnitt „${noCyr(x.section) || 'Datei'}“${noCyr(x.what) ? ', ' + noCyr(x.what) : ''}${x.date ? ', ' + dmy(x.date) : ''} (Datei ${maskFile(x.src)}${x.line ? ', Zeile ' + x.line : ''}): ${x.de || 'Inhalt nicht auswertbar oder nicht unterstützt (siehe Originalzeile)'}${x.amount ? ` — Betrag/Menge laut Zeile: ${x.amount}${x.currency ? ' ' + x.currency : ''}` : ''}; NICHT in den Beträgen enthalten.`;
    (de.skippedTaxable || []).forEach(x => rsn('skipped', skipText(x)));
    (de.skippedUndated || []).forEach(x => rsn('undated', skipText(x) + ' Das Jahr ist nicht erkennbar.'));
    (de.unreadFiles || []).forEach(x => rsn('file', `Datei „${maskFile(x.what)}“ wurde nicht ausgewertet (${x.de || 'unbekanntes Format, Lesefehler oder nur Mengenangaben'}) — enthaltene Veräußerungen oder Erträge sind NICHT in den Beträgen enthalten.`));
    errors.forEach(e => rsn('error', `Ein Abschnitt dieser Aufstellung konnte nicht vollständig erstellt werden (${e}).`));
    const complete = !!de.complete && !errors.length;
    if (!complete && !reasons.length) rsn('generic', 'Die Berechnung ist als unvollständig gekennzeichnet — Einzelheiten siehe Anwendung.');

    // ─── Methode (Hinweise, Annahmen) ───
    const method = [
      'Die Beträge wurden aus den beigefügten Originalabrechnungen der Broker (CSV-Exporte) mit einem selbst erstellten Rechenprogramm ermittelt. Die Berechnung erfolgt ausschließlich im Browser; es werden keine Daten übertragen.',
      'Veräußerungen: FIFO-Verfahren (zuerst angeschaffte Wertpapiere gelten als zuerst veräußert, § 20 Abs. 4 Satz 7 EStG), getrennt je Broker, Konto und Wertpapier.',
      'Währungsumrechnung: Anschaffungskosten und Veräußerungserlöse in fremder Währung werden mit dem Referenzkurs der Europäischen Zentralbank (EZB) am Tag der Anschaffung bzw. am Tag der Veräußerung in Euro umgerechnet (§ 20 Abs. 4 Satz 1 EStG); Erträge mit dem Kurs am Zuflusstag. Liegt für einen Tag kein Kurs vor (Wochenende, Feiertag), gilt der zuletzt davor veröffentlichte Kurs (in den Tabellen mit Datum vermerkt).',
      'Transaktionskosten (Kommissionen) sind in den Anschaffungskosten bzw. als Minderung des Veräußerungserlöses berücksichtigt.',
      'Verluste aus Aktienveräußerungen werden nur mit Gewinnen aus Aktienveräußerungen verrechnet (§ 20 Abs. 6 Satz 4 EStG); die Verrechnung und ein Verlustvortrag werden vom Finanzamt vorgenommen. Verlustvorträge aus Vorjahren sind in den Beträgen dieser Aufstellung nicht berücksichtigt; der Sparer-Pauschbetrag ist nicht abgezogen.',
      `Ausländische Quellensteuer: angesetzt wird die auf Dividenden einbehaltene Steuer, begrenzt auf ${Math.round(rate * 100)} % der Bruttodividende und auf die deutsche Steuer auf diese Erträge; Nachweise (Abrechnungen) liegen bei.`,
    ];
    if (decl.funds != null) method.push('Investmentfonds (ETF): Erträge und Gewinne sind je Fondsart angegeben; die Teilfreistellung (§ 20 InvStG) wendet das Finanzamt an.');
    if ((de.crypto || []).length) method.push('Kryptowerte (§ 23 EStG): Veräußerungen innerhalb eines Jahres nach der Anschaffung sind steuerpflichtig (Freigrenze je Person); Veräußerungen danach sind steuerfrei und gesondert ausgewiesen.');

    // ─── Quellen ───
    const sources = (ing.files || []).map(f => ({ name: maskFile(f.name), broker: f.format === 'ecb_rates' ? 'EZB' : noCyr(f.broker), format: TC.REPORT_FORMATS[f.format] || f.format, period: f.period || (f.from ? `${dmy(f.from)}${f.to && f.to !== f.from ? ' – ' + dmy(f.to) : ''}` : ''), records: f.records || 0, used: f.format !== 'taxtool_result' && f.format !== 'xlsx' && f.format !== 'unknown' && !f.error }));
    const now = ctx.now || new Date().toISOString().slice(0, 10);
    return { title: `Aufstellung der Kapitalerträge ${year} — selbst erstellt`, year, name: String(ctx.name || '').trim(), createdOn: dmy(now), joint: !!st.joint, complete, reasons, brokers, summary, sales, incomes, special, excluded,
      method, sources, rateSource: typeof ctx.rateSource === 'string' ? noCyr(ctx.rateSource) : Object.entries(ctx.rateSource || {}).map(([c, s]) => c + ': ' + TC.rateSourceDE(s)).join('; '), checks, checksOk: checks.every(c => c.ok), errors, footer: TC.REPORT_FOOTER, hasRates: Object.keys(table).length > 0 };
  };

  // ─── HTML на отчета (немски; стиловете са в tax.html под #reportRoot) ───
  TC.reportHTML = function (m) {
    const th = a => `<tr>${a.map(c => `<th${c.startsWith('>') ? ' class="n"' : ''}>${esc(c.replace(/^>/, ''))}</th>`).join('')}</tr>`;
    const td = (v, cls) => `<td${cls ? ` class="${cls}"` : ''}>${v}</td>`;
    const e0 = v => v == null ? '—' : esc(v);
    const eur = v => v == null || !isFinite(v) ? '—' : esc(F(v));
    const sgn = v => v == null ? '' : v < 0 ? ' neg' : '';
    const rateCell = (r, on, date) => r == null ? '—' : `${esc(rateDE(r))}${on && on !== date ? `<div class="s">(Kurs vom ${esc(dmy(on))})</div>` : ''}`;
    const sec = (t, body, cls) => `<section class="${cls || ''}"><h2>${esc(t)}</h2>${body}</section>`;
    const out = [];
    // заглавие
    out.push(`<header><h1>${esc(m.title)}</h1><table class="kv"><tr><td>Name</td><td>${m.name ? esc(m.name) : '______________________________'}${m.joint ? ' <span class="s">(Zusammenveranlagung)</span>' : ''}</td></tr>
      <tr><td>Steuerjahr</td><td>${esc(m.year)}</td></tr><tr><td>Erstellt am</td><td>${esc(m.createdOn)}</td></tr>
      <tr><td>Broker / Konten</td><td>${m.brokers.length ? m.brokers.map(b => `${esc(b.broker)}${b.account ? ', Konto ' + esc(b.account) : ''} <span class="s">(${b.from ? 'Daten ' + esc(dmy(b.from)) + (b.to && b.to !== b.from ? ' – ' + esc(dmy(b.to)) : '') + '; ' : ''}${b.records} Datensätze${b.files > 1 ? ', ' + b.files + ' Dateien' : ''})</span>`).join('<br>') : '—'}</td></tr></table></header>`);
    // червена рамка при НЕПЪЛНО
    if (!m.complete) {
      const top = m.reasons.slice(0, 8);
      out.push(`<div class="redframe"><b>ACHTUNG: Diese Aufstellung ist UNVOLLSTÄNDIG.</b> Die Beträge sind vorläufig und dürfen so nicht abgegeben werden. Gründe:<ul>${top.map(r => `<li>${esc(r.text)}</li>`).join('')}</ul>${m.reasons.length > top.length ? `<div class="s">… und ${m.reasons.length - top.length} weitere Punkte — siehe Abschnitt „Offene Punkte“.</div>` : ''}</div>`);
    }
    // Zusammenfassung
    const S = m.summary;
    out.push(sec('Zusammenfassung — Anlage KAP', `<table class="t sum">${th(['Feld in der Steuererklärung (Anlage KAP)', '>Betrag', 'Berechnung'])}${S.rows.map(r => `<tr class="${r.part ? 'part' : ''}"><td>${r.part ? '<span class="s">davon · </span>' : ''}<b>${esc(r.field)}</b>${r.ref ? ` <span class="s">(${esc(r.ref)} — im Formular prüfen)</span>` : ''}</td><td class="n${sgn(r.eur)}"><b>${eur(r.eur)}</b></td><td class="s">${esc(r.calc)}</td></tr>`).join('')}</table>
      <div class="ctl">${esc(S.control)}</div>
      ${S.lines ? '' : `<div class="s">Die Zeilennummern sind für ${esc(m.year)} nicht geprüft — das Feld bitte anhand des Textes im Formular suchen.</div>`}
      ${S.pauschbetrag != null ? `<div class="s">Der Sparer-Pauschbetrag (${esc(F(S.pauschbetrag))}${S.joint ? ', Zusammenveranlagung' : ''}) ist in diesen Beträgen nicht abgezogen; er wird vom Finanzamt berücksichtigt.</div>` : ''}`));
    // Methode
    out.push(sec('Methode', `<ul>${m.method.map(t => `<li>${esc(t)}</li>`).join('')}</ul>`));
    // Veräußerungen
    const SA = m.sales, saleTable = (b, extraCols) => {
      if (!b.rows.length) return '<div class="s">Keine Veräußerungen.</div>';
      return `<table class="t wide">${th(['Wertpapier', 'Kauf', 'Verkauf', '>Stück', '>Kaufkurs je Stück / Kaufbetrag (Währung)', '>EZB-Kurs Kauf', '>Anschaffungskosten EUR', '>Verkaufskurs je Stück / Verkaufsbetrag (Währung)', '>EZB-Kurs Verkauf', '>Veräußerungserlös EUR', '>Gewinn / Verlust EUR'])}
        ${b.rows.map(r => `<tr${r.first ? ' class="first"' : ''}><td>${esc(r.label)}<div class="s">${esc(r.broker)}${r.account ? ' · ' + esc(r.account) : ''}${r.manual ? ' · Kaufdaten manuell angegeben' : ''}${r.exempt ? ' · Haltedauer über 1 Jahr (steuerfrei)' : ''}</div></td>
          <td>${e0(r.buyDate ? dmy(r.buyDate) : '')}</td><td>${esc(dmy(r.sellDate))}</td><td class="n">${esc(qtyDE(r.qty))}</td>
          <td class="n">${r.buyPx == null ? '—' : esc(pxDE(r.buyPx) + NB + (r.buyCcy || ''))}<div class="s">${r.buyAmt == null ? '' : '= ' + esc(ccyDE(r.buyAmt, r.buyCcy))}</div></td><td class="n">${r.buyCcy && r.buyCcy !== 'EUR' ? rateCell(r.buyRate, r.buyRateOn, r.buyDate) : '—'}</td><td class="n">${eur(r.ak)}</td>
          <td class="n">${r.sellPx == null ? '—' : esc(pxDE(r.sellPx) + NB + (r.sellCcy || ''))}<div class="s">${r.sellAmt == null ? '' : '= ' + esc(ccyDE(r.sellAmt, r.sellCcy))}</div></td><td class="n">${r.sellCcy && r.sellCcy !== 'EUR' ? rateCell(r.sellRate, r.sellRateOn, r.sellDate) : '—'}</td><td class="n">${eur(r.ve)}</td><td class="n${sgn(r.gv)}"><b>${eur(r.gv)}</b></td></tr>
          ${r.note ? `<tr class="note"><td colspan="11" class="s">${esc(r.note)}</td></tr>` : ''}`).join('')}
        <tr class="tot"><td colspan="6">Zwischensumme ${esc(b.title)}</td><td class="n">${eur(b.ak)}</td><td colspan="2"></td><td class="n">${eur(b.ve)}</td><td class="n${sgn(b.gv)}"><b>${eur(b.gv)}</b></td></tr></table>`;
    };
    let ver = `<div class="s">Je Verkauf eine Zeile pro verbrauchtem Kauf-Lot (FIFO). Einzelbeträge sind auf Cent gerundet; Summen werden aus den ungerundeten Beträgen gebildet — Rundungsdifferenzen von wenigen Cent sind möglich.</div>`;
    ver += `<h3>Aktien</h3>${saleTable(SA.stocks)}${SA.stocks.rows.length ? `<table class="t tot2"><tr><td>Summe der Gewinne aus Aktienveräußerungen (Zeile 20)</td><td class="n">${eur(SA.stocks.gains)}</td></tr><tr><td>Summe der Verluste aus Aktienveräußerungen (Zeile 23, positiv)</td><td class="n">${eur(SA.stocks.losses)}</td></tr><tr><td><b>Saldo Aktienveräußerungen</b></td><td class="n${sgn(SA.stocks.gains - SA.stocks.losses)}"><b>${eur(SA.stocks.gains - SA.stocks.losses)}</b></td></tr></table>` : ''}`;
    if (SA.funds.rows.length) ver += `<h3>Investmentfonds / ETF (Anlage KAP-INV)</h3>${saleTable(SA.funds)}`;
    if (SA.options.rows.length) ver += `<h3>Optionen / Termingeschäfte</h3><table class="t">${th(['Instrument', 'Art', 'Eröffnung / Zufluss', 'Schluss', '>Stück', '>Erlös EUR', '>Kosten EUR', '>Gewinn / Verlust EUR'])}${SA.options.rows.map(r => `<tr><td>${esc(r.label)}<div class="s">${esc(r.broker)}${r.account ? ' · ' + esc(r.account) : ''}</div></td><td>${esc(r.kind)}</td><td>${r.open ? esc(dmy(r.open)) : '—'}</td><td>${r.close ? esc(dmy(r.close)) : '—'}</td><td class="n">${esc(qtyDE(r.qty))}</td><td class="n">${eur(r.ve)}</td><td class="n">${eur(r.ak)}</td><td class="n${sgn(r.gv)}"><b>${eur(r.gv)}</b></td></tr>`).join('')}<tr class="tot"><td colspan="7">Zwischensumme Optionen / Termingeschäfte</td><td class="n${sgn(SA.options.gv)}"><b>${eur(SA.options.gv)}</b></td></tr></table>`;
    if (SA.crypto.rows.length) ver += `<h3>Kryptowerte (Anlage SO, § 23 EStG)</h3>${saleTable(SA.crypto)}<table class="t tot2"><tr><td>Steuerpflichtig (Haltedauer bis 1 Jahr)</td><td class="n">${eur(SA.crypto.taxable)}</td></tr><tr><td>Steuerfrei (Haltedauer über 1 Jahr)</td><td class="n">${eur(SA.crypto.exempt)}</td></tr></table>`;
    out.push(sec(`Veräußerungen ${m.year}`, ver, 'landscape-ok'));
    // Erträge
    const IN = m.incomes, incTable = (rows, total, totalLabel, withDesc) => rows.length ? `<table class="t">${th(['Datum', 'Wertpapier / Beschreibung', 'Konto', '>Betrag (Währung)', '>EZB-Kurs', '>Betrag EUR'])}${rows.map(r => `<tr><td>${esc(dmy(r.date))}</td><td>${r.label ? esc(r.label) : ''}${r.desc ? `<div class="s">${esc(r.desc)}</div>` : ''}</td><td class="s">${esc(r.broker)}${r.account ? ' · ' + esc(r.account) : ''}</td><td class="n">${esc(ccyDE(r.amount, r.ccy))}</td><td class="n">${r.ccy && r.ccy !== 'EUR' ? rateCell(r.rate, r.rateOn, r.date) : '—'}</td><td class="n${sgn(r.eur)}">${eur(r.eur)}</td></tr>`).join('')}<tr class="tot"><td colspan="5">${esc(totalLabel)}</td><td class="n${sgn(total)}"><b>${eur(total)}</b></td></tr></table>` : '<div class="s">Keine Buchungen.</div>';
    out.push(sec(`Dividenden ${m.year}`, incTable(IN.dividends.rows, IN.dividends.total, 'Summe Dividenden')));
    if (IN.pil.rows.length) out.push(sec(`Ersatzzahlungen für Dividenden (Payment in Lieu) ${m.year}`, incTable(IN.pil.rows, IN.pil.total, 'Summe Ersatzzahlungen')));
    out.push(sec(`Zinsen ${m.year}`, incTable(IN.interest.rows, IN.interest.total, 'Summe Zinsen (Gutschriften abzüglich Belastungen)') + (Math.abs(IN.interest.debits) > 0.004 ? `<div class="s">Davon Sollzinsen (Belastungen) ${esc(F(IN.interest.debits))} — nicht abzugsfähig, in den Beträgen nicht berücksichtigt.</div>` : '')));
    out.push(sec(`Quellensteuer ${m.year}`, incTable(IN.withholding.rows, IN.withholding.total, 'Summe einbehaltene Quellensteuer (negativ = einbehalten)') + (IN.credit.length ? `<h3>Anrechenbare ausländische Steuern (Zeile 41)</h3><table class="t">${th(['Wertpapier', '>Einbehalten EUR', '>Bruttodividende EUR', `>Höchstbetrag EUR (${Math.round(IN.rate * 100)} %)`, '>Anrechenbar EUR'])}${IN.credit.map(c => `<tr><td>${esc(c.label)}</td><td class="n">${eur(c.withheld)}</td><td class="n">${eur(c.gross)}</td><td class="n">${eur(c.cap)}</td><td class="n"><b>${eur(c.credited)}</b></td></tr>`).join('')}<tr class="tot"><td>Summe</td><td class="n">${eur(IN.credit.reduce((s, c) => s + c.withheld, 0))}</td><td class="n">${eur(IN.credit.reduce((s, c) => s + c.gross, 0))}</td><td class="n"></td><td class="n"><b>${eur(IN.credit.reduce((s, c) => s + c.credited, 0))}</b></td></tr></table>` : '')));
    // Besondere Vorgänge
    out.push(sec('Besondere Vorgänge', m.special.length ? `<table class="t">${th(['Datum', 'Wertpapier', 'Vorgang', 'Behandlung und Begründung'])}${m.special.map(s => `<tr><td>${esc(dmy(s.date))}</td><td>${esc(s.sym || '')}</td><td>${esc(s.title)}${s.disputed ? ' <span class="s">(zu prüfen)</span>' : ''}</td><td class="s">${esc(s.text)}</td></tr>`).join('')}</table>` : '<div class="s">Keine besonderen Vorgänge (Übertrage, Splits, Fusionen, Ticker-Wechsel) im Jahr ' + esc(m.year) + '.</div>'));
    // Nicht berücksichtigt
    const ex = m.excluded, exRows = rows => rows.map(r => `<tr><td>${esc(r.title)}</td><td class="n">${r.n}</td><td class="n">${r.totals ? esc(r.totals) : ''}${r.eur != null ? `<div>${esc(F(r.eur))}${r.eurMissing ? ' <span class="s">(ohne Umrechnung für ' + r.eurMissing + ' Zeilen — kein Kurs)</span>' : ''}</div>` : ''}</td><td class="s">${esc(r.basis)}</td></tr>`).join('');
    let nb = '';
    nb += ex.law.length ? `<table class="t">${th(['Art', '>Anzahl', '>Summe (netto; − = Belastung)', 'Rechtsgrundlage'])}${exRows(ex.law)}</table>` : '<div class="s">Keine solchen Positionen im Jahr ' + esc(m.year) + '.</div>';
    if (ex.info.length) nb += `<div class="s" style="margin-top:6px">Weitere Zeilen der Abrechnungen ohne steuerliche Bedeutung (nicht berechnet): ${ex.info.map(r => `${r.n}× ${esc(r.title)}`).join('; ')}.</div>`;
    out.push(sec('Nicht berücksichtigt — nicht abzugsfähig', nb));
    if (ex.review.length) out.push(sec('Hinweise — nicht in den Beträgen enthalten', `<table class="t">${th(['Art', '>Anzahl', '>Summe', 'Hinweis'])}${exRows(ex.review)}</table>`));
    // Offene Punkte
    out.push(sec('Offene Punkte', m.reasons.length ? `<ol>${m.reasons.map(r => `<li class="${r.type === 'generic' ? '' : 'open'}">${esc(r.text)}</li>`).join('')}</ol>` : '<div>Keine offenen Punkte.</div>'));
    // Quellen
    out.push(sec('Quellen — ausgewertete Dateien', `<table class="t">${th(['Datei', 'Broker', 'Format', 'Zeitraum', '>Datensätze'])}${m.sources.map(s => `<tr><td>${esc(s.name)}</td><td>${esc(s.broker)}</td><td class="s">${esc(s.format)}${s.used ? '' : ' — nicht ausgewertet'}</td><td>${esc(s.period)}</td><td class="n">${s.records || ''}</td></tr>`).join('')}</table>${m.rateSource ? `<div class="s">Wechselkurse: ${esc(m.rateSource)}</div>` : ''}`));
    out.push(`<footer>${esc(m.footer)}</footer>`);
    return `<div class="rp" lang="de">${out.join('\n')}</div>`;
  };
})(typeof window !== 'undefined' ? window : globalThis);
