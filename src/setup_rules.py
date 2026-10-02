"""
Техническа класификация на сетъп — чист код, без AI и без мрежа (пакет 1, т.1).

Въпросът тук е "пробил ли е, и може ли да се купи", не "добра ли е акцията":
  • pivot  = най-високият High на базата БЕЗ последните N бара (screener.compute_pivot);
  • confirmed  — close СТРОГО над pivot, не повече от +BUYABLE_ZONE_MAX_PCT над него,
                 и обем >= BREAKOUT_VOLUME_MULT × среден 50д → единственото, което
                 може да стане Action;
  • no_volume  — над pivot (в buyable zone), но без обем → Watchlist, чака потвърждение;
  • below_pivot — под pivot (или точно на него) → Watchlist с buy-stop ниво = pivot;
  • extended   — над pivot × (1 + BUYABLE_ZONE_MAX_PCT%) → не се гони, чака pullback.

Решението е на кода: main.apply_hard_rules() връща във Watchlist всяко Action,
което не е `eligible`, независимо от AI класификацията (кодът има последната дума).

Ценови сравнения са на цента (цени и pivot са закръглени до 2 знака, tick = $0.01):
close == pivot НЕ е пробив; close == pivot×1.05 (закръглено) още е в buyable zone.
"""
from __future__ import annotations
import datetime as dt

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


# ──────────────────────────────────────────────────────────────────────────
# Търговски сесии (за "валиден до")
# ──────────────────────────────────────────────────────────────────────────
def _as_date(d) -> dt.date:
    if isinstance(d, dt.datetime):
        return d.date()
    if isinstance(d, dt.date):
        return d
    return dt.date.fromisoformat(str(d)[:10])


def is_session(d) -> bool:
    d = _as_date(d)
    return d.weekday() < 5 and d.isoformat() not in config.NYSE_HOLIDAYS


