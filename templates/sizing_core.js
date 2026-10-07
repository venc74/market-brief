// Оразмеряване на позиция — ЧИСТА функция, без DOM и без мрежа (07.10.2026). Работи в браузъра (глобален MBSizing) и в node (module.exports) — един и същи файл, който се вгражда
// в страницата и който проверва test_sizing_js.py. Баланс, риск и таван са лични: стоят САМО в localStorage на устройството (виж sizing_ui.js) и никога не се изпращат никъде.
(function (root) {
  "use strict";

  function num(x) {                                              // строго: "80 000" или "12abc" не са числа (parseFloat би ги прочел като 80 и 12); запетаята е десетичен знак
    if (typeof x === "number") return isFinite(x) ? x : NaN;
    if (x === null || x === undefined) return NaN;
    var s = String(x).trim().replace(",", ".");
    if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(s)) return NaN;
    var n = parseFloat(s);
    return isFinite(n) ? n : NaN;
  }

  // o: { balance, riskPct, capPct, applyRegime, regimeFactor, entry, stop, adrPct, strategy }
  // → { ok:false, reason:"data"|"balance"|"settings" } или { ok:true, shares, value, pctOfAccount, lossAtStop, effRiskPct, ... }
  function sizePosition(o) {
    var entry = num(o.entry), stop = num(o.stop);
    // липсващи данни или стоп на/над входа → без брой акции
    if (!(entry > 0) || !(stop > 0) || !(stop < entry)) return { ok: false, reason: "data" };
    var balance = num(o.balance);
    if (!(balance > 0)) return { ok: false, reason: "balance" };
    var risk = num(o.riskPct), cap = num(o.capPct);
    if (!(risk > 0) || !(cap > 0)) return { ok: false, reason: "settings" };

    var rf = num(o.regimeFactor);
    var factor = (o.applyRegime && rf > 0) ? rf : 1;            // режимният фактор е върху ВЪВЕДЕНИЯ риск, само ако отметката е включена
    var effRisk = risk * factor;                                 // % от сметката
    var perShare = entry - stop;
    var riskBudget = balance * effRisk / 100;
    var EPS = 1e-9;
    var shares = Math.floor(riskBudget / perShare + EPS);
    var value = shares * entry;
    var capValue = balance * cap / 100;
    var capped = false;
    if (value > capValue + EPS) {                                // позицията надвишава тавана → свива се до тавана
      shares = Math.floor(capValue / entry + EPS);
      value = shares * entry;
      capped = true;
    }
    var lossAtStop = shares * perShare;                          // реалният риск при стопа (след свиване може да е под бюджета)
    var stopPct = perShare / entry * 100;
    var adr = num(o.adrPct);
    return {
      ok: true,
      shares: shares,
      value: value,
      pctOfAccount: value / balance * 100,
      lossAtStop: lossAtStop,
      effRiskPct: effRisk,                                       // въведеният риск × режимния фактор
      factor: factor,
      realRiskPct: lossAtStop / balance * 100,                   // реалният риск при стопа, % от сметката
      capped: capped,
      capPct: cap,
      gap10: value * 0.10,                                       // загуба при гап −10% / −15% (стойност на позицията × 0.10 / 0.15)
      gap15: value * 0.15,
      perShare: perShare,
      stopPct: stopPct,
      tooSmall: shares < 1,
      // стратегия Kullamagi (qm_breakout/qm_ep): стопът е по-далеч от 1 ADR под входа → акцията е избягала, входът е преследване. Допуск: ADR е закръглен до 0.01 п.п., а стопът — до цент
      // (иначе публикуваният стоп = вход × (1 − ADR) би дал фалшиво предупреждение: 7.193% > 7.19%)
      chase: o.strategy === "kullamagi" && adr > 0 && stopPct > adr + 0.005 + 0.005 / entry * 100 + 1e-9
    };
  }

  function money(n) {                                            // "$5,466" — без locale, за да е еднакво на всяко устройство
    var s = String(Math.round(Math.abs(n)));
    s = s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return (n < 0 ? "−$" : "$") + s;
  }

  function pct(n, d) {                                           // 0.5 → "0.5%", 25 → "25%", 0.25 → "0.25%"
    if (!isFinite(n)) return "—";
    return String(parseFloat(n.toFixed(d === undefined ? 1 : d))) + "%";
  }

  var api = { sizePosition: sizePosition, money: money, pct: pct, num: num };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MBSizing = api;
})(typeof window !== "undefined" ? window : this);
