"""
29.10.2026 · разходката, т. 2 (термометърът), решение 2: картата „Основна инфлация“ казва ясно за кой месец са данните (с годината) и че излизат с ~6 седмици закъснение
(в края на следващия месец). До 29.10 пишеше само „за август“, а подсказката — „~1 месец закъснение“.
Закъснението, измерено в брифовете: брифът от 30.09 още показва юли, от 01.10 — август → августовските данни са излезли на 30.09 (~6 седмици след средата на август, ~4 след края му).

РЕАЛНО: tests/fixtures/core_inflation_2026-09-29_10-01.json — macro.core_inflation от брифовете на 29.09, 30.09 и 01.10; tests/fixtures/brief_2026-10-19.json — за рендера.
СИНТЕТИЧНО (означено): застоялият запис в т. 3 и декемврийските данни, показани през 2027, в т. 4.
Пускане: python test_core_inflation_label.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cpi_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
CI = json.loads((ROOT / "tests" / "fixtures" / "core_inflation_2026-09-29_10-01.json").read_text(encoding="utf-8"))["briefs"]
LAG = "излизат с ~6 седмици закъснение (в края на следващия месец)"


def card(ci):
    b = copy.deepcopy(B19)
    b["macro"]["core_inflation"] = ci
    with contextlib.redirect_stdout(io.StringIO()):
        h = render.render_dashboard(b, publish=False)
    i = h.index('<div class="t-name">Основна инфлация</div>')
    c = h[h.rindex("<div", 0, i):]
    return c[:c.index('<div class="t-label">')], re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", c[c.index('<div class="t-label">'):c.index("</div>", c.index('<div class="t-label">'))])))


print("── 1. РЕАЛНОТО закъснение: 30.09 — още юли, 01.10 — август ──")
assert [CI[d]["date"] for d in ("2026-09-29", "2026-09-30", "2026-10-01")] == ["2026-07-01", "2026-07-01", "2026-08-01"]
print("  ✓ августовските данни се появяват в брифа от 01.10 (излезли на 30.09 — в края на следващия месец)")

print()
print("── 2. картата: месецът с годината и закъснението (РЕАЛНИТЕ записи) ──")
for d, month in (("2026-09-30", "юли 2026"), ("2026-10-01", "август 2026")):
    head, label = card(CI[d])
    assert label.strip().startswith(f"данни за {month} · {LAG} · ") and " 3м средно " in label, label          # юли — „→ стабилна“, август — „↓ пада“
    assert label.strip().endswith("информативно, не влиза в режима")
    print(f"  ✓ {d}: «{label.strip()[:110]}…»")
assert "в края на следващия" in head and "~1 месец" not in head                                              # подсказката — същото, без старото „~1 месец закъснение“
b19_head, b19_label = card(B19["macro"]["core_inflation"])                                                   # РЕАЛНО: 19.10 — пак август
assert b19_label.strip().startswith(f"данни за август 2026 · {LAG}")

print()
print("── 3. СИНТЕТИЧНО: застояли данни ──")
_, label = card({"value": None, "stale": True, "last_date": "2026-07-01", "last_month": "юли", "age_days": 90})
assert label.strip() == f"застояли данни — последно за юли 2026 (90 дни) · {LAG} · информативно, не влиза в режима", label
print(f"  ✓ «{label.strip()}»")

print()
print("── 4. СИНТЕТИЧНО: декемврийските данни, показани през февруари 2027 — годината е на данните ──")
_, label = card({"value": 2.4, "date": "2026-12-01", "month": "декември", "age_days": 40})
assert label.strip().startswith(f"данни за декември 2026 · {LAG}")
print(f"  ✓ «{label.strip()}»")
print("\n✅ test_core_inflation_label: всичко мина")
