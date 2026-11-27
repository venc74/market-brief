"""
11.11.2026 (т. 5): „защо“ на новината за Anthropic казваше „$1.5 трлн“, а показаното заглавие (AP) — „about $1.3 trillion“. Причината: моделът е избрал заглавието на FT
(„… IPO valuation to $1.5tn or more“) и е написал „защо“ за него; редът е събрал AP, FT и CNBC като една история, а основното заглавие се сменя към по-надеждния източник
(config.NEWS_SOURCE_PRIORITY: AP пред FT) — и проверката на числата гледаше цялата група, затова „$1.5“ мина. Сега: ако числата в „защо“ ги има в заглавието на модела,
а в по-надеждното ги няма — основното остава това на модела. Измерено: най-много 5 от 48 групирани реда (13.10–11.11).
16.11.2026 (пакет 16.11, т. 1): основното е ВИНАГИ изборът на модела — т. 2 е обновена.

РЕАЛНО: tests/fixtures/news_anthropic_2026-11-11.json (редът от брифа на 11.11 — трите заглавия, източниците и „защо“).
СИНТЕТИЧНО (означено): пулът е построен от трите реални заглавия; отговорът на модела ({i, h, why, also}) — както би го върнал; т. 2 — „защо“ без числа / с числото на AP.
Пускане: python test_news_why_main.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
config.NEWS_AI_WHY = 1                            # 27.11.2026 (уикенд пакет, т. 4): тук — пътят с AI „защо“; без флага „защо“ се маха (test_news_no_why)
from src import news_aggregator as na

R = json.loads((ROOT / "tests" / "fixtures" / "news_anthropic_2026-11-11.json").read_text(encoding="utf-8"))["row"]
pool = [{"title": R["headline"], "source": R["source"], "link": R.get("link")}] + [{"title": a["headline"], "source": a["source"], "link": a.get("link")} for a in R["also"]]
AP, FT, CN = 0, 1, 2
assert (pool[AP]["source"], pool[FT]["source"], pool[CN]["source"]) == ("AP Business", "Financial Times", "CNBC") and "$1.5tn" in pool[FT]["title"] and "$1.3 trillion" in pool[AP]["title"]
h = lambda k: " ".join(pool[k]["title"].split()[:6])
item = lambda why: [{"i": FT, "h": h(FT), "why": why, "also": [{"i": AP, "h": h(AP)}, {"i": CN, "h": h(CN)}]}]

print("── 1. РЕАЛНОТО „защо“ ($1.5 трлн) — основното заглавие остава това на FT ──")
out, dropped = na.pick_verbatim(item(R["why"]), pool, 8)
assert len(out) == 1 and out[0]["source"] == "Financial Times" and "$1.5tn" in out[0]["headline"] and out[0]["why"] == R["why"]
assert [a["source"] for a in out[0]["also"]] == ["AP Business", "CNBC"]
assert not any("по-надеждния" in str(d.get("reason")) for d in dropped)
print(f"  ✓ „{out[0]['headline'][:60]}…“ (FT); също: AP, CNBC; „защо“ непроменено")

print("── 2. от 16.11 (пакет 16.11, т. 1): основното е изборът на модела и без числа (СИНТЕТИЧНО „защо“) ──")
o2, d2 = na.pick_verbatim(item("Оценката на Anthropic при IPO-то расте — бичи сигнал за AI сектора."), pool, 8)
assert o2[0]["source"] == "Financial Times" and not any("по-надеждния" in str(d.get("reason")) for d in d2)
o3, d3 = na.pick_verbatim(item("Anthropic търси оценка от около $1.3 трлн. при IPO-то."), pool, 8)
assert o3[0]["source"] == "Financial Times" and o3[0]["why"] == "Anthropic търси оценка от около $1.3 трлн. при IPO-то."          # числото е от AP в групата — остава
print("  ✓ „защо“ без числа или с $1.3 трлн → FT (изборът на модела); до 16.11 — AP")
print("\n✅ test_news_why_main: всичко мина")
