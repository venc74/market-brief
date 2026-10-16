"""
16.10.2026 · В8 (трети преглед): distribution days — статус ok / partial / failed; при провал на единия индекс — изрично (етикет, банер, ред в "Запас до смяна на режима");
при провал на двата — карта "не се изтеглиха днес", банер и ред в запаса (до 16.10 картата изчезваше без дума, а провалът на единия даваше тихо броене само по другия).

РЕАЛНО: tests/fixtures/ohlc_SPY_2026-10-07.csv и ohlc_QQQ_2026-10-07.csv (Yahoo, до 07.10.2026); tests/fixtures/brief_2026-10-15.json — термометърът и страницата като рамка.
СИНТЕТИЧНО (маркирано): провалите на тегленето (празна история / изключение), подмененото теглене.
Пускане: python test_distribution_status.py
"""
import sys, re, json, copy, pathlib, tempfile, io, contextlib, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_ddst_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import entry_timing as et, data_warnings, regime_claims as rc, render

H = {s: pd.read_csv(ROOT / "tests" / "fixtures" / f"ohlc_{s}_2026-10-07.csv", index_col=0, parse_dates=True) for s in ("SPY", "QQQ")}
B15 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-15.json").read_text(encoding="utf-8"))

def evaluate(fail=()):
    """fail — кои индекси "не се изтеглят" (СИНТЕТИЧНО): 'QQQ' → празна история, 'SPY!' → изключение."""
    order = ["SPY", "QQQ"]
    def fetch(fn, *a, **k):
        sym = order.pop(0)
        if sym + "!" in fail:
            raise RuntimeError("Yahoo timeout (СИНТЕТИЧНО)")
        return pd.DataFrame() if sym in fail else H[sym]
    real = et.net_utils.fetch_with_timeout
    et.net_utils.fetch_with_timeout = fetch
    try:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            r = et.evaluate_distribution_days()
    finally:
        et.net_utils.fetch_with_timeout = real
    return r, dict(et.LAST_STATUS), out.getvalue()

print("── 1. ok / partial / failed (РЕАЛНИТЕ барове до 07.10) ──")
ok, st_ok, _ = evaluate()
assert (ok["spy_count"], ok["qqq_count"], ok["fetch_status"], ok["missing"], st_ok["status"]) == (7, 3, "ok", [], "ok"), (ok, st_ok)          # = брифът от 08.10 (SPY 7 / QQQ 3)
pq, st_pq, log = evaluate(fail=("QQQ",))
assert (pq["spy_count"], pq["qqq_count"], pq["count"], pq["fetch_status"], pq["missing"]) == (7, None, 7, "partial", ["QQQ"]) and st_pq["status"] == "partial"
assert pq["label"].endswith("· QQQ не се изтегли днес — само по SPY") and "QQQ не се изтегли — броенето е само по SPY" in log
ps, st_ps, _ = evaluate(fail=("SPY!",))
assert ps["spy_count"] is None and ps["qqq_count"] == 3 and st_ps["missing"] == ["SPY"] and "RuntimeError" in st_ps["errors"]["SPY"]
nf, st_f, log_f = evaluate(fail=("SPY", "QQQ"))
assert nf is None and st_f["status"] == "failed" and st_f["missing"] == ["SPY", "QQQ"] and "нито SPY, нито QQQ" in log_f
print("  ✓ двата: SPY 7, QQQ 3 (= брифът от 08.10); QQQ липсва → само по SPY, етикетът го казва; SPY хвърля → QQQ продължава; двата → None + статус failed")

print()
print("── 2. банерът и запасът до смяна на режима ──")
w = lambda st: [x["message"] for x in data_warnings.collect(None, None, dd_status=st)]
assert w(st_ok) == [] and w(st_pq) == ["Distribution days: QQQ не се изтегли днес — броят и блокът на Offensive са само по SPY."]
assert w(st_f) == ["Distribution days: нито SPY, нито QQQ не се изтеглиха днес — броят и блокът на Offensive не са проверени (липсата не е нечервен ден)."]
th = B15["thermometer"]
assert any("distribution days SPY 7/9 (QQQ не се изтегли днес)" in p for p in rc.margin(th, pq, st_pq)["parts"])
assert "distribution days: не се изтеглиха днес (нито SPY, нито QQQ) — блокът на Offensive не е проверен" in rc.margin(th, None, st_f)["parts"]
assert not any("distribution" in p for p in rc.margin(th, None, None)["parts"])                  # без статус (стар бриф) — както преди
print("  ✓ банер при partial и failed (нищо при ok); запасът казва кой индекс липсва / че блокът не е проверен")

print()
print("── 3. картата (РЕАЛНИЯТ бриф от 15.10 като рамка) ──")
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
b = copy.deepcopy(B15); b["distribution_days"] = None; b["distribution_days_status"] = st_f
assert "Distribution Days (подобно на IBD) — не се изтеглиха днес (нито SPY, нито QQQ)" in flat(render.render_dashboard(b))
b2 = copy.deepcopy(B15); b2["distribution_days"] = pq; b2["distribution_days_status"] = st_pq
assert "QQQ не се изтегли днес — само по SPY" in flat(render.render_dashboard(b2))
b3 = copy.deepcopy(B15); b3["distribution_days"] = None
assert "не се изтеглиха днес" not in flat(render.render_dashboard(b3))
print("  ✓ failed → карта '— не се изтеглиха днес'; partial → етикетът; стар бриф без статус — както преди")
print("\n✅ test_distribution_status: всичко мина")
