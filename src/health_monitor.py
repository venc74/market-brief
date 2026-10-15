"""
Здравен монитор (втори преглед, 10.10.2026, подобрение №1) · проверка на очакваните артефакти в края на run-а → банер при липса.

Защо: К1 — OI снимката не се записваше от 09.10 (job-ът падаше при git pull --rebase), а брифът щеше да показва "снимката липсва" ден след ден, без нищо да казва,
че job-ът е счупен. Провалите на теглене са графични (graceful) — това е добре за брифа, но значи, че се виждат само ако нещо ги търси.
Проверки (чиста функция върху data/ и статусите на модулите; без мрежа):
  1. OI снимката за предишната NYSE сесия (job "Unusual Options OI snapshot");
  2. брифът (data/<дата>.json) за предишната NYSE сесия — пропуснат сутрешен run;
  3. книгите: резолюцията на живите записи (backtest.LAST_RESOLUTION) — цени няма / до по-стара дата / тикъри без цени;
  4. GLB състоянието (data/glb_state.json) е записано днес, щом скрийнърът е минал;
  5. дневните кешове (news, splits, 13F, Magic Formula) са с днешна дата;
  6. таблицата NYSE_HOLIDAYS не свършва в следващите NYSE_HOLIDAYS_WARN_DAYS дни;
  7. (16.10.2026) дневните барове са за последната NYSE сесия (bar_freshness: изчакването преди run-а и делът на универса със стар бар).
Всяка проверка е в собствен try — грешка в монитора не чупи брифа и не вдига фалшив банер.
"""
from __future__ import annotations
import datetime as dt
import json
import pathlib

import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src.setup_rules import is_session

# кеш → (флаг в config, човешко име)
DAILY_CACHES = {
    "news_cache.json": ("ENABLE_NEWS", "значимите новини"),
    "splits_cache.json": ("ENABLE_SPLITS_CALENDAR", "календара на сплитовете"),
    "dataroma_cache.json": ("ENABLE_DATAROMA", "13F (Superinvestor)"),
    "magic_formula_cache.json": ("ENABLE_MAGIC_FORMULA", "Magic Formula (MF✓)"),
}


def prev_session(today) -> dt.date:
    d = dt.date.fromisoformat(str(today)) - dt.timedelta(days=1)
    while not is_session(d):
        d -= dt.timedelta(days=1)
    return d


def _read(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _fmt(d) -> str:
    try:
        x = dt.date.fromisoformat(str(d))
        return f"{x.day:02d}.{x.month:02d}"
    except (TypeError, ValueError):
        return str(d)


def check(today: str, data_dir=None, *, resolution: dict | None = None, glb_status: dict | None = None, freshness: dict | None = None) -> list[dict]:
    """[{"check", "message"}] — само проблемите; празен списък = всичко очаквано е налице."""
    d = pathlib.Path(data_dir or config.DATA_DIR)
    prev = prev_session(today).isoformat()
    out: list[dict] = []

    try:                                     # 16.10.2026: застоял дневен бар (src/bar_freshness.py) — единственият банер за него
        from src import bar_freshness
        msg = bar_freshness.message(freshness)
        if msg:
            out.append({"check": "daily_bars", "message": msg})
    except Exception as e:
        print(f"[health] дневните барове не се провериха: {type(e).__name__}: {e}")

    if config.ENABLE_UNUSUAL_OPTIONS:
        try:
            snaps = _read(d / "unusual_options_oi_snapshot.json").get("snapshots") or {}
            if prev not in snaps:
                last = max(snaps) if snaps else None
                out.append({"check": "oi_snapshot", "message": (
                    f"OI снимката за сесията {_fmt(prev)} липсва (последна: {_fmt(last) if last else 'няма'}) — UOV✓ и очакваното движение при отчет липсват (липсващ UOV✓ НЕ значи нормален обем); "
                    "провери job-а „Unusual Options OI snapshot“ в GitHub Actions.")})
        except FileNotFoundError:
            out.append({"check": "oi_snapshot", "message": "файлът с OI снимките липсва — job-ът „Unusual Options OI snapshot“ не е записвал."})
        except Exception as e:
            print(f"[health] OI снимката не се провери: {type(e).__name__}: {e}")

    try:
        if not (d / f"{prev}.json").exists():
            out.append({"check": "prior_brief", "message": f"брифът за предишната сесия ({_fmt(prev)}) липсва — сутрешният run вероятно не е минал (cron-job.org / Actions)."})
    except Exception as e:
        print(f"[health] предишният бриф не се провери: {type(e).__name__}: {e}")

    if config.ENABLE_BACKTEST and resolution:
        try:
            r = resolution
            if r.get("ok") is False:
                out.append({"check": "books", "message": f"книгите не са обновени днес — цените за {r.get('live')} живи записа не се изтеглиха ({r.get('error')}); резолюцията е отложена."})
            elif r.get("live"):
                if r.get("data_through") and r["data_through"] < prev:
                    out.append({"check": "books", "message": f"цените за живите записи в книгите са до {_fmt(r['data_through'])}, очаквано {_fmt(prev)} — резолюцията може да изостава."})
                if r.get("missing"):
                    out.append({"check": "books", "message": f"без цени днес (резолюцията им е отложена): {', '.join(r['missing'])}."})
        except Exception as e:
            print(f"[health] книгите не се провериха: {type(e).__name__}: {e}")

    if config.ENABLE_GLB_SCREENER and (glb_status or {}).get("ok"):
        try:
            upd = _read(d / "glb_state.json").get("updated")
            if upd != today:
                out.append({"check": "glb_state", "message": f"GLB скрийнърът мина, но състоянието му (data/glb_state.json) не е записано днес (последно: {_fmt(upd)})."})
        except Exception as e:
            out.append({"check": "glb_state", "message": f"GLB състоянието не се прочете ({type(e).__name__}) — утре хистерезисът започва отначало."})

    try:                                     # 6. таблицата NYSE_HOLIDAYS свършва (последната ѝ година)
        last_year = max(int(h[:4]) for h in config.NYSE_HOLIDAYS)
        left = (dt.date(last_year, 12, 31) - dt.date.fromisoformat(today)).days
        if left < config.NYSE_HOLIDAYS_WARN_DAYS:
            out.append({"check": "holidays", "message": (
                f"NYSE_HOLIDAYS в config.py покрива до {last_year} г. (остават {max(left, 0)} дни) — добави празниците за {last_year + 1}, иначе те ще се броят за сесии "
                "(buy-stop прозорец, застояли данни, изтичане на Watchlist).")})
    except Exception as e:
        print(f"[health] NYSE_HOLIDAYS не се провери: {type(e).__name__}: {e}")

    for fname, (flag, name) in DAILY_CACHES.items():
        if not getattr(config, flag, False):
            continue
        try:
            date = _read(d / fname).get("date")
            if date and date < today:
                out.append({"check": "cache", "message": f"кешът за {name} е от {_fmt(date)} — модулът не се е обновил днес (вероятно паднало теглене)."})
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[health] кешът {fname} не се провери: {type(e).__name__}: {e}")
    return out
