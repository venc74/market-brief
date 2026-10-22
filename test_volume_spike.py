"""
22.10.2026 · етап 4 (добавено 22.10): флагът на скрийнъра breakout_volume значи само „обем ≥ BREAKOUT_VOLUME_MULT (1.5)× средния за 50 сесии“ — и при цена под pivot.
Реално на 22.10: ROKU с обем 3.5× и цена −1.32% под pivot имаше breakout_volume true, а картата пишеше „3.5x ✓ пробивен“. Сега: (1) към модела отива честното име volume_spike
(дали има пробив казват pct_from_pivot и setup / setup_reason); (2) на картата „✓ пробивен“ е само над pivot, иначе „над 1.5× средния, без пробив (под pivot)“. Логиката на сетъпа не се пипа.

РЕАЛНО: tests/fixtures/card_roku_2026-10-22.json — картата на ROKU от Watchlist на 22.10; brief_2026-09-22.json (Action AMD, −0.19% под pivot) и brief_2026-10-16.json (Action EXPD, +1.7%).
СИНТЕТИЧНО (означено): отговорът на AI (празен).
Пускане: python test_volume_spike.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_vspike_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import ai_brief, render, setup_rules

ROKU = json.loads((ROOT / "tests" / "fixtures" / "card_roku_2026-10-22.json").read_text(encoding="utf-8"))["card"]
assert ROKU["breakout_volume"] is True and ROKU["pct_from_pivot"] == -1.32 and ROKU["volume_ratio"] == 3.5

print("── 1. какво вижда моделът ──")
seen = []
ai_brief._call_claude = lambda system, user, **k: (seen.append(user), json.dumps({"tickers": []}))[1]
with contextlib.redirect_stdout(io.StringIO()):
    ai_brief.ticker_narratives([copy.deepcopy(ROKU)], [], "Defensive")
payload = seen[0][seen[0].index("КАНДИДАТИ: ") + len("КАНДИДАТИ: "):].split("\n", 1)[0]
cand = json.loads(payload)[0]
assert "breakout_volume" not in cand and cand["volume_spike"] is True and cand["pct_from_pivot"] == -1.32 and cand["setup"] == "below_pivot"
assert setup_rules._volume_ok(ROKU) is True                                                   # кодът на сетъпа — както досега
print("  ✓ ROKU: към модела — volume_spike: true, pct_from_pivot −1.32, setup below_pivot; без полето breakout_volume; сетъпът на кода не се мени")

print()
print("── 2. картата (РЕАЛНИ Action карти: AMD 22.09 под pivot, EXPD 16.10 над pivot) ──")
b22 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-09-22.json").read_text(encoding="utf-8"))
b16 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
amd = next(c for c in b22["action"] if c["ticker"] == "AMD"); expd = b16["action"][0]
assert (amd["breakout_volume"], amd["pct_from_pivot"], expd["breakout_volume"], expd["pct_from_pivot"]) == (True, -0.19, True, 1.7)
with contextlib.redirect_stdout(io.StringIO()):
    p22, p16 = render.render_dashboard(b22), render.render_dashboard(b16)
assert f"{amd['volume_ratio']}x · над 1.5× средния, без пробив (под pivot)" in p22 and f"{amd['volume_ratio']}x ✓ пробивен" not in p22
assert f"{expd['volume_ratio']}x ✓ пробивен" in p16
print(f"  ✓ AMD (−0.19% под pivot, обем {amd['volume_ratio']}x): „над 1.5× средния, без пробив (под pivot)“; EXPD (+1.7%, {expd['volume_ratio']}x): „✓ пробивен“")
print("\n✅ test_volume_spike: всичко мина")
