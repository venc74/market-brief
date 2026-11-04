"""
04.11.2026 · четвърти преглед, С3: покритието на обновяването преди отварянето — ред „Премаркет за N от M тикъра“ винаги, „частично“ при паднала партида, непълен универс или
под config.PREOPEN_MIN_PM_SHARE от поисканите с бари в премаркета. До 04.11 ok = „поне един тикър“ и карето казваше „Нищо за отбелязване … в универса“ и при 5 от 918.
  1. coverage() — чиста функция;
  2. run върху РЕАЛНИТЕ 5-минутни бари (5 тикъра) при 20 поискани → „частично“, карето и имейлът го казват;
  3. main(): универсът не се зареди (Wikipedia) → банерът в карето, обновяването върви за картите / книгите / наблюдаваните; без мрежа и без имейл.

РЕАЛНО: tests/fixtures/preopen_2026-11-03.json.gz (5-минутни бари с премаркет — бележката в test_preopen); tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): „сега“ (09:05 Ню Йорк), поисканите тикъри без бари (Z01…), подменените build_universe / fetch_5m / имейл, LAST_FETCH с паднала партида.
Пускане: python test_preopen_coverage.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_precov_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import preopen, render, screener, emailer

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "preopen_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
NOW = dt.datetime(2026, 11, 3, 14, 5, tzinfo=dt.timezone.utc)                   # СИНТЕТИЧНО: 09:05 Ню Йорк
q = lambda: contextlib.redirect_stdout(io.StringIO())
frames = {t: pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"], "Volume": b["v"]}, index=pd.to_datetime(b["t"], utc=True)) for t, b in FX["bars_5m"].items()}
boom = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("x"))

print("── 1. coverage() ──")
assert preopen.coverage({"requested": 930, "with_pm": 682}, {"batches": 10, "batches_failed": 0}) == \
    {"with_pm": 682, "requested": 930, "batches": 10, "batches_failed": 0, "partial": False, "reason": None}                  # 03.11 — РЕАЛНИТЕ числа
c = preopen.coverage({"requested": 930, "with_pm": 600}, {"batches": 10, "batches_failed": 2})
assert c["partial"] and c["reason"] == "2 от 10 партиди не се изтеглиха", c
c = preopen.coverage({"requested": 930, "with_pm": 100}, {}, "универсът е непълен — Nasdaq-100: 0 тикъра")
assert c["reason"] == "премаркет само за 100 от 930 тикъра; универсът е непълен — Nasdaq-100: 0 тикъра", c
print("  ✓ 682 от 930 — пълно; паднали партиди / под прага / непълен универс — „частично“ с причината")

print("── 2. run: 5 тикъра с премаркет от 20 поискани ──")
uni = list(frames) + [f"Z{i:02d}" for i in range(1, 16)]                          # СИНТЕТИЧНО: 15 без бари
with q():
    res = preopen.run(NOW, frames5=frames, brief={}, records=[], watched=[], universe=uni, daily_fn=boom, filings_fn=boom, headlines_fn=boom)
assert res["ok"] and res["coverage"]["partial"] and res["coverage"]["reason"] == "премаркет само за 5 от 20 тикъра", res["coverage"]
b = copy.deepcopy(B19); b["preopen"] = res
with q():
    page = render.render_dashboard(b, publish=False)
box = page[page.index('<section class="preopen"'):page.index("</section>", page.index('<section class="preopen"'))]
assert "Премаркет за 5 от 20 тикъра." in box and "⚠ Частично: премаркет само за 5 от 20 тикъра — празното НЕ значи, че няма гапове." in box
assert "Частично: премаркет само за 5 от 20 тикъра" in preopen.email_html(res)
print("  ✓ карето: „Премаркет за 5 от 20“ и „Частично“; имейлът — също")

print("── 3. main(): универсът не се зареди → банер, обновяването върви ──")
sent = []
orig = (screener.build_universe, preopen.fetch_5m, preopen.skip_reason, emailer.send_brief)
try:
    screener.build_universe = boom
    preopen.fetch_5m = lambda tickers: {t: frames[t] for t in tickers if t in frames}
    preopen.skip_reason = lambda now: None
    emailer.send_brief = lambda html, subj: sent.append(subj) or True
    (config.DATA_DIR / "2026-11-03.json").write_text(json.dumps(B19), encoding="utf-8")
    with q():
        preopen.main(NOW)
finally:
    screener.build_universe, preopen.fetch_5m, preopen.skip_reason, emailer.send_brief = orig
saved = json.loads((config.DATA_DIR / "preopen" / "2026-11-03.json").read_text(encoding="utf-8"))
assert saved["coverage"]["partial"] and "универсът не се зареди (TimeoutError)" in saved["coverage"]["reason"], saved["coverage"]
page = (config.DOCS_DIR / "index.html").read_text(encoding="utf-8")
assert "универсът не се зареди (TimeoutError) — проверени са само картите, книгите и наблюдаваните" in page
print("  ✓ data/preopen/<дата>.json и карето — „универсът не се зареди“; run-ът не пада")
print("\n✅ test_preopen_coverage: всичко мина")
