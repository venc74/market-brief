"""
Следобедна снимка на open interest за Unusual Options (FIX 2026-09-29).

Пуска се от отделен GitHub Actions job (.github/workflows/oi_snapshot.yml) в
15:00 UTC в работни дни, НЕ от сутрешния бриф. Причината — проба 29.09.2026:
в 05:40 UTC Yahoo връща OI 0 за седмичните падежи и непълен за месечните
(APH 38 734 в 05:35 срещу 248 232 в 13:09 UTC за същите два падежа). До 18.09
сутрешният fetch получаваше пълен OI; от 21.09 — не.

Логиката на съотношението: сутрешният бриф показва ВЧЕРАШНИЯ опционен обем.
Правилният знаменател е OI в началото на вчерашната сесия — точно това, което
Yahoo показва следобед в деня на сесията (OI се обновява веднъж дневно от OCC
и не се мени в рамките на сесията). Затова тази снимка се пази с датата на
сесията, а утрешният бриф търси снимката за своята "последна сесия".

Какво се снима (пакет 4б т.б, 06.10.2026): НАШИТЕ тикъри — кандидатите от последните брифове и позициите (snapshot_tickers); списъкът "Unusual
Options" отпадна, затова топ-80 по ликвидност вече не е нужен (config.UNUSUAL_OPTIONS_OI_SNAPSHOT_TICKERS, по подразбиране 0). OI по падеж
(calls + puts) за ВСИЧКИ падежи в (сесия, сесия + UNUSUAL_OPTIONS_OI_SNAPSHOT_HORIZON_DAYS]
(пакет 4б т.а, 06.10.2026: преди — първите 4 падежа; знаменателят на
съотношението трябва да е от един и същ времеви прозорец, виж unusual_options.py).
Снимката носи horizon_days — по него се различава от старата (първите 4 падежа).

Graceful: провал на тикър → пропуска се; ден без сесия (празник) → нищо не се
записва; провал изцяло → файлът остава какъвто е, сутрешният бриф казва, че
снимката липсва.

Dedup/cutoff (FIX 2026-10-01): workflow-ът пуска И schedule: (15:00 UTC), И
workflow_dispatch от cron-job.org — ако вече има снимка за днешната сесия
(кой да е от двата тригера я е взел), вторият run пропуска, не презаписва.
Ако няма пълна снимка и часът в Ню Йорк е след
config.UNUSUAL_OPTIONS_OI_SNAPSHOT_CUTOFF_NY_HOUR (16:00 ET = 20:00 UTC през
лятото, 21:00 UTC през зимата) — също пропуска, вместо да пази OI извън
измерения валиден прозорец (сесията 09:30–16:00 ET). Виж _skip_reason().
"""
from __future__ import annotations
import datetime as dt
import json
import re
import time

from zoneinfo import ZoneInfo

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import unusual_options as uo

_NY = ZoneInfo("America/New_York")


def _quality(snap: dict) -> tuple[int, int, int]:
    """(тикъри, от тях с OI ≥ 50, заявени) — заявени = успешни + неуспешни."""
    t = snap.get("tickers") or {}
    with_oi = sum(1 for v in t.values() if sum(v.values()) >= 50)
    return len(t), with_oi, len(t) + len(snap.get("failed") or [])


def snapshot_is_complete(snap: dict) -> bool:
    """
    FIX 2026-10-02 (т.4 от 02.10): "вече има снимка" не значи "има ПЪЛНА снимка".
    Пълна = поне config.UNUSUAL_OPTIONS_OI_SNAPSHOT_MIN_COMPLETE_PCT % от
    заявените тикъри са успешни И поне половината от успешните имат OI ≥ 50
    (същият праг като предупреждението "празен OI и следобед" в take_snapshot).
    Реалните снимки 29.09–01.10: 80/80, failed 0, OI ≥ 50 за 80 — пълни.
    """
    n, with_oi, requested = _quality(snap)
    if n == 0 or requested == 0:
        return False
    return (n / requested * 100 >= config.UNUSUAL_OPTIONS_OI_SNAPSHOT_MIN_COMPLETE_PCT
            and with_oi >= n / 2)


