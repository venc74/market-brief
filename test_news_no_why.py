"""
27.11.2026 (уикенд пакет, т. 4 и 10): „Значими новини“ — само оригинал + превод. На 27.11 моделът върна „защо“ за всичките 8 новини и 5 крипто (с „Бразилия“, „Виетнам търси сделка“,
„Кристин Лагард“, „серия на Brent“ — ги няма в заглавията), макар промптът да не го иска: правилото за „също“ споменаваше "why", а кодът пазеше каквото върне моделът. Сега:
без NEWS_AI_WHY „защо“ се маха в кода (pick_verbatim) и правилото не го споменава. Броят „Reuters Business 79 от 51“ — знаменателят беше само основният фийд; сега — всичко от
източника в прозореца. Т. 10: „…, Fitch says“ (рейтинговата агенция) не е ANF (Abercrombie & Fitch).

РЕАЛНО: tests/fixtures/news_2026-11-27.json — пулът, новините с „защо“-то на модела и news_window от брифа на 27.11. СИНТЕТИЧНО (означено): отговорът на модела е сглобен от
реалните индекси и „защо“-тата.
Пускане: python run_tests.py test_news_no_why
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
config.NEWS_AI_WHY = 0
from src import news_aggregator as na, render

FX = json.loads((ROOT / "tests" / "fixtures" / "news_2026-11-27.json").read_text(encoding="utf-8"))
pool = [{"source": p[0], "published": p[1], "title": p[2], "summary": ""} for p in FX["pool"]]
titles = [p["title"] for p in pool]

print("── 1. РЕАЛНО (27.11): „защо“ от модела не стига до брифа ──")
assert all(n["why"] for n in FX["news"]) and all(c["why"] for c in FX["crypto"])                         # 27.11 — 8 / 8 и 5 / 5 с „защо“
items = [{"i": titles.index(n["headline"]), "h": " ".join(n["headline"].split()[:6]), "why": n["why"]} for n in FX["news"] if n["headline"] in titles]   # СИНТЕТИЧНО: отговорът
rows, dropped = na.pick_verbatim(items, pool, 8)
assert len(rows) == len(items) == 8 and all(r["why"] == "" for r in rows)
assert not any("Бразилия" in str(r) or "Лагард" in str(r) for r in rows)
u = na._select_user(pool[:5], 8)
assert '"why"' not in u and "why" not in na.ALSO_RULE_NO_WHY and "why" in na.ALSO_RULE
print("  ✓ 8 новини — без „защо“; промптът и правилото за „също“ — без why")

print("── 2. РЕАЛНО: броят към подбора — от всичко в прозореца ──")
note = render.news_pool_note(FX["news_window"], {})
assert "Reuters Business 79 от 102" in note and "AP Business 77 от 101" in note and "79 от 51" not in note, note
print(f"  ✓ «{note[:110]}…»")

print("── 3. РЕАЛНО: „Fitch says“ не е ANF ──")
M = na.priority_matchers([{"ticker": "ANF", "name": FX["anf_name"]}])
nv = next(n for n in FX["news"] if n["headline"].startswith("Nvidia halts server shipments"))
assert nv["ours"] == ["ANF"]                                                                            # 27.11 — грешно
texts = [nv["headline"]] + [a["headline"] for a in nv["also"]]
assert not any(na.priority_hits(t, M) for t in texts)
assert na.priority_hits("Abercrombie & Fitch shares jump after earnings beat", M) == ["ANF"]            # СИНТЕТИЧНО: пълното име — да
print("  ✓ „…, Fitch says“ — без ANF; „Abercrombie & Fitch …“ — ANF")
print("\n✅ test_news_no_why: всичко мина")
