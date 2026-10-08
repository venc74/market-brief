"""
Стоп и размер (07.10.2026) · src/trade_levels.py: вход, стоп, ADR, стоп % и предупреждения към всяко предложение за покупка. Размерът (брой акции) НЕ е тук — той е в браузъра (test_sizing_js.py).

РЕАЛНО: дневните барове на EXEL/AMD/TWLO/LNTH (tests/fixtures/ohlc_*.csv, Yahoo, свалени 02.10.2026; сигнални бардове 26.06 и 21.09), картата на EXPD от брифа на 05.10 и реалните барове на EXPD до
06.10, картите DOCN/CORT/CRL от QM скана към 02.10 (tests/fixtures/qm_frames_2026-10-02.json), реалният SYNA after-hours (tests/fixtures/qm_ep_2026-10-02.json). СИНТЕТИЧНО (маркирано): граничните
случаи на предупреждението за шум, стоп на тавана за EXPD (struct_low снижен), невалидни входове.
Проверява: (1) ADR% = 100×(средно high/low за 20 − 1), същата формула като qm_breakout и независимо смятана тук; (2) CANSLIM стопът е СЪЩИЯТ като в плана и в Track Record-а (ingest) и се
записва кое ниво е избрано; (3) Kullamägi: стоп = вход × (1 − ADR), очакван стоп 0.55×ADR като втори ред, без режимен фактор; (4) wiring през apply_hard_rules.
Пускане: python test_trade_levels.py
"""
import sys, json, copy, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import config
from src import screener, setup_rules, sizing, trade_levels as tl, qm_breakout as q, qm_ep, backtest
from src import main as brief_main

config.ENABLE_BACKTEST = False
FIX = ROOT / "tests" / "fixtures"


def adr_independent(high, low, n=20):
    """Независимо смятане: средно на (high/low − 1) × 100 за последните n бара (≠ кода в модула: цикъл, без numpy маски)."""
    s = 0.0
    for h, l in zip(list(high)[-n:], list(low)[-n:]):
        s += h / l - 1
    return 100 * s / n


