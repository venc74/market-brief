"""
Корелационен риск между текущите Action кандидати — чисто информационен флаг.

MAX_PER_SECTOR (config.py) пази от сурова GICS секторна концентрация, но не
хваща тематична/поведенческа корелация: два тикъра от различни GICS сектори
(напр. "AI инфраструктура" енергиен доставчик + полупроводников производител)
могат да се движат почти идентично при риск-off ден, без изобщо да делят
сектор. THESIS_BASKETS label-based overlap би бил евристика — тук вместо
това мерим РЕАЛНА историческа ценова корелация (pairwise Pearson на дневните
% промени), защото два тикъра с еднакъв thesis label могат да имат слаба
реална корелация, или обратното.

ВАЖНО: това НЕ променя кой тикър влиза в Action — само добавя предупредителна
бележка в dashboard-а. Изборът на кандидати остава изцяло на apply_hard_rules()
в main.py; евентуална промяна на тази логика заради корелация е бъдещо,
отделно решение.

Graceful degradation (Секция 7): <2 кандидата → празен списък без мрежова
заявка; провал на fetch/изчислението → празен списък + print диагностика.
Не се кешира за деня — Action листата вече е дневна, а изчислението е леко
(≤5 тикъра, кратка Close серия).
"""
from __future__ import annotations
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


def fetch_correlation_flags(action_candidates: list[dict]) -> list[dict]:
    """
    За текущите Action кандидати (обикновено ≤5) — изчислява pairwise
    корелация на дневните % промени за последните config.CORRELATION_
    LOOKBACK_DAYS търговски дни. Флагва двойки с |corr| >=
    config.CORRELATION_THRESHOLD.

    Връща [{"tickers": [t1, t2], "correlation": round(rho, 2)}, ...]
    Празен списък при <2 кандидата или провал на fetch-а (graceful).
    """
    tickers = [c["ticker"] for c in action_candidates]
    if len(tickers) < 2:
        return []

    try:
        data = yf.download(tickers, period=f"{config.CORRELATION_LOOKBACK_DAYS + 10}d",
                           progress=False, auto_adjust=True)["Close"]
        returns = data.pct_change().dropna(how="all")
        corr = returns.corr()

        flags = []
        for i, t1 in enumerate(tickers):
            if t1 not in corr.columns:
                continue
            for t2 in tickers[i + 1:]:
                if t2 not in corr.columns:
                    continue
                rho = corr.loc[t1, t2]
                if rho == rho and abs(rho) >= config.CORRELATION_THRESHOLD:  # rho==rho: не е NaN
                    flags.append({"tickers": [t1, t2], "correlation": round(float(rho), 2)})
        return flags
    except Exception as e:
        print(f"[correlation] fetch/calc failed: {e}")
        return []


if __name__ == "__main__":
    mock = [{"ticker": "QQQ"}, {"ticker": "XLK"}, {"ticker": "GLD"}]
    for f in fetch_correlation_flags(mock):
        print(f"  {f['tickers'][0]} ↔ {f['tickers'][1]}: {f['correlation']}")
