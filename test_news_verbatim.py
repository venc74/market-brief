"""
15.10.2026 · "Значими новини": заглавието е ДОСЛОВНО от източника (news_aggregator.pick_verbatim) — моделът връща само индекса "i" в пула, "why" и по желание превод "headline_bg".

Реален дефект (брифът от 14.10): заглавията бяха полупреведени от модела — "Dollar languishes като фокусът се насочва към CPI и Fed speakers", "Oil prices climb като Iran deploy нови
тактики …", "Delaware jury finds Arm breached license agreement с Qualcomm, awards $2 в damages" (мащабът на сумата изчезна); в историята 88 от 688 заглавия са смесени.

РЕАЛНО: tests/fixtures/news_raw_pool_2026-10-15.json — суровият пул (142 заглавия от Reuters Business, CNBC, Financial Times, AP Business), свален на 15.10.2026 ~15:30 Берлин;
tests/fixtures/brief_2026-10-14.json и brief_2026-10-15.json — рамка за страницата и имейла (+ реалните смесени заглавия от 14.10).
СИНТЕТИЧНО (маркирано): отговорът на модела (индекси, why, преводи), подмененият _call_claude. 30.10.2026 (т. 8): разделът за котвите на тезите (гейт G4) — махнат с тезите.
Пускане: python test_news_verbatim.py
"""
import sys, json, pathlib, contextlib, io, re, copy, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_news_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import news_aggregator as na, ai_brief, render
assert str(na._CACHE).startswith(_tmp.name)

POOL = json.loads((ROOT / "tests" / "fixtures" / "news_raw_pool_2026-10-15.json").read_text(encoding="utf-8"))["items"]
B14 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-14.json").read_text(encoding="utf-8"))
B15 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-15.json").read_text(encoding="utf-8"))
assert len(POOL) == 142 and {r["source"] for r in POOL} == {"Reuters Business", "CNBC", "Financial Times", "AP Business"}

print("── 0. РЕАЛНИЯТ дефект от 14.10 ──")
mixed = [n["headline"] for n in B14["news"] if re.search(r"[А-Яа-я]", n["headline"]) and len(re.findall(r"\b[A-Za-z]{3,}\b", n["headline"])) >= 2]
assert "Dollar languishes като фокусът се насочва към CPI и Fed speakers" in mixed and any("awards $2 в damages" in h for h in mixed)
print(f"  ✓ {len(mixed)} от {len(B14['news'])} заглавия на 14.10 са полупреведени; 'awards $2 в damages' — без мащаба на сумата")

print()
print("── 1. pick_verbatim върху РЕАЛНИЯ пул (СИНТЕТИЧЕН отговор на модела) ──")
T = {i: POOL[i]["title"] for i in (13, 40, 67, 72)}
assert T[67].startswith("TSMC posts record profit") and "$12 billion" in T[72] and "$40 million" in T[40]
answer = [
    {"i": 67, "why": "Рекордната печалба на TSMC е пряк ориентир за AI търсенето.", "headline_bg": "TSMC отчита рекордна печалба за шесто поредно тримесечие"},
    {"i": 72, "why": "Приходите от енергия държат бюджета на Русия.", "headline_bg": "Приходите на Русия от петрол и газ растат с 10% до $12 през октомври"},   # без мащаба
    {"i": 40, "why": "Сделка за AI в здравеопазването.", "headline_bg": "AstraZeneca сключва сделка за $45 млн с insitro"},                                      # число, което го няма
    {"i": 999, "headline": "Dollar languishes като фокусът се насочва към CPI", "why": "x"},                                                                    # няма такъв индекс
    {"headline": "Oil prices climb като Iran deploy нови тактики", "why": "x"},                                                                                  # без индекс (старият формат)
    {"i": 67, "why": "повторение"},
    {"i": 13, "headline": "Nvidia, AMD, Micron падат като AI разпродажбата се задълбочава", "why": "Разпродажбата в чиповете удря индексите."},                  # "headline" на модела се игнорира
]
news, dropped = na.pick_verbatim(answer, POOL, 8)
assert [n["headline"] for n in news] == [T[67], T[72], T[40], T[13]] and [n["source"] for n in news] == [POOL[i]["source"] for i in (67, 72, 40, 13)]
assert news[0]["headline_bg"] == "TSMC отчита рекордна печалба за шесто поредно тримесечие" and "headline_bg" not in news[1] and "headline_bg" not in news[2] and "headline_bg" not in news[3]
assert sorted(d["reason"] for d in dropped) == sorted(["преводът на заглавието е махнат (число или мащаб, различни от оригинала)"] * 2 + ["няма валиден индекс в пула"] * 2 + ["повторен индекс"])
assert not any(re.search(r"[А-Яа-я]", n["headline"]) for n in news)
print("  ✓ заглавие и източник — дословно от пула по индекса; 'headline' на модела се игнорира; без индекс / извън пула / повторен — отпадат")
print("  ✓ преводът остава само ако числата и мащабът съвпадат с оригинала ('до $12' без 'млрд' и '$45 млн' срещу '$40 million' — махнати)")

