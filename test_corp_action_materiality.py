"""
13.10.2026 · праг на същественост при корпоративни действия: изключване само при коефициент ≥ config.CORP_ACTION_MATERIAL_RATIO (1.10 ≈ отделени 9% от стойността); под прага — маркерът
от 09.10 (картата остава); записът в config.CORP_ACTIONS_KNOWN с "material": True е съществен независимо от коефициента (HON 29.06.2026: отделяне на Honeywell Aerospace + обратен сплит 1:2 =
един коефициент 0.9535 при ~48% отделена стойност).

РЕАЛНО: tests/fixtures/corp_actions_materiality_2026-10-13.json — Close и Stock Splits на J (1.01 на 16.05.2025, Amentum), SPGI (1.057 на 01.07.2026, Mobility Global), HON (0.9535 на 29.06.2026);
tests/fixtures/corp_actions_2026-10-13.json — CTVA (6.665 на 01.10.2026) и VYLR. СИНТЕТИЧНО (означено): редовете на модулите като {ticker}, датата "днес" за J (06.06.2025), подмененото теглене.
Пускане: python test_corp_action_materiality.py
"""
import sys, json, pathlib, io, contextlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_corpmat_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import corp_actions as ca

FX = {**json.loads((ROOT / "tests" / "fixtures" / "corp_actions_materiality_2026-10-13.json").read_text(encoding="utf-8"))["tickers"],
      **json.loads((ROOT / "tests" / "fixtures" / "corp_actions_2026-10-13.json").read_text(encoding="utf-8"))["tickers"]}


def series(v):
    sp = [(d, r) for d, r in zip(v["dates"], v["splits"]) if r]
    return {"dates": [d for d, _ in sp], "ratios": [r for _, r in sp], "close": pd.Series(v["close"], index=pd.to_datetime(v["dates"]))}


ALL = {t: series(v) for t, v in FX.items()}
fetch_ex = lambda ts: {t: ALL[t] for t in ts if t in ALL}                                                       # СИНТЕТИЧНО: подмяна на мрежата с РЕАЛНИТЕ серии
fetch_mark = lambda ts: {t: (ALL[t]["dates"], ALL[t]["ratios"]) for t in ts if t in ALL}


def ex(tickers, module, today):
    ca.reset()
    with contextlib.redirect_stdout(io.StringIO()):
        return ca.exclude([{"ticker": t} for t in tickers], module, today, fetch=fetch_ex)


print("── 1. is_material върху 18-те измерени събития (универсът, 2 г.) ──")
EV = [("CTVA", "2026-10-01", 6.665, True), ("MIDD", "2026-07-07", 1.243, True), ("SPGI", "2026-07-01", 1.057, False), ("HON", "2026-06-29", 0.9535, True), ("FDX", "2026-06-01", 1.241, True),
      ("SF", "2026-02-27", 1.5, False), ("BDX", "2026-02-10", 1.272, True), ("CMCSA", "2026-01-05", 1.067, False), ("FNF", "2025-12-17", 1.037, False), ("CBSH", "2025-12-02", 1.05, False),
      ("DD", "2025-11-03", 2.39, True), ("HON", "2025-10-30", 1.061, False), ("APG", "2025-07-01", 1.5, False), ("FTV", "2025-06-30", 1.327, True), ("J", "2025-05-16", 1.01, False),
      ("WDC", "2025-02-24", 1.323, True), ("LEN", "2025-01-21", 1.033, False), ("CBSH", "2024-12-03", 1.05, False)]
for t, d, r, want in EV:
    assert ca.is_material(t, r, d) is want, (t, d, r)
assert config.CORP_ACTION_MATERIAL_RATIO == 1.10 and not ca.is_material("HON", 0.9535, "2025-01-01")             # HON — само за датата от таблицата
print(f"  ✓ съществени ({sum(w for *_, w in EV)}): CTVA, MIDD, HON 29.06 (по таблицата), FDX, BDX, DD, FTV, WDC; под прага — SPGI, CMCSA, FNF, HON 30.10, J, LEN; точни — SF, APG, CBSH×2")

print()
print("── 2. CTVA (6.665) — изключена; HON 29.06 (0.9535) — изключена по таблицата; SPGI (1.057) — остава ──")
kept, out = ex(["CTVA", "HON", "SPGI"], "screener", "2026-10-13")
assert [e["ticker"] for e in out] == ["CTVA", "HON"] and [r["ticker"] for r in kept] == ["SPGI"]
hon = out[1]["text"]
assert hon.startswith("HON — изключена: отделяне на Honeywell Aerospace (HONA, 1 за 2 HON) заедно с обратен сплит 1:2 — Yahoo ги записва като един коефициент на 29.06;") and "+" not in hon.split(";")[1]
print("  ✓", hon)

print()
print("── 3. J (1.01) — маркер, не изключване (СИНТЕТИЧНА 'днес' 06.06.2025, 14 сесии след събитието) ──")
kept, out = ex(["J"], "screener", "2025-06-06")
assert out == [] and kept == [{"ticker": "J"}]
cards = [{"ticker": "J"}, {"ticker": "SPGI"}]
with contextlib.redirect_stdout(io.StringIO()):
    d = ca.annotate([cards], "2025-06-06", fetch=fetch_mark)
assert d["flagged"] == [{"ticker": "J", "date": "2025-05-16", "ratio": 1.01}] and cards[0]["corp_action"]["text"].startswith("⚠ корпоративно действие на 16.05 (коефициент 1.01")
assert "corp_action" not in cards[1]                                                                            # SPGI: събитието е след "днес"
with contextlib.redirect_stdout(io.StringIO()):
    d2 = ca.annotate([[{"ticker": "SPGI"}]], "2026-08-03", fetch=fetch_mark)                                   # СИНТЕТИЧНО: 23 сесии след 01.07.2026
assert [f["ticker"] for f in d2["flagged"]] == ["SPGI"]
print("  ✓ J остава в модула с маркер '⚠ корпоративно действие на 16.05 (коефициент 1.01 …'; SPGI (1.057) — същото в 60-те сесии след 01.07")

print()
print("── 4. точните корекции не се маркират ──")
c3 = [{"ticker": "SF"}]
with contextlib.redirect_stdout(io.StringIO()):
    ca.annotate([c3], "2026-03-10", fetch=lambda ts: {"SF": (["2026-02-27"], [1.5])})                          # СИНТЕТИЧНО: 3 за 2
assert "corp_action" not in c3[0]
print("  ✓ 1.5 (3 за 2) — без маркер")

print()
print("── 5. main: маркерът се вика след изключването ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src.index("corp_actions.exclude(qm_rows") < src.index("corp_actions.annotate([action, watchlist, glb_candidates, qm_cards], today)") < src.index('"corp_actions": corp_diag')
print("  ✓")
print()
print("Всички тестове минаха.")
