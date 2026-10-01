"""
Тест за т.2 от прегледа на 01.10: _price_diverges() в thesis_context.py —
визуално предупреждение до "потвърдена от новина" значката, когато цената не
следва потвърдения механизъм. Гейтовете (news_status, laggard/leading) не се
пипат тук — само се четат.

Реален пример: rows/sector за "Финанси при стръмна крива" са КОПИРАНИ буквално
от data/2026-10-01.json. Останалото е синтетично (гранични случаи), маркирано.

Пускане: python test_thesis_price_warning.py
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src.thesis_context import _price_diverges

print("── РЕАЛЕН пример (01.10.2026, 'Финанси при стръмна крива') ──")
REAL_ROWS = [
    {'ticker': 'JPM', 'chg_1m_pct': -7.1, 'above_50': False, 'above_200': True,
     'history_days': 251, 'status': 'позиция'},
    {'ticker': 'BAC', 'chg_1m_pct': -11.7, 'above_50': False, 'above_200': False,
     'history_days': 251, 'status': 'позиция'},
]
REAL_SECTOR = {'etf': 'XLF', 'label': None, 'rs_4w': -6.65, 'rs_12w': -6.14,
              'laggard': False, 'leading': False}
result = _price_diverges(REAL_ROWS, REAL_SECTOR)
assert result is True, f"01.10 Финанси трябва да флагне (RS отрицателен и на 4с, и на 12с), получено {result}"
print(f"  _price_diverges = {result}")
print("  ✓ True — минава през RS крака (-6.65%/-6.14%), не през 200DMA (1/2 JPM/BAC не е мнозинство)")
print()

print("── СИНТЕТИЧНИ гранични случаи (измислени входове) ──")

# 1) 1/2 под 200DMA, RS положителен и на двата хоризонта → нищо не флагва (без мнозинство, без RS)
r = _price_diverges(
    [{"above_200": True}, {"above_200": False}],
    {"rs_4w": 1.0, "rs_12w": 1.0})
assert r is False
print(f"  ✓ 1/2 под 200DMA (не мнозинство) + RS положителен → {r}")

# 2) строго мнозинство под 200DMA (2/3), RS положителен → флагва само през 200DMA крака
r = _price_diverges(
    [{"above_200": False}, {"above_200": False}, {"above_200": True}],
    {"rs_4w": 2.0, "rs_12w": 2.0})
assert r is True
print(f"  ✓ 2/3 под 200DMA (строго мнозинство) + RS положителен → {r} (200DMA крак)")

# 3) RS смесен (4с отрицателен, 12с положителен) — не е "И на двата", не флагва през RS крака
r = _price_diverges([{"above_200": True}], {"rs_4w": -1.0, "rs_12w": 1.0})
assert r is False
print(f"  ✓ above_200=True + RS смесен (4с<0, 12с>0) → {r} (RS трябва ДВАТА отрицателни)")

# 4) всички above_200 = None (без данни) + RS липсва → False, не гърми
r = _price_diverges([{"above_200": None}, {"above_200": None}], {"rs_4w": None, "rs_12w": None})
assert r is False
print(f"  ✓ без данни никъде → {r} (без грешка)")

# 5) празни rows + валиден отрицателен RS сектор → все пак флагва (RS кракът не зависи от rows)
r = _price_diverges([], {"rs_4w": -3.0, "rs_12w": -3.0})
assert r is True
print(f"  ✓ без тикъри в rows, но RS отрицателен на сектора → {r}")

print()
print("Всички тестове минаха.")
