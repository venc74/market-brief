"""
19.10.2026 · етап 2, т. 10 (трети преглед, решение "в" на Венци): тезите и днешните новини.

Махат се AI етикетите ("потвърдена от новина", "опровергана от новина", "друг път", "разрешена") и бележката на модела; до тезата е ДОСЛОВНОТО заглавие на свързаната новина
БЕЗ етикет (кой съди — читателят); карето "Контекст" с числата от кода остава (тезата с избрано заглавие го получава, както преди маркираната).

Изборът: кандидатите за всяка теза — от КОДА (заглавията от суровия пул с котва на тезата: тикър, име на компания, термин на механизма); моделът само отсява шума и
връща индексите; кодът приема само индекс от кандидатите на СЪЩАТА теза. Котвите сами не стигат — на РЕАЛНИЯ пул от 15.10: 57 кандидата в 4 тези, сред тях "Zimbabwe’s Caine
Prize winner rejects claim he used AI …", "Walmart is a buy … says Deutsche Bank".
Разход (РЕАЛНО ai_usage на 18 брифа от 24.09): проверката беше 9 651 входни + 462 изходни токена на ден (≈ $0.036, 11.6% от AI разхода); новият промпт върху пула от 15.10 е
0.23 от стария по знаци → ≈ 2 250 входни токена, изходът — индекси → ≈ $0.008 на ден.

РЕАЛНО: tests/fixtures/news_raw_pool_2026-10-15.json (142 заглавия), тезите от брифа на 15.10 (brief_2026-10-15.json; там "Въглища и LNG" е "confirmed" по стария механизъм).
СИНТЕТИЧНО (означено): отговорите на модела, провалът.
Пускане: python test_thesis_news_pick.py
"""
import sys, json, pathlib, tempfile, io, contextlib, copy, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_tpick_")
config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DATA_DIR.mkdir()
from src import ai_brief, render

FX = ROOT / "tests" / "fixtures"
POOL = json.loads((FX / "news_raw_pool_2026-10-15.json").read_text(encoding="utf-8"))["items"]
B15 = json.loads((FX / "brief_2026-10-15.json").read_text(encoding="utf-8"))
TH = [{k: t[k] for k in ("name", "chain", "tickers", "status")} for t in B15["theses"]]
q = lambda: contextlib.redirect_stdout(io.StringIO())
SEMIS, COAL = "Полупроводници и AI инфраструктура", "Въглища и LNG"

print("── 1. кандидатите по котвите (РЕАЛНИЯТ пул, РЕАЛНИТЕ тези) ──")
seen = []
ai_brief._call_claude = lambda system, user, **k: seen.append(user) or json.dumps({"picks": []})                 # СИНТЕТИЧНО
with q():
    out = ai_brief.thesis_news_pick(copy.deepcopy(TH), POOL)
assert ai_brief.THESIS_CHECK_DIAG["candidates"] == {"Ядрена енергия": 0, SEMIS: 18, COAL: 15, "Отбрана и дронове": 9, "Крипто регулация (CLARITY Act)": 0, "Финанси при стръмна крива": 15}
assert all("news_headlines" not in t for t in out) and len(seen) == 1
payload = json.loads(seen[0].split("механизма):\n", 1)[1].split("\n\n", 1)[0])
assert [p["name"] for p in payload] == [SEMIS, COAL, "Отбрана и дронове", "Финанси при стръмна крива"]           # тези без кандидати не се пращат
assert all(set(c) == {"i", "t"} and c["t"] == POOL[c["i"]]["title"] for p in payload for c in p["candidates"])  # само дословни заглавия, без резюмета
assert len(seen[0]) < 10000 and "Zimbabwe" in seen[0]
print(f"  ✓ кандидати {ai_brief.THESIS_CHECK_DIAG['candidates']}; към модела — само заглавия с индекс, без резюмета ({len(seen[0])} знака); шумът (Zimbabwe … AI) е сред кандидатите — моделът отсява")

print()
print("── 2. изборът на модела → дословното заглавие до тезата (СИНТЕТИЧЕН отговор) ──")
ans = {"picks": [{"name": SEMIS, "i": [13, 26, 21]}, {"name": COAL, "i": [11, 13]}, {"name": "Непозната", "i": [1]}]}
ai_brief._call_claude = lambda system, user, **k: json.dumps(ans)
with q():
    out = ai_brief.thesis_news_pick(copy.deepcopy(TH), POOL)