def _skip_reason(session: dt.date, existing: dict, now_utc: dt.datetime) -> str | None:
    """
    Чиста функция (без мрежа/часовник) — FIX 2026-10-01 (отговор на прегледа
    на партида 1, т.4): workflow-ът има и schedule: (15:00 UTC), и
    workflow_dispatch от cron-job.org — двата може да стрелят за същия ден
    (GitHub-native scheduler закъснява с часове, наблюдавано: 19:55 UTC и
    18:22 UTC за 30.09/29.09). Връща причина за пропускане, или None ако
    трябва да продължи. Изнесена отделно за тест без мокване на
    дата/мрежа — виж _merge_regime() в thermometer.py за същия паттърн.

    02.10: пропуска само ако съществуващата снимка е ПЪЛНА; непълна → нов
    опит (преди крайния срок), а save() пази по-добрата от двете.
    """
    snap = existing.get(session.isoformat())
    if snap and snapshot_is_complete(snap):
        fetched = snap.get("fetched_at_utc", "?")
        return (f"пълна снимка за сесия {session} вече съществува (fetched_at_utc={fetched}) "
                f"— пропускам, не презаписвам")
    now_ny = now_utc.astimezone(_NY)
    if now_ny.hour >= config.UNUSUAL_OPTIONS_OI_SNAPSHOT_CUTOFF_NY_HOUR:
        extra = (" (съществуващата снимка е непълна, но повторен опит вече е късно)"
                 if snap else "")
        return (f"{now_utc.strftime('%H:%M')} UTC ({now_ny.strftime('%H:%M %Z')}) — след "
                f"прага ({config.UNUSUAL_OPTIONS_OI_SNAPSHOT_CUTOFF_NY_HOUR}:00 Ню Йорк) за "
                f"валиден OI прозорец — пропускам вместо да пазя данни извън измерения "
                f"прозорец{extra}")
    if snap:
        n, with_oi, requested = _quality(snap)
        print(f"[oi_snapshot] съществуваща снимка за {session} е непълна "
              f"({n}/{requested} тикъра, OI ≥ 50 за {with_oi}) — нов опит")
    return None


