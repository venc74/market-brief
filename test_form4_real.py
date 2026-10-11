"""
С6 (втори преглед, 10.10.2026) · Form 4 парсерите (insider_buying._parse_form4 — само открити покупки P; _parse_form4_all_codes — P и S с 10b5-1, за watch monitor) срещу РЕАЛНИ
документи от SEC (правило 9 — въведено заради инцидента с aff10b5One: синтетичен тест мина, а полето липсваше в 56/56 реални файла).

РЕАЛНО (sec.gov, изтеглени на 11.10.2026, tests/fixtures/form4/):
  • TFC_0001534574-26-000016.xml — Truist, Michael P. Lyons (President & CEO; isDirector/isOfficer във формат "true"), ОТКРИТА ПОКУПКА P на 17.09.2026: 21 000 акции × $48.3608, пряко (D), aff10b5One false;
  • BLSH_0000929638-26-003649.xml — Bullish, Andrew Bliss (директор, без officerTitle), ПРОДАЖБА S на 24.09.2026: 100 × $40.10, непряко (By Bliss Capital Limited), след нея 4 794 773, aff10b5One true;
  • TFC_0001681329-26-000006.xml — Truist, Donta L. Wilson (Chief Consumer & SB BK Officer), ПРОДАЖБА S на 31.07.2026: 13 280 × $51.8538, след нея 56 009.099, aff10b5One false.
СИНТЕТИЧНО (маркирано): булевите като "1"/"0" вместо "true"/"false" и махнат aff10b5One — текстови подмени върху реалните документи.
Пускане: python test_form4_real.py
"""
import sys, pathlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import insider_buying as ib

FX = ROOT / "tests" / "fixtures" / "form4"
TFC_P = (FX / "TFC_0001534574-26-000016.xml").read_text(encoding="utf-8")
BLSH_S = (FX / "BLSH_0000929638-26-003649.xml").read_text(encoding="utf-8")
TFC_S = (FX / "TFC_0001681329-26-000006.xml").read_text(encoding="utf-8")

print("── 1. _parse_form4 (Insider Buying — само P) ──")
p = ib._parse_form4(TFC_P)
assert p["ticker"] == "TFC" and p["company"] == "TRUIST FINANCIAL CORP"
assert p["owners"] == [{"name": "Lyons Michael P.", "title": "President & CEO", "is_officer": True}]          # isOfficer "true" (FIX 25.09) и &amp; в длъжността
tx = p["transactions"]
assert len(tx) == 1 and tx[0]["date"] == dt.date(2026, 9, 17) and tx[0]["shares"] == 21000.0 and tx[0]["price"] == 48.3608
assert abs(tx[0]["value"] - 21000 * 48.3608) < 1e-6 and tx[0]["internal_transfer"] is False and tx[0]["ownership"] == "D"
assert ib._parse_form4(BLSH_S) is None and ib._parse_form4(TFC_S) is None                                      # продажбите не са покупки
print("  ✓ TFC (Lyons, CEO): P 21 000 × $48.3608 = $1 015 576.80 на 17.09, пряко, служител; продажбите на BLSH и TFC (Wilson) → None")

print()
print("── 2. _parse_form4_all_codes (watch monitor — P и S, 10b5-1, дял) ──")
a = ib._parse_form4_all_codes(BLSH_S)
assert a["owners"] == [{"name": "Bliss Andrew", "title": "", "is_officer": False, "is_director": True}]
t = a["transactions"][0]
assert (t["code"], t["date"], t["shares"], t["price"], t["shares_after"], t["planned_10b5_1"]) == ("S", dt.date(2026, 9, 24), 100.0, 40.1, 4794773.0, True)
w = ib._parse_form4_all_codes(TFC_S)
assert w["owners"][0]["is_officer"] is True and w["owners"][0]["is_director"] is False and w["owners"][0]["title"] == "Chief Consumer & SB BK Officer"
t = w["transactions"][0]
assert (t["code"], t["shares"], t["price"], t["planned_10b5_1"]) == ("S", 13280.0, 51.8538, False) and t["shares_after"] == 56009.099 and t["pct_of_holdings"] == 19.2
l = ib._parse_form4_all_codes(TFC_P)["transactions"][0]
assert (l["code"], l["planned_10b5_1"], l["pct_of_holdings"]) == ("P", False, 50.0)                            # 21 000 от 42 000 преди → 50%
print("  ✓ BLSH (Bliss, директор): S 100 × $40.10, по план 10b5-1, след нея 4 794 773; TFC (Wilson): S 13 280 × $51.8538, извънпланова, 19.2% от дяла; TFC (Lyons): P, 50%")

print()
print("── 3. варианти на формата (СИНТЕТИЧНИ подмени върху реалните документи) ──")
p1 = ib._parse_form4(TFC_P.replace("<isOfficer>true</isOfficer>", "<isOfficer>1</isOfficer>"))
assert p1["owners"][0]["is_officer"] is True
b1 = ib._parse_form4_all_codes(BLSH_S.replace("<aff10b5One>true</aff10b5One>", "<aff10b5One>1</aff10b5One>"))
assert b1["transactions"][0]["planned_10b5_1"] is True
b0 = ib._parse_form4_all_codes(BLSH_S.replace("<aff10b5One>true</aff10b5One>", "<aff10b5One>0</aff10b5One>"))
assert b0["transactions"][0]["planned_10b5_1"] is False
bn = ib._parse_form4_all_codes(BLSH_S.replace("<aff10b5One>true</aff10b5One>", ""))
assert bn["transactions"][0]["planned_10b5_1"] is None                                                        # липсва → "неизвестно", не "извънпланова"
assert ib._parse_form4("<не е xml") is None and ib._parse_form4_all_codes("<не е xml") is None
print("  ✓ '1'/'0' = 'true'/'false'; без aff10b5One → None (неизвестно); невалиден XML → None")
print()
print("Всички тестове минаха.")
