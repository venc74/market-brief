"""
16.10.2026 · т. 8 (трети преглед): имейлът. (а) скрит индикатор не е жълта точка (status "yellow" е само запълване) — ред "Скрити днес: … — причина", както на страницата;
(б) Watchlist с buy-stop, стоп и отчет (CLAUDE.md, 07.10: "Имейлът: само вход, стоп, стоп % и предупрежденията"; 4б: отчетът и в имейла) — до 16.10 само тикърите;
(в) Action — бележката за buy-stop книгата ("в buy-stop книгата: отворена от ДД.ММ по $X").

РЕАЛНО: tests/fixtures/brief_2026-09-08.json (4 скрити индикатора: Fed Net Liquidity, MOVE, VIX Term Structure, IEI/HYG — в имейла бяха 4 жълти точки от 9; в историята 31 от 88 брифа
имат скрит индикатор), brief_2026-10-16.json (ZBRA buy-stop $390.80, стоп $360.30 −7.8%, отчет 03.11; 8 компактни реда; EXPD Action с бележката за книгата), brief_2026-10-14.json
(EXPD — задействан buy-stop, карта) и brief_2026-10-15.json (EXPD — задействан, компактен ред). Без СИНТЕТИЧНИ входове.
Пускане: python test_email_watchlist.py
"""
import sys, re, json, pathlib, tempfile, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_email_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import render

B = {d: json.loads((ROOT / "tests" / "fixtures" / f"brief_{d}.json").read_text(encoding="utf-8")) for d in ("2026-09-08", "2026-10-14", "2026-10-15", "2026-10-16")}
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))
DOT = re.compile(r'<span title="([^"]*)" style="display:inline-block;width:\d+px;height:\d+px;border-radius:50%')

print("── (а) скритите индикатори (РЕАЛНИЯТ бриф от 08.09) ──")
ind = B["2026-09-08"]["thermometer"]["indicators"]
hidden = [i["name"] for i in ind if i.get("hide")]
assert hidden == ["Fed Net Liquidity", "MOVE (Bond Vol)", "VIX Term Structure", "IEI/HYG (Credit Spread)"] and {i["status"] for i in ind if i.get("hide")} == {"yellow"}
e = render.render_email(B["2026-09-08"])
dots = [m.group(1) for m in DOT.finditer(e)]
assert len(ind) == 9 and dots == [i["name"] for i in ind if not i.get("hide")] and not set(hidden) & set(dots)
assert "Скрити днес: Fed Net Liquidity — няма данни · MOVE (Bond Vol) — няма данни · VIX Term Structure — няма данни · IEI/HYG (Credit Spread) — няма данни" in flat(e)
e16 = render.render_email(B["2026-10-16"])
assert len(DOT.findall(e16)) == len(B["2026-10-16"]["thermometer"]["indicators"]) and "Скрити днес" not in flat(e16)       # без скрити — всички точки, без ред
print(f"  ✓ 08.09: {len(dots)} точки (беше 9, от тях 4 жълти за скритите) + 'Скрити днес: Fed Net Liquidity — няма данни · MOVE …'; 16.10 (без скрити) — всички 10 точки, без ред")

print()
print("── (б) Watchlist с buy-stop, стоп и отчет (РЕАЛНИЯТ бриф от 16.10) ──")
f16 = flat(e16)
assert "Watchlist · 9: ZBRA Buy-stop $390.80 (таван $410.34, валиден до 20.10, от 14.10) · Stop $360.30 (−7.8%) ⚠ Отчет на 03.11 (след 12 сесии)" in f16
assert "Без сетъп за вход днес: HUM — структурен стоп 13.9% > 10%, отчет 06.11 · WSM — структурен стоп 12.5% > 10% · PSX — структурен стоп 14.9% > 10%, отчет 28.10" in f16
assert f16.count("EBAY — структурен стоп 15.7% > 10%, отчет 28.10") == 1
print("  ✓ 'ZBRA Buy-stop $390.80 (таван $410.34, валиден до 20.10, от 14.10) · Stop $360.30 (−7.8%) ⚠ Отчет на 03.11 …'; 'Без сетъп за вход днес: HUM — структурен стоп 13.9% > 10%, отчет 06.11 · …'")
f14 = flat(render.render_email(B["2026-10-14"]))
assert "EXPD ✅ Задействан на 09.10 по $194.59 (buy-stop от 09.10) · стоп $181.53 · цел 2R $220.71" in f14 and "EXPD Buy-stop" not in f14       # задействан → не "чака buy-stop"
f15 = flat(render.render_email(B["2026-10-15"]))
assert "EXPD — ✅ задействан в buy-stop книгата на 09.10 по $194.59, стоп $181.53 (6.7% под входа)" in f15
print("  ✓ 14.10 (карта): 'EXPD ✅ Задействан на 09.10 по $194.59 …' вместо buy-stop; 15.10 (компактен): 'EXPD — ✅ задействан в buy-stop книгата на 09.10 по $194.59, стоп $181.53 …'")

print()
print("── (в) Action — бележката за buy-stop книгата (РЕАЛНИЯТ бриф от 16.10) ──")
i = f16.find("EXPD Expeditors")
assert i >= 0 and "в buy-stop книгата: отворена от 09.10 по $194.59" in f16[i:f16.find("Watchlist ·")]
print("  ✓ EXPD (Action, потвърден пробив): 'в buy-stop книгата: отворена от 09.10 по $194.59' — и в имейла")
print("\n✅ test_email_watchlist: всичко мина")
