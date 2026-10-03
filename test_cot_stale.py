"""
Пакет 2 · т.7 (2026-10-03): давност на COT — ако най-новият отчет е по-стар от config.COT_STALE_DAYS (13 дни), секцията "COT
Екстремуми" показва банер (спряна/забавена публикация на CFTC, провалено теглене — кешът мълчаливо остава със стари данни).

Праг: потребителят поиска "~12 дни"; реалните данни показват, че 12 дава фалшива тревога в празнична седмица, затова е 13 (виж
config.py). РЕАЛНО: възрастта на най-новия COT отчет в 65 брифа с COT редове (06.07 → 02.10.2026, прочетено от data/ на 03.10.2026):
6–10 дни в 64 от тях и 13 дни на 06.07.2026 (отчет 23.06; 3 юли беше почивен, излизането се мести в понеделник); COT редовете и
as_of на брифовете от 22.09 и 02.10 (tests/fixtures); реалният кеш data/cot_cache.json към 03.10.2026: последен отчет 22.09 (11 дни).
СИНТЕТИЧНО: кешовете с пазар "Gold" (20 седмици), датите на "днес", празният кеш, провалът на теглене.
Пускане: python test_cot_stale.py
"""
import sys, pathlib, json, tempfile, datetime as dt, html as htmllib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import cot, render

D = dt.date.fromisoformat
FIX = ROOT / "tests" / "fixtures"

print("── прагът (РЕАЛНИ дати) ──")
assert config.COT_STALE_DAYS == 13
resolved = [("Gold", "disaggregated", "GOLD - COMMODITY EXCHANGE INC.")]
def cache_with(last_date):
    start = D(last_date) - dt.timedelta(weeks=19)
    return {"disaggregated": {"GOLD - COMMODITY EXCHANGE INC.": [
        {"date": (start + dt.timedelta(weeks=i)).isoformat(), "net": 1000.0 + i} for i in range(20)]}, "tff": {}}

# реални случаи: (дата на брифа, най-нов отчет, възраст)
for brief_day, as_of, age, stale in (("2026-10-02", "2026-09-22", 10, False),        # петък сутрин преди излизането (брифът от 02.10)
                                     ("2026-09-22", "2026-09-15", 7, False),
                                     ("2026-07-06", "2026-06-23", 13, False)):       # празничен петък 3 юли → излизане в понеделник
    f = cot.freshness(cache_with(as_of), resolved, D(brief_day))
    assert (f["as_of"], f["age_days"], f["stale"]) == (as_of, age, stale), (brief_day, f)
print("  ✓ РЕАЛНО: 02.10 (отчет 22.09, 10 дни) и 22.09 (15.09, 7 дни) → не са стари; 06.07 (23.06, 13 дни, празничен петък) → не е стар")
config.COT_STALE_DAYS = 12
assert cot.freshness(cache_with("2026-06-23"), resolved, D("2026-07-06"))["stale"] is True         # с праг 12 06.07 би дал фалшива тревога
config.COT_STALE_DAYS = 13
print("  ✓ с праг 12 брифът от 06.07 (13 дни) щеше да получи банер без причина — затова 13")
assert cot.freshness(cache_with("2026-06-22"), resolved, D("2026-07-06"))["stale"] is True            # 14 дни → стар
assert cot.freshness(cache_with("2026-09-22"), resolved, D("2026-10-03"))["stale"] is False           # реалният кеш: 11 дни към 03.10
assert cot.freshness(cache_with("2026-09-22"), resolved, D("2026-10-06"))["stale"] is True            # ако 29.09 не бъде публикуван до вторник: 14 дни
print("  ✓ границата: 13 дни не е стар, 14 е; реалният кеш (последен отчет 22.09) е 11 дни на 03.10 → не е стар")
brief_cot = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))["cot"]
assert {c["as_of"] for c in brief_cot} == {"2026-09-22"} and len(brief_cot) == 18                       # РЕАЛНО: всички 18 реда са към 22.09
print("  ✓ РЕАЛНО: и осемнадесетте COT реда в брифа от 02.10 са към 22.09 (10 дни)")
print()