def session_window(brief_date, sessions: int | None = None) -> list[dt.date]:
    """
    Първите `sessions` търговски сесии, ВКЛЮЧИТЕЛНО сесията на брифа (брифът е
    в 05:30 UTC, преди US отваряне — сесията на деня на брифа е първата, в която
    може да се търгува). Събота/неделя/празник → следващата търговска сесия.
    """
    n = sessions if sessions is not None else config.BUY_STOP_WINDOW_SESSIONS
    d = _as_date(brief_date)
    out: list[dt.date] = []
    while len(out) < n:
        if is_session(d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def valid_through(brief_date, sessions: int | None = None) -> str:
    return session_window(brief_date, sessions)[-1].isoformat()


def max_chase(pivot: float) -> float:
    """Най-високата цена, при която входът още е в buyable zone (pivot +5%)."""
    return round(pivot * (1 + config.BUYABLE_ZONE_MAX_PCT / 100), 2)


# ──────────────────────────────────────────────────────────────────────────
# Класификация
# ──────────────────────────────────────────────────────────────────────────
def _volume_ok(c: dict) -> bool:
    if "breakout_volume" in c:
        return bool(c["breakout_volume"])
    vr = c.get("volume_ratio")
    return isinstance(vr, (int, float)) and vr >= config.BREAKOUT_VOLUME_MULT


def classify_setup(c: dict, today=None) -> dict:
    """
    Връща {kind, eligible, gate, pct_from_pivot, volume_ok, buy_stop, max_chase,
           valid_through, trigger_text}. Без price/pivot → kind "no_data" (не е Action).
    """
    today = today or dt.date.today()
    price, pivot = c.get("price"), c.get("pivot")
    vr = c.get("volume_ratio")
    out = {"kind": "no_data", "eligible": False, "gate": "no_data",
           "pct_from_pivot": c.get("pct_from_pivot"), "volume_ok": _volume_ok(c),
           "buy_stop": None, "max_chase": None, "valid_through": None,
           "trigger_text": "Няма данни за цена/pivot — не може да се прецени пробив."}
    if not isinstance(price, (int, float)) or not isinstance(pivot, (int, float)) or pivot <= 0:
        return out

    pct = (price / pivot - 1) * 100
    chase = max_chase(pivot)
    through = valid_through(today)
    mult = config.BREAKOUT_VOLUME_MULT
    vol_txt = f"{vr:.2f}×" if isinstance(vr, (int, float)) else "?"
    out.update({"pct_from_pivot": round(pct, 2), "max_chase": chase, "valid_through": through})

    if price > chase:
        out.update(kind="extended", gate="extended", trigger_text=(
            f"Extended: {pct:+.1f}% над pivot ${pivot:.2f} (над +{config.BUYABLE_ZONE_MAX_PCT:g}%, "
            f"таван за вход ${chase:.2f}) — не се гони; чака pullback към pivot."))
    elif price > pivot:
        if out["volume_ok"]:
            out.update(kind="confirmed", eligible=True, gate=None, trigger_text=(
                f"Потвърден пробив: close ${price:.2f} над pivot ${pivot:.2f} ({pct:+.1f}%), "
                f"обем {vol_txt} ≥ {mult:g}× — купува се до ${chase:.2f}."))
        else:
            out.update(kind="no_volume", gate="no_volume", trigger_text=(
                f"Над pivot ${pivot:.2f} ({pct:+.1f}%), но обемът е {vol_txt} (< {mult:g}×) — "
                f"чака пробив с обем (затваряне над ${pivot:.2f} с ≥ {mult:g}× среден обем)."))
    else:
        out.update(kind="below_pivot", gate="below_pivot", buy_stop=round(pivot, 2), trigger_text=(
            f"Чака пробив: buy-stop ${pivot:.2f} (валиден {config.BUY_STOP_WINDOW_SESSIONS} сесии, "
            f"до {through}); сега {abs(pct):.1f}% под pivot. Купува се само ако High ≥ ${pivot:.2f}, "
            f"до ${chase:.2f}; обем ≥ {mult:g}× среден за потвърждение."))
    return out


def annotate(candidates: list[dict], today=None) -> list[dict]:
    """Слага c["setup"] на всеки кандидат (преди AI синтеза, за да го вижда и промптът)."""
    for c in candidates:
        try:
            c["setup"] = classify_setup(c, today)
        except Exception as e:                       # graceful: един счупен кандидат не чупи run-а
            print(f"[setup] {c.get('ticker')}: {type(e).__name__}: {e}")
            c["setup"] = {"kind": "no_data", "eligible": False, "gate": "no_data",
                          "trigger_text": "Класификацията на сетъпа не успя."}
    return candidates


# ──────────────────────────────────────────────────────────────────────────
# Подредба
# ──────────────────────────────────────────────────────────────────────────
_SCREEN_GROUP = {"confirmed": 0, "no_volume": 1, "below_pivot": 2, "extended": 3, "no_data": 4}


def screen_priority(row: dict) -> tuple:
    """
    Ред в run_screen(): потвърдените пробиви първи, после над pivot без обем,
    после под pivot (най-близките първо), накрая extended — fundamental_screen()
    гледа само първите 60, а капацитетът не бива да отива за недостижими сетъпи.
    """
    kind = classify_setup(row)["kind"]
    return (_SCREEN_GROUP[kind], abs(row.get("pct_from_pivot") or 0.0))


# Watchlist картите са най-много 10: потвърден пробив, спрян от лимит/режим/earnings,
# е по-силен от buy-stop кандидат, а той — от "над pivot без обем"; extended най-накрая.
_WATCH_GROUP = {"confirmed": 0, "below_pivot": 1, "no_volume": 2, "extended": 3, "no_data": 4}


def watchlist_sort_key(c: dict) -> tuple:
    setup = c.get("setup") or classify_setup(c)
    return (_WATCH_GROUP.get(setup["kind"], 4), abs(c.get("pct_from_pivot") or 0.0))
