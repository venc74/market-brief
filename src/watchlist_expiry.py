"""
Watchlist regime-gate expiry — code-enforced state за "regime_gate" тип
watchlist кандидати (findings log 04-11.09, т.2).

Преди: датата, до която чакаме конкретна промяна в пазарния режим, беше
чист AI prose в свободния watchlist_trigger текст ("до 2026-09-15").
Потвърдено на 4 отделни дни (DELL/ROKU): AI-то преждевременно твърдеше, че
правилото вече се е задействало — 8 дни ПРЕДИ собствената си дата — а на
следващия ден напълно забравяше концепцията, връщайки се към plain текст
без дата изобщо. Нула code state зад твърдението, чист AI prose.

Сега: датата е code-computed (config.WATCHLIST_STALENESS_DAYS от първото
появяване), не AI избор — same "кодът има последната дума" принцип като
apply_hard_rules() в main.py. AI-то продължава да описва цена/обем условието
свободно (watchlist_trigger), но вече не решава КОГА тезата изтича, нито
дали правилото вече се е задействало.

Само "regime_gate" reason_type participва (виж ai_brief.py промпт
инструкцията) — "existing_position"/"earnings_blackout"/"other" не се
засягат от този механизъм.

Anti-renewal защита: при изтичане записът се маркира "expired": True, НЕ
се трие директно — ако СЪЩИЯТ тикър продължи да получава "regime_gate"
класификация, докато режимът остава Defensive, той остава изключен, вместо
да получи нов 10-дневен прозорец всеки път, когато AI-то го предложи наново
(което би направило прозореца безсмислен — вечно подновяващ се). Записът
се изчиства само когато режимът вече не е Defensive (условието е разрешено,
по един или друг начин) ИЛИ тикърът напусне watchlist кандидатурата изцяло.

Персистира се в data/watchlist_expiry.json, keyed по тикър.

Graceful degradation: провал навсякъде тук → връща оригиналния watchlist
непроменен, не чупи pipeline-а; липсващ/повреден JSON → празен dict.
"""
from __future__ import annotations
import datetime as dt
import json

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_STATE_PATH = config.DATA_DIR / "watchlist_expiry.json"


def _load() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[watchlist_expiry] state JSON повреден, започвам от празен: {e}")
    return {}


def _save(state: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str),
                           encoding="utf-8")


def apply_regime_gate_expiry(watchlist: list[dict], regime: str, today: str) -> list[dict]:
    """
    За всеки watchlist кандидат с ai.watchlist_reason_type == "regime_gate":
      - няма запис -> създава {first_seen_date, expiry_date, expired: False};
      - има активен запис, today >= expiry_date, regime == "Defensive" ->
        маркира expired=True, изключва тикъра от резултата;
      - вече expired запис, regime все още Defensive -> остава изключен
        (anti-renewal, виж модул docstring-а);
      - regime вече не е Defensive -> записът се изчиства (условието вече
        не важи, каквото и да стане после е нова преценка).

    Тикъри, отпаднали от watchlist кандидатурата изцяло (по друга причина),
    се prune-ват от state-а, за да не расте неограничено.

    Връща филтрирания watchlist списък. Graceful: изключение -> оригиналния
    watchlist непроменен.
    """
    try:
        state = _load()
        current_tickers = set()
        kept = []

        for c in watchlist:
            ticker = c.get("ticker")
            reason_type = (c.get("ai") or {}).get("watchlist_reason_type")
            if not ticker:
                kept.append(c)
                continue
            current_tickers.add(ticker)

            if reason_type != "regime_gate":
                kept.append(c)
                continue

            rec = state.get(ticker)
            if rec is None:
                expiry = (dt.date.fromisoformat(today) +
                         dt.timedelta(days=config.WATCHLIST_STALENESS_DAYS)).isoformat()
                state[ticker] = {"first_seen_date": today, "expiry_date": expiry,
                                 "expired": False}
                kept.append(c)
                continue

            if rec.get("expired"):
                if regime != "Defensive":
                    del state[ticker]
                    kept.append(c)
                continue

            if today >= rec["expiry_date"] and regime == "Defensive":
                print(f"[watchlist_expiry] {ticker}: изтекъл regime-gate прозорец "
                     f"({rec['expiry_date']}), режимът остава Defensive — "
                     "автоматично изключен от watchlist")
                rec["expired"] = True
                continue

            kept.append(c)

        for ticker in list(state.keys()):
            if ticker not in current_tickers:
                del state[ticker]

        _save(state)
        return kept
    except Exception as e:
        print(f"[watchlist_expiry] apply_regime_gate_expiry failed: {e}")
        return watchlist
