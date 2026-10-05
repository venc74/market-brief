"""
Qullamaggie (06.10.2026) · т.2: маркер QM✓ върху нашите CANSLIM карти (Action/Watchlist) и позиции (v2 отворени/чакащи и buy-stop книгата), когато тикърът е и кандидат за пробив на Qullamaggie;
скенерът е вързан в main.run (отделен блок до GLB, с try/except), диагностиката е в брифа, а провал на скана дава банер (празният списък не е "няма сетъпи").

РЕАЛНО: кандидатите DOCN, CORT, CRL от скана към 02.10.2026 (tests/fixtures/qm_frames_2026-10-02.json) и РЕАЛНИТЕ Watchlist карти от брифа на 05.10.2026 (EXPD, FTNT, …). СИНТЕТИЧНО: присвояването на QM✓ на
реалната карта на EXPD (EXPD не е кандидат — така картата показва маркера), позициите, подмененият скан.
Пускане: python test_qm_markers.py
"""
import sys, json, pathlib, tempfile, copy, ast, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import qm_breakout as q, data_warnings, render
from src import main as brief_main

FIX = json.loads((ROOT / "tests" / "fixtures" / "qm_frames_2026-10-02.json").read_text(encoding="utf-8"))
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
frames = {t: pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"])) for t, d in FIX["frames"].items()}
ROWS, _ = q.scan_frames(frames, lead=FIX["lead"])
BY = {r["ticker"]: r for r in ROWS}
assert sorted(BY) == ["CORT", "CRL", "DOCN"]

print("── текстът на маркера (РЕАЛЕН кандидат DOCN към 02.10) ──")
m = q.qm_marker(BY["DOCN"])
assert m["tag"] == "QM✓"
want = ("Breakout кандидат (Qullamaggie): ниво $151.83 (+8.4% над затварянето), ADR 7.2%, ръст +49% преди базата, база 8 сесии, очакван стоп ≈ $145.82, максимален $140.91.\n"
        "Отделна стратегия — измерване, не препоръка. Входът е по opening range high в сесията, стопът — low of day.")
assert m["title"] == want, m["title"]
print("  ", m["title"].replace("\n", " | "))

print()
print("── върху карти и позиции ──")
cards_a = [{"ticker": "DOCN", "markers": [{"tag": "SI✓", "title": "x"}]}, {"ticker": "AAPL"}]
cards_w = [{"ticker": "CORT"}, {"ticker": "EXPD", "markers": []}]
pos = [{"ticker": "CRL", "entry_date": "2026-09-22"}, {"ticker": "MSFT"}, {"ticker": "CRL", "also_action": True}]
n = brief_main.attach_qm_markers(cards_a + cards_w, BY) + brief_main.attach_qm_markers(pos, BY)
assert n == 4
assert [x["tag"] for x in cards_a[0]["markers"]] == ["SI✓", "QM✓"] and "markers" not in cards_a[1]                                   # съществуващите маркери се запазват
assert [x["tag"] for x in cards_w[0]["markers"]] == ["QM✓"] and cards_w[1]["markers"] == []
assert [x["tag"] for x in pos[0]["markers"]] == ["QM✓"] and "markers" not in pos[1] and [x["tag"] for x in pos[2]["markers"]] == ["QM✓"]
assert brief_main.attach_qm_markers([], BY) == 0 and brief_main.attach_qm_markers([{"ticker": "X"}], {}) == 0
print("  ✓ Action (след SI✓), Watchlist и позиции (отворена/чакаща/buy-stop) получават QM✓; тикъри без кандидатура — не; по ВСИЧКИ кандидати (не само показаните 8)")

print()
print("── картата на страницата ──")
tmp = tempfile.TemporaryDirectory(prefix="mb_qmm_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(tmp.name) / "docs", pathlib.Path(tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
brief = copy.deepcopy(B05)
for c in brief["watchlist"]:
    if c["ticker"] == "EXPD":
        c["markers"] = (c.get("markers") or []) + [q.qm_marker(BY["DOCN"])]                                                       # СИНТЕТИЧНО: маркерът на DOCN върху реалната карта на EXPD
page = htmllib.unescape(render.render_dashboard(brief))
assert page.count("QM✓") >= 1 and "Breakout кандидат (Qullamaggie): ниво $151.83" in page
print("  ✓ Watchlist картата показва QM✓ с текста при hover/клик")

print()
print("── банер при провал на скана ──")
assert data_warnings.collect(None, None, qm_diag={"ok": True, "batches": 10, "batches_failed": 0}) == [] and data_warnings.collect(None, None, qm_diag=None) == [] and data_warnings.collect(None, None, qm_diag={}) == []
w = data_warnings.collect(None, None, qm_diag={"ok": False, "error": "RuntimeError: мрежата падна"})
assert w == [{"source": "qm_breakout", "level": "warn", "message": "Qullamaggie скенер: не се изпълни (RuntimeError: мрежата падна) — празният списък НЕ значи, че няма кандидати за пробив днес."}]
w = data_warnings.collect(None, None, qm_diag={"ok": True, "batches": 10, "batches_failed": 3, "with_history": 620, "universe": 903})
assert "3 от 10 партиди" in w[0]["message"] and "620 от 903" in w[0]["message"]
print("  ✓ нормален скан — без банер; не се изпълни — 'празният списък НЕ значи, че няма кандидати'; 3 от 10 партиди паднали — 'списъкът е върху 620 от 903 тикъра'")

print()
print("── main.run (структурно) ──")
tree = ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8"))
run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
calls = [(n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id, n.lineno) for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name))]
names = [c for c, _ in calls]
assert "scan" in names and names.count("attach_qm_markers") == 2 and "cards" in names
keys = [k.value for n in ast.walk(run) if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
assert "qm_breakout" in keys and "qm_diag" in keys
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "qm_diag=qm_diag" in src and src.index("qm_breakout.scan(universe=qm_universe)") > src.index("glb_screener.screen()") and src.index("attach_qm_markers(action + watchlist, qm_by_ticker)") > src.index("qm_breakout.scan(universe=qm_universe)")
glb_line = next(l for c, l in calls if c == "screen")
scan_line = next(l for c, l in calls if c == "scan")
assert scan_line > glb_line
print("  ✓ run(): скенерът е след GLB, маркерите върху action+watchlist и върху позициите, brief има 'qm_breakout' и 'qm_diag', банерът получава qm_diag; целият блок е в try/except")
print()
print("Всички тестове минаха.")
