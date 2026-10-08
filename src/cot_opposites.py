"""
Обратен залог (08.10.2026, точка 2г + г от прегледа на брифа): бележката се сглобява от КОДА — не от модела, нищо не се маха.

Реални случаи на 08.10: VLO и DINO са в Watchlist (покупка), а в COT тезата за RBOB Gasoline са "губи" (цена надолу); HSY и MDLZ печелят при Cocoa, но губят при Sugar No. 11; MPC губи при
бензина, но печели при Corn. Секциите не се виждаха една друга. Сега:
  • картата в Action / Watchlist / Qullamaggie получава `cot_notes` — кои COT тези казват обратното на сетъпа (покупка срещу "губи"; шорт срещу "печели");
  • тикърът в COT тезата получава `opposite` — къде сме го подбрали (Action/Watchlist/Qullamaggie/Short) и обратното на какво е тезата;
  • тикър с обратен ефект в ДВА различни COT пазара (при различни движения на инструментите) получава `cross_market` и в двете тези. Лихвените пазари с една и съща посока на
    доходностите се махат по-рано (cot_theses.apply_rate_market_conflicts) — тук остава останалото, което е "маркира се, не се маха".
Текстът: ефектът (печели/губи) и движението идват от тезата (кодът ги е изчислил от config.COT_MECHANISM_SIGN × посоката на екстремума), причината — от таблицата
config.COT_EFFECT_REASON (механизъм × ефект). Моделът не участва. Чисти функции + annotate() (мутира подадените речници, никога не хвърля).
"""
from __future__ import annotations

import config

EFFECT_UP = {"gains": "ПЕЧЕЛИ", "loses": "ГУБИ"}
WHERE_LONG = (("action", "Action"), ("watchlist", "Watchlist"), ("qm", "Qullamaggie"))
SIDE_BG = {"long": "кандидат за покупка", "short": "кандидат за шорт"}


def reason(mechanism_type: str | None, effect: str, side: str | None = None) -> str | None:
    """Причината (от config.COT_EFFECT_REASON) за ефекта при механизъм; None за "other"/непознат тип."""
    key = f"tracks_instrument:{side}" if mechanism_type == "tracks_instrument" else mechanism_type
    return (config.COT_EFFECT_REASON.get(key or "") or {}).get(effect)


def entries(cot_rows: list[dict] | None) -> list[dict]:
    """
    Всички (пазар, тикър, ефект) от днешните COT тези с изчислен ефект: [{market, ticker, effect, move_text, sub ("direct"/"cross"), label, why}], където why е
    причината по механизма (за два механизма — двете, разделени с „ · “).
    """
    out = []
    for row in cot_rows or []:
        if not isinstance(row, dict):
            continue
        for sub_key, sub in (("direct", row.get("direct_thesis")), ("cross", row.get("cross_sector_thesis"))):
            for t in (sub or {}).get("tickers") or []:
                eff = t.get("effect") if isinstance(t, dict) else None
                if eff not in EFFECT_UP:
                    continue
                mechs = t.get("mechanisms") or ([{"type": t["mechanism_type"]}] if t.get("mechanism_type") else [])
                labels, whys = [], []
                for m in mechs:
                    typ = m.get("type")
                    labels.append((config.COT_MECHANISM_SIGN.get(typ) or {}).get("label") or ("следва инструмента" if typ == "tracks_instrument" else str(typ)))
                    w = reason(typ, eff, t.get("side"))
                    if w:
                        whys.append(w)
                out.append({"market": row.get("market"), "ticker": t.get("ticker"), "effect": eff, "move_text": row.get("move_text") or "", "sub": sub_key,
                            "label": " и ".join(dict.fromkeys(labels)), "why": " · ".join(dict.fromkeys(whys))})
    return out


def _tail(e: dict) -> str:
    return f"{EFFECT_UP[e['effect']]}" + (f" ({e['label']}: {e['why']})" if e["why"] else (f" ({e['label']})" if e["label"] else ""))


def card_note(e: dict) -> dict:
    """Бележката върху КАРТАТА: {market, effect, text}."""
    return {"market": e["market"], "effect": e["effect"],
            "text": f"COT: {e['move_text']} → {e['ticker']} {_tail(e)} — обратно на сетъпа; информация, не отменя нивата."}


