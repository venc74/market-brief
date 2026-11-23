"""
23.11.2026 (пакет 23.11, т. 4): ден на пазарен гап — NQ ≥ ±3% или ES ≥ ±2% в 08:55 Ню Йорк (фючърсите в карето преди отварянето спрямо 16:00 на предишната сесия). Тогава: етикет в EP,
„Нови днес“ и книгите; EP гапът без собствена новина / 8-K — „пазарен ход“, не индивидуален сетъп; записите в книгите с вход или сигнал в такъв ден — етикет и статистиката с и без тях.

РЕАЛНО: tests/fixtures/market_gap_2026-11-23.json — карето от 23.11 (NQ +5.08%, ES +3.40%; 10 гапа с 8-K и заглавията) и фючърсите от всички карета 13.11–23.11;
tests/fixtures/gw_book_2026-11-23.json — записите на „GLB по Уиш“. СИНТЕТИЧНО (означено): датите на вход 23.11 върху два реални записа (книгите се резолвират на следващата сутрин).
Пускане: python run_tests.py test_market_gap
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, re, io, contextlib, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_mgap_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import market_gap as mg, backtest, render, preopen
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"

FX = json.loads((ROOT / "tests" / "fixtures" / "market_gap_2026-11-23.json").read_text(encoding="utf-8"))
P = FX["preopen_2311"]

print("── 1. РЕАЛНО: кой ден е ден на пазарен гап ──")
assert (config.MARKET_GAP_NQ_PCT, config.MARKET_GAP_ES_PCT) == (3.0, 2.0)
m = mg.classify(P["market"]["futures"])
assert m["gap"] and (m["nq"], m["es"], m["time_ny"]) == (5.08, 3.4, "08:55")
assert m["text"] == "ден на пазарен гап: NQ +5.08%, ES +3.40% в 08:55 Ню Йорк (фючърсите спрямо 16:00 на предишната сесия)"
hist = {d: mg.classify(f) for d, f in FX["futures_by_day"].items()}
assert [d for d, v in hist.items() if v and v["gap"]] == ["2026-11-23"] and sum(1 for v in hist.values() if v) == 7      # 7 дни с фючърси; преди 13.11 — неизвестни
assert mg.classify([{"symbol": "ES=F", "chg_pct": -2.1}])["gap"] and not mg.classify([{"symbol": "NQ=F", "chg_pct": 2.9}])["gap"]    # СИНТЕТИЧНО: праговете
assert mg.classify([]) is None
print(f"  ✓ 23.11 — {m['text'][:60]}…; 13.11–20.11 — не (най-много NQ +1.84% на 19.11)")

print("── 2. РЕАЛНО (23.11): EP гаповете без собствена новина / 8-K — пазарен ход ──")
gaps = copy.deepcopy(P["gaps"])
assert mg.mark_rows(gaps, m) == 8
assert [g["ticker"] for g in gaps if not g.get("market_move")] == ["NVDA", "DELL"]                     # NVDA — 8-K т. 5.02; DELL — заглавие за компанията
assert mg.mark_rows(copy.deepcopy(P["gaps"]), {**m, "gap": False}) == 0                                # не е ден на гап → нищо
print("  ✓ пазарен ход: " + ", ".join(g["ticker"] for g in gaps if g.get("market_move")) + " · собствена новина: NVDA (8-K), DELL")

print("── 3. карето, имейлът му и страницата в 15:05 ──")
res = {**copy.deepcopy(P), "gaps": gaps, "market_gap": m, "market_moves": 8}
em = preopen.email_html(res)
assert "⚠ ден на пазарен гап: NQ +5.08%" in em and em.count("(пазарен ход)") == 8
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B); b["preopen"] = res
EPF = json.loads((ROOT / "tests" / "fixtures" / "ep_facts_2026-11-23.json").read_text(encoding="utf-8"))
ep_row = copy.deepcopy(EPF["rows"]["ABNB"]["row"])                                                     # РЕАЛНИЯТ EP ред на ABNB (06.11) като основа
ep_row.update(ticker="SMCI", company="Super Micro Computer", filings_8k=[], headlines=[{"title": "Nasdaq's Worst Week Since 2020: 5 AI Tech Stocks to Buy on the Dip"}])   # СИНТЕТИЧНО: заглавието на SMCI от карето, без 8-K
b["qm_ep"] = {**(b.get("qm_ep") or {}), "rows": [ep_row]}
with contextlib.redirect_stdout(io.StringIO()):
    html = render.render_dashboard(b, publish=False)
t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
assert "⚠ ден на пазарен гап: NQ +5.08%, ES +3.40% в 08:55 Ню Йорк (фючърсите спрямо 16:00 на предишната сесия) — гаповете без собствена новина или 8-K са пазарен ход, не индивидуален сетъп (8 от 10)." in t
assert t.count("пазарен ход") >= 9 and "гаповете без собствена новина или 8-K са пазарен ход, не индивидуален сетъп: SMCI." in t
assert render.market_gap_day({"preopen": {"market_gap": {**m, "gap": False}}}) is None and render.market_gap_day({}) is None      # сутрин / ден без гап
print("  ✓ карето: ред и 8 белега; EP: ред и белег на SMCI; имейлът на карето — същото")

print("── 4. книгите: етикетът и статистиката с и без (СИНТЕТИЧНО: вход 23.11 на два реални записа) ──")
REC = copy.deepcopy(json.loads((ROOT / "tests" / "fixtures" / "gw_book_2026-11-23.json").read_text(encoding="utf-8"))["records"])
keys = sorted(k for k, v in REC.items() if v.get("return_pct_exec") is not None and not v.get("deal"))[:2]
real = sorted(k for k, v in REC.items() if "2026-11-23" in backtest.market_gap_dates(v))                  # РЕАЛНО: записът със сигнал на 23.11 (вход — на 24.11)
for k in keys:
    REC[k]["fill_exec_date"] = "2026-11-23"
backtest._TRACKER_PATH.write_text(json.dumps(REC), encoding="utf-8")
folder = config.DATA_DIR / "preopen"; folder.mkdir()
(folder / "2026-11-23.json").write_text(json.dumps(P), encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    st = backtest.apply_market_gap_labels("2026-11-24")
assert len(real) == 1 and st["ok"] and st["labelled"] == 2 + len(real) and st["gap_days"] == ["2026-11-23"], (real, st)
tr = json.loads(backtest._TRACKER_PATH.read_text(encoding="utf-8"))
assert all(tr[k]["market_gap"] == {"date": "2026-11-23", "nq": 5.08, "es": 3.4} for k in keys)
assert sum(1 for v in tr.values() if v.get("market_gap")) == 3 and tr[real[0]]["market_gap"]["date"] == "2026-11-23"
with contextlib.redirect_stdout(io.StringIO()):
    s = backtest.get_glb_wish_summary(backtest.CATEGORY_GLB_WISH_HIGH)
blk = s["market_gap"]
assert blk["n"] == 2 and blk["n_all"] - blk["n_rest"] == 2 and blk["avg_all"] is not None and blk["avg_rest"] is not None    # COST (реалният) — чака, още без резултат
b2 = copy.deepcopy(B); b2.setdefault("backtest", {})["glb_wish_high"] = s
with contextlib.redirect_stdout(io.StringIO()):
    t2 = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", render.render_dashboard(b2, publish=False)))
assert "Ден на пазарен гап (2):" in t2 and "(NQ +5.1%)" in t2 and "Среден резултат: с тях" in t2 and "ден на пазарен гап (23.11, NQ +5.1%)" in t2
print(f"  ✓ 3 етикета ({real[0]} — реален, сигнал на 23.11, чака; два — синтетични, с резултат); средно с тях {blk['avg_all']:+.2f}% ({blk['n_all']}) · без тях {blk['avg_rest']:+.2f}% ({blk['n_rest']})")

print("── 5. main: стъпката ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'steps.step("market_gap_labels", lambda: backtest.apply_market_gap_labels(today)' in src
print("  ✓")
print("\n✅ test_market_gap: всичко мина")
