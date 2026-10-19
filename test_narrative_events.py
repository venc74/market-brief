"""
19.10.2026 · етап 2, "спекулативна проза" (дребните от 16.10): AI текстът на картата назова двигател, който го няма в данните и новините (EXPD 16.10: "… алтернатива на морски
маршрути през Червено море"). Евтин вариант: (1) промптът на тикърите получава дословните заглавия на деня с правилото да назовава събитие само ако е в тях или във веригите;
(2) кодът сверява назованите събития в двигателите (why_now, catalysts; не в рисковете) по затворен речник със заглавията, макро текста и веригите на деня и маха неподкрепените.
Измерено върху 89 реални брифа (740 карти): 6 махнати (тарифи ×4, кибератака ×1, Червено море ×1) — 0.8% от картите. Първата версия махаше и 5 верни текста: "тарифни повишения" при
застрахователи (ALL, TRV 29.07 — цените на премиите, не мита) и "военни" като описание на продукта/клиента (WWD 24.06, HWM 27.07 и 28.07) — сега не се пипат (раздел 4).

РЕАЛНО: tests/fixtures/brief_2026-10-16.json — картата на EXPD (катализаторът с "Червено море"), новините на деня ("Oil heads for weekly gain with Mideast supply risks"), макро и
веригите; tests/fixtures/narrative_texts_2026-06-24_10-12.json — AI текстовете на 10-те карти от измерването (data/<дата>.json, без промяна). СИНТЕТИЧНО (маркирано): изреченията за
граничните случаи, подмененото извикване на модела, празните източници в раздел 4.
Пускане: python test_narrative_events.py
"""
import sys, json, copy, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import ai_brief as ab

B16 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-16.json").read_text(encoding="utf-8"))
src = ab.narrative_event_sources(B16["ai_macro"], B16["news"])
quiet = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. РЕАЛНИЯТ случай: EXPD 16.10 ──")
cards = copy.deepcopy([c for c in B16["action"] if c["ticker"] == "EXPD"])
before = list(cards[0]["ai"]["catalysts"])
red = [x for x in before if "Червено море" in x]
assert len(red) == 1
with quiet():
    d = ab.verify_narrative_events(cards, src)
assert d == [{"ticker": "EXPD", "field": "catalysts", "events": ["Червено море"], "removed": red[0]}]
assert cards[0]["ai"]["catalysts"] == [x for x in before if x != red[0]]
print(f"  ✓ махнат катализаторът «{red[0][:70]}…» (Червено море — няма го в новините/макрото); останалите {len(before) - 1} — непокътнати")

print()
print("── 2. граници (СИНТЕТИЧНИ изречения, РЕАЛНИТЕ източници от 16.10) ──")
assert ab._unsupported_events("Геополитически рискове в Близкия изток повдигат петрола.", src) == []          # "Mideast" е в заглавията на деня
assert ab._unsupported_events("Митата върху вноса от Китай натискат маржа.", src) == ["тарифи"]
assert ab._unsupported_events("Компанията е ориентирана към структуриран растеж.", src) == []                 # "ориентиран" не е "Иран"
assert ab._unsupported_events("ATM strike на падежа 20.11.", src) == []                                       # английското strike не е стачка
c2 = [{"ticker": "X", "ai": {"why_now": "Техническият пробив е чист. Войната в региона вдига търсенето.", "catalysts": [], "risks": ["Ураганният сезон удря застрахователите."]}}]
with quiet():
    ab.verify_narrative_events(c2, src)
assert c2[0]["ai"]["why_now"] == "Техническият пробив е чист." and c2[0]["ai"]["risks"] == ["Ураганният сезон удря застрахователите."]   # рисковете не се пипат
print("  ✓ 'Близкия изток' (Mideast в заглавията) остава; мита без новина — махнато; 'ориентиран', 'strike' — не са събития; рисковете — непокътнати")

print()
print("── 3. промптът носи дословните заглавия ──")
p = ab._build_ticker_user_prompt([], [], "Defensive", B16["news"])
assert "ДНЕШНИ НОВИНИ (дословни заглавия): " in p and B16["news"][0]["headline"] in p and "САМО ако е в тези заглавия" in p
assert "ДНЕШНИ НОВИНИ" not in ab._build_ticker_user_prompt([], [], "Defensive")
seen = {}
real = ab._call_claude
ab._call_claude = lambda system, user, **k: seen.setdefault("u", user) and '{"tickers": []}'                    # СИНТЕТИЧНО
try:
    with quiet():
        ab.ticker_narratives([{"ticker": "EXPD", "setup": {"kind": "confirmed"}}], [], "Defensive", news=B16["news"])
finally:
    ab._call_claude = real
assert B16["news"][5]["headline"] in seen["u"]
print("  ✓ заглавията на деня са в промпта на тикърите (без новини — без блок)")
srcm = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "news=news)" in srcm and "ai_brief.verify_narrative_events(candidates, ai_brief.narrative_event_sources(ai_macro, news))" in srcm and '"narrative_events"' in srcm
print("  ✓ main подава новините и сверява текста")

print()
print("── 4. РЕАЛНИТЕ текстове от измерването (източниците — празни, СИНТЕТИЧНО: най-строгият случай) ──")
F = json.loads((ROOT / "tests" / "fixtures" / "narrative_texts_2026-06-24_10-12.json").read_text(encoding="utf-8"))
got = {}
for c in F["cards"]:
    cc = [{"ticker": c["ticker"], "ai": {"why_now": c["why_now"], "catalysts": copy.deepcopy(c["catalysts"])}}]
    with quiet():
        got[(c["date"], c["ticker"])] = [(x["field"], x["events"]) for x in ab.verify_narrative_events(cc, "")]
for k in [("2026-07-29", "ALL"), ("2026-07-29", "TRV"), ("2026-06-24", "WWD"), ("2026-07-27", "HWM"), ("2026-07-28", "HWM")]:
    assert got[k] == [], (k, got[k])
assert got[("2026-07-29", "ROST")] == [("catalysts", ["тарифи"])] and got[("2026-08-12", "AVT")] == [("why_now", ["тарифи"])]
assert got[("2026-09-16", "FTNT")] == [("catalysts", ["кибератака"])] and got[("2026-09-16", "EXPD")] == got[("2026-10-12", "EXPD")] == [("catalysts", ["тарифи"])]
print("  ✓ 'тарифни повишения' (ALL, TRV) и 'военни поръчки/двигатели' (WWD, HWM) не са събитие; ROST/AVT/EXPD тарифи и FTNT кибератаки — махат се")
print("\n✅ test_narrative_events: всичко мина")
