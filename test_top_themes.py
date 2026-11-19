"""
19.11.2026 (пакет 19.11, т. 2): топ темите на деня — автоматично, без ръчни списъци и без AI (src/top_themes.py). Заглавията от всички източници (и първата страница — FT World,
Reuters World) се групират по общи имена; тема = ≥ 3 издателя или ≥ 6 заглавия; държава / общо съществително само не е тема. Заглавията на темата влизат първи и задължително в
пула към подбора; редът „Топ теми“ под „Нощта“ (и в имейла) дава дословното заглавие, броя източници и часа; макро разказът ги получава с „само факти от тези заглавия“.

Диагнозата (19.11): срещата Тръмп–Си–Путин — 12 заглавия в пула от 4 издателя (CNBC, FT, Reuters, AP); подборът (AI) взе едно, трето по ред, разказът не я спомена.
На 18.11 моделът я избра („China’s Xi calls for removing trade … ahead of his meeting with Trump and Putin“), но кодът я махна (апострофът — поправено на 18.11).

РЕАЛНО: tests/fixtures/themes_2026-11-18_19.json — пулът от 19.11 + FT World / Reuters World в прозореца; 18.11 — фийдовете, свалени следобед (приблизителен пул).
СИНТЕТИЧНО (означено): т. 4 — подменената мрежа и отговорът на AI; т. 5 — рамката на страницата.
Пускане: python test_top_themes.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_themes_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import top_themes as tt, news_aggregator as na, render, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "themes_2026-11-18_19.json").read_text(encoding="utf-8"))

print("── 1. РЕАЛНО: 19.11 — Anthropic IPO, срещата Тръмп–Си–Путин, Мъск ──")
T19 = tt.themes(FX["items19"])
assert [set(t["names"]) for t in T19][:2] == [{"ANTHROPIC", "IPO"}, {"PUTIN", "TRUMP", "XI", "CHINA"}], [t["names"] for t in T19]
a, s = T19[0], T19[1]
assert a["n_publishers"] == 4 and a["n_headlines"] == 13 and a["front"] and a["headline"].startswith("EXCLUSIVE: Anthropic clinches biggest-ever IPO")
assert s["n_publishers"] == 4 and s["n_headlines"] == 11 and s["front"] and "Putin" in s["headline"] and "Xi" in s["headline"] and s["key"].startswith("Putin–Trump–Xi")
assert T19[2]["names"] == ["MUSK"] and len(T19) == 3
assert not any(set(t["names"]) & {"INDIA", "BANK", "UKRAINE"} and len(t["names"]) == 1 for t in tt.themes(FX["items19"], max_n=10))     # държава / „Bank“ сами — не са тема
print(f"  ✓ «{a['headline'][:60]}…» (4 издателя, 13); «{s['headline'][:60]}…» (4, 11); Мъск (3, 5); без „India“ и „Bank“")

print("── 2. РЕАЛНО (приблизителен пул): 18.11 ──")
T18 = tt.themes(FX["items18"])
assert [set(t["names"]) for t in T18] == [{"HUANG", "NVIDIA", "JENSEN"}, {"SENATE", "ALASKA"}, {"APPLE"}], [t["names"] for t in T18]
assert not any("XI" in t["names"] for t in T18)                                  # срещата: в този пул — Reuters и AP; CNBC (изместени) и FT World за 18.11 липсват
print("  ✓ Nvidia–Хуанг (9), изборите в Аляска (6), срив на Apple (3); срещата — под прага в приблизителния пул (Reuters + AP)")

print("── 3. заглавията на темите — първи в пула, различни издатели първо ──")
first = tt.pool_items(T19)
assert len(first) == 3 * config.THEME_POOL_PER_THEME - (config.THEME_POOL_PER_THEME - min(config.THEME_POOL_PER_THEME, T19[2]["n_headlines"]))
assert first[0]["title"] == a["headline"] and len({tt.publisher(x["source"]) for x in first[:4]}) == 4
print(f"  ✓ {len(first)} заглавия, по {config.THEME_POOL_PER_THEME} на тема; първите 4 — от 4 издателя")

print("── 4. СИНТЕТИЧНО: significant_news — темите влизат първи (мрежата и AI — подменени) ──")
raw = [dict(x, summary="") for x in FX["items19"] if not x["source"].startswith(("FT World", "Reuters World"))]
front = [dict(x, summary="") for x in FX["items19"] if x["source"].startswith(("FT World", "Reuters World"))]
def fake_gather(hours=24, since=None, **k):
    na.LAST_FRONT.clear(); na.LAST_FRONT.extend(front); na.LAST_WINDOW.clear(); na.LAST_WINDOW.update(sources={})
    return list(raw)
orig = (na.gather_raw, ai_brief._call_claude)
na.gather_raw = fake_gather
ai_brief._call_claude = lambda *a_, **k: '{"news": []}'
try:
    with contextlib.redirect_stdout(io.StringIO()):
        na.significant_news(max_items=8)
finally:
    na.gather_raw, ai_brief._call_claude = orig
pool = na.LAST_DIAG["pool"]
assert [p[2] for p in pool[:len(first)]] == [x["title"] for x in first] and na.LAST_WINDOW["themes_in_pool"] == len(first)
assert [t["key"] for t in na.LAST_THEMES] == [t["key"] for t in T19]
print(f"  ✓ първите {len(first)} в пула — заглавията на темите (сред тях FT World / Reuters World)")

print("── 5. страницата, имейлът, промптът ──")
B = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B); b["top_themes"] = T19
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(b, publish=False)
    mail = render.render_email(b)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
assert "Топ теми" in txt and f"„{s['headline']}“" in txt and "4 източника: AP, CNBC, FT, Reuters · 11 заглавия" in txt and txt.index("Топ теми") < txt.index("Пазарен термометър")
assert "Топ теми" in mail and "4 източника" in mail
p = ai_brief.macro_user_prompt({}, [], {"indicators": []}, themes=T19)
assert "ТОП ТЕМИ НА ДЕНЯ" in p and "САМО факти" in p
print("  ✓ „Топ теми“ над термометъра, в имейла и в промпта на разказа (само факти от заглавията)")
print("\n✅ test_top_themes: всичко мина")