by = {t["name"]: t for t in out}
assert by[SEMIS]["news_headlines"] == [{"headline": POOL[13]["title"], "source": POOL[13]["source"]}, {"headline": POOL[26]["title"], "source": POOL[26]["source"]}]   # най-много 2
assert by[COAL]["news_headlines"] == [{"headline": POOL[11]["title"], "source": POOL[11]["source"]}]
assert ai_brief.THESIS_CHECK_DIAG["rejected"] == [{"thesis": COAL, "i": 13, "reason": "индексът не е сред кандидатите на тезата"}]          # Nvidia не е кандидат за въглищата
assert all("news_status" not in t and "news_note" not in t for t in out)
print(f"  ✓ {SEMIS}: «{POOL[13]['title']}», «{POOL[26]['title']}» (третото — над тавана 2); {COAL}: «{POOL[11]['title'][:60]}…»; индекс извън кандидатите — отхвърлен")

print()
print("── 3. без кандидати → без извикване; провал → тезите непроменени ──")
calls = []
ai_brief._call_claude = lambda system, user, **k: calls.append(1) or "{}"
with q():
    assert ai_brief.thesis_news_pick(copy.deepcopy(TH), [{"title": "Weather is mild in Paris", "source": "AP Business"}]) == TH and calls == []
ai_brief._call_claude = lambda system, user, **k: (_ for _ in ()).throw(RuntimeError("API"))                     # СИНТЕТИЧНО
with q():
    assert ai_brief.thesis_news_pick(copy.deepcopy(TH), POOL) == TH
print("  ✓ нито едно заглавие с котва → модел не се вика; грешка на модела → тезите както са")

print()
print("── 4. страницата: заглавието без етикет; старият бриф с етикети — без етикети ──")
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
b = copy.deepcopy(B15); b["theses"] = [{**t, **{k: by[t["name"]][k] for k in ("news_headlines",) if k in by[t["name"]]}} for t in B15["theses"]]
for t in b["theses"]:
    t.pop("news_status", None); t.pop("news_note", None)
with q():
    page = flat(render.render_dashboard(b, publish=False))
sec = page.split("Геополитически тези · мониторинг", 1)[1].split("Action ·", 1)[0]
assert f"📰 {POOL[13]['title']} · {POOL[13]['source']}" in sec
for lab in ("потвърдена от новина", "опровергана от новина", "друг път", "разрешена", "механизмът потвърден"):
    assert lab not in sec, lab
with q():
    old = flat(render.render_dashboard(copy.deepcopy(B15), publish=False))                                    # РЕАЛНИЯТ 15.10: "Въглища и LNG" confirmed + бележка
old_sec = old.split("Геополитически тези · мониторинг", 1)[1].split("Action ·", 1)[0]
assert B15["theses"][[t["name"] for t in B15["theses"]].index(COAL)]["news_status"] == "confirmed" and "потвърдена от новина" not in old_sec
print("  ✓ '📰 <заглавие> · <източник>' до тезата, без етикет; старият бриф (15.10, 'потвърдена от новина' по стария механизъм) — без етикета и без бележката")

print()
print("── 5. карето «Контекст» се дава и за теза с избрано заглавие; main вика новата функция ──")
src = (ROOT / "src" / "thesis_context.py").read_text(encoding="utf-8")
assert 'if th.get("news_headlines") or th.get("news_status") in FLAGGED_NEWS or th.get("status") == "active":' in src
srcm = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "theses = ai_brief.thesis_news_pick(" in srcm and "thesis_reality_check(" not in srcm
assert not hasattr(ai_brief, "thesis_reality_check") and not hasattr(ai_brief, "_news_gate") and not hasattr(ai_brief, "_headline_gate")
assert ai_brief._SECTION_LABELS["thesis_news_pick"] == "Тези: свързани новини"
print("  ✓ thesis_context: news_headlines → каре; main: thesis_news_pick; старият механизъм (етикети, G1–G4) е махнат; етикет в ai_usage")
print("\n✅ test_thesis_news_pick: всичко мина")
