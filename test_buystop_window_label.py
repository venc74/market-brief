"""
Пакет 1б (б) · картата на buy-stop кандидата показва прозореца на ЗАПИСА в книгата ("валиден до 09.10, от 05.10"), не нов 5-сесиен прозорец от днес.
Преди: EXPD беше "валиден до 09.10" на 05.10 и "до 12.10" на 06.10 (classify_setup смята прозореца от деня на брифа), докато книгата брои 5-те сесии от ПЪРВИЯ ден (запис от 05.10 → 09.10) и
картата от 06.10 е само продължение на същия запис. Показване — книгата и дедупът не се променят.

РЕАЛНО: Watchlist картите на EXPD от брифовете на 05.10 (tests/fixtures/brief_2026-10-05.json) и 06.10 (tests/fixtures/expd_card_2026-10-06.json): buy-stop $194.59 и в двата дни, pivot $194.59,
под pivot с 1.09% / 0.24%. Записът в книгата се създава от РЕАЛНИЯ ingest код върху картата от 05.10 (планът-преглед е изчислен от sizing.buy_stop_preview — в самия бриф от 05.10 го няма, P2 още не беше качен).
СИНТЕТИЧНО: временният tracker, датите 12.10 и бъдещата дата, преместеното ниво 197.00, записите в други статуси/категории, повреденото четене.
Пускане: python test_buystop_window_label.py
"""
import sys, json, pathlib, tempfile, copy, ast, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import setup_rules, backtest, sizing, render

D = dt.date.fromisoformat
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
C05 = next(c for c in B05["watchlist"] if c["ticker"] == "EXPD")
C06 = json.loads((ROOT / "tests" / "fixtures" / "expd_card_2026-10-06.json").read_text(encoding="utf-8"))["card"]
assert (C05["setup"]["buy_stop"], C06["setup"]["buy_stop"]) == (194.59, 194.59) and (C05["setup"]["valid_through"], C06["setup"]["valid_through"]) == ("2026-10-09", "2026-10-12")

_tmp = tempfile.TemporaryDirectory(prefix="mb_bsw_")
config.DATA_DIR = pathlib.Path(_tmp.name)
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DOCS_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
config.BUYSTOP_TRACK_FROM = ""                                           # тук се тества показването; guard-ът по дата има собствен тест (test_buystop_start_guard.py)


def fresh(card, day):
    c = copy.deepcopy(card)
    c.pop("setup", None)
    return c


print("── записът в книгата от РЕАЛНАТА карта на 05.10 ──")
c = copy.deepcopy(C05)
setup_rules.annotate([c], D("2026-10-05"))
assert c["setup"]["trigger_text"] == C05["setup"]["trigger_text"] and c["setup"]["valid_through"] == "2026-10-09"          # кодът възпроизвежда реалната карта
c["plan_preview"] = sizing.buy_stop_preview(c, 0.5, D("2026-10-05"))
tr = {}
backtest._ingest_buystop_list(tr, "2026-10-05", [c], "Defensive")
backtest._save_tracker(tr)
rec = tr["EXPD_2026-10-05_buystop"]
assert (rec["status"], rec["valid_through"], rec["buy_stop"], rec["window_sessions"]) == ("pending", "2026-10-09", 194.59, 5)
book = backtest.pending_buystop_by_ticker()
assert list(book) == ["EXPD"] and book["EXPD"]["entry_date"] == "2026-10-05"
print("  ✓ EXPD_2026-10-05_buystop: pending, ниво $194.59, валиден до 2026-10-09 (5 сесии от първия ден)")

print()
print("── картата от 06.10: без книга — нов прозорец; с книга — прозорецът на записа ──")
c0 = fresh(C06, "06"); setup_rules.annotate([c0], D("2026-10-06"))
assert c0["setup"]["valid_through"] == "2026-10-12" and "valid_label" not in c0["setup"] and c0["setup"]["trigger_text"] == C06["setup"]["trigger_text"]
c1 = fresh(C06, "06"); setup_rules.annotate([c1], D("2026-10-06"), book)
s1 = c1["setup"]
assert (s1["valid_through"], s1["valid_from"], s1["valid_label"], s1["book_status"]) == ("2026-10-09", "2026-10-05", "до 09.10, от 05.10", "pending") and "book_level" not in s1
assert "(валиден до 09.10, от 05.10 — 5 сесии от първия ден)" in s1["trigger_text"] and "сега 0.2% под pivot" in s1["trigger_text"] and "2026-10-12" not in s1["trigger_text"]
assert s1["buy_stop"] == 194.59 and s1["max_chase"] == c0["setup"]["max_chase"] and s1["kind"] == "below_pivot"       # нивата не се пипат
print("  ✓ без книга: 'до 2026-10-12' (както в реалната карта от 06.10); с книга: 'до 09.10, от 05.10' и текстът на сетъпа се пренаписва, нивата са същите")
print("    ", s1["trigger_text"])

