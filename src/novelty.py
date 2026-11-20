"""
20.11.2026 (пакет 20.11, т. 2): „Нови днес“ във всеки скрийнър (CANSLIM, Kullamägi, GLB Classic / Momentum, EP) — еднакъв вид. Ново е: първа поява в скрийнъра (в предишния бриф
го нямаше) ИЛИ промяна на статуса днес (чака пробив → близо до вход → пробив / вход; отпадане — отделно). Старите валидни — сгънати, по един ред: предложен ДД.ММ (първата поява
в поредицата от брифове), валиден до, разстояние до входа. Статусите — от числата на картата: „близо до вход“ = до config.NOVELTY_NEAR_PCT % до нивото.
Историята — записаните брифове преди днес (config.DATA_DIR, последните config.NOVELTY_HISTORY_BRIEFS). Чисти функции освен history().
"""
from __future__ import annotations

import json

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

SCREENERS = ("canslim", "qm", "glb_classic", "glb_momentum", "ep")
LABELS = {"canslim": "CANSLIM", "qm": "Kullamägi", "glb_classic": "GLB Classic", "glb_momentum": "GLB Momentum", "ep": "EP"}


def _near(dist) -> bool:
    return isinstance(dist, (int, float)) and 0 <= dist <= config.NOVELTY_NEAR_PCT


def statuses(brief: dict | None) -> dict[str, dict[str, dict]]:
    """Бриф → {скрийнър: {тикър: {"status", "dist"}}} — само валидните предложения (CANSLIM: „Купува се днес“ и „Чака пробив“; Kullamägi; GLB по тип; EP)."""
    b = brief or {}
    out = {s: {} for s in SCREENERS}
    for c in b.get("action") or []:
        if c.get("ticker"):
            out["canslim"][c["ticker"]] = {"status": "вход днес", "dist": None}
    for c in b.get("watchlist") or []:
        s = c.get("setup") or {}
        t = c.get("ticker")
        if not t:
            continue
        if s.get("kind") == "below_pivot" and s.get("buy_stop") and not s.get("triggered"):
            d = (s["buy_stop"] / c["price"] - 1) * 100 if isinstance(c.get("price"), (int, float)) and c["price"] > 0 else None
            out["canslim"][t] = {"status": "близо до вход" if _near(d) else "чака пробив", "dist": None if d is None else round(d, 2)}
        elif s.get("kind") == "confirmed":
            out["canslim"][t] = {"status": "пробив", "dist": None}
    for c in b.get("qm_breakout") or []:
        t = c.get("ticker")
        if not t:
            continue
        d = c.get("pct_to_trigger")
        if not isinstance(d, (int, float)) and isinstance(c.get("trigger"), (int, float)) and isinstance(c.get("close"), (int, float)) and c["close"] > 0:
            d = (c["trigger"] / c["close"] - 1) * 100
        bo = c.get("book_open") or {}
        st = "в позиция" if bo.get("filled") else ("близо до вход" if _near(d) else "чака пробив")
        out["qm"][t] = {"status": st, "dist": None if not isinstance(d, (int, float)) else round(d, 2)}
    for c in b.get("glb_candidates") or []:
        t = c.get("ticker")
        if not t:
            continue
        key = "glb_momentum" if (c.get("glb_type") or "").lower().startswith("mom") else "glb_classic"
        out[key][t] = {"status": "пробив днес" if c.get("sessions") == 1 else "над линията", "dist": c.get("pct_vs_line")}
    for r in ((b.get("qm_ep") or {}).get("rows")) or []:
        if r.get("ticker"):
            out["ep"][r["ticker"]] = {"status": "гап след затварянето", "dist": r.get("gap_pct")}
    return out


def history(today: str, n: int | None = None) -> list[tuple[str, dict]]:
    """[(дата, statuses(бриф))] за записаните брифове преди днес — от най-новия назад; нечетим — пропуснат."""
    files = sorted((p for p in config.DATA_DIR.glob("20[0-9][0-9]-[0-9][0-9]-[0-9][0-9].json") if p.stem < today), reverse=True)[:n or config.NOVELTY_HISTORY_BRIEFS]
    out = []
    for f in files:
        try:
            out.append((f.stem, statuses(json.loads(f.read_text(encoding="utf-8")))))
        except Exception as e:
            print(f"[novelty] {f.name}: {type(e).__name__}")
    return out


def classify(today: str, current: dict[str, dict], hist: list[tuple[str, dict]]) -> dict[str, dict]:
    """
    current — statuses() на днешните карти; hist — history(). → {скрийнър: {"items": {тикър: {status, dist, new, changed, first_seen, prev_status, label}}, "dropped": [тикъри]}}.
    first_seen — първият бриф от непрекъснатата поредица с тикъра в скрийнъра (до вчера); нов → днес. Чиста функция.
    """
    out = {}
    prev = hist[0][1] if hist else {s: {} for s in SCREENERS}
    for s in SCREENERS:
        items = {}
        for t, x in (current.get(s) or {}).items():
            first, pstat = today, None
            for d, st in hist:
                if t in (st.get(s) or {}):
                    first = d
                    if pstat is None:
                        pstat = st[s][t]["status"]
                else:
                    break
            in_prev = t in (prev.get(s) or {})
            new = not in_prev
            changed = in_prev and pstat is not None and pstat != x["status"]
            label = "нов днес" if new else (f"от {first[8:10]}.{first[5:7]} — днес {x['status']}" if changed else None)
            items[t] = {**x, "new": new, "changed": changed, "first_seen": first, "prev_status": pstat, "label": label}
        dropped = sorted(t for t in (prev.get(s) or {}) if t not in (current.get(s) or {}))
        out[s] = {"items": items, "dropped": dropped}
    return out


def annotate(brief_parts: dict, today: str, hist: list[tuple[str, dict]] | None = None) -> dict:
    """
    brief_parts — {"action", "watchlist", "qm_breakout", "glb_candidates", "qm_ep"} (днешните карти); слага card["novelty"] на картите и връща classify(...) за brief["novelty"].
    """
    hist = history(today) if hist is None else hist
    cur = statuses(brief_parts)
    res = classify(today, cur, hist)
    by = {}
    for s in SCREENERS:
        for t, v in res[s]["items"].items():
            by[(s, t)] = v
    for c in brief_parts.get("action") or []:
        if ("canslim", c.get("ticker")) in by:
            c["novelty"] = by[("canslim", c["ticker"])]
    for c in brief_parts.get("watchlist") or []:
        if ("canslim", c.get("ticker")) in by:
            c["novelty"] = by[("canslim", c["ticker"])]
    for c in brief_parts.get("qm_breakout") or []:
        if ("qm", c.get("ticker")) in by:
            c["novelty"] = by[("qm", c["ticker"])]
    for c in brief_parts.get("glb_candidates") or []:
        k = "glb_momentum" if (c.get("glb_type") or "").lower().startswith("mom") else "glb_classic"
        if (k, c.get("ticker")) in by:
            c["novelty"] = by[(k, c["ticker"])]
    for r in ((brief_parts.get("qm_ep") or {}).get("rows")) or []:
        if ("ep", r.get("ticker")) in by:
            r["novelty"] = by[("ep", r["ticker"])]
    return {s: {"new": sorted(t for t, v in res[s]["items"].items() if v["new"] or v["changed"]),
                "old": sorted(t for t, v in res[s]["items"].items() if not (v["new"] or v["changed"])), "dropped": res[s]["dropped"]} for s in SCREENERS}
