"""
Watchlist · текстът "Trigger" е на КОДА, не на модела (08.10.2026, точка 2б). Блокът "ВЧЕРАШНИ WATCHLIST TRIGGER-И" и полето watchlist_trigger от изхода на AI са махнати; текстът се сглобява от setup.trigger_text,
режимния gate (main._regime_gate) и отчета (earnings).

Защо: вчерашният текст на модела се подаваше обратно като "контекст" и се самоподсилваше (05.10: "Вече в портфейла / не добавяй" за AMD, AVT, ANET дори след архивирането на позициите — пакет 2 го
филтрираше със заплатка). На 08.10 и осемте Watchlist карти бяха със сетъп "too_wide", а Trigger-ът им беше свободен текст на модела — "Пазарният режим се промени на Neutral или по-добър" (режим
"Neutral" няма), "Вчерашният trigger НЕ е изпълнен…", условия, които кодът не проверява.

РЕАЛНО: tests/fixtures/watchlist_cards_2026-10-08.json — Watchlist картите от брифа на 08.10 (цена, pivot, обем, сетъп, отчет) с публикувания текст на модела; tests/fixtures/brief_2026-10-02.json —
Watchlist картите от 02.10 (три от тях със "Вече в портфейла" от модела). СИНТЕТИЧНО (маркирано): граничните случаи (отчет днес / без дата, потвърден сетъп, режим Cash), подменените _call_claude.
Пускане: python test_watchlist_trigger.py
"""
import sys, json, pathlib, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import ai_brief, main as brief_main

FX = json.loads((ROOT / "tests" / "fixtures" / "watchlist_cards_2026-10-08.json").read_text(encoding="utf-8"))
B02 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-02.json").read_text(encoding="utf-8"))
REGIME, CARDS = FX["regime"], FX["cards"]
assert REGIME == "Defensive" and len(CARDS) == 8 and {c["setup"]["kind"] for c in CARDS} == {"too_wide"}

print("── 1. промптът: няма блок с вчерашни тригери и няма поле watchlist_trigger ──")
slim = [{"ticker": "AAA"}]
prompt = ai_brief._build_ticker_user_prompt(slim, [], "Defensive")
assert "ВЧЕРАШНИ WATCHLIST TRIGGER" not in prompt and '- "watchlist_trigger"' not in prompt and "prior" not in prompt.lower()
assert 'НЕ пиши "watchlist_trigger"' in prompt and '"watchlist_reason_type"' in prompt
for gone in ("_load_prior_watchlist_triggers", "prior_trigger_usable", "_live_v2_positions", "_POSITION_WORDING"):
    assert not hasattr(ai_brief, gone), gone
import inspect
assert "prior_triggers" not in inspect.signature(ai_brief._build_ticker_user_prompt).parameters and "prior_triggers" not in inspect.signature(ai_brief._narratives_for_batch).parameters
print("  ✓ промптът няма блока «ВЧЕРАШНИ WATCHLIST TRIGGER-И» и казва на модела да не пише watchlist_trigger; помощниците за вчерашните тригери и параметърът prior_triggers са махнати")

print()
print("── 2. изходът на модела: полето се изхвърля, ако все пак дойде ──")
cand = [{"ticker": "AAA", "earnings": {}}]
out = ai_brief.merge_narratives(cand, [{"ticker": "AAA", "classification": "Watchlist", "watchlist_reason_type": "other", "watchlist_trigger": "Вчерашният trigger НЕ е изпълнен (СИНТЕТИЧЕН отговор на модела)", "why_now": "x"}])
assert "watchlist_trigger" not in out[0]["ai"] and out[0]["ai"]["watchlist_reason_type"] == "other"
print("  ✓ СИНТЕТИЧНО: отговор на модела с watchlist_trigger → полето е изхвърлено в merge_narratives; reason_type (за regime_gate изтичането) остава")

print()
print("── 3. РЕАЛНИТЕ осем Watchlist карти от 08.10: текстът от кода срещу публикувания на модела ──")
texts = {}
for c in CARDS:
    t = brief_main._watchlist_trigger_text(c, REGIME)
    texts[c["ticker"]] = t
    pub = c["ai_published"]["watchlist_trigger"] or ""
    assert c["setup"]["trigger_text"] in t and t.startswith(c["setup"]["trigger_text"]) or t.startswith("Отчет ")
    assert "Neutral" not in t and "Вчерашният" not in t
    assert "Режим Defensive — Action само при добър entry timing" in t                                   # режимният gate е част от текста: Defensive изисква entry timing "good", а сетъпът не е потвърден
