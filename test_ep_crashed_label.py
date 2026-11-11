"""
11.11.2026 (т. 3): при ръст за 3 месеца под −30% (config.QM_EP_CRASHED_RET63_PCT) етикетът е „сринала се, не забравена“ вместо „пренебрегната“ — сутрин (EP таблицата
и имейлът) и в карето в 15:05 (страницата и имейлът). Само етикет: включването в EP не се променя. Реално: 11.11 в 15:05 — CRWV +13.4% (−55% за 3 мес.), NBIS +10.9% (−48%);
сутрин — FN на 03.11 (−41%). Измерено: сутрин 1 от 9 EP реда, в 15:05 — 6 от 15 гапа (LRCX, SITM, MKSI, COHR на 06.11; CRWV, NBIS на 11.11).

РЕАЛНО: tests/fixtures/ep_crashed_2026-11-11.json, tests/fixtures/brief_2026-10-19.json (рамката).
СИНТЕТИЧНО (означено): т. 1 — границите.
Пускане: python test_ep_crashed_label.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_crashed_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import qm_ep, preopen, render

FX = json.loads((ROOT / "tests" / "fixtures" / "ep_crashed_2026-11-11.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
L = "сринала се, не забравена"

print("── 1. думата (СИНТЕТИЧНИ граници) ──")
assert qm_ep.neglect_label(-30.1, True) == L and qm_ep.neglect_label(-30.0, True) == "пренебрегнат" and qm_ep.neglect_label(5, True) == "пренебрегнат"
assert qm_ep.neglect_label(35, False) == "не е пренебрегнат" and qm_ep.neglect_label(None, True) is None and qm_ep.neglect_label(-55, False) == L
print("  ✓ под −30% → „сринала се, не забравена“; −30% и нагоре — както преди")

print("── 2. РЕАЛНО: карето в 15:05 на 11.11 — CRWV и NBIS ──")
G = {g["ticker"]: g for g in FX["preopen"]["gaps"]}
assert round(G["CRWV"]["ret63_pct"]) == -55 and round(G["NBIS"]["ret63_pct"]) == -48 and G["CRWV"]["neglect"] and G["NBIS"]["neglect"]
mail = preopen.email_html(FX["preopen"])
assert f"{L} (3 мес. -55%)" in mail and f"{L} (3 мес. -48%)" in mail and "пренебрегнат (3 мес." not in mail
bb = copy.deepcopy(B19); bb["preopen"] = FX["preopen"]
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
box = page[page.index('<section class="preopen"'):page.index("</section>", page.index('<section class="preopen"'))]
assert box.count(L) == 2 and "· пренебрегнат" not in box
print(f"  ✓ страницата и имейлът: CRWV, NBIS — „{L}“")

print("── 3. РЕАЛНО: сутрин 03.11 — FN (−41%) в EP таблицата и имейла ──")
rows = FX["qm_ep_2026_11_03"]["rows"]
fn = [r for r in rows if r["ticker"] == "FN"]
assert fn and fn[0]["ret63_pct"] < -30 and all(r["ret63_pct"] >= -30 for r in rows if r["ticker"] != "FN")
bb = copy.deepcopy(B19); ep = dict(bb.get("qm_ep") or {}); ep.update(ok=True, rows=rows, not_neglected=[], session=FX["qm_ep_2026_11_03"]["session"]); bb["qm_ep"] = ep
with contextlib.redirect_stdout(io.StringIO()):
    page, email = render.render_dashboard(bb, publish=False), render.render_email(bb)
sec = page[page.index('<section id="qm-ep">'):page.index("</section>", page.index('<section id="qm-ep">'))]
assert sec.count(L) == 1 and sec.index("FN") < sec.index(L) and email.count(L) == 1
print("  ✓ само FN носи етикета — на страницата и в имейла")
print("\n✅ test_ep_crashed_label: всичко мина")
