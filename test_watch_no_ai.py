"""
23.11.2026 (пакет 23.11, т. 2 — решено 20.11): наблюдаваните без AI. За всеки тикър — дословните заглавия с превод (src/translate.py, с проверката) и фактите от новите
Form 4 от кода (watch_monitor.insider_summary — на мястото на AI „прочита“); нищо ново → „нищо ново от ДД.ММ“. config.ENABLE_WATCH_AI = 0 (1 връща AI резюмето).

РЕАЛНО: tests/fixtures/watch_2026-11-23.json — brief["watch"] от 23.11 (новините на DOCU, ACN, HONA, ANT) и от 16.11 (новите Form 4 на BFLY, AI, ACN, CRCL), без AI полето;
AI текстовете от същите дни — за сравнение. СИНТЕТИЧНО (означено): преводите.
Пускане: python test_watch_no_ai.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib, tempfile, io, contextlib, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_watchnoai_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import watch_monitor as wm, translate as tr, render

FX = json.loads((ROOT / "tests" / "fixtures" / "watch_2026-11-23.json").read_text(encoding="utf-8"))
R16 = {w["ticker"]: w for w in FX["rows_1611"]}

print("── 1. РЕАЛНО (16.11): фактите от новите Form 4 — от кода ──")
assert wm.insider_summary(R16["BFLY"]["insider_days"]) == [
    "Продажби: 2 души, 2 записа (човек × ден), $984,925 — по план 10b5-1: 1, извънпланови: 1; най-голямата: President & CEO $634,925 (30.10, 1.2% от дела)."]
assert wm.insider_summary(R16["AI"]["insider_days"]) == [
    "Продажби: 1 човек, 2 записа (човек × ден), $5.1 млн — по план 10b5-1: 2, извънпланови: 0; най-голямата: CEO and Chairman of the Board $3.9 млн (10.11, 31.3% от дела)."]
acn = wm.insider_summary(R16["ACN"]["insider_days"])
assert len(acn) == 2 and acn[0].startswith("Покупки: 2 души") and acn[1].startswith("Продажби: 3 души") and "Co-CEO Asia Pacific $2.7 млн (05.11, 62.5% от дела)" in acn[1], acn
assert wm.insider_summary([]) == [] and wm.insider_summary(None) == []
for t in ("BFLY", "AI"):
    print(f"  ✓ {t}: «{wm.insider_summary(R16[t]['insider_days'])[0][:100]}…»  (AI на 16.11: «{(FX['ai_1611'][t] or '')[:70]}…»)")
assert not any(w in " ".join(acn) for w in ("рутинн", "тревож", "сигнал"))                         # само числата, без оценка

print("── 2. преводът на заглавията (заглавията — РЕАЛНИ от 23.11, преводите — СИНТЕТИЧНИ) ──")
rows = copy.deepcopy(FX["rows_2311"])
active = [r for r in rows if r.get("event")]
assert [r["ticker"] for r in active] == ["DOCU", "ACN", "HONA", "ANT"]
BG = {"DocuSign (DOCU) Stock Looks Pricey Following Its New AI Contract Push": "Акцията на DocuSign (DOCU) изглежда скъпа след новия тласък с AI договори",
      "A $12 Billion Fund Dumps These 3 Stocks": "Фонд за $12 млрд се освобождава от тези 3 акции",
      "ANT, BABA, PANW, TTWO, ZS: Why Retail Traders Couldn’t Take Their Eyes Off These Stocks Last Week":
          "ANT, BABA, PANW, TTWO, ZS: защо ритейл трейдърите не откъсваха поглед от тези акции миналата седмица"}
def fake(system, user, **k):
    assert system == tr.SYSTEM
    items = json.loads(user.split("ЗАГЛАВИЯ:\n", 1)[1])
    return json.dumps({"bg": [BG.get(x["t"], "Пазар за управление на финансови процеси 2026") for x in items]}, ensure_ascii=False)   # ACN — без числата → бележка
with contextlib.redirect_stdout(io.StringIO()):
    rep = wm.translate_news(active, call=fake)
assert rep["n"] == 4 and rep["ok"] == 3 and len(rep["skipped"]) == 1, rep
docu = active[0]["news"][0]
assert docu["headline_bg"] == BG[docu["title"]] and docu["title"].startswith("DocuSign (DOCU)")       # оригиналът остава
acn_n = active[1]["news"][0]
assert "headline_bg" not in acn_n and acn_n["translation_note"].startswith("преводът е пропуснат — несъответствие (липсва: 2030, 13.11, billion"), acn_n
assert wm.translate_news([{"ticker": "X", "news": []}]) == {"n": 0, "ok": 0, "skipped": []}
print(f"  ✓ 3 от 4 приети; ACN (без числата) → «{acn_n['translation_note'][:70]}…»")

print("── 2б. Title Case (Yahoo): главната буква не е име — заглавията РЕАЛНИ от 23.11 ──")
assert tr.is_title_case("DocuSign (DOCU) Stock Looks Pricey Following Its New AI Contract Push")
assert tr.names("DocuSign (DOCU) Stock Looks Pricey Following Its New AI Contract Push", set()) == ["DOCUSIGN", "DOCU", "AI"]
assert tr.names("A $12 Billion Fund Dumps These 3 Stocks", set()) == []
assert not tr.is_title_case("Trump says he and China's Xi want moderate AI rules - Reuters")            # РЕАЛНО (20.11, Reuters) — обикновен регистър, без промяна
assert tr.problems("Financial Process Management Market 2026: Size, Share, Trends, and Forecast to 2030 | Capitalize on $13.11B AI and Cloud Growth with Accenture, IBM, TCS, NTT DATA, and Capgemini",
                   "Пазарът за управление на финансови процеси 2026: размер, дял, тенденции и прогноза до 2030 г. — растеж от $13,11 млрд в AI и облака с IBM, TCS, NTT DATA и Capgemini",
                   set(), must=["Accenture"]) == ["ACCENTURE"]                                              # СИНТЕТИЧНО: името на компанията — задължително (must)
print("  ✓ DocuSign / DOCU / AI — да; Stock / Looks / Pricey — не; името на наблюдаваната компания — задължително")

print("── 3. main: без AI при ENABLE_WATCH_AI = 0 ──")
assert config.ENABLE_WATCH_AI == 0
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
i = src.index("def _watch():"); body = src[i:src.index("watch_rows = steps.step(", i)]
assert body.index("if not config.ENABLE_WATCH_AI:") < body.index("ai_brief.watch_ticker_digest(") and "watch_monitor.translate_news(active, pool_titles=" in body
print("  ✓ watch_ticker_digest — само при ENABLE_WATCH_AI = 1")

print("── 4. страницата: заглавие → превод; Form 4 от кода; „нищо ново от 20.11“; без AI резюме ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B)
bf = copy.deepcopy(R16["BFLY"]); bf["insider_summary"] = wm.insider_summary(bf["insider_days"])
b["watch"] = [{**r, "ai": {}} for r in rows] + [{**bf, "ai": {}}]
with contextlib.redirect_stdout(io.StringIO()):
    html = render.render_dashboard(b, publish=False)
h = " ".join(html.split())
assert BG["DocuSign (DOCU) Stock Looks Pricey Following Its New AI Contract Push"] in h
assert "преводът е пропуснат — несъответствие (липсва: 2030, 13.11, billion" in h
assert "Продажби: 2 души, 2 записа (човек × ден), $984,925" in h
assert "нищо ново от 20.11" in h and 'class="wm-summary"' not in h
for t, s in FX["ai_2311"].items():
    assert s[:40] not in h                                                                           # AI резюметата от 23.11 ги няма
print("  ✓")
print("\n✅ test_watch_no_ai: всичко мина")