print()
print("── 2. significant_news: промптът носи индексите; кешът е във временната директория ──")
prompts = []
def fake_claude(system, user, **k):
    prompts.append(user)
    return json.dumps({"news": answer}, ensure_ascii=False)
ai_brief._call_claude = fake_claude
na._RAW_MEMO = (24, POOL)                                                        # СИНТЕТИЧНО: без мрежа — РЕАЛНИЯТ пул
with contextlib.redirect_stdout(io.StringIO()) as out:
    got = na.significant_news()
assert [n["headline"] for n in got] == [T[67], T[72], T[40], T[13]]
compact = json.loads(prompts[0].split("НОВИНИ:\n", 1)[1].split("\n\n", 1)[0])
assert len(compact) == config.NEWS_MAX_TO_FILTER and compact[67] == {"i": 67, "s": POOL[67]["source"], "t": T[67], "d": POOL[67]["summary"]}
assert "Заглавието НЕ го пишеш" in prompts[0] and '{"news": [{"i": 0, "h": "първите шест думи на заглавието", "why": "...", "also": [{"i": 5, "h": "първите шест думи"}]}]}' in prompts[0] and "headline_bg" not in prompts[0]   # 19.10: + ехото "h" (С3); 29.10: + "also"; 30.10: без превод
assert na.LAST_DIAG["kept"] == 4 and len(na.LAST_DIAG["dropped"]) == 5 and "няма валиден индекс в пула" in out.getvalue()
assert json.loads(na._CACHE.read_text(encoding="utf-8"))["news"] == got
print("  ✓ всеки ред на пула е с 'i'; резултатът и кешът носят оригиналните заглавия; отпадналите са в LAST_DIAG и в лога")

print()
print("── 3. страницата и имейлът (РЕАЛНИЯТ бриф от 15.10 като рамка) ──")
b = copy.deepcopy(B15); b["news"] = got
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
page, mail = flat(render.render_dashboard(b)), flat(render.render_email(copy.deepcopy(b)))
assert f"{T[67]} · {POOL[67]['source']} — Рекордната печалба" in page and "TSMC отчита рекордна печалба за шесто поредно тримесечие" not in page   # 30.10.2026: преводът не се показва
assert T[13] in page and "Nvidia, AMD, Micron падат" not in page
assert f"{T[67]} — Рекордната печалба" in mail and "TSMC отчита рекордна печалба за шесто поредно тримесечие" not in mail
old = flat(render.render_dashboard(copy.deepcopy(B15)))                          # старият формат (без source / headline_bg) се рендерира както преди
assert B15["news"][0]["headline"] in old
print("  ✓ оригинал · източник — защо (от 30.10 без превода в скоби); старият формат се рендерира както преди")
print("\n✅ test_news_verbatim: всичко мина")
