"""
Пакет 1б (2026-10-05) · точка 5 (показване): блокът на dashboard-а е надписан "Buy-stop кандидати — измерване, не препоръка"; win rate се показва чак при ≥ 20 затворени
(дотогава — броят и средният R), редовете носят "и Action" и таг на режима; Action секцията "Track Record v2" остава непроменена, а бриф без ключа "buystop" (по-стар
или изключена функция) се рендира без блока и без грешка.

РЕАЛНО: брифът от 05.10.2026 (tests/fixtures/brief_2026-10-05.json) — всичко извън новия блок. СИНТЕТИЧНО: записите на buy-stop книгата (T01…), обобщенията от тях
(backtest.get_buystop_summary върху временен tracker), подменените директории docs/ и data/.
Пускане: python test_buystop_render.py
"""
import sys, json, pathlib, tempfile, copy, html as htmllib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import backtest, render

_tmp = tempfile.TemporaryDirectory(prefix="mb_bsd_")
DOCS, DATA = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
DOCS.mkdir(); DATA.mkdir()
config.DOCS_DIR, config.DATA_DIR = DOCS, DATA
backtest._TRACKER_PATH = DATA / "backtest_tracker.json"
backtest.yf.download = lambda *a, **k: (_ for _ in ()).throw(AssertionError("без мрежа"))

BRIEF = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
_n = [0]


def rec(status, r=None, regime="Defensive", category="buystop", day="2026-09-10", res=None):
    _n[0] += 1
    t = f"T{_n[0]:02d}"
    k = f"{t}_{day}_{category or 'a'}"
    d = {"method": "v2", "ticker": t, "entry_date": day, "status": status, "buy_stop": 100.0, "max_chase": 105.0, "stop_loss": 92.0, "target_1": 116.0,
         "valid_through": "2026-09-16", "fill_date": None if status in ("pending", "not_triggered") else day, "fill_price": 100.0, "realized_r": r,
         "current_r": None, "resolution_date": res, "regime": regime, "return_pct": None, "spy_return_pct": None}
    if category:
        d["category"] = category
    return k, d


def page(items, with_key=True):
    backtest._save_tracker(dict(items))
    brief = copy.deepcopy(BRIEF)
    if with_key:
        brief["backtest"] = {**brief["backtest"], "buystop": backtest.get_buystop_summary()}
    return " ".join(htmllib.unescape(render.render_dashboard(brief)).split())


def section(txt):
    m = re.search(r"<h2>Buy-stop кандидати — измерване, не препоръка</h2>(.*?)</section>", txt)
    return m.group(1) if m else None


TITLE = "Buy-stop кандидати — измерване, не препоръка"

print("── празна книга ──")
p = page([])
s = section(p)
assert s and "Още няма записани кандидати" in s and "Win rate" not in s
assert f"<h2>{TITLE}</h2>" in p and "Не са позиции и не са съвет за покупка" in s and "в рамките на 5 сесии" in s and "не над +5%" in s
print("  ✓ заглавието е 'Buy-stop кандидати — измерване, не препоръка'; празно състояние; бележка 'не са позиции и не са съвет за покупка', прозорец 5 сесии, таван +5%")

print()
print("── 14 затворени: без win rate ──")
items = [rec("stopped", -1.0, res=f"2026-09-{12 + i:02d}") for i in range(13)] + [rec("trailing_stop_exit", 1.57, res="2026-09-28")]
items += [rec("pending") , rec("open", regime="Offensive"), rec("not_triggered", res="2026-09-16")]
p = page(items); s = section(p)
assert "Записани: 17" in s and "затворени 14" in s and "не се задействаха 1" in s
assert "Затворени: 14 · среден R: -0.82" in s
assert "Win rate:" not in s and "Win rate се показва след 20 затворени (сега 14)" in s and "Спрямо SPY" not in s and "медиана" not in s
assert "Defensive 16 / 14" in s and "Offensive 1 / 0" in s and "R)" not in s.split("По режим")[1].split("</div>")[0]
print("  ✓ 17 записа, 14 затворени, среден R −0.82; 'Win rate се показва след 20 затворени (сега 14)'; няма win rate, медиана и SPY; режимите са само бройки")
assert "Чакащи и отворени (2)" in s and "чака buy-stop" in s and "отворена от 2026-09-10" in s and "Последни затворени (10)" in s
assert "стоп" in s and "trailing изход" in s
print("  ✓ таблицата 'Чакащи и отворени' (чака buy-stop / отворена от …) и 'Последни затворени (10)' с български етикети на изхода")

print()
print("── 20 затворени: win rate, интервал, медиана ──")
items = [rec("stopped", -1.0, res=f"2026-09-{10 + i:02d}") for i in range(18)] + [rec("trailing_stop_exit", 1.5, res="2026-09-29"), rec("trailing_stop_exit", 2.0, res="2026-09-30")]
p = page(items); s = section(p)
assert "Win rate: 10.0%" in s and "(2 win / 18 loss; 95% интервал 2.8–30.1%)" in s and "медиана R -1.00" in s
avg_def = round((18 * -1.0 + 1.5 + 2.0) / 20, 2)                                                       # независима сметка за Defensive: 20 затворени
assert "Win rate се показва след" not in s and f"Defensive 20 / 20 ({avg_def:+.2f}R)" in s, s.split("По режим")[1][:200]
print("  ✓ при 20 затворени: 'Win rate: 10.0% (2 win / 18 loss; 95% интервал 2.8–30.1%) · медиана R −1.00', и среден R по режим")

print()
print("── 'и Action' и режим на редовете ──")
k_b, v_b = rec("open", regime="Cash", day="2026-10-01")
k_a, v_a = rec("open", category=None, day="2026-10-02")
v_a["ticker"] = v_b["ticker"]; k_a = f"{v_a['ticker']}_2026-10-02_a"
p = page([(k_b, v_b), (k_a, v_a)]); s = section(p)
assert s.count("и Action") >= 2 and ">Cash</td>" in s and v_b["ticker"] in s
print("  ✓ тикър и в двете книги → маркер 'и Action' на реда; режимът на картата (Cash) е в таблицата")

print()
print("── Action секцията и стар бриф ──")
act_before = re.search(r"<h2>Track Record v2.*?</section>", page([], with_key=False)).group(0)
act_after = re.search(r"<h2>Track Record v2.*?</section>", page([rec('open'), rec('stopped', -1.0, res='2026-09-20')])).group(0)
assert act_before == act_after
p_old = page([], with_key=False)
assert section(p_old) is None and TITLE not in p_old
print("  ✓ секцията 'Track Record v2' е бит-в-бит същата с и без buy-stop книгата; бриф без ключа 'buystop' (по-стар бриф) се рендира без блока")

print()
print("Всички тестове минаха.")
