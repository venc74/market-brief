"""
11.11.2026 (т. 1–2):
  т. 1 — висяща сделка (data/deal_state.json, „pending“) е извън ВСИЧКИ скенери извън CANSLIM: Kullamägi, GLB, EP и обновяването в 15:05 (screener.scan_universe).
         Реално: CART (DoorDash) на 11.11 беше карта в QM и в Momentum GLB. Приключване — само по 8-K (config.DEAL_CLOSE_BY_NEWS = 0; виж test_deal_closed).
  т. 2 — един универс за деня (screener.day_universe → data/universe.json): сутрешният бриф го строи веднъж, 15:05 чете същия. Реално 11.11: сутрин 917,
         в 15:05 поискани 925 = 917 + 8 наблюдавани извън универса (AI, BFLY, BHC, BLSH, BMNR, CRCL, SAP, TDOC); „918“ сутрин е броят преди изваждането на ROKU.

РЕАЛНО: tests/fixtures/universe_deals_2026-11-11.json (универсът на живо 11.11, състоянието на сделките, картите QM и GLB, наблюдаваните, покритието в 15:05),
tests/fixtures/brief_2026-10-19.json (рамката на страницата).
СИНТЕТИЧНО (означено): подмененият build_universe (брои тегленията), датите, записът в книгите за CART.
Пускане: python test_universe_deals.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_unideals_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import screener, spinoff_watch as sw, preopen, render

FX = json.loads((ROOT / "tests" / "fixtures" / "universe_deals_2026-11-11.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
U = FX["universe"]
sw.save_state(FX["deal_state"])
BUILDS = []
def fake_build():                                                                   # СИНТЕТИЧНО: заместител на Wikipedia — брои тегленията, връща РЕАЛНИЯ списък от 11.11
    BUILDS.append(1)
    screener.LAST_UNIVERSE_SOURCES.clear(); screener.LAST_UNIVERSE_SOURCES.update(FX["universe_sources"])
    return list(U)
screener.build_universe = fake_build
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 2. един универс за деня: построен веднъж, после — записаният ──")
assert len(U) == 917 and "CRWV" in U and "NBIS" in U and "ROKU" not in U and {"CART", "NWE"} <= set(U)
with q():
    u1 = screener.day_universe("2026-11-11")
assert BUILDS == [1] and u1 == U and screener.LAST_DAY_UNIVERSE == {"date": "2026-11-11", "source": "built", "n": 917}
saved = json.loads(screener.universe_cache_path().read_text(encoding="utf-8"))
assert saved["date"] == "2026-11-11" and saved["tickers"] == U and saved["sources"]["S&P 400"]["n"] == 400
screener._DAY_MEMO.clear(); screener.LAST_UNIVERSE_SOURCES.clear()                   # другият job (15:05) — нов процес
with q() as log:
    u2 = screener.day_universe("2026-11-11")
assert BUILDS == [1] and u2 == U and screener.LAST_DAY_UNIVERSE["source"] == "cache" and screener.LAST_UNIVERSE_SOURCES["S&P 500"]["n"] == 503
assert "записаният за 2026-11-11" in log.getvalue()
with q():
    for _ in range(3):
        screener.day_universe("2026-11-11")                                           # термометър, скрийнинг, GLB, QM — в същия процес
assert BUILDS == [1]
screener._DAY_MEMO.clear()
with q():
    screener.day_universe("2026-11-12")                                               # нов ден — строи се наново
assert BUILDS == [1, 1] and screener.LAST_DAY_UNIVERSE["source"] == "built"
screener._DAY_MEMO.clear(); screener.universe_cache_path().write_text(json.dumps(saved), encoding="utf-8")
st = json.loads(json.dumps(FX["deal_state"])); st["closed"]["NWE"] = {"ticker": "NWE", "how": "8-K т. 2.01,3.01", "seen": "2026-11-11"}   # СИНТЕТИЧНО: приключила след записа
sw.save_state(st)
with q():
    u3 = screener.day_universe("2026-11-11")
assert "NWE" not in u3 and len(u3) == 916 and screener.LAST_UNIVERSE_EXCLUDED == {"NWE": st["closed"]["NWE"]}   # приключилите — и при четене от записа
sw.save_state(FX["deal_state"]); screener._DAY_MEMO.clear()
print("  ✓ 1 теглене от Wikipedia за деня (вместо 4–5); 15:05 чете записания списък; нов ден — наново; приключилите се вадят и при четене")

print("── 1. висящите сделки — извън скенерите (РЕАЛНО: CART, NWE на 11.11) ──")
with q():
    su = screener.scan_universe("2026-11-11")
assert len(su) == 915 and "CART" not in su and "NWE" not in su and set(screener.LAST_SCAN_EXCLUDED) == {"CART", "NWE"}
assert screener.LAST_SCAN_EXCLUDED["CART"]["buyer"] == FX["deal_state"]["pending"]["CART"]["buyer"]
assert "CART" in [c["ticker"] for c in FX["qm_breakout"]] and {"CART", "NWE"} <= {c["ticker"] for c in FX["glb_candidates"]}     # така излязоха на 11.11
src = {f: (ROOT / "src" / f).read_text(encoding="utf-8") for f in ("main.py", "glb_screener.py", "qm_breakout.py", "preopen.py", "thermometer.py", "options_record.py", "screener.py")}
assert 'steps.step("qm_universe", lambda: screener.scan_universe(today)' in src["main.py"] and "qm_ep.run(qm_universe" in src["main.py"]        # QM и EP
assert "universe = scan_universe()" in src["glb_screener.py"] and "universe = scan_universe()" in src["qm_breakout.py"]
assert "universe = screener.scan_universe(day)" in src["preopen.py"] and "exclude=_pending_deals()" in src["preopen.py"]
assert "universe = day_universe()" in src["thermometer.py"] and "record(screener.day_universe(today)" in src["options_record.py"]
assert "    universe = day_universe()" in src["screener.py"]                                                    # CANSLIM — целият универс (етикет „deal“)
print("  ✓ универсът на скенерите 915 = 917 − CART − NWE; QM, EP, GLB, 15:05 — scan_universe; CANSLIM, термометърът, опциите — day_universe")

print("── 1–2. обновяването в 15:05: заявката, картите, покритието ──")
asked = []
NOW = dt.datetime(2026, 11, 11, 14, 6, tzinfo=dt.timezone.utc)
rec = [{"ticker": "CART", "status": "open", "category": "glb_wish_high"}]                           # СИНТЕТИЧНО: запис в книга за CART
with q():
    res = preopen.run(NOW, fetch5=lambda ts: (asked.extend(ts), {})[1], brief={"qm_breakout": FX["qm_breakout"]}, records=rec, watched=FX["watched"],
                      universe=su, daily_fn=lambda ts: {}, filings_fn=lambda *a, **k: [], headlines_fn=lambda *a: [], exclude={"CART", "NWE"})
assert "CART" not in asked and "NWE" not in asked and "A" in asked and res["excluded_deals"] == ["CART", "NWE"]
outside = sorted(set(FX["watched"]) - set(U))
assert outside == ["AI", "BFLY", "BHC", "BLSH", "BMNR", "CRCL", "SAP", "TDOC"] and len(asked) == 915 + 8
assert (res["coverage"]["universe"], res["coverage"]["extra"], res["coverage"]["requested"]) == (915, 8, 923)
assert FX["preopen_coverage"]["requested"] == 925 == 917 + len(outside)                               # РЕАЛНО 11.11 — преди поправката (с CART и NWE)
res["coverage"]["universe_source"] = "cache"
bb = copy.deepcopy(B19); bb["preopen"] = res
bb["deals_pending_scan"] = [{"ticker": t, "buyer": v.get("buyer"), "announced": v.get("announced")} for t, v in sorted(screener.LAST_SCAN_EXCLUDED.items())]
with q():
    page = render.render_dashboard(bb, publish=False)
assert "(универсът на скенерите 915, както сутринта + 8 извън него — наблюдаваните, картите и книгите)" in page and "Висящи сделки — извън карето: CART, NWE." in page
line = page[page.index("<b>Висяща сделка — извън скенерите</b>"):][:400]
assert page.count("<b>Висяща сделка — извън скенерите</b>") == 2 and "CART (" in line and "NWE (" in line                         # QM и GLB
assert page.index('<section id="qm">') < page.index("Висяща сделка — извън скенерите") < page.index('<section id="qm-ep">')
print("  ✓ CART и NWE не се теглят в 15:05 (и картата CART от QM, и записът в книгата); „Премаркет за … (универсът на скенерите 915 … + 8)“; редът в QM и GLB")
print("\n✅ test_universe_deals: всичко мина")
