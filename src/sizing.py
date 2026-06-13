"""
Position Sizing (Секция 3.7). Таблицата от спека, ред по ред, като код.
Stop = по-високото от (под базата −2%) и (под 50DMA −1%) — т.е. по-близкият
логичен stop, за да не раздуваме риска на акция изкуствено.
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


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
