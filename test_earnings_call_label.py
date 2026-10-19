"""
19.10.2026 · етап 2, т. 11: AI полето earnings_call на Action картата беше под етикет "Препоръка" — това е бележка на модела (датата и предупреждението за отчета са от кода).
Сега: "Бележка на AI за отчета", и само когато има текст.

РЕАЛНО: tests/fixtures/brief_2026-10-16.json — Action картата на EXPD ("преди earnings — next_earnings е на 03.11, days_to_earnings=18; …"). СИНТЕТИЧНО: картата без полето.
Пускане: python test_earnings_call_label.py
"""
import sys, re, json, copy, pathlib, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_ecall_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import render

B16 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
call = B16["action"][0]["ai"]["earnings_call"]
assert B16["action"][0]["ticker"] == "EXPD" and call.startswith("преди earnings — next_earnings е на 03.11")
page = flat(render.render_dashboard(copy.deepcopy(B16)))
assert f"Бележка на AI за отчета {call[:40]}" in page and "Препоръка преди earnings" not in page
b = copy.deepcopy(B16); b["action"][0]["ai"].pop("earnings_call")                                              # СИНТЕТИЧНО: без полето
assert "Бележка на AI за отчета" not in flat(render.render_dashboard(b))
print("  ✓ EXPD 16.10: 'Бележка на AI за отчета преди earnings — …' (беше 'Препоръка'); без текст — без ред")
print("\n✅ test_earnings_call_label: всичко мина")
