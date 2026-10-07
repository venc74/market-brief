"""
Наблюдавани тикъри (08.10.2026): BLSH е махнат от data/watch_list.json (списъкът е празен), а секцията ОСТАВА — с ред "Списъкът е празен" вместо да изчезне мълчаливо (преди `{% if watch %}` я скриваше и
не личеше дали е проверена). Нови тикъри ще се добавят по-късно в същия файл. Изключен модул (ENABLE_WATCH_MONITOR=0) пак не показва секцията.

РЕАЛНО: базовият бриф е реалният от 05.10.2026 (tests/fixtures/brief_2026-10-05.json). СИНТЕТИЧНО: празният списък, един тикър "TEST" с карта без събития, изключеният модул — маркирани. Не чете реалния
data/watch_list.json (изолация на тестовете): структурата на файла се проверява върху временно копие със същия вид (ръчна _note + празен списък).
Пускане: python test_watch_empty.py
"""
import sys, re, json, copy, pathlib, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import render, watch_monitor, backtest

config.ENABLE_BACKTEST = False
tmp = pathlib.Path(tempfile.mkdtemp(prefix="mb_wl_"))
config.DOCS_DIR, config.DATA_DIR = tmp / "docs", tmp / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))


def text(brief):
    page = render.render_dashboard(brief)
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>", " ", page, flags=re.S))).split())


print("── списъкът: празен файл със същия вид (СИНТЕТИЧНО копие: ръчна _note + tickers: []) ──")
wl = config.DATA_DIR / "watch_list.json"
wl.write_text(json.dumps({"_note": "Ръчно поддържан списък за секцията '🔎 Наблюдавани тикъри'.", "tickers": []}, ensure_ascii=False, indent=1), encoding="utf-8")
watch_monitor._LIST_PATH = wl
assert watch_monitor.load_watch_list() == [] and watch_monitor.collect() == []                 # без мрежа: празен списък → нула заявки
wl.write_text(json.dumps({"tickers": ["blsh", " test "]}), encoding="utf-8")
assert watch_monitor.load_watch_list() == ["BLSH", "TEST"]                                      # добавянето по-късно продължава да работи
print("  ✓ празен списък → [] и collect() връща [] без заявки; добавени по-късно тикъри пак се четат (главни букви, без интервали)")

print()
print("── секцията в страницата ──")
b = copy.deepcopy(B05)
b["watch"] = []
config.ENABLE_WATCH_MONITOR = True
t = text(b)
assert "Наблюдавани тикъри · последните 24ч" in t and "Списъкът е празен — тикъри се добавят в data/watch_list.json" in t
assert "Няма значими събития" not in t
print("  ✓ празен списък, модулът е включен: заглавието 'Наблюдавани тикъри' остава с ред 'Списъкът е празен — тикъри се добавят в data/watch_list.json…'")
b["watch"] = [{"ticker": "TEST", "news": [], "insider": [], "insider_cluster": False, "quiet": True}]
t = text(b)
assert "Наблюдавани тикъри · последните 24ч" in t and "TEST" in t and "Списъкът е празен" not in t and "Няма значими събития" in t
print("  ✓ СИНТЕТИЧНО: един тикър без събития → картата 'TEST' с 'Няма значими събития…', без реда за празен списък")
b["watch"] = []
config.ENABLE_WATCH_MONITOR = False
t = text(b)
assert "Наблюдавани тикъри · последните 24ч" not in t and "Списъкът е празен" not in t
print("  ✓ СИНТЕТИЧНО: изключен модул (ENABLE_WATCH_MONITOR=0) → секцията не се показва")
print("\n✅ test_watch_empty: всичко мина")
