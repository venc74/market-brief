"""
Пакет 1 — исторически реплей върху РЕАЛНИ барове (регресионен тест на целия продукционен път):
за всеки сигнален бар на AMD, TWLO, LNTH и EXEL (tests/fixtures, Yahoo, свалени на 02.10.2026)
се пуска screener._evaluate_technicals → setup_rules.classify_setup → sizing.position_plan_v2 →
trade_sim.simulate — със и без т.9 (trend template). Числата са замразени от реален ход на кода;
ако логиката се промени, този тест гърми и показва кое се е променило.

Какво НЕ е: статистика. Четири тикъра са твърде малка извадка за изводи — големият реплей
(904 тикъра, 02.01.2024 → 01.10.2026) е в коментарите на config.py и в commit-ите; там е и проверката,
че trade_sim съвпада със симулатора на реплея на всичките 497 сигнала.
Пускане: python test_replay_regression.py
"""
import sys, pathlib, collections
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import screener, setup_rules, sizing, trade_sim

F = lambda s: pd.read_csv(ROOT / "tests/fixtures" / f"ohlc_{s}.csv", index_col=0, parse_dates=True)
SPY = F("SPY")["Close"]
LAST = "2026-10-02"                      # последният бар във фикстурите


def brief_date(signal_bar):
    b = signal_bar + pd.Timedelta(days=1)          # брифът е сутринта след сигналния бар (уикенд → понеделник)
    while b.weekday() >= 5:
        b += pd.Timedelta(days=1)
    return b


def replay(template: bool):
    config.TREND_TEMPLATE_ENABLED = template
    try:
        out = {"bars": 0, "survivors": 0, "kinds": collections.Counter(), "by_ticker": collections.defaultdict(collections.Counter),
               "confirmed": [], "buy_stop": collections.Counter()}
        for sym in ("AMD", "TWLO", "LNTH", "EXEL"):
            df = F(sym)
            for i in range(260, len(df)):
                sub = df.iloc[:i + 1]
                out["bars"] += 1
                row = screener._evaluate_technicals(sym, sub, SPY.loc[:sub.index[-1]])
                if row is None:
                    continue
                out["survivors"] += 1
                b = brief_date(sub.index[-1])
                s = setup_rules.classify_setup(row, b.date())
                out["kinds"][s["kind"]] += 1
                out["by_ticker"][sym][s["kind"]] += 1
                if s["kind"] == "confirmed":
                    plan = sizing.position_plan_v2(row, 1.0, b.date())
                    assert plan["valid"], plan
                    rec = dict(entry_date=b.date().isoformat(), buy_stop=plan["buy_stop"], max_chase=plan["max_chase"],
                               stop_loss=plan["stop_loss"], target_1=plan["target_1"])
                    r = trade_sim.simulate(rec, df, LAST)
                    out["confirmed"].append((sym, sub.index[-1].date().isoformat(), r["status"], r["fill_date"], r["fill_price"],
                                             r["exit_date"], r["realized_r"], r["return_pct"]))
                elif s["kind"] == "below_pivot":                               # ХИПОТЕТИЧЕН buy-stop план (Watchlist)
                    st = setup_rules.stop_levels(row["struct_low"], row["pivot"])
                    risk = row["pivot"] - st["stop"]
                    rec = dict(entry_date=b.date().isoformat(), buy_stop=row["pivot"], max_chase=setup_rules.max_chase(row["pivot"]),
                               stop_loss=st["stop"], target_1=round(row["pivot"] + 2 * risk, 2))
                    out["buy_stop"][trade_sim.simulate(rec, df, LAST)["status"]] += 1
        return out
    finally:
        config.TREND_TEMPLATE_ENABLED = True


on, off = replay(True), replay(False)

print("── РЕАЛЕН реплей: AMD, TWLO, LNTH, EXEL — всеки сигнален бар от 04.2026 нататък (≥260 бара история) ──")
for name, o in (("С т.9 (trend template)", on), ("БЕЗ т.9 (само Stage 2)", off)):
    print(f"  {name}: {o['bars']} сигнални бара → {o['survivors']} технически оцелели; по тип: {dict(o['kinds'])}")
assert on["bars"] == off["bars"] == 476
assert on["survivors"] == 77 and dict(on["kinds"]) == {"too_wide": 51, "below_pivot": 19, "no_volume": 6, "confirmed": 1}
assert off["survivors"] == 81 and dict(off["kinds"]) == {"too_wide": 55, "below_pivot": 19, "no_volume": 6, "confirmed": 1}
assert {k: dict(v) for k, v in on["by_ticker"].items()} == {
    "AMD": {"too_wide": 8}, "TWLO": {"too_wide": 9}, "LNTH": {"too_wide": 16, "below_pivot": 1, "no_volume": 2},
    "EXEL": {"below_pivot": 18, "confirmed": 1, "no_volume": 4, "too_wide": 18}}
assert off["by_ticker"]["AMD"]["too_wide"] - on["by_ticker"]["AMD"]["too_wide"] == 4          # 16, 17, 20, 21.04.2026 (50DMA под 150DMA)
print("  ✓ т.9 маха 4 дни (AMD, 16–21.04.2026), всичките иначе твърде разтегнати → на Action не променя нищо")
print(f"  ✓ от {on['survivors']} технически валидни дни само 1 е допустим за Action (потвърден пробив с обем и стоп ≤10%); "
      f"{on['kinds']['too_wide']} ({on['kinds']['too_wide'] / on['survivors'] * 100:.0f}%) са твърде разтегнати")

conf = on["confirmed"]
assert conf == off["confirmed"] and len(conf) == 1
sym, sig, status, fill_d, fill_p, exit_d, r_, ret = conf[0]
assert (sym, sig, status, fill_d, fill_p, exit_d, r_, ret) == ("EXEL", "2026-06-26", "stopped", "2026-06-29", 55.0, "2026-08-12", -1.0, -8.38)
print("  ✓ единственият Action: EXEL (сигнал 26.06, бриф 29.06) → вход $55.00 по отварянето, стоп на 12.08 → -1.00R / -8.38%")

assert dict(on["buy_stop"]) == dict(off["buy_stop"]) == {"not_triggered": 10, "open": 5, "pending": 3, "stopped": 1}
print("  ✓ 19 buy-stop кандидата под pivot (ХИПОТЕТИЧНИ планове): 10 не се задействат в 5 сесии, 5 са отворени, 3 чакат, 1 е стопнат")

print()
print("Всички тестове минаха.")
