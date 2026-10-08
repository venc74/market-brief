"""
Стоп и размер (07.10.2026) · JavaScript в браузъра: templates/sizing_core.js (математиката) и sizing_ui.js (настройки в localStorage, "коригирай", режимният фактор) — върху СЪЩИТЕ файлове, които
се вграждат в страницата. Python не може да изпълни JS, затова: (1) математиката — през `node`, ако го има (в CI го има), иначе през headless Chrome; (2) цялата страница (DOM) — през headless Chrome.
Ако няма нито едното — изрично "SKIP" с причината и код 0 (не се мълчи: виж изхода). Очакваните числа са смятани НЕЗАВИСИМО тук (чист Python), не взети от JS.

РЕАЛНО: нивата на EXPD (Watchlist, buy-stop 194.59 / стоп 181.53, ADR 2.01% — реалният ADR20 към 02.10), на EXEL (Action, 29.06: вход 54.77 / стоп 50.39 — таван 8%) и на QM картите DOCN, CORT, CRL (скан
към 02.10); базата на страницата е реалният бриф от 05.10. Тестовите настройки са тези от задачата: баланс 80000, риск 0.5%, таван 25%. СИНТЕТИЧНО (маркирано): таванът 5% (за да се получи
свиване), коригираните вход/стоп, невалидните входове. Пускане: python test_sizing_js.py
"""
import sys, os, re, json, copy, math, shutil, pathlib, tempfile, subprocess, datetime as dt
from html.parser import HTMLParser
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

CORE = ROOT / "templates" / "sizing_core.js"
UI = ROOT / "templates" / "sizing_ui.js"


# ── независим Python-еталон ──────────────────────────────────────────────────
def r0(x):                                           # закръгляне "половинките нагоре" като Math.round (за положителни)
    return int(math.floor(x + 0.5))


def money(x):
    return f"${r0(abs(x)):,}"


def pct(x, d=1):
    s = f"{x:.{d}f}"
    s = s.rstrip("0").rstrip(".") if "." in s else s
    return s + "%"


def ref(balance, risk, cap, apply_regime, factor, entry, stop, adr=None, strategy="canslim"):
    if not (entry > 0 and stop > 0 and stop < entry):
        return {"ok": False, "reason": "data"}
    if not balance > 0:
        return {"ok": False, "reason": "balance"}
    if not (risk > 0 and cap > 0):
        return {"ok": False, "reason": "settings"}
    f = factor if (apply_regime and factor and factor > 0) else 1
    eff = risk * f
    per = entry - stop
    shares = math.floor(balance * eff / 100 / per + 1e-9)
    value = shares * entry
    capped = False
    if value > balance * cap / 100 + 1e-9:
        shares = math.floor(balance * cap / 100 / entry + 1e-9)
        value = shares * entry
        capped = True
    loss = shares * per
    stop_pct = per / entry * 100
    return {"ok": True, "shares": shares, "value": value, "pctOfAccount": value / balance * 100, "lossAtStop": loss, "effRiskPct": eff, "factor": f, "realRiskPct": loss / balance * 100,
            "capped": capped, "gap10": value * 0.10, "gap15": value * 0.15, "stopPct": stop_pct, "tooSmall": shares < 1,
            "chase": strategy == "kullamagi" and adr is not None and adr > 0 and stop_pct > adr + 0.005 + 0.005 / entry * 100 + 1e-9}


# ── среда: node / Chrome ─────────────────────────────────────────────────────
def find_chrome():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if os.path.exists(mac) else None


NODE, CHROME = shutil.which("node"), find_chrome()
print(f"  среда: node = {NODE or 'няма'}; Chrome = {CHROME or 'няма'}")


