"""
03.11.2026 · разходката, т. 20: архивът — бутони „← предишен ден · следващ →“ в рамката на историческия бриф. Вървят само по наличните дни (docs/data/index.json — без уикенди и празници);
в краищата на архива бутонът е изключен; ден без бриф — без бутоните.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — страницата. СИНТЕТИЧНО (означено): списъкът с дати (подменен fetch, с реалните дни 30.10 петък · 02.11 понеделник · 03.11 вторник), кликовете.
Поведението се проверява в headless Chrome; без Chrome — само наличието в страницата (ред в лога).
Пускане: python test_archive_nav.py
"""
import sys, json, os, pathlib, shutil, signal, subprocess, tempfile, threading, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_archnav_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(B19, publish=False)

print("── 1. в страницата ──")
assert '<button id="hist-prev" type="button">← предишен ден</button>' in page and '<button id="hist-next" type="button">следващ →</button>' in page
assert page.index('id="hist-nav"') < page.index('id="history-frame"') and '<div id="hist-nav" class="hist-nav" hidden>' in page
print("  ✓ бутоните са над рамката и скрити, докато няма отворен бриф")


def find_chrome():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if os.path.exists(mac) else None


def chrome_dump(html, tmp):
    """Страницата в headless Chrome → DOM след скриптовете (както в test_sizing_js: --dump-dom може да не излезе сам, затова — до </html>, с watchdog)."""
    f = pathlib.Path(tmp) / "page.html"
    f.write_text(html, encoding="utf-8")
    prof = tempfile.mkdtemp(prefix="chrome_profile_", dir=tmp)
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", f"--user-data-dir={prof}", "--virtual-time-budget=4000", "--host-resolver-rules=MAP * ~NOTFOUND", "--dump-dom", f.as_uri()]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", start_new_session=True)

    def kill():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
    w = threading.Timer(60, kill); w.start()
    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
            if "</html>" in line:
                break
    finally:
        w.cancel(); kill(); proc.wait(timeout=20)
    return "".join(lines)


CHROME = find_chrome()
print()
print("── 2. поведението (headless Chrome) ──")
if not CHROME:
    print("  (няма Chrome — само проверката в страницата)")
else:
    stub = """<script>window.fetch = function () { return Promise.resolve({ok: true, json: function () { return Promise.resolve(["2026-11-03", "2026-10-30", "2026-11-02"]); }}); };</script>"""
    drive = """<script>
    window.addEventListener("load", function () { setTimeout(function () {
      var $ = function (id) { return document.getElementById(id); }, log = [];
      var snap = function () { log.push([$("hist-date").value, $("hist-nav").hidden, $("hist-prev").disabled, $("hist-next").disabled, $("hist-cur").textContent, ($("history-frame").getAttribute("src") || "")]); };
      snap();
      $("hist-open").click(); snap();          // последният ден: следващ — изключен
      $("hist-prev").click(); snap();          // 03.11 → 02.11
      $("hist-prev").click(); snap();          // 02.11 → 30.10 (през уикенда)
      $("hist-prev").click(); snap();          // началото: остава
      $("hist-next").click(); snap();          // 30.10 → 02.11
      $("hist-date").value = "2026-11-01"; $("hist-open").click(); snap();   // неделя: няма бриф
      var out = document.createElement("pre"); out.id = "t-out"; out.textContent = JSON.stringify(log); document.body.appendChild(out);
    }, 50); });
    </script>"""
    html = page.replace("<head>", "<head>" + stub, 1).replace("</body>", drive + "</body>", 1)
    with tempfile.TemporaryDirectory(prefix="mb_archnav_c_") as tmp:
        dom = chrome_dump(html, tmp)
    m = re.search(r'<pre id="t-out">(.*?)</pre>', dom, re.S)
    assert m, dom[-300:]
    log = json.loads(m.group(1).replace("&quot;", '"'))
    assert log[0][:2] == ["2026-11-03", True]                                                        # преди да се отвори — скрити
    assert log[1] == ["2026-11-03", False, False, True, "03.11.2026", "archive/2026-11-03.html"]     # последният: „следващ“ изключен
    assert log[2] == ["2026-11-02", False, False, False, "02.11.2026", "archive/2026-11-02.html"]
    assert log[3] == ["2026-10-30", False, True, False, "30.10.2026", "archive/2026-10-30.html"]     # през уикенда; първият: „предишен“ изключен
    assert log[4][0] == "2026-10-30" and log[5][0] == "2026-11-02" and log[5][5] == "archive/2026-11-02.html"
    assert log[6][0] == "2026-11-01" and log[6][1] is True                                           # неделя: няма бриф — без бутоните
    print("  ✓ 03.11 → 02.11 → 30.10 (през уикенда); в краищата бутонът е изключен; неделя — „няма бриф“, без бутоните")
print("\n✅ test_archive_nav: всичко мина")
