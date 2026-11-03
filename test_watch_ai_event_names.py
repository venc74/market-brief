"""
03.11.2026 · поправки след брифа, т. 5: наблюдаваните — AI коментар само при новина или Form 4 СЪБИТИЕ (подаден от предишния бриф); без събитие → без AI ред. На 03.11 BFLY, ELF и ACN
получиха „Няма новини за последните 24 часа — само insider транзакции“ заради Form 4 отпреди 1–5 седмици. И БЕЗ имена на хора (прегледът на 03.11): само длъжността — името е в
таблицата. Моделът пишеше „Julie Spellman“, „Paula Price“, „Ryoji Sekido“ (ACN), „Catapano Joseph Ronald“ (дословно, TDOC), „Franks“ (ELF). Правило в промпта и поправка от кода
(ai_brief.strip_person_names): име на ЧОВЕК-инсайдър от Form 4 (≥ 2 думи от името, фамилията сама или дума след длъжност) → махнато, ако длъжността е точно преди него, иначе →
длъжността му на български (role_bg). Фирма-инсайдър (NIPPON LIFE INSURANCE CO) — остава. Измерено върху всички AI текстове за наблюдаваните 29.10–03.11: 38 замени, нито една
останала фамилия от Form 4.

РЕАЛНО: tests/fixtures/watch_ai_2026-11-03.json — редовете на ACN, ELF, BMNR, BFLY, DOCU от брифа на 03.11 (новините, Form 4, AI текстът на модела).
СИНТЕТИЧНО (означено): датите на подаване ("filed" — полето е ново), подмененото AI повикване (връща РЕАЛНИЯ текст на модела), фактите / Form 4 тегленето в т. 3.
Пускане: python test_watch_ai_event_names.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_watch_ai_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import ai_brief, watch_monitor as wm

FX = {r["ticker"]: r for r in json.loads((ROOT / "tests" / "fixtures" / "watch_ai_2026-11-03.json").read_text(encoding="utf-8"))["rows"]}
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. strip_person_names — РЕАЛНИЯТ текст на модела от 03.11 ──")
strip = lambda t, k: ai_brief.strip_person_names(FX[t]["ai"][k], FX[t]["insider"])
acn_s, n1 = strip("ACN", "summary")
acn_i, n2 = strip("ACN", "insider_read")
assert "CEO Julie Spellman" in FX["ACN"]["ai"]["summary"]                                                                             # РЕАЛНО: името в текста
assert "Периодът покрива покупки от CEO и директор, както и продажби от няколко ръководители." in acn_s
assert not any(n in acn_s + acn_i for n in ("Spellman", "Sweet", "Paula", "Price Paula", "Sekido", "Ryoji", "Hogan"))
assert "съизпълнителен директор (Co-CEO Asia Pacific) е продал извънпланово" in acn_i and "CEO е купила извънпланово" in acn_i
assert n2[0] == "«Ryoji Sekido» → «съизпълнителен директор»", n2
elf, n3 = strip("ELF", "insider_read")
assert "CEO продаде" in elf and "SVP Operations продаде" in elf and "Amin" not in elf and "Franks" not in elf and "Tarang" not in elf
assert strip("BMNR", "cross_reference")[0] == FX["BMNR"]["ai"]["cross_reference"]                                                  # без инсайдъри — нищо не се пипа
nippon = [{"owner_name": "NIPPON LIFE INSURANCE CO", "owner_title": "10% Owner"}]
assert ai_brief.strip_person_names("Nippon Life Insurance купува всеки ден.", nippon)[0] == "Nippon Life Insurance купува всеки ден."   # фирма — остава
assert [ai_brief.role_bg(t) for t in ("Chair and CEO", "Chief Financial Officer", "Co-CEO Asia Pacific", "Chief Accounting Officer", "SVP Operations")] == \
    ["изпълнителен директор", "финансов директор", "съизпълнителен директор", "главен счетоводител", "вицепрезидент"]
assert ai_brief.role_bg("", True) == "член на борда" and ai_brief.role_bg(None) == "инсайдър"
print("  ✓ ACN: „покупки от CEO и директор“ (без имената), „съизпълнителен директор (Co-CEO Asia Pacific) е продал“, „CEO е купила“; ELF: „CEO продаде“, „SVP Operations продаде“")
print("  ✓ фирма-инсайдър (Nippon Life) — остава; длъжностите на български от Form 4")

print()
print("── 2. _watch_digest_batch — правилото в промпта и поправката (СИНТЕТИЧНО: AI повикването връща РЕАЛНИЯ текст от 03.11) ──")
sent = []
reply = {"digests": [{"ticker": "ACN", **{k: FX["ACN"]["ai"][k] for k in ("summary", "insider_read", "cross_reference")}}]}
ai_brief._call_claude = lambda system, user, **k: (sent.append(user), json.dumps(reply, ensure_ascii=False))[1]
row = {k: v for k, v in copy.deepcopy(FX["ACN"]).items() if k != "ai"}
with q() as log:
    out = ai_brief._watch_digest_batch([row], {"cot_markets": [], "leading_sectors": []}, 24)
assert "БЕЗ ИМЕНА НА ХОРА — пиши САМО длъжността на български" in sent[0] and "Sweet Julie Spellman" not in sent[0].split("НАБЛЮДАВАНИ ТИКЪРИ")[0]
assert "Spellman" not in out[0]["ai"]["summary"] and "Sekido" not in out[0]["ai"]["insider_read"] and "съизпълнителен директор" in out[0]["ai"]["insider_read"]
assert "[ai] watch ACN summary: «Julie Spellman» — махнато (длъжността е преди него)" in log.getvalue()
print("  ✓ промптът казва правилото; отговорът се поправя преди страницата, с ред в лога")

print()
print("── 3. събитие: новина или Form 4, подаден в прозореца (СИНТЕТИЧНО: датите на подаване и тегленето) ──")
today = dt.datetime.now(dt.timezone.utc).date()
recent, old = (today - dt.timedelta(days=0)).isoformat(), (today - dt.timedelta(days=9)).isoformat()
ins = {"ACN": [{**t, "date": dt.date.fromisoformat(t["date"]), "filed": old} for t in FX["ACN"]["insider"]],                                    # само стари
       "ELF": [{**t, "date": dt.date.fromisoformat(t["date"]), "filed": recent if i == 0 else old} for i, t in enumerate(FX["ELF"]["insider"])],     # един нов
       "BFLY": [{**t, "date": dt.date.fromisoformat(t["date"])} for t in FX["BFLY"]["insider"]]}                                                 # без "filed" — не е нов
wm.insider_buying.fetch_insider_transactions = lambda ts: {t: ins.get(t, []) for t in ts}
wm._recent_news = lambda t, h, keys=None: [{"title": n["title"], "publisher": n.get("publisher", "")} for n in FX[t]["news"]]
with q():
    rows = wm.collect(["ACN", "ELF", "BFLY", "BMNR", "DOCU"], facts_fn=lambda ts: {t: {"name": t} for t in ts}, window_hours=24)
ev = {r["ticker"]: (r["event"], r["f4_new"], r["quiet"]) for r in rows}
assert ev == {"ACN": (False, 0, False), "ELF": (True, 1, False), "BFLY": (False, 0, False), "BMNR": (True, 0, False), "DOCU": (False, 0, True)}, ev
main_src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'active = [r for r in rows if r.get("event")]' in main_src
print("  ✓ ACN (Form 4 отпреди 9 дни) и BFLY (без дата) — без AI; ELF (нов Form 4) и BMNR (новини) — с AI; DOCU — тих; редът и Form 4 знамената остават за всички")
print("\n✅ test_watch_ai_event_names: всичко мина")