assert "Neutral" in CARDS[0]["ai_published"]["watchlist_trigger"] and CARDS[0]["ticker"] == "ZBRA"        # реалният дефект: режим "Neutral"
assert "Вчерашният trigger НЕ е изпълнен" in next(c for c in CARDS if c["ticker"] == "NTAP")["ai_published"]["watchlist_trigger"]
print(f"  ✓ осемте текста: сетъпът от кода + режимният gate; без «Neutral», без «Вчерашният trigger»; публикуваните на 08.10 текстове на модела ги съдържаха (ZBRA: «… променил на Neutral …», NTAP: «Вчерашният trigger НЕ е изпълнен …»)")
print("    ZBRA: " + texts["ZBRA"][:260])
vlo = texts["VLO"]
assert next(c for c in CARDS if c["ticker"] == "VLO")["earnings"]["days_to_earnings"] == 14
assert not vlo.startswith("Отчет ")                                                                       # 14 дни е извън 0…7 → не е blackout
print("  ✓ VLO (отчет след 14 дни) не се третира като blackout — извън прозореца 0…7 дни")

print()
print("── 4. граници (СИНТЕТИЧНИ карти) ──")
base = {"ticker": "XYZ", "pct_from_pivot": -2.0, "volume_ratio": 1.0, "breakout_volume": False,
        "setup": {"kind": "below_pivot", "eligible": False, "trigger_text": "Чака пробив: buy-stop $10.00 (валиден 5 сесии, до 14.10)."}, "earnings": {}}
t0 = brief_main._watchlist_trigger_text(base, "Offensive")
assert t0 == "Чака пробив: buy-stop $10.00 (валиден 5 сесии, до 14.10)."
c1 = copy.deepcopy(base); c1["earnings"] = {"next_earnings": "2026-10-12", "days_to_earnings": 4, "in_blackout": True}
assert brief_main._watchlist_trigger_text(c1, "Offensive") == "Отчет на 2026-10-12 (4 дни) — нов Action най-рано след отчета. " + base["setup"]["trigger_text"]
c2 = copy.deepcopy(base); c2["earnings"] = {"next_earnings": "2026-10-08", "days_to_earnings": 0, "in_blackout": True}
assert brief_main._watchlist_trigger_text(c2, "Offensive").startswith("Отчет ДНЕС — нов Action най-рано след отчета.")
c3 = copy.deepcopy(base); c3["earnings"] = {"next_earnings": None, "days_to_earnings": None, "in_blackout": True}
assert brief_main._watchlist_trigger_text(c3, "Offensive").startswith("Отчет на неизвестна дата")
c4 = copy.deepcopy(base); c4["setup"] = {"kind": "confirmed", "eligible": True, "trigger_text": "Потвърден пробив: close $10.50 над pivot $10.00 (+5.0%), обем 1.8× ≥ 1.5× — купува се до $10.50."}
c4["pct_from_pivot"], c4["breakout_volume"] = 2.0, True
assert brief_main._watchlist_trigger_text(c4, "Offensive") == c4["setup"]["trigger_text"]                  # потвърден пробив, който AI не е избрал за Action: пак текстът на кода
assert brief_main._watchlist_trigger_text(c4, "Cash").endswith("Сетъпът се преценява отново, щом режимът се подобри.") and "Режим Cash" in brief_main._watchlist_trigger_text(c4, "Cash")
c5 = {"ticker": "NOSETUP", "earnings": {}}
assert brief_main._watchlist_trigger_text(c5, "Offensive") == "Не е избран за Action днес — виж „Защо точно сега“."
print("  ✓ СИНТЕТИЧНО: само сетъп; отчет с дата/днес/без дата + сетъп; потвърден пробив (Offensive — само сетъпът; Cash — + режимният gate); карта без нищо → «Не е избран за Action днес»")

print()
print("── 5. през apply_hard_rules и страницата ──")
card = copy.deepcopy(CARDS[0])
card.update({"sector": "Technology", "company": "Zebra", "ai": {"classification": "Watchlist", "watchlist_reason_type": "regime_gate", "why_now": "x"}})
with contextlib.redirect_stdout(io.StringIO()):
    action, watch = brief_main.apply_hard_rules([card], 0.5, "Defensive")
assert not action and watch[0]["ai"]["watchlist_trigger"] == brief_main._watchlist_trigger_text(CARDS[0], "Defensive")
assert watch[0]["ai"]["watchlist_reason_type"] == "regime_gate"                                              # reason_type (AI) остава — по него е изтичането на regime_gate
print("  ✓ ZBRA през apply_hard_rules: Trigger = текстът от кода; reason_type 'regime_gate' (AI) се пази за watchlist_expiry")
override = {**copy.deepcopy(CARDS[1]), "sector": "Technology", "ai": {"classification": "Action", "why_now": "x"}}
with contextlib.redirect_stdout(io.StringIO()):
    _, w2 = brief_main.apply_hard_rules([override], 0.5, "Defensive")
assert w2[0]["ai"]["watchlist_reason_type"] == "technical_gate" and w2[0]["ai"]["watchlist_trigger"] == CARDS[1]["setup"]["trigger_text"]
print("  ✓ AI казва Action, кодът връща в Watchlist (technical_gate): текстът е setup.trigger_text — както преди")
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "st.setup.trigger_text not in (st.ai.watchlist_trigger or '')" in tpl
print("  ✓ шаблонът не повтаря реда «Сетъп:», когато Trigger-ът вече съдържа setup.trigger_text")
print("\n✅ test_watchlist_trigger: всичко мина")
