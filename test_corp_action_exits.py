"""
13.10.2026 · "Излязоха от вчера": тикър, изключен заради корпоративно действие, носи ТАЗИ причина (същия текст като реда "Изключени (корпоративно действие)" под Watchlist), не общата
("не е в днешния технически списък" / причината от screener.explain_exits).

РЕАЛНО: Watchlist картите от брифа на 05.10 (tests/fixtures/brief_2026-10-05.json) като "вчера"; текстът на изключването — от corp_actions.exclude върху РЕАЛНИТЕ серии на CTVA и VYLR
(tests/fixtures/corp_actions_2026-10-13.json). СИНТЕТИЧНО (означено): картата на CTVA във вчерашния Watchlist, днешният Watchlist (вчерашният без две карти), подмененото теглене и explain.
Пускане: python test_corp_action_exits.py
"""
import sys, json, pathlib, io, contextlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_corpexit_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import corp_actions as ca, watchlist_exits as we

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
FX = json.loads((ROOT / "tests" / "fixtures" / "corp_actions_2026-10-13.json").read_text(encoding="utf-8"))["tickers"]
ALL = {t: {"dates": [d for d, r in zip(v["dates"], v["splits"]) if r], "ratios": [r for r in v["splits"] if r],
           "close": pd.Series(v["close"], index=pd.to_datetime(v["dates"]))} for t, v in FX.items()}

ca.reset()
with contextlib.redirect_stdout(io.StringIO()):
    _, ex = ca.exclude([{"ticker": "CTVA"}], "screener", "2026-10-13", fetch=lambda ts: {t: ALL[t] for t in ts if t in ALL})
TEXT = ex[0]["text"]
assert TEXT.startswith("CTVA — изключена: отделяне на Vylor (1:1) на 01.10;") and "извън скрийнъра до" in TEXT

prior = [c for c in B05["watchlist"]] + [{"ticker": "CTVA", "setup": {"kind": "below_pivot"}}]             # СИНТЕТИЧНО: CTVA във вчерашния Watchlist
gone = prior[0]["ticker"]
today = [c for c in prior if c["ticker"] not in (gone, "CTVA")]                                               # СИНТЕТИЧНО: днес без първата карта и без CTVA
asked = []
explain = lambda ts: asked.extend(ts) or {t: "RS линия 95.0% от 52-седмичния максимум < 97% (СИНТЕТИЧНО)" for t in ts}

print("── 1. изключеният носи причината от корпоративното действие ──")
rows = we.compute(prior, [], today, [], explain=explain, corp_excluded={"CTVA": TEXT})
r = {x["ticker"]: x for x in rows}
assert r["CTVA"]["reason"] == TEXT and r["CTVA"]["kind"] == "corp_action"
assert r[gone]["reason"].startswith("RS линия") and asked == [gone]                                          # explain не се пита за CTVA
print("  ✓ CTVA:", r["CTVA"]["reason"][:110], "…")
print(f"  ✓ {gone}: причината от скрийнъра (explain е питан само за него)")

print()
print("── 2. без изключване — както досега ──")
asked.clear()
rows2 = we.compute(prior, [], today, [], explain=explain)
assert {x["ticker"]: x["kind"] for x in rows2}["CTVA"] == "screener" and sorted(asked) == sorted([gone, "CTVA"])
print("  ✓ без corp_excluded CTVA получава общата причина от скрийнъра")

print()
print("── 3. main подава изключените от скрийнъра ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'corp_excluded={e["ticker"]: e["text"] for e in corp_ex_screener})' in src
assert src.index('candidates, corp_ex_screener = corp_actions.exclude(candidates, "screener", today)') < src.index("wl_exits = watchlist_exits.run(")
print("  ✓")
print()
print("Всички тестове минаха.")