print()
print("── граници ──")
c = fresh(C06, "06"); setup_rules.annotate([c], D("2026-10-12"), book)                       # СИНТЕТИЧНО: на 12.10 записът от 05.10 е изтекъл (още нерезолвиран)
assert c["setup"]["valid_through"] == "2026-10-16" and "valid_label" not in c["setup"]
c = fresh(C06, "06"); setup_rules.annotate([c], D("2026-10-09"), book)                       # последният ден на прозореца — още важи
assert c["setup"]["valid_label"] == "до 09.10, от 05.10"
c = fresh(C06, "06"); setup_rules.annotate([c], D("2026-10-02"), book)                       # запис от бъдеща дата (напр. преразпускане на стар ден) се игнорира
assert "valid_label" not in c["setup"]
c = fresh(C06, "06"); setup_rules.annotate([c], "2026-10-06", book)                          # датата като низ
assert c["setup"]["valid_label"] == "до 09.10, от 05.10"
c = fresh(C06, "06"); setup_rules.annotate([c], D("2026-10-06"), {"EXPD": {**rec, "buy_stop": 197.0}})   # СИНТЕТИЧНО: нивото на картата е изместено спрямо записа
assert c["setup"]["book_level"] == 197.0 and "Книгата следи ниво $197.00 от 05.10" in c["setup"]["trigger_text"] and c["setup"]["buy_stop"] == 194.59
c = fresh(C06, "06"); setup_rules.annotate([c], D("2026-10-06"), {"AAPL": rec})              # запис за друг тикър
assert "valid_label" not in c["setup"]
c = fresh(C06, "06"); c["price"] = c["pivot"] * 1.02                                         # над pivot → не е below_pivot (СИНТЕТИЧНО: цената на реалната карта е вдигната)
setup_rules.annotate([c], D("2026-10-06"), book)
assert c["setup"]["kind"] != "below_pivot" and "valid_label" not in c["setup"]
assert setup_rules.apply_book_window({"kind": "below_pivot", "buy_stop": 100.0, "trigger_text": "x"}, None) == {"kind": "below_pivot", "buy_stop": 100.0, "trigger_text": "x"}
print("  ✓ изтекъл запис (12.10) и бъдещ запис се игнорират; 09.10 още важи; дата като низ; изместено ниво → бележка за нивото на книгата; друг тикър, не-below_pivot и липсваща книга — без промяна")

print()
print("── кои записи се броят за 'чакащ' ──")
other = {
    "EXPD_2026-10-06_x": {**rec, "entry_date": "2026-10-06", "valid_through": "2026-10-12", "status": "open"},               # СИНТЕТИЧНО: вече отворена
    "EXPD_2026-10-01_action": {k: v for k, v in {**rec, "entry_date": "2026-10-01", "valid_through": "2026-10-07"}.items() if k != "category"},   # Action запис (без category)
    "EXPD_2026-10-02_old": {**rec, "entry_date": "2026-10-02", "valid_through": "2026-10-08", "method": "v1"},
}
backtest._save_tracker(other)
assert backtest.pending_buystop_by_ticker() == {}
backtest._save_tracker({**other, "EXPD_2026-10-05_buystop": rec, "EXPD_2026-10-03_buystop": {**rec, "entry_date": "2026-10-03", "valid_through": "2026-10-09"}})
assert backtest.pending_buystop_by_ticker()["EXPD"]["entry_date"] == "2026-10-05"                  # при няколко чакащи — най-скорошният
orig = backtest._load_tracker
backtest._load_tracker = lambda: (_ for _ in ()).throw(RuntimeError("счупен файл"))
assert backtest.pending_buystop_by_ticker() == {}
backtest._load_tracker = orig
print("  ✓ само v2 + категория buystop + статус pending; отворен, Action и v1 запис не се броят; при няколко — най-скорошният; провал на четенето → {} (без изключение)")

print()
print("── страницата (РЕАЛНИЯТ бриф от 05.10 с картата на EXPD от 06.10) ──")
def page(card):
    b = copy.deepcopy(B05)
    b["watchlist"] = [card if x["ticker"] == "EXPD" else x for x in b["watchlist"]]
    return re.sub(r"\s+", " ", htmllib.unescape(render.render_dashboard(b)))
p1 = page(c1)
assert "🎯 Buy-stop $194.59 · валиден до 09.10, от 05.10 · таван за вход" in p1 and "(валиден до 09.10, от 05.10 — 5 сесии от първия ден)" in p1
p0 = page(c0)
assert "🎯 Buy-stop $194.59 · валиден до 2026-10-12 · таван за вход" in p0 and "от първия ден" not in p0
print("  ✓ с книга: '🎯 Buy-stop $194.59 · валиден до 09.10, от 05.10' и 'Сетъп: … (валиден до 09.10, от 05.10 — 5 сесии от първия ден)'; без книга — както преди ('до 2026-10-12')")

print()
print("── main.run (структурно) ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
tree = ast.parse(src)
run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
calls = [n for n in ast.walk(run) if isinstance(n, ast.Call) and ast.unparse(n.func) == "setup_rules.annotate"]
assert len(calls) == 1 and [ast.unparse(a) for a in calls[0].args] == ["candidates", "today", "backtest.live_buystop_by_ticker()"]
assert src.index("setup_rules.annotate(candidates") < src.index("ai_brief.ticker_narratives(")
print("  ✓ run(): annotate получава чакащите записи на книгата ПРЕДИ AI синтеза (промптът цитира същия текст)")
print()
print("Всички тестове минаха.")
