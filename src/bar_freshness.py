"""
Предпазител за ЗАСТОЯЛ дневен бар (16.10.2026, решение на Венци след измерването от 15.10).

Измерено (РЕАЛНИ брифове 24.07–15.10, 60 брифа; затварянията сверени с Yahoo на 15.10): в 6 брифа (29.07, 04.08, 18.08, 19.08, 04.09, 23.09) барът в 07:30 беше от ПРЕДИШНАТА сесия.
  • скрийнърът и картите — цената на картата е затварянето от D−2 (29.07: 10 от 10 карти, 04.08: 5/5, 18.08: 9/10, 19.08: 4/10 — частично, SPY беше пресен, 04.09: 4/4, 23.09: 3/4), без нито едно
    предупреждение;
  • термометърът — SPY тренд скрит в 5 от 6 дни (собствената му проверка за давност работи), т.е. видимите индикатори намаляват;
  • distribution days — на 19.08, 04.09 и 23.09 броят съвпада с бара от D−1 (отделно теглене); на 29.07 и 04.08 модулът още не е бил включен;
  • книгите — в тези 6 дни няма нито една Action карта и нито един запис; резолюцията изостава с ден и се наваксва на следващия run.
Фон на обикновен ден (15.10): 2 от 519 тикъра със стар последен бар (EA — делистната, WBD).

  • expected_session(today) — последната NYSE сесия преди деня на брифа (брифът е преди отварянето);
  • last_bar_dates(tickers, fetch) — последната дата с Close за всеки тикър (един yf.download, period 10d); fetch(tickers) → DataFrame във формата на yf.download (тестовете го подменят);
  • probe(today, fetch) — SPY + config.BAR_FRESHNESS_PROBE: пресни ли са (SPY задължително, кошницата ≥ BAR_FRESHNESS_MIN_SHARE);
  • wait_for_fresh(today, fetch, sleep, clock) — нов опит на BAR_FRESHNESS_RETRY_SEC до BAR_FRESHNESS_MAX_WAIT_SEC; резултатът е в LAST_DIAG;
  • universe(last_dates, card_tickers, today) — след скрийнъра: колко от универса са със стар бар и кои карти са засегнати (LAST_DIAG["universe"]);
  • message(diag) — текстът за здравната проверка (един банер: "Здравна проверка: дневните данни са от ДД.ММ (Yahoo не е обновил) …") или None.
Graceful: провал на тегленето → не чака безкрайно и не вдига; без резултат → без банер от този модул (провалът на Yahoo има свои банери).
"""
from __future__ import annotations

import collections
import datetime as dt
import time

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src.setup_rules import is_session
from src import sessions as _sessions

LAST_DIAG: dict = {}
_MAX_ERRORS = 3


def _dm(iso: str | None) -> str:
    return f"{iso[8:10]}.{iso[5:7]}" if iso else "?"


def expected_session(today) -> str:
    """Последната NYSE сесия преди деня на брифа (src/sessions.prev_session)."""
    return _sessions.prev_session(today).isoformat()


def _download(tickers):
    import yfinance as yf
    return yf.download(list(tickers), period="10d", progress=False, auto_adjust=config.SCREENER_AUTO_ADJUST, group_by="ticker", threads=True)


def last_bar_dates(tickers, fetch=None) -> dict[str, str | None]:
    """{тикър: последната дата с Close (ISO) или None}. Ред с NaN Close не се брои (23.09: частичен бар с High/Low и без Close)."""
    from src.screener import _frame_for
    tickers = list(dict.fromkeys(tickers))
    data = (fetch or _download)(tickers)
    out: dict[str, str | None] = {}
    for t in tickers:
        try:
            s = _frame_for(data, t, len(tickers))["Close"].dropna()
            out[t] = s.index[-1].date().isoformat() if len(s) else None
        except Exception:
            out[t] = None
    return out


def probe(today, fetch=None) -> dict:
    exp = expected_session(today)
    basket = list(dict.fromkeys(("SPY",) + tuple(config.BAR_FRESHNESS_PROBE)))
    dates = last_bar_dates(basket, fetch)
    fresh = [t for t, d in dates.items() if d and d >= exp]
    spy = dates.get("SPY")
    stale_dates = [d for t, d in dates.items() if d and d < exp]
    ok = bool(spy and spy >= exp) and len(fresh) >= config.BAR_FRESHNESS_MIN_SHARE * len(basket)
    data_from = spy if (spy and spy < exp) else (collections.Counter(stale_dates).most_common(1)[0][0] if stale_dates else None)
    return {"ok": ok, "expected": exp, "spy_last": spy, "basket_n": len(basket), "basket_fresh": len(fresh),
            "stale": sorted(t for t in basket if t not in fresh), "data_from": data_from}


