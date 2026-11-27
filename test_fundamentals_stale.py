"""
27.11.2026 (уикенд пакет, т. 6): празен Yahoo .info (24.11: 33 от 42) — последните известни фундаменти от кеша с датата („от 25.11“); заглавният ред казва истината
(проверени · днес от Yahoo · от кеша · последните известни · без данни); отворена позиция никога не изпада от радара заради грешка в данните — остава с „данни липсват“.
На 24.11 RGA, TGT, USFD излязоха от радара („фундаментите не се изтеглиха днес“), а RGA и USFD са живи в книгите.

РЕАЛНО: tests/fixtures/fund_cache_2026-11-27.json — записите на RGA и USFD от кеша (Yahoo .info, 25.11). СИНТЕТИЧНО (означено): празният .info и датата след отчета им.
Пускане: python run_tests.py test_fundamentals_stale
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, io, contextlib, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_fstale_")
config.DATA_DIR = pathlib.Path(_tmp.name); config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"; config.DOCS_DIR.mkdir()
from src import screener, render

CACHE = json.loads((ROOT / "tests" / "fixtures" / "fund_cache_2026-11-27.json").read_text(encoding="utf-8"))["tickers"]


class EmptyTicker:                                                                                      # СИНТЕТИЧНО: празен .info, както на 24.11
    def __init__(self, s): self.info = {}


def run(tickers, today, live):
    orig = screener.yf.Ticker
    screener.yf.Ticker = EmptyTicker
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return screener.fundamental_screen([{"ticker": t, "price": 100.0} for t in tickers], today=today, cache=copy.deepcopy(CACHE), live=live)
    finally:
        screener.yf.Ticker = orig


print("── 1. изтекъл запис (отчетът мина) + празен .info → последните известни, с датата ──")
D = dt.date(2027, 2, 20)                                                                               # СИНТЕТИЧНО: след отчетите на RGA и USFD
assert not screener.fund_cache_valid(CACHE["RGA"], D) and screener.fund_cache_stale(CACHE["RGA"], D)
out = run(["RGA", "USFD", "TGT"], D, live={"USFD"})
by = {r["ticker"]: r for r in out}
assert all(by[t]["fundamentals_asof"] == "2026-11-25" for t in ("RGA", "USFD") if t in by), by
assert "TGT" not in by and screener.LAST_FUNDAMENTALS["TGT"]["result"] == "unavailable"                  # без кеш и без позиция — не е оценен
fc = screener.LAST_STATUS["fundamentals_cache"]
assert fc["stale"] == 2 and fc["missing_kept"] == 0
print(f"  ✓ RGA, USFD — от кеша на 25.11 ({', '.join(sorted(by))} минават / отпадат по критериите); TGT — без данни")

print("── 2. отворена позиция без кеш — остава с „данни липсват“ ──")
out2 = run(["TGT"], D, live={"TGT"})
assert [r["ticker"] for r in out2] == ["TGT"] and out2[0]["data_missing"].startswith("данни липсват")
assert screener.LAST_STATUS["fundamentals_cache"]["missing_kept"] == 1
print(f"  ✓ TGT — «{out2[0]['data_missing']}»")

print("── 3. заглавният ред — истината ──")
st = {"fundamentals_checked": 42, "fundamentals_not_checked": {"n": 0, "max": 60, "top": []}, "fundamentals_unavailable": ["A", "TGT"],
      "fundamentals_cache": {"hits": 9, "requests": 33, "stored": 0, "stale": 31, "missing_kept": 1}}          # СИНТЕТИЧНО: 24.11 по новото правило
line = render.fundamentals_note(st)
assert line == "Фундаменти: проверени 42 · днес от Yahoo 0 · от кеша 9 · последните известни (стар кеш) 31 · без данни 2 (A, TGT); от тях с отворена позиция — остават с „данни липсват“: 1.", line
row = render.radar_reason({**out2[0], "setup": {}})
assert "⚠ данни липсват" in row
print(f"  ✓ «{line}»")
print("\n✅ test_fundamentals_stale: всичко мина")
