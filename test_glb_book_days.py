"""
06.11.2026 (пакет 05–06.11, т. 11): книгата „GLB по Уиш“ — в обобщаващия ред до броя записи и независимите дни на сигнала, защото 14 от първите 20 записа бяха от два дни (04.11 и 29.10).

РЕАЛНО: tests/fixtures/glb_book_days_2026-11-06.json — датите на сигнала на 21-те записа в книгата към 06.11 (data/backtest_tracker.json); tests/fixtures/glb_book_2026-11-03.json.gz и brief_2026-10-19.json — страницата.
СИНТЕТИЧНО (означено): запис без signal_date и единственият ден в т. 2.
Пускане: python test_glb_book_days.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, re, html as htmllib, collections
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_glbdays_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import backtest, render

D = json.loads((ROOT / "tests" / "fixtures" / "glb_book_days_2026-11-06.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
q = lambda: contextlib.redirect_stdout(io.StringIO())


def summary(records):
    real = backtest._load_tracker
    backtest._load_tracker = lambda: records
    try:
        with q():
            return backtest.get_glb_wish_summary(backtest.CATEGORY_GLB_WISH_HIGH)
    finally:
        backtest._load_tracker = real


rec = lambda k, day, sig=True: {"method": "v2", "category": backtest.CATEGORY_GLB_WISH_HIGH, "ticker": f"T{k}", "entry_date": day, "status": "pending", **({"signal_date": day} if sig else {})}

print("── 1. РЕАЛНО: 21 записа към 06.11 ──")
tr = {f"T{i}": rec(i, d) for i, d in enumerate(D["signal_dates"])}
S = summary(tr)
count = collections.Counter(D["signal_dates"])
assert S["records"] == 21 and S["days"] == 8 and count.most_common(2) == [("2026-11-04", 9), ("2026-10-29", 5)]
print(f"  ✓ {S['records']} записа · {S['days']} дни; най-много: {count.most_common(2)}")

print("── 2. границите (СИНТЕТИЧНО) ──")
assert summary({"a": rec(1, "2026-11-02", sig=False), "b": rec(2, "2026-11-02")})["days"] == 1            # без signal_date — по датата на записа
assert summary({})["enabled"] in (True, False)
print("  ✓ запис без дата на сигнала — по датата на записа")

print("── 3. страницата: редът на книгата ──")
b = copy.deepcopy(B19); b.setdefault("backtest", {})["glb_wish_high"] = S
with q():
    page = flat(render.render_dashboard(b, publish=False))
assert "21 записа · 8 дни" in page
one = copy.deepcopy(S); one.update(records=2, days=1, tickers=2)
b["backtest"]["glb_wish_high"] = one
with q():
    assert "2 записа · 1 ден" in flat(render.render_dashboard(b, publish=False))
print("  ✓ „21 записа · 8 дни“; „2 записа · 1 ден“")
print("\n✅ test_glb_book_days: всичко мина")
