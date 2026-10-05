"""
Допълнение към пакет 2 (2026-10-05): червени distribution days → режимът е най-много Defensive (никога Offensive), с причина в
regime_reason; Cash и Defensive не се променят. thermometer.apply_distribution_cap() върху резултата на build_thermometer;
main.py смята distribution days веднага след термометъра (преди макро брифа и режимния gate).

РЕАЛНО: брифовете от 22.09 (Offensive, SPY 10 / QQQ 6 — червено), 02.10 (Defensive по override, SPY 10 / QQQ 5 — червено),
20.08 (жълто: SPY 6 / QQQ 7) и 08.09 (зелено: SPY 6 / QQQ 5) от tests/fixtures; РЕАЛЕН EXEL (+1.56% над pivot, обем 2.49×) за
gate-а. СИНТЕТИЧНО: Cash/Defensive по броене, override-ът над Offensive по броене (22.09 със сменен режим), граничните броеве
8/9 (праг DISTRIBUTION_DAYS_RED=9), QQQ-само, липсващ индекс, +3% кандидат, изключеният превключвател.
Пускане: python test_distribution_cap.py
"""
import sys, json, copy, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import thermometer as th, entry_timing, setup_rules, screener, ai_brief
from src import main as brief_main

config.ENABLE_BACKTEST = False
FIX = ROOT / "tests" / "fixtures"
B = {d: json.loads((FIX / f"brief_{d}.json").read_text(encoding="utf-8")) for d in ("2026-09-22", "2026-10-02", "2026-08-20", "2026-09-08")}
T = lambda d: B[d]["thermometer"]
DD = lambda d: B[d]["distribution_days"]
assert (T("2026-09-22")["regime"], DD("2026-09-22")["status"], DD("2026-09-22")["spy_count"], DD("2026-09-22")["qqq_count"]) == ("Offensive", "red", 10, 6)

print("── РЕАЛЕН 22.09: Offensive + червени distribution days (SPY 10 / QQQ 6) ──")
src_t = T("2026-09-22")
before = copy.deepcopy(src_t)
out = th.apply_distribution_cap(src_t, DD("2026-09-22"))
assert src_t == before                                                              # входът не се мутира
assert out["regime"] == "Defensive" and out["sizing_factor"] == config.DEFENSIVE_SIZING_FACTOR == 0.5
assert out["regime_reason"] == src_t["regime_reason"] + " — distribution days червени (SPY 10/25, QQQ 6/25; праг 9) — Offensive блокиран"
cap = out["distribution_cap"]
assert cap["active"] and cap["changed_regime"] and (cap["spy_count"], cap["qqq_count"], cap["count"], cap["threshold"], cap["lookback"]) == (10, 6, 10, 9, 25)
assert cap["text"] == "distribution days червени (SPY 10/25, QQQ 6/25; праг 9) — Offensive блокиран (по броене: Offensive)"
assert "Режимът по броенето е Offensive" in out["exit_rule"] and "9 или повече (сега 10)" in out["exit_rule"]
assert th.apply_distribution_cap(out, DD("2026-09-22")) is out                         # идемпотентно: втори вик не дублира текста
assert out["regime_reason"].count("Offensive блокиран") == 1
print(f"  ✓ Offensive → Defensive, sizing 1.0 → 0.5; причина: '…{out['regime_reason'][-85:]}'")
print("  ✓ входният речник не се мутира; повторно прилагане е no-op")
print()

print("── без промяна: РЕАЛНИ 02.10 / 20.08 / 08.09 ──")
t02 = T("2026-10-02")
assert t02["regime_by_count"] == "Defensive" and DD("2026-10-02")["status"] == "red"
assert th.apply_distribution_cap(t02, DD("2026-10-02")) is t02                         # Defensive по броене + червено → нищо
assert th.apply_distribution_cap(T("2026-08-20"), DD("2026-08-20")) is T("2026-08-20")       # жълто
assert th.apply_distribution_cap(T("2026-09-08"), DD("2026-09-08")) is T("2026-09-08")       # зелено (Offensive остава)
assert T("2026-09-08")["regime"] == "Offensive"
print("  ✓ 02.10 (Defensive по override и по броене, червено), 20.08 (жълто), 08.09 (Offensive, зелено) → същият обект, без промяна")
print()

