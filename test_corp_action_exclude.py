"""
13.10.2026 · корпоративно действие с нецял коефициент (отделяне) → ИЗКЛЮЧВАНЕ от модулите, чийто прозорец назад обхваща датата (решението от 09.10 "маркер, не изключване" отпада).

Случаят (РЕАЛЕН, брифът от 13.10): CTVA в GLB като "Classic", "пробив над историческия връх" +4.6% над линия $12.71 — юнското затваряне ~$85 ÷ 6.665 (оценката на Yahoo за отделянето на
Vylor на 01.10, 1 VYLR за 1 CTVA). Грешката на коефициента (+7.9% в деня при σ 1.6%) е по-голяма от "пробива".

РЕАЛНО: tests/fixtures/corp_actions_2026-10-13.json (Close и Stock Splits на CTVA и VYLR до 12.10 + GLB картата на CTVA от 13.10); tests/fixtures/corp_actions_2026-10-09.json (Close и Stock Splits
за 6 месеца към 09.10: FDX 1.241 на 01.06, MIDD 1.243 на 07.07, IESC/APH/MNST 2:1, CRWD 4:1, DD 1:3, P/BDX без събития). СИНТЕТИЧНО (означено): редовете на скрийнъра/QM като {ticker},
сплитът 3:2 и дивидентът в акции 1.05, датите извън прозорците, подмененото теглене.
Пускане: python test_corp_action_exclude.py
"""
import sys, json, pathlib, copy, re, tempfile, io, contextlib, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_corpex_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import corp_actions as ca, data_warnings, render

FX13 = json.loads((ROOT / "tests" / "fixtures" / "corp_actions_2026-10-13.json").read_text(encoding="utf-8"))
FX09 = json.loads((ROOT / "tests" / "fixtures" / "corp_actions_2026-10-09.json").read_text(encoding="utf-8"))["tickers"]
D = dt.date.fromisoformat


def series(v):
    sp = [(d, r) for d, r in zip(v["dates"], v["splits"]) if r]
    return {"dates": [d for d, _ in sp], "ratios": [r for _, r in sp], "close": pd.Series(v["close"], index=pd.to_datetime(v["dates"]))}


ALL = {**{t: series(v) for t, v in FX09.items() if t != "CTVA"}, **{t: series(v) for t, v in FX13["tickers"].items()}}
calls = []


def fake_fetch(tickers):                                                       # СИНТЕТИЧНО: подмяна на мрежата с РЕАЛНИТЕ серии от fixture-ите
    calls.append(list(tickers))
    return {t: ALL[t] for t in tickers if t in ALL}


def run(rows, module, today, fetch=fake_fetch):
    with contextlib.redirect_stdout(io.StringIO()):
        return ca.exclude(rows, module, today, fetch=fetch)


print("── 1. РЕАЛНАТА GLB карта на CTVA от 13.10 ──")
ca.reset()
card = FX13["glb_card_ctva"]
assert (card["prior_high_month"], card["line"], card["pct_vs_line"], card["glb_type"]) == ("2026-06", 12.71, 4.6, "classic")
kept, out = run([card, {"ticker": "P", "prior_high_month": "2026-03"}], "glb", "2026-10-13")
assert [r["ticker"] for r in kept] == ["P"] and [e["ticker"] for e in out] == ["CTVA"]
WANT = ("CTVA — изключена: отделяне на Vylor (1:1) на 01.10; историята преди датата е оценка на Yahoo (коефициент 6.665); "
        "CTVA + VYLR = $89.19 към 12.10 спрямо $77.65 преди (+14.9%); връща се, когато линията е от месец след 10.2026")
assert out[0]["text"] == WANT, out[0]["text"]
assert sorted(calls[0]) == ["CTVA", "P", "VYLR"]                               # новата компания се тегли в същата партида
print("  ✓", out[0]["text"])
print("    ($77.65 = затварянето на 30.09 по Yahoo $11.6504 × 6.665; $89.19 = CTVA $13.30 + VYLR $75.89 на 12.10)")

print()
print("── 2. прозорците на модулите ──")
ca.reset()
kept, out = run([{"ticker": t} for t in ("CTVA", "FDX", "MIDD", "P", "IESC", "APH", "MNST", "CRWD", "DD", "BDX")], "screener", "2026-10-13")   # СИНТЕТИЧНИ редове с РЕАЛНИТЕ серии
assert sorted(e["ticker"] for e in out) == ["CTVA", "FDX", "MIDD"] and sorted(r["ticker"] for r in kept) == ["APH", "BDX", "CRWD", "DD", "IESC", "MNST", "P"]
fdx = next(e for e in out if e["ticker"] == "FDX")
assert fdx["text"].startswith("FDX — изключена: корпоративно действие на 01.06 (нецял коефициент 1.241 — отделяне или сплит с нецял коефициент)") and "извън скрийнъра до" in fdx["text"]
print("  ✓ скрийнър (252 сесии): CTVA, FDX (1.241, 01.06), MIDD (1.243, 07.07) — изключени; 2:1, 4:1, 1:3 и без събитие — остават")
print("   ", fdx["text"])
ca.reset()
kept, out = run([{"ticker": t} for t in ("CTVA", "FDX", "MIDD")], "qm", "2026-10-13")
assert sorted(e["ticker"] for e in out) == ["CTVA", "FDX", "MIDD"]
_, out_late = run([{"ticker": "FDX"}], "qm", "2026-12-07")                                                  # СИНТЕТИЧНА дата: 130+ сесии след 01.06
assert out_late == [] and ca.sessions_since(D("2026-06-01"), D("2026-12-07")) >= config.CORP_ACTION_QM_SESSIONS
_, out_scr_late = run([{"ticker": "FDX"}], "screener", "2026-12-07")
assert [e["ticker"] for e in out_scr_late] == ["FDX"]                                                        # скрийнърът (252) още го държи вън
print("  ✓ QM (130 сесии): същите трима на 13.10; на 07.12 (СИНТЕТИЧНО) FDX се връща в QM, но не и в скрийнъра")
ca.reset()
_, out_g = run([{"ticker": "CTVA", "prior_high_month": "2026-11"}, {"ticker": "CTVA", "prior_high_month": "2026-10"}], "glb_wish", "2027-03-01")   # СИНТЕТИЧНИ линии след събитието
assert out_g == []
print("  ✓ GLB / книгата на Уиш: линия от 10.2026 или по-късно (след отделянето) — не се изключва")

