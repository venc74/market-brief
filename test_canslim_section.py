"""
30.10.2026 · разходката, т. 9–10: един раздел „CANSLIM“ вместо отделни Action и Watchlist.
  • Класът (купува се днес / чака) е САМО на кода: потвърден пробив (setup.eligible) → кандидат за Action, после отчетът, режимът, лимитите и планът; всичко друго — Watchlist.
    AI не класифицира: промптът не иска classification / watchlist_reason_type, merge_narratives ги изхвърля, apply_hard_rules не чете ai.classification. Измерено върху 20-те
    брифа с кодов сетъп (05–30.10): AI е свалил потвърден пробив веднъж — ROKU 23.10 (цел на придобиване; от 26.10 кодът я прави "deal"); вдигане не е възможно (кодовият gate).
  • Подредба: „Купува се днес“ (пълни карти с плана; празно → „Днес няма потвърден пробив.“) → „Чака пробив“ (под pivot с buy-stop ниво и срок — пълни карти) → „На радара (N)“
    (сгъната таблица: тикър, сектор, цена, % спрямо pivot, причината с числото, RS рейтинг, от колко брифа е в раздела) → „Излязоха от вчера“; книгите — сгънати, под раздела.

РЕАЛНО: tests/fixtures/brief_2026-10-14.json, brief_2026-10-15.json, brief_2026-10-16.json (16.10: Action EXPD, ZBRA с buy-stop, 8 too_wide), brief_2026-10-19.json
(EXPD — запис в Action книгата), brief_2026-10-05.json (EXPD под pivot).
СИНТЕТИЧНО (означено): отговорът на модела (classification), отчетът в прозореца, режимът Defensive върху реалната карта, extended / no_volume с измислени числа, празният ден.
Пускане: python test_canslim_section.py
"""
import sys, json, copy, shutil, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_canslim_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
config.ENABLE_BACKTEST = False
from src import ai_brief, render, watchlist_exits, main as brief_main

FXD = ROOT / "tests" / "fixtures"
B = {d: json.loads((FXD / f"brief_{d}.json").read_text(encoding="utf-8")) for d in ("2026-10-05", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19")}
B16 = B["2026-10-16"]
q = lambda: contextlib.redirect_stdout(io.StringIO())
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))

print("── 1. класът е само на кода ──")
expd = copy.deepcopy(B16["action"][0])
assert expd["ticker"] == "EXPD" and expd["setup"]["kind"] == "confirmed" and expd["setup"]["eligible"]
expd["ai"] = {"classification": "Watchlist", "watchlist_reason_type": "other", "why_now": "x"}                    # СИНТЕТИЧНО: моделът „сваля“ потвърдения пробив
hum = copy.deepcopy(next(c for c in B16["watchlist"] if c["ticker"] == "HUM"))
hum["ai"] = {"classification": "Action", "why_now": "x"}                                                          # СИНТЕТИЧНО: моделът „вдига“ too_wide
with q():
    act, wl = brief_main.apply_hard_rules([expd, hum], 1.0, "Offensive")
assert [c["ticker"] for c in act] == ["EXPD"] and [c["ticker"] for c in wl] == ["HUM"] and wl[0]["ai"]["watchlist_reason_type"] == "technical_gate"
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
body = src[src.index("def apply_hard_rules"):src.index("def _annotate_screener_exits")]
assert 'get("classification"' not in body and '["classification"]' not in body
assert 'cls = "Watchlist" if forced else ("Action" if setup.get("eligible") else "Watchlist")' in body
prompt = ai_brief._build_ticker_user_prompt([{"ticker": "AAA"}], [], "Offensive")
assert "се решава САМО от кода" in prompt and "избери най-силните" not in prompt and "Правила: максимум" not in prompt
merged = ai_brief.merge_narratives([{"ticker": "AAA", "earnings": {}}], [{"ticker": "AAA", "classification": "Action", "watchlist_reason_type": "regime_gate", "why_now": "x"}])
assert merged[0]["ai"] == {"ticker": "AAA", "why_now": "x"}
print("  ✓ РЕАЛНИТЕ EXPD (потвърден пробив) и HUM (too_wide) от 16.10: „Watchlist“ / „Action“ от модела не променят нищо — EXPD е Action, HUM — Watchlist (technical_gate)")
print("  ✓ apply_hard_rules не чете ai.classification; промптът не иска клас и не „избира най-силните“; merge изхвърля classification / watchlist_reason_type")

print()
print("── 2. „Чака пробив“ и „На радара“ — РЕАЛНИЯТ 16.10 ──")
waiting, radar = render.split_canslim(B16["watchlist"])
assert [c["ticker"] for c in waiting] == ["ZBRA"] and [r["ticker"] for r in radar] == ["HUM", "WSM", "PSX", "BBY", "AMG", "THC", "LLY", "EBAY"]
h = radar[0]
assert (h["sector"], h["price"], h["pct_from_pivot"], h["reason"], h["rs_rating"]) == ("Healthcare", 432.2, 0.77, "разтегната · стоп 13.9%", 94)
print("  ✓ Чака пробив: ZBRA (buy-stop $390.80); На радара (8): HUM Healthcare $432.20 +0.8% „разтегната · стоп 13.9%“ RS 94, WSM, PSX, …")
e19 = next(c for c in B["2026-10-19"]["watchlist"] if c["ticker"] == "EXPD")                                       # РЕАЛНО: запис в Action книгата + задействан buy-stop
assert render.radar_reason(e19).startswith("Вече в портфейла от 2026-10-16")
nv = {"setup": {"kind": "no_volume"}, "volume_ratio": 0.93}                                                       # СИНТЕТИЧНИ числа
ex = {"setup": {"kind": "extended", "pct_from_pivot": 7.24}}
rb = {"setup": {"kind": "confirmed"}, "ai": {"watchlist_reason_type": "regime_block"}}
eb = {"setup": {"kind": "confirmed"}, "ai": {"watchlist_reason_type": "earnings_blackout"}, "earnings": {"next_earnings": "2026-11-03", "days_to_earnings": 4}}
assert [render.radar_reason(x) for x in (nv, ex, rb, eb)] == ["пробив без обем · 0.9× (< 1.5×)", "над зоната за покупка · +7.2% (> +5%)", "блокирана от режима",
                                                               "отчет на 03.11 (4 дни) — вход след отчета"]
