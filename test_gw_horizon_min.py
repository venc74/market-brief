"""
23.11.2026 (пакет 23.11, т. 9): „GLB по Уиш“ — доходността N сесии след входа без записите от сделки и средната само при N ≥ config.GLB_WISH_HORIZON_MIN_N; иначе
„малко данни (N)“. На 23.11 редът казваше „20 сесии — +5.52% (SPY −9.50%, алфа +15.02%), 1 записа“ — единственият запис беше CART (цел на придобиване: цената следва офертата).

РЕАЛНО: tests/fixtures/gw_book_2026-11-23.json — всичките 31 записа на книгата glb_wish_high от data/backtest_tracker.json към 23.11 (CART — сделка, отворен; NWE — приключила
сделка). СИНТЕТИЧНО (означено): по-малката книга за „малко данни (3)“.
Пускане: python run_tests.py test_gw_horizon_min
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, re, io, contextlib, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_gwmin_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import backtest, render
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"

FX = json.loads((ROOT / "tests" / "fixtures" / "gw_book_2026-11-23.json").read_text(encoding="utf-8"))
REC = FX["records"]


def summary(records: dict) -> dict:
    backtest._TRACKER_PATH.write_text(json.dumps(records), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        return backtest.get_glb_wish_summary(backtest.CATEGORY_GLB_WISH_HIGH)


print("── 1. РЕАЛНО (23.11): без CART и NWE ──")
assert config.GLB_WISH_HORIZON_MIN_N == 5
assert REC["CART_2026-10-26_gwh"]["deal"] and "20" in REC["CART_2026-10-26_gwh"]["horizons"]
s = summary(REC)
assert s["horizon_deals_excluded"] == 2 and s["horizon_min_n"] == 5
assert s["horizons"]["20"]["n_exec"] == 0, s["horizons"]["20"]                                         # до 23.11 — 1 (CART)
n10, n5 = s["horizons"]["10"]["n_exec"], s["horizons"]["5"]["n_exec"]
assert n10 == 19 and n5 == 26, (n5, n10)                                                                # до 23.11 — 20 и 27 (с CART; NWE — и тогава извън, приключила)
print(f"  ✓ 20 сесии — 0 записа (беше 1 — CART); 10 сесии — {n10} (беше 20); 5 сесии — {n5} (беше 27)")


def line(sm: dict) -> str:
    B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
    b = copy.deepcopy(B)
    b.setdefault("backtest", {})["glb_wish_high"] = sm
    with contextlib.redirect_stdout(io.StringIO()):
        html = render.render_dashboard(b, publish=False)
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    i = t.index("Доходност N сесии след входа")
    return t[i:i + 400]


print("── 2. страницата ──")
L = line(s)
assert "без записите от сделки (2)" in L and "20 сесии — още няма записи с толкова сесии" in L and re.search(r"10 сесии — [+-]\d+\.\d\d% \(SPY", L), L
small = {k: v for k, v in REC.items() if k in sorted(k for k, v in REC.items() if "10" in (v.get("horizons") or {}) and not v.get("deal"))[:3]}   # СИНТЕТИЧНО: 3 записа
L3 = line(summary(small))
assert "10 сесии — малко данни (3)" in L3 and "5 сесии — малко данни (3)" in L3, L3
print(f"  ✓ «{L[:150]}…»")
print(f"  ✓ малка книга: «{L3[L3.index('5 сесии'):L3.index('5 сесии') + 60]}…»")
print("\n✅ test_gw_horizon_min: всичко мина")
