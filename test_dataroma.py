"""
Пакет 4а · т.1 (2026-10-03): Майкъл Бъри / Scion е махнат от DATAROMA_CIK; механизмът за мениджъри,
спрели да подават 13F ("stopped" → отделен ред, без moves/exits), е непроменен.

РЕАЛНО: самият списък от config.DATAROMA_CIK (15 мениджъра). СИНТЕТИЧНО: филингите и холдингите на
тестовите мениджъри (мрежата е подменена) — те не са реални 13F данни.

т.9 (2026-10-03): мащабът хиляди/долари на стойностите в 13F — датата на филинга + проверка по цена/акция; старата
евристика ("най-голяма позиция под 1e7 → хиляди") вдигаше 1000× малък фонд в долари. Всички холдинги тук са
СИНТЕТИЧНИ (реални филинги не могат да се теглят от тук — SEC връща 403 на анонимен User-Agent).
Пускане: python test_dataroma.py
"""
import sys, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import dataroma

print("── списъкът с мениджъри (РЕАЛЕН конфиг) ──")
assert "0001649339" not in config.DATAROMA_CIK
assert not any("Бъри" in n or "Scion" in n or "Burry" in n for n in config.DATAROMA_CIK.values())
assert len(config.DATAROMA_CIK) == 15 and "Уорън Бъфет · Berkshire Hathaway" in config.DATAROMA_CIK.values()
print("  ✓ Scion (CIK 0001649339) го няма; останалите 15 мениджъра са непроменени")
print()

print("── механизмът за спрели мениджъри е непроменен (СИНТЕТИЧНИ мениджъри, мрежата е подменена) ──")
tmp = tempfile.TemporaryDirectory(prefix="market_brief_dr_")
dataroma._CACHE = pathlib.Path(tmp.name) / "dataroma_cache.json"
dataroma._TMAP_CACHE = pathlib.Path(tmp.name) / "sec_tickers.json"
config.DATA_DIR = pathlib.Path(tmp.name)
dataroma._ticker_map = lambda: {}
today = dt.date.today()
OLD = "2025-11-03"                                    # както Scion: последен filing преди >165 дни
FRESH = (today - dt.timedelta(days=30)).isoformat()
FILINGS = {"0000000001": [("a-new", FRESH), ("a-old", "2026-05-01")],
           "0000000002": [("b-last", OLD)]}
HOLD = {"a-new": [{"issuer": "NEWCO INC", "value": 50_000_000.0, "cusip": "N1", "shares": 1000.0},
                  {"issuer": "OLDCO INC", "value": 50_000_000.0, "cusip": "O1", "shares": 1000.0}],
        "a-old": [{"issuer": "OLDCO INC", "value": 50_000_000.0, "cusip": "O1", "shares": 1000.0},
                  {"issuer": "GONECO INC", "value": 20_000_000.0, "cusip": "G1", "shares": 500.0}],
        "b-last": [{"issuer": "ZZZ INC", "value": 90_000_000.0, "cusip": "Z1", "shares": 900.0}]}
dataroma._recent_13f_filings = lambda cik, n=2: FILINGS.get(cik, [])[:n]
dataroma._info_table = lambda cik, acc: [dict(h) for h in HOLD.get(acc, [])]
config.DATAROMA_CIK = {"0000000001": "Активен · Test Fund", "0000000002": "Спрял · Stopped Fund"}
dataroma._MEMO.clear()
b = dataroma._fetch_all(config.DATAROMA_MIN_VALUE)
assert [m["manager"] for m in b["stopped_managers"]] == ["Спрял · Stopped Fund"]
assert b["stopped_managers"][0]["last_filing_date"] == OLD and b["stopped_managers"][0]["days_since_filing"] > config.DATAROMA_STALE_FILER_DAYS
assert all(r["manager"] == "Активен · Test Fund" for r in b["moves"] + b["new_positions"] + b["major_exits"])      # спрелият не произвежда редове
assert [r["company"] for r in b["new_positions"]] == ["NEWCO INC"] and [r["company"] for r in b["major_exits"]] == ["GONECO INC"]
print("  ✓ мениджър с последен filing 03.11.2025 → 'stopped' (отделен ред, не 'продал всичко'), не произвежда moves/exits;")
print("    активният мениджър си произвежда нова позиция (NEWCO) и голям изход (GONECO)")

print()
print("── т.9: мащаб хиляди/долари (СИНТЕТИЧНИ холдинги) ──")
def agg(positions):
    """positions = [(value, shares), ...] → CUSIP агрегат като от _aggregate_by_cusip."""
    return {f"C{i}": {"issuer": f"CO{i}", "value": float(v), "shares": float(s)} for i, (v, s) in enumerate(positions)}

def legacy(a):                                                                   # старата евристика, за контраст
    mx = max((x["value"] for x in a.values()), default=0)
    return 1000 if mx and mx < 1e7 else 1

