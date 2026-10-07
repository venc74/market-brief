"""
Стоп и размер (07.10.2026) · ЗАЩИТА: брифът е ПУБЛИЧЕН — никъде в кода, в workflow-а, в публикуваните данни (brief JSON), в страницата и в имейла няма размер на сметка, брой акции, риск в долари или лични
числа. Размерът се смята САМО в браузъра на читателя (templates/sizing_core.js) от настройки, които стоят само в localStorage на устройството му. Тестът пази това да не се върне:
  1. кодът/конфигурацията/workflow-ите/README не съдържат PORTFOLIO_SIZE, RISK_PER_TRADE_PCT, QM_RISK_FACTOR, QM_MAX_POSITION_PCT (config няма такива атрибути);
  2. картите на Action, Watchlist, QM breakout и EP (в brief JSON) нямат shares / total_investment / pct_of_portfolio / max_risk_usd / risk_usd / shares_at_max_stop / capped_by_position_limit;
  3. отрендерираната страница (без <script>) и имейлът нямат "брой акции", "инвестиция", "акции при … риск", "N акции ($…)" и нито едно число от сметка;
  4. страницата не носи предварително попълнен баланс; JS файловете не пращат нищо никъде (без fetch/XMLHttpRequest/sendBeacon/WebSocket/cookie) и ползват само localStorage, в try/catch.
РЕАЛНО: страницата и имейлът са от РЕАЛНИЯ бриф от 05.10 + нива на EXEL, EXPD, DOCN, CORT, CRL, SYNA (tests/helpers_page.py). Исторически публикуваните docs/data/*.json от юни–октомври съдържат
старите полета (публикувани преди 07.10, с номинални $100k) — те не се пренаписват. Пускане: python test_no_account_numbers.py
"""
import sys, re, json, pathlib, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from tests import helpers_page
from src import render

BANNED_NAMES = ("PORTFOLIO_SIZE", "RISK_PER_TRADE_PCT", "QM_RISK_FACTOR", "QM_MAX_POSITION_PCT")

print("── 1. код, конфигурация, workflow-и, README ──")
assert not any(hasattr(config, n) for n in BANNED_NAMES), [n for n in BANNED_NAMES if hasattr(config, n)]
scanned = []
for pat in ("config.py", "src/*.py", "templates/*", ".github/workflows/*.yml", "README.md", "tools/*.py"):
    for p in sorted(ROOT.glob(pat)):
        text = p.read_text(encoding="utf-8")
        scanned.append(p.name)
        hit = [n for n in BANNED_NAMES if n in text]
        assert not hit, f"{p.relative_to(ROOT)} съдържа {hit}"
wf = (ROOT / ".github" / "workflows" / "daily_brief.yml").read_text(encoding="utf-8")
assert "vars.PORTFOLIO" not in wf and "vars.RISK" not in wf
print(f"  ✓ нито една от {', '.join(BANNED_NAMES)} в {len(scanned)} файла (config, src, templates, workflow-и, README, tools); config няма такива атрибути; daily_brief.yml не подава променливи за сметка")

print()
print("── 2. картите в brief JSON ──")
brief, LV = helpers_page.build_brief()
FORBIDDEN_KEYS = {"shares", "total_investment", "pct_of_portfolio", "max_risk_usd", "risk_usd", "shares_at_max_stop", "capped_by_position_limit"}


def keys_in(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield path + "/" + str(k), k
            yield from keys_in(v, path + "/" + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from keys_in(v, f"{path}[{i}]")


for section in ("action", "watchlist", "qm_breakout", "qm_ep"):
    bad = [p for p, k in keys_in(brief[section]) if k in FORBIDDEN_KEYS]
    assert not bad, (section, bad[:5])
blob = json.dumps({s: brief[s] for s in ("action", "watchlist", "qm_breakout", "qm_ep")}, ensure_ascii=False)
assert "PORTFOLIO" not in blob
print(f"  ✓ Action ({len(brief['action'])}), Watchlist ({len(brief['watchlist'])}), QM breakout ({len(brief['qm_breakout'])}), EP ({len(brief['qm_ep']['rows'])}) — без {', '.join(sorted(FORBIDDEN_KEYS))}; остава публичният sizing_factor")
assert brief["action"][0]["plan"]["sizing_factor"] == 0.5 and brief["action"][0]["levels"]["regime_factor"] == 0.5
assert set(LV) == {"EXEL", "EXPD", "DOCN", "CORT", "CRL", "SYNA"}

print()
print("── 3. страницата и имейлът ──")
page = render.render_dashboard(brief)
mail = render.render_email(brief)
page_no_js = re.sub(r"<script\b.*?</script>", " ", page, flags=re.S)
txt = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", page_no_js)).split())
mtxt = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", mail)).split())
for nm, t in (("страницата", txt), ("имейлът", mtxt)):
    for phrase in ("Брой акции", "брой акции", "Инвестиция", "акции при", "риск $", "риск ${"):
        assert phrase not in t, (nm, phrase)
    assert not re.search(r"\d+ акции\s*\(\$", t) and not re.search(r"\d[\d,]* акции\b", t), (nm, re.findall(r".{20}\d[\d,]* акции\b.{10}", t)[:3])
print("  ✓ страницата (без <script>) и имейлът: без 'брой акции', 'инвестиция', 'акции при … риск', 'N акции ($…)'; на страницата остават само нивата (вход, стоп, стоп %, ADR, предупреждения)")
assert 'id="mb-balance"' in page and not re.search(r'id="mb-balance"[^>]*\bvalue=', page) and not re.search(r'id="mb-(risk|cap)"[^>]*\bvalue="\d', page)
assert "въведи баланса в настройките, за да видиш размера на позицията" in txt
print("  ✓ полетата за баланс/риск/таван са празни в HTML-а (стойности се четат само от localStorage в браузъра)")
assert "Вход ≈" in mtxt and "Stop $50.39" in mtxt and "акции" not in mtxt.split("Action")[1].split("Watchlist")[0]
print("  ✓ имейлът: само вход, стоп, стоп % и предупрежденията (EXEL: 'Вход ≈ $54.77 · Stop $50.39 (−8.0%)')")

print()
print("── 4. JavaScript: нищо не напуска устройството ──")
for name in ("sizing_core.js", "sizing_ui.js"):
    js = (ROOT / "templates" / name).read_text(encoding="utf-8")
    for token in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "document.cookie", "EventSource", "new Image", "navigator."):
        assert token not in js, (name, token)
ui = (ROOT / "templates" / "sizing_ui.js").read_text(encoding="utf-8")
assert re.findall(r"localStorage\.(\w+)\(", ui) == ["getItem", "setItem"] and ui.count("try {") >= 2                  # само getItem и setItem, и двата в try/catch
assert re.search(r"try \{\s*var raw = window\.localStorage\.getItem", ui) and re.search(r"try \{ window\.localStorage\.setItem", ui)
print("  ✓ sizing_core.js и sizing_ui.js: без fetch/XMLHttpRequest/sendBeacon/WebSocket/cookie; localStorage — само getItem/setItem, и двете в try/catch")
print("\n✅ test_no_account_numbers: всичко мина")