print()
print("── 3. точни корекции (не се изключват) ──")
assert all(ca.is_exact_ratio(r) for r in (2, 4, 0.5, 1 / 3, 1.5, 1.25, 2 / 3)) and not any(ca.is_exact_ratio(r) for r in (6.665, 1.243, 1.241, 1.057, 1.327, 1.323, 2.39, 1.01, 1.05))
SYN = {"SF": {"dates": ["2026-02-27"], "ratios": [1.5], "close": pd.Series([100.0], index=pd.to_datetime(["2026-02-27"]))},          # СИНТЕТИЧНО: 3 за 2
       "CBSH": {"dates": ["2025-12-02"], "ratios": [1.05], "close": pd.Series([50.0], index=pd.to_datetime(["2025-12-02"]))}}       # СИНТЕТИЧНО: 5% дивидент в акции
ca.reset()
kept, out = run([{"ticker": "SF"}, {"ticker": "CBSH"}], "screener", "2026-10-13", fetch=lambda ts: {t: SYN[t] for t in ts if t in SYN})
assert out == [] and len(kept) == 2
print("  ✓ 3:2 (SF), 5:4, 2:3 — точни; CBSH (5% дивидент в акции, config.CORP_ACTION_EXACT_TICKERS) — остава; 6.665, 1.243, 1.241, 1.05, 1.01 — не са точни")

print()
print("── 4. graceful: провал на тегленето ──")
ca.reset()
rows = [{"ticker": "CTVA"}]
kept, out = run(rows, "screener", "2026-10-13", fetch=lambda ts: (_ for _ in ()).throw(RuntimeError("Yahoo down (СИНТЕТИЧНО)")))
assert kept == rows and out == [] and ca.LAST_DIAG["ok"] is False
w = data_warnings.collect(None, None, corp_diag=dict(ca.LAST_DIAG))
assert len(w) == 1 and "днес НИЩО не е изключено заради отделяне" in w[0]["message"]
print("  ✓ нищо не се изключва, диагностиката е ok=False → банер 'днес НИЩО не е изключено …'")

print()
print("── 5. редът под секцията (РЕАЛНИЯТ бриф от 05.10 като рамка) ──")
ca.reset()
_, ex = run([card], "glb", "2026-10-13")
b = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
b["corp_excluded"] = {"screener": [], "glb": ex, "qm": []}
page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b))))
assert "Изключени (корпоративно действие): " + WANT in page
glb_sec = page[page.index("GLB Watchlist · Green Line Breakout"):]
assert glb_sec.index("Изключени (корпоративно действие)") < 1500
b2 = copy.deepcopy(b); b2["glb_candidates"] = []; b2["glb_status"] = {"ok": True, "universe": 903, "with_history": 901, "batches_failed": 0}
page2 = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b2))))
assert "Няма GLB кандидати днес" in page2 and "Изключени (корпоративно действие): CTVA — изключена" in page2
print("  ✓ под GLB секцията (и когато друг кандидат няма): 'Изключени (корпоративно действие): CTVA — изключена: …'")

print()
print("── 6. main.run: изключването е преди AI и преди книгите; маркерът от 09.10 не се вика ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
i_scr = src.index('candidates, corp_ex_screener = corp_actions.exclude(candidates, "screener", today)')
assert i_scr < src.index("setup_rules.annotate(candidates") < src.index("ai_brief.ticker_narratives(")
i_glb, i_gw = src.index('glb_candidates, corp_ex_glb = corp_actions.exclude(glb_candidates, "glb", today)'), src.index('glb_wish_signals, corp_ex_gw = corp_actions.exclude(glb_wish_signals, "glb_wish", today)')
i_qm = src.index('qm_rows, corp_ex_qm = corp_actions.exclude(qm_rows, "qm", today)')
i_book = src.index("backtest.update_backtest_tracker(action, today, watchlist_before_expiry")
assert max(i_glb, i_gw, i_qm) < i_book and i_qm < src.index("qm_cards = qm_breakout.cards(")
assert "corp_actions.annotate(" not in src and '"corp_excluded": corp_excluded' in src
print("  ✓ скрийнър → преди setup_rules.annotate и AI; GLB, сигналите на Уиш и QM → преди записа в книгите; corp_actions.annotate (маркерът) вече не се вика")
print()
print("Всички тестове минаха.")
