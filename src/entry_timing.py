"""
Entry Timing (Секция [нова]) — screening и timing остават СТРИКТНО разделени.
Screening (screener.py + fundamental_screen + AI класификация в
apply_hard_rules) отговаря на "коя акция е добра"; този модул отговаря на
съвсем различен въпрос — "добър ли е точно СЕГА моментът да влезеш".

Концепции 1+2 (pivot + volume confirmation, 2% extension rule, виж
evaluate_pivot_volume/evaluate по-долу) са per-ticker — взимат ГОТОВИЯ Action
списък, добавят "entry_timing" под-обект на всеки кандидат, mirroring как
enrich.py добавя "options"/"earnings"/"short_view". Използват СЪЩЕСТВУВАЩИ
полета от screener.py, нула нови мрежови заявки.

Концепция 3 (distribution days market gate, виж evaluate_distribution_days
по-долу) е пазарно-глобален сигнал, НЕ per-ticker — SPY/QQQ дневен OHLCV,
отделна функция, извиквана отделно от evaluate() в main.py, показвана като
самостоятелен елемент близо до термометъра в dashboard-а, не badge на
Action картата.

И трите концепции НЕ променят classification, plan, или sizing — ако модулът
се счупи изцяло, screening-ът продължава напълно непокътнат (graceful
degradation, Секция 7).

ИЗРИЧНО НЕ в този модул (за по-късна разработка): follow-through day логика,
"3 дни над 21-EMA" филтър, undercut & rally (U&R) сетъп, staggered/pyramid
entry.
"""
from __future__ import annotations
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import net_utils


def evaluate_pivot_volume(candidate: dict) -> dict | None:
    """
    Концепции 1+2 за ЕДИН кандидат. Чете pct_from_pivot/volume_ratio/
    breakout_volume — всичките вече на candidate dict-а от screener.py,
    нищо ново не се смята тук освен verdict/note интерпретацията.

    Zone логика:
      pct < 0                              → все още НЕ е пробил pivot-а
      0 <= pct <= ENTRY_TIMING_EXTENDED_PCT → идеална входна зона
      pct > ENTRY_TIMING_EXTENDED_PCT       → extended (screener.py вече
                                               гарантира pct <= 5.0 — по-широк
                                               праг от него, никога >5%)
    Комбинирано с breakout_volume (bool, вече >= config.BREAKOUT_VOLUME_MULT
    от screener.py) за финалния verdict в {"good", "caution", "wait"}.

    Връща None ако pct_from_pivot липсва (graceful — candidate идва от
    нестандартен път, напр. тест данни без пълно enrich).
    """
    pct = candidate.get("pct_from_pivot")
    if pct is None:
        return None
    vol_confirmed = bool(candidate.get("breakout_volume"))
    vol_ratio = candidate.get("volume_ratio")
    vol_txt = f"{vol_ratio:.1f}x" if isinstance(vol_ratio, (int, float)) else "?"

    if pct < 0:
        verdict = "wait"
        note = f"Все още {abs(pct):.1f}% под pivot — не е пробил още, изчакай реален пробив."
    elif pct <= config.ENTRY_TIMING_EXTENDED_PCT:
        if vol_confirmed:
            verdict = "good"
            note = f"Pivot пробив ({pct:+.1f}%) с обем потвърждение ({vol_txt} среден) — добър timing."
        else:
            verdict = "caution"
            note = f"Близо до pivot ({pct:+.1f}%), но БЕЗ обем потвърждение ({vol_txt} среден) — сигналът е слаб."
    else:
        if vol_confirmed:
            verdict = "caution"
            note = f"Extended {pct:+.1f}% над pivot (обемът е добър, {vol_txt}) — обмисли изчакване на pullback."
        else:
            verdict = "wait"
            note = f"Extended {pct:+.1f}% над pivot И без обем потвърждение ({vol_txt}) — изчакай pullback."

    return {
        "verdict": verdict,
        "extended": pct > config.ENTRY_TIMING_EXTENDED_PCT,
        "volume_confirmed": vol_confirmed,
        "pct_from_pivot": pct,
        "note": note,
    }


def evaluate(action_candidates: list[dict]) -> list[dict]:
    """
    Мутира и връща СЪЩИЯ Action списък, добавяйки "entry_timing" под-обект
    на всеки кандидат — same паттърн като enrich() (обогатява съществуващи
    dict-ове, не създава паралелна структура).

    Graceful (Секция 7): неуспешна оценка на конкретен тикър →
    c["entry_timing"] = None, print диагностика, останалите кандидати и
    целият pipeline продължават непокътнати.
    """
    for c in action_candidates:
        try:
            c["entry_timing"] = evaluate_pivot_volume(c)
        except Exception as e:
            print(f"[entry_timing] {c.get('ticker')}: {e}")
            c["entry_timing"] = None
    return action_candidates