def wait_for_fresh(today, fetch=None, sleep=time.sleep, clock=time.monotonic) -> dict:
    """
    Пресни ли са дневните барове за последната сесия; ако не — нов опит на BAR_FRESHNESS_RETRY_SEC до BAR_FRESHNESS_MAX_WAIT_SEC. Връща (и пише в LAST_DIAG)
    {ok, expected, attempts, waited_sec, spy_last, basket_fresh, basket_n, stale, data_from, error}. Провал на тегленето (изключение, не стар бар) → най-много
    _MAX_ERRORS опита, после ok=None (неизвестно, без банер от този модул — паднал Yahoo има свои банери); иначе run-ът би чакал 25 мин и при изцяло паднал източник.
    """
    LAST_DIAG.clear()
    t0, attempts, errors, last = clock(), 0, 0, None
    while True:
        attempts += 1
        try:
            last = probe(today, fetch)
            last["error"] = None
        except Exception as e:
            errors += 1
            last = {"ok": None, "expected": expected_session(today), "error": f"{type(e).__name__}: {e}"}
        waited = clock() - t0
        if last.get("ok") or errors >= _MAX_ERRORS or waited + config.BAR_FRESHNESS_RETRY_SEC > config.BAR_FRESHNESS_MAX_WAIT_SEC:
            break
        print(f"[bars] дневните барове за {_dm(last['expected'])} още ги няма (SPY: {_dm(last.get('spy_last'))}, кошница {last.get('basket_fresh', '?')}/{last.get('basket_n', '?')}"
              f"{'; ' + last['error'] if last.get('error') else ''}) — нов опит след {config.BAR_FRESHNESS_RETRY_SEC // 60} мин")
        sleep(config.BAR_FRESHNESS_RETRY_SEC)
    LAST_DIAG.update(last, attempts=attempts, waited_sec=int(round(clock() - t0)))
    if LAST_DIAG.get("ok"):
        print(f"[bars] дневните барове са за {_dm(LAST_DIAG['expected'])}" + (f" (след {LAST_DIAG['waited_sec'] // 60} мин изчакване)" if attempts > 1 else ""))
    elif LAST_DIAG.get("ok") is False:
        print(f"[bars] ⚠ дневните данни са от {_dm(LAST_DIAG.get('data_from'))}, очаквана сесия {_dm(LAST_DIAG['expected'])} — брифът тръгва с банер")
    return dict(LAST_DIAG)


def universe(last_dates: dict[str, str | None], card_tickers=(), today=None) -> dict:
    """След скрийнъра: {n, stale, share, by_date, stale_cards} — тикърите от универса с последен бар отпреди очакваната сесия; записва се в LAST_DIAG["universe"]."""
    exp = LAST_DIAG.get("expected") or expected_session(today or dt.date.today())
    have = {t: d for t, d in (last_dates or {}).items() if d}
    stale = {t: d for t, d in have.items() if d < exp}
    cards = [t for t in dict.fromkeys(card_tickers or ()) if t in stale]
    out = {"expected": exp, "n": len(have), "stale": len(stale), "share": round(len(stale) / len(have), 4) if have else 0.0,
           "by_date": dict(collections.Counter(stale.values()).most_common(3)), "stale_cards": cards}
    LAST_DIAG["universe"] = out
    return out


def message(diag: dict | None) -> str | None:
    """Текстът за здравната проверка или None. Първо — общото (SPY/кошницата не са обновени след изчакването); иначе — частично застоял универс над прага или засегнати карти."""
    d = diag or {}
    if not d:
        return None
    u = d.get("universe") or {}
    cards = f" Засегнати карти: {', '.join(u['stale_cards'])}." if u.get("stale_cards") else ""
    if d.get("ok") is False:
        waited = f"; изчакано {d.get('waited_sec', 0) // 60} мин" if d.get("attempts", 1) > 1 else ""
        return (f"дневните данни са от {_dm(d.get('data_from'))} (Yahoo не е обновил сесията {_dm(d.get('expected'))}{waited}) — скрийнърът, картите и термометърът са с данните "
                f"от предишната сесия.{cards}")
    if u.get("n") and (u.get("share", 0) > config.BAR_FRESHNESS_UNIVERSE_WARN_SHARE or u.get("stale_cards")):
        top = next(iter(u.get("by_date") or {}), None)
        return (f"дневните данни за {u['stale']} от {u['n']} тикъра в универса са от {_dm(top)} (Yahoo не е обновил сесията {_dm(u.get('expected'))}) — за тях скрийнърът е "
                f"с данните от предишната сесия.{cards}")
    return None