def chrome_dump(html_text, tmp, extra=()):
    """
    Зарежда страницата в headless Chrome и връща DOM-а след изпълнението на скриптовете. `--dump-dom` на някои версии (напр. 154 на macOS) печата DOM-а, но процесът не излиза сам, затова се чете до
    затварящия </html> и процесът се убива (с watchdog при провал).
    08.10.2026 (вероятната причина за червения Tests run на ubuntu-latest, непотвърдена — логът изисква вход): двете извиквания в (д) делят един и същ --user-data-dir и първият Chrome се убива със SIGKILL; на Linux
    остава SingletonLock/деца на процеса и вторият Chrome се "закача" за стария сесия и излиза без изход (празен stdout). Затова: СОБСТВЕН профил на всяко извикване, убива се цялата група процеси, един повторен
    опит при празен изход, а при провал съобщението носи края на stderr на Chrome (виси в анотацията на Tests run-а).
    """
    import threading, signal, tempfile as _tf
    f = pathlib.Path(tmp) / "page.html"
    f.write_text(html_text, encoding="utf-8")
    last = ""
    for attempt in (1, 2):
        profile = pathlib.Path(_tf.mkdtemp(prefix="chrome_profile_", dir=tmp))
        err_path = pathlib.Path(tmp) / f"chrome_err_{attempt}.txt"
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars", f"--user-data-dir={profile}", "--virtual-time-budget=4000",
               '--host-resolver-rules=MAP * ~NOTFOUND', "--dump-dom", *extra, f.as_uri()]                       # без мрежа: всички имена → NOTFOUND
        with open(err_path, "w") as err:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8", start_new_session=True)

            def kill_group():
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
            watchdog = threading.Timer(60, kill_group)
            watchdog.start()
            lines = []
            try:
                for line in proc.stdout:
                    lines.append(line)
                    if "</html>" in line:
                        break
            finally:
                watchdog.cancel()
                kill_group()
                proc.wait(timeout=20)
        out = "".join(lines)
        if "<html" in out and "</html>" in out:
            return out
        last = f"опит {attempt}: изход {out[-300:]!r}; stderr на Chrome: {err_path.read_text(errors='replace')[-500:]!r}"
        print(f"  ⚠ chrome_dump: празен/непълен изход — {last}")
    raise AssertionError(last)


# ── 1. математиката: JS срещу Python ─────────────────────────────────────────
BAL, RISK, CAP = 80000, 0.5, 25
CASES = [  # (име, apply_regime, factor, entry, stop, adr, strategy, cap) — РЕАЛНИТЕ нива са първите
    ("EXPD (Watchlist, Defensive ×0.5)", True, 0.5, 194.59, 181.53, 2.01, "canslim", CAP),
    ("EXPD без режимен фактор", False, 0.5, 194.59, 181.53, 2.01, "canslim", CAP),
    ("EXEL (Action, таван 8%)", True, 0.5, 54.77, 50.39, 3.09, "canslim", CAP),
    ("DOCN (QM)", True, 1.0, 151.83, 140.91, 7.19, "kullamagi", CAP),
    ("CORT (QM)", True, 1.0, 120.51, 114.84, 4.71, "kullamagi", CAP),
    ("CRL (QM)", True, 1.0, 298.98, 289.48, 3.18, "kullamagi", CAP),
    ("СИНТЕТИЧНО: DOCN с таван 5% → свива се", True, 1.0, 151.83, 140.91, 7.19, "kullamagi", 5),
    ("СИНТЕТИЧНО: гап над 1 ADR (стоп 14.4% при ADR 7.19)", True, 1.0, 151.83, 130.0, 7.19, "kullamagi", CAP),
    ("СИНТЕТИЧНО: същият стоп при CANSLIM — без предупреждение за преследване", True, 0.5, 151.83, 130.0, 7.19, "canslim", CAP),
    ("СИНТЕТИЧНО: стоп = вход", True, 1.0, 100.0, 100.0, 3.0, "kullamagi", CAP),
    ("СИНТЕТИЧНО: стоп над входа", True, 1.0, 100.0, 105.0, 3.0, "kullamagi", CAP),
    ("СИНТЕТИЧНО: липсва стоп", True, 1.0, 100.0, None, 3.0, "canslim", CAP),
    ("СИНТЕТИЧНО: 0 акции (риск на акция $1000 при бюджет $200)", True, 0.5, 5000.0, 4000.0, None, "canslim", CAP),
    ("СИНТЕТИЧНО: риск 0 → настройки", True, 1.0, 100.0, 95.0, 3.0, "canslim", CAP),
]
payloads = [{"balance": BAL, "riskPct": (0 if "риск 0" in c[0] else RISK), "capPct": c[7], "applyRegime": c[1], "regimeFactor": c[2], "entry": c[3], "stop": c[4], "adrPct": c[5], "strategy": c[6]} for c in CASES]
payloads.append({"balance": "", "riskPct": RISK, "capPct": CAP, "applyRegime": True, "regimeFactor": 1, "entry": 100, "stop": 95, "adrPct": 3, "strategy": "canslim"})            # без баланс
payloads.append({"balance": "80 000", "riskPct": RISK, "capPct": CAP, "applyRegime": True, "regimeFactor": 1, "entry": 100, "stop": 95, "adrPct": 3, "strategy": "canslim"})     # невалиден текст → balance
payloads.append({"balance": "80000", "riskPct": "0,5", "capPct": "25", "applyRegime": True, "regimeFactor": "1", "entry": "100,00", "stop": "95", "adrPct": "3", "strategy": "canslim"})   # запетая като десетичен знак (мобилна клавиатура)