def snapshot_tickers(max_briefs: int | None = None) -> list[str]:
    """
    Пакет 4б т.б: НАШИТЕ тикъри за снимката — Action/Watchlist от последните config.UNUSUAL_OPTIONS_SNAPSHOT_BRIEF_DAYS брифа (data/YYYY-MM-DD.json;
    кандидатите се повтарят от ден на ден) плюс позициите от tracker-а (pending/open/trailing, и двете книги). Чисто локално четене; провал на файл
    се пропуска. Редът е стабилен (най-новите брифове първи), без дубликати.
    """
    n = config.UNUSUAL_OPTIONS_SNAPSHOT_BRIEF_DAYS if max_briefs is None else max_briefs
    out: list[str] = []

    def add(t):
        if isinstance(t, str) and t and t not in out:
            out.append(t)
    files = sorted((p for p in config.DATA_DIR.glob("*.json") if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", p.name)), reverse=True)[:n]
    for path in files:
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[oi_snapshot] {path.name} нечетим, пропускам: {e}")
            continue
        for c in (brief.get("action") or []) + (brief.get("watchlist") or []):
            add(c.get("ticker"))
    try:
        tracker = json.loads((config.DATA_DIR / "backtest_tracker.json").read_text(encoding="utf-8"))
        for rec in tracker.values():
            if rec.get("status") in ("pending", "open", "trailing"):
                add(rec.get("ticker"))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[oi_snapshot] tracker нечетим, пропускам позициите: {e}")
    return out


def _window_oi(tk, session: dt.date) -> dict[str, int]:
    """OI (calls + puts) по падеж за падежите в (session, session + HORIZON_DAYS]; падеж, изтекъл в деня на сесията, не се снима."""
    hi = session + dt.timedelta(days=config.UNUSUAL_OPTIONS_OI_SNAPSHOT_HORIZON_DAYS)
    per_exp: dict[str, int] = {}
    for exp in (tk.options or []):
        try:
            d = dt.date.fromisoformat(str(exp))
        except ValueError:
            continue
        if not (session < d <= hi) or len(per_exp) >= config.UNUSUAL_OPTIONS_MAX_EXPIRIES + 2:
            continue
        ch = tk.option_chain(exp)
        per_exp[str(exp)] = int(sum(
            float(df["openInterest"].fillna(0).sum())
            for df in (ch.calls, ch.puts)
            if df is not None and not df.empty and "openInterest" in df))
    return per_exp


def take_snapshot() -> dict | None:
    if uo.yf is None:
        print("[oi_snapshot] yfinance липсва — нищо не е заснето")
        return None
    # дата в Ню Йорк (като датата на последния бар на SPY), не UTC датата
    today = dt.datetime.now(dt.timezone.utc).astimezone(_NY).date()
    session = uo.last_session_date()
    if session != today:
        print(f"[oi_snapshot] днес ({today}) няма сесия (последна: {session}) — "
              f"нищо не се записва")
        return None

    reason = _skip_reason(session, uo.load_oi_snapshots(), dt.datetime.now(dt.timezone.utc))
    if reason:
        print(f"[oi_snapshot] {reason}")
        return None

    t0 = time.time()
    # пакет 4б т.б: нашите кандидати и позиции (+ по избор най-ликвидните, config.UNUSUAL_OPTIONS_OI_SNAPSHOT_TICKERS; по подразбиране 0)
    tickers = snapshot_tickers()
    if config.UNUSUAL_OPTIONS_OI_SNAPSHOT_TICKERS > 0:
        tickers += [t for t in uo._top_by_volume(uo._sp500_ndx_universe(), config.UNUSUAL_OPTIONS_OI_SNAPSHOT_TICKERS) if t not in tickers]
    if not tickers:
        print("[oi_snapshot] няма кандидати и позиции за снимка — нищо не е заснето")
        return None
    oi: dict[str, dict[str, int]] = {}
    failed: list[str] = []
    for sym in tickers:
        try:
            per_exp = _window_oi(uo.yf.Ticker(sym), session)
            if per_exp:
                oi[sym] = per_exp
        except Exception as e:
            failed.append(sym)
            print(f"[oi_snapshot] {sym}: {type(e).__name__}: {e}")

    with_oi = sum(1 for v in oi.values() if sum(v.values()) >= 50)
    snap = {"session_date": session.isoformat(),
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "horizon_days": config.UNUSUAL_OPTIONS_OI_SNAPSHOT_HORIZON_DAYS,
            "tickers": oi, "failed": failed}
    print(f"[oi_snapshot] сесия {session}: {len(oi)}/{len(tickers)} тикъра, "
          f"OI ≥ 50 за {with_oi}, неуспешни {failed or '—'}, {time.time() - t0:.0f} с")
    if oi and with_oi < len(oi) / 2:
        # и следобед празен OI = нов проблем, не часът — да се види в лога
        print(f"[oi_snapshot] ⚠ OI ≥ 50 само за {with_oi}/{len(oi)} — Yahoo връща "
              f"празен OI и следобед")
    return snap


def save(snap: dict) -> None:
    path = config.UNUSUAL_OPTIONS_OI_SNAPSHOT_FILE
    snaps = uo.load_oi_snapshots()
    old = snaps.get(snap["session_date"])
    if old and (_quality(old)[1], _quality(old)[0]) > (_quality(snap)[1], _quality(snap)[0]):
        print(f"[oi_snapshot] новата снимка е по-лоша от съществуващата за "
              f"{snap['session_date']} — запазвам старата")
        return
    snaps[snap["session_date"]] = snap
    keep = sorted(snaps)[-config.UNUSUAL_OPTIONS_OI_SNAPSHOT_KEEP:]
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"snapshots": {d: snaps[d] for d in keep}},
                               ensure_ascii=False, indent=1))
    print(f"[oi_snapshot] записано в {path.name} (пазят се {len(keep)} сесии)")


if __name__ == "__main__":
    try:
        s = take_snapshot()
        if s and s["tickers"]:
            save(s)
    except Exception as e:
        # никога не чупи job-а — сутрешният бриф ще каже, че снимката липсва
        print(f"[oi_snapshot] неуспешен изцяло: {type(e).__name__}: {e}")