_orig_get = cot.get_extremes
def _quiet_get(*a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return _orig_get(*a, **k)
cot.get_extremes = _quiet_get
print("── get_extremes() записва статуса (СИНТЕТИЧЕН кеш: Gold, 20 седмици, резки стойности) ──")
cot.refresh_cache = lambda: cache_with("2026-08-25")
# последната седмица е екстремум: нетната позиция скача
c = cache_with("2026-08-25"); c["disaggregated"]["GOLD - COMMODITY EXCHANGE INC."][-1]["net"] = 99999.0
cot.refresh_cache = lambda: c
ext = cot.get_extremes(today=D("2026-10-03"))
st = cot.LAST_STATUS
assert [e["market"] for e in ext] == ["Gold"] and ext[0]["as_of"] == "2026-08-25"                       # екстремумът се връща и когато е стар
assert st["stale"] is True and st["as_of"] == "2026-08-25" and st["age_days"] == 39 and st["threshold_days"] == 13 and st["reason"] == "stale"
print("  ✓ данни към 25.08, днес 03.10: екстремумът още се връща (Gold), но LAST_STATUS = stale, 39 дни, праг 13")
c2 = cache_with("2026-09-29"); c2["disaggregated"]["GOLD - COMMODITY EXCHANGE INC."][-1]["net"] = 99999.0
cot.refresh_cache = lambda: c2
ext = cot.get_extremes(today=D("2026-10-03"))
assert [e["market"] for e in ext] == ["Gold"] and cot.LAST_STATUS["stale"] is False and cot.LAST_STATUS["age_days"] == 4 and cot.LAST_STATUS["reason"] == ""
print("  ✓ данни към 29.09 → не е стар (4 дни), reason празен")
cot.refresh_cache = lambda: {"tff": {}, "disaggregated": {}}
assert cot.get_extremes(today=D("2026-10-03")) == [] and cot.LAST_STATUS["stale"] is True and cot.LAST_STATUS["reason"] == "no_data" and cot.LAST_STATUS["as_of"] is None
def boom():
    raise ConnectionError("CFTC down")
cot.refresh_cache = boom
assert cot.get_extremes(today=D("2026-10-03")) == [] and cot.LAST_STATUS["reason"] == "no_data" and cot.LAST_STATUS["stale"] is True
print("  ✓ празен кеш или изключение при теглене → [] и stale с причина 'no_data' (без изключение)")
print()

print("── рендер: банерът в секцията (РЕАЛЕН бриф от 02.10, СИНТЕТИЧЕН статус) ──")
brief = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
assert "cot_status" not in brief                                                                          # старите брифове нямат поле → без банер


def page(b):
    with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
        o1, o2 = config.DOCS_DIR, config.DATA_DIR
        config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
        try:
            return htmllib.unescape(render.render_dashboard(b))
        finally:
            config.DOCS_DIR, config.DATA_DIR = o1, o2

assert "COT данните са остарели" not in page(brief)
b2 = dict(brief); b2["cot_status"] = {"as_of": "2026-09-22", "age_days": 10, "stale": False, "threshold_days": 13, "reason": ""}
assert "COT данните са остарели" not in page(b2)
b3 = dict(brief); b3["cot_status"] = {"as_of": "2026-09-08", "age_days": 24, "stale": True, "threshold_days": 13, "reason": "stale"}
h3 = page(b3)
assert "COT данните са остарели" in h3 and "последният отчет е към 2026-09-08 (24 дни назад; нормално 6–10, праг 13)" in h3
assert h3.count("COT Екстремуми") == 1 and "30-Year Treasury Bond" in h3                                # секцията е една и редовете са на мястото си
b4 = dict(brief); b4["cot"] = []; b4["cot_status"] = {"as_of": "2026-09-08", "age_days": 24, "stale": True, "threshold_days": 13, "reason": "stale"}
h4 = page(b4)
assert "COT данните са остарели" in h4 and "Няма показани екстремуми" in h4                              # банерът се показва и без редове
b5 = dict(brief); b5["cot"] = []; b5["cot_status"] = {"as_of": None, "age_days": None, "stale": True, "threshold_days": 13, "reason": "no_data"}
h5 = page(b5)
assert "няма налични данни (кешът е празен или CFTC е недостъпна)" in h5
b6 = dict(brief); b6["cot"] = []
assert "COT Екстремуми" not in page(b6)                                                                    # празно и без статус → секцията се крие, както досега
print("  ✓ без статус / свеж статус → без банер; стар статус → банер с датата и възрастта в секцията с РЕАЛНИТЕ 18 реда;")
print("    стар статус без редове → секция само с банера; няма данни → отделен текст; празно и без статус → секцията се крие както досега")
print()

print("── main.py ──")
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert '"cot_status": dict(cot.LAST_STATUS) if config.ENABLE_COT else {}' in main_src
print("  ✓ брифът носи cot_status (празен, ако COT е изключен)")
print()
print("Всички тестове минаха.")