# малък фонд (портфейл ~$30M, най-голямата позиция $8M), ДОЛАРИ, филинг 2026: цени $20–$400
small = agg([(8_000_000, 40_000), (6_000_000, 100_000), (5_000_000, 12_500), (4_500_000, 50_000), (3_500_000, 70_000), (3_000_000, 15_000)])
assert legacy(small) == 1000                                                      # старото грешеше: $8M → $8 млрд
assert dataroma._value_scale(small, "2026-08-14") == (1, "price")
big = agg([(60_000_000_000, 300_000_000), (30_000_000_000, 150_000_000), (9_000_000_000, 80_000_000), (5e9, 25_000_000), (2e9, 10_000_000)])
assert dataroma._value_scale(big, "2026-08-14") == (1, "price") and legacy(big) == 1
# ХИЛЯДИ (филинг преди 03.01.2023): стойностите са 1000× по-малки → цена/акция стотни; и двата сигнала са съгласни
old_k = agg([(8_000, 40_000), (6_000, 100_000), (5_000, 12_500), (4_500, 50_000), (3_500, 70_000)])
assert dataroma._value_scale(old_k, "2022-11-14") == (1000, "price")
# голям фонд в хиляди: най-голямата позиция $60 млрд/1000 = 6e7 ≥ 1e7 → старото го мереше като долари (1000× по-малко)
big_k = agg([(60_000_000, 300_000_000), (30_000_000, 150_000_000), (9_000_000, 80_000_000), (5_000_000, 25_000_000), (2_000_000, 10_000_000)])
assert legacy(big_k) == 1 and dataroma._value_scale(big_k, "2022-11-14") == (1000, "price")
# филър, който не спазва правилото: филинг 2026, но стойностите са в хиляди → цената надделява над датата
rogue = agg([(8_000, 40_000), (6_000, 100_000), (5_000, 12_500), (4_500, 50_000), (3_500, 70_000)])
assert dataroma._value_scale(rogue, "2026-08-14") == (1000, "price_override")
# ранно приел долари: филинг 2022, но цената казва долари
early = agg([(8_000_000, 40_000), (6_000_000, 100_000), (5_000_000, 12_500), (4_500_000, 50_000), (3_500_000, 70_000)])
assert dataroma._value_scale(early, "2022-11-14") == (1, "price_override")
# малко позиции (< 5 с цена) → само датата; без дата и без цена → долари
few = agg([(8_000, 40_000), (6_000, 100_000)])
assert dataroma._value_scale(few, "2022-11-14") == (1000, "date") and dataroma._value_scale(few, "2026-08-14") == (1, "date")
assert dataroma._value_scale(few, None) == (1, "default_dollars") and dataroma._value_scale({}, "garbage") == (1, "default_dollars")
# облигации/позиции без акции не влизат в медианата
mixed = {**small, "B1": {"issuer": "BOND", "value": 9e6, "shares": 0.0}}
assert dataroma._value_scale(mixed, "2026-08-14") == (1, "price")
print("  ✓ малък фонд в долари ($8M най-голяма позиция) → ×1 (старото: ×1000); голям фонд в хиляди → ×1000 (старото: ×1);")
print("    филър в хиляди след 2023 → цената печели ('price_override'); малко позиции → датата; без дата/цена → долари")

# край-до-край през _manager_snapshot: малкият фонд ($30M) с нова позиция от $1M
tmp2 = tempfile.TemporaryDirectory(prefix="market_brief_dr2_")
dataroma._CACHE = pathlib.Path(tmp2.name) / "c.json"
FRESH2 = (dt.date.today() - dt.timedelta(days=30)).isoformat()
dataroma._recent_13f_filings = lambda cik, n=2: [("s-new", FRESH2), ("s-old", "2026-05-01")]
rows_new = [{"issuer": f"CO{i}", "value": v, "cusip": f"C{i}", "shares": s} for i, (v, s) in enumerate(
    [(8_000_000, 40_000), (6_000_000, 100_000), (5_000_000, 12_500), (4_500_000, 50_000), (3_500_000, 70_000), (3_000_000, 15_000), (1_000_000, 8_000)])]
rows_old = [dict(r) for r in rows_new[:6]]
dataroma._info_table = lambda cik, acc: [dict(r) for r in (rows_new if acc == "s-new" else rows_old)]
snap = dataroma._manager_snapshot("0000000009", "Малък · Tiny Fund")
assert snap["current_scale"] == 1 and snap["prev_scale"] == 1 and snap["current_scale_basis"] == "price"
assert snap["current_total"] == 31_000_000.0
hl = dataroma._new_position_highlights_from_snapshot(snap, {})
assert [(r["company"], r["pct_of_portfolio"]) for r in hl] == [("CO6", 3.2)]                   # $1M от $31M = 3.2% (с ×1000: 3.2% от $31 млрд = $1 млрд)
assert hl[0]["value"] == 1_000_000.0
moves = dataroma._moves_from_snapshot(snap, config.DATAROMA_MIN_VALUE, {})
assert moves == []                                                                              # нито една позиция не стига $10M прага (старото: 7 редове "$млрд")
print("  ✓ край-до-край: фонд от $31M → нова позиция $1M = 3.2% от портфейла (не $1 млрд), нито един ред в Moves под прага $10M")
tmp2.cleanup()

tmp.cleanup()

print()
print("Всички тестове минаха.")
