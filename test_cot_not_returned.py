"""
Пакет 3 (добавка от 06.10) · пазар, който моделът не върне, не се губи мълчаливо: имена в COT_DIAG["not_returned"], статистика по партиди (поискани/върнати/токени), ЕДНО повторно извикване само за
липсващите (на порции до COT_BATCH_SIZE), банер в data_warnings, видим текст "моделът не върна пазара, следващият run опитва пак", суров отговор в лога при непълна партида (не в brief JSON).

Случаят от 06.10 (РЕАЛНО): 20 екстремума към 2026-09-29, четири COT извиквания (1688/1985/569/1631 токена, всички end_turn); третото (Corn, Australian Dollar, Natural Gas, Cocoa, British Pound) върна само
Corn → AUD, NatGas, Cocoa и GBP изчезнаха (старият код: "if not t: continue"; в диагностиката само extremes=20, theses=16).

РЕАЛНО: 20-те екстремума (tests/fixtures/cot_extremes_2026-09-29.json — cot.get_extremes() към отчета от 29.09), проверените имена на директните тикъри (tests/fixtures/cot_direct_tickers_2026-10-05.json),
реалният бриф от 05.10 за страницата. СИНТЕТИЧНО: ВСИЧКИ отговори на модела (празни списъци с тикъри — пресъздават само ФОРМАТА на отговора и кои пазари са върнати), токените, повторните отговори,
провалът на партида, временният кеш.
Пускане: python test_cot_not_returned.py
"""
import sys, json, pathlib, io, contextlib, re, ast, copy, datetime as dt, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import ai_brief, data_warnings, render

FIX = ROOT / "tests" / "fixtures"
EX = json.loads((FIX / "cot_extremes_2026-09-29.json").read_text(encoding="utf-8"))["extremes"]
for e in EX:
    e.setdefault("history", [])
CHK = json.loads((FIX / "cot_direct_tickers_2026-10-05.json").read_text(encoding="utf-8"))["checked"]
B05 = json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
NAMES = [e["market"] for e in EX]
assert len(EX) == 20 and {e["as_of"] for e in EX} == {"2026-09-29"}
BATCH3 = ["Corn", "Australian Dollar", "Natural Gas", "Cocoa", "British Pound"]
assert NAMES[10:15] == BATCH3

company = {t: r["name"] for t, r in CHK.items() if r["name"]}
for t in ("FXA", "FXB", "UNG", "EQT", "AR", "CORN", "BTCO", "IBIT", "FBTC", "GBTC", "HODL", "BITB"):
    company.setdefault(t, t)
ai_brief._verified_company_name = lambda t: {"name": company.get(t, t), "verified": True, "quote_type": (CHK.get(t) or {}).get("quote_type"),
                                              "category": (CHK.get(t) or {}).get("category"), "long_name": company.get(t), "sector": None, "industry": None}
config.COT_BATCH_SIZE = 5
TMP = tempfile.TemporaryDirectory(prefix="mb_cotnr_")
config.DATA_DIR = pathlib.Path(TMP.name)
config.DOCS_DIR = pathlib.Path(TMP.name) / "docs"
config.DOCS_DIR.mkdir()
REAL_CACHE = ROOT / "data" / "cot_theses_cache.json"
real_before = REAL_CACHE.read_bytes() if REAL_CACHE.exists() else None
D = dt.date.fromisoformat

state = {"calls": [], "omit": {}, "fail": set(), "tokens": [1688, 1985, 569, 1631, 400, 400, 400, 400, 400]}


def fake_claude(system, user, max_tokens=0):
    """СИНТЕТИЧЕН модел: връща запис (празен списък тикъри) за поискания пазар, освен ако не е в state["omit"][номер на извикването]; state["fail"] — извикването хвърля."""
    m = re.search(r"\):\s*(\[.*?\])\n\nВИД НА ПАЗАРА", user, re.S)
    markets = [b["market"] for b in json.loads(m.group(1))]
    i = len(state["calls"])
    state["calls"].append(markets)
    if i in state["fail"]:
        raise ConnectionError("API недостъпно")
    ret = [x for x in markets if x not in state["omit"].get(i, set())]
    text = json.dumps({"theses": [{"market": x, "tickers": []} for x in ret]}, ensure_ascii=False)
    ai_brief.AI_USAGE.append({"section": "COT тези", "model": config.CLAUDE_MODEL, "input_tokens": 3000, "output_tokens": state["tokens"][min(i, len(state["tokens"]) - 1)],
                              "max_tokens": max_tokens, "stop_reason": "end_turn"})
    return text


ai_brief._call_claude = fake_claude
cache = pathlib.Path(TMP.name) / "cache.json"


