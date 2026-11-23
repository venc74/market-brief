"""
16.11.2026 (пакет 16.11, т. 4): Form 4 при ръчно наблюдаваните показваше едно и също всеки ден — SIRI „покупки · 1 човек · извънпланови · BERKSHIRE HATHAWAY INC $21.5 млн (30.10)“
от 30.10 до 16.11. Защо: отметката, таблицата, ≥25% и AI бяха от целия 30-дневен прозорец (config.WATCH_INSIDER_LOOKBACK_DAYS), а не от новото; в дните с новина (10.11, 11.11) AI
преразказваше покупките от 30.10 наново. Новините НЕ се повтаряха (0 от 215 за ноември — прозорецът им е от предишния бриф). Сега: новите Form 4 (подадени от деня на предишния
бриф) — отметката, таблицата, ≥25%, AI; по-старите — сгънати „вече показано“; нищо ново → „нищо ново от ДД.ММ“.

РЕАЛНО: tests/fixtures/watch_form4_2026-11-16.json — SIRI, CRCL, BFLY, ACN от data/2026-11-16.json (Form 4 за 30 дни, новините, името), предишният бриф — 13.11;
brief_2026-10-19.json — рамката. СИНТЕТИЧНО (означено): подменените теглене (EDGAR, RSS, цени) и AI отговорът.
Пускане: python test_watch_new_only.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, pathlib, tempfile, io, contextlib, re, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_watchnew_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import watch_monitor as wm, insider_buying, ai_brief, render

FX = json.loads((ROOT / "tests" / "fixtures" / "watch_form4_2026-11-16.json").read_text(encoding="utf-8"))
SINCE, R = FX["since"], FX["rows"]
TX = {t: [{**x, "date": dt.date.fromisoformat(x["date"])} for x in r["insider"]] for t, r in R.items()}
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. РЕАЛНО: ново / вече показано (предишният бриф — 13.11) ──")
n, o = wm.split_new_old(TX["SIRI"], SINCE)
assert n == [] and len(o) == 3 and {x["owner_name"] for x in o} == {"BERKSHIRE HATHAWAY INC"}
n, o = wm.split_new_old(TX["CRCL"], SINCE)
assert len(n) == 1 and len(o) == 55 and n[0]["filed"] == "2026-11-13"
n, o = wm.split_new_old(TX["BFLY"], SINCE)
assert len(n) == 1 and n[0]["filed"] == "2026-11-13" and o[0]["filed"] == "2026-11-03"
print("  ✓ SIRI 0 нови / 3 стари; CRCL 1 нов (13.11) / 55; BFLY 1 нов / 1 стар")

print("── 2. collect(): отметките, таблицата и ≥25% — само от новото ──")
insider_buying.fetch_insider_transactions = lambda tickers: {t: copy.deepcopy(TX[t]) for t in tickers}          # СИНТЕТИЧНО: без EDGAR
wm._recent_news = lambda tk, h, keys=None: copy.deepcopy(R[tk]["news"])                                          # СИНТЕТИЧНО: новините от брифа
with q():
    rows = {r["ticker"]: r for r in wm.collect(["SIRI", "CRCL", "BFLY", "ACN"], facts_fn=lambda t: {}, since_day=SINCE)}
s = rows["SIRI"]
assert s["insider_flags"] == [] and s["insider_days"] == [] and len(s["insider_days_old"]) == 3 and s["since"] == SINCE
assert not s["event"] and not s["quiet"] and not s["insider_cluster"]
c = rows["CRCL"]
assert len(c["insider_days"]) == 1 and c["insider_flags"][0]["n"] == 1 and len(c["insider_days_old"]) >= 1 and c["event"]
a = rows["ACN"]
assert a["insider_flags"] == [] and a["insider_big_sell"] == [] and a["event"]                    # новини има, Form 4 — само старо
assert len(a["insider_big_sell_old"]) >= 1                                                        # продажбите ≥25% от октомври — в „вече показано“
print(f"  ✓ SIRI — без отметка; CRCL — 1 нов ред; ACN — новини, Form 4 и ≥25% само в „вече показано“ ({len(a['insider_big_sell_old'])})")

print("── 3. AI получава само новото ──")
seen = {}
def fake_call(system, user, max_tokens=0, **k):
    seen["user"] = user
    return json.dumps({"digests": [{"ticker": t, "summary": "Новина.", "insider_read": "", "cross_reference": ""} for t in ("SIRI", "ACN", "CRCL")]})
ai_brief._call_claude = fake_call                                                                 # СИНТЕТИЧНО
with q():
    ai_brief._watch_digest_batch([rows["ACN"], rows["CRCL"]], {})
payload = json.loads(re.search(r"\(данни за последните \d+ часа — от предишния бриф\):\n(\[.*?\])\n\nТЕМИ", seen["user"], re.S).group(1))
by = {x["ticker"]: x for x in payload}
assert by["ACN"]["insider"] == [] and by["ACN"]["sells_25pct_of_stake"] == [] and len(by["CRCL"]["insider"]) == 1
print("  ✓ ACN — без Form 4 в заявката (стария не преразказва); CRCL — 1 ред")

print("── 4. страницата: „нищо ново от 13.11“ и сгънато „вече показано“ ──")
b = copy.deepcopy(B19); b["watch"] = [{**rows[t], "in_brief": []} for t in ("SIRI", "CRCL", "ACN")]
with q():
    page = render.render_dashboard(b, publish=False)
sec = page[page.index("<h2>🔎 Наблюдавани тикъри"):]
sec = sec[:sec.index("</section>")]
siri = sec[sec.index('<span class="wt-t">SIRI'):]
siri = siri[:siri.index("</summary>")]
assert "нищо ново от 13.11" in siri and "BERKSHIRE" not in siri and "покупки ·" not in siri
assert "▸ вече показано · Form 4 от предишни брифове (3)" in sec and "Form 4: нищо ново от 13.11." in sec
crcl = sec[sec.index('<span class="wt-t">CRCL'):]
crcl = crcl[:crcl.index("</summary>")]
assert "продажби · 1 човек" in crcl and "нищо ново" not in crcl
print("  ✓ SIRI: „нищо ново от 13.11“ на реда, Berkshire — само в „вече показано“; CRCL — отметката за новия Form 4")
print("\n✅ test_watch_new_only: всичко мина")
