"""
Entry Timing (Секция [нова], начало на итерация 1) — screening и timing
остават СТРИКТНО разделени. Screening (screener.py + fundamental_screen +
AI класификация в apply_hard_rules) отговаря на "коя акция е добра"; този
модул отговаря на съвсем различен въпрос — "добър ли е точно СЕГА моментът
да влезеш" в акция, която screening-ът вече е одобрил.

Взима ГОТОВИЯ Action списък (след apply_hard_rules) като вход, добавя
"entry_timing" под-обект на всеки кандидат — чисто информационен badge,
mirroring как enrich.py вече добавя "options"/"earnings"/"short_view"
под-обекти. НЕ променя classification, plan, или sizing — ако този модул
се счупи изцяло, screening-ът продължава напълно непокътнат (graceful
degradation, Секция 7).

Итерация 1 покрива концепции 1+2 (pivot + volume confirmation, 2% extension
rule) — и двете използват СЪЩЕСТВУВАЩИ полета, вече изчислени от
screener.py (pct_from_pivot, volume_ratio, breakout_volume) за всеки
Action кандидат. Нула нови мрежови заявки в тази итерация.

Концепция 3 (distribution days market gate) е ОТДЕЛНА, по-късна задача —
изисква нови данни (SPY/QQQ дневен OHLCV) и е пазарно-глобален сигнал, не
per-ticker; остава извън обхвата на тази итерация нарочно.

ИЗРИЧНО НЕ в тази итерация (за по-късна разработка): follow-through day
логика, "3 дни над 21-EMA" филтър, undercut & rally (U&R) сетъп,
staggered/pyramid entry.
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


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


if __name__ == "__main__":
    import json
    mock = [
        {"ticker": "GOOD", "pct_from_pivot": 1.2, "volume_ratio": 1.8, "breakout_volume": True},
        {"ticker": "THIN_VOL", "pct_from_pivot": 0.5, "volume_ratio": 0.9, "breakout_volume": False},
        {"ticker": "EXTENDED", "pct_from_pivot": 3.8, "volume_ratio": 1.9, "breakout_volume": True},
        {"ticker": "NOT_YET", "pct_from_pivot": -2.1, "volume_ratio": 1.1, "breakout_volume": False},
    ]
    print(json.dumps(evaluate(mock), indent=2, ensure_ascii=False))
