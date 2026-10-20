"""
NYSE сесии и празници — ЕДНО място (етап 3, част Б, 20.10.2026). До 20.10 същата логика беше копирана в ~10 модула (setup_rules, bar_freshness, health_monitor,
qm_ep, corp_actions ×2, earnings_move, cot_track, dataroma, thesis_context, backtest) с различни имена и различни граници; тук е всяка семантика веднъж, с
точните граници. Старите имена остават като тънки обвивки — поведението е същото (реплеят: сесиите за всички дати 2024–2028 и 24 брифа — стар ↔ нов код).

Празниците: config.NYSE_HOLIDAYS (официалният календар на nyse.com); ранните затваряния: config.NYSE_EARLY_CLOSES. Сесия = делничен ден, който не е празник.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_DAY = dt.timedelta(days=1)


def as_date(d) -> dt.date:
    if isinstance(d, dt.datetime):
        return d.date()
    if isinstance(d, dt.date):
        return d
    return dt.date.fromisoformat(str(d)[:10])


def is_session(d) -> bool:
    d = as_date(d)
    return d.weekday() < 5 and d.isoformat() not in config.NYSE_HOLIDAYS


def next_session(d) -> dt.date:
    """Първата сесия СТРОГО след d."""
    d = as_date(d) + _DAY
    while not is_session(d):
        d += _DAY
    return d


def prev_session(d) -> dt.date:
    """Последната сесия СТРОГО преди d (брифът е преди отварянето → последната сесия с бар)."""
    d = as_date(d) - _DAY
    while not is_session(d):
        d -= _DAY
    return d


def roll_forward(d) -> dt.date:
    """d, ако е сесия; иначе следващата (срок, паднал в почивен ден → следващият работен ден)."""
    d = as_date(d)
    return d if is_session(d) else next_session(d)


def roll_back(d) -> dt.date:
    """d, ако е сесия; иначе предишната (последната сесия от седмица, чийто петък е празник)."""
    d = as_date(d)
    return d if is_session(d) else prev_session(d)


def next_weekday(d) -> dt.date:
    """Следващият делничен ден СТРОГО след d — празниците НЕ се прескачат (календарната бележка проверява точно него: "утре / в понеделник е празник")."""
    d = as_date(d) + _DAY
    while d.weekday() >= 5:
        d += _DAY
    return d


def sessions_between(a, b) -> int:
    """Брой сесии СТРОГО между a и b (без двата края)."""
    a, b = as_date(a), as_date(b)
    n, d = 0, a + _DAY
    while d < b:
        n += is_session(d)
        d += _DAY
    return n


def sessions_in(a, b, cap_days: int | None = None) -> int:
    """Брой сесии d с a < d <= b (0, ако b <= a). cap_days — горна граница на обхождането в календарни дни (earnings_move: 400)."""
    a, b = as_date(a), as_date(b)
    n, d = 0, a + _DAY
    while d <= b and (cap_days is None or (d - a).days < cap_days):
        n += is_session(d)
        d += _DAY
    return n


def busday_count(a, b) -> int:
    """Брой сесии в [a, b) (numpy.busday_count с празниците на NYSE); a > b → отрицателен брой за [b, a)."""
    a, b = as_date(a), as_date(b)
    hol = sorted(config.NYSE_HOLIDAYS)
    if a <= b:
        return int(np.busday_count(a, b, holidays=hol))
    return -int(np.busday_count(b, a, holidays=hol))


def add_sessions(d, n: int) -> dt.date:
    """Датата, на която се навършват n сесии след d (без самия d)."""
    d, k = as_date(d), 0
    while k < n:
        d += _DAY
        k += is_session(d)
    return d


def session_window(d, n: int) -> list[dt.date]:
    """Първите n сесии, ВКЛЮЧИТЕЛНО d, ако е сесия (иначе от следващата)."""
    d, out = as_date(d), []
    while len(out) < n:
        if is_session(d):
            out.append(d)
        d += _DAY
    return out


def week_last_session(monday) -> dt.date:
    """Последната сесия от седмицата на `monday` (етикетът на седмичния бар на Yahoo): петъкът, назад през празник."""
    d = as_date(monday)
    return roll_back(d + dt.timedelta(days=max(0, 4 - d.weekday())))


def cut_today(bars):
    """
    20.10.2026 (етап 3, решено 20.10): дневните барове на скрийнъра, QM и термометъра — без днешния (частичен при повторен run в хода на сесията; сутрин в 07:30
    няма такъв бар и нищо не се реже). Макро фючърсите НЕ минават оттук — там живата нощна цена с днешна дата е нарочна.
    """
    return complete_bars(bars, dt.date.today())


def complete_bars(bars, today=None):
    """
    Барове с дата < today — днешният бар е ЧАСТИЧЕН при run в хода на сесията (19.10, 18:55 UTC: SPY с обем 22 млн при 64 млн на 16.10). Брифът е преди
    отварянето, затова сутрин нищо не се реже. Без today или празно → както е. Индексът може да е с часова зона (Yahoo .history()).
    """
    if bars is None or today is None or len(bars) == 0:
        return bars
    import pandas as pd
    idx = pd.DatetimeIndex(bars.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return bars[idx.normalize() < pd.Timestamp(as_date(today))]
