"""
Общи помощници за ценови серии. Без мрежа, без състояние.

last_and_week_ago() е "седмица назад по ДАТА + NaN guard" — същата логика като в thermometer.move_index() (FIX 2026-09-25),
изнесена тук, за да я ползват и VIX (thermometer.vix_level) и global_market_signals (macro_layer) без cross-module coupling.
move_index() не е пипан (additive) и продължава да носи своята вградена копие на логиката.
"""
from __future__ import annotations
import datetime as dt
import math


def last_and_week_ago(close, days: int = 7) -> tuple[float, float, "dt.date"]:
    """
    (last, week_ago, last_date) от pandas Series с Close, индексирана по време.

    FIX 2026-10-03 (пакет 2 т.9): дотук VIX и global_market_signals взимаха `.iloc[-6]` — пет БАРА назад, без NaN проверка.
    Бар, който липсва в историята (празник, дупка при Yahoo), мести прозореца тихо: на 2y реална история (VIX, ^TNX, DXY,
    злато, петрол, мед) котвата по позиция е различна от котвата "7 календарни дни" в 86 от 499 дни — около празниците
    прозорецът става 8–9 календарни дни, а при VIX флагът за скок (>= VIX_SPIKE_WEEKLY_PCT) се обръща в 5 дни от 499.
    NaN в `.iloc[-1]` пък даваше "nan" в числата, подадени на AI, и фалшиво червено при сравненията.

    Котвата е ДАТАТА НА ПОСЛЕДНИЯ БАР (не датата на run-а): между двете наблюдения има винаги точно `days` календарни дни,
    или последният бар на или преди тази дата. NaN в последния бар НЕ се пропуска (иначе "последната" стойност би била
    тихо по-стара) — вдига ValueError, както и липсата на стойност на или преди котвата.
    """
    if close is None or len(close) == 0:
        raise ValueError("празна история")
    last_ts = close.index[-1]
    last = float(close.iloc[-1])
    if math.isnan(last):
        raise ValueError(f"NaN Close — последен ред {last_ts.date()}")
    prior = close.loc[close.index <= last_ts - dt.timedelta(days=days)].dropna()
    if prior.empty:
        raise ValueError(f"няма стойност на или преди {days} дни назад")
    return last, float(prior.iloc[-1]), last_ts.date() if hasattr(last_ts, "date") else last_ts