def js_results(pl):
    code = (f"const S = require({json.dumps(str(CORE))}); const P = {json.dumps(pl)}; "
            "console.log(JSON.stringify(P.map(p => S.sizePosition(p))));")
    if NODE:
        r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-400:]
        return json.loads(r.stdout), "node"
    with tempfile.TemporaryDirectory() as tmp:
        page = (f"<!doctype html><html><head><meta charset='utf-8'><script>{CORE.read_text(encoding='utf-8')}</script></head><body><pre id='out'></pre>"
                f"<script>document.getElementById('out').textContent = JSON.stringify({json.dumps(pl)}.map(p => MBSizing.sizePosition(p)));</script></body></html>")
        out = chrome_dump(page, tmp)
        m = re.search(r'<pre id="out">(.*?)</pre>', out, re.S)
        assert m, out[:300]
        import html as h
        return json.loads(h.unescape(m.group(1))), "headless Chrome"


def close(a, b):
    return abs(a - b) <= 1e-6 * max(1.0, abs(b))


if NODE or CHROME:
    print("── 1. математиката (sizing_core.js) срещу независимия Python-еталон ──")
    got, how = js_results(payloads)
    for c, p, g in zip(CASES, payloads, got):
        want = (ref(BAL, p["riskPct"], p["capPct"], p["applyRegime"], p["regimeFactor"], p["entry"], p["stop"], p["adrPct"], p["strategy"])
                if p["stop"] is not None else {"ok": False, "reason": "data"})
        assert g["ok"] == want["ok"] and (g["ok"] or g["reason"] == want["reason"]), (c[0], g, want)
        if want["ok"]:
            assert g["shares"] == want["shares"] and g["capped"] == want["capped"] and g["tooSmall"] == want["tooSmall"] and g["chase"] == want["chase"], (c[0], g, want)
            for k in ("value", "pctOfAccount", "lossAtStop", "effRiskPct", "factor", "realRiskPct", "gap10", "gap15", "stopPct"):
                assert close(g[k], want[k]), (c[0], k, g[k], want[k])
        r = (f"{g['shares']} акции, {money(g['value'])}, {pct(g['pctOfAccount'])}, загуба {money(g['lossAtStop'])}, гап {money(g['gap10'])}/{money(g['gap15'])}"
             + (" (ограничено от тавана)" if g.get("capped") else "") + (" ⚠ преследване" if g.get("chase") else "")) if g["ok"] else f"няма резултат ({g['reason']})"
        print(f"  ✓ {c[0]}: {r}")
    # без баланс / невалиден текст / запетая
    g_nobal, g_text, g_comma = got[-3], got[-2], got[-1]
    assert g_nobal == {"ok": False, "reason": "balance"} and g_text == {"ok": False, "reason": "balance"}
    assert g_comma["ok"] and g_comma["shares"] == math.floor(80000 * 0.5 / 100 / 5 + 1e-9) == 80
    print(f"  ✓ без баланс / баланс '80 000' (интервал) → 'въведи баланса'; '0,5' и '100,00' със запетая → 80 акции")
    # ръчна проверка на задачата (баланс 80000, риск 0.5%, таван 25%)
    g = got[0]
    assert (g["shares"], r0(g["value"]), r0(g["lossAtStop"]), r0(g["gap10"]), r0(g["gap15"])) == (15, 2919, 196, 292, 438)      # EXPD при ×0.5: 80000×0.25% = $200 / 13.06 = 15.3 → 15
    g = got[3]
    assert (g["shares"], r0(g["value"]), r0(g["lossAtStop"]), r0(g["gap10"]), r0(g["gap15"])) == (36, 5466, 393, 547, 820)       # DOCN: $400 / 10.92 = 36.6 → 36
    print(f"  ✓ ръчно: EXPD (×0.5) = 15 акции, $2,919 (3.6%), загуба при стоп $196, гап $292/$438; DOCN = 36 акции, $5,466 (6.8%), загуба $393, гап $547/$820  [мотор: {how}]")
