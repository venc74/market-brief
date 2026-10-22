"""
21.10.2026 · етап 4 (решение от 21.10): книга „GLB по Уиш“ по НЕГОВОТО правило (категория glb_wish_high) — линия при най-високата цена (High) на месечен бар от предходните месеци,
непробита ≥ 3 месеца; вход при свежо затваряне над нея, изход при първото затваряне под нея. Чист старт от деня на качването (GLB_WISH_HIGH_TRACK_FROM); същия ден спира книгата
„GLB — наш вариант (close)“ (glb_wish): нови записи няма, отворените се затварят по правилото си, секцията е архив. Празна дата → новата книга не записва, старата не спира.

РЕАЛНО: tests/fixtures/glb_wish_high_2026-10-21.json — барове на HLT, MA, MSFT, SPY от Yahoo (21.10.2026, до 20.10); tests/fixtures/brief_2026-10-16.json — реалният бриф за страницата.
СИНТЕТИЧНО (означено): датите на старта в т. 3–5 (2026-10-14) — за да има записи и в двете книги около деня на старта.
Пускане: python test_glb_wish_high_book.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_gwh_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import glb_screener as g, backtest, trade_sim, render
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"

FX = json.loads((ROOT / "tests" / "fixtures" / "glb_wish_high_2026-10-21.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())


def frame(sym):
    t = FX["tickers"][sym]
    m = pd.DataFrame([{"Open": c, "High": h, "Low": c, "Close": c, "Volume": 0} for d, h, c in t["monthly"]], index=pd.to_datetime([d for d, _, _ in t["monthly"]]))
    d = t["daily"]
    return pd.concat([m, pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))])


DF = {s: frame(s) for s in FX["tickers"]}
g._verified_company_name = lambda s: {"name": s, "verified": True}

print("── 1. сигналът по High срещу сигнала по close (РЕАЛНИ барове) ──")
wc, wh = g.wish_signal(DF["MSFT"], "2026-10-20"), g.wish_signal(DF["MSFT"], "2026-10-20", kind="high")
assert wc and (wc["signal_date"], wc["line"], wc["close"], wc["line_kind"]) == ("2026-10-19", 533.5, 533.52, "close") and wh is None
t = g.wish_table(DF["MSFT"]["Close"], DF["MSFT"]["High"])
assert round(float(t.loc["2026-10-19", "line"]), 2) == 555.45 and t.loc["2026-10-19", "prior_high_month"] == "2025-07" and not t.loc["2026-10-19", "signal"]
h = g.wish_signal(DF["HLT"], "2026-10-21", kind="high")
assert (h["signal_date"], h["line"], h["close"], h["prior_high_month"], h["months_unpenetrated"], h["line_kind"]) == ("2026-10-20", 358.0, 359.29, "2026-06", 3, "high"), h
assert g.wish_signal(DF["HLT"], "2026-10-21") is None                         # по close линията HLT е пробил на 15.10 — 20.10 не е свеж
m_h, m_c = g.wish_signal(DF["MA"], "2026-10-14", kind="high"), g.wish_signal(DF["MA"], "2026-10-14")
assert (m_h["signal_date"], m_h["line"], m_c["signal_date"], m_c["line"]) == ("2026-10-13", 601.77, "2026-10-13", 595.29)
assert g.wish_table(DF["MSFT"]["Close"]).equals(g.wish_table(DF["MSFT"]["Close"], None))     # без high — точно старото поведение
print("  ✓ MSFT 19.10: по close — свеж сигнал ($533.52 над $533.50), по High — не ($555.45, 07.2025); HLT 20.10 — свеж пробив над $358.00 (06.2026, 3 мес.); MA 13.10 — и по двете линии")

print()
print("── 2. screen(): двата списъка от едни и същи цени (подменено yf.download) ──")
big = pd.concat({s: DF[s] for s in ("HLT", "MA", "MSFT")}, axis=1)
g.yf = type("Y", (), {"download": staticmethod(lambda batch, **kw: big[list(batch)])})
g.time.sleep = lambda s: None
state = pathlib.Path(_tmp.name) / "glb_state.json"
state.write_text(json.dumps({"updated": "2026-10-21", "events": {}, "seed": {"version": config.GLB_SEED_VERSION, "sessions": 40, "from": "2026-08-25", "to": "2026-10-20"}}), encoding="utf-8")
with q():
    g.screen(universe=["HLT", "MA", "MSFT"], state_path=state, today="2026-10-21")
assert [w["ticker"] for w in g.LAST_WISH_HIGH_SIGNALS] == ["HLT"] and [w["ticker"] for w in g.LAST_WISH_SIGNALS] == []
assert g.LAST_STATUS["wish_high_signals"] == 1 and g.LAST_STATUS["wish_signals"] == 0
print("  ✓ на 21.10: „GLB по Уиш“ — HLT; close книгата — нищо свежо (MSFT е от 19.10)")

print()
print("── 3. старт и архив (СИНТЕТИЧНА дата на старта 14.10) ──")
config.TRACK_GLB_WISH = config.TRACK_GLB_WISH_HIGH = True
config.GLB_WISH_TRACK_FROM = "2026-10-12"
config.GLB_WISH_HIGH_TRACK_FROM = ""
tr = {}
backtest._ingest_glb_wish_list(tr, "2026-10-14", [{"ticker": "MA", **m_h}], "Offensive", backtest.CATEGORY_GLB_WISH_HIGH)
backtest._ingest_glb_wish_list(tr, "2026-10-14", [{"ticker": "MA", **m_c}], "Offensive")
assert list(tr) == ["MA_2026-10-14_gw"]                                       # без дата: новата книга не записва, старата — да
config.GLB_WISH_HIGH_TRACK_FROM = "2026-10-14"
tr = {}
backtest._ingest_glb_wish_list(tr, "2026-10-14", [{"ticker": "MA", **m_c}], "Offensive")                       # close книгата: от деня на старта — архив
backtest._ingest_glb_wish_list(tr, "2026-10-13", [{"ticker": "MSFT", **wc, "signal_date": "2026-10-12"}], "Offensive")   # денят преди — още записва
backtest._ingest_glb_wish_list(tr, "2026-10-13", [{"ticker": "MA", **m_h}], "Offensive", backtest.CATEGORY_GLB_WISH_HIGH)  # новата: преди старта — не
backtest._ingest_glb_wish_list(tr, "2026-10-14", [{"ticker": "MA", **m_h}], "Offensive", backtest.CATEGORY_GLB_WISH_HIGH)
backtest._ingest_glb_wish_list(tr, "2026-10-21", [{"ticker": "HLT", **h}], "Defensive", backtest.CATEGORY_GLB_WISH_HIGH)
backtest._ingest_glb_wish_list(tr, "2026-10-21", [{"ticker": "HLT", **h}], "Defensive", backtest.CATEGORY_GLB_WISH_HIGH)    # повторение — без втори запис
assert sorted(tr) == ["HLT_2026-10-21_gwh", "MA_2026-10-14_gwh", "MSFT_2026-10-13_gw"], sorted(tr)
assert tr["MA_2026-10-14_gwh"]["category"] == "glb_wish_high" and tr["MA_2026-10-14_gwh"]["line"] == 601.77 and tr["HLT_2026-10-21_gwh"]["line"] == 358.0
config.TRACK_GLB_WISH_HIGH = False
t2 = {}
backtest._ingest_glb_wish_list(t2, "2026-10-21", [{"ticker": "HLT", **h}], "Defensive", backtest.CATEGORY_GLB_WISH_HIGH)
backtest._ingest_glb_wish_list(t2, "2026-10-21", [{"ticker": "MA", **m_c}], "Defensive")
assert list(t2) == ["MA_2026-10-21_gw"]                                       # изключена нова книга → старата не спира
config.TRACK_GLB_WISH_HIGH = True
print("  ✓ празна дата: само close книгата; от 14.10: „GLB по Уиш“ записва (MA, HLT), close книгата — до 13.10 (MSFT), от 14.10 — не; повторение — един запис; TRACK_GLB_WISH_HIGH=0 → нищо не спира")

print()
print("── 4. резолюция (същата симулация) и обобщенията ──")
bars = lambda s: DF[s][DF[s].index >= "2026-01-01"][["Open", "Close"]]
r_ma = trade_sim.simulate_glb_wish(tr["MA_2026-10-14_gwh"], bars("MA"), "2026-10-21")
r_hl = trade_sim.simulate_glb_wish(tr["HLT_2026-10-21_gwh"], bars("HLT"), "2026-10-21")
assert (r_ma["status"], r_ma["fill_price"], r_ma["line_used"]) == ("open", 604.8, 601.77) and r_ma["dist_to_line_pct"] == 3.1
assert (r_hl["status"], r_hl["fill_price"]) == ("open", 359.29)
for k, r in (("MA_2026-10-14_gwh", r_ma), ("HLT_2026-10-21_gwh", r_hl)):
    tr[k].update({kk: r.get(kk) for kk in backtest._GW_RESULT_KEYS})
backtest._save_tracker(tr)
sh, sc = backtest.get_glb_wish_summary(backtest.CATEGORY_GLB_WISH_HIGH), backtest.get_glb_wish_summary()
assert (sh["records"], sh["open"], sh["track_from"], sh["archived_from"], sh["category"]) == (2, 2, "2026-10-14", None, "glb_wish_high")
assert (sh["tickers"], sh["result_tickers"]) == (2, 2)                                                  # 22.10: „N записа / M тикъра“
assert (sc["records"], sc["track_from"], sc["archived_from"], sc["category"]) == (1, "2026-10-12", "2026-10-14", "glb_wish")
assert [p["ticker"] for p in sh["live"]] == ["HLT", "MA"]
print("  ✓ MA: отворена от $604.80, +3.1% над $601.77; HLT: отворена от $359.29; обобщението на „GLB по Уиш“ — 2 записа от 14.10; close книгата — архив от 14.10")

print()
print("── 5. страницата: двете секции (РЕАЛНИЯТ бриф от 16.10) ──")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
b.setdefault("backtest", {})["glb_wish_high"], b["backtest"]["glb_wish"] = sh, sc
with q():
    page = render.render_dashboard(copy.deepcopy(b))
i_h, i_c = page.index(f"{config.GLB_WISH_BOOK_NAME} · книга (измерване, не препоръка)"), page.index(f"{config.GLB_CLOSE_BOOK_NAME} · архив · книга (измерване, не препоръка)")
assert i_h < i_c
sec_h, sec_c = page[i_h:page.index("</section>", i_h)], page[i_c:page.index("</section>", i_c)]
assert "Правилото на Eric Wish:</b> зелената линия е най-високата цена (High) на месечен бар" in sec_h and "13 162 сделки" in sec_h and "Измерване — книга glb_wish_high: 2 записа / 2 тикъра" in sec_h
assert "статистика след 20 записа с резултат (сега 2 в 2 тикъра)" in sec_h
assert "Архив:</b> нови записи няма от 14.10.2026" in sec_c and "линията е наша" in sec_c and "26 116 сделки" in sec_c and "Архив" not in sec_h
for sec in (sec_h, sec_c):
    assert "Реплеят е върху днешния универс (оцелелите): абсолютната алфа е надута; сравнението между правилата е честно" in sec
old = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
with q():
    page_old = render.render_dashboard(old)
assert f"{config.GLB_WISH_BOOK_NAME} · книга" not in page_old and "книга (измерване, не препоръка)" in page_old       # старият бриф: само неговата (close) книга, без новата секция
print("  ✓ „GLB по Уиш“ е първа (неговата линия, реплеят 13 162 сделки), close книгата — „архив“ от 14.10; и в двете: реплеят е върху оцелелите; старият бриф — без новата секция")
print("\n✅ test_glb_wish_high_book: всичко мина")
