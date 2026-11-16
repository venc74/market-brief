"""
16.11.2026 (пакет 16.11, т. 6): заглавието на секторната карта („Водят 7 от 11 … — широка ротация извън мега-технологиите …“) стоеше същото от 02.11, докато RS за 4 седмици
на водещите се топеше (XLV 15.5 на 11.11 → 8.1 на 16.11). Сега заглавието се смята и от посоката: RS 4 седм. на първите три водещи срещу преди SECTOR_BOARD_RANK_LAG (5) сесии
— спад ≥ 30% и ≥ 3 пункта → „преднината на водещите се топи: … средно 13.1 → 7.6 за 5 сесии (XLV 14.6 → 8.1, …)“. Измерено 03.08–13.11 (74 сесии): 8 пъти; огледалното
„расте“ би било 24 пъти (при всяка смяна на водещите) — не се казва.

РЕАЛНО: tests/fixtures/sector_etfs_spy_closes_2026-11-13.csv — затварянията (auto_adjust) на 11-те секторни ETF-а и SPY от Yahoo, 01.04–13.11.2026, изтеглени 16.11.2026.
СИНТЕТИЧНО (означено): т. 3 — ред без "rs_4w_prev" (стар бриф).
Пускане: python test_sector_fade.py
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import sector_layer as sl

D = pd.read_csv(ROOT / "tests" / "fixtures" / "sector_etfs_spy_closes_2026-11-13.csv", index_col=0, parse_dates=True)
ETFS = {e: config.SECTOR_ETFS.get(e, e) for e in config.SECTOR_BOARD_ETFS}


def rows_at(day):
    data = D[D.index <= day]
    return sl.mark_leaders(sl.board_rows(data, data["SPY"].dropna(), ETFS), None)


print("── 1. РЕАЛНО: данни към 13.11 (брифът от 16.11) — преднината се топи ──")
r13 = rows_at("2026-11-13")
xlv = next(r for r in r13 if r["etf"] == "XLV")
assert (xlv["rs_4w"], xlv["rs_4w_prev"]) == (8.13, 14.56), (xlv["rs_4w"], xlv["rs_4w_prev"])
t = sl.leaders_trend(r13)
assert t["kind"] == "fade" and (t["prev"], t["now"]) == (13.1, 7.6) and t["etfs"] == ["XLV", "XLP", "XLY"]
S = sl.board_summary(r13, None)
assert S.endswith("широка ротация извън мега-технологиите — средната акция бие индекса (RS е спрямо SPY, претеглен по капитализация); преднината на водещите се топи: "
                  "RS за 4 седм. на първите три — средно 13.1 → 7.6 за 5 сесии (XLV 14.6 → 8.1, XLP 14.3 → 6.6, XLY 10.3 → 7.9)."), S
print(f"  ✓ „…{S[-150:]}“")

print("── 2. РЕАЛНО: 06.11 и 10.11 — без бележка; 74 сесии — 8 пъти ──")
for day in ("2026-11-06", "2026-11-10"):
    assert sl.leaders_trend(rows_at(day)) is None and "се топи" not in sl.board_summary(rows_at(day), None)
fired = [d.strftime("%d.%m") for d in D.index[D.index >= "2026-08-03"] if sl.leaders_trend(rows_at(d))]
assert fired == ["03.08", "05.08", "26.08", "10.09", "17.09", "08.10", "12.11", "13.11"], fired
print(f"  ✓ 06.11 / 10.11 — без бележка; „се топи“: {', '.join(fired)}")

print("── 3. СИНТЕТИЧНО: стар бриф без rs_4w_prev — без бележка ──")
old = [{k: v for k, v in r.items() if k != "rs_4w_prev"} for r in r13]
assert sl.leaders_trend(old) is None and "се топи" not in sl.board_summary(old, None)
print("  ✓ без полето — заглавието както до 16.11")
print("\n✅ test_sector_fade: всичко мина")
