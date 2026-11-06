"""
06.11.2026 (пакет 05–06.11, т. 2): фундаментите (Yahoo .info — таван 60 заради 401) се проверяват за най-силните по RS; при равен RS — старият ред. До 06.11 първите 60 бяха по сетъпа
(потвърдени → без обем → под pivot → extended): брифът от 05.11 — PFG RS 74 проверен, CROX RS 97 и LLY — не. Финалистите се връщат в стария ред (надолу по pipeline-а нищо не се мени).
Брифът казва „фундаментите не са проверени за N имена“ и кои са с най-висок RS (страницата и имейлът).

РЕАЛНО: tests/fixtures/fundamentals_order_2026-11-05.json — техническите кандидати към бара от 04.11 (бележката там), tests/fixtures/brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): отговорът на Yahoo .info (всички минават), кратките списъци в т. 3.
Пускане: python test_fundamentals_order.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_fundorder_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
config.RS_LINE_STATE_FILE = config.DATA_DIR / "screener_rs_state.json"
from src import screener, setup_rules, render

ROWS = json.loads((ROOT / "tests" / "fixtures" / "fundamentals_order_2026-11-05.json").read_text(encoding="utf-8"))["rows"]
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())


class FakeTicker:                                                                     # СИНТЕТИЧНО: всички минават филтъра
    def __init__(self, sym):
        self.info = {"marketCap": 5e10, "earningsQuarterlyGrowth": 0.5, "revenueGrowth": 0.3, "returnOnEquity": 0.3, "longName": sym, "sector": "Technology", "industry": "X"}


screener.yf.Ticker = FakeTicker
screener.time.sleep = lambda s: None
real_tech = screener.technical_screen

print("── 1. подредбата: по RS, при равен RS — сетъпът (РЕАЛНИТЕ кандидати към 04.11) ──")
assert len(ROWS) == 62
old = [r["ticker"] for r in sorted(ROWS, key=setup_rules.screen_priority)]
new = sorted(ROWS, key=setup_rules.fundamentals_priority)
rs = {r["ticker"]: r["rs_rating"] for r in ROWS}
assert [r["rs_rating"] for r in new] == sorted(rs.values(), reverse=True)
assert rs["CROX"] == 97 and old.index("CROX") >= 60 and "CROX" in [r["ticker"] for r in new[:60]] and "LLY" in [r["ticker"] for r in new[:60]]   # старият ред оставя CROX извън първите 60
assert old.index("PFG") < 60                                                          # PFG RS 74 — по стария ред вътре
assert setup_rules.fundamentals_priority({"rs_rating": None, "pct_from_pivot": 0, "price": 10, "pivot": 11}) > setup_rules.fundamentals_priority({"rs_rating": 70, "pct_from_pivot": 0, "price": 10, "pivot": 11})     # без RS — накрая
print(f"  ✓ стар ред — извън първите 60: {old[60:]}; нов ред — извън: {[r['ticker'] for r in new[60:]]} (RS {[r['rs_rating'] for r in new[60:]]})")

print("── 2. run_screen: първите 60 по RS, финалистите — в стария ред; статусът ──")
screener.build_universe = lambda: [r["ticker"] for r in ROWS]
screener.technical_screen = lambda *a, **k: copy.deepcopy(ROWS)
screener.LAST_STATUS.update(ok=False)
with q():
    fin = screener.run_screen()
assert len(fin) == 60 and {r["ticker"] for r in fin} == {r["ticker"] for r in new[:60]}
assert [r["ticker"] for r in fin] == [r["ticker"] for r in sorted(fin, key=setup_rules.screen_priority)]        # надолу по pipeline-а — старият ред
nc = screener.LAST_STATUS["fundamentals_not_checked"]
assert nc["n"] == 2 and nc["max"] == 60 and [x["ticker"] for x in nc["top"]] == [r["ticker"] for r in new[60:]]
assert screener.LAST_FUNDAMENTALS[new[61]["ticker"]]["result"] == "not_checked"
print(f"  ✓ 60 финалисти (стар ред); непроверени: {nc['n']} — {nc['top']}")

print("── 3. редът в брифа: страницата и имейлът ──")
st = {"fundamentals_not_checked": {"n": 13, "max": 60, "top": [{"ticker": "NDAQ", "rs_rating": 77}, {"ticker": "UNP", "rs_rating": 77}]}}      # СИНТЕТИЧНО: по измерването с хистерезиса (бар 04.11)
note = render.fundamentals_note(st)
assert note == "Фундаментите не са проверени за 13 имена (таван 60 заради Yahoo — проверяват се най-силните по RS); с най-висок RS от тях: NDAQ (RS 77), UNP (RS 77) — те не са в списъците по-горе."
assert render.fundamentals_note({}) is None and render.fundamentals_note(None) is None and render.fundamentals_note({"fundamentals_not_checked": {"n": 0}}) is None
assert "за 1 име " in render.fundamentals_note({"fundamentals_not_checked": {"n": 1, "max": 60, "top": []}})
b = copy.deepcopy(B19); b["screener_status"] = st
with q():
    page, mail = render.render_dashboard(b, publish=False), render.render_email(b)
assert note in page and note in mail
b.pop("screener_status")
with q():
    assert "Фундаментите не са проверени" not in render.render_dashboard(b, publish=False)          # стар бриф — без реда
print("  ✓ „Фундаментите не са проверени за 13 имена … с най-висок RS от тях: NDAQ (RS 77), UNP (RS 77)“ — на страницата и в имейла; стар бриф — без реда")
print("\n✅ test_fundamentals_order: всичко мина")
