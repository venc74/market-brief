"""
30.10.2026 · поправки от брифа, т. 2: Form 4 в „Наблюдавани тикъри“ — флаг за всяка посока поотделно (покупки / продажби), с плана (10b5-1) и CLUSTER по посока;
таблицата с Form 4 под реда остава както е (по ред на сделка). До 30.10 CLUSTER беше общ: ACN го носеше заради продажбите, а под него беше извънплановата покупка на CEO.
Примери (РЕАЛНО, 30.10): CRCL — 25 продажби, всички по 10b5-1, 5 инсайдъри → CLUSTER продажби · по план; CRBG — 27 планови покупки на Nippon Life (1 купувач → не е клъстер);
ACN — 3 извънпланови покупки (CEO Julie Sweet ~$3.0 млн на 26.10) + продажби на 3 инсайдъри (частично по план) → CLUSTER само при продажбите.

РЕАЛНО: tests/fixtures/watch_brief_2026-10-30.json — brief["watch"] от 30.10 (Form 4 от EDGAR); tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): кратките редици в т. 3.
Пускане: python test_watch_insider_flags.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_wflags_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import watch_monitor as wm, render

FX = json.loads((ROOT / "tests" / "fixtures" / "watch_brief_2026-10-30.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
W = {r["ticker"]: r for r in FX["watch"]}
tx = lambda t: [{**x, "date": dt.date.fromisoformat(x["date"][:10])} for x in W[t]["insider"]]

print("── 1. РЕАЛНИТЕ случаи от 30.10 ──")
crcl, crbg, acn = wm.insider_flags(tx("CRCL")), wm.insider_flags(tx("CRBG")), wm.insider_flags(tx("ACN"))
assert [(f["label"], f["n"], f["owners"], f["cluster"], f["plan"]) for f in crcl] == [("продажби", 25, 5, True, "по план (10b5-1)")]
assert [(f["label"], f["n"], f["owners"], f["cluster"], f["plan"]) for f in crbg] == [("покупки", 27, 1, False, "по план (10b5-1)")]
assert [(f["label"], f["n"], f["cluster"], f["plan"]) for f in acn] == [("покупки", 3, False, "извънпланови"), ("продажби", 9, True, "частично по план")]
assert acn[0]["top_offplan"] == {"owner": "Sweet Julie Spellman", "title": "Chair and CEO", "date": "2026-10-26", "value": 3001041}
assert W["ACN"]["insider_cluster"] is True                                                                          # старият общ флаг — заради продажбите
print("  ✓ CRCL: CLUSTER продажби · по план; CRBG: покупки · по план (един купувач); ACN: покупки · извънпланови (Chair and CEO $3.0 млн, 26.10) + CLUSTER продажби · частично по план")

print()
print("── 2. страницата: флаговете в колоната, таблицата с Form 4 — без промяна ──")
rows = []
for r in FX["watch"]:
    r = copy.deepcopy(r)
    r["insider_flags"] = wm.insider_flags([{**x, "date": dt.date.fromisoformat(x["date"][:10])} for x in r["insider"]])
    rows.append(r)
b = copy.deepcopy(B19); b["watch"] = rows
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
txt = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
row = lambda t: txt(page[page.index(f'<span class="wt-t">{t}<'):page.index("</summary>", page.index(f'<span class="wt-t">{t}<'))])
assert "CLUSTER продажби 25 · по план (10b5-1)" in row("CRCL") and "покупки 27 · по план (10b5-1)" in row("CRBG") and "CLUSTER покупки" not in row("CRBG")
assert "покупки 3 · извънпланови · Chair and CEO $3.0 млн (26.10)" in row("ACN") and "CLUSTER продажби 9 · частично по план" in row("ACN")
acn_det = page[page.index('<span class="wt-t">ACN<'):]; acn_det = acn_det[:acn_det.index("</details>")]
assert acn_det.count("<tr>") == len(W["ACN"]["insider"]) + 1                                                       # таблицата: заглавие + ред на сделка
print("  ✓ „CLUSTER продажби 25 · по план (10b5-1)“, „покупки 3 · извънпланови · Chair and CEO $3.0 млн (26.10)“; Form 4 таблицата — ред на сделка")

print()
print("── 3. планът (СИНТЕТИЧНИ редици) ──")
d = dt.date(2026, 10, 20)
mk = lambda **k: {"code": "S", "owner_name": "A", "owner_title": "", "value": 100.0, "date": d, "planned_10b5_1": None, **k}
assert wm.insider_flags([mk(), mk(owner_name="B")])[0]["plan"] == "планът неизвестен"
assert wm.insider_flags([mk(planned_10b5_1=True), mk(owner_name="B")])[0]["plan"] == "частично по план"
assert wm.insider_flags([]) == [] and wm.insider_flags([mk(code="P", planned_10b5_1=False)])[0]["top_offplan"]["value"] == 100
print("  ✓ неизвестен план, смесен, празно")
print("\n✅ test_watch_insider_flags: всичко мина")