else:
    print("SKIP: няма нито node, нито Chrome — математиката на JS НЕ е проверена в тази среда (в CI има node)")

# ── 2. цялата страница в headless Chrome ─────────────────────────────────────
class Cards(HTMLParser):
    """Събира за всяка .lv карта атрибутите и видимия текст на .lv-size (и data-state)."""
    def __init__(self):
        super().__init__()
        self.cards, self._cur, self._depth, self._size_depth, self._in_size = [], None, 0, 0, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "div" and "lv" in cls:
            self._cur = {"attrs": a, "size": [], "state": None, "warn": []}
            self.cards.append(self._cur)
            self._depth = 1
            return
        if self._cur is None:
            return
        if tag == "div":
            self._depth += 1
            if "lv-size" in cls:
                self._in_size, self._size_depth, self._cur["state"] = True, self._depth, a.get("data-state")

    def handle_endtag(self, tag):
        if self._cur is None or tag != "div":
            return
        if self._in_size and self._depth == self._size_depth:
            self._in_size = False
        self._depth -= 1
        if self._depth == 0:
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None and self._in_size:
            self._cur["size"].append(data)


def parse(out):
    p = Cards()
    p.feed(out)
    for c in p.cards:
        c["text"] = " ".join(" ".join(c["size"]).split())
    return {(float(c["attrs"]["data-entry"]), float(c["attrs"]["data-stop"])): c for c in p.cards}


def expect_text(res, risk_txt, label=None):
    if not res["ok"]:
        return {"data": "няма достатъчно данни", "balance": "въведи баланса в настройките, за да видиш размера на позицията"}[res["reason"]]
    parts = [risk_txt + " от сметката"]
    parts.append("0 акции — рисковият бюджет не стига за 1 акция при този стоп" if res["tooSmall"] else f"{res['shares']} акции · {money(res['value'])} ({pct(res['pctOfAccount'])} от сметката)")
    if res["capped"]:
        parts.append(f"ограничено от тавана ({pct(res['capPct'])} от сметката) — реален риск при стопа {money(res['lossAtStop'])} ({pct(res['realRiskPct'], 2)} от сметката)")
    parts.append(f"загуба при стоп: {money(res['lossAtStop'])}")
    parts.append(f"при гап −10%: {money(res['gap10'])} · при гап −15%: {money(res['gap15'])}")
    if res["chase"]:
        parts.append("⚠ акцията е избягала над 1 ADR — входът е преследване")
    return " ".join(" ".join(parts).split())


def build_page():
    """РЕАЛЕН бриф от 05.10 + нивата: EXEL (Action), EXPD (Watchlist), DOCN/CORT/CRL (QM), SYNA (EP) — виж tests/helpers_page.py. → (html, {тикър: levels})"""
    from tests import helpers_page
    from src import render
    b, levels = helpers_page.build_brief()
    return render.render_dashboard(b), levels


