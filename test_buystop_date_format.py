"""
15.10.2026 · buy-stop картата в ПЪРВИЯ ден пише датата като ДД.ММ, не ISO: "(валиден 5 сесии, до 20.10)" и "🎯 Buy-stop $390.80 · валиден до 20.10" (ZBRA на 14.10: "до 2026-10-20").
От втория ден (чакащ запис в книгата) текстът и досега беше "до 20.10, от 14.10" (setup_rules.apply_book_window). Същото и за реда "Валиден до" на Action картата.

РЕАЛНО: tests/fixtures/brief_2026-10-14.json — картата на ZBRA (price 386.57, pivot 390.80, buy-stop валиден до 2026-10-20).
СИНТЕТИЧНО (маркирано): чакащият запис в книгата за ZBRA (втори ден); реалният план на ZBRA, сложен като Action карта.
Пускане: python test_buystop_date_format.py
"""
import sys, json, pathlib, copy, re, tempfile, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_bsdate_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import setup_rules, render, main

# 20.10.2026 (етап 3, т. 1): реалните брифове до 20.10 носят старата формулировка ("Купува се само ако … обем ≥ 1.5× среден за потвърждение") — превежда се в новата
import re as _re
_OLD_TAIL = _re.compile(r"Купува се само ако High ≥ \$([\d.]+), до \$([\d.]+); обем ≥ ([\d.]+)× среден за потвърждение\.")
new_wording = lambda t: _OLD_TAIL.sub(lambda m: (f"Buy-stop поръчката се изпълнява при докосване (High ≥ ${m[1]}), до ${m[2]}; обемът се вижда едва при затварянето — "
                                                  f"книгата отбелязва дали денят на входа затвори с ≥ {m[3]}× среден обем."), t or "")

B14 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-14.json").read_text(encoding="utf-8"))
REAL = next(c for c in B14["watchlist"] if c["ticker"] == "ZBRA")
assert "(валиден 5 сесии, до 2026-10-20)" in REAL["setup"]["trigger_text"]                     # дефектът в публикувания бриф

print("── 1. РЕАЛНАТА карта на ZBRA от 14.10, сметната наново ──")
z = copy.deepcopy(REAL)
setup_rules.annotate([z], dt.date(2026, 10, 14))
assert z["setup"]["trigger_text"] == new_wording(REAL["setup"]["trigger_text"]).replace("до 2026-10-20", "до 20.10") and z["setup"]["valid_through"] == "2026-10-20"
print("  ✓", z["setup"]["trigger_text"])
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
z["ai"]["watchlist_trigger"] = main._watchlist_trigger_text(z, B14["thermometer"]["regime"])           # текстът "Trigger" се сглобява от кода (2б) — наново от новия setup
b = copy.deepcopy(B14); b["watchlist"] = [z if c["ticker"] == "ZBRA" else c for c in b["watchlist"]]
page = flat(render.render_dashboard(b))
card = page[page.index("🎯 Buy-stop $390.80"):][:600]
assert card.startswith("🎯 Buy-stop $390.80 · валиден до 20.10 · таван за вход")
assert "Trigger: Чака пробив: buy-stop $390.80 (валиден 5 сесии, до 20.10)" in page and "(валиден 5 сесии, до 2026-10-20)" not in page
print("  ✓ картата: '🎯 Buy-stop $390.80 · валиден до 20.10' и 'Trigger: … (валиден 5 сесии, до 20.10)'; таблицата на книгата остава с ISO датите (както всички колони с дати)")

print()
print("── 2. втори ден: прозорецът на записа (СИНТЕТИЧЕН чакащ запис от 14.10) ──")
z2 = copy.deepcopy(REAL)
rec = {"ticker": "ZBRA", "status": "pending", "entry_date": "2026-10-14", "valid_through": "2026-10-20", "buy_stop": 390.8, "window_sessions": 5}
setup_rules.annotate([z2], dt.date(2026, 10, 15), {"ZBRA": rec})
assert "(валиден до 20.10, от 14.10 — 5 сесии от първия ден)" in z2["setup"]["trigger_text"] and z2["setup"]["valid_label"] == "до 20.10, от 14.10"
print("  ✓ '(валиден до 20.10, от 14.10 — 5 сесии от първия ден)' — пренаписването намира новия формат")

print()
print("── 3. Action картата: 'Валиден до ДД.ММ' (РЕАЛНИЯТ v2 план на ZBRA от 14.10, СИНТЕТИЧНО сложен като Action — от 03.10 насам няма v2 Action карта) ──")
a = copy.deepcopy(B14)
act = copy.deepcopy(REAL); act["plan"] = copy.deepcopy(REAL["plan_preview"])
a["action"] = [act]
p = flat(render.render_dashboard(a))
assert "Валиден до 20.10 (5 сесии)" in p and "Валиден до 2026-10-20" not in p
print("  ✓ 'Валиден до 20.10 (5 сесии)'")
print("\n✅ test_buystop_date_format: всичко мина")
