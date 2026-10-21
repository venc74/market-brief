"""
21.10.2026 · етап 4 (решение от 21.10): едното правило за „водещ сектор“ в кода отчита устойчивото изоставане — RS > 0 и на 4, и на 12 седмици (или RS на 6-месечен връх)
И да НЕ е потвърдено изоставащ (confirmed_laggard). До 21.10 секторната карта показваше XLP и XLY като водещи по снимката на деня, а текстът им ги наричаше потвърдено изоставащи
(75% и 80% от последните 20 сесии с отрицателна RS и на двата хоризонта). sector_layer.is_leader ползват leading_sectors (подредба и SECT✓), картата и промптът за веригите.
Измерено върху всички брифове с полето (39, от 13.06): водещ и потвърдено изоставащ едновременно — 3 дни (19, 20, 21.10: XLP; 21.10 и XLY); SECT✓ на Action картите не се мени (0 от 7).

РЕАЛНО: tests/fixtures/sector_card_2026-10-21.json — ротацията и веригите на модела от брифа на 21.10; tests/fixtures/brief_2026-10-19.json — ротацията на 19.10.
Пускане: python test_sector_leaders.py
"""
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import sector_layer, sector_claims, ai_brief

FX = json.loads((ROOT / "tests" / "fixtures" / "sector_card_2026-10-21.json").read_text(encoding="utf-8"))
rot = FX["rotation"]

print("── 1. правилото върху РЕАЛНАТА ротация от 21.10 ──")
snap = [r["etf"] for r in rot if r.get("leading") or r.get("rs_at_6m_high")]
assert snap == ["XLE", "XLP", "XLV", "XLY"]                                                    # по снимката на деня (старото правило)
assert [r["etf"] for r in sector_layer.leading_sectors(rot)] == ["XLE", "XLV"]
assert ai_brief._leaders_text(rot) == "XLE, XLV"
assert [r["etf"] for r in FX["sector_card"]["rows"]] == ["XLE", "XLP", "XLV", "XLY"]           # картата в брифа (стар код)
print("  ✓ по снимката на деня — XLE, XLP, XLV, XLY; по правилото — XLE и XLV (XLP 75%, XLY 80% изоставане); промптът — „XLE, XLV“")

print()
print("── 2. картата ──")
c = sector_claims.sector_card(FX["sector_logic"], rot)
assert [r["etf"] for r in c["rows"]] == ["XLE", "XLV"]
om = {o["etf"]: o["rs_line"] for o in c["omitted"]}
assert set(om) == {"XLP", "XLY"} and om["XLP"].endswith("· не е водещ: потвърдено изоставане — 75% от последните 20 сесии")
assert om["XLY"].endswith("— 80% от последните 20 сесии")
print(f"  ✓ водещи на картата: XLE, XLV; веригите на модела за XLP и XLY — в „не са водещи“: «{om['XLP']}»")

print()
print("── 3. 19.10 и празна ротация ──")
b19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
assert [r["etf"] for r in sector_layer.leading_sectors(b19["rotation"])] == ["XLE", "XLV"]
assert sector_layer.leading_sectors([]) == [] and sector_layer.is_leader({}) is False
assert sector_layer.is_leader({"leading": False, "rs_at_6m_high": True, "confirmed_laggard": False}) is True
print("  ✓ 19.10: XLP (85%) не е водещ; празна ротация — празно")
print("\n✅ test_sector_leaders: всичко мина")
