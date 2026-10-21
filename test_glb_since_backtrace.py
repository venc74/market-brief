"""
21.10.2026 · етап 4, т. 5 (решения от 21.10): реалният ден на входа за GLB събитие от възстановяването от историята. Възстановяването на 09.10 гледа само последните 40 сесии
(14.08–09.10) от празно състояние, затова MRK — с close +2.73% над линията още на 13.08 — получи „GLB от 14.08“ (първия ден на прозореца), а MEDP — „от 19.08“ (първия close ≥ +1%
в прозореца; на 14.08 беше между −3% и +1%, а по същото правило е „вътре“ от 10.08; така и FCX — от 05.08). glb_screener.episode_start връща назад до границата на епизода
(последното затваряне под линията − 3%) и взема първия ден след нея с правилото за вход и СЪЩАТА линия. Важи (а) за живото състояние — еднократно, за събитията със since_bar
в прозореца на последното възстановяване; (б) за всяко бъдещо възстановяване.

РЕАЛНО: tests/fixtures/glb_wish_line_2026-10-21.json — барове на MRK, MSFT, WAT, MEDP от Yahoo (21.10.2026, до 20.10) и реалните им събития и белегът seed от data/glb_state.json след
брифа от 21.10 (seed.from = 2026-08-14; MRK since_bar = 2026-08-14). СИНТЕТИЧНО: белегът „версия 1“ в т. 3 — за да тръгне ново възстановяване.
Пускане: python test_glb_since_backtrace.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_glbbt_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import glb_screener as g

FX = json.loads((ROOT / "tests" / "fixtures" / "glb_wish_line_2026-10-21.json").read_text(encoding="utf-8"))
T = list(FX["tickers"])
q = lambda: contextlib.redirect_stdout(io.StringIO())


def frame(sym):
    t = FX["tickers"][sym]
    m = pd.DataFrame([{"Open": c, "High": h, "Low": c, "Close": c, "Volume": 0} for d, h, c in t["monthly"]], index=pd.to_datetime([d for d, _, _ in t["monthly"]]))
    d = t["daily"]
    return pd.concat([m, pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))])


DF = {s: frame(s) for s in T}
g._verified_company_name = lambda s: {"name": s, "verified": True}
g.time.sleep = lambda s: None
big = pd.concat({s: DF[s] for s in T}, axis=1)
g.yf = type("Y", (), {"download": staticmethod(lambda batch, **kw: big[list(batch)])})
assert FX["seed"]["from"] == "2026-08-14" and FX["events"]["MRK"]["since_bar"] == "2026-08-14"

print("── 1. episode_start върху РЕАЛНОТО събитие на MRK ──")
ne = g.episode_start("MRK", DF["MRK"], FX["events"]["MRK"])
assert (ne["since"], ne["since_bar"], ne["since_close"], ne["line"], ne["months_unpenetrated"], ne["glb_type"], ne["since_backtraced_from"]) == \
       ("2026-08-13", "2026-08-13", 135.55, 131.95, 28, "classic", "2026-08-14"), ne
assert ne["tightness"]["band_hold_pct"] == 98.4 and ne["breakout_volume_ratio"] == 0.86
for s in ("MSFT", "WAT"):                                                       # входът им е след границата на епизода — няма по-ранен
    assert g.episode_start(s, DF[s], FX["events"][s]) is None, s
nm = g.episode_start("MEDP", DF["MEDP"], FX["events"]["MEDP"])
assert (nm["since"], nm["since_close"], nm["line"], nm["glb_type"], nm["since_backtraced_from"]) == ("2026-08-10", 602.43, 592.46, "momentum", "2026-08-19"), nm
assert g.episode_start("MRK", DF["MRK"], {**FX["events"]["MRK"], "since_bar": None}) is None
print("  ✓ MRK: 14.08 → 13.08 ($135.55, +2.73%; границата е 03.08 при $127.77 < линията − 3%); линия $131.95 и 28 месеца — същите; Classic, band_hold 98.4%, обем 0.86×; MEDP: 19.08 → 10.08 ($602.43, Momentum); MSFT и WAT — без промяна")

print()
print("── 2. живото състояние: еднократно, за входовете от прозореца на възстановяването ──")
state = pathlib.Path(_tmp.name) / "glb_state.json"
state.write_text(json.dumps({"updated": "2026-10-21", "events": FX["events"], "seed": FX["seed"]}, ensure_ascii=False), encoding="utf-8")
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rows = {r["ticker"]: r for r in g.screen(universe=T, state_path=state, today="2026-10-21")}
assert "MRK: входът е 2026-08-13, не 2026-08-14" in out.getvalue() and "MEDP: входът е 2026-08-10, не 2026-08-19" in out.getvalue()
assert rows["MRK"]["since"] == "2026-08-13" and rows["MRK"]["since_bar"] == "2026-08-13" and rows["MRK"]["pct_vs_line"] == 12.4
assert rows["MEDP"]["since_bar"] == "2026-08-10" and rows["MEDP"]["line"] == 592.46
assert {s: rows[s]["since_bar"] for s in ("MSFT", "WAT")} == {s: FX["events"][s]["since_bar"] for s in ("MSFT", "WAT")}
saved = json.loads(state.read_text(encoding="utf-8"))
assert saved["events"]["MRK"]["since_backtraced_from"] == "2026-08-14" and saved["events"]["MEDP"]["since_backtraced_from"] == "2026-08-19" and saved["seed"] == FX["seed"]
out2 = io.StringIO()
with contextlib.redirect_stdout(out2):
    rows2 = {r["ticker"]: r for r in g.screen(universe=T, state_path=state, today="2026-10-21")}
assert "входът е" not in out2.getvalue() and rows2["MRK"]["since"] == "2026-08-13" and rows2["MEDP"]["since"] == "2026-08-10"
print("  ✓ MRK показва „GLB от 13.08“, MEDP — „от 10.08“; MSFT и WAT — непроменени; записите пазят since_backtraced_from; второто пускане не мести нищо")

print()
print("── 3. ново възстановяване (СИНТЕТИЧЕН белег версия 1): първата сесия на прозореца не става ден на входа ──")
state.write_text(json.dumps({"updated": "2026-10-21", "events": {}, "seed": {"version": 1}}, ensure_ascii=False), encoding="utf-8")
with q():
    rows3 = {r["ticker"]: r for r in g.screen(universe=T, state_path=state, today="2026-10-21")}
seed = json.loads(state.read_text(encoding="utf-8"))["seed"]
first = seed["from"]
assert seed["version"] == config.GLB_SEED_VERSION and seed["sessions"] == config.GLB_SEED_SESSIONS and first == "2026-08-25", seed
assert rows3["MRK"]["since"] == "2026-08-13" and rows3["MEDP"]["since"] == "2026-08-10"
assert rows3["WAT"]["since_bar"] == "2026-09-17" and rows3["MSFT"]["since_bar"] == "2026-10-12"
assert all(r["since_bar"] != first for r in rows3.values()), {s: r["since_bar"] for s, r in rows3.items()}
print(f"  ✓ прозорец {first} → {seed['to']}: MRK пак е от 13.08 (не {first}); WAT 17.09 и MSFT 12.10 — като в живото състояние; нито една карта не е с първия ден на прозореца")
print("\n✅ test_glb_since_backtrace: всичко мина")
