"""
19.10.2026 · етап 2, т. 14 (трети преглед, С3) + дребната "why" = заглавието: новините в news_aggregator.pick_verbatim.

  • Ехо: моделът връща и "h" — първите 6 думи на заглавието; кодът ги сверява с pool[i]. Объркан индекс (заглавието на брифа щеше да е на ДРУГА новина, а "why" — за първата) →
    еднозначният ред в пула със същото начало или отпадане с причина. Без "h" (стар отговор) — както досега, броят е в LAST_DIAG["no_echo"].
  • Числа: изречение в "why" с число, което го няма в заглавието и резюмето на източника (t, d — това вижда моделът), се маха. Не се броят: имена на индекси ("S&P 500",
    "Russell 2000"), срок с тире или слят ("10-year", "10-годишните", "19-годишен"), "10Y", "Q3", "G7".
  • "why" = заглавието (РЕАЛНО: в 16 от 16 реда на 16.10 и 19.10 "why" започва с преразказ на превода — "Нефтът върви към седмична печалба заради рисковете за доставките от
    Близкия изток, което …"): промптът казва, че "why" е САМО ефектът; кодово махане няма — припокриването на думите с превода е от 0.10 до 1.00 в тези 16 реда, не е надежден признак.

Измерено: 16 от 16 реални реда (16.10, 19.10) — "why" е за своето заглавие, 0 махнати числа; в историята 39 от 704 "why" с число извън ЗАГЛАВИЕТО (резюмето не се пази в брифа —
горна граница), 8 от тях — "~20% от световния петролен трафик" за Ормузкия проток.

РЕАЛНО: tests/fixtures/news_raw_pool_2026-10-15.json (142 заглавия с резюметата, 15.10 ~15:30 Берлин); новините на брифовете от 16.10 и 19.10 (tests/fixtures/brief_2026-10-16.json,
brief_2026-10-19.json). СИНТЕТИЧНО (означено): отговорите на модела (индекси, ехо, why).
Пускане: python test_news_echo.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import news_aggregator as na

FX = ROOT / "tests" / "fixtures"
POOL = json.loads((FX / "news_raw_pool_2026-10-15.json").read_text(encoding="utf-8"))["items"]
T = lambda i: POOL[i]["title"]
assert T(67).startswith("TSMC posts record profit") and T(13).startswith("Nvidia, AMD, Micron fall") and T(1).startswith("Wholesale prices jumped 6.3%")

print("── 1. ехото на заглавието (РЕАЛНИЯТ пул, СИНТЕТИЧНИ отговори) ──")
ans = [
    {"i": 67, "h": "TSMC posts record profit for a", "why": "Ориентир за AI търсенето."},                          # вярно
    {"i": 14, "h": "Nvidia, AMD, Micron fall as AI", "why": "Натиск върху полупроводниците."},                     # объркан индекс (13 → 14): поправя се
    {"i": 2, "h": "Oil prices surge on Iran deal", "why": "Петролът нагоре."},                                    # такова заглавие няма → отпада
    {"i": 0, "h": "Kremlin", "why": "Дизел."},                                                                    # 1 дума — твърде кратко → отпада
    {"i": 72, "why": "Енергийните приходи на Русия."},                                                            # без ехо — както досега
]
news, dropped = na.pick_verbatim(ans, POOL, 8)
assert [n["headline"] for n in news] == [T(67), T(13), T(72)], [n["headline"] for n in news]
reasons = [d["reason"] for d in dropped]
assert reasons == ["индексът поправен по заглавието: 14 → 13", "индексът не съвпада със заглавието", "ехото е по-кратко от 3 думи"], reasons
assert dropped[1]["pool_title"] == T(2)
print("  ✓ вярно ехо — приет; индекс 14 с ехото на 13 → поправен на 13 (ред в дневника); ехо без съвпадение и ехо от 1 дума — отпадат; без ехо — приет")

print()
print("── 2. числата в why (РЕАЛНИТЕ заглавия и резюмета, СИНТЕТИЧНИ why) ──")
assert "0.6%" in POOL[1]["summary"] and "0.6" not in T(1)
news, dropped = na.pick_verbatim([
    {"i": 1, "h": "Wholesale prices jumped 6.3% annually in", "why": "PPI +6.3% при очаквани 0.6% м/м — натиск върху Fed. Доходностите нагоре."},   # 0.6 — от резюмето
    {"i": 67, "h": "TSMC posts record profit for a", "why": "Печалбата е +40% — ориентир за AI. Подкрепа за полупроводниците в S&P 500."},          # 40 — измислено
    {"i": 25, "h": "U.S. Treasury dismisses IMF debt warning", "why": "10-годишните над 5% и дългът над $40 трлн натискат оценките."},             # 5, 40 — от резюмето; 10-годишните — срок
], POOL, 8)
assert news[0]["why"] == "PPI +6.3% при очаквани 0.6% м/м — натиск върху Fed. Доходностите нагоре."
assert news[1]["why"] == "Подкрепа за полупроводниците в S&P 500."
assert news[2]["why"] == "10-годишните над 5% и дългът над $40 трлн натискат оценките."
assert [d["removed"] for d in dropped] == [["Печалбата е +40% — ориентир за AI."]]
print("  ✓ число от резюмето (0.6%, $40 трлн, 5%) — остава; '+40%' за TSMC (няма го в източника) — изречението е махнато; 'S&P 500', '10-годишните' не са твърдения")

print()
print("── 3. РЕАЛНИТЕ новини от 16.10 и 19.10 (16 реда) ──")
for day in ("16", "19"):
    B = json.loads((FX / f"brief_2026-10-{day}.json").read_text(encoding="utf-8"))
    cuts = [na._why_numbers(n["why"], n["headline"])[1] for n in B["news"]]
    assert len(B["news"]) == 8 and cuts == [[]] * 8, (day, cuts)
B16 = json.loads((FX / "brief_2026-10-16.json").read_text(encoding="utf-8"))
mort = next(n for n in B16["news"] if "mortgage" in n["headline"])
assert "почти 3 години" in mort["why"] and "nearly 3 years" in mort["headline"]
print("  ✓ 0 махнати от 16 — сред тях 'почти 3 години' срещу 'nearly 3 years' (срок без тире е твърдение и е в заглавието)")

print()
print("── 4. промптът ──")
src = (ROOT / "src" / "news_aggregator.py").read_text(encoding="utf-8")
assert 'В \\"h\\" повтори ДОСЛОВНО първите 6 думи на заглавието' in src and "НЕ преразказва заглавието" in src and "no_echo=" in src
print("  ✓ искането за ехото, 'why' = само ефектът, броят на отговорите без ехо в LAST_DIAG")
print("\n✅ test_news_echo: всичко мина")