print("── 1. ADR% ──")
exel_df = pd.read_csv(FIX / "ohlc_EXEL.csv", index_col=0, parse_dates=True).loc[:"2026-06-26"]
want = adr_independent(exel_df["High"], exel_df["Low"])
assert tl.adr_pct(exel_df["High"], exel_df["Low"]) == round(want, 2)
spy = pd.read_csv(FIX / "ohlc_SPY.csv", index_col=0, parse_dates=True)["Close"].loc[:"2026-06-26"]
row = screener._evaluate_technicals("EXEL", exel_df, spy)
assert row["adr_pct"] == round(want, 2), (row["adr_pct"], want)                       # screener-ът слага adr_pct на реда
print(f"  ✓ РЕАЛЕН EXEL (26.06): ADR20 = {row['adr_pct']}% (независимо смятане {want:.4f}); screener го слага на реда")
QMF = json.loads((FIX / "qm_frames_2026-10-02.json").read_text(encoding="utf-8"))
frames = {t: pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"])) for t, d in QMF["frames"].items()}
for t in ("DOCN", "CORT", "CRL", "AAPL"):
    f = frames[t]
    assert tl.adr_pct(f["High"], f["Low"]) == round(adr_independent(f["High"], f["Low"]), 2) == round(float(q.compute_features(f)["adr"][-1]), 2), t   # същата формула като в qm_breakout
print("  ✓ РЕАЛНИ DOCN/CORT/CRL/AAPL: същото число като qm_breakout.compute_features (формулата на qullamaggie.com/faq)")
exr = json.loads((FIX / "ohlc_EXPD_SPY_raw_2026-10-06.json").read_text(encoding="utf-8"))["bars"]["EXPD"]
i = exr["dates"].index("2026-10-02")
assert tl.adr_pct(exr["h"][:i + 1], exr["l"][:i + 1]) == 2.01
print("  ✓ РЕАЛЕН EXPD към 02.10: ADR20 = 2.01% (списъци вместо Series — също работи)")
assert tl.adr_pct([10, 11], [9, 10]) is None and tl.adr_pct([1.0] * 19, [1.0] * 19) is None            # СИНТЕТИЧНО: по-малко от 20 бара → не гадаем
bad = [10.0] * 20; badl = [9.0] * 19 + [0.0]
assert tl.adr_pct(bad, badl) is None and tl.adr_pct([10.0] * 19 + [float("nan")], [9.0] * 20) is None   # СИНТЕТИЧНО: low = 0 / NaN → None
print("  ✓ СИНТЕТИЧНО: < 20 бара, low = 0 или NaN → None (без гадаене)")

print()
print("── 2. CANSLIM: стопът е същият като в плана и в Track Record-а ──")
BR = json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
EXPD = {w["ticker"]: w for w in BR["watchlist"]}["EXPD"]
pv = sizing.buy_stop_preview(EXPD, 0.5, "2026-10-05")
lv = tl.canslim_levels(pv, 2.01, 0.5, "вход при задействане (buy-stop)")                    # 2.01 = РЕАЛНИЯТ ADR20 на EXPD към 02.10
assert (lv["strategy"], lv["entry"], lv["stop"], lv["stop_pct"], lv["adr_pct"], lv["regime_factor"]) == ("canslim", 194.59, 181.53, 6.71, 2.01, 0.5)
assert lv["stop_source"] == "structural" and lv["stop_source_text"] == "структурен: 15-барен low −1%" and lv["warnings"] == []
print(f"  ✓ РЕАЛНА EXPD карта: вход $194.59, стоп $181.53 (−6.71%), източник 'структурен: 15-барен low −1%', ADR 2.01%, без предупреждение (6.71 ≥ 0.5×2.01)")
capped = tl.canslim_levels(sizing.position_plan_v2({**EXPD, "struct_low": 178.0, "price": 194.59}, 1.0, "2026-10-05"), 2.01, 1.0, "референтен вход")
assert capped["stop_source"] == "cap" and capped["stop"] == 179.02 and capped["stop_pct"] == 8.0 and "таван 8% под входа" in capped["stop_source_text"]
print("  ✓ СИНТЕТИЧНО (struct_low снижен до $178): избраното ниво е таванът 8% → стоп $179.02 (−8.0%), източник 'cap'")
exel_plan = sizing.position_plan_v2(row, 1.0, dt.date(2026, 6, 29))
lx = tl.canslim_levels(exel_plan, row["adr_pct"], 1.0, "референтен вход (сигнален close)")
assert (lx["entry"], lx["stop"], lx["stop_pct"], lx["stop_source"]) == (54.77, 50.39, 8.0, "cap") and lx["stop"] == exel_plan["stop_loss"]
print(f"  ✓ РЕАЛЕН EXEL (29.06): вход $54.77, стоп $50.39 (−8.0%, таван), ADR {row['adr_pct']}%")
# предупреждение за шум — граници (СИНТЕТИЧНО)
assert tl.noise_warning(1.2, 3.0) == "стопът е в нормалния дневен шум (−1.2% при ADR 3.0%)"
assert tl.noise_warning(1.5, 3.0) is None and tl.noise_warning(1.49, 3.0) is not None and tl.noise_warning(5.0, None) is None and tl.noise_warning(0.4, 0) is None
pn = {**pv, "risk_pct": 1.2, "stop_loss": 192.25, "entry_mid": 194.59}
assert tl.canslim_levels(pn, 3.0, 1.0, "x")["warnings"] == ["стопът е в нормалния дневен шум (−1.2% при ADR 3.0%)"]
assert tl.canslim_levels(pn, None, 1.0, "x")["warnings"] == [] and tl.canslim_levels(pn, None, 1.0, "x")["adr_pct"] is None
print("  ✓ СИНТЕТИЧНО: стоп 1.2% при ADR 3.0% → 'стопът е в нормалния дневен шум'; точно на 0.5×ADR — без предупреждение; без ADR — без предупреждение, adr_pct = None")
assert tl.canslim_levels({"valid": False, "reason": "x"}, 2.0, 1.0, "x") is None and tl.canslim_levels(None, 2.0, 1.0, "x") is None
assert tl.canslim_levels({**pv, "stop_loss": 200.0}, 2.0, 1.0, "x") is None                      # стоп над входа → без нива
assert tl.for_candidate({"valid": True, "entry_mid": "x"}, {"ticker": "T"}, 1.0, "x") is None     # счупени данни не гърмят
print("  ✓ невалиден план / стоп над входа / счупени данни → None (картата няма нива, не гърми)")

print()
print("── 3. Същият стоп влиза в Track Record-а ──")
action_card = {"ticker": "EXEL", "plan": exel_plan, "levels": lx}
tr = {}
backtest._ingest_action_list(tr, "2026-06-29", [action_card])
assert [r["stop_loss"] for r in tr.values()] == [lx["stop"]] == [50.39]
buy_card = {"ticker": "EXPD", "setup": EXPD["setup"], "plan_preview": pv, "levels": lv}
tr2 = {}
config.BUYSTOP_TRACK_FROM = ""
backtest._ingest_buystop_list(tr2, "2026-10-05", [buy_card], "Defensive")
assert [r["stop_loss"] for r in tr2.values()] == [lv["stop"]] == [181.53]
print("  ✓ Action (EXEL): запис в Track Record-а stop_loss = 50.39 = стопът на картата; buy-stop книгата (EXPD): 181.53 = стопът на картата")

print()
print("── 4. Kullamägi: стоп = вход × (1 − ADR), очакван стоп 0.55×ADR ──")
rows, _ = q.scan_frames(frames, lead=QMF["lead"], max_dist_adr=2.0)  # РЕАЛНАТА карта DOCN от 02.10 е на 1.17 ADR от нивото; с правилото ≤1 ADR (08.10) не е карта — тук пазим и трите реални карти (старото определение ≤2 ADR) за рендера/книгата
by = {r["ticker"]: r for r in rows}
for t, (e, s, a, es) in {"DOCN": (151.83, 140.91, 7.19, 145.82), "CORT": (120.51, 114.84, 4.71, 117.39), "CRL": (298.98, 289.48, 3.18, 293.75)}.items():
    L = by[t]["levels"]
    assert (L["entry"], L["stop"], L["adr_pct"], L["stop_pct"], L["expected_stop"]) == (e, s, a, a, es), (t, L)
    assert L["stop"] == by[t]["max_stop"] and L["expected_stop"] == by[t]["expected_stop"] and L["strategy"] == "kullamagi"
    assert L["stop_source_text"] == "стоп за оразмеряване (макс. 1×ADR)" and L["expected_stop_label"] == "очакван стоп (0.55×ADR)"
    assert L["stop_note"] == "ориентировъчен — реалният стоп е дъното на деня на влизане" and L["regime_factor"] == 1.0 and L["warnings"] == []
print("  ✓ РЕАЛНИ: DOCN вход $151.83 → стоп $140.91 (−7.19%), очакван $145.82; CORT $120.51 → $114.84 (−4.71%), $117.39; CRL $298.98 → $289.48 (−3.18%), $293.75")
assert tl.kullamagi_levels(0, 5, stop_adr=1.0, entry_label="x") is None and tl.kullamagi_levels(10, None, stop_adr=1.0, entry_label="x") is None and tl.kullamagi_levels(10, 150, stop_adr=1.0, entry_label="x") is None
print("  ✓ СИНТЕТИЧНО: вход 0 / без ADR / ADR ≥ 100% (стоп ≤ 0) → None")

EP = json.loads((FIX / "qm_ep_2026-10-02.json").read_text(encoding="utf-8"))
d = EP["daily"]["SYNA"]
daily = {"SYNA": pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))}
# РЕАЛНИЯТ ред на SYNA от 01.10 (after-hours 122.04 към официално затваряне 106.15); сесията и числата — от fixture-а
sess = "2026-10-01"
base = {"ticker": "SYNA", "session": sess, "prev_close": 106.15, "ah_price": 122.04, "gap_pct": 14.97}
e = qm_ep.enrich_gappers([base], daily)[0]
L = e["levels"]
assert L["entry"] == 122.04 and L["stop"] == e["max_stop"] and L["strategy"] == "kullamagi" and L["entry_label"] == "after-hours цена"
assert L["stop_pct"] == round(e["adr"], 2) and "expected_stop" not in L and not any(k in e for k in ("shares", "risk_usd", "total_investment", "pct_of_portfolio"))
print(f"  ✓ РЕАЛЕН SYNA (AH 01.10): вход = after-hours цената $122.04, стоп $ {L['stop']} (−{L['stop_pct']}%, 1×ADR); без очакван стоп; в реда няма брой акции")

