"""
27.11.2026 (уикенд пакет, т. 13): премаркетът тегли ПЪРВО отворените позиции и записите в книгите, картите, наблюдаваните и сутрешните EP — после универса. На 27.11 преди срива
липсваха WST, RGA, GHC, AHR, TNL, LIVN, ALLE (бяха в последните партиди след 915-те тикъра на универса).

РЕАЛНО: тикърите от „Без премаркет цена“ на 27.11 (WST, RGA, GHC, AHR, TNL, LIVN, ALLE) като записи в книгите. СИНТЕТИЧНО (означено): универсът и наблюдаваният.
Пускане: python run_tests.py test_preopen_order
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, pathlib, io, contextlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_porder_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import preopen

BOOK = ["WST", "RGA", "GHC", "AHR", "TNL", "LIVN", "ALLE"]
UNIV = [f"U{i:03d}" for i in range(900)] + ["ALLE"]                                                      # СИНТЕТИЧНО: универсът (ALLE е и в него)
asked = []
with contextlib.redirect_stdout(io.StringIO()):
    preopen.run(dt.datetime(2026, 11, 27, 14, 5, tzinfo=dt.timezone.utc), fetch5=lambda ts: (asked.extend(ts), {})[1], brief={},
                records=[{"ticker": t, "status": "open"} for t in BOOK], watched=["ANT"], universe=UNIV, market_fn=None, weights_fn=None)
print("── първо книгите и наблюдаваните, после универсът ──")
assert asked[:8] == BOOK + ["ANT"], asked[:10]
assert asked.count("ALLE") == 1 and len(asked) == 900 + 8
print(f"  ✓ първите 8: {', '.join(asked[:8])}; после {len(asked) - 8} от универса")
print("\n✅ test_preopen_order: всичко мина")
