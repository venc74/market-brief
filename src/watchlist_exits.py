"""
Watchlist · "Излязоха от вчера" (09.10.2026). Тикърите от Watchlist на ПРЕДИШНИЯ бриф, които днес не са нито в Action, нито във Watchlist, с причината от кода — за да не се чете изчезването на карта като загадка
(08→09.10: AMD, DINO, KEYS, VLO). Причината е на кода, не на модела:
  • тикърът го няма в днешния технически списък → screener.explain_exits (първият филтър, който не минава: "RS линия 95.2% от 52-седмичния максимум < 97%", "база с дълбочина 36.4% (над 35%)", …);
  • тикърът е в днешните кандидати, но е извън 10-те карти на Watchlist → "извън 10-те карти" + днешният сетъп;
  • "вчера:" — какво е казвал сетъпът му в предишния бриф (напр. "структурен стоп 19.1% > 10%"). Само информация; нищо не се променя в Action/Watchlist.
Чисти функции без мрежа освен explain_exits (подава се отвън); всяка грешка → празен резултат (graceful), брифът не се чупи.
"""
from __future__ import annotations
import datetime as dt
import json
import re

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_SNAP = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


def setup_text(setup: dict | None) -> str | None:
    """Кратко описание на сетъпа от числата на кода (setup_rules): None, ако няма какво да се каже."""
    try:
        s = setup or {}
        kind = s.get("kind")
        if kind == "too_wide" and s.get("struct_risk_pct") is not None:
            return f"структурен стоп {float(s['struct_risk_pct']):.1f}% > {config.STOP_REJECT_STRUCT_RISK_PCT:g}%"
        if kind == "extended":
            return f"над +{config.BUYABLE_ZONE_MAX_PCT:g}% от pivot"
        if kind == "no_volume":
            return f"над pivot без обем ≥ {config.BREAKOUT_VOLUME_MULT:g}×"
        if kind == "below_pivot":
            return "под pivot — чака buy-stop"
        if kind == "confirmed":
            return "потвърден пробив"
    except (TypeError, ValueError):
        pass
    return None


def prior_watchlist(today_iso: str, data_dir=None) -> tuple[str | None, list[dict]]:
    """(дата, карти) на Watchlist от най-новия записан бриф със СТРОГО по-ранна дата от today_iso; нечетим snapshot се прескача към следващия по-стар; няма такъв → (None, [])."""
    try:
        d = pathlib.Path(data_dir or config.DATA_DIR)
        for p in sorted((x for x in d.glob("*.json") if _SNAP.match(x.name)), reverse=True):
            if p.stem >= today_iso:
                continue
            try:
                snap = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[watchlist_exits] {p.name} нечетим, пропускам: {type(e).__name__}: {e}")
                continue
            if isinstance(snap, dict) and isinstance(snap.get("watchlist"), list):
                return snap.get("date") or p.stem, [c for c in snap["watchlist"] if isinstance(c, dict) and c.get("ticker")]
    except Exception as e:
        print(f"[watchlist_exits] предишният Watchlist не се прочете: {type(e).__name__}: {e}")
    return None, []


def compute(prior_cards: list[dict], action: list[dict], watchlist: list[dict], candidates: list[dict], explain=None) -> list[dict]:
    """
    Редовете {ticker, reason, yesterday, kind} за тикърите от предишния Watchlist, които днес не са в Action/Watchlist (в реда от вчера). explain(tickers) -> {тикър: причина} за тези извън кандидатите
    (screener.explain_exits); без нея/при провал причината е "не е в днешния технически списък".
    """
    now = {c.get("ticker") for c in (action or [])} | {c.get("ticker") for c in (watchlist or [])}
    cands = {c.get("ticker"): c for c in (candidates or []) if c.get("ticker")}
    gone = [c for c in prior_cards if c["ticker"] not in now]
    outside = sorted({c["ticker"] for c in gone if c["ticker"] not in cands})
    reasons: dict = {}
    if outside and explain is not None:
        try:
            reasons = explain(outside) or {}
        except Exception as e:
            print(f"[watchlist_exits] причините не се смятаха: {type(e).__name__}: {e}")
    rows = []
    for c in gone:
        t = c["ticker"]
        if t in cands:
            st = setup_text(cands[t].get("setup"))
            reason, kind = "в скрийнъра, но извън 10-те карти" + (f" ({st})" if st else ""), "limit"
        else:
            reason, kind = reasons.get(t) or "не е в днешния технически списък", "screener"
        rows.append({"ticker": t, "reason": reason, "yesterday": setup_text(c.get("setup")), "kind": kind})
    return rows


def run(today_iso: str, action: list[dict], watchlist: list[dict], candidates: list[dict], explain=None, data_dir=None) -> dict:
    """{"from": дата на предишния бриф, "rows": [...]} или {} (няма предишен бриф / грешка)."""
    try:
        d, prior = prior_watchlist(today_iso, data_dir)
        if d is None:
            return {}
        return {"from": d, "rows": compute(prior, action, watchlist, candidates, explain)}
    except Exception as e:
        print(f"[watchlist_exits] пропуснато: {type(e).__name__}: {e}")
        return {}


def label(info: dict, today_iso: str) -> str:
    """"вчера (08.10)" при предишен календарен ден, иначе "предишния бриф (09.10)"."""
    try:
        d = dt.date.fromisoformat(info["from"])
        prev = dt.date.fromisoformat(today_iso) - dt.timedelta(days=1)
        return f"вчера ({d.day:02d}.{d.month:02d})" if d == prev else f"предишния бриф ({d.day:02d}.{d.month:02d})"
    except (KeyError, ValueError, TypeError):
        return "вчера"
