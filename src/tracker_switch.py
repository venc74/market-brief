"""
Track Record v2 — чист старт и архив на v1 (пакет 1, т.7 · 2026-10-03).

Защо: v1 статистиката не е надеждна база за сравнение (стари pivot/вход/стоп правила,
фантомни входове, цензурирани резултати) — Track Record-ът започва от нула под v2. Но историята
НЕ се трие: архивира се, с отделна статистика и обратим път.

switch_to_v2() — еднократно, при първия run с v2 код:
  1. резолюция на живите v1 позиции по обичайната логика (стоп/цел в пропуснатите дни);
  1а. v1 позициите, изтекли във фаза 1 (цел 1 недостигната → по v1 дизайн без R), получават
     mark-to-market R по Close на/преди датата на изтичане — както v2 изтичането — и влизат в n;
  2. останалите отворени v1 (open/trailing) се затварят по последния Close като "v1_closed" с
     mark-to-market R = (цена − entry) / (entry − стоп) (без цена или split флаг → без R, броят се
     като "без цена" и не влизат в статистиката);
  3. data/backtest_archive_v1.json получава ВСИЧКИ v1 записи, точно копие на tracker-а ПРЕДИ
     превключването (за връщане) и отделна v1 статистика;
  4. tracker-ът остава само с v2 записите; data/track_record_state.json пази методологията и
     v1 статистиката (брифът показва един ред "v1 методология: n=…, win rate …, среден R …").
Редът на записите е такъв, че срив на който и да е етап не губи данни: архивът се пише ПЪРВИ,
състоянието ПОСЛЕДНО; повторно изпълнение след срив довършва вместо да презаписва.

ensure_v2_methodology() — безопасният вход от main.py: идемпотентен, graceful (провал →
методологията остава v1 до следващия run, нищо не се губи).
revert_to_v1() — връща оригиналния v1 tracker; v2 записите се запазват в отделен backup файл.
"""
from __future__ import annotations
import collections
import copy
import datetime as dt
import json

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import backtest

_LIVE = ("open", "trailing")


def _archive_path() -> pathlib.Path:
    return config.DATA_DIR / "backtest_archive_v1.json"


def _write_json(path: pathlib.Path, data) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def v1_stats(records: dict) -> dict:
    """Статистика на v1 записи: n = резолвирани с R (включително v1_closed с цена)."""
    recs = list(records.values())
    resolved = [r for r in recs if r.get("realized_r") is not None]
    wins = [r for r in resolved if r["realized_r"] > 0]
    n = len(resolved)
    return {
        "n": n, "wins": len(wins), "losses": n - len(wins),
        "win_rate_pct": round(len(wins) / n * 100, 1) if n else 0.0,
        "avg_r": round(sum(r["realized_r"] for r in resolved) / n, 2) if n else 0.0,
        "records": len(recs),
        "v1_closed": sum(1 for r in recs if r.get("status") == "v1_closed"),
        "unpriced": sum(1 for r in recs if r.get("status") == "v1_closed" and r.get("realized_r") is None),
        # v1 "expired" (фаза 1) получава R при превключването (mark-to-market при изтичането, виж
        # _mark_expired_to_market); без цена/с split флаг остава без R, не влиза в n и се брои тук
        "expired_no_r": sum(1 for r in recs if r.get("status") == "expired" and r.get("realized_r") is None),
        "expired_mtm": sum(1 for r in recs if r.get("expiry_mtm")),
        "by_status": dict(collections.Counter(r.get("status") for r in recs)),
    }


def _close_v1_positions(legacy: dict, prices: dict, today: dt.date) -> list[str]:
    """Затваря отворените v1 (open/trailing) на последната цена; връща ключовете."""
    closed = []
    for key, rec in legacy.items():
        if rec.get("status") not in _LIVE:
            continue
        entry, stop = rec.get("entry_price"), rec.get("stop_loss")
        cur = prices.get(rec.get("ticker"))
        rec["closed_from"] = rec["status"]
        rec["status"] = "v1_closed"
        rec["resolution_date"] = today.isoformat()
        rec["discovered_date"] = today.isoformat()
        if cur is None or rec.get("needs_manual_review") or not entry or not stop or entry <= stop:
            rec["realized_r"] = None            # без валидна цена/скала → извън статистиката
            rec["mtm_unavailable"] = True
        else:
            rec["close_price"] = round(float(cur), 4)
            rec["realized_r"] = round((float(cur) - entry) / (entry - stop), 2)
        closed.append(key)
    return closed


def _mark_expired_to_market(legacy: dict, fetch_closes) -> list[str]:
    """
    v1 "expired" без R (фаза 1: цел 1 недостигната до 16-ата седмица) → R по Close на/преди
    датата на изтичане (resolution_date), с формулата на v1: (Close − entry) / (entry − стоп).
    Без цена, split флаг или невалидни нива → остава без R. Връща ключовете с R.
    """
    pending = {k: r for k, r in legacy.items()
               if r.get("status") == "expired" and r.get("realized_r") is None and r.get("resolution_date")}
    if not pending:
        return []
    closes = fetch_closes(sorted({(r["ticker"], r["resolution_date"]) for r in pending.values()})) or {}
    done = []
    for key, rec in pending.items():
        px = closes.get((rec["ticker"], rec["resolution_date"]))
        entry, stop = rec.get("entry_price"), rec.get("stop_loss")
        if px is None or rec.get("needs_manual_review") or not entry or not stop or entry <= stop:
            continue
        rec["expiry_close"] = round(float(px), 4)
        rec["realized_r"] = round((float(px) - entry) / (entry - stop), 2)
        rec["expiry_mtm"] = True
        done.append(key)
    return done


