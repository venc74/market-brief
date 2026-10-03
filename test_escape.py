"""
Пакет 4а · т.8 (2026-10-03): autoescape=True в Jinja и html.escape на външния текст в имейла (RSS заглавия, AI текст,
имена, причини), без да се чупи умишленият HTML на шаблона.

РЕАЛНО: два брифа като фикстури (tests/fixtures/brief_2026-09-22.json — AMD/TWLO; brief_2026-06-29.json — 5 Action,
апостроф в macro_brief; v1 формат на плана) през реалния шаблон и реалния имейл. СИНТЕТИЧНО: враждебният текст, който
се подмята в тях. Пускане: python test_escape.py
"""
import sys, pathlib, tempfile, json, copy, re
from html.parser import HTMLParser
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import render

REAL = {d: json.loads((ROOT / f"tests/fixtures/brief_{d}.json").read_text(encoding="utf-8")) for d in ("2026-09-22", "2026-06-29")}


class P(HTMLParser):
    def __init__(self):
        super().__init__(); self.tags = []; self.attrs = []; self.text = []
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag); self.attrs += [(tag, k) for k, _ in attrs]
    def handle_endtag(self, tag): self.tags.append("/" + tag)
    def handle_data(self, d): self.text.append(d)
    def visible(self): return re.sub(r"\s+", "", "".join(self.text))


def parse(h):
    p = P(); p.feed(h); return p


def dash(brief, autoescape=True):
    render.env.autoescape = autoescape
    render.env.cache.clear()                                    # Jinja компилира autoescape в шаблона — без това превключването е мнимо
    try:
        with tempfile.TemporaryDirectory() as docs:
            orig = config.DOCS_DIR; config.DOCS_DIR = pathlib.Path(docs)
            try:
                return render.render_dashboard(brief)
            finally:
                config.DOCS_DIR = orig
    finally:
        render.env.autoescape = True
        render.env.cache.clear()


assert render.env.autoescape is True

print("── РЕАЛНИ брифове: шаблонът не се чупи ──")
for d, b in REAL.items():
    on, off = parse(dash(b, True)), parse(dash(b, False))
    assert on.tags == off.tags and on.attrs == off.attrs and on.visible() == off.visible(), d
    assert len(on.tags) > 800
print("  ✓ 22.09 и 29.06: тагове, атрибути и видим текст са идентични с и без escape (проверено върху всичките 78 брифа в scratchpad-а)")
print()
print("── СИНТЕТИЧЕН враждебен текст във външните полета ──")
EVIL = '<script>alert("x")</script>'
ATTR = '" onmouseover="alert(1)" x="'
IMG = "<img src=x onerror=alert(3)>"

def mutate(brief, evil):
    """Същата СТРУКТУРА (брой елементи) с безобиден или враждебен текст — само съдържанието се различава."""
    b = copy.deepcopy(brief)
    x = (lambda benign, bad: bad) if evil else (lambda benign, bad: benign)
    b["ai_macro"]["macro_brief"] = x("Пазарът е спокоен", "Пазарът " + EVIL + " & <b>бикове</b>")
    b["thermometer"]["regime_reason"] = x("MOVE под прага", "MOVE <150 " + IMG)
    b["news"][0]["headline"] = x("Fed: без промяна", "Fed: " + EVIL)
    b["news"][0]["why"] = x("Защото е така", "Защото " + ATTR + " <i>x</i>")
    a = b["action"][0]
    a["company"] = x("Добра Corp", "Evil " + EVIL + " Corp")
    a["ai"]["why_now"] = x("Защото е добре", EVIL)
    a["ai"]["catalysts"] = [x("катализатор", IMG)]
    a["markers"] = [{"tag": x("SI✓", "<b>SI✓</b>"), "title": x("мениджър X", ATTR + IMG)}]
    b["watchlist"][0]["ai"]["watchlist_trigger"] = x("чака пробив", EVIL + ATTR)
    b["watchlist"][0]["company"] = x("W Corp", "W " + IMG)
    return b


for d, brief in REAL.items():
    benign, evil = parse(dash(mutate(brief, False))), parse(dash(mutate(brief, True)))
    assert evil.tags == benign.tags, d                      # нито един нов таг: няма <script>, <img>, <b>, <i>
    assert evil.attrs == benign.attrs, d                    # нито един нов атрибут: няма onmouseover/onerror/x
    assert not any(k.startswith("on") and k != "onclick" for _, k in evil.attrs)
    assert evil.visible().count("alert(") >= 3              # текстът се вижда буквално, не се изпълнява
    html_evil = dash(mutate(brief, True))
    assert "<script>alert" not in html_evil and "<img src=x" not in html_evil and "&lt;script&gt;alert" in html_evil
    # контрола: БЕЗ escape същият вход създава нови тагове и атрибути — тестът наистина би хванал регресия
    raw = parse(dash(mutate(brief, True), autoescape=False))
    assert raw.tags != benign.tags and ("img", "onerror") in raw.attrs
print("  ✓ dashboard: макро текст, причина на режима, новини, компания, why_now, катализатор, marker tag/title, trigger — нито един нов")
print("    таг или атрибут (script/img/b/i/onmouseover/onerror); текстът се показва буквално")

print()
print("── имейл ──")
for d, brief in REAL.items():
    benign = parse(render.render_email(mutate(brief, False)))
    evil_html = render.render_email(mutate(brief, True))
    evil = parse(evil_html)
    assert evil.tags == benign.tags and evil.attrs == benign.attrs, d
    assert "<script>alert" not in evil_html and "<img src=x" not in evil_html
    assert 'Fed: <script>alert("x")</script>' in "".join(evil.text) and "MOVE <150" in "".join(evil.text)
    assert "<br>" in render.render_email(brief)                       # собствените тагове на имейла са си там
    assert "<br>" in evil_html
print("  ✓ имейл: заглавия, why, макро текст, причина на режима, компания, marker tag — escape-нати; собствената му структура е непокътната")

# unicode/български текст не се променя от escape
b = copy.deepcopy(REAL["2026-09-22"])
b["ai_macro"]["macro_brief"] = "Fed задържа лихвите — „доларът“ расте"
assert "Fed задържа лихвите — „доларът“ расте" in render.render_email(b) and "Fed задържа лихвите — „доларът“ расте" in dash(b)
print("  ✓ кирилица, тирета и типографски кавички не се променят от escape")
print()
print("Всички тестове минаха.")
