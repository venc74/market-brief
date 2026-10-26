"""
26.10.2026 · етап 4б, т. 2 (решение от 26.10): етикет „събитие/M&A“ и за слухове — скок ≥ 8% при обем ≥ 3× средния (50 сесии) в деня на сигнала / сетъпа / входа И заглавие за продажба,
придобиване или сливане около деня (src/event_label.py). Записите остават; статистиката на книгите — с тях и без тях (backtest.events_block); групите по обем при входа — без "deal" / "event".

Случаят (РЕАЛЕН): CART — първият запис в новата книга „GLB по Уиш“ (сигнал 23.10): +9.2% при 4.4× обем; заглавията: „Instacart Is Exploring a Sale, and Uber and DoorDash Are Circling“.
Измерено 26.10 върху 53-те записа в книгите: условието за цена и обем — само CART; най-близкият — R (Ryder, 22.10) +10.5% при 2.3× (под прага за обема).

РЕАЛНО: tests/fixtures/event_cart_2026-10-23.json — записите на CART и R, дневните им барове от Yahoo и заглавията от Google News за CART около 23.10 (свалени 26.10).
СИНТЕТИЧНО (означено): записите на buy-stop книгата в т. 4 и подмененото теглене / новините.
Пускане: python test_event_label.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_event_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import event_label as el, backtest, render
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
q = lambda: contextlib.redirect_stdout(io.StringIO())

FX = json.loads((ROOT / "tests" / "fixtures" / "event_cart_2026-10-23.json").read_text(encoding="utf-8"))
BARS = {s: pd.DataFrame({"Close": v["c"], "Volume": v["v"]}, index=pd.to_datetime(v["dates"])) for s, v in FX["bars"].items()}
NEWS = FX["news"]
assert (config.EVENT_JUMP_PCT, config.EVENT_VOL_X, config.ENABLE_EVENT_LABEL) == (8, 3, True)

print("── 1. скокът в деня (РЕАЛНИ барове) ──")
j_cart, j_r = el.jump(BARS["CART"]["Close"], BARS["CART"]["Volume"], "2026-10-23"), el.jump(BARS["R"]["Close"], BARS["R"]["Volume"], "2026-10-22")
assert j_cart[0] == 9.21 and 4.0 <= j_cart[1] <= 5.0 and el.is_jump(j_cart)
assert j_r[0] >= 8 and j_r[1] < 3 and not el.is_jump(j_r)                                              # R (Ryder): скок, но обемът под 3×
assert el.jump(BARS["CART"]["Close"], BARS["CART"]["Volume"], "2026-10-25") is None                    # неделя — няма бар
print(f"  ✓ CART 23.10: {j_cart[0]:+.2f}% при {j_cart[1]:.1f}× → скок; R 22.10: {j_r[0]:+.1f}% при {j_r[1]:.1f}× → не (обем)")

print()
print("── 2. заглавията (РЕАЛНИТЕ от Google News около 23.10) ──")
allitems = [x for v in NEWS.values() for x in v]
heads = el.ma_headlines(allitems)
assert any("Exploring a Sale" in h["title"] or "Explores Sale" in h["title"] for h in heads) and any("sell itself" in h["title"] for h in heads)
assert not any("officer" in h["title"].lower() or "shares are proposed for sale" in h["title"] for h in heads)
for t in ("24,060 shares are proposed for sale by Maplebear (CART) officer Chris Rogers under a trading plan. - Stock Titan",
          "Maplebear chief legal officer sells $937,934 in stock - Investing.com", "Maplebear Inc. (CART) Stock Forecasts - Yahoo Finance"):
    assert el.ma_headlines([{"title": t}]) == []                                                       # РЕАЛНИ заглавия от 26.10 — не са за продажба на компанията
assert "after%3A2026-10-20+before%3A2026-10-25" in el._gnews_url('"CART" stock', "2026-10-23")
print(f"  ✓ {len(heads)} заглавия за продажба / сливане от {len(allitems)}; продажбите на акции от служители и прогнозите — не")

print()
print("── 3. етикетът върху записите (РЕАЛНИТЕ CART и R; теглене и новини от fixture-а) ──")
tr = copy.deepcopy(FX["records"])
assert tr["CART_2026-10-26_gwh"]["status"] == "pending" and el.record_days(tr["CART_2026-10-26_gwh"]) == ["2026-10-23"]      # GLB: входът е сигналният ден
seen = []
fetch = lambda url: (seen.append(url), NEWS.get(url, []))[1]
with q():
    st = el.label_records(tr, "2026-10-26", download=lambda ts: {t: BARS[t] for t in ts if t in BARS}, fetch=fetch, name_lookup=lambda t: "Maplebear Inc." if t == "CART" else None)
c = tr["CART_2026-10-26_gwh"]
assert st["ok"] and st["checked"] == 2 and st["jumps"] == 1 and st["labelled"] == ["CART"]
assert c["event"]["day"] == "2026-10-23" and c["event"]["ret_pct"] == 9.21 and c["event"]["headlines"] >= 2 and el.MA_RE.search(c["event"]["headline"])
assert "event" not in tr["R_2026-10-23_gw"] and tr["R_2026-10-23_gw"]["event_checked"] == "2026-10-26" and len(seen) == 2       # новини — само за скока (CART, двете заявки)
with q():
    st2 = el.label_records(tr, "2026-10-27", download=lambda ts: (_ for _ in ()).throw(AssertionError("не се тегли пак")), fetch=fetch)
assert st2["checked"] == 0                                                                               # проверен веднъж
buy = {"method": "v2", "category": "buystop", "ticker": "X", "entry_date": "2026-10-23", "status": "pending"}                      # СИНТЕТИЧНО: чакащ buy-stop
assert el.record_days(buy) is None
print(f"  ✓ CART → събитие/M&A «{c['event']['headline'][:70]}…»; R — проверен, без етикет; веднъж на запис; чакащ buy-stop — по-късно")

print()
print("── 4. статистиката с тях и без тях; групите по обем без тях (СИНТЕТИЧНИ записи на buy-stop книгата) ──")
mk = lambda t, r, ok, lab=None: {"method": "v2", "category": "buystop", "ticker": t, "entry_date": "2026-10-05", "status": "stopped", "fill_date": "2026-10-06", "realized_r": r,
                                 "entry_volume_ratio": 2.0 if ok else 1.0, "entry_volume_ok": ok, **({"event": {"day": "2026-10-06", "ret_pct": 9.0, "vol_x": 4.0, "headline": "X explores a sale"}} if lab == "event" else {}),
                                 **({"deal": {"buyer": "Fox Corporation"}} if lab == "deal" else {})}
recs = {"A_bs": mk("A", -1.0, True), "B_bs": mk("B", 2.0, True, "event"), "C_bs": mk("C", 0.5, False), "D_bs": mk("D", 3.0, False, "deal")}
ev = backtest.events_block(list(recs.values()), "realized_r")
assert ev["n"] == 2 and [l["kind"] for l in ev["labels"]] == ["event", "deal"] and (ev["n_all"], ev["avg_all"], ev["n_rest"], ev["avg_rest"]) == (4, 1.12, 2, -0.25)
g = backtest.entry_volume_groups(list(recs.values()), True)
assert (g["high"], g["low"], g["excluded"], g["high_avg_r"], g["low_avg_r"]) == (1, 1, 2, -1.0, 0.5)
assert backtest.events_block([mk("A", -1.0, True)], "realized_r") is None
print(f"  ✓ средно R с тях {ev['avg_all']:+.2f} (4) · без тях {ev['avg_rest']:+.2f} (2); групите по обем — без двата етикетирани")

print()
print("── 5. книгата „GLB по Уиш“ и страницата ──")
c.update(status="open", fill_date="2026-10-23", fill_price=56.44, return_pct=-4.28, return_pct_exec=-4.0, last_close=54.03)        # СИНТЕТИЧНО: състоянието след резолюцията
backtest._save_tracker({"CART_2026-10-26_gwh": c})
config.TRACK_GLB_WISH_HIGH = True
S = backtest.get_glb_wish_summary(backtest.CATEGORY_GLB_WISH_HIGH)
assert S["events"]["n"] == 1 and S["events"]["labels"][0]["ticker"] == "CART" and S["events"]["n_rest"] == 0 and S["events"]["avg_all"] == -4.28
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19); b.setdefault("backtest", {})["glb_wish_high"] = S
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", render.render_dashboard(b, publish=False))))
assert "С етикет (цената следва сделка или слух за сделка, не сетъпа): CART 26.10 — събитие/M&A (+9.2% при" in page and "Средно доходност %: с тях -4.28 (1) · без тях — още няма." in page
print("  ✓ „С етикет …: CART 26.10 — събитие/M&A (+9.2% при 4.x× обем на 23.10: «…»). Средно доходност %: с тях −4.28 (1) · без тях — още няма.“")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.index('steps.step("event_labels"') < src.index("backtest_summary = backtest.get_backtest_summary()") and src.index("backtest.update_backtest_tracker(") < src.index('steps.step("event_labels"')
print("  ✓ main: етикетите — след записа и резолюцията, преди обобщенията на книгите")
print("\n✅ test_event_label: всичко мина")
