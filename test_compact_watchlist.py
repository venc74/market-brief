"""
Опростяване (втори преглед, 10.10.2026, решено): too_wide / extended / no_volume във Watchlist — един компактен ред (тикър, причина, стоп %, отчет), без AI наратив;
AI наративи само за config.AI_NARRATIVE_SETUPS = (confirmed, below_pivot). Отворена позиция (OPEN✓) остава карта.

Защо: реално 05–09.10 — 0 Action, 5–9 от Watchlist картите too_wide, а наративите (ai_usage "Тикър наративи") бяха най-голямото перо в изхода:
in/out по дни 8 455/7 363 · 10 963/9 239 · 9 596/8 234 · 10 071/7 392 · 7 717/4 822 (сума на партидите). Оценка по модела на ai_usage (фиксирано ~1 950 входни на партида,
~510 входни и ~840 изходни на тикър): спестени средно ~7 800 входни и ~6 700 изходни токена на ден (~39% от изхода на целия run).
РЕАЛНО: tests/fixtures/brief_2026-10-05.json (EXPD below_pivot + 8 too_wide), tests/fixtures/watchlist_cards_2026-10-08.json (8 too_wide).
СИНТЕТИЧНО: подмененото _call_claude, отворената позиция в т.3.
Пускане: python test_compact_watchlist.py
"""
import sys, json, re, pathlib, tempfile, copy, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cw_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import ai_brief, render

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
FX08 = json.loads((ROOT / "tests" / "fixtures" / "watchlist_cards_2026-10-08.json").read_text(encoding="utf-8"))
assert config.AI_NARRATIVE_SETUPS == ("confirmed", "below_pivot")
calls = []
ai_brief._call_claude = lambda system, user, **k: calls.append(user) or json.dumps({"tickers": []})

print("── 1. към модела отиват само confirmed / below_pivot ──")
ai_brief.ticker_narratives([copy.deepcopy(c) for c in B05["watchlist"]], [], "Defensive")
assert len(calls) == 1
sent = {x["ticker"] for x in json.loads(re.search(r"КАНДИДАТИ: (\[.*?\])\n", calls[0], re.S).group(1))}
assert sent == {"EXPD"}
calls.clear()
ai_brief.ticker_narratives([copy.deepcopy(c) for c in FX08["cards"]], [], "Defensive")
assert calls == []
print("  ✓ РЕАЛНИЯТ 05.10: 1 извикване само с EXPD (вместо 2 партиди с 9 тикъра); РЕАЛНИЯТ 08.10 (8 too_wide): нито едно извикване")

print()
print("── 2. страницата: карта само за EXPD, останалите — един ред ──")
cards, compact = render.split_watchlist(B05["watchlist"])
assert [c["ticker"] for c in cards] == ["EXPD"] and len(compact) == 8 and all(r["kind"] == "too_wide" for r in compact)
page = " ".join(re.sub(r"<[^>]+>", " ", htmllib.unescape(render.render_dashboard(copy.deepcopy(B05)))).split())
assert "Watchlist · 1 (+8 без сетъп за вход)" in page and "В скрийнъра, без сетъп за вход днес:" in page
assert "FTNT — структурен стоп 12.6% > 10%" in page and "AMD — структурен стоп 25.6% > 10%" in page
print("  ✓ «Watchlist · 1 (+8 без сетъп за вход)»; ред «FTNT — структурен стоп 12.6% > 10% · AMD — структурен стоп 25.6% > 10% · …»; картата е само на EXPD")

print()
print("── 3. отворена позиция с too_wide остава карта; extended показва стопа ──")
wl = copy.deepcopy(B05["watchlist"])
wl[1]["ai"] = {"watchlist_reason_type": "existing_position"}                          # СИНТЕТИЧНО: FTNT като отворена позиция
ext = copy.deepcopy(wl[2]); ext["ticker"] = "EXTX"; ext["setup"] = {"kind": "extended", "struct_risk_pct": 6.2}
cards, compact = render.split_watchlist(wl + [ext])
assert [c["ticker"] for c in cards] == ["EXPD", "FTNT"] and compact[-1]["ticker"] == "EXTX" and compact[-1]["reason"] == f"над +{config.BUYABLE_ZONE_MAX_PCT:g}% от pivot"
b = copy.deepcopy(B05); b["watchlist"] = wl + [ext]
page = " ".join(re.sub(r"<[^>]+>", " ", htmllib.unescape(render.render_dashboard(b))).split())
assert "EXTX — над +5% от pivot, стоп 6.2%" in page
print("  ✓ OPEN✓ позиция (СИНТЕТИЧНО FTNT) остава карта; extended → «над +5% от pivot, стоп 6.2%»")
print()
print("Всички тестове минаха.")
