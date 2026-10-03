"""
Пакет 2 · т.1 (2026-10-03): macro_tailwind през ETF → Yahoo сектор/индустрия (config.SECTOR_ETF_YAHOO) вместо
сравнение на български имена с английски Yahoo полета; само подредба и маркер SECT✓, никога филтър.

РЕАЛНО: ротацията и картите на четири брифа (tests/fixtures/brief_2026-06-29 / 09-08 / 09-22 / 10-02.json). Реплеят върху
всичките 78 брифа (data/, само четене): старо 0 от 645 карти, ново 253 (39%), 66 от 78 дни имат поне една. СИНТЕТИЧНО —
граничните случаи. Пускане: python test_sector_tailwind.py
"""
import sys, pathlib, json
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import sector_layer, screener

BR = {d: json.loads((ROOT / f"tests/fixtures/brief_{d}.json").read_text(encoding="utf-8")) for d in ("2026-06-29", "2026-09-08", "2026-09-22", "2026-10-02")}


def old_logic(card, names):                      # старото сравнение, дословно
    keys = [s.lower() for s in names]
    return any(k in (card.get("sector", "") + card.get("industry", "")).lower() or (card.get("sector", "").lower() in k) for k in keys)


print("── мостът покрива всички ETF-и ──")
etfs = [e for e in config.SECTOR_ETFS if "PROXY" not in e]
assert all(e in config.SECTOR_ETF_YAHOO for e in etfs) and len(etfs) == 17
print("  ✓ всеки от 17-те секторни ETF-а има Yahoo сектор или индустрия")

print("── РЕАЛНИ брифове ──")
expected = {"2026-06-29": (14, 1), "2026-09-08": (4, 2), "2026-09-22": (4, 4), "2026-10-02": (7, 7)}
for d, (n, tw) in expected.items():
    b = BR[d]
    leaders = sector_layer.leading_sectors(b["rotation"])
    cards = b["action"] + b["watchlist"]
    assert len(cards) == n
    assert not any(old_logic(c, [l["sector"] for l in leaders]) for c in cards)            # старото: никога
    assert sum(bool(sector_layer.tailwind_leaders(c, leaders)) for c in cards) == tw, d
b = BR["2026-10-02"]; leaders = sector_layer.leading_sectors(b["rotation"])
amd = next(c for c in b["watchlist"] if c["ticker"] == "AMD")
assert [m["etf"] for m in sector_layer.tailwind_leaders(amd, leaders)] == ["SMH", "XLK"]   # индустрия Semiconductors + сектор Technology
exel = next(c for c in BR["2026-06-29"]["watchlist"] + BR["2026-06-29"]["action"] if c["ticker"] == "EXEL")
assert [m["etf"] for m in sector_layer.tailwind_leaders(exel, sector_layer.leading_sectors(BR["2026-06-29"]["rotation"]))] == ["XBI"]
print("  ✓ старата логика: 0 от 29 карти; новата: 14 от 29 (29.06 EXEL → XBI; 02.10 AMD → SMH + XLK; 22.09 всичките четири Technology → XLK)")

print("── СИНТЕТИЧНО: граници ──")
m = sector_layer.etf_matches
assert m({"sector": "Technology"}, "XLK") and m({"sector": "technology"}, "XLK") and not m({"sector": "Technology."}, "XLK")
assert m({"sector": "Technology", "industry": "Semiconductors"}, "SMH") and m({"industry": "semiconductor equipment & materials"}, "SMH")
assert not m({"sector": "Technology", "industry": "Software - Infrastructure"}, "SMH")
assert m({"sector": "Healthcare", "industry": "Biotechnology"}, "XBI") and m({"sector": "Healthcare", "industry": "Biotechnology"}, "XLV")
assert not m({"sector": "", "industry": ""}, "XLK") and not m({}, "XLK") and not m({"sector": "Technology"}, "NOPE") and not m({"sector": "Technology"}, None)
assert not m({"sector": "Technology"}, "XLE")
print("  ✓ точно съвпадение без регистър; индустриален ETF (SMH, XBI) и секторен ETF (XLV) върху една и съща карта; празни полета и непознат ETF → не")

print("── подредба и маркер: никога филтър ──")
leaders = [{"etf": "XLE", "sector": "Енергетика", "rs_chg_4w_pct": 3.25}, {"etf": "SMH", "sector": "Полупроводници", "rs_chg_4w_pct": -0.5}]
cards = [{"ticker": "A", "sector": "Financial Services"}, {"ticker": "B", "sector": "Energy", "markers": [{"tag": "MF✓", "title": "x"}]},
         {"ticker": "C", "sector": "Technology", "industry": "Semiconductors"}, {"ticker": "D", "sector": "Utilities"}]
out = screener.apply_sector_tailwind([dict(c) for c in cards], leaders)
assert [c["ticker"] for c in out] == ["B", "C", "A", "D"] and len(out) == 4                 # tailwind първи, стабилно, нищо не отпада
assert out[0]["macro_tailwind"] and out[0]["tailwind_etfs"] == ["XLE"] and not out[2]["macro_tailwind"]
assert [mk["tag"] for mk in out[0]["markers"]] == ["MF✓", "SECT✓"]                         # маркерът се добавя към съществуващите
assert out[0]["markers"][1]["title"] == "Водещ сектор (макро попътен вятър): Енергетика (XLE, RS +3.2% за 4 седмици)"
assert "RS" in out[1]["markers"][0]["title"] and "-0.5%" in out[1]["markers"][0]["title"]
# само български имена (стар извикващ) → пак работи през обратното съпоставяне
out = screener.apply_sector_tailwind([dict(c) for c in cards], None, ["Енергетика"])
assert [c["ticker"] for c in out][:1] == ["B"] and out[0]["tailwind_etfs"] == ["XLE"]
# без водещи сектори → без промяна (нищо не се филтрира, нищо не се добавя)
same = screener.apply_sector_tailwind([dict(c) for c in cards], [], [])
assert [c["ticker"] for c in same] == ["A", "B", "C", "D"] and "macro_tailwind" not in same[0]
print("  ✓ tailwind картите са първи (стабилно), броят не се променя, маркерът SECT✓ се добавя към другите маркери със сектор и RS; без лидери — без промяна")
print()
print("Всички тестове минаха.")