print("  ✓ причините с числото: «пробив без обем · 0.9×», «над зоната за покупка · +7.2%», «блокирана от режима», «отчет на 03.11 (4 дни)», записът в книгата — текстът на кода")
with q():
    _, wd = brief_main.apply_hard_rules([copy.deepcopy(B16["action"][0]) | {"pct_from_pivot": 4.0, "volume_ratio": 1.8}], 1.0, "Defensive")   # СИНТЕТИЧНО: Defensive, +4% над pivot
assert render.split_canslim(wd)[1][0]["reason"] == "блокирана от режима; в buy-stop книгата: отворена от 09.10 по $194.59"
print("  ✓ РЕАЛНАТА EXPD в СИНТЕТИЧЕН Defensive (+4% над pivot) → ред „блокирана от режима; в buy-stop книгата: отворена от 09.10 по $194.59“")

print()
print("── 3. „от колко дни е на радара“ — поредните брифове (РЕАЛНИТЕ 14–16.10) ──")
for d in ("2026-10-14", "2026-10-15", "2026-10-16"):
    shutil.copy(FXD / f"brief_{d}.json", config.DATA_DIR / f"{d}.json")
days = watchlist_exits.radar_days(["ZBRA", "HUM", "WSM", "EXPD", "NEW"], "2026-10-19")
assert days == {"ZBRA": 4, "HUM": 4, "WSM": 2, "EXPD": 4, "NEW": 1}, days
(config.DATA_DIR / "2026-10-15.json").write_text("{не е json", encoding="utf-8")                                    # СИНТЕТИЧНО: нечетим бриф — прескача се
with q():
    assert watchlist_exits.radar_days(["ZBRA"], "2026-10-19") == {"ZBRA": 3}
assert "watchlist_exits.radar_days([c[\"ticker\"] for c in action + watchlist], today)" in src and 'c["radar_days"] = _days[c["ticker"]]' in src
print("  ✓ ZBRA, HUM, EXPD — 4 (14, 15, 16 и днес), WSM — 2 (от 16.10), нов — 1; нечетим бриф се прескача; main записва radar_days на картите")

print()
print("── 4. страницата: CANSLIM — купува се днес → чака пробив → на радара (сгънат) → излязоха; книгите — под раздела ──")
b = copy.deepcopy(B16)
for c in b["watchlist"]:
    c["radar_days"] = 3                                                                                            # СИНТЕТИЧНО: стойността на колоната
with q():
    page = render.render_dashboard(b, publish=False)
sec = page[page.index('<section id="canslim">'):page.index("</section>", page.index('<section id="canslim">'))]
t = flat(sec)
order = [t.index(x) for x in ("CANSLIM", "Купува се днес · 1", "EXPD", "Чака пробив · 1", "ZBRA", "На радара (8)", "Излязоха от")]
assert order == sorted(order) and "<h2>Action" not in page and "<h2>Watchlist" not in page
assert '<details class="cs-radar">' in sec and '<details class="cs-radar" open' not in sec                           # сгънат
assert "Тикър Сектор Цена Спрямо pivot Причина RS Дни HUM SECT✓" in t and "Healthcare $432.20 +0.8% разтегната · стоп 13.9% · отчет 06.11 94 3 WSM" in t   # маркерът — с подсказката
assert page.index('<section id="canslim">') < page.index("Track Record v2") and page.index("Track Record v2") < page.index("Buy-stop кандидати — измерване")
empty = copy.deepcopy(B16); empty["action"] = []; empty["watchlist"] = []                                            # СИНТЕТИЧНО: празен ден
with q():
    te = flat(render.render_dashboard(empty, publish=False))
assert "Купува се днес · 0 Днес няма потвърден пробив." in te and "Чака пробив · 0 Няма кандидат под pivot с buy-stop." in te and "На радара (" not in te
print("  ✓ ред: CANSLIM → Купува се днес · 1 (EXPD) → Чака пробив · 1 (ZBRA) → На радара (8), сгънат → Излязоха; Track Record v2 и buy-stop книгата — под раздела")
print("  ✓ празен ден: „Днес няма потвърден пробив.“, „Няма кандидат под pivot с buy-stop.“, без „На радара“")

print()
print("── 5. имейлът — същият ред ──")
with q():
    m = flat(render.render_email(copy.deepcopy(B16)))
order = [m.index(x) for x in ("CANSLIM · купува се днес · 1", "EXPD", "Чака пробив · 1: ZBRA Buy-stop $390.80", "На радара (8): HUM — разтегната · стоп 13.9%, отчет 06.11", "Излязоха от")]
assert order == sorted(order)
print("  ✓ „CANSLIM · купува се днес · 1“ → „Чака пробив · 1: ZBRA Buy-stop $390.80 …“ → „На радара (8): HUM — разтегната · стоп 13.9% …“ → „Излязоха от …“")
print("\n✅ test_canslim_section: всичко мина")