def run(day="2026-10-07", omit=None, fail=None, extremes=None):
    state.update(calls=[], omit=omit or {}, fail=fail or set())
    ai_brief.AI_USAGE.clear()
    cache.unlink(missing_ok=True) if day == "fresh" else None
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = ai_brief.cot_theses(extremes or EX, [], [], [], today=D(day if day != "fresh" else "2026-10-07"), cache_path=cache)
    return {c["market"]: c for c in out}, buf.getvalue()


print("── 06.10: третата партида връща само Corn (СИНТЕТИЧЕН отговор на модела; РЕАЛНИТЕ 20 екстремума) → повторно извикване само за 4-те липсващи ──")
omit3 = {2: {"Australian Dollar", "Natural Gas", "Cocoa", "British Pound"}}                       # третото извикване (индекс 2) пропуска 4 от 5
cache.unlink(missing_ok=True)
r, log = run("2026-10-07", omit=omit3)
assert len(state["calls"]) == 5 and state["calls"][4] == ["Australian Dollar", "Natural Gas", "Cocoa", "British Pound"]
d = ai_brief.COT_DIAG
assert d["not_returned"] == [] and d["retried"] == ["Australian Dollar", "Natural Gas", "Cocoa", "British Pound"] and d["recovered"] == d["retried"]
assert [(b["batch"], b["requested"], b["returned"], b["output_tokens"]) for b in d["batches"]] == [("1/4", 5, 5, 1688), ("2/4", 5, 5, 1985), ("3/4", 5, 1, 569), ("4/4", 5, 5, 1631), ("повторение 1/1", 4, 4, 400)]
assert d["batches"][4]["retry"] is True and all(b["status"] == "ok" for b in d["batches"])
assert len(r) == 20 and all(c["cross_sector_thesis"]["source"] == "generated" for c in r.values()) and d["cache"]["generated"] == 20 and d["cache"]["none"] == 0
assert "НЕПЪЛЕН отговор: поискани 5, върнати 1; липсват ['Australian Dollar', 'Natural Gas', 'Cocoa', 'British Pound']" in log and "→ 1 повторно извикване" in log
assert len(json.loads(cache.read_text(encoding="utf-8"))["entries"]) == 20
print("  ✓ 4 извиквания + 1 повторно (точно за AUD, NatGas, Cocoa, GBP); batches: 1/4 5→5 (1688 т.), 2/4 5→5, 3/4 5→1 (569 т.), 4/4 5→5, повторение 4→4; всичките 20 в кеша; not_returned празен")

print()
print("── повторението пак пропуска два пазара: имена, банер, текст, кеш, следващия ден ──")
omit_retry = {2: {"Australian Dollar", "Natural Gas", "Cocoa", "British Pound"}, 4: {"Cocoa", "British Pound"}}
cache.unlink(missing_ok=True)
r, log = run("2026-10-07", omit=omit_retry)
d = ai_brief.COT_DIAG
assert d["not_returned"] == ["Cocoa", "British Pound"] and d["recovered"] == ["Australian Dollar", "Natural Gas"] and len(state["calls"]) == 5
assert len(r) == 20 and d["extremes"] == 20 and d["theses"] == 20                                     # пазарът се показва, не се губи
for m in ("Cocoa", "British Pound"):
    x = r[m]["cross_sector_thesis"]
    assert x["empty_reason"] == "моделът не върна пазара, следващият run опитва пак" and x["source"] == "none" and not x["tickers"]
assert [t["ticker"] for t in r["British Pound"]["direct_thesis"]["tickers"]] == ["FXB"]                  # директната е от таблицата и остава
assert d["cache"]["generated"] == 18 and d["cache"]["none"] == 2 and len(json.loads(cache.read_text(encoding="utf-8"))["entries"]) == 18
assert "⚠ cot_theses: моделът не върна 2 от 20 пазара и след повторно извикване: ['Cocoa', 'British Pound']" in log
w = data_warnings.collect(None, None, cot_diag=d)
assert w == [{"source": "cot", "level": "warn", "message": "COT: моделът не върна теза за 2 от 20 пазара (Cocoa, British Pound) и след повторно извикване — показват се с директната теза от таблицата (или със стара теза, ако има); следващият run опитва пак."}]
assert data_warnings.collect(None, None, cot_diag={"not_returned": []}) == [] and data_warnings.collect(None, None, cot_diag=None) == [] and data_warnings.collect(None, None) == []
r2, log2 = run("2026-10-08", omit={})                                                                  # СИНТЕТИЧНО: следващият ден, моделът вече връща всичко
assert state["calls"] == [["Cocoa", "British Pound"]] and ai_brief.COT_DIAG["not_returned"] == [] and ai_brief.COT_DIAG["cache"]["cached"] == 18 and ai_brief.COT_DIAG["cache"]["generated"] == 2
assert all(c["cross_sector_thesis"]["source"] in ("cache", "generated") for c in r2.values())
print("  ✓ not_returned = ['Cocoa', 'British Pound'] (20/20 пазара се показват; директната на GBP — FXB от таблицата), 18 в кеша; банерът в data_warnings; на следващия ден 1 извикване само за двата, 18 от кеша")