def switch_to_v2(today: dt.date | None = None, *, fetch_prices=None, fetch_expiry_closes=None) -> dict:
    """Виж модулния docstring. Връща {"status": ..., ...}; не вдига при очаквани провали."""
    today = today or dt.date.today()
    fetch_prices = fetch_prices or backtest._fetch_current_prices
    fetch_expiry_closes = fetch_expiry_closes or backtest._fetch_closes_on_or_before
    tracker = backtest._load_tracker()
    legacy = {k: r for k, r in tracker.items() if r.get("method") != "v2"}
    v2_recs = {k: r for k, r in tracker.items() if r.get("method") == "v2"}
    state_path = backtest._state_path()

    if not legacy:
        # няма v1 записи: или чист старт, или предишен run се е сринал СЛЕД архива и tracker-а
        stats = None
        if _archive_path().exists():
            stats = json.loads(_archive_path().read_text(encoding="utf-8")).get("stats")
        _write_json(state_path, {"methodology": "v2", "switched_on": today.isoformat(),
                                 "v1_archive_file": _archive_path().name if stats else None,
                                 "v1_stats": stats, "reverted_on": None})
        return {"status": "adopted" if stats else "fresh_start"}

    pre_switch = copy.deepcopy(tracker)            # точното v1 състояние — за revert
    # 1) пропуснати стопове/цели по обичайната логика (мутира записите на място)
    backtest._resolve_open_positions(tracker, today)
    expired_mtm = _mark_expired_to_market(legacy, fetch_expiry_closes)      # 1а) изтеклите получават R
    live = {k: r for k, r in legacy.items() if r.get("status") in _LIVE}
    prices = {}
    if live:
        prices = fetch_prices(sorted({r["ticker"] for r in live.values()}))
        if not prices:
            print("[switch] няма цени за отворените v1 позиции — отлагам превключването за следващия run")
            return {"status": "deferred", "reason": "no_prices"}
    closed = _close_v1_positions(legacy, prices, today)
    stats = v1_stats(legacy)

    archive = {"archived_on": today.isoformat(),
               "note": "v1 методология — архив при превключването към Track Record v2; не се трие.",
               "pre_switch_tracker": pre_switch, "records": legacy, "closed_on_switch": closed,
               "expired_marked_to_market": expired_mtm,
               "prices": {t: round(float(p), 4) for t, p in prices.items()}, "stats": stats}
    _write_json(_archive_path(), archive)                         # 1) архив (при срив tracker-ът е непокътнат)
    backtest._save_tracker(v2_recs)                               # 2) tracker само с v2
    _write_json(state_path, {"methodology": "v2", "switched_on": today.isoformat(),   # 3) състояние ПОСЛЕДНО
                             "v1_archive_file": _archive_path().name, "v1_stats": stats, "reverted_on": None})
    print(f"[switch] Track Record v2 от {today}: {len(legacy)} v1 записа в архива, {len(closed)} затворени по "
          f"последната цена, {len(expired_mtm)} изтекли оценени по Close при изтичането; "
          f"v1: n={stats['n']}, win rate {stats['win_rate_pct']}%, среден R {stats['avg_r']}")
    return {"status": "switched", "archived": len(legacy), "closed": len(closed),
            "expired_mtm": len(expired_mtm), "stats": stats}


def ensure_v2_methodology(today: dt.date | None = None, *, fetch_prices=None, fetch_expiry_closes=None) -> dict:
    """Безопасният вход от main.py: идемпотентен и graceful (провал → v1 до следващия run)."""
    if not config.TRACK_RECORD_V2:
        return {"status": "disabled"}
    try:
        if backtest.methodology() == "v2":
            return {"status": "already"}
        return switch_to_v2(today, fetch_prices=fetch_prices, fetch_expiry_closes=fetch_expiry_closes)
    except Exception as e:
        print(f"[switch] превключването към v2 пропадна, остава v1 до следващия run: {type(e).__name__}: {e}")
        return {"status": "failed", "error": str(e)}


def revert_to_v1(today: dt.date | None = None) -> dict:
    """
    Връща оригиналния v1 tracker (точното състояние преди превключването). Текущият tracker
    (v2 записите) се запазва в data/backtest_tracker_v2_backup_<дата>.json — нищо не се губи.
    След връщането methodology() е "v1"; ensure_v2_methodology() ще превключи наново при
    следващия run, освен ако TRACK_RECORD_V2=0.
    """
    today = today or dt.date.today()
    if not _archive_path().exists():
        return {"status": "no_archive"}
    archive = json.loads(_archive_path().read_text(encoding="utf-8"))
    pre = archive.get("pre_switch_tracker")
    if not isinstance(pre, dict):
        return {"status": "no_archive"}
    current = backtest._load_tracker()
    backup = config.DATA_DIR / f"backtest_tracker_v2_backup_{today.isoformat()}.json"
    _write_json(backup, current)
    restored = copy.deepcopy(pre)
    for key, rec in current.items():                       # v2 записи остават в backup-а, не в v1 tracker-а
        if rec.get("method") != "v2":
            restored.setdefault(key, rec)
    backtest._save_tracker(restored)
    state = backtest.load_state()
    _write_json(backtest._state_path(), {**state, "methodology": "v1", "reverted_on": today.isoformat()})
    return {"status": "reverted", "records": len(restored), "v2_backup": backup.name}