def thesis_note(e: dict, where: str, side: str) -> dict:
    """Бележката върху тикъра в COT тезата: къде е подбран и обратното на какво е тезата."""
    return {"where": where, "side": side,
            "text": f"⚠ обратен залог: {e['ticker']} е {SIDE_BG[side]} в {where}, а тази теза казва {_tail(e)}."}


def _conflicting(side: str) -> str:
    return "loses" if side == "long" else "gains"


def cross_market(es: list[dict]) -> dict[tuple[str, str], list[str]]:
    """
    Един тикър с обратен ефект в различни COT пазари: {(пазар, тикър): [текстове]}. Само пазари с РАЗЛИЧЕН пазар (същият тикър два пъти в един пазар — директна и cross —
    се брои веднъж по пазар). Текстът за всеки пазар сочи обратните на него.
    """
    by_t: dict[str, dict[str, dict]] = {}
    for e in es:
        by_t.setdefault(e["ticker"], {}).setdefault(e["market"], e)
    out: dict[tuple[str, str], list[str]] = {}
    for tk, per_market in by_t.items():
        effects = {e["effect"] for e in per_market.values()}
        if len(per_market) < 2 or len(effects) < 2:
            continue
        for market, e in per_market.items():
            opp = [o for m, o in per_market.items() if m != market and o["effect"] != e["effect"]]
            if opp:
                out[(market, tk)] = [f"⚠ обратни сигнали: {tk} {EFFECT_UP[o['effect']]} — {o['move_text']}"
                                     + (f" ({o['label']}: {o['why']})" if o["why"] else "") for o in opp]
    return out


def annotate(cot_rows: list[dict] | None, long_lists: dict[str, list[dict]] | None = None, short_cards: list[dict] | None = None) -> dict:
    """
    Слага бележките: на картите (cot_notes), на тикърите в COT тезите (opposite, cross_market). long_lists — {"action": [...], "watchlist": [...], "qm": [...]} (картите са
    покупки), short_cards — шорт кандидатите. Идемпотентно (презаписва полетата), мутира на място, никога не хвърля. Връща диагностика {cards, theses, cross_market}.
    """
    diag = {"cards": 0, "theses": 0, "cross_market": 0}
    try:
        es = entries(cot_rows)
        by_ticker: dict[str, list[dict]] = {}
        seen_pair: set[tuple] = set()
        for e in es:                                                          # директна и cross теза на един пазар за същия тикър и ефект → една бележка
            k = (e["market"], e["ticker"], e["effect"])
            if k not in seen_pair:
                seen_pair.add(k)
                by_ticker.setdefault(e["ticker"], []).append(e)
        picked: dict[str, list[tuple[str, str]]] = {}                       # тикър → [(къде, страна)]
        groups = [(name, "long", (long_lists or {}).get(key) or []) for key, name in WHERE_LONG] + [("Short", "short", short_cards or [])]
        for where, side, cards in groups:
            for c in cards:
                tk = c.get("ticker") if isinstance(c, dict) else None
                if not tk:
                    continue
                picked.setdefault(tk, []).append((where, side))
                notes = [card_note(e) for e in by_ticker.get(tk, []) if e["effect"] == _conflicting(side)]
                if notes:
                    c["cot_notes"] = notes
                    diag["cards"] += 1
                else:
                    c.pop("cot_notes", None)
        cm = cross_market(es)
        for row in cot_rows or []:
            if not isinstance(row, dict):
                continue
            for sub in (row.get("direct_thesis"), row.get("cross_sector_thesis")):
                for t in (sub or {}).get("tickers") or []:
                    if not isinstance(t, dict) or not t.get("ticker"):
                        continue
                    opp = []
                    for where, side in picked.get(t["ticker"], []):
                        if t.get("effect") == _conflicting(side):
                            e = next((x for x in by_ticker[t["ticker"]] if x["market"] == row.get("market") and x["effect"] == t["effect"]), None)
                            if e:
                                opp.append(thesis_note(e, where, side))
                    if opp:
                        t["opposite"] = opp
                        diag["theses"] += 1
                    else:
                        t.pop("opposite", None)
                    texts = cm.get((row.get("market"), t["ticker"]))
                    if texts:
                        t["cross_market"] = texts
                        diag["cross_market"] += 1
                    else:
                        t.pop("cross_market", None)
    except Exception as ex:                                                   # бележките са информация — провал не чупи run-а
        print(f"[cot_opposites] бележките за обратен залог пропуснати: {type(ex).__name__}: {ex}")
    return diag
