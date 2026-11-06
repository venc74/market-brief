"""
06.11.2026 (пакет 05–06.11, т. 9): коментарите на наблюдаваните — само преразказ на дадените новини / Form 4, без собствени обяснения на причините (lock-up, мотиви на мениджъри); имена на хора — само длъжности.
Реално, 05.11: CRCL „по-вероятното обяснение е координирано ликвидиране след IPO lock-up изтичане“ и „комбинация, която сигнализира фокус върху маржа“; SIRI „Buffett продължава да добавя“. Върху 120-те текста
(от началото на секцията до 06.11) проверката маха 6 парчета: TDOC ×2, BLSH, CRCL ×2, SIRI.

РЕАЛНО: tests/fixtures/watch_causes_2026-11-05.json — коментарите, заглавията и Form 4 на CRCL и SIRI.
СИНТЕТИЧНО (означено): кратките изречения в т. 2, отговорът на модела в т. 3.
Пускане: python test_watch_causes.py
"""
import sys, json, pathlib, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_watchcauses_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import ai_brief as ab

FX = json.loads((ROOT / "tests" / "fixtures" / "watch_causes_2026-11-05.json").read_text(encoding="utf-8"))["rows"]
titles = lambda t: " ".join(n["title"] for n in FX[t]["news"])

print("── 1. РЕАЛНИТЕ коментари от 05.11 ──")
new, g = ab.strip_watch_causes(FX["CRCL"]["ai"]["summary"], titles("CRCL"))
assert "сигнализира" not in new and new.startswith("Circle отчете Q3 над очакванията, подкрепен от продажбата на Arc Token, и съкрати 5% от персонала.") and [x["term"] for x in g] == ["сигнализира"]
new, g = ab.strip_watch_causes(FX["CRCL"]["ai"]["insider_read"], titles("CRCL"))
assert "lock-up" not in new and "обяснение" not in new and "10b5-1" in new and g                     # фактите от Form 4 остават
new, g = ab.strip_watch_causes(FX["SIRI"]["ai"]["insider_read"], titles("SIRI"))
assert "Buffett" not in new and new.startswith("Трите покупки са от Berkshire Hathaway") and [x["term"] for x in g] == ["Buffett"]
assert ab.strip_watch_causes(FX["SIRI"]["ai"]["summary"], titles("SIRI"))[1] == []                    # преразказът на заглавията остава непокътнат
print("  ✓ CRCL: без „сигнализира“ и „lock-up“; SIRI: без „Buffett“; фактите и преразказът остават")

print("── 2. границите (СИНТЕТИЧНО) ──")
s = ab.strip_watch_causes
assert s("Няма новини.", "")[0] == "Няма новини." and s("", "") == ("", []) and s(None, "") == (None, [])
assert s("Компанията обяви lock-up за 90 дни.", "Company announces 90-day lock-up")[1] == []           # думата е в заглавието
assert s("Компанията обяви lock-up за 90 дни.", "Company reports earnings")[0] == ""                   # няма я — цялото изречение
assert s("Продажбата е умерена и не сигнализира изход от позицията.", "")[1] == []                     # отрицание — не е обяснение
assert s("Cathie Wood добави акции.", "Cathie Wood buys more")[1] == []                                # името е в заглавието: не е измислено (длъжностите — от промпта)
assert s("Кратко — знак за нещо.", "")[0] == ""                                                         # първата част е твърде къса — цялото изречение
print("  ✓ думата от заглавие остава; отрицанието — не е обяснение; къса първа част — цялото изречение")

print("── 3. промптът и веригата (СИНТЕТИЧЕН отговор) ──")
assert "без собствени обяснения на причините" in ab.SYSTEM_WATCH and "не преразказваш" not in ab.SYSTEM_WATCH
seen = {}


def fake(system, user, max_tokens=0, **k):
    seen["user"] = user
    return json.dumps({"digests": [{"ticker": "SIRI", "summary": "Berkshire купи още. По-вероятното обяснение е доверие.", "insider_read": "Трите покупки са извън план.", "cross_reference": ""}]}, ensure_ascii=False)


ab._call_claude = fake
row = {"ticker": "SIRI", "news": FX["SIRI"]["news"], "insider": [], "insider_cluster": False, "insider_flags": []}
with contextlib.redirect_stdout(io.StringIO()):
    out = ab._watch_digest_batch([row], {}, 24)
assert "САМО ПРЕРАЗКАЗ" in seen["user"] and "ликвидност/данъци" not in seen["user"] and "не гадай защо е продажбата" in seen["user"]
assert out[0]["ai"]["summary"] == "Berkshire купи още." and out[0]["ai_removed"][0]["field"] == "summary" and "ai_removed" in out[0]
print("  ✓ промптът е без подсказката „ликвидност/данъци“; изречението без опора пада, записът е в „ai_removed“")
print("\n✅ test_watch_causes: всичко мина")
