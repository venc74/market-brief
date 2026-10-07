"""
Qullamaggie · езикова хигиена (07.10.2026): в QM кода, шаблона и имейла няма (1) думи, смесени от кирилски и латински букви ("момentum", "orязана"), и (2) латински съкращения, написани с
кирилски близнаци ("АН" вместо "AH" — А и Н са кирилски; "ЕР" вместо "EP"). Двете се виждат еднакво, но са различни символи и чупят търсене/копиране. Проверката е по КОДОВИ ТОЧКИ.

Обхват: src/qm_breakout.py, src/qm_ep.py, test_qm_*.py, секциите qm и qm-ep в templates/dashboard.html.j2, render._qm_email_block, блокът "Qullamaggie" в config.py, и ВИДИМИЯТ текст на
отрендерираните секции (dashboard + имейл). Същото за "AH" в EP таблицата: заглавието и редовете трябва да са с латинско A и H.

РЕАЛНО: отрендерираният текст е от реалните карти DOCN/CORT/CRL към 02.10.2026, реалния EP на SYNA (01.10) и реалния бриф от 05.10 (като в test_qm_render.py). СИНТЕТИЧНО: само
резюмето на AI в EP реда ("ON Semi предлага…") и самите тестови низове за проверката на детектора (по-долу, маркирани).
Пускане: python test_qm_language.py
"""
import sys, io, re, inspect, pathlib, contextlib, runpy, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

CYR = re.compile(r"[\u0400-\u04FF]")
LAT = re.compile(r"[A-Za-z]")
TOKEN = re.compile(r"[A-Za-z\u0400-\u04FF]+")
LOOK = {"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X"}      # кирилски букви с латински близнак (главни)
ABBR = {"AH", "EP", "MA", "EMA", "SMA", "ATM", "CET", "ET", "OHLC"}                                                    # латински съкращения, които QM текстът ползва / би могъл да ползва


def problems(text):
    """[(токен, вид)] — смесени думи и кирилски 'близнаци' на латинско съкращение. \\n / \\t в кода не са част от думата."""
    text = re.sub(r"\\[nrt]", " ", text)
    out = []
    for m in TOKEN.finditer(text):
        t = m.group()
        if CYR.search(t) and LAT.search(t):
            out.append((t, "смесена дума"))
        elif len(t) >= 2 and all(c in LOOK for c in t) and "".join(LOOK[c] for c in t) in ABBR:
            out.append((t, f"кирилски близнаци на {''.join(LOOK[c] for c in t)}"))
    return out


# ── детекторът сам: СИНТЕТИЧНИ низове (кирилицата е вписана с кодови точки, за да не се слива с латиницата) ──
CYR_AH = "\u0410\u041d"                       # кирилски А + Н
CYR_EP = "\u0415\u0420"                       # кирилски Е + Р
assert problems(f"{CYR_AH} гап") == [(CYR_AH, "кирилски близнаци на AH")]
assert problems(f"({CYR_EP})") == [(CYR_EP, "кирилски близнаци на EP")]
assert problems("AH гап, EP, ADR") == [] and problems("НЕ е сигнал, САМО наблюдение, от НА") == []                         # истински български думи не се хващат
assert problems("\u043c\u043e\u043centum") == [("\u043c\u043e\u043centum", "смесена дума")]                                  # кирилско "мом" + латинско "entum" (реалният случай "момentum")
assert problems("Kullam\u00e4gi QM\u2713") == []                                                                          # ä и ✓ не са кирилица
assert problems("\\n\u041a\u0410\u0422\u0410\u041b\u0418\u0417\u0410\u0422\u041e\u0420\u0418") == []                      # '\n' пред кирилска дума не я слепва с латинска буква
print("  ✓ детекторът хваща кирилско 'АН'/'ЕР' и смесени думи, а истинските български думи и 'Kullamägi' не ги хваща")

# ── 1. кодът ──
files = {f: (ROOT / f).read_text(encoding="utf-8") for f in ("src/qm_breakout.py", "src/qm_ep.py", "src/trade_levels.py", "templates/sizing_core.js", "templates/sizing_ui.js")}      # + 07.10 (стоп и размер)
for p in sorted(ROOT.glob("test_qm_*.py")):
    if p.name != pathlib.Path(__file__).name:                    # този файл съдържа проверените низове
        files[p.name] = p.read_text(encoding="utf-8")
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
i0 = tpl.index('<section id="qm">'); i1 = tpl.index("</section>", tpl.index('<section id="qm-ep">')) + len("</section>")
files["templates/dashboard.html.j2 [qm + qm-ep]"] = tpl[i0:i1]
m0 = tpl.index("{% macro levels_block"); files["templates/dashboard.html.j2 [levels_block]"] = tpl[m0:tpl.index("{% endmacro %}", m0)]                  # стоп и размер (07.10)
s0 = tpl.index('<div id="mb-settings"'); files["templates/dashboard.html.j2 [настройки]"] = tpl[s0:tpl.index("</header>", s0) if "</header>" in tpl[s0:] else s0 + 1800]
from src import render
files["render._qm_email_block"] = inspect.getsource(render._qm_email_block)
cfg = (ROOT / "config.py").read_text(encoding="utf-8")
c0 = cfg.index("Qullamaggie"); c1 = cfg.index("QM_EP_LOG_FILE")
files["config.py [Qullamaggie блок]"] = cfg[cfg.rfind("\n", 0, c0): cfg.index("\n", c1)]
bad = {f: problems(t) for f, t in files.items()}
bad = {f: v for f, v in bad.items() if v}
assert not bad, bad
print(f"  ✓ без смесени думи и без кирилски 'близнаци' в {len(files)} QM обекта: {', '.join(sorted(files))}")

# ── 2. видимият текст ──
with contextlib.redirect_stdout(io.StringIO()):
    ns = runpy.run_path(str(ROOT / "test_qm_render.py"))
render_, brief_with, EP_Y = ns["render"], ns["brief_with"], ns["EP_Y"]
b = brief_with(ep_out=EP_Y)
raw = render_.render_dashboard(b)
sec = raw[raw.index('<section id="qm">'): raw.index("</section>", raw.index('<section id="qm-ep">'))]
txt_dash = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", sec))).strip()
txt_mail = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render_._qm_email_block(b)))).strip()
for nm, t in (("dashboard", txt_dash), ("имейл", txt_mail)):
    assert not problems(t), (nm, problems(t))
    assert CYR_AH not in t and CYR_EP not in t, nm
    assert re.search(r"(?<![A-Za-z])AH(?![A-Za-z])", t), (nm, "няма латинско AH")
assert re.search(r"<th class=\"n\">AH гап</th>", sec) and "SYNA AH +15.0%" in txt_dash and "Вчера, AH срещу отваряне" in txt_mail
print("  ✓ видимият текст: латинско AH в заглавието на таблицата и в реда на SYNA (dashboard: 'SYNA AH +15.0%'; имейл: 'Вчера, AH срещу отваряне'); без смесени думи")
print("\n✅ test_qm_language: всичко мина")
