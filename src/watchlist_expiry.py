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

Само "regime_gate" reason_type participва — от 10.10.2026 (В2) етикетът е на
КОДА (main._code_reason_type: потвърден сетъп, спрян от режима), не на модела;
"existing_position"/"earnings_blackout"/"technical_gate"/"regime_block"/"other"
не се засягат. Срокът е WATCHLIST_STALENESS_DAYS NYSE сесии (не календарни дни).

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
# В2 (10.10.2026): тикърите, изключени ДНЕС (изтекъл прозорец или вече изтекъл, докато режимът е Defensive) → {тикър: запис};
# main ги подава на watchlist_exits, за да покаже "Излязоха от вчера" с вярната причина
LAST_EXPIRED: dict = {}


def _expiry_for(first_seen: str) -> str:
    """
    В2: срокът е WATCHLIST_STALENESS_DAYS NYSE СЕСИИ след първото появяване (config: "работни дни"); до 10.10 беше timedelta(days=10) —
    календарни. Денят на първото появяване не се брои: изтича в сесия № N+1 от него, включително.
    """
    from src.setup_rules import session_window
    return session_window(first_seen, config.WATCHLIST_STALENESS_DAYS + 1)[-1].isoformat()


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
    LAST_EXPIRED.clear()
    try:
        state = _load()
        current_tickers = set()
        gated = set()           # В2: само тикърите, които ДНЕС са regime_gate (етикетът е на кода — main._code_reason_type)
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
            gated.add(ticker)

            rec = state.get(ticker)
            if rec is None:
                state[ticker] = {"first_seen_date": today, "expiry_date": _expiry_for(today),
                                 "expired": False}
                kept.append(c)
                continue

            if rec.get("expired"):
                if regime != "Defensive":
                    del state[ticker]
                    kept.append(c)
                else:
                    LAST_EXPIRED[ticker] = dict(rec)
                continue

            rec["expiry_date"] = _expiry_for(rec["first_seen_date"])       # В2: стари записи (календарни) → в сесии
            if today >= rec["expiry_date"] and regime == "Defensive":
                print(f"[watchlist_expiry] {ticker}: изтекъл regime-gate прозорец "
                     f"({rec['expiry_date']}), режимът остава Defensive — "
                     "автоматично изключен от watchlist")
                rec["expired"] = True
                LAST_EXPIRED[ticker] = dict(rec)
                continue

            kept.append(c)

        for ticker in list(state.keys()):
            # В2: изчиства се и записът на тикър, който е във Watchlist, но вече НЕ е regime_gate (сетъпът е друг — нова ситуация,
            # не подновяване от AI етикет; до 10.10 ZBRA/EXPD пазеха брояч, пуснат от етикета на модела)
            if ticker not in current_tickers or ticker not in gated:
                del state[ticker]

        _save(state)
        return kept
    except Exception as e:
        print(f"[watchlist_expiry] apply_regime_gate_expiry failed: {e}")
        return watchlist