print()
print("── суров отговор: в лога, не в brief JSON ──")
cache.unlink(missing_ok=True)
r, log = run("2026-10-07", omit=omit3)
assert 'суров отговор (' in log and '{"theses": [{"market": "Corn", "tickers": []}]}' in log
dj = json.dumps(ai_brief.COT_DIAG, ensure_ascii=False)
assert "суров" not in dj and '"market": "Corn"' not in dj and '"tickers"' not in dj and '{"theses"' not in dj
print("  ✓ при непълна партида логът носи имената и суровия текст на отговора; COT_DIAG (отива в brief JSON) — само имена и числа")

print()
print("── порции: най-много ceil(липсващи / COT_BATCH_SIZE) повторни извиквания ──")
cache.unlink(missing_ok=True)
omit_all = {i: set(NAMES[i * 5 + 1:i * 5 + 5]) for i in range(4)}                                       # всяка от 4-те партиди връща само първия си пазар → 16 липсващи
r, log = run("2026-10-07", omit=omit_all)
assert len(state["calls"]) == 4 + 4 and [len(c) for c in state["calls"][4:]] == [5, 5, 5, 1] and ai_brief.COT_DIAG["not_returned"] == []
print("  ✓ 16 липсващи → 4 повторни извиквания (5+5+5+1), не 16 и не 1 голямо; всички са възстановени")

print()
print("── провалена партида (изключение): без повторно извикване — вече е опитана два пъти ──")
cache.unlink(missing_ok=True)
r, log = run("2026-10-07", fail={2, 3})                                                                  # третата партида хвърля на двата опита (извиквания 2 и 3)
d = ai_brief.COT_DIAG
assert len(state["calls"]) == 5 and d["not_returned"] == BATCH3 and d["retried"] == [] and not any(b.get("retry") for b in d["batches"])
assert [b["status"] for b in d["batches"]] == ["ok", "ok", "failed", "ok"] and d["batches"][2]["returned"] == 0
assert len(r) == 20 and all(r[m]["cross_sector_thesis"]["source"] == "none" for m in BATCH3)
print("  ✓ партида 3/4 пада два пъти (изключение): статус failed, 0 върнати, НЕ се харчи трето извикване; всичките 5 пазара са в not_returned и се показват")

print()
print("── страницата (РЕАЛНИЯТ бриф от 05.10, но с COT секцията от този сценарий) ──")
cache.unlink(missing_ok=True)
r, _ = run("2026-10-07", omit=omit_retry)
brief = copy.deepcopy(B05)
brief["cot"] = list(r.values())
brief["cot_diag"] = dict(ai_brief.COT_DIAG)
brief["data_warnings"] = data_warnings.collect(None, None, cot_diag=ai_brief.COT_DIAG)
page = re.sub(r"\s+", " ", htmllib.unescape(render.render_dashboard(brief)))
assert "COT: моделът не върна теза за 2 от 20 пазара (Cocoa, British Pound)" in page
txt = re.sub(r"<[^>]+>", " ", page)
txt = re.sub(r"\s+", " ", txt)
assert txt.count("Няма cross-sector теза — моделът не върна пазара, следващият run опитва пак") == 2          # по един ред за Cocoa и British Pound
j = txt.rfind("British Pound", 0, txt.rfind("Няма cross-sector теза — моделът не върна пазара"))
assert j > txt.find("COT")                                                                                  # пазарът е в самата COT секция (карта), не само в банера
em = htmllib.unescape(render.render_email(brief))
assert "COT: моделът не върна теза за 2 от 20 пазара" in em
print("  ✓ банер най-горе в dashboard-а и в имейла; Cocoa и British Pound са в COT секцията с 'Няма cross-sector теза — моделът не върна пазара, следващият run опитва пак'")

print()
print("── main (структурно) ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
call = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and ast.unparse(n.func) == "data_warnings.collect")
assert {k.arg: ast.unparse(k.value) for k in call.keywords}["cot_diag"] == "ai_brief.COT_DIAG"                 # по аргумент, не по точния низ: други пакети добавят свои аргументи към същото извикване
print("  ✓ main подава ai_brief.COT_DIAG на data_warnings.collect")

assert (REAL_CACHE.read_bytes() if REAL_CACHE.exists() else None) == real_before
print()
print("Всички тестове минаха.")
