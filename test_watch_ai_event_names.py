"""
03.11.2026 · поправки след брифа, т. 5: наблюдаваните — AI коментар само при новина или Form 4 СЪБИТИЕ (подаден от предишния бриф); без събитие → без AI ред. На 03.11 BFLY, ELF и ACN
получиха „Няма новини за последните 24 часа — само insider транзакции“ заради Form 4 отпреди 1–5 седмици. И имената на хора — само дословно от таблицата: EDGAR пише инсайдъра
„Фамилия Име Презиме“ („Sweet Julie Spellman“), а моделът на 03.11 написа „Julie Spellman“, „Paula Price“, „Ryoji Sekido“ (ACN) и „Tarang Amin“ (ELF). Сега: правило в промпта
и поправка от кода (ai_brief.fix_person_names) — преподредено / непълно име на инсайдър → дословното име; име без общи думи с входа → само ред в лога (може да е „Wall Street“).
Измерено върху всички AI текстове за наблюдаваните 29.10–03.11: 12 замени (всички — имена на инсайдъри), 4 само в лога („Bitcoin Futures“, „Treasury Bond“), 0 махнати изречения.

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

print("── 1. fix_person_names — РЕАЛНИЯТ текст на модела от 03.11 ──")
def check(t, k):
    r = FX[t]
    owners = list(dict.fromkeys(x["owner_name"] for x in r["insider"]))
    blob = " ".join([t, r.get("name") or ""] + [x.get("owner_title") or "" for x in r["insider"]] + [f"{n['title']} {n.get('publisher', '')}" for n in r["news"]])
    return ai_brief.fix_person_names(r["ai"][k], owners, blob)
acn_s, n1 = check("ACN", "summary")
acn_i, n2 = check("ACN", "insider_read")
assert "Julie Spellman" in FX["ACN"]["ai"]["summary"] and "Sweet Julie Spellman" not in FX["ACN"]["ai"]["summary"]                  # РЕАЛНО: грешното име
assert "CEO Sweet Julie Spellman" in acn_s and "Price Paula A" in acn_s and "Paula Price" not in acn_s
assert "Sekido Ryoji" in acn_i and "Ryoji Sekido" not in acn_i and "Sweet Julie Spellman" in acn_i
assert n1 == ["«Julie Spellman» → «Sweet Julie Spellman» (дословно от Form 4)", "«Paula Price» → «Price Paula A» (дословно от Form 4)"], n1
elf, n3 = check("ELF", "insider_read")
assert "AMIN TARANG" in elf and n3 == ["«Tarang Amin» → «AMIN TARANG» (дословно от Form 4)"], n3
bm, n4 = check("BMNR", "cross_reference")
assert bm == FX["BMNR"]["ai"]["cross_reference"] and n4 == ["«Bitcoin Futures» — няма го във входа (само лог)"]                        # не е име на човек — остава
assert ai_brief.fix_person_names("CEO Sweet Julie Spellman купи.", ["Sweet Julie Spellman"], "")[0] == "CEO Sweet Julie Spellman купи."   # дословното — без промяна
print("  ✓ ACN: „Julie Spellman“ → „Sweet Julie Spellman“, „Paula Price“ → „Price Paula A“, „Ryoji Sekido“ → „Sekido Ryoji“; ELF: „Tarang Amin“ → „AMIN TARANG“")
print("  ✓ BMNR: „Bitcoin Futures“ остава (само лог); дословното име не се пипа")

print()
print("── 2. _watch_digest_batch — правилото в промпта и поправката (СИНТЕТИЧНО: AI повикването връща РЕАЛНИЯ текст от 03.11) ──")
sent = []
reply = {"digests": [{"ticker": "ACN", **{k: FX["ACN"]["ai"][k] for k in ("summary", "insider_read", "cross_reference")}}]}
ai_brief._call_claude = lambda system, user, **k: (sent.append(user), json.dumps(reply, ensure_ascii=False))[1]
row = {k: v for k, v in copy.deepcopy(FX["ACN"]).items() if k != "ai"}
with q() as log:
    out = ai_brief._watch_digest_batch([row], {"cot_markets": [], "leading_sectors": []}, 24)
assert "ИМЕНА НА ХОРА — САМО дословно от таблицата" in sent[0] and "„Sweet Julie Spellman“" in sent[0]
assert "Sweet Julie Spellman" in out[0]["ai"]["summary"] and "Sekido Ryoji" in out[0]["ai"]["insider_read"]
assert "[ai] watch ACN summary: «Julie Spellman» → «Sweet Julie Spellman» (дословно от Form 4)" in log.getvalue()
print("  ✓ промптът казва правилото с примера; отговорът се поправя преди страницата, с ред в лога")

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
