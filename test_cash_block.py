"""
23.11.2026 (пакет 23.11, т. 5): режим Cash — всички карти и „Нови днес“ показват „Cash — без нови входове“ и са без размер (в браузъра — блокирани, като при отчета преди входа);
в Defensive остава ×0.5. До 23.11 в Cash картите показваха размер ×0.5 (на 23.11 режимът беше Cash, sizing_factor 0.5).

РЕАЛНО: tests/fixtures/novelty_2026-11-20.json — картите от брифа на 20.11 (CANSLIM, Kullamägi, GLB, EP) и историята; режимът Cash — както в брифа на 23.11.
СИНТЕТИЧНО (означено): поставянето на режима върху картите от 20.11 (тогава режимът беше Defensive).
Пускане: python run_tests.py test_cash_block
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, re, copy, io, contextlib, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_cash_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import novelty as nv, render

FX = json.loads((ROOT / "tests" / "fixtures" / "novelty_2026-11-20.json").read_text(encoding="utf-8"))
H = [tuple(x) for x in FX["history"]]
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))


def page(regime: str, factor: float) -> tuple[str, str, str]:
    cards = copy.deepcopy(FX["cards"])
    res = nv.annotate(cards, "2026-11-20", H)
    b = copy.deepcopy(B)
    b.update(date="2026-11-20", action=cards["action"], watchlist=cards["watchlist"], qm_breakout=cards["qm_breakout"], glb_candidates=cards["glb_candidates"],
             qm_ep=cards["qm_ep"], novelty=res)
    b["thermometer"] = {**b["thermometer"], "regime": regime, "sizing_factor": factor}                  # СИНТЕТИЧНО: режимът върху картите от 20.11
    with contextlib.redirect_stdout(io.StringIO()):
        html = render.render_dashboard(b, publish=False)
        em = render.render_email(b)
    return html, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)), em


print("── 1. Cash: картите и „Нови днес“ — „Cash — без нови входове“, без размер ──")
assert config.CASH_BLOCK_TEXT == "Cash — без нови входове"
assert render.cash_block({"thermometer": {"regime": "Cash"}}) == config.CASH_BLOCK_TEXT and render.cash_block({"thermometer": {"regime": "Defensive"}}) is None
html, txt, em = page("Cash", 0.5)
n_lv = len(re.findall(r'<div class="lv"', html))
n_cash = len(re.findall(r'data-blocked="1" data-blocked-reason="cash" data-blocked-text="без размер — Cash — без нови входове"', html))
n_earn = len(re.findall(r'data-blocked-reason="earnings"', html))
assert n_lv > 0 and n_cash + n_earn == n_lv, (n_lv, n_cash, n_earn)                                     # всяка карта е блокирана — Cash или отчет
assert n_cash >= 3 and txt.count("⚠ Cash — без нови входове — без размер") == n_lv                          # и при отчета — двата реда
assert txt.count("⚠ Cash — без нови входове") >= n_cash + 3                                             # + плочките „Нови днес“ (CROX, GKOS, R)
tiles = re.findall(r'<div class="nov-tile">.*?</div>\s*</div>', html, re.S)
assert "Нови днес · CANSLIM · 1 CROX" in txt and all("Cash — без нови входове" in t for t in re.findall(r'<div class="nov-tile">(.*?)<div class="kv">', html, re.S))
assert "Cash — без нови входове — картите са само за наблюдение, без размер." in em
print(f"  ✓ {n_lv} карти: {n_cash} — Cash, {n_earn} — отчет преди входа; плочките „Нови днес“ — с етикета; имейлът — ред при Kullamägi")

print("── 2. Defensive: без блокиране, режимният фактор ×0.5 ──")
html, txt, em = page("Defensive", 0.5)
assert 'data-blocked-reason="cash"' not in html and "Cash — без нови входове" not in txt and "Cash — без нови входове" not in em
assert 'data-factor="0.5"' in html and 'data-regime-label="защитен режим"' in html
print("  ✓ data-factor 0.5, „защитен режим“")

print("── 3. JS: текстът на блокирането и сборът ──")
js = (ROOT / "templates" / "sizing_ui.js").read_text(encoding="utf-8")
assert 'card.getAttribute("data-blocked-text") || "без размер — отчетът е преди входа"' in js
assert '"Ако вземеш всички: Cash — без нови входове"' in js and 'getAttribute("data-blocked-reason") === "cash"' in js
print("  ✓")
print("\n✅ test_cash_block: всичко мина")
