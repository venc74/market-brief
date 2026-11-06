"""
06.11.2026 (пакет 05–06.11, т. 10): етикет „секторен отскок“, когато ≥ 3 гапа в един ден са от една индустрия — сутрин (after-hours) и в 15:05 (премаркет). Реално, 06.11, 09:05 Ню Йорк: LRCX, SITM, MKSI, COHR след срива от
05.11; ABNB (с отчет) не влиза. Индустрията — GICS Sub-Industry от таблиците на универса; COHR е „Electronic Components“, затова групата „полупроводници и компоненти“.

РЕАЛНО: tests/fixtures/preopen_gaps_2026-11-06.json (гаповете), tests/fixtures/wiki_sp500_2026-10-30.html.gz, wiki_sp400_2026-10-30.html.gz (таблиците), tests/fixtures/brief_2026-10-19.json (рамката).
СИНТЕТИЧНО (означено): кратките списъци в т. 2.
Пускане: python test_ep_sector_bounce.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, types
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_epbounce_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import screener, qm_ep, preopen, render

FXD = ROOT / "tests" / "fixtures"
PO = json.loads((FXD / "preopen_gaps_2026-11-06.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
HTML = {u["url"]: gzip.decompress((FXD / f).read_bytes()).decode("utf-8") for u, f in zip(config.UNIVERSE_SOURCES, ("wiki_sp500_2026-10-30.html.gz", "wiki_ndx100_list_2026-10-30.html.gz", "wiki_sp400_2026-10-30.html.gz"))}
screener.requests.get = lambda url, **k: types.SimpleNamespace(text=HTML[url])

print("── 1. индустриите от РЕАЛНИТЕ таблици; етикетът за 06.11 ──")
screener.LAST_UNIVERSE_INDUSTRY.clear()
with contextlib.redirect_stdout(io.StringIO()):
    screener.build_universe()
I = screener.LAST_UNIVERSE_INDUSTRY
assert (I["LRCX"], I["MKSI"], I["SITM"], I["COHR"], I["ABNB"]) == ("Semiconductor Materials & Equipment", "Semiconductor Materials & Equipment", "Semiconductors", "Electronic Components", "Hotels, Resorts & Cruise Lines")
gaps = [g["ticker"] for g in PO["gaps"]]
assert gaps == ["ABNB", "LRCX", "SITM", "MKSI", "COHR"]
b = qm_ep.sector_bounce(gaps)
assert len(b) == 1 and b[0]["tickers"] == ["LRCX", "SITM", "MKSI", "COHR"] and b[0]["group"] == "полупроводници и компоненти"
T = b[0]["text"]
assert T == "Секторен отскок: LRCX, SITM, MKSI и COHR — 4 гапа от една индустрия (полупроводници и компоненти); не е новина за всяка компания поотделно."
print(f"  ✓ {T}")

print("── 2. границите (СИНТЕТИЧНО) ──")
ind = {"A": "Banks", "B": "Banks", "C": "Banks", "D": "Banks", "E": "Oil", "F": "Oil"}
assert qm_ep.sector_bounce(["A", "B"], ind) == [] and qm_ep.sector_bounce(["A", "E", "F"], ind) == []          # 2 от една — не
assert qm_ep.sector_bounce(["A", "B", "C"], ind)[0]["group"] == "Banks" and qm_ep.sector_bounce(["A", "A", "B"], ind) == []     # повторен тикър — веднъж
assert qm_ep.sector_bounce(["X", "Y", "Z"], ind) == [] and qm_ep.sector_bounce([], ind) == [] and qm_ep.sector_bounce(["A", "B", "C"], {}) == []     # без индустрия — не се брои
print("  ✓ 2 от една индустрия — не; 3 — да; тикър без индустрия не се брои")

print("── 3. сутрин и в 15:05: страницата и имейлите ──")
day = {**PO, "sector_bounce": b}
mail = preopen.email_html(day)
assert T in mail and mail.index("EP — гапове") < mail.index(T) < mail.index("ABNB")
bb = copy.deepcopy(B19); bb["preopen"] = day
ep = dict(bb.get("qm_ep") or {}); ep.update(ok=True, sector_bounce=b, rows=[])
bb["qm_ep"] = ep
with contextlib.redirect_stdout(io.StringIO()):
    page, email = render.render_dashboard(bb, publish=False), render.render_email(bb)
assert page.count(T) == 2 and page.index(T) < page.index('<section id="qm-ep">') < page.rindex(T)              # карето преди отварянето и секцията EP
assert T in email
bb["preopen"] = {**PO}; ep2 = dict(ep); ep2.pop("sector_bounce"); bb["qm_ep"] = ep2                             # стар бриф — без полето
with contextlib.redirect_stdout(io.StringIO()):
    assert "Секторен отскок" not in render.render_dashboard(bb, publish=False)
src = (ROOT / "src" / "preopen.py").read_text(encoding="utf-8")
assert 'res["sector_bounce"] = qm_ep_sector_bounce(gaps)' in src and "screener.build_universe()" in src
print("  ✓ в карето преди отварянето и имейла му; в секцията EP и сутрешния имейл; стар бриф — без реда")
print("\n✅ test_ep_sector_bounce: всичко мина")
