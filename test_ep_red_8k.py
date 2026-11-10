"""
10.11.2026 (т. 1): 8-K т. 4.02 (Non-Reliance on Previously Issued Financial Statements — предстои преизчисляване) е ОТДЕЛНО червено предупреждение
в EP реда сутрин, в карето преди отварянето (15:05) и в двата имейла — не само в списъка с точки. Реално: AAON, 8-K от 09.11 16:09 ET с т. 2.02, 4.02, 7.01;
на 10.11 стоеше само като „4.02 — отказ от предишни отчети“ в реда с точките.

РЕАЛНО: tests/fixtures/ep_aaon_sanm_2026-11-10.json (сутрешният qm_ep и карето от 10.11), tests/fixtures/brief_2026-10-19.json (рамката на страницата).
СИНТЕТИЧНО (означено): т. 2 — 8-K без 4.02 и празни входове.
Пускане: python test_ep_red_8k.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_red8k_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import qm_ep, preopen, render

FXD = ROOT / "tests" / "fixtures"
FX = json.loads((FXD / "ep_aaon_sanm_2026-11-10.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
ROWS = {r["ticker"]: r for r in FX["qm_ep"]["rows"]}
GAPS = {g["ticker"]: g for g in FX["preopen"]["gaps"]}
W = "⚠ 8-K т. 4.02 (09.11): non-reliance: компанията обявява, че по-рано публикувани финансови отчети вече не са надеждни — предстои преизчисляване (restatement)"

print("── 1. РЕАЛНО: AAON сутрин и в 15:05 — и двата записа на точките ──")
assert [c for c, *_ in ROWS["AAON"]["filings_8k"][0]["items"]] == ["2.02", "4.02", "7.01"]       # сутрин: [код, en, bg]
assert GAPS["AAON"]["filings_8k"][0]["items"] == ["2.02", "4.02", "7.01"]                         # в карето: само кодовете
assert qm_ep.red_8k(ROWS["AAON"]["filings_8k"]) == [W] and preopen.red_8k(GAPS["AAON"]["filings_8k"]) == [W]
assert qm_ep.red_8k(ROWS["SANM"]["filings_8k"]) == []                                              # 2.02 и 8.01 — без предупреждение
print(f"  ✓ {W[:60]}…; SANM (2.02, 8.01) — нищо")

print("── 2. границите (СИНТЕТИЧНО) ──")
assert qm_ep.red_8k(None) == [] and qm_ep.red_8k([]) == [] and qm_ep.red_8k([{"items": []}]) == []
two = [{"accepted_et": "2026-11-09 16:09", "items": ["4.02"]}, {"accepted_et": "2026-11-09 16:09", "items": [["4.02", "x", "y"]]}]
assert qm_ep.red_8k(two) == ["⚠ 8-K т. 4.02 (09.11): " + qm_ep.RED_8K_TEXT["4.02"]]               # същият ред — веднъж
assert qm_ep.red_8k([{"items": ["4.02"]}]) == ["⚠ 8-K т. 4.02: " + qm_ep.RED_8K_TEXT["4.02"]]     # без час — без дата
print("  ✓ празно → нищо; повторен 8-K → веднъж; без час → без дата")

print("── 3. страницата и имейлите ──")
mail = preopen.email_html(FX["preopen"])
assert W.replace("„", "&quot;") in mail or W in mail
assert mail.index("4.02 — отказ от предишни отчети") < mail.index("⚠ 8-K т. 4.02") and "color:#991b1b'>⚠ 8-K т. 4.02" in mail
bb = copy.deepcopy(B19); bb["preopen"] = FX["preopen"]
ep = dict(bb.get("qm_ep") or {}); ep.update(ok=True, rows=FX["qm_ep"]["rows"], not_neglected=[], session=FX["qm_ep"]["session"])
bb["qm_ep"] = ep
with contextlib.redirect_stdout(io.StringIO()):
    page, email = render.render_dashboard(bb, publish=False), render.render_email(bb)
assert page.count(W) == 2 and page.index(W) < page.index('<section id="qm-ep">') < page.rindex(W)          # карето преди отварянето и EP таблицата
assert "color:var(--red);font-weight:600\">" + W in page
assert email.count(W) == 1 and 'color:#991b1b">' + W in email                                              # сутрешният имейл: EP редът на AAON
i = email.index(W); assert email.rfind("AAON", 0, i) > email.rfind("SANM", 0, i)
print("  ✓ карето (страница + имейл), EP таблицата, сутрешният имейл — червено, под реда с точките")
print("\n✅ test_ep_red_8k: всичко мина")