print("── СИНТЕТИЧНО: Cash, Defensive, празни данни, превключвател ──")
red = {"count": 12, "spy_count": 12, "qqq_count": 4, "status": "red", "label": "x"}
cash = {**copy.deepcopy(src_t), "regime": "Cash", "regime_by_count": "Cash"}
assert th.apply_distribution_cap(cash, red) is cash and "distribution_cap" not in cash          # Cash не се променя
dfn = {**copy.deepcopy(src_t), "regime": "Defensive", "regime_by_count": "Defensive"}
assert th.apply_distribution_cap(dfn, red) is dfn                                                # Defensive по броене — нищо
assert th.apply_distribution_cap(src_t, None) is src_t                                           # няма данни за distribution days
assert th.apply_distribution_cap(src_t, {**red, "status": "yellow"}) is src_t and th.apply_distribution_cap(src_t, {**red, "status": "green"}) is src_t
config.DISTRIBUTION_DAYS_BLOCKS_OFFENSIVE = False
assert th.apply_distribution_cap(src_t, red) is src_t                                            # изключен
config.DISTRIBUTION_DAYS_BLOCKS_OFFENSIVE = True
assert th.apply_distribution_cap({"regime": "Defensive", "unavailable": True, "regime_by_count": "Defensive"}, red)["regime"] == "Defensive"   # fallback термометър
print("  ✓ Cash и Defensive по броене → без промяна; None / жълто / зелено → без промяна; превключвателят изключва блока")

# Defensive по override при Offensive по броене: режимът не се мени, но причината казва, че Offensive е блокиран и без override
ov = {**copy.deepcopy(src_t), "regime": "Defensive", "regime_by_count": "Offensive", "sizing_factor": 0.5,
      "regime_reason": "MOVE: тест override", "exit_rule": "Override-ът пада, когато MOVE падне."}
o2 = th.apply_distribution_cap(ov, red)
assert o2["regime"] == "Defensive" and o2["sizing_factor"] == 0.5 and o2["distribution_cap"]["changed_regime"] is False
assert o2["regime_reason"].startswith("MOVE: тест override · distribution days червени (SPY 12/25, QQQ 4/25; праг 9)") and "и без override" in o2["regime_reason"]
assert o2["exit_rule"].startswith("Override-ът пада") and "Освен това: Distribution days блокират Offensive" in o2["exit_rule"]
print("  ✓ Defensive по override (Offensive по броене): режимът не се променя, но причината и exit_rule казват, че и без override Offensive е блокиран")
print()

print("── граница на прага (праг 9) през evaluate_distribution_days ──")
def dd(spy, qqq):
    entry_timing._count_distribution_days = lambda sym, lb: spy if sym == "SPY" else qqq
    return entry_timing.evaluate_distribution_days()
assert dd(8, 8)["status"] == "yellow" and th.apply_distribution_cap(src_t, dd(8, 8)) is src_t
at = th.apply_distribution_cap(src_t, dd(9, 3))
assert dd(9, 3)["status"] == "red" and at["regime"] == "Defensive" and "(SPY 9/25, QQQ 3/25; праг 9)" in at["regime_reason"]
qq = th.apply_distribution_cap(src_t, dd(3, 10))                                                  # червено само заради QQQ
assert qq["regime"] == "Defensive" and "(SPY 3/25, QQQ 10/25; праг 9)" in qq["regime_reason"]
only_spy = th.apply_distribution_cap(src_t, dd(9, None))                                         # QQQ не се изтегли
assert "(SPY 9/25; праг 9)" in only_spy["regime_reason"] and "QQQ" not in only_spy["regime_reason"]
assert dd(None, None) is None and th.apply_distribution_cap(src_t, dd(None, None)) is src_t
print("  ✓ 8 → жълто, без промяна; 9 → червено, блок; червено само от QQQ → и двата броя в текста; липсващ индекс → само наличния; без данни → без промяна")
print()

print("── gate и sizing надолу по веригата (РЕАЛЕН EXEL, СИНТЕТИЧЕН +3% кандидат) ──")
df = pd.read_csv(FIX / "ohlc_EXEL.csv", index_col=0, parse_dates=True).loc[:"2026-06-26"]
spy = pd.read_csv(FIX / "ohlc_SPY.csv", index_col=0, parse_dates=True)["Close"].loc[:"2026-06-26"]
exel = screener._evaluate_technicals("EXEL", df, spy)
D0 = dt.date(2026, 6, 29)
def cand(row, **over):
    c = dict(row)
    c.update({"company": c["ticker"] + " Corp", "sector": "Healthcare",
              "earnings": {"next_earnings": None, "days_to_earnings": None, "in_blackout": False},
              "options": {}, "short_view": {}, "ai": {"classification": "Action", "why_now": "тест", "catalysts": [], "risks": []}})
    c.update(over); c["setup"] = setup_rules.classify_setup(c, D0)
    return c
ext = cand({"ticker": "SYN3", "price": 103.0, "pivot": 100.0, "pct_from_pivot": 3.0, "volume_ratio": 2.0,
            "breakout_volume": True, "struct_low": 96.0})
