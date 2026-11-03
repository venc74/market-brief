"""
03.11.2026 · разходката, т. 16: сплитовете. Логиката е същата (целият пазар, цена > $10, пазарна стойност > $500 млн); когато няма нищо — ЕДИН ред „Няма сплитове тази седмица при акциите
над $10 и $500 млн; при позициите и наблюдаваните — няма до ДД.ММ“; отчетът на филтъра (колко отпаднаха и защо) — само в данните; позициите / наблюдаваните — отгоре; провал на
източника — червеният ред остава; секцията е веднага след „Макро бриф“ (до 03.11 — след книгите на GLB, с два реда отчет на филтъра).

РЕАЛНО: tests/fixtures/splits_report_2026-11-03.json (отчетът на брифа от 03.11: 11 в седмицата, 0 минават, 15 позиции / наблюдавани без сплит); tests/fixtures/brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): сплитът на позиция, редът, който минава филтъра, провалът на източника.
Пускане: python test_splits_section.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_splits_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render

SR = json.loads((ROOT / "tests" / "fixtures" / "splits_report_2026-11-03.json").read_text(encoding="utf-8"))["splits_report"]
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))


def sec_of(sr):
    b = copy.deepcopy(B19); b["splits_report"] = sr
    with contextlib.redirect_stdout(io.StringIO()):
        p = flat(render.render_dashboard(b, publish=False))
    i = p.index("Сплитове · тази седмица")
    return p, p[i:p.index("Наблюдавани тикъри", i) if "Наблюдавани тикъри" in p[i:] else i + 900]


print("── 1. РЕАЛНО 03.11: нищо — един ред; отчетът на филтъра — само в данните ──")
p, s = sec_of(SR)
assert (SR["state"], SR["diag"]["in_week"], SR["diag"]["passed"], SR["priority_checked"]) == ("empty", 11, 0, 15)
assert "Няма сплитове тази седмица при акциите над $10 и $500 млн; при позициите и наблюдаваните — няма до 20.11." in s
assert "Източникът върна" not in p and "RETO" not in p and "без данни" not in s and "Няма предстоящи сплитове" not in p
mi, si = p.index("Макро бриф"), p.index("Сплитове · тази седмица")
between = p[mi:si]
assert "Наблюдавани тикъри" not in between and "CANSLIM" not in between and "GLB" not in between                     # веднага след макро разказа
print("  ✓ „Няма сплитове тази седмица при акциите над $10 и $500 млн; при позициите и наблюдаваните — няма до 20.11.“; без „Източникът върна 11 …“; веднага след „Макро бриф“")

print()
print("── 2. позиция със сплит — отгоре; провал — червеният ред (СИНТЕТИЧНО) ──")
pos = {"ticker": "ABC", "split_type": "normal", "ratio": "2:1", "price": 120.0, "date": "2026-11-05", "date_human": "05.11", "badge": "position", "days_to_split": 2}
_, s2 = sec_of({**SR, "priority": [pos]})
assert s2.index("Отворени позиции и наблюдавани") < s2.index("ABC") < s2.index("Няма сплитове тази седмица при акциите над $10 и $500 млн.") and "при позициите и наблюдаваните — няма" not in s2
_, s3 = sec_of({"state": "source_failed", "diag": {"errors": ["HTTP 503"]}, "rows": [], "priority": [], "priority_checked": 15})
assert "⚠ Календарът на сплитовете не върна данни днес — празното НЕ значи, че няма сплитове." in s3 and "Няма сплитове тази седмица" not in s3
row = {"ticker": "XYZ", "split_type": "reverse", "ratio": "1:10", "price": 45.0, "date": "2026-11-06", "date_human": "06.11"}
_, s4 = sec_of({**SR, "state": "ok", "rows": [row]})
assert "XYZ reverse 1:10 · $45.00 · 06.11" in s4 and "При позициите и наблюдаваните — няма до 20.11." in s4
print("  ✓ позицията — отгоре, после редът за пазара; провал — червен ред (не „няма“); ред, който минава — плочка + „При позициите и наблюдаваните — няма до 20.11.“")
print("\n✅ test_splits_section: всичко мина")
