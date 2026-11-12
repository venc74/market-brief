"""
12.11.2026 (т. 4): при 0 непроверени фундамента редът под „На радара“ не изчезва — „Фундаменти: проверени всички N (M от кеша).“ Реално 12.11: 79 проверени — 58 нови заявки
към Yahoo и 21 от кеша, 0 непроверени (редът беше изчезнал).

РЕАЛНО: tests/fixtures/screener_status_2026-11-12.json — screener_status от брифа на 12.11 (data/2026-11-12.json, изрязано 12.11.2026); brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): т. 2 — кандидати без данни от Yahoo, брифове отпреди кеша / без броя.
Пускане: python test_fundamentals_all_checked.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_fund_all_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render

FXD = ROOT / "tests" / "fixtures"
ST = json.loads((FXD / "screener_status_2026-11-12.json").read_text(encoding="utf-8"))["screener_status"]
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))

print("── 1. РЕАЛНО: 12.11 — 79 проверени, 21 от кеша, 0 непроверени ──")
assert ST["fundamentals_not_checked"]["n"] == 0 and ST["fundamentals_checked"] == 79 and ST["fundamentals_cache"]["hits"] == 21
note = render.fundamentals_note(ST)
assert note == "Фундаменти: проверени всички 79 (21 от кеша).", note
b = copy.deepcopy(B19); b["screener_status"] = ST
with contextlib.redirect_stdout(io.StringIO()):
    page, mail = render.render_dashboard(b, publish=False), render.render_email(b)
assert note in page and note in mail
print(f"  ✓ „{note}“ — на страницата и в имейла")

print("── 2. СИНТЕТИЧНО: без данни от Yahoo, без кеша, стари брифове ──")
un = {**ST, "fundamentals_unavailable": ["EMPTY", "LLY"]}
assert render.fundamentals_note(un) == "Фундаменти: проверени всички 79 (21 от кеша); за 2 Yahoo не върна данни (EMPTY, LLY) — те не са оценени."
assert render.fundamentals_note({**ST, "fundamentals_unavailable": [f"T{i}" for i in range(7)]}).count("…") == 1
pre_cache = {k: v for k, v in ST.items() if k != "fundamentals_cache"}                    # 06.11–09.11: без кеша
assert render.fundamentals_note(pre_cache) == "Фундаменти: проверени всички 79."
assert render.fundamentals_note({**ST, "fundamentals_cache": {"hits": 0, "requests": 79, "stored": 0}}) == "Фундаменти: проверени всички 79 (0 от кеша)."
assert render.fundamentals_note({"fundamentals_not_checked": {"n": 0}}) is None              # без броя — както преди
assert render.fundamentals_note({**ST, "fundamentals_checked": 0}) is None                   # няма кандидати
assert render.fundamentals_note({k: v for k, v in ST.items() if k != "fundamentals_not_checked"}) is None      # бриф отпреди 06.11
assert render.fundamentals_note({**ST, "fundamentals_not_checked": {"n": 3, "max": 60, "top": []}}).startswith("Фундаментите не са проверени за 3 имена")   # с непроверени — старият ред
print("  ✓ без данни от Yahoo — изрично; без кеша — без скобите; без броя / без кандидати / стар бриф — без ред; с непроверени — старият ред")
print("\n✅ test_fundamentals_all_checked: всичко мина")
