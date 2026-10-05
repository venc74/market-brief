"""
Position Sizing (Секция 3.7). Таблицата от спека, ред по ред, като код.
Stop = по-високото от (под базата −2%) и (под 50DMA −1%) — т.е. по-близкият
логичен stop, за да не раздуваме риска на акция изкуствено.
"""
from __future__ import annotations

import datetime as dt

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import setup_rules


def position_plan(row: dict, sizing_factor: float = 1.0) -> dict:
    price = row["price"]
    pivot = row["pivot"]
    base_low = row.get("base_low", price * 0.92)
    ma50 = row.get("ma50", price * 0.95)

    entry_low = round(pivot * 0.98, 2)
    entry_high = round(pivot * 1.02, 2)
    entry_mid = round(pivot, 2)

    stop_base = base_low * 0.98
    stop_ma = ma50 * 0.99
    stop = round(max(stop_base, stop_ma), 2)
    if stop >= entry_low:                       # дегенерирал стоп — под базата
        stop = round(stop_base, 2)

    risk_per_share = round(entry_mid - stop, 2)
    if risk_per_share <= 0:
        return {"valid": False, "reason": "Stop над entry — структурата не позволява смислен план."}

    max_risk_usd = round(config.PORTFOLIO_SIZE * config.RISK_PER_TRADE_PCT / 100
                         * sizing_factor, 0)
    shares = int(max_risk_usd // risk_per_share)
    total_invest = round(shares * entry_mid, 0)
    pct_portfolio = round(total_invest / config.PORTFOLIO_SIZE * 100, 1)

    target1 = round(entry_mid + risk_per_share * config.MIN_REWARD_RISK, 2)
    risk_pct_of_price = risk_per_share / entry_mid * 100
    horizon = ("2–4 седмици" if risk_pct_of_price < 6 else
               "4–8 седмици" if risk_pct_of_price < 10 else "8–12 седмици")

    return {
        "valid": True,
        "entry_range": [entry_low, entry_high],
        "entry_mid": entry_mid,
        "stop_loss": stop,
        "stop_basis": "под 50DMA" if stop == round(stop_ma, 2) else "под базата",
        "risk_per_share": risk_per_share,
        "max_risk_usd": max_risk_usd,
        "sizing_factor": sizing_factor,
        "shares": shares,
        "total_investment": total_invest,
        "pct_of_portfolio": pct_portfolio,
        "target_1": target1,
        "target_2": f"trailing stop под 10DMA след достигане на ${target1}",
        "reward_risk": config.MIN_REWARD_RISK,
        "time_horizon": horizon,
    }


def position_plan_v2(row: dict, sizing_factor: float = 1.0, today=None) -> dict:
    """
    Пакет 1, т.3 (2026-10-03): план за ПОТВЪРДЕН пробив (виж setup_rules).

    Вход: buy-stop на pivot — ако инструментът отвори над него, изпълнението е по
    отварянето, но не по-високо от pivot +BUYABLE_ZONE_MAX_PCT% ("таван за вход").
    Референтният вход за стоп/цел/брой акции е сигналният close (`price`), както в
    реплея — реалното изпълнение може да е по-високо в рамките на тавана.
    Стоп = най-ниският Low на последните STOP_STRUCT_LOOKBACK_BARS бара −buffer, но не
    повече от STOP_MAX_PCT% под входа; структурен риск над STOP_REJECT_STRUCT_RISK_PCT%
    → невалиден план ("твърде разтегнато", запасна проверка след setup_rules).
    Цел 1 = 2R (MIN_REWARD_RISK) за TARGET_PARTIAL_FRACTION от позицията; остатъкът —
    trailing под TRAIL_SMA_DAYS-дневната средна, стопът остава активен (виж trade_sim).

    Ключовете от стария position_plan() са запазени (entry_range, entry_mid, stop_loss,
    stop_basis, risk_per_share, max_risk_usd, sizing_factor, shares, total_investment,
    pct_of_portfolio, target_1, target_2, reward_risk, time_horizon); entry_range вече
    е зоната за покупка [buy-stop, таван], entry_mid — планиращият вход.
    """
    price, pivot = row.get("price"), row.get("pivot")
    if (not isinstance(price, (int, float)) or not isinstance(pivot, (int, float))
            or price <= 0 or pivot <= 0):
        return {"valid": False, "reason": "Няма цена/pivot за план."}
    entry_ref = round(float(price), 2)
    st = setup_rules.stop_levels(row.get("struct_low"), entry_ref)
    if st is None:
        return {"valid": False,
                "reason": f"Няма {config.STOP_STRUCT_LOOKBACK_BARS}-баров структурен low — стопът не може да се изчисли."}
    if st["too_wide"]:
        return {"valid": False, "reason": (
            f"Твърде разтегнато: структурният стоп е {st['struct_risk_pct']:.1f}% под входа "
            f"(> {config.STOP_REJECT_STRUCT_RISK_PCT:g}%).")}

    stop = st["stop"]
    risk_per_share = round(entry_ref - stop, 2)
    if risk_per_share <= 0:
        return {"valid": False, "reason": "Стоп над входа — структурата не позволява смислен план."}

    max_risk_usd = round(config.PORTFOLIO_SIZE * config.RISK_PER_TRADE_PCT / 100
                         * sizing_factor, 0)
    shares = int(max_risk_usd // risk_per_share)
    total_invest = round(shares * entry_ref, 0)
    pct_portfolio = round(total_invest / config.PORTFOLIO_SIZE * 100, 1)

    target1 = round(entry_ref + risk_per_share * config.MIN_REWARD_RISK, 2)
    risk_pct = risk_per_share / entry_ref * 100
    horizon = ("2–4 седмици" if risk_pct < 6 else
               "4–8 седмици" if risk_pct < 10 else "8–12 седмици")
    buy_stop = round(pivot, 2)
    chase = setup_rules.max_chase(pivot)
    stop_basis = (f"таван {config.STOP_MAX_PCT:g}% под входа (структурният е {st['struct_risk_pct']:.1f}%)"
                  if st["stop_capped"] else
                  f"структурен: {config.STOP_STRUCT_LOOKBACK_BARS}-барен low −{config.STOP_STRUCT_BUFFER_PCT:g}%")

    return {
        "valid": True,
        "method": "v2",
        "entry_range": [buy_stop, chase],
        "entry_mid": entry_ref,
        "buy_stop": buy_stop,
        "max_chase": chase,
        "valid_through": setup_rules.valid_through(today or dt.date.today()),
        "window_sessions": config.BUY_STOP_WINDOW_SESSIONS,
        "stop_loss": stop,
        "stop_basis": stop_basis,
        "stop_capped": st["stop_capped"],
        "struct_stop": st["struct_stop"],
        "struct_risk_pct": st["struct_risk_pct"],
        "risk_pct": round(risk_pct, 2),
        "risk_per_share": risk_per_share,
        "max_risk_usd": max_risk_usd,
        "sizing_factor": sizing_factor,
        "shares": shares,
        "total_investment": total_invest,
        "pct_of_portfolio": pct_portfolio,
        "target_1": target1,
        "target_1_fraction": config.TARGET_PARTIAL_FRACTION,
        "target_2": (f"остатъкът ({(1 - config.TARGET_PARTIAL_FRACTION) * 100:.0f}%): trailing под "
                     f"{config.TRAIL_SMA_DAYS}DMA след ${target1}; стопът ${stop} остава активен"),
        "reward_risk": config.MIN_REWARD_RISK,
        "time_horizon": horizon,
    }



def buy_stop_preview(row: dict, sizing_factor: float = 1.0, today=None) -> dict:
    """
    Пакет 2 (2026-10-05): план-преглед за Watchlist карта с buy-stop (кандидат под pivot) — стоп, риск %, цел 1 (2R), брой акции и
    сума при ТЕКУЩИЯ sizing на режима, както Action картата. Референтният вход е самото buy-stop ниво (pivot), не текущата цена
    под него — същото, с което setup_rules.classify_setup смята стопа и риска, затова stop/risk_pct съвпадат със setup.
    Няма buy-stop или няма валиден план (твърде разтегнато, без struct_low) → {"valid": False, "reason": ...}. Не променя класификацията.
    """
    setup = row.get("setup") or {}
    bs = setup.get("buy_stop")
    if not isinstance(bs, (int, float)) or bs <= 0:
        return {"valid": False, "reason": "Няма buy-stop ниво."}
    plan = position_plan_v2({**row, "price": bs}, sizing_factor, today)
    return {**plan, "preview": True} if plan.get("valid") else plan
