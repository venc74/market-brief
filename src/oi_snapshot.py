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

Какво се снима: топ config.UNUSUAL_OPTIONS_OI_SNAPSHOT_TICKERS от днешното
ранжиране по ликвидност (кешът от сутрешния run, същият ред), по
config.UNUSUAL_OPTIONS_OI_SNAPSHOT_EXPIRATIONS най-близки падежа, OI по падеж
(calls + puts). Утрешното ранжиране се прави наново — резервът над
SCAN_LIMIT покрива разликата (виж config).

Graceful: провал на тикър → пропуска се; ден без сесия (празник) → нищо не се
записва; провал изцяло → файлът остава какъвто е, сутрешният бриф казва, че
снимката липсва.

Dedup/cutoff (FIX 2026-10-03): workflow-ът пуска И schedule: (15:00 UTC), И
workflow_dispatch от cron-job.org — ако вече има снимка за днешната сесия
(кой да е от двата тригера я е взел), вторият run пропуска, не презаписва.
Ако нищо още няма и часът е след config.UNUSUAL_OPTIONS_OI_SNAPSHOT_CUTOFF_UTC_HOUR
(20:00 UTC по подразбиране) — също пропуска, вместо да пази OI извън измерения
валиден прозорец (~13:30–20:00 UTC). Виж _skip_reason().
"""
from __future__ import annotations
import datetime as dt
import json
import time

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import unusual_options as uo


def _skip_reason(session: dt.date, existing: dict, now_utc: dt.datetime) -> str | None:
    """
    Чиста функция (без мрежа/часовник) — FIX 2026-10-03 (отговор на прегледа
    на партида 1, т.4): workflow-ът има и schedule: (15:00 UTC), и
    workflow_dispatch от cron-job.org — двата може да стрелят за същия ден
    (GitHub-native scheduler закъснява с часове, наблюдавано: 19:55 UTC и
    18:22 UTC за 30.09/29.09). Връща причина за пропускане, или None ако
    трябва да продължи. Изнесена отделно за тест без мокване на
    дата/мрежа — виж _merge_regime() в thermometer.py за същия паттърн.
    """
    if session.isoformat() in existing:
        fetched = existing[session.isoformat()].get("fetched_at_utc", "?")
        return (f"снимка за сесия {session} вече съществува (fetched_at_utc={fetched}) "
                f"— пропускам, не презаписвам")
    if now_utc.hour >= config.UNUSUAL_OPTIONS_OI_SNAPSHOT_CUTOFF_UTC_HOUR:
        return (f"{now_utc.strftime('%H:%M')} UTC — след прага "
                f"({config.UNUSUAL_OPTIONS_OI_SNAPSHOT_CUTOFF_UTC_HOUR}:00 UTC) за валиден OI "
                f"прозорец — пропускам вместо да пазя данни извън измерения прозорец")
    return None


def take_snapshot() -> dict | None:
    if uo.yf is None:
        print("[oi_snapshot] yfinance липсва — нищо не е заснето")
        return None
    today = dt.datetime.now(dt.timezone.utc).date()
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
    tickers = uo._top_by_volume(uo._sp500_ndx_universe(),
                                config.UNUSUAL_OPTIONS_OI_SNAPSHOT_TICKERS)
    oi: dict[str, dict[str, int]] = {}
    failed: list[str] = []
    for sym in tickers:
        try:
            tk = uo.yf.Ticker(sym)
            per_exp = {}
            for exp in (tk.options or [])[:config.UNUSUAL_OPTIONS_OI_SNAPSHOT_EXPIRATIONS]:
                ch = tk.option_chain(exp)
                per_exp[exp] = int(sum(
                    float(df["openInterest"].fillna(0).sum())
                    for df in (ch.calls, ch.puts)
                    if df is not None and not df.empty and "openInterest" in df))
            if per_exp:
                oi[sym] = per_exp
        except Exception as e:
            failed.append(sym)
            print(f"[oi_snapshot] {sym}: {type(e).__name__}: {e}")

    with_oi = sum(1 for v in oi.values() if sum(v.values()) >= 50)
    snap = {"session_date": session.isoformat(),
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
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
