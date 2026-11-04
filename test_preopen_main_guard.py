"""
04.11.2026 · четвърти преглед, Н1: обновяването преди отварянето — повреден data/<дата>.json на сутрешния бриф не сваля стъпката с traceback (до 04.11 json.loads беше извън try):
записът data/preopen/<дата>.json се прави, страницата не се рендерира (без сутрешен бриф), изходът е 0, когато премаркетът се изтегли.

РЕАЛНО: tests/fixtures/preopen_2026-11-03.json.gz (5-минутните бари с премаркет — бележката в test_preopen).
СИНТЕТИЧНО (означено): повреденият JSON, „сега“ (09:05 Ню Йорк), подменените build_universe / fetch_5m / skip_reason / имейл, EDGAR и заглавията (без мрежа — гърмят).
Пускане: python test_preopen_main_guard.py
"""
import sys, json, gzip, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_preguard_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import preopen, screener, emailer

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "preopen_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
frames = {t: pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"], "Volume": b["v"]}, index=pd.to_datetime(b["t"], utc=True)) for t, b in FX["bars_5m"].items()}
NOW = dt.datetime(2026, 11, 3, 14, 5, tzinfo=dt.timezone.utc)                   # СИНТЕТИЧНО

print("── повреден сутрешен бриф → стъпката минава, без страница ──")
(config.DATA_DIR / "2026-11-03.json").write_text('{"date": "2026-11-03", "thermometer": ', encoding="utf-8")      # СИНТЕТИЧНО: отрязан файл
orig = (screener.build_universe, preopen.fetch_5m, preopen.skip_reason, emailer.send_brief)
out = io.StringIO()
try:
    screener.build_universe = lambda: list(frames)
    preopen.fetch_5m = lambda tickers: {t: frames[t] for t in tickers if t in frames}
    preopen.skip_reason = lambda now: None
    emailer.send_brief = lambda html, subj: True
    with contextlib.redirect_stdout(out):
        code = preopen.main(NOW)
finally:
    screener.build_universe, preopen.fetch_5m, preopen.skip_reason, emailer.send_brief = orig
assert code == 0, code
assert "сутрешният бриф за 2026-11-03 не се прочете (JSONDecodeError" in out.getvalue(), out.getvalue()[-500:]
assert (config.DATA_DIR / "preopen" / "2026-11-03.json").exists() and not (config.DOCS_DIR / "index.html").exists()
print("  ✓ ред ::warning::, data/preopen/2026-11-03.json е записан, страницата не е пипната, изход 0")
print("\n✅ test_preopen_main_guard: всичко мина")
