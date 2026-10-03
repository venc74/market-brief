"""
Пакет 4а · т.1 (2026-10-03): Майкъл Бъри / Scion е махнат от DATAROMA_CIK; механизмът за мениджъри,
спрели да подават 13F ("stopped" → отделен ред, без moves/exits), е непроменен.

РЕАЛНО: самият списък от config.DATAROMA_CIK (15 мениджъра). СИНТЕТИЧНО: филингите и холдингите на
тестовите мениджъри (мрежата е подменена) — те не са реални 13F данни.
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
b = dataroma._fetch_all(config.DATAROMA_MIN_VALUE)
assert [m["manager"] for m in b["stopped_managers"]] == ["Спрял · Stopped Fund"]
assert b["stopped_managers"][0]["last_filing_date"] == OLD and b["stopped_managers"][0]["days_since_filing"] > config.DATAROMA_STALE_FILER_DAYS
assert all(r["manager"] == "Активен · Test Fund" for r in b["moves"] + b["new_positions"] + b["major_exits"])      # спрелият не произвежда редове
assert [r["company"] for r in b["new_positions"]] == ["NEWCO INC"] and [r["company"] for r in b["major_exits"]] == ["GONECO INC"]
print("  ✓ мениджър с последен filing 03.11.2025 → 'stopped' (отделен ред, не 'продал всичко'), не произвежда moves/exits;")
print("    активният мениджър си произвежда нова позиция (NEWCO) и голям изход (GONECO)")
tmp.cleanup()

print()
print("Всички тестове минаха.")
