"""
18.11.2026 (спешно, т. 5): етикетът на Market Breadth (% над 40dMA) — спрямо собствената история, не по абсолютен праг. До 18.11: 40–80% → „здравословна ширина“ (56 от 69 брифа);
на 18.11 — 55.6% „здравословна“, при спад от 68.1% за 5 сесии. Сега: перцентилът сред записаните брифове преди днес (thermometer.breadth_history), праговете със стойностите им
(под 25-и — слаба, над 75-и — силна) и посоката за 5 сесии (мъртва зона 5 п.п.). Статусът (цветът, Cash при < 10%) — по абсолютните прагове, както досега.

РЕАЛНО: tests/fixtures/breadth_history_2026-11-18.json — стойностите от брифовете 14.08–17.11 и индикаторът от брифа на 18.11.
СИНТЕТИЧНО (означено): т. 2 — къса история и стойност под 10%; т. 3 — брифовете във временната папка.
Пускане: python test_breadth_relative.py
"""
import sys, json, copy, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_breadth_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import thermometer as th

FX = json.loads((ROOT / "tests" / "fixtures" / "breadth_history_2026-11-18.json").read_text(encoding="utf-8"))
H = [tuple(x) for x in FX["history"]]
IND = FX["indicator_2026_11_18"]
assert len(H) == 68 and H[0][0] == "2026-08-14" and IND["value"] == 55.6 and IND["label"] == "55.6% над 40dMA (здравословна ширина)"

print("── 1. РЕАЛНО: 18.11 — в средата, стеснява се ──")
r = th.breadth_relative(copy.deepcopy(IND), H)
assert r["label"] == ("55.6% над 40dMA — в средата спрямо собствената история: 66-и перцентил от 68 брифа (от 14.08; праг: под 25-и = 29.5% — слаба, над 75-и = 62.0% — силна)"
                      " · за 5 сесии 68.1% → 55.6% — стеснява се"), r["label"]
assert r["status"] == IND["status"] == "green" and r["relative"]["pct"] == 66 and "здравословна" not in r["label"]
r2 = th.breadth_relative(dict(IND, value=70.5, label="70.5% над 40dMA (здравословна ширина)"), H)       # СИНТЕТИЧНО: стойността
assert "силна спрямо собствената история: 99-и перцентил" in r2["label"], r2["label"]
print(f"  ✓ «{r['label'][:95]}…»")

print("── 2. СИНТЕТИЧНО: къса история и стойност под 10% ──")
s = th.breadth_relative(copy.deepcopy(IND), H[:10])
assert s["label"] == "55.6% над 40dMA (здравословна ширина; по абсолютния праг — историята е 10 брифа, под 40: 40–80% — здравословна)", s["label"]
low = dict(IND, value=8.2, status="red", label="8.2% над 40dMA (oversold, вероятен отскок — не е сигнал за дъно: …)")
x = th.breadth_relative(low, H)
assert x["label"].startswith("8.2% над 40dMA — слаба спрямо собствената история: 0-и перцентил") and x["label"].endswith("· oversold, вероятен отскок — не е сигнал за дъно: …")
assert x["status"] == "red"
print("  ✓ под 40 брифа — абсолютният праг с бележка; под 10% — oversold бележката остава, статусът red")

print("── 3. СИНТЕТИЧНО: историята от записаните брифове преди днес ──")
for d, v in (("2026-11-16", 67.7), ("2026-11-17", 63.7), ("2026-11-18", 55.6)):
    (config.DATA_DIR / f"{d}.json").write_text(json.dumps({"thermometer": {"indicators": [{"name": "Market Breadth (% над 40dMA)", "value": v}]}}), encoding="utf-8")
(config.DATA_DIR / "2026-11-15.json").write_text("{не е json", encoding="utf-8")
assert th.breadth_history("2026-11-18") == [("2026-11-16", 67.7), ("2026-11-17", 63.7)]
print("  ✓ днешният и нечетимият — вън")
print("\n✅ test_breadth_relative: всичко мина")
