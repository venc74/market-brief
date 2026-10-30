"""
15.10.2026 · фактите за секторите (sector_claims.facts) казват и кой е на 6-месечен връх по RS — за да не излиза "единственият сектор с потвърдено лидерство на двата времеви хоризонта"
(веригата за XLE на 15.10), когато на двата хоризонта са XLE, XLV и XLK, а само 6-месечният връх е на XLE.

РЕАЛНО: tests/fixtures/brief_2026-10-15.json — ротацията (17 ETF-а; XLE +3.85 / +13.63 и rs_at_6m_high; XLV +1.73 / +4.44; XLK +1.31 / +4.61) и веригата за XLE.
СИНТЕТИЧНО (маркирано): подмененият _call_claude, ротацията без поле rs_at_6m_high (стар формат).
Пускане: python test_sector_6m_high.py
"""
import sys, json, pathlib, contextlib, io, copy
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import sector_claims as sc, ai_brief

B15 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-15.json").read_text(encoding="utf-8"))
ROT = B15["rotation"]
xle = next(x for x in B15["ai_macro"]["sector_logic"] if x["etf"] == "XLE")["chain"]
assert "единственият сектор с потвърдено лидерство на двата времеви хоризонта и на 6m RS high" in xle

print("── 1. фактите от РЕАЛНАТА ротация на 15.10 ──")
f = sc.facts(ROT)
assert f["both"] == ["XLE", "XLV", "XLK"] and f["at_6m_high"] == ["XLE"]
assert f["text"] == ("Сектори с положителна RS и на 4, и на 12 седмици: XLE, XLV, XLK; само за 4 седмици: XLP, SMH; само за 12 седмици: GDX. "
                     "На 6-месечен връх по RS (до 1% под 6-месечния максимум): XLE."), f["text"]
print("  ✓", f["text"])
old = [{k: v for k, v in r.items() if k != "rs_at_6m_high"} for r in ROT]                          # СИНТЕТИЧНО: стар формат без полето
assert sc.facts(old)["at_6m_high"] == [] and sc.facts(old)["text"].endswith("На 6-месечен връх по RS (до 1% под 6-месечния максимум): нито един.")
print("  ✓ ротация без полето → 'нито един' (без изключение)")

print()
print("── 2. промптът ──")
prompts = []
ai_brief._call_claude = lambda system, user, **k: (prompts.append(user), json.dumps({"macro_brief": "x"}))[1]
with contextlib.redirect_stdout(io.StringIO()):
    ai_brief.macro_and_sector_brief({}, ROT, copy.deepcopy(B15["thermometer"]))
assert f["text"] not in prompts[0] and '"единственият" важи само когато списъкът е с един сектор' not in prompts[0]          # 30.10.2026 (разходката, т. 7): без веригите — и без правилото
print("  ✓ от 30.10 промптът е без фактите и правилото за 'единственият' (веригите по сектори отпаднаха); facts() по-горе остава")
print("\n✅ test_sector_6m_high: всичко мина")
