"""
10.11.2026 (т. 6): UOV✓ иска и абсолютен минимум договори — обемът в прозореца на падежите ≥ config.UNUSUAL_OPTIONS_MARKER_MIN_CONTRACTS (500), по който и път
да е минало съотношението (кошница / история / абсолютните 2.0×). Реално: CPAY 10.11 — 0.44× OI над P90 на кошницата (0.4377), но 249 договора срещу OI 565.
Върху всичките 19 маркера от 14.10 насам: отпадат само AMG 14.10 (68) и CPAY 10.11 (249); най-малкият оставащ е ROKU 28.10 (1 680).

РЕАЛНО: tests/fixtures/uov_min_contracts_2026-11-10.json — 19-те маркера (бележките от брифовете), uov_diag от 10.11, историята на LLY.
СИНТЕТИЧНО (означено): т. 1 — кошница с праг 0 (всяко съотношение минава — проверява се само минимумът); т. 3 — заместители на мрежовите стъпки.
Пускане: python test_uov_min_contracts.py
"""
import sys, json, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_uovmin_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import unusual_options as uo

FX = json.loads((ROOT / "tests" / "fixtures" / "uov_min_contracts_2026-11-10.json").read_text(encoding="utf-8"))
M = FX["markers"]
assert config.UNUSUAL_OPTIONS_MARKER_MIN_CONTRACTS == 500

print("── 1. РЕАЛНО: 19-те маркера от 14.10 насам с минимума 500 договора ──")
open_basket = {"p": 0.0, "ratios": {"X": 0.0}}                                       # СИНТЕТИЧНО: праг 0 — проверява се само минимумът
gone = [(m["date"], m["ticker"], m["contracts"]) for m in M if not uo.marker_decision(m["ticker"], m["ratio"], open_basket, [], contracts=m["contracts"])["marked"]]
assert len(M) == 19 and gone == [("2026-10-14", "AMG", 68), ("2026-11-10", "CPAY", 249)], gone
kept = sorted(m["contracts"] for m in M if m["contracts"] >= 500)
assert kept[0] == 1680 and [m["ticker"] for m in M if m["contracts"] == 1680] == ["ROKU"]
assert all(f"Обем {m['contracts']:,} / OI" in m["note"] for m in M)                  # договорите са обемът от бележката (прозорецът на падежите)
print(f"  ✓ отпадат {gone}; остават 17, най-малкият — ROKU 28.10 с 1 680 договора")

print("── 2. РЕАЛНО: CPAY и LLY на 10.11 ──")
D = FX["uov_diag_2026_11_10"]
assert D["decisions"]["CPAY"]["marked"] and D["decisions"]["LLY"]["marked"] and D["basket"]["p"] == 0.4377   # така излязоха на 10.11
basket = {"p": D["basket"]["p"], "ratios": D["ratios"]}
cp = uo.marker_decision("CPAY", 0.4407, basket, [], contracts=249)
ll = uo.marker_decision("LLY", 0.4468, basket, list(FX["history_lly"].values()), contracts=37657)
assert (cp["marked"], cp["mode"], cp["thin"]) == (False, "day", 249) and ll["marked"] and "thin" not in ll
ab = uo.marker_decision("CPAY", 2.5, {}, [], contracts=249)                          # абсолютният път (2.0×) — същият минимум
assert ab["marked"] is False and ab["thin"] == 249 and uo.marker_decision("CPAY", 2.5, {}, [])["marked"] is True       # без договори (стар извикващ) — както преди
print("  ✓ CPAY 0.44× (над P90 0.4377), 249 договора → без UOV✓; LLY 37 657 → с UOV✓; и по абсолютния път")

print("── 3. candidate_markers: diag['thin'] и лога ──")
A = {"CPAY": {"call_vol": 112, "put_vol": 137, "total_vol": 249, "ratio": 0.4407, "why": "", "used": ["2026-11-20"], "dropped": [], "oi_used": 565},
     "LLY": {"call_vol": 17322, "put_vol": 20335, "total_vol": 37657, "ratio": 0.4468, "why": "", "used": ["2026-11-20"], "dropped": [], "oi_used": 84279}}
saved = (uo._snapshot_for_yesterday, uo.reference_basket, uo._analysis_memo, uo.load_ratio_history, uo.save_ratio_history)
uo._snapshot_for_yesterday = lambda today: ({"tickers": {}, "fetched_at_utc": "x"}, "2026-11-09", "")
uo.reference_basket = lambda *a, **k: {"reference": 60, "valid": 60, **basket, "median": 0.2, "reason": "", "stopped": False, "missing": {}}
uo._analysis_memo = lambda sym, *a, **k: A[sym]
uo.load_ratio_history = lambda *a, **k: {"LLY": FX["history_lly"]}
uo.save_ratio_history = lambda *a, **k: None
try:
    with contextlib.redirect_stdout(io.StringIO()) as log:
        mk, diag = uo.candidate_markers(["CPAY", "LLY"], dt.date(2026, 11, 10))
finally:
    uo._snapshot_for_yesterday, uo.reference_basket, uo._analysis_memo, uo.load_ratio_history, uo.save_ratio_history = saved
assert list(mk) == ["LLY"] and diag["thin"] == {"CPAY": 249} and diag["decisions"]["CPAY"]["thin"] == 249 and diag["min_contracts"] == 500
assert "CPAY: 0.44× OI минава прага, но обемът е 249 договора (< 500) — без UOV✓" in log.getvalue()
print("  ✓ маркер само за LLY; CPAY в diag['thin'] и в лога")
print("\n✅ test_uov_min_contracts: всичко мина")
