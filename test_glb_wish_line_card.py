"""
21.10.2026 · етап 4 (решения от 21.10): GLB картата показва броя затваряния под нашата линия от входа (т. 4) и линията на Уиш — най-високата цена (High) на месечния бар към деня на нашия вход, непробита ≥ 3 месеца
(неговото правило: постовете от 16.01.2023, 05.11.2025, 02.12.2025; нашата линия е по месечния close и е по-ниска). Ред: „линия по Уиш (High): $X (ММ.ГГГГ) — над / под нея с Y%“;
ако най-високият бар още не е „почивал“ 3 месеца — „при входа няма зелена линия“. Само информация: не филтрира и не мести входа.

РЕАЛНО: tests/fixtures/glb_wish_line_2026-10-21.json — дневните барове на MRK, MSFT, WAT, MEDP от Yahoo (свалени 21.10.2026, до 20.10) и реалните им събития от data/glb_state.json
след брифа от 21.10. Месеците преди 2026 са по един ред на месец (High = месечният максимум, Close = последният) — месечната серия е същата; Low на тези редове е close-ът
(→ „× от дъното“ на картата не се проверява тук). СИНТЕТИЧНО: нищо.
Пускане: python test_glb_wish_line_card.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
config.GLB_CARDS_RULE = "close_hysteresis"          # 22.10.2026: тестът е за старото правило на картите (close линия + хистерезис), което остава зад GLB_CARDS_RULE

_tmp = tempfile.TemporaryDirectory(prefix="mb_glbwl_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import glb_screener as g, render

FX = json.loads((ROOT / "tests" / "fixtures" / "glb_wish_line_2026-10-21.json").read_text(encoding="utf-8"))
T = list(FX["tickers"])
q = lambda: contextlib.redirect_stdout(io.StringIO())


def frame(sym):
    t = FX["tickers"][sym]
    m = pd.DataFrame([{"Open": c, "High": h, "Low": c, "Close": c, "Volume": 0} for d, h, c in t["monthly"]], index=pd.to_datetime([d for d, _, _ in t["monthly"]]))
    d = t["daily"]
    daily = pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))
    return pd.concat([m, daily])


DF = {s: frame(s) for s in T}

print("── 1. wish_high_line върху РЕАЛНИТЕ барове ──")
exp = {"MSFT": ("2026-10-12", 555.45, "2025-07", 14, True), "WAT": ("2026-09-17", 428.22, "2021-09", 59, True),
       "MRK": ("2026-08-14", 135.05, "2026-07", 0, False), "MEDP": ("2026-08-19", 677.9, "2026-07", 0, False)}
for s, (day, line, month, un, valid) in exp.items():
    w = g.wish_high_line(DF[s], day)
    assert (w["line"], w["month"], w["months_unpen"], w["valid"]) == (line, month, un, valid), (s, w)
assert g.wish_high_line(DF["MSFT"].iloc[:0], "2026-10-12") is None and g.wish_high_line(None, "2026-10-12") is None
print("  ✓ MSFT $555.45 (07.2025, 14 мес.) и WAT $428.22 (09.2021, 59 мес.) — линии; MRK $135.05 и MEDP $677.90 (07.2026, 0 мес.) — още не е зелена линия; празни данни → None")

print()
print("── 2. screen() със РЕАЛНИТЕ събития от 21.10 (подменено yf.download) ──")
state = pathlib.Path(_tmp.name) / "glb_state.json"
state.write_text(json.dumps({"updated": "2026-10-21", "events": FX["events"], "seed": FX["seed"]}, ensure_ascii=False), encoding="utf-8")
big = pd.concat({s: DF[s] for s in T}, axis=1)
g.yf = type("Y", (), {"download": staticmethod(lambda batch, **kw: big[list(batch)])})
g._verified_company_name = lambda s: {"name": s, "verified": True}
g.time.sleep = lambda s: None
with q():
    rows = {r["ticker"]: r for r in g.screen(universe=T, state_path=state, today="2026-10-21")}
assert set(rows) == set(T), rows.keys()
got = {s: (r["wish_high"]["line"], r["wish_high"]["valid"], r["wish_high"]["pct"]) for s, r in rows.items()}
assert got == {"MSFT": (555.45, True, -4.2), "WAT": (428.22, True, 3.4), "MRK": (135.05, False, 9.8), "MEDP": (677.9, False, -8.2)}, got
assert {s: r["line"] for s, r in rows.items()} == {s: FX["events"][s]["line"] for s in T}                 # нашата линия не се пипа
print("  ✓ картите носят линията на Уиш към деня на входа: MSFT −4.2% под $555.45, WAT +3.4% над $428.22; MRK и MEDP — без зелена линия при входа; нашата линия е същата")
# 21.10 (етап 4, т. 4): затварянията под НАШАТА линия от входа до 20.10 — MSFT 2 (16.10, 20.10), WAT и MRK 0; MEDP 9 — от реалния вход 10.08 (episode_start, т. 5; от 19.08 са 6, както в доклада)
assert rows["MEDP"]["since_bar"] == "2026-08-10" and rows["MRK"]["since_bar"] == "2026-08-13"
assert {s: r["closes_below_line"] for s, r in rows.items()} == {"MEDP": 9, "MSFT": 2, "WAT": 0, "MRK": 0}, {s: r.get("closes_below_line") for s, r in rows.items()}
print("  ✓ затваряния под линията от входа: MEDP 9 (от 10.08), MSFT 2, WAT 0, MRK 0")

print()
print("── 3. страницата (РЕАЛНИЯТ бриф от 16.10 с тези карти) ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
b["glb_candidates"] = [{**r, "in_screener": False, "already_open_position": False} for r in rows.values()]
with q():
    page = render.render_dashboard(copy.deepcopy(b))
sec = page[page.index("GLB Watchlist · Green Line Breakout"):]
sec = sec[:sec.index("</section>")]
assert "линия по Уиш (High): $555.45 (07.2025) — под нея с 4.2%" in sec and "линия по Уиш (High): $428.22 (09.2021) — над нея с 3.4%" in sec
assert "по Уиш (High): при входа няма зелена линия — върхът $135.05 (07.2026) е непробит 0 мес. (нужни ≥ 3); цената е 9.8% над него" in sec
assert "върхът $677.90 (07.2026) е непробит 0 мес. (нужни ≥ 3); цената е 8.2% под него" in sec
assert sec.count("затваряния под линията от входа: 9 — по правилото на Уиш първото е изход") == 1 and sec.count("затваряния под линията от входа: 0<") == 2
old = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
with q():
    page_old = render.render_dashboard(old)
assert "по Уиш (High)" not in page_old and "затваряния под линията" not in page_old and "GLB Watchlist" in page_old                                     # стар бриф без полето — без реда, без грешка
print("  ✓ редовете се виждат на картите; РЕАЛНИЯТ бриф от 16.10 (без полето) се рендерира без тях")
print("\n✅ test_glb_wish_line_card: всичко мина")
