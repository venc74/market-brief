"""
19.10.2026 · етап 2, т. 6: Watchlist карта със задействан запис в книгата (EXPD 19.10) — (а) шаблонът показваше trigger_text два пъти ("Сетъп: ✅ Задействан …" и зеленият ред);
(б) кодът пишеше "Вече в портфейла от 2026-10-16 (entry $199.77). Повторният breakout сигнал потвърждава тезата — …" — това е запис в книгата (не портфейл), повторен пробив няма
(сетъпът на 19.10 е no_volume), датата е ISO. Сега: "Запис в книгата Action v2 от 16.10 (вход $199.77) — не е нов вход."

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — картата на EXPD (Watchlist, no_volume, задействан buy-stop запис от 09.10; текстът на кода от 19.10). Записът в книгата Action v2
(вход 16.10 по $199.77) — числата от същия текст. СИНТЕТИЧНО (маркирано): подмененото четене на книгите (_live_positions и др.) за apply_hard_rules.
Пускане: python test_book_card_text.py
"""
import sys, re, json, copy, pathlib, tempfile, io, contextlib, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_bookcard_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import render, main

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
EXPD = next(c for c in B19["watchlist"] if c["ticker"] == "EXPD")
TT = EXPD["setup"]["trigger_text"]
assert EXPD["setup"]["kind"] == "no_volume" and EXPD["setup"]["triggered"] and TT.startswith("✅ Задействан на 09.10 по $194.59")
assert EXPD["ai"]["watchlist_trigger"] == ("Вече в портфейла от 2026-10-16 (entry $199.77). Повторният breakout сигнал потвърждава тезата — "
                                           "управлявай съществуващата позиция, не добавяй риск.")                                    # какво казваше кодът на 19.10
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))

print("── (а) trigger_text веднъж на картата (РЕАЛНИЯТ бриф от 19.10) ──")
page = flat(render.render_dashboard(copy.deepcopy(B19)))
assert page.count(TT[:60]) == 1 and "Сетъп: ✅ Задействан" not in page
print("  ✓ '✅ Задействан на 09.10 по $194.59 …' — веднъж (до 19.10: два пъти, 'Сетъп: …' + зеленият ред)")

print()
print("── (б) текстът на кода за запис в Action книгата ──")
card = {k: copy.deepcopy(v) for k, v in EXPD.items() if k != "markers"}
card["ai"] = {"classification": "Action"}
saved = (main._live_positions, main._pending_action_plans, main._last_resolved_positions)
main._live_positions = lambda: {"EXPD": {"ticker": "EXPD", "fill_date": "2026-10-16", "entry_date": "2026-10-16", "entry_price": 199.77, "status": "open"}}   # СИНТЕТИЧНО четене, РЕАЛНИТЕ числа
main._pending_action_plans = lambda: {}
main._last_resolved_positions = lambda: {}
try:
    with contextlib.redirect_stdout(io.StringIO()):
        action, watch = main.apply_hard_rules([card], 1.0, "Defensive")
finally:
    main._live_positions, main._pending_action_plans, main._last_resolved_positions = saved
w = next(c for c in watch if c["ticker"] == "EXPD")
assert w["ai"]["watchlist_trigger"] == "Запис в книгата Action v2 от 16.10 (вход $199.77) — не е нов вход." and w["ai"]["watchlist_reason_type"] == "existing_position"
assert "портфейла" not in w["ai"]["watchlist_trigger"] and "потвърждава" not in w["ai"]["watchlist_trigger"]
print("  ✓ 'Запис в книгата Action v2 от 16.10 (вход $199.77) — не е нов вход.' (до 19.10: 'Вече в портфейла от 2026-10-16 … Повторният breakout сигнал потвърждава тезата …')")
print("\n✅ test_book_card_text: всичко мина")
