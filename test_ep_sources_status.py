"""
04.11.2026 · четвърти преглед, С1: 8-K (EDGAR) и заглавията (Yahoo RSS) — „не се провери“ ≠ „няма“. До 04.11 провалът на тегленето връщаше [] и карето преди отварянето казваше
„без 8-K и без заглавие за компанията досега“ (сутрешната EP карта — „Неясен катализатор“ без бележка).
  1. qm_ep.catalyst_sources: провал / None → празен списък + причината; успех → данните, без причина;
  2. обновяването преди отварянето върху РЕАЛНИТЕ 5-минутни бари (LSCC, AEIS — 03.11): провалени EDGAR и заглавия → filings_error / headlines_error, страницата и имейлът
     казват „не се провери“, не „без 8-K“;
  3. сутрешният EP: sources_note на реда и бележката към модела.

РЕАЛНО: tests/fixtures/preopen_2026-11-03.json.gz (5-минутните бари с премаркет, 8-K-тата на LSCC и AEIS след затварянето на 02.11 — бележката в test_preopen);
tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): „сега“ (09:05 Ню Йорк), подменените EDGAR / заглавия / дневни функции (хвърлят грешка или връщат None).
Пускане: python test_ep_sources_status.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_epsrc_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import qm_ep, preopen, render

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "preopen_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
NOW = dt.datetime(2026, 11, 3, 14, 5, tzinfo=dt.timezone.utc)                   # СИНТЕТИЧНО: 09:05 Ню Йорк
q = lambda: contextlib.redirect_stdout(io.StringIO())
frames = {t: pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"], "Volume": b["v"]}, index=pd.to_datetime(b["t"], utc=True)) for t, b in FX["bars_5m"].items()}
since = dt.datetime(2026, 11, 1)


def boom(*a, **k):
    raise TimeoutError("SEC")


print("── 1. catalyst_sources ──")
with q():
    s1 = qm_ep.catalyst_sources("LSCC", "2026-11-02", since, filings_fn=boom, headlines_fn=lambda t, s: None)
assert s1 == {"filings_8k": [], "filings_error": "EDGAR: TimeoutError", "headlines_raw": [], "headlines_error": "Yahoo RSS: не се провериха"}, s1
assert qm_ep.sources_note(s1) == "8-K: не се провери (EDGAR: TimeoutError) · заглавия: не се провериха (Yahoo RSS: не се провериха)"
s2 = qm_ep.catalyst_sources("LSCC", "2026-11-02", since, filings_fn=lambda t, s, now_utc=None: [], headlines_fn=lambda t, s: [{"title": "x"}], now_utc=NOW)
assert s2["filings_error"] is None and s2["headlines_error"] is None and s2["headlines_raw"] == [{"title": "x"}] and qm_ep.sources_note(s2) is None
print("  ✓ провал → празно + причината; проверено и празно → без причина")

print("── 2. преди отварянето — РЕАЛНИТЕ бари, провалени EDGAR и заглавия ──")
with q():
    res = preopen.run(NOW, frames5=frames, brief={}, records=[], watched=[], daily_fn=boom, filings_fn=boom, headlines_fn=boom)
g = {r["ticker"]: r for r in res["gaps"]}
assert set(g) == {"LSCC", "AEIS"}, set(g)
assert g["LSCC"]["filings_error"] == "EDGAR: TimeoutError" and g["LSCC"]["headlines_error"] == "Yahoo RSS: TimeoutError", g["LSCC"]
b = copy.deepcopy(B19); b["preopen"] = res
with q():
    page = render.render_dashboard(b, publish=False)
box = page[page.index('<section class="preopen"'):page.index("</section>", page.index('<section class="preopen"'))]
assert box.count("8-K: не се провери (EDGAR: TimeoutError)") == 2 and box.count("заглавия: не се провериха (Yahoo RSS: TimeoutError)") == 2, box
assert "без 8-K и без заглавие" not in box
mail = preopen.email_html(res)
assert mail.count("8-K: не се провери (EDGAR: TimeoutError)") == 2
print("  ✓ карето и имейлът: „8-K: не се провери“ при LSCC и AEIS (реално и двете имат 8-K 2.02), без „без 8-K и без заглавие“")

print("── 3. проверено и празно → „без 8-K и без заглавие“, както досега ──")
with q():
    res2 = preopen.run(NOW, frames5=frames, brief={}, records=[], watched=[], daily_fn=boom, filings_fn=lambda t, s, now_utc=None: [], headlines_fn=lambda t, s: [])
b = copy.deepcopy(B19); b["preopen"] = res2
with q():
    page2 = render.render_dashboard(b, publish=False)
assert page2.count("без 8-K и без заглавие за компанията досега") == 2 and "не се провери" not in page2[page2.index('<section class="preopen"'):page2.index("</section>", page2.index('<section class="preopen"'))]
print("  ✓ двата източника отговориха празно → старият ред")

print("── 4. сутрешният EP: бележката към модела ──")
row = {"ticker": "LSCC", "headlines": [], "filings_8k": [], "filings_error": "EDGAR: TimeoutError"}
prompt = qm_ep._build_prompt([row])
assert "не се провери (EDGAR не отговори) — липсата НЕ значи, че няма 8-K" in prompt
print("  ✓ моделът знае, че 8-K не е проверен")
print("\n✅ test_ep_sources_status: всичко мина")