print()
print("── 5. През apply_hard_rules: нивата на Action и Watchlist ──")
jun = {"ticker": "EXEL", **row, "sector": "Healthcare", "company": "EXEL Corp", "earnings": {"next_earnings": None, "days_to_earnings": None, "in_blackout": False},
       "options": {}, "short_view": {}, "ai": {"classification": "Action", "why_now": "тест", "catalysts": [], "risks": []}}
jun["setup"] = setup_rules.classify_setup(jun, dt.date(2026, 6, 29))
for regime, factor in (("Offensive", 1.0), ("Defensive", 0.5)):
    action, watch = brief_main.apply_hard_rules([copy.deepcopy(jun)], factor, regime)
    assert [a["ticker"] for a in action] == ["EXEL"]
    L = action[0]["levels"]
    assert (L["entry"], L["stop"], L["stop_pct"], L["stop_source"], L["regime_factor"]) == (54.77, 50.39, 8.0, "cap", factor) and L["entry_label"] == "референтен вход (сигнален close)"
    assert L["stop"] == action[0]["plan"]["stop_loss"] and L["adr_pct"] == row["adr_pct"]
print("  ✓ РЕАЛЕН EXEL става Action с levels (вход 54.77, стоп 50.39, режимен фактор 1.0 при Offensive / 0.5 при Defensive)")
cand = copy.deepcopy(EXPD); cand.pop("plan_preview", None); cand.pop("levels", None); cand["adr_pct"] = 2.01
action, watch = brief_main.apply_hard_rules([cand, copy.deepcopy({w["ticker"]: w for w in BR["watchlist"]}["FTNT"])], 0.5, "Defensive")
w = {x["ticker"]: x for x in watch}
assert w["EXPD"]["levels"]["entry_label"] == "вход при задействане (buy-stop)" and w["EXPD"]["levels"]["stop"] == 181.53 and w["EXPD"]["levels"]["adr_pct"] == 2.01
assert "levels" not in w["FTNT"] and "plan_preview" not in w["FTNT"]
print("  ✓ РЕАЛНА EXPD (Watchlist, buy-stop) получава нива; РЕАЛНАТА FTNT (твърде разтегната, без buy-stop) — не")
print("\n✅ test_trade_levels: всичко мина")
