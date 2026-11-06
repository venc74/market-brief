"""
Пакет 1, т.2 (2026-10-03): buy-stop изпълнение в trade_sim.simulate().

РЕАЛНИ барове: tests/fixtures/ohlc_EXEL.csv (Yahoo, свалени на 02.10.2026). Плановите нива са:
  • бриф 29.06 — РЕАЛНИЯТ Action план на EXEL (position_plan_v2);
  • брифове 20.07, 25.09, 01.10 — ХИПОТЕТИЧНИ планове (тогава EXEL беше Watchlist под pivot):
    реалните барове, но нивата са изчислени от същите правила, за да покажат буквално
    not_triggered / вход при докосване / pending.
Всичко останало (граници на pivot/прозореца/тавана, празници, гап) е СИНТЕТИЧНО — маркирано.
Пускане: python test_trade_sim.py
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import trade_sim, sizing

sim = trade_sim.simulate


def mk(rows, start="2026-03-02"):
    """СИНТЕТИЧНИ дневни барове (O, H, L, C) по работни дни от `start`."""
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close"])


PLAN = dict(entry_date="2026-03-02", buy_stop=100.0, max_chase=105.0, stop_loss=92.0,
            target_1=116.0, window_sessions=5)
QUIET = (97.0, 99.5, 96.0, 98.0)        # не стига до pivot 100.00


print("── СИНТЕТИЧНО: изпълнение на buy-stop ──")
# pivot докоснат ТОЧНО (High == 100.00), отваряне под него → вход на 100.00, първата сесия е деня на брифа
r = sim(PLAN, mk([(98, 100.0, 97, 99)]))
assert (r["status"], r["fill_date"], r["fill_price"]) == ("open", "2026-03-02", 100.0), r
# High с цент под pivot → няма вход
r = sim(PLAN, mk([(98, 99.99, 97, 99)] * 5))
assert r["status"] == "not_triggered" and r["resolution_date"] == "2026-03-06" and r["fill_price"] is None, r
# гап над pivot → по отварянето
r = sim(PLAN, mk([(102.0, 103, 101, 102.5)]))
assert (r["status"], r["fill_price"]) == ("open", 102.0), r
# таванът за вход: отваряне точно на $105.00 е допустимо, $105.01 → не се гони
assert sim(PLAN, mk([(105.0, 106, 104, 105.5)]))["status"] == "open"
r = sim(PLAN, mk([(105.01, 107, 105, 106)]))
assert r["status"] == "skipped_extended" and r["resolution_date"] == "2026-03-02" and r["fill_price"] is None, r
print("  ✓ High == pivot → вход на pivot (в деня на брифа); High 99.99 ×5 → not_triggered; гап → по Open;")
print("    $105.00 вход, $105.01 → skipped_extended (извън статистиката)")

# прозорец: 5-тата сесия още важи, 6-тата — не; докато тече → pending
r = sim(PLAN, mk([QUIET] * 4 + [(99, 100.0, 98, 99)]))
assert (r["status"], r["fill_date"]) == ("open", "2026-03-06"), r
r = sim(PLAN, mk([QUIET] * 5 + [(99, 101, 98, 100)]))
assert r["status"] == "not_triggered" and r["resolution_date"] == "2026-03-06", r
r = sim(PLAN, mk([QUIET] * 4))
assert r["status"] == "pending" and r["resolution_date"] is None, r
assert sim(PLAN, mk([]))["status"] == "pending"
print("  ✓ вход на 5-тата сесия ✓, на 6-тата → not_triggered; с 4 бара (прозорецът тече) → pending; без бара → pending")

# бриф в събота → първата сесия е понеделник; барове ПРЕДИ entry_date не пълнят
wk = dict(PLAN, entry_date="2026-03-07")                               # събота
bars = mk([(98, 101, 97, 100)] + [(98, 100.0, 97, 99)] * 3, start="2026-03-05")   # Чт, Пт, Пн, Вт
r = sim(wk, bars)
assert (r["status"], r["fill_date"]) == ("open", "2026-03-09"), r      # чт/пт (High 101) са преди брифа
r = sim(dict(PLAN, entry_date="2026-03-03"), mk([(98, 101, 97, 100)] + [QUIET] * 6))   # понеделникът е преди брифа
assert r["status"] == "not_triggered", r
print("  ✓ събота → първата сесия е понеделник; барове преди деня на брифа не пълнят")

# празник: прозорецът е по БАРОВЕ (сесии), не по календарни дни — липсващ работен ден не е сесия
idx = pd.DatetimeIndex(["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-22", "2026-06-23"])   # 19.06 празник
b = pd.DataFrame([QUIET] * 4 + [(99, 100.0, 98, 99), (99, 101, 98, 100)], index=idx, columns=["Open", "High", "Low", "Close"])
r = sim(dict(PLAN, entry_date="2026-06-13"), b)
assert (r["status"], r["fill_date"]) == ("open", "2026-06-22"), r        # 5-тата сесия е 22.06
print("  ✓ прозорецът брои сесии (13.06 → 15,16,17,18,22.06; 19.06 е празник)")

# невалиден риск: стопът над входа
assert sim(dict(PLAN, stop_loss=101.0), mk([(98, 100.0, 97, 99)]))["status"] == "invalid_risk"
print("  ✓ стоп ≥ цената на входа → invalid_risk")
print()

print("── СИНТЕТИЧНО: изход след входа (т.4 частична продажба · т.5 гап през стопа и изтичане) ──")
# стоп на входния ден (гап вход + Low под стопа) → -1R на стоп-цената
r = sim(PLAN, mk([(100.5, 101, 91.0, 95)]))
assert (r["status"], r["exit_price"], r["realized_r"]) == ("stopped", 92.0, -1.0), r
# стоп по-късно
r = sim(PLAN, mk([(99, 101, 98, 100), (99, 100, 91.5, 95)]))
assert (r["status"], r["exit_date"], r["realized_r"]) == ("stopped", "2026-03-03", -1.0), r
print("  ✓ стоп на входния ден и по-късно = -1.00R (цялата позиция)")

# т.5: гап през стопа → изход по отварянето (загуба над 1R); отваряне ТОЧНО на стопа и вътре в бара → по стопа
r = sim(PLAN, mk([(99, 101, 98, 100), (90.0, 91, 89, 90.5)]))
assert (r["status"], r["exit_price"], r["realized_r"]) == ("stopped", 90.0, -1.25), r          # (90-100)/8
r = sim(PLAN, mk([(99, 101, 98, 100), (92.0, 93, 90, 91)]))
assert (r["exit_price"], r["realized_r"]) == (92.0, -1.0), r
r = sim(PLAN, mk([(99, 101, 98, 100), (92.01, 93, 91, 92)]))
assert (r["exit_price"], r["realized_r"]) == (92.0, -1.0), r
# гап през стопа СЛЕД частична продажба: 0.5×(+2.0) + 0.5×(88-100)/8
r = sim(PLAN, mk([(99, 101, 98, 100), (100, 117, 99, 115), (88.0, 89, 87, 88.5)]))
assert (r["exit_price"], r["realized_r"]) == (88.0, round(0.5 * 2.0 + 0.5 * (88 - 100) / 8, 2)) and r["realized_r"] == 0.25, r
# на ВХОДНИЯ ден редът на събитията е неизвестен → винаги по стоп-цената, не по отварянето
r = sim(PLAN, mk([(100.5, 101, 85.0, 95)]))
assert (r["exit_price"], r["realized_r"]) == (92.0, -1.0), r
print("  ✓ гап под стопа на по-късен бар → по Open $90 = -1.25R (над 1R); Open точно $92.00 и вътре в бара → по стопа;")
print("    след частична продажба: +0.25R; на входния ден → по стоп-цената")

# цел → 50% се продава на $116 (2R), остатъкът → trailing → излиза при Close под 10DMA
rows = [(99, 101, 98, 100)]                                            # вход 100.0 (риск 8)
rows += [(100 + i, 106 + i, 100 + i, 101 + i) for i in range(1, 12)]   # покачване; High стига $116 (t1) на 10-тия бар
rows += [(112, 113, 111, 112), (111, 112, 110, 111), (108, 109, 100, 101)]      # Close 101 под 10DMA
r = sim(PLAN, mk(rows))
assert r["status"] == "trailing_stop_exit" and r["target1_hit_date"] == "2026-03-16", r
assert (r["partial_price"], r["partial_fraction"], r["exit_price"]) == (116.0, 0.5, 101.0), r
assert r["R"] == 0.5 * 2.0 + 0.5 * (101.0 - 100.0) / 8.0 and r["realized_r"] == 1.06, r     # 1.0 + 0.0625 = 1.0625
print("  ✓ 50% на $116 (+2.00R) + остатък на $101 (+0.125R) = +1.0625R → 1.06; стопът не е изключен")

# цел на входния ден → частичната е точно на целта; гап над целта на по-късен бар → по отварянето
r = sim(PLAN, mk([(99, 117, 98, 116)]))
assert (r["status"], r["partial_price"], r["target1_hit_date"]) == ("trailing", 116.0, "2026-03-02"), r
r = sim(PLAN, mk([(99, 101, 98, 100), (120.0, 121, 119, 120)]))
assert r["partial_price"] == 120.0 and r["current_r"] == round(0.5 * (120 - 100) / 8 + 0.5 * (120 - 100) / 8, 2) == 2.5, r
print("  ✓ цел на входния ден → продава на $116; гап над целта ($120) на по-късен бар → по отварянето ($120, +2.50R)")

# стоп СЛЕД частичната: остатъкът излиза на стопа → +0.5R (печалба по R, макар и "stopped")
r = sim(PLAN, mk([(99, 101, 98, 100), (100, 117, 99, 115), (99, 100, 91.0, 95)]))
assert r["status"] == "stopped" and r["partial_price"] == 116.0 and r["exit_price"] == 92.0, r
assert r["R"] == 0.5 * 2.0 + 0.5 * -1.0 == 0.5 and r["realized_r"] == 0.5, r
# в един бар стопът е ПЪРВИ: Low под стопа и High над целта → -1R, без частична
r = sim(PLAN, mk([(99, 101, 98, 100), (100, 117, 91.0, 110)]))
assert r["status"] == "stopped" and r["partial_price"] is None and r["realized_r"] == -1.0, r
print("  ✓ стоп след частичната: 0.5×(+2.0) + 0.5×(-1.0) = +0.50R; Low под стопа и High над целта в един бар → стопът е първи (-1.00R)")

# живи: open / trailing с текущ R (включва частичната)
r = sim(PLAN, mk([(99, 101, 98, 100), (100, 104, 99, 104)]))
assert (r["status"], r["current_r"], r["realized_r"]) == ("open", 0.5, None), r        # (104-100)/8
r = sim(PLAN, mk([(99, 101, 98, 100), (110, 117, 109, 111)]))
assert r["status"] == "trailing" and r["target1_hit_date"] == "2026-03-03" and r["realized_r"] is None, r
assert r["current_r"] == round(0.5 * 2.0 + 0.5 * (111 - 100) / 8, 2) == 1.69, r        # 1.0 + 0.6875
print("  ✓ живи: 'open' (+0.50R) и 'trailing' след частична продажба (+1.69R = 1.00 + 0.69) — без realized_r")

# TARGET_PARTIAL_FRACTION е параметър: 0 → цялата позиция е в trailing
orig_frac = config.TARGET_PARTIAL_FRACTION
config.TARGET_PARTIAL_FRACTION = 0.0
r = sim(PLAN, mk(rows))
config.TARGET_PARTIAL_FRACTION = orig_frac
assert r["status"] == "trailing_stop_exit" and r["realized_r"] == round((101.0 - 100.0) / 8.0, 2) == 0.12, r
print("  ✓ TARGET_PARTIAL_FRACTION = 0 → цялата позиция се пази до trailing изхода (+0.12R)")

# изтичане (т.5): mark-to-market и във фаза 1; фаза 2 → претеглен R; календарен срок
weeks = config.BACKTEST_MAX_HOLD_WEEKS
long_open = mk([(99, 101, 98, 100)] + [(100, 104, 98, 102)] * (weeks * 5 + 8))
r = sim(PLAN, long_open)
assert r["status"] == "expired" and r["resolution_date"] == "2026-06-22", r            # 02.03 + 16 седмици
assert (r["exit_date"], r["exit_price"], r["realized_r"]) == ("2026-06-22", 102.0, 0.25), r   # т.5: mark-to-market (102-100)/8
r = sim(PLAN, mk([(99, 101, 98, 100)] + [(97, 98, 94, 96)] * (weeks * 5 + 8)))
assert r["status"] == "expired" and r["realized_r"] == -0.5, r                          # под водата: (96-100)/8
rows = [(99, 101, 98, 100)] + [(100 + i * 0.5, 117 + i * 0.5, 99, 101 + i * 0.5) for i in range(weeks * 5 + 8)]
r = sim(PLAN, mk(rows))
assert r["status"] == "expired_in_trail" and r["resolution_date"] == "2026-06-22" and r["partial_price"] == 116.0, r
assert r["realized_r"] == round(0.5 * 2.0 + 0.5 * (r["exit_price"] - 100.0) / 8.0, 2), r
r = sim(PLAN, mk([(99, 101, 98, 100)] + [(100, 104, 98, 101)] * 10), today="2026-06-23")   # данните свършват рано, срокът е минал
assert r["status"] == "expired" and r["exit_date"] == "2026-03-16" and r["realized_r"] == 0.12, r     # по последния наличен Close
r = sim(PLAN, mk([(99, 101, 98, 100)] + [(100, 104, 98, 101)] * 10), today="2026-06-22")   # на самия срок още не е изтекла
assert r["status"] == "open", r
print("  ✓ изтичане 16 седмици след входа → mark-to-market по последния Close: expired +0.25R / -0.50R (преди: без R),")
print("    expired_in_trail с претеглен R; срокът важи и по календар")
print()

print("── СИНТЕТИЧНО: R и доходността се мерят от РЕАЛНАТА цена на изпълнение, не от сигналния close ──")
# Планът е изчислен от сигнален close $101 (стоп $92 → риск $9, цел 2R = $119), но simulate() получава само
# нивата — сигналният close не е негов вход. Реалният вход е max(Open, pivot).
PLAN_SC = dict(entry_date="2026-03-02", buy_stop=100.0, max_chase=105.0, stop_loss=92.0, target_1=119.0, window_sessions=5)
# а) гап над pivot: вход по Open $103 (не $100 и не $101); следващият ден гапва под стопа и излиза по Open $90
r = sim(PLAN_SC, mk([(103.0, 104, 102, 103.5), (90.0, 91, 89, 90.5)]))
assert (r["fill_price"], r["risk_per_share"], r["exit_price"]) == (103.0, 11.0, 90.0), r
assert r["realized_r"] == round((90.0 - 103.0) / 11.0, 2) == -1.18, r                      # от сигналния close щеше да е -1.22, от pivot -1.25
assert r["return_pct"] == round((90.0 - 103.0) / 103.0 * 100, 2) == -12.62, r
# б) докосване: Open $98 под pivot, High го стига → вход точно на pivot $100 (не на Open $98, не на close $101)
r = sim(PLAN_SC, mk([(98.0, 100.0, 97, 99), (99, 109, 98, 108)]))
assert (r["fill_price"], r["status"]) == (100.0, "open") and r["current_r"] == round((108.0 - 100.0) / 8.0, 2) == 1.0, r   # от close $101 → 0.78
# в) целта е ЦЕНОВО ниво от плана ($119); частичната продажба на нея е R от реалния вход: (119-103)/11 = +1.45, не +2.00
r = sim(PLAN_SC, mk([(103.0, 104, 102, 103.5), (104, 120, 103, 119), (100, 101, 91, 95)]))
assert (r["fill_price"], r["partial_price"], r["status"], r["exit_price"]) == (103.0, 119.0, "stopped", 92.0), r
assert r["realized_r"] == round(0.5 * (119.0 - 103.0) / 11.0 + 0.5 * (92.0 - 103.0) / 11.0, 2) == 0.23, r
print("  ✓ гап вход $103: риск $11 (не $9 от плана), гап изход $90 → -1.18R / -12.62% (от close $101 би било -1.22R);")
print("    вход при докосване $100 → +1.00R при Close $108 (от close $101 — +0.78R); цел $119 от плана = +1.45R от реалния вход")
print()

print("── РЕАЛНИ барове на EXEL (tests/fixtures) ──")
exel = pd.read_csv(ROOT / "tests/fixtures/ohlc_EXEL.csv", index_col=0, parse_dates=True)
TODAY = "2026-10-02"

# 29.06: РЕАЛНИЯТ Action план — гап над pivot, стоп на 12.08
plan = sizing.position_plan_v2({"price": 54.77, "pivot": 53.93, "struct_low": 50.80}, 1.0, "2026-06-29")
rec = dict(entry_date="2026-06-29", buy_stop=plan["buy_stop"], max_chase=plan["max_chase"],
           stop_loss=plan["stop_loss"], target_1=plan["target_1"])
assert exel.loc["2026-06-29", "Open"] == 55.00 and 53.93 < 55.00 <= plan["max_chase"]      # отваря над pivot, под тавана
r = sim(rec, exel, TODAY)
assert (r["status"], r["fill_date"], r["fill_price"]) == ("stopped", "2026-06-29", 55.0), r
assert (r["exit_date"], r["exit_price"], r["realized_r"]) == ("2026-08-12", 50.39, -1.0), r
assert exel.loc["2026-08-12", "Open"] > 50.39 >= exel.loc["2026-08-12", "Low"]              # без гап — стопът е ударен вътре в деня
# реалният риск е от входа $55.00 (Open), не от сигналния close $54.77 на картата: $4.61 срещу $4.38 в плана
assert plan["risk_per_share"] == 4.38 and r["risk_per_share"] == 4.61 and r["return_pct"] == -8.38   # от close $54.77 би било -7.99%
print("  ✓ бриф 29.06 (реален Action): вход по отварянето $55.00 (гап над pivot $53.93), стоп $50.39 на 12.08 → -1.00R")

# 20.07: хипотетичен buy-stop $57.57, а EXEL не го стига 5 сесии (20–24.07)
rec = dict(entry_date="2026-07-20", buy_stop=57.57, max_chase=60.45, stop_loss=52.96, target_1=66.79)
assert exel.loc["2026-07-20":"2026-07-24", "High"].max() < 57.57
r = sim(rec, exel, TODAY)
assert r["status"] == "not_triggered" and r["resolution_date"] == "2026-07-24" and r["realized_r"] is None, r
print("  ✓ бриф 20.07 (хипотетичен buy-stop $57.57): най-високият High 20–24.07 е под него → not_triggered (до 24.07)")

# 25.09: докосване — отваря под pivot $59.72, High го стига на 30.09 → вход точно на pivot
rec = dict(entry_date="2026-09-25", buy_stop=59.72, max_chase=62.71, stop_loss=54.94, target_1=69.28)
assert exel.loc["2026-09-30", "Open"] < 59.72 <= exel.loc["2026-09-30", "High"]
assert exel.loc["2026-09-25":"2026-09-29", "High"].max() < 59.72
r = sim(rec, exel, TODAY)
assert (r["status"], r["fill_date"], r["fill_price"]) == ("open", "2026-09-30", 59.72), r
print("  ✓ бриф 25.09 (хипотетичен buy-stop $59.72): без вход 25–29.09, на 30.09 High го докосва → вход $59.72, жива")

# 01.10: прозорецът (01.10 … 07.10) още тече при данни до 02.10 → pending
rec = dict(entry_date="2026-10-01", buy_stop=59.72, max_chase=62.71, stop_loss=54.94, target_1=69.28)
r = sim(rec, exel, TODAY)
assert r["status"] == "pending", r
print("  ✓ бриф 01.10 (хипотетичен): има 2 от 5 сесии (01–02.10), High под $59.72 → pending")

print()
print("Всички тестове минаха.")
