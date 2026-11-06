"""
06.11.2026 (пакет 05–06.11, т. 6): секторната карта — колона „Днес“ (абсолютната промяна за деня) и изречението отгоре: при SPY ≤ −2% за деня и мнозинство сектори надолу — „широка разпродажба;
относително най-слабо засегнати: …“ вместо „ротация“. Реално, сесията от 05.11: SPY −4.41%, 11 от 11 надолу, а брифът от 06.11 казваше „широка ротация извън мега-технологиите“.

РЕАЛНО: tests/fixtures/market_day_2026-11-05.json — затварянията от Yahoo (бележката там); tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): кратките редове в т. 2.
Пускане: python test_sector_day.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_sectorday_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import sector_layer as sl, render

FX = json.loads((ROOT / "tests" / "fixtures" / "market_day_2026-11-05.json").read_text(encoding="utf-8"))
DF = pd.DataFrame(FX["close"], index=pd.to_datetime(FX["index"])).tail(126)
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))

print("── 1. РЕАЛНО, 05.11: колоната и изречението ──")
b = sl.sector_board(download=lambda syms: DF, universe_sector={}, trend={}, ratings={}, earnings_fn=lambda s, t: {}, today=DF.index[-1].date())
day = {r["etf"]: r["chg_1d_pct"] for r in b["sectors"]}
assert b["spy_1d_pct"] == -4.41 and len(day) == 11 and all(v < 0 for v in day.values()) and day["XLK"] == -8.0
for e, v in day.items():
    assert v == round((DF[e].iloc[-1] / DF[e].iloc[-2] - 1) * 100, 2), e
s = b["summary"]
assert "широка разпродажба (SPY -4.4% за деня, надолу 11 от 11); относително най-слабо засегнати: Комуникации (-0.6%), Комунални услуги (-0.7%) и Потребителски (защитни) (-0.8%)" in s, s
assert "ротация" not in s and config.SECTOR_BROAD_TEXT not in s
print(f"  ✓ {s}")

print("── 2. границите (СИНТЕТИЧНО) ──")
rows = lambda *v: [{"etf": f"E{k}", "sector": f"С{k}", "chg_1d_pct": x, "word": "отслабва"} for k, x in enumerate(v)]
assert sl.selloff_text(rows(-1, -2, 1), -1.99) is None                                                # SPY над прага
assert "надолу 2 от 3" in sl.selloff_text(rows(-1, -2, 1), -2.0)                                      # точно на прага; мнозинство
assert sl.selloff_text(rows(-1, 1), -3.0) is None and sl.selloff_text(rows(-1, -1, 1, 1), -3.0) is None   # половината не е мнозинство
assert sl.selloff_text(rows(-1), None) is None and sl.selloff_text([{"etf": "A", "sector": "С"}], -3.0) is None     # стар ред без промяна
assert "С0 (-1.0%), С2 (-2.0%) и С1 (-3.0%)" in sl.selloff_text(rows(-1, -3, -2, -4), -3.0)            # трите с най-малък спад
assert "ротация" in sl.board_summary(rows(-1, -2, -3), -1.0) and "разпродажба" not in sl.board_summary(rows(-1, -2, -3))     # без данни / обикновен ден — както досега
print("  ✓ SPY −2.0% — да, −1.99% — не; половината сектори — не; без дневни данни — както досега")

print("── 3. страницата: колона „Днес“; стар бриф — тире ──")
bb = copy.deepcopy(B19); bb["sector_board"] = b
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
sec = page.split("Секторна карта · кои сектори водят", 1)[1].split("</section>", 1)[0]
assert '<span>Днес</span>' in sec and 'data-l="Днес"' in sec and '<span class="neg">-8.0%</span>' in sec and sec.count('data-l="Днес"') == 11
old = copy.deepcopy(b); [r.pop("chg_1d_pct") for r in old["sectors"]]
bb["sector_board"] = old
with contextlib.redirect_stdout(io.StringIO()):
    sec2 = render.render_dashboard(bb, publish=False).split("Секторна карта · кои сектори водят", 1)[1].split("</section>", 1)[0]
assert sec2.count('data-l="Днес" class="wt-num"><span class="wt-mu">—</span>') == 11
print("  ✓ колоната е в таблицата (11 реда, отрицателните — червени); стар бриф без полето — „—“")
print("\n✅ test_sector_day: всичко мина")