def _count_distribution_days(sym: str, lookback: int) -> int | None:
    """
    Тегли дневен OHLCV за sym (lookback + буфер дни, за да има "предходен ден"
    контекст за първата сесия в прозореца) през net_utils.fetch_with_timeout()
    (Секция timeout guard, точка от 02.08.2026 review-то). IBD/O'Neil
    дефиниция: close надолу с поне config.DISTRIBUTION_DAYS_MIN_DECLINE_PCT
    спрямо предходния close, И обем над предходния обем — виж config.py
    коментара защо магнитуден праг, не просто close<prev.

    Graceful: провал на fetch/недостатъчна история → None (не 0 — 0 би
    означавало "проверено, нула distribution days", различно от "не успяхме
    да проверим").
    """
    hist = net_utils.fetch_with_timeout(
        lambda: yf.Ticker(sym).history(period=f"{lookback + 15}d"))
    if hist is None or hist.empty or len(hist) < lookback + 1:
        return None
    close, volume = hist["Close"], hist["Volume"]
    pct_chg = close.pct_change() * 100
    is_dd = (pct_chg <= -config.DISTRIBUTION_DAYS_MIN_DECLINE_PCT) & (volume > volume.shift(1))
    return int(is_dd.iloc[-lookback:].sum())


def evaluate_distribution_days() -> dict | None:
    """
    Концепция 3: distribution days market gate. Пазарно-глобален сигнал
    (SPY + QQQ), НЕ per-ticker — показва се отделно близо до термометъра в
    dashboard-а, не badge на Action картата (за разлика от концепции 1+2).

    Калибрация (02.08.2026 review, проверено на 3г реална SPY история):
    класическите O'Neil прагове ("3-4 = внимание", "5+ = сериозен риск") НЕ
    пасват — медианата в 25-дневен rolling прозорец вече е 5 (модерните
    пазари имат структурно по-висока базова честота на "down+higher-vol" дни,
    отколкото когато O'Neil е калибрирал правилото десетилетия по-рано) —
    "5+" би флагвало "риск" ~50% от времето, безполезен сигнал. Прагове тук
    (config.DISTRIBUTION_DAYS_YELLOW/RED) са на 70-ти/95-ти персентил от
    реалната история (7/9), не текстовите O'Neil числа. Forward 10-дневен
    SPY return корелация с broя е практически нулева (0.011) — метриката НЕ
    предсказва посока — но std на forward return расте отчетливо с broя
    (1.96→2.37→3.20→5.12 по bucket) — предсказва НЕСИГУРНОСТ/риск, точно
    каквото Entry Timing (кога е добър момент за нов вход) търси.

    Gate статусът използва max(SPY, QQQ) — CANSLIM кандидатите тук са
    growth-нагласени, QQQ distress е поне толкова релевантен, колкото SPY.

    Graceful: провал на fetch за ДВАТА индекса → None (dashboard-ът скрива
    целия елемент). Провал само на единия → продължава с наличния.
    """
    spy_count = _count_distribution_days("SPY", config.DISTRIBUTION_DAYS_LOOKBACK)
    qqq_count = _count_distribution_days("QQQ", config.DISTRIBUTION_DAYS_LOOKBACK)
    if spy_count is None and qqq_count is None:
        return None

    gate_count = max(c for c in (spy_count, qqq_count) if c is not None)
    if gate_count >= config.DISTRIBUTION_DAYS_RED:
        status = "red"
    elif gate_count >= config.DISTRIBUTION_DAYS_YELLOW:
        status = "yellow"
    else:
        status = "green"

    parts = []
    if spy_count is not None:
        parts.append(f"SPY {spy_count}")
    if qqq_count is not None:
        parts.append(f"QQQ {qqq_count}")
    label = (f"{' / '.join(parts)} (последни "
            f"{config.DISTRIBUTION_DAYS_LOOKBACK} сесии)")

    return {"count": gate_count, "spy_count": spy_count, "qqq_count": qqq_count,
            "status": status, "label": label}


if __name__ == "__main__":
    import json
    mock = [
        {"ticker": "GOOD", "pct_from_pivot": 1.2, "volume_ratio": 1.8, "breakout_volume": True},
        {"ticker": "THIN_VOL", "pct_from_pivot": 0.5, "volume_ratio": 0.9, "breakout_volume": False},
        {"ticker": "EXTENDED", "pct_from_pivot": 3.8, "volume_ratio": 1.9, "breakout_volume": True},
        {"ticker": "NOT_YET", "pct_from_pivot": -2.1, "volume_ratio": 1.1, "breakout_volume": False},
    ]
    print(json.dumps(evaluate(mock), indent=2, ensure_ascii=False, default=str))
    print(json.dumps(evaluate_distribution_days(), indent=2, ensure_ascii=False, default=str))
