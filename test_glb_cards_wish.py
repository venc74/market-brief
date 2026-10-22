"""
22.10.2026 · етап 4 (решение от 22.10): GLB картите следват правилото на книгата „GLB по Уиш“ — линия = най-високият месечен High на предходните месеци, непробит ≥ 3 месеца; картата
започва при свеж close над нея и свършва при първия close под нея (нов свеж пробив на по-висока линия я заменя) — плюс свежест: вижда се до 20-ата сесия от входа И докато close-ът е
до +10% над линията. Епизодът се смята наново от историята всеки ден (без glb_state.json). Книгата не се засяга — следи всеки запис до изхода.
Измерено 21.10 (реплей 2016–2026): средно 13.1 карти на ден, най-много 51; около 1% от големите печалби не се виждат в първите 10 сесии.

РЕАЛНО: tests/fixtures/glb_cards_2026-10-21.json — барове на EBAY, HLT, MA, MCK, XOM, AMAT, WAT, MSFT от Yahoo (21.10.2026, до 20.10). Линията на AMAT ($255.89) е числото от поста на
Уиш от 02.12.2025 — независима проверка на линията. tests/fixtures/brief_2026-10-19.json — брифът за страницата. СИНТЕТИЧНО (означено): по-тесните прагове в т. 2.
Пускане: python test_glb_cards_wish.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_glbcards_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import glb_screener as g, render

FX = json.loads((ROOT / "tests" / "fixtures" / "glb_cards_2026-10-21.json").read_text(encoding="utf-8"))
T = list(FX["tickers"])


def frame(sym):
    t = FX["tickers"][sym]
    m = pd.DataFrame([{"Open": c, "High": h, "Low": c, "Close": c, "Volume": 0} for d, h, c in t["monthly"]], index=pd.to_datetime([d for d, _, _ in t["monthly"]]))
    d = t["daily"]
    return pd.concat([m, pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))])


DF = {s: frame(s) for s in T}
assert config.GLB_CARDS_RULE == "wish_high" and config.GLB_CARD_MAX_SESSIONS == 20 and config.GLB_CARD_MAX_ABOVE_PCT == 10.0

print("── 1. картите към 21.10 (РЕАЛНИ барове) ──")
C = {s: g.wish_card(s, DF[s], "2026-10-21") for s in T}
vis = {s: (c["since"], c["sessions"], c["pct_vs_line"], c["line"]) for s, c in C.items() if c and c["visible"]}
assert vis == {"EBAY": ("2026-10-15", 4, 1.6, 119.31), "HLT": ("2026-10-20", 1, 0.4, 358.0), "MA": ("2026-10-13", 6, 3.1, 601.77),
               "MCK": ("2026-10-16", 3, 3.1, 999.0), "XOM": ("2026-10-16", 3, 0.8, 176.41)}, vis
amat = C["AMAT"]
assert amat and not amat["visible"] and amat["line"] == 255.89 and amat["sessions"] > 20 and amat["pct_vs_line"] > 10        # линията от поста на Уиш (02.12.2025)
assert C["WAT"] is None and C["MSFT"] is None
assert C["HLT"]["prior_high_month"] == "2026-06" and C["HLT"]["months_unpenetrated"] == 3 and C["XOM"]["since_close"] > 176.41
print("  ✓ видими: EBAY (15.10), HLT (20.10, сесия 1), MA (13.10), MCK (16.10), XOM (16.10 — след close под линията на 15.10 и обратно над нея)")
print("  ✓ AMAT: отворен пробив над $255.89 — линията от поста на Уиш от 02.12.2025 — но извън 20-те сесии и над +10%; WAT и MSFT — без отворен пробив")

print()
print("── 2. праговете на свежестта (СИНТЕТИЧНО по-тесни) ──")
config.GLB_CARD_MAX_ABOVE_PCT = 1.0
assert {s for s in T if (c := g.wish_card(s, DF[s], "2026-10-21")) and c["visible"]} == {"HLT", "XOM"}
config.GLB_CARD_MAX_ABOVE_PCT = 10.0
config.GLB_CARD_MAX_SESSIONS = 3
assert {s for s in T if (c := g.wish_card(s, DF[s], "2026-10-21")) and c["visible"]} == {"HLT", "MCK", "XOM"}
config.GLB_CARD_MAX_SESSIONS = 20
print("  ✓ до +1% над линията — само HLT и XOM; до 3 сесии — HLT, MCK, XOM")

print()
print("── 3. screen(): без glb_state.json, статусът брои отворените ──")
big = pd.concat({s: DF[s] for s in T}, axis=1)
g.yf = type("Y", (), {"download": staticmethod(lambda batch, **kw: big[list(batch)])})
g._verified_company_name = lambda s: {"name": s, "verified": True}
g.time.sleep = lambda s: None
state = pathlib.Path(_tmp.name) / "glb_state.json"
with contextlib.redirect_stdout(io.StringIO()):
    rows = g.screen(universe=T, state_path=state, today="2026-10-21")
assert sorted(r["ticker"] for r in rows) == ["EBAY", "HLT", "MA", "MCK", "XOM"] and all(r["rule"] == "wish_high" and "visible" not in r for r in rows)
assert g.LAST_STATUS["rule"] == "wish_high" and g.LAST_STATUS["open_episodes"] == 6 and g.LAST_STATUS["candidates"] == 5 and not state.exists()
print("  ✓ 5 карти, 6 отворени пробива (AMAT извън свежестта), правилото — в статуса; файлът на хистерезиса не се пише")

print()
print("── 4. страницата (РЕАЛНИЯТ бриф от 19.10 с тези карти) ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b["glb_candidates"] = [{**r, "in_screener": False, "already_open_position": False} for r in rows]
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b)
sec = page[page.index("GLB Watchlist · Green Line Breakout"):]; sec = sec[:sec.index("</section>")]
assert "Правилото е на Eric Wish:" in sec and "картата се вижда до 20-ата сесия от входа и докато е до +10% над линията" in sec and "хистерезисът" not in sec
assert "линия (High) $358.00 (06.2026)" in sec and "сесия 1 от 20" in sec and "prior high" not in sec
old = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
with contextlib.redirect_stdout(io.StringIO()):
    page_old = render.render_dashboard(old)
assert "Идеята е на Eric Wish:" in page_old and "prior high" in page_old                     # стар бриф (картите без "rule") — старият текст
print("  ✓ заглавието казва правилото на Уиш и свежестта; картата — „линия (High) $358.00 (06.2026)“ и „сесия 1 от 20“; старият бриф — старият текст")
print("\n✅ test_glb_cards_wish: всичко мина")
