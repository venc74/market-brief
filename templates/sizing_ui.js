// Оразмеряване на позиция в браузъра (07.10.2026): настройки (баланс, риск %, таван %, режимен фактор) само в localStorage на устройството; всеки достъп е в try/catch, а без
// localStorage страницата работи нормално (настройките важат до затваряне на страницата). Нищо не се изпраща и не се записва никъде другаде. Математиката е в sizing_core.js (MBSizing).
(function () {
  "use strict";
  var S = window.MBSizing;
  if (!S) return;

  var KEY = "mb_settings_v1";
  var DEFAULTS = { balance: "", risk: "0.5", cap: "25", regime: true };
  var state = { balance: DEFAULTS.balance, risk: DEFAULTS.risk, cap: DEFAULTS.cap, regime: DEFAULTS.regime };
  var persisted = true;

  function load() {
    try {
      var raw = window.localStorage.getItem(KEY);
      if (!raw) return;
      var o = JSON.parse(raw);
      if (o && typeof o === "object") {
        if (o.balance !== undefined) state.balance = String(o.balance);
        if (o.risk !== undefined) state.risk = String(o.risk);
        if (o.cap !== undefined) state.cap = String(o.cap);
        if (o.regime !== undefined) state.regime = !!o.regime;
      }
    } catch (e) { persisted = false; }
  }

  function save() {
    try { window.localStorage.setItem(KEY, JSON.stringify(state)); }
    catch (e) { persisted = false; }
  }

  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  }

  function line(parts, cls) {                       // parts: низове или [болд текст]
    var d = el("div", undefined, cls);
    parts.forEach(function (p) {
      if (Array.isArray(p)) d.appendChild(el("b", p[0]));
      else d.appendChild(document.createTextNode(p));
    });
    return d;
  }

  function cardInputs(card) {
    var entry = card.getAttribute("data-entry"), stop = card.getAttribute("data-stop");
    var adj = card.querySelector(".lv-adj");
    if (adj && !adj.hidden) {                       // "коригирай": реален вход/стоп само за тази карта (не се записват)
      entry = adj.querySelector(".lv-in-entry").value;
      stop = adj.querySelector(".lv-in-stop").value;
    }
    return { entry: entry, stop: stop };
  }

  function renderCard(card) {
    var box = card.querySelector(".lv-size");
    if (!box) return;
    var inp = cardInputs(card);
    var factor = S.num(card.getAttribute("data-factor"));
    var res = S.sizePosition({
      balance: state.balance, riskPct: state.risk, capPct: state.cap,
      applyRegime: state.regime, regimeFactor: factor,
      entry: inp.entry, stop: inp.stop, adrPct: card.getAttribute("data-adr"),
      strategy: card.getAttribute("data-strategy")
    });
    while (box.firstChild) box.removeChild(box.firstChild);
    box.setAttribute("data-state", res.ok ? "ok" : res.reason);
    if (!res.ok) {
      if (res.reason === "balance") box.appendChild(el("div", "въведи баланса в настройките, за да видиш размера на позицията", "lv-hint"));
      else if (res.reason === "settings") box.appendChild(el("div", "провери настройките: рискът и таванът трябва да са положителни числа", "lv-hint"));
      else box.appendChild(el("div", "няма достатъчно данни", "lv-hint"));
      return;
    }
    var label = card.getAttribute("data-regime-label") || "режимен фактор";
    var note = card.getAttribute("data-regime-note") || "";
    var riskTxt = "риск " + S.pct(S.num(state.risk), 2);
    if (res.factor !== 1) riskTxt += " × " + res.factor + " " + label + " = " + S.pct(res.effRiskPct, 2);
    else if (state.regime && note) riskTxt += " (" + note + ")";
    box.appendChild(line([riskTxt + " от сметката"], "lv-risk"));
    if (res.tooSmall) {
      box.appendChild(line(["0 акции — рисковият бюджет не стига за 1 акция при този стоп"], "lv-warn"));
    } else {
      box.appendChild(line([[res.shares + " акции"], " · " + S.money(res.value) + " (" + S.pct(res.pctOfAccount) + " от сметката)"], "lv-main"));
    }
    if (res.capped) {
      box.appendChild(line(["ограничено от тавана (" + S.pct(res.capPct) + " от сметката) — реален риск при стопа " + S.money(res.lossAtStop) + " (" + S.pct(res.realRiskPct, 2) + " от сметката)"], "lv-warn"));
    }
    box.appendChild(line(["загуба при стоп: ", [S.money(res.lossAtStop)]], "lv-loss"));
    box.appendChild(line(["при гап −10%: ", [S.money(res.gap10)], " · при гап −15%: ", [S.money(res.gap15)]], "lv-loss"));
    if (res.chase) box.appendChild(line(["⚠ акцията е избягала над 1 ADR — входът е преследване"], "lv-warn"));
  }

  function renderStreak() {                           // "10 поредни загуби ≈ −X% от сметката" — 10 × ефективния риск (виж MBSizing.losingStreak)
    var box = document.getElementById("mb-streak"), panel = document.getElementById("mb-settings");
    if (!box) return;
    var pf = panel ? S.num(panel.getAttribute("data-regime-factor")) : NaN;
    var r = S.losingStreak({ riskPct: state.risk, applyRegime: state.regime, regimeFactor: pf, n: 10 });
    if (!r.ok) { box.textContent = "10 поредни загуби ≈ — (въведи риск на сделка)"; return; }
    var txt = "10 поредни загуби ≈ −" + S.pct(r.lossPct, 2) + " от сметката (10 × риск " + S.pct(r.riskPct, 2);
    if (r.factor !== 1) txt += " × " + r.factor + " защитен режим; за QM и EP, които са без режимен фактор: −" + S.pct(r.lossPctFull, 2);
    box.textContent = txt + ")";
  }

  function renderAll() {
    var cards = document.querySelectorAll(".lv");
    for (var i = 0; i < cards.length; i++) renderCard(cards[i]);
    renderStreak();
    var n = document.getElementById("mb-persist-note");
    if (n) n.hidden = persisted;
  }

  function initSettings() {
    var btn = document.getElementById("mb-settings-btn"), panel = document.getElementById("mb-settings");
    var fb = document.getElementById("mb-balance"), fr = document.getElementById("mb-risk"), fc = document.getElementById("mb-cap"), fg = document.getElementById("mb-regime");
    if (!btn || !panel || !fb || !fr || !fc || !fg) return;
    fb.value = state.balance; fr.value = state.risk; fc.value = state.cap; fg.checked = !!state.regime;
    function toggle(open) {
      var show = open === undefined ? panel.hidden : open;
      panel.hidden = !show;
      btn.setAttribute("aria-expanded", show ? "true" : "false");
    }
    btn.addEventListener("click", function () { toggle(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") toggle(false); });
    function onChange() {
      state.balance = fb.value; state.risk = fr.value; state.cap = fc.value; state.regime = fg.checked;
      save();
      renderAll();
    }
    [fb, fr, fc].forEach(function (f) { f.addEventListener("input", onChange); });
    fg.addEventListener("change", onChange);
    var hints = document.querySelectorAll(".lv-hint-open");
    for (var i = 0; i < hints.length; i++) hints[i].addEventListener("click", function () { toggle(true); });
  }

  function initCards() {
    var cards = document.querySelectorAll(".lv");
    Array.prototype.forEach.call(cards, function (card) {
      var adjBtn = card.querySelector(".lv-adjust-btn"), adj = card.querySelector(".lv-adj");
      if (!adjBtn || !adj) return;
      var fe = adj.querySelector(".lv-in-entry"), fs = adj.querySelector(".lv-in-stop"), rs = adj.querySelector(".lv-reset");
      function reset() { fe.value = card.getAttribute("data-entry"); fs.value = card.getAttribute("data-stop"); }
      adjBtn.addEventListener("click", function () {
        var open = adj.hidden;
        if (open) reset();
        adj.hidden = !open;
        adjBtn.setAttribute("aria-expanded", open ? "true" : "false");
        adjBtn.textContent = open ? "скрий" : "коригирай";
        renderCard(card);
      });
      fe.addEventListener("input", function () { renderCard(card); });
      fs.addEventListener("input", function () { renderCard(card); });
      if (rs) rs.addEventListener("click", function () { reset(); renderCard(card); });
    });
  }

  load();
  initSettings();
  initCards();
  renderAll();
  window.MBSizingUI = { renderAll: renderAll, state: state };
})();
