"""
Пакет 4а · т.6 (2026-10-03): етикетът на базата е честното "база X% дълбочина" — кодът мери само дълбочина, не
форма; AI промптът изрично забранява "cup with handle"/"flat base"/"VCP".
РЕАЛНО: барове от tests/fixtures (AMD, TWLO, LNTH, EXEL; Yahoo, свалени на 02.10.2026) през screener._evaluate_technicals.
Картата е СИНТЕТИЧНА (реалният шаблон). Пускане: python test_base_label.py
"""
import sys, pathlib, re, json
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import screener, ai_brief
from test_dashboard_cleanup import render_brief, action_card

F = lambda s: pd.read_csv(ROOT / "tests/fixtures" / f"ohlc_{s}.csv", index_col=0, parse_dates=True)
SPY = F("SPY")["Close"]

print("── РЕАЛНО: етикетът във всеки ред на скрийнъра ──")
rows = []
for sym in ("AMD", "TWLO", "LNTH", "EXEL"):
    df = F(sym)
    for i in range(260, len(df)):
        r = screener._evaluate_technicals(sym, df.iloc[:i + 1], SPY.loc[:df.index[i]])
        if r:
            rows.append(r)
assert len(rows) == 77
pat = re.compile(r"^база \d+\.\d% дълбочина$")
assert all(pat.match(r["base_type"]) for r in rows)
assert all(r["base_type"] == f"база {r['base_depth_pct']}% дълбочина" for r in rows)
assert not any(w in r["base_type"].lower() for r in rows for w in ("cup", "flat", "deep", "handle"))
amd = screener._evaluate_technicals("AMD", F("AMD").loc[:"2026-09-21"], SPY.loc[:"2026-09-21"])
print(f"  ✓ {len(rows)} реални реда: всички са 'база X.X% дълбочина' (напр. AMD 21.09.2026: '{amd['base_type']}'); нито един 'cup with handle' / 'flat base'")
print()

print("── картата и имейлът ──")
from src import render, thermometer
import tempfile
html = render_brief(action=[action_card(base_type=amd["base_type"], base_depth_pct=amd["base_depth_pct"])])
assert f"<span>База (13 седмици)</span><b>{amd['base_type']}</b>" in html and "Формация" not in html
assert html.count(f"{amd['base_depth_pct']}%") >= 1 and f"{amd['base_type']} ({amd['base_depth_pct']}%)" not in html     # без дублиран процент
brief = {"date": "2026-10-05", "thermometer": thermometer.thermometer_unavailable(RuntimeError("тест")), "watchlist": [],
         "action": [action_card(base_type=amd["base_type"], base_depth_pct=amd["base_depth_pct"])],
         "ai_macro": {"macro_brief": "тест", "regime_comment": "", "sector_logic": []}}
email = render.render_email(brief)
assert f"{amd['base_type']} · RS нов макс" in email and "cup with handle" not in email
print(f"  ✓ карта: 'База (13 седмици): {amd['base_type']}' (без дублиран процент и без 'Формация'); имейл: '{amd['base_type']} · RS нов макс'")
print()

print("── AI промпт ──")
slim = [{"ticker": "AMD", "base_type": amd["base_type"], "base_depth_pct": amd["base_depth_pct"]}]
prompt = ai_brief._build_ticker_user_prompt(slim, [], "Offensive")
payload = prompt.split("КАНДИДАТИ:")[1].split("\n")[0]
assert "cup" not in payload.lower() and "база" in payload
assert 'НЕ наричай базата "cup with handle", "flat base", "VCP"' in prompt
def code_hits(p):                                                                      # без редовете-коментари
    return [l for l in p.read_text(encoding="utf-8").splitlines()
            if not l.lstrip().startswith("#") and re.search(r"cup with handle|flat base|deep base", l)]
src_hits = [p.name for p in (ROOT / "src").glob("*.py") if code_hits(p)]
assert src_hits == ["ai_brief.py"]                                                    # единственото място е забраната в промпта
print("  ✓ payload-ът към модела носи 'база X% дълбочина'; промптът забранява изрично cup with handle / flat base / VCP;")
print("    в src/ тези думи ги има само в самата забрана")
print()
print("Всички тестове минаха.")
