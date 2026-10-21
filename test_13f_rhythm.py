"""
21.10.2026 · етап 4, ритъм на данните (решение от 21.10): секциите за 13F са цели само в първия бриф след нов 13F на някой от мениджърите; в другите дни — един ред
„13F: последни 13F от ДД.ММ — следваща вълна около ДД.ММ“ и секциите са свити. Следващата вълна е срокът на текущото тримесечие (45 дни след края му, през почивни дни и празници).
Бриф без полето superinvestor_status.filings (всички отпреди 21.10), липсващ предишен бриф или провалено теглене → цели секции, както досега.

РЕАЛНО: tests/fixtures/thirteenf_filings_2026-10-21.json — датите на 13F от брифовете на 19, 20 и 21.10 (Egerton Capital подава нов 13F на 20.10, предишният е от 21.07);
tests/fixtures/brief_2026-10-19.json — реалният бриф (без новото поле) за страницата. СИНТЕТИЧНО (означено): статусът „failed“.
Пускане: python test_13f_rhythm.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_13fr_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import data_rhythm as r, render

FX = json.loads((ROOT / "tests" / "fixtures" / "thirteenf_filings_2026-10-21.json").read_text(encoding="utf-8"))["filings"]
st = lambda d: {"kind": FX[d]["kind"], "filings": FX[d]["filings"]}
prev = lambda d: {"superinvestor_status": st(d)}

print("── 1. реалните дати от 19–21.10 ──")
d20 = r.thirteenf_rhythm(st("2026-10-20"), prev("2026-10-19"), "2026-10-20")
d21 = r.thirteenf_rhythm(st("2026-10-21"), prev("2026-10-20"), "2026-10-21")
assert d20["compact"] and not d20["fresh"] and d20["latest"] == "2026-08-14" and d20["next_wave"] == "2026-11-16"
assert d20["text"] == "13F: последни 13F от 14.08 — следваща вълна около 16.11 (срокът е 45 дни след края на тримесечието)"
assert d21["fresh"] and not d21["compact"] and d21["new"] == ["Джон Армитидж · Egerton Capital"] and d21["text"] is None
d22 = r.thirteenf_rhythm(st("2026-10-21"), prev("2026-10-21"), "2026-10-22")
assert d22["compact"] and d22["text"].startswith("13F: последни 13F от 20.10 — следваща вълна около 16.11")
print("  ✓ 20.10 — без нов 13F: „последни 13F от 14.08 — следваща вълна около 16.11“; 21.10 — нов 13F на Egerton (20.10) → цели секции; 22.10 — пак ред, „последни 13F от 20.10“")

print()
print("── 2. без полето, без предишен бриф, провал (СИНТЕТИЧЕН статус „failed“) ──")
b19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
assert "filings" not in (b19.get("superinvestor_status") or {})
assert r.thirteenf_rhythm(st("2026-10-20"), b19, "2026-10-20")["compact"] is False                 # предишният бриф е отпреди полето
assert r.thirteenf_rhythm(st("2026-10-20"), None, "2026-10-20")["compact"] is False
assert r.thirteenf_rhythm({**st("2026-10-20"), "kind": "failed"}, prev("2026-10-19"), "2026-10-20")["compact"] is False
assert r.thirteenf_rhythm(b19.get("superinvestor_status"), prev("2026-10-19"), "2026-10-20")["compact"] is False
assert [r.next_13f_wave(d) for d in ("2026-11-16", "2026-11-17", "2027-01-05")] == ["2026-11-16", "2027-02-16", "2027-02-16"]
print("  ✓ цели секции без полето / без предишен бриф / при провал; вълните: 16.11.2026 (14.11 е събота), после 16.02.2027 (14.02 е неделя, 15.02 — Presidents' Day)")

print()
print("── 3. страницата (РЕАЛНИЯТ бриф от 19.10) ──")
q = lambda: contextlib.redirect_stdout(io.StringIO())
b = copy.deepcopy(b19); b["thirteenf_rhythm"] = d20
with q():
    page, page_old = render.render_dashboard(b), render.render_dashboard(copy.deepcopy(b19))
i = page.index("13F: последни 13F от 14.08")
assert page.index('<details class="si-full">') > i and page.index("Superinvestor Positions — Last 13F", i) > page.index('<details class="si-full">')
assert page.index("</details>", page.index('<details class="si-full">')) < page.index("Исторически архив")
assert "si-full" not in page_old and "последни 13F от" not in page_old
print("  ✓ редът и свитите секции за 13F; бриф без полето — както досега")
print("\n✅ test_13f_rhythm: всичко мина")