real = cand(exel)
for regime, sizing in (("Offensive", 1.0), (out["regime"], out["sizing_factor"])):
    action, watch = brief_main.apply_hard_rules([copy.deepcopy(real), copy.deepcopy(ext)], sizing, regime)
    if regime == "Offensive":
        assert [a["ticker"] for a in action] == ["EXEL", "SYN3"] and not watch
        risk_off = {a["ticker"]: a["plan"]["max_risk_usd"] for a in action}
    else:
        assert [a["ticker"] for a in action] == ["EXEL"] and [w["ticker"] for w in watch] == ["SYN3"]
        assert watch[0]["ai"]["watchlist_reason_type"] == "regime_block" and "Режим Defensive" in watch[0]["ai"]["watchlist_trigger"]
        assert action[0]["plan"]["max_risk_usd"] == risk_off["EXEL"] / 2                            # риск ×0.5
        assert action[0]["plan"]["sizing_factor"] == 0.5
print("  ✓ при Offensive (sizing 1.0): РЕАЛЕН EXEL (+1.56%, 'good') и СИНТЕТИЧЕН +3% → 2 Action; при блока (Defensive, sizing 0.5):")
print(f"    EXEL остава Action с риск ${risk_off['EXEL'] / 2:,.0f} вместо ${risk_off['EXEL']:,.0f}, +3% отива във Watchlist 'regime_block'")
print()

print("── макро промптът и рендерът ──")
seen = {}
ai_brief._call_claude = lambda system, user, max_tokens=0: (seen.setdefault("u", user), json.dumps({"macro_brief": "x", "sector_logic": [], "regime_comment": "y"}))[1]
ai_brief.macro_and_sector_brief({}, [], out)
assert "червените distribution days" in seen["u"] and "блокират Offensive" in seen["u"]
seen.clear(); ai_brief.macro_and_sector_brief({}, [], src_t)
assert "червените distribution days" not in seen["u"]
import tempfile, html as htmllib
from src import render
# 22.09 е записан в стария формат (без counts) — шаблонът го показва през regime_reason; днешният формат (с counts) показва реда
# от distribution_cap над броенето: същият РЕАЛЕН термометър + СИНТЕТИЧНО добавени counts/regime_by_count/overrides
new_fmt = {**src_t, "counts": src_t["regime_reason"], "regime_by_count": "Offensive", "overrides": []}
out_new = th.apply_distribution_cap(new_fmt, DD("2026-09-22"))
assert out_new["regime_by_count"] == "Offensive" and out_new["regime"] == "Defensive"
brief = json.loads(json.dumps(B["2026-09-22"])); brief["thermometer"] = out
brief_new = json.loads(json.dumps(B["2026-09-22"])); brief_new["thermometer"] = out_new
with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
    o1, o2_ = config.DOCS_DIR, config.DATA_DIR
    config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
    try:
        dash = htmllib.unescape(render.render_dashboard(brief)); mail = htmllib.unescape(render.render_email(brief))
        plain = htmllib.unescape(render.render_dashboard(json.loads(json.dumps(B["2026-09-22"]))))
        dash_new = htmllib.unescape(render.render_dashboard(brief_new)); mail_new = htmllib.unescape(render.render_email(brief_new))
    finally:
        config.DOCS_DIR, config.DATA_DIR = o1, o2_
assert "distribution days червени (SPY 10/25, QQQ 6/25; праг 9) — Offensive блокиран" in dash and "Offensive блокиран" in mail
assert "Offensive блокиран" not in plain                                                              # същият бриф без блока (както е записан)
assert ">Defensive</div>" in dash
assert "⚡ distribution days червени (SPY 10/25, QQQ 6/25; праг 9) — Offensive блокиран (по броене: Offensive)" in dash_new   # ред в заглавието (формат с counts)
assert ">Defensive</div>" in dash_new and "Offensive блокиран" in mail_new
print("  ✓ макро промптът казва, че кодът е блокирал Offensive (само когато има блок); dashboard (ред в заглавието) и имейл показват причината")
print()

print("── main.py ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.count("entry_timing.evaluate_distribution_days()") == 1                                    # един fetch
i_dd, i_cap = src.index("entry_timing.evaluate_distribution_days()"), src.index("apply_distribution_cap(thermo, distribution_days)")
i_thermo, i_macro, i_hard = src.index("thermo = build_thermometer(macro)"), src.index("ai_brief.macro_and_sector_brief("), src.index("apply_hard_rules(candidates, thermo[")
assert i_thermo < i_dd < i_cap < i_macro < i_hard
seg = src[i_dd - 200:i_cap + 400]
assert seg.count("try:") >= 2 and seg.count("except Exception") >= 2
print("  ✓ термометър → distribution days (try/except) → apply_distribution_cap (try/except) → макро бриф → apply_hard_rules; един fetch")
print()
print("Всички тестове минаха.")
