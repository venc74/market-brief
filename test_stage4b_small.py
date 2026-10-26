"""
26.10.2026 · етап 4б, т. 10 (решение от 26.10) — дребните:
  (а) GLB дата = датата на СЕСИЯТА на пробива, не на брифа: NWSA и ED на 23.10 — „GLB от 23.10“ при пробив на 22.10 (старият хистерезис слага since = денят на брифа; since_bar е сесията);
  (б) задействаните записи в buy-stop книгата — еднакво: компактен ред, без AI текст (до 26.10 ZBRA below_pivot — пълна карта, AAPL / AMG no_volume — ред „без сетъп“);
  (в) „последните 10 от 14“ под таблиците на затворените (книгата glb_wish на 26.10: 14 затворени, показани 10);
  (г) отворена позиция в qm_breakout с отчет в следващите EARNINGS_WARNING_SESSIONS сесии — ред в таблицата (CBOE 30.10, UTHR 04.11, RVTY 03.11; DOCU 03.12 е извън прозореца).
(д) EPS +120.5% (AMG) и +120.3% (RS) — проверено, не е код: две различни полета (AMG — earningsQuarterlyGrowth на Yahoo = нетна печалба Q2 2026 $185.9 млн / Q2 2025 $84.3 млн;
RS — нашият преглед на отчетите: EPS $8.02 / $3.64) — съвпадение.

РЕАЛНО: tests/fixtures/stage4b_small_2026-10-26.json — картите на ED / NWSA (GLB) и ZBRA / AAPL / AMG (Watchlist) от 23.10, обобщението на glb_wish и живите записи на qm_breakout от 26.10,
датите на отчетите от Yahoo (26.10); tests/fixtures/brief_2026-10-19.json — реалният бриф за рендера. СИНТЕТИЧНО (означено): вмъкването на картите / обобщенията в брифа от 19.10,
подмененото извикване на модела.
Пускане: python test_stage4b_small.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_s4b_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render, ai_brief, earnings_move

FX = json.loads((ROOT / "tests" / "fixtures" / "stage4b_small_2026-10-26.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))


def page_of(**over) -> str:
    b = copy.deepcopy(B19)
    for k, v in over.items():
        if k == "backtest":
            b.setdefault("backtest", {}).update(v)
        else:
            b[k] = v
    with q():
        return flat(render.render_dashboard(b, publish=False))


print("── (а) GLB дата = сесията на пробива ──")
g = {c["ticker"]: c for c in FX["glb_cards_2026_10_23"]}
assert (g["ED"]["since"], g["ED"]["since_bar"]) == (g["NWSA"]["since"], g["NWSA"]["since_bar"]) == ("2026-10-23", "2026-10-22")
pg = page_of(glb_candidates=FX["glb_cards_2026_10_23"])                                                            # СИНТЕТИЧНО: картите от 23.10 в брифа от 19.10
assert pg.count("GLB от 22.10") == 2 and "GLB от 23.10" not in pg
print("  ✓ ED и NWSA: „GLB от 22.10“ (сесията), не 23.10 (брифът)")

print()
print("── (б) задействаните записи — компактен ред, без AI текст ──")
wl = copy.deepcopy(FX["watchlist_2026_10_23"])
assert sorted((c["ticker"], c["setup"]["kind"], c["setup"]["triggered"]) for c in wl) == [("AAPL", "no_volume", True), ("AMG", "no_volume", True), ("ZBRA", "below_pivot", True)]
cards, compact = render.split_watchlist(wl)
assert cards == [] and sorted(r["ticker"] for r in compact) == ["AAPL", "AMG", "ZBRA"]
z = next(r for r in compact if r["ticker"] == "ZBRA")
assert z["reason"].startswith("✅ задействан в buy-stop книгата на 21.10 по $390.80") and z["reason"].endswith("днес: под pivot — чака buy-stop")
sent = []
real = ai_brief._call_claude
ai_brief._call_claude = lambda system, user, **k: (sent.append(user), '{"tickers": []}')[1]                       # СИНТЕТИЧНО
try:
    with q():
        ai_brief.ticker_narratives(copy.deepcopy(wl), [], "Defensive")
finally:
    ai_brief._call_claude = real
assert sent == []
pw = page_of(watchlist=wl)
assert "ZBRA — ✅ задействан в buy-stop книгата на 21.10 по $390.80" in pw and "AAPL — ✅ задействан в buy-stop книгата" in pw
print(f"  ✓ ZBRA (below_pivot), AAPL и AMG (no_volume) — все ред „без сетъп“: «{z['reason'][:90]}…»; без AI извикване")

print()
print("── (в) „последните 10 от 14“ ──")
gw = FX["glb_wish_2026_10_26"]
assert (gw["line_exit"] + gw["expired"], len(gw["recent"])) == (14, 10)
pgw = page_of(backtest={"glb_wish": gw})
assert "Последно затворени (последните 10 от 14):" in pgw
gw_small = {**gw, "recent": gw["recent"][:3], "line_exit": 3, "expired": 0}                                       # СИНТЕТИЧНО: всички затворени са показани
assert "Последно затворени (3):" in page_of(backtest={"glb_wish": gw_small})
print("  ✓ glb_wish на 26.10: „Последно затворени (последните 10 от 14)“; когато са показани всички — само броят")

print()
print("── (г) QM: отворени позиции с отчет в следващите сесии ──")
live = copy.deepcopy(FX["qm_live_2026_10_26"])
D = FX["earnings_dates_2026_10_26"]
assert D == {"DOCU": "2026-12-03", "CBOE": "2026-10-30", "UTHR": "2026-11-04", "RVTY": "2026-11-03"}
n = earnings_move.book_marks(live, dt.date(2026, 10, 26), dates={}, lookup=D.get)
marks = {r["ticker"]: r.get("earnings_next") for r in live}
assert n == 3 and marks["CBOE"] == {"date": "2026-10-30", "sessions": 4} and marks["UTHR"] == {"date": "2026-11-04", "sessions": 7} and marks["RVTY"]["sessions"] == 6
assert marks["DOCU"] is None                                                                                          # 03.12 — след 20 сесии
qb = {**FX["qm_summary_2026_10_26"], "live": live}                                                                   # РЕАЛНОТО обобщение от 26.10 с отбелязаните редове
pq = page_of(backtest={"qm_breakout": qb})
assert "📅 отчет 30.10 (след 4 сесии) — позицията държи през отчета; стопът не пази от гап" in pq and "📅 отчет 04.11 (след 7 сесии)" in pq
print("  ✓ CBOE 30.10 (след 4 сесии), UTHR 04.11 (след 7), RVTY 03.11 (след 6) — ред под тикъра; DOCU 03.12 — извън 20-те сесии")
print("\n✅ test_stage4b_small: всичко мина")