if CHROME:
    print()
    print("── 2. страницата в headless Chrome (РЕАЛЕН бриф от 05.10 + нива на EXEL, EXPD, DOCN, CORT, CRL, SYNA) ──")
    html, LV = build_page()
    html = re.sub(r"<link[^>]+fonts\.(googleapis|gstatic)[^>]*>", "", html)               # без външни заявки (шрифтовете не са нужни за логиката)
    assert html.count('class="lv"') == 6 and "mb-settings-btn" in html and "MBSizing" in html and "MBSizingUI" in html
    KEYS = {"EXEL": "EXEL", "EXPD": "EXPD", "DOCN": "DOCN", "CORT": "CORT", "CRL": "CRL"}
    SET = {"balance": "80000", "risk": "0.5", "cap": "25", "regime": True}

    def with_settings(settings):
        inj = f'<script>try{{localStorage.setItem("mb_settings_v1", {json.dumps(json.dumps(settings))});}}catch(e){{}}</script>'
        return html.replace("<body>", "<body>" + inj, 1)

    def late(script, h=None):
        h = h or html
        return h.replace("</body>", f"<script>{script}</script></body>", 1)

    def check(cards, settings, apply_regime=True, cap=None, only=None):
        for name, lv in LV.items():
            if only and name not in only:
                continue
            c = cards[(lv["entry"], lv["stop"])]
            assert c["attrs"]["data-strategy"] == lv["strategy"] and float(c["attrs"]["data-factor"]) == lv["regime_factor"]
            res = ref(float(settings["balance"] or 0), float(settings["risk"]), float(cap or settings["cap"]), apply_regime, lv["regime_factor"], lv["entry"], lv["stop"], lv["adr_pct"], lv["strategy"])
            res = {**res, "capPct": float(cap or settings["cap"])} if res["ok"] else res
            risk_txt = f"риск {pct(float(settings['risk']), 2)}"
            if res["ok"] and res["factor"] != 1:
                risk_txt += f" × {res['factor']:g} защитен режим = {pct(res['effRiskPct'], 2)}"
            elif res["ok"] and apply_regime and lv.get("regime_note"):
                risk_txt += f" ({lv['regime_note']})"
            want = expect_text(res, risk_txt)
            assert c["text"] == want, (name, c["text"], want)
            yield name, c["text"]

    with tempfile.TemporaryDirectory() as tmp:
        # (а) без настройки: страницата работи, всяка карта казва да въведеш баланса
        cards = parse(chrome_dump(html, tmp))
        assert len(cards) == 6 and all(c["state"] == "balance" and c["text"] == "въведи баланса в настройките, за да видиш размера на позицията" for c in cards.values())
        print("  ✓ без настройки: и шестте карти показват 'въведи баланса в настройките, за да видиш размера на позицията' (без брой акции)")

    with tempfile.TemporaryDirectory() as tmp:
        # (б) настройки от задачата: 80000 / 0.5% / 25%, режимният фактор включен
        out = parse(chrome_dump(with_settings(SET), tmp))
        got = dict(check(out, SET))
        for n in ("EXEL", "EXPD"):
            assert "риск 0.5% × 0.5 защитен режим = 0.25% от сметката" in got[n], got[n]
        for n in ("DOCN", "CORT", "CRL", "SYNA"):
            assert "риск 0.5% (отделна стратегия — без режимен фактор) от сметката" in got[n], got[n]
        print("  ✓ 80000 / 0.5% / 25% (фактор вкл.): Action и Watchlist — 'риск 0.5% × 0.5 защитен режим = 0.25%'; QM и EP — 'отделна стратегия — без режимен фактор'; всички числа = еталона")
        for n in ("EXEL", "EXPD", "DOCN"):
            print(f"      {n}: {got[n]}")

    with tempfile.TemporaryDirectory() as tmp:
        # (в) режимният фактор изключен
        s2 = {**SET, "regime": False}
        out = parse(chrome_dump(with_settings(s2), tmp))
        got = dict(check(out, s2, apply_regime=False))
        assert "× 0.5" not in got["EXPD"] and got["EXPD"].startswith("риск 0.5% от сметката 30 акции")
        print("  ✓ СИНТЕТИЧНО (отметката изключена): EXPD — 'риск 0.5% от сметката', 30 акции (без ×0.5)")

    with tempfile.TemporaryDirectory() as tmp:
        # (г) таван 5% → свива се
        s3 = {**SET, "cap": "5"}
        out = parse(chrome_dump(with_settings(s3), tmp))
        got = dict(check(out, s3, cap=5))
        assert "ограничено от тавана (5% от сметката) — реален риск при стопа $284 (0.35% от сметката)" in got["DOCN"], got["DOCN"]
        print("  ✓ СИНТЕТИЧНО (таван 5%): DOCN — 'ограничено от тавана (5% от сметката) — реален риск при стопа $284 (0.35% от сметката)'")

    with tempfile.TemporaryDirectory() as tmp:
        # (д) localStorage е забранен: без изключение; настройките от полетата важат в страницата
        block = 'try{Object.defineProperty(window,"localStorage",{get:function(){throw new Error("blocked")}});}catch(e){}'
        pre = html.replace("<body>", f"<body><script>{block}</script>", 1)
        typed = ('var b=document.getElementById("mb-balance");b.value="80000";b.dispatchEvent(new Event("input",{bubbles:true}));'
                 'document.title=document.querySelectorAll(".lv-size[data-state=ok]").length;')
        o1 = chrome_dump(pre, tmp)
        assert all(c["state"] == "balance" for c in parse(o1).values())
        out = chrome_dump(late(typed, pre), tmp)
        assert "<title>6</title>" in out
        cards = parse(out)
        assert all(c["state"] == "ok" for c in cards.values())
        assert not re.search(r'id="mb-persist-note"\s+hidden', out)                         # бележката "localStorage не е достъпен" е видима
        print("  ✓ СИНТЕТИЧНО (localStorage хвърля изключение): страницата зарежда, картите казват 'въведи баланса'; въведен баланс в полето работи до затваряне; бележката за непостоянните настройки е видима")

    with tempfile.TemporaryDirectory() as tmp:
        # (е) "коригирай": само за тази карта, не се записва; chase предупреждението само при Kullamägi
        docn, cort = LV["DOCN"], LV["CORT"]
        script = ("var cards=document.querySelectorAll('.lv');"
                  "function pick(e,s){for(var i=0;i<cards.length;i++){if(parseFloat(cards[i].getAttribute('data-entry'))===e&&parseFloat(cards[i].getAttribute('data-stop'))===s)return cards[i];}}"
                  "function setv(f,v){f.value=v;f.dispatchEvent(new Event('input',{bubbles:true}));}"
                  f"var c1=pick({docn['entry']},{docn['stop']});c1.querySelector('.lv-adjust-btn').click();"
                  "setv(c1.querySelector('.lv-in-entry'),'151.83');setv(c1.querySelector('.lv-in-stop'),'130');"                                             # DOCN: стоп 14.4% при ADR 7.19 → преследване
                  f"var c2=pick({cort['entry']},{cort['stop']});c2.querySelector('.lv-adjust-btn').click();setv(c2.querySelector('.lv-in-stop'),'125');"       # CORT: стоп над входа
                  "var e3=pick(194.59,181.53);e3.querySelector('.lv-adjust-btn').click();setv(e3.querySelector('.lv-in-stop'),'150');"                         # EXPD (CANSLIM): широк стоп
                  "document.title=localStorage.getItem('mb_settings_v1');")
        out = chrome_dump(late(script, with_settings(SET)), tmp)
        cards = parse(out)
        a = cards[(docn["entry"], docn["stop"])]
        want = expect_text({**ref(80000, 0.5, 25, True, 1.0, 151.83, 130.0, docn["adr_pct"], "kullamagi"), "capPct": 25}, "риск 0.5% (отделна стратегия — без режимен фактор)")
        assert a["text"] == want and "⚠ акцията е избягала над 1 ADR — входът е преследване" in a["text"], (a["text"], want)
        assert cards[(cort["entry"], cort["stop"])]["text"] == "няма достатъчно данни"
        e3 = cards[(194.59, 181.53)]["text"]
        assert "⚠" not in e3 and "акции" in e3                                              # CANSLIM: без предупреждение за преследване
        assert cards[(LV["CRL"]["entry"], LV["CRL"]["stop"])]["text"].startswith("риск 0.5% (отделна стратегия")      # другите карти не са пипнати
        title = re.search(r"<title>(.*?)</title>", out, re.S).group(1)
        assert json.loads(title.replace("&quot;", '"')) == {"balance": "80000", "risk": "0.5", "cap": "25", "regime": True}          # "коригирай" не записва нищо в localStorage
        print("  ✓ СИНТЕТИЧНО 'коригирай': DOCN с вход 151.83 / стоп 130 → преизчислено + '⚠ акцията е избягала над 1 ADR'; CORT със стоп над входа → 'няма достатъчно данни' (без акции);")
        print("    EXPD със стоп 150 (CANSLIM) — без предупреждение за преследване; другите карти не се променят; localStorage остава с оригиналните 4 настройки")
else:
    print("SKIP: няма Chrome — DOM проверката на страницата (настройки, localStorage, 'коригирай') НЕ е изпълнена в тази среда")

print("\n✅ test_sizing_js: изпълнените проверки минаха" + ("" if (NODE or CHROME) and CHROME else " (има пропуснати — виж SKIP по-горе)"))
