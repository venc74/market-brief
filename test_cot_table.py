"""
03.11.2026 · разходката, т. 17: COT без AI. Седмична таблица от кода — Пазар · перцентил · позиция (текст) · цената потвърждава (да / не) + един ред със собствената статистика на модула;
видими — екстремумите (≤ 10 / ≥ 90); сгънато „▸ Всички 40 пазара“ по групи: валути (вкл. индекса на долара), лихви, индекси, крипто, суровини (вкл. WTI, злато). AI тезите
(повикванията, промптът, кешът data/cot_theses_cache.json) и списъците с тикъри са махнати; бележките „обратен залог“ — с тях (нямат вход). Седмичният ритъм остава.
Цената на тезите до 03.11 (брифовете, cot_diag): ~5.5–6 хил. изходни токена в деня на нов отчет (19.10: 6 008 · 26.10: 5 472 · 02.11: 5 635) + входните (~4 партиди × ~7 хил. знака).

РЕАЛНО: tests/fixtures/cot_all_2026-11-03.json.gz — сериите на 40-те пазара от data/cot_cache.json към 03.11 (отчет към 27.10) и екстремумите на брифа от 03.11; tests/fixtures/brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): кратката серия в т. 1.
Пускане: python test_cot_table.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cottable_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import cot, render

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "cot_all_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))

print("── 1. всички 40 пазара — перцентилът и посоката са същите като на екстремумите в брифа ──")
labels = [m for m, *_ in cot.MAJOR_MARKETS]
groups = [m for _, ms in config.COT_GROUPS for m in ms]
assert sorted(groups) == sorted(labels) and len(groups) == len(set(groups)) == 40                       # всеки пазар — точно в една група
assert [g for g, _ in config.COT_GROUPS] == ["валути", "лихви", "индекси", "крипто", "суровини"] and "US Dollar Index" in dict(config.COT_GROUPS)["валути"]
assert {"WTI Crude Oil", "Gold"} <= set(dict(config.COT_GROUPS)["суровини"])
rows = cot.all_markets(FX["series"])
assert len(rows) == 40 and [r["group"] for r in rows] == sorted((r["group"] for r in rows), key=[g for g, _ in config.COT_GROUPS].index)
ext = {e["market"]: e for e in FX["extremes_2026_11_03"]}
got = {r["market"]: r for r in rows if r["direction"]}
assert set(got) == set(ext) and len(got) == 17
for m, e in ext.items():
    assert (got[m]["percentile"], got[m]["direction"], got[m]["net_position"], got[m]["position_label"]) == (e["percentile"], e["direction"], e["net_position"], e["position_label"]), m
plain = [r for r in rows if not r["direction"]]
assert all(r["position_label"] in ("нетно дълги", "нетно къси") for r in plain) and len(plain) == 23
assert cot.all_markets({"X": [{"date": "2026-10-27", "net": 1}] * 5}) == []                              # СИНТЕТИЧНО: под 10 точки — без ред
print(f"  ✓ 40 пазара в 5 групи; 17 в екстремум — перцентилът, посоката и етикетът съвпадат с брифа от 03.11; 23 — „нетно дълги / къси“")

print()
print("── 2. страницата: видими — екстремумите; сгънато — всички 40 по групи; без тези и тикъри ──")
b = copy.deepcopy(B19)
b["cot"] = [{**e, "category": "financial", "price_confirmation": {"confirmed": FX["confirmed_2026_11_03"].get(e["market"]), "text": f"SMA10 · {e['market']}"}}
            for e in FX["extremes_2026_11_03"] if FX["confirmed_2026_11_03"].get(e["market"]) is not None]
b["cot_all"] = rows
b["cot_summary"] = {"text": FX["cot_summary_text"]}
b["cot_rhythm"] = {}
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
sec = page[page.index("COT Екстремуми"):]; sec = sec[:sec.index("</section>")]
fs = flat(sec)
assert "Пазар Перцентил Позиция Цената потвърждава" in fs and "Без AI" in fs
assert 'class="thesis' not in sec and "Директна теза" not in fs and "Cross-sector" not in fs and "cot-tickers" not in sec
vis = sec[:sec.index('<details class="cot-all">')]
assert vis.count("<tr><td>") == len(b["cot"]) and FX["cot_summary_text"] in flat(vis)
assert f"<summary>Всички 40 пазара</summary>" in sec
allt = flat(sec[sec.index('<details class="cot-all">'):])
idx = [allt.index(f" {g} ") for g in ("валути", "лихви", "индекси", "крипто", "суровини")]
assert idx == sorted(idx) and allt.index("US Dollar Index") < allt.index("лихви") and allt.index("WTI Crude Oil") > allt.index("суровини")
yes = [m for m, c in FX["confirmed_2026_11_03"].items() if c]
assert all(re.search(re.escape(m) + r" \d+ [^<]*? да", fs) for m in yes)
print(f"  ✓ видими {len(b['cot'])} екстремума (да / не за цената, {len(yes)} „да“), редът на модула под тях; ▸ Всички 40 пазара — валути → лихви → индекси → крипто → суровини; без тези и тикъри")

print()
print("── 3. AI тезите са махнати от кода ──")
src = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "src").glob("*.py")}
assert "cot_theses.py" not in src and "cot_opposites.py" not in src
assert "SYSTEM_COT = " not in src["ai_brief.py"] and "def cot_theses(" not in src["ai_brief.py"] and "ai_brief.cot_theses(" not in src["main.py"] and "cot_opposites" not in src["main.py"].replace("бележките за обратен залог (cot_opposites)", "")
assert not hasattr(config, "COT_THESES_CACHE_FILE") and not hasattr(config, "COT_DIRECT_TICKERS") and not hasattr(config, "COT_BATCH_SIZE")
assert not (ROOT / "data" / "cot_theses_cache.json").exists()
print("  ✓ без SYSTEM_COT / cot_theses / cot_opposites / кеша на тезите и настройките им")
print("\n✅ test_cot_table: всичко мина")
