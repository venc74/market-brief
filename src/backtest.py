"""
Track Record — проследява какво реално се случва с исторически Action
препоръки след като са дадени. Данните вече се трупат ежедневно в
data/YYYY-MM-DD.json (виж main.py docstring-а) именно за тази цел.

Entry price = средата (midpoint) на plan.entry_range в деня на препоръката.

Двуфазова резолюция (реалната система НЕ затваря позицията на target_1 —
превключва на trailing stop под 10DMA, за да улови допълнителен upside):

  Фаза 1 ("open"): от деня СЛЕД entry-то, следим дневен High/Low спрямо
  target_1/stop_loss.
    - Low <= stop_loss           → терминално "stopped", realized_r = -1.0
    - High >= target_1           → преминаваме във Фаза 2 ("trailing")
    - И двете в един ден (gap)   → "stopped" печели (консервативно допускане)
    - Нищо от горното до config.BACKTEST_MAX_HOLD_WEEKS след entry-то
      → терминално "expired", realized_r = None (неопределен изход, target_1
      никога не е бил стигнат — не участва в win/loss статистиката)

  Фаза 2 ("trailing"): от деня СЛЕД докосването на target_1, следим дневен
  Close спрямо rolling 10-дневна средна (10DMA) на Close.
    - Close < 10DMA за първи път  → терминално "trailing_stop_exit",
      realized_r = (exit_price - entry_price) / (entry_price - stop_loss),
      закръглено до 2 знака (не хардкоднато +2.0 — реалният upside/downside
      след target_1 варира).
    - Ако Фаза 2 продължи отвъд config.BACKTEST_MAX_HOLD_WEEKS (броено от
      ОРИГИНАЛНОТО entry, не от target_1 датата) без Close < 10DMA
      → терминално "expired_in_trail", realized_r по същата формула спрямо
      последната налична Close цена (НЕ null — за разлика от Фаза-1
      "expired", тук вече знаем сделката е била печеливша поне до target_1).

Уникален идентификатор на позиция: (ticker, entry_date) — един тикър,
препоръчан на различни дати, е ОТДЕЛНА позиция, ОСВЕН ако новата дата попада
в ЖИВОТА на вече записана позиция за същия тикър, т.е. в интервала
[entry_date, resolution_date] (или след entry_date, докато е още жива). Нова
позиция се разрешава едва СЛЕД реална резолюция на предходната
(stopped/trailing_stop_exit/expired/expired_in_trail), не по изтичане на
времеви прозорец — иначе screener-ът препоръчва пак същия незатворен
интерес и той се брои като отделна сделка, изкуствено удвоявайки/
утроявайки статистиката (виж _is_continuation).

Персистира се в data/backtest_tracker.json, keyed по "{ticker}_{entry_date}".

Graceful degradation (Секция 7): провал на price fetch за конкретен тикър
→ остава в текущия си статус, опитва пак следващия ден; липсващ/повреден
tracker JSON → започва от празен dict; провал на update_backtest_tracker()
като цяло → старият tracker на диска остава недокоснат (последно успешно
състояние), get_backtest_summary() продължава да го чете нормално.
"""
from __future__ import annotations
import datetime as dt
import json
import re

import pandas as pd
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import net_utils
from src import enrich

_TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
_LIVE_STATUSES = ("open", "trailing")

# FIX 2026-09-17: датата, за която резолюцията вече е минала В ТОЗИ ПРОЦЕС —
# пази от двоен yf.download(), когато resolve_positions_only() е извикан рано
# и update_backtest_tracker() го последва в същия run. Виж resolve_positions_only().
#
# СЪЗНАТЕЛНО in-process, не персистирано във файл: персистиран
# "last_resolved_date" би потискал резолюцията и при РЪЧЕН re-trigger на
# workflow-а същия ден (правено е), т.е. вторият run щеше да показва остаряло
# Track Record състояние — точно дефектът, който този фикс поправя. Флагът
# нарочно живее само колкото процеса.
#
# НЕ се пази в самия tracker dict: get_backtest_summary() прави
# `for r in records: by_status[r.get("status")] += 1` (ред ~425), значи
# мета-запис без "status" би добавил by_status[None] в dashboard брояча.
_RESOLVED_THIS_RUN: str | None = None


# ──────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────
def _load_tracker() -> dict:
    if _TRACKER_PATH.exists():
        try:
            return json.loads(_TRACKER_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[backtest] tracker JSON повреден, започвам от празен: {e}")
    return {}


def _save_tracker(tracker: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    _TRACKER_PATH.write_text(json.dumps(tracker, ensure_ascii=False, indent=1, default=str),
                             encoding="utf-8")


def _snapshot_files() -> list[pathlib.Path]:
    """Само YYYY-MM-DD.json — изключва кеш файлове (cot_cache.json и т.н.)."""
    return sorted(p for p in config.DATA_DIR.glob("*.json") if _SNAPSHOT_RE.match(p.name))


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 1: нови позиции от Action snapshot-ите (с дедупликация)
# ──────────────────────────────────────────────────────────────────────────
def _is_continuation(tracker: dict, ticker: str, entry_date: str) -> bool:
    """
    True ако entry_date попада В ЖИВОТА на вече записана позиция за същия тикър:
    интервалът [entry_date, resolution_date], или [entry_date, ∞) докато е жива.

    FIX 2026-09-18: замества _has_live_position(), който питаше "има ли жива
    позиция СЕГА" — проверка на СЪСТОЯНИЕ, докато обявената семантика (виж
    модулния docstring и FIX 2026-07-09) е ВРЕМЕВА: "нова позиция за същия
    тикър се разрешава едва СЛЕД реална резолюция на предходната".

    Разликата не е козметична. Снимките са постоянни и _ingest_new_positions()
    ги обхожда наново при ВСЕКИ run, а решението за пропускане не се записваше
    никъде. Затова един и същ стар запис се пре-разглеждаше всеки ден срещу
    различно състояние — и в мига, в който блокиращата позиция резолвираше,
    отговорът се обръщаше и двумесечна снимка влизаше като "нова сделка".

    Потвърдени случаи, всичките с тикър в Action списъка два поредни дни:
      ADI_2026-06-19, CAT_2026-06-19 (появил се 21.07), ROK_2026-06-19
      (24.08), TRV_2026-07-03 (03.08, 4 дни след като TRV_2026-06-29
      резолвира), FITB_2026-07-21 (18.09, ден след като FITB_2026-07-20
      резолвира). Трите резолвирани фантома вече бяха преброени в
      статистиката като реални загуби (-1.0R всеки, 3 от 24 резолюции).

    Механизмът беше ЗАБЕЛЯЗАН на 02.08 (виж _resolve_position docstring-а,
    CAT_2026-06-19 е разгледан поименно), но мис-класифициран като timing/
    reporting особеност — решението тогава беше `discovered_date`, за да не
    изчезва от седмичния изглед. Въпросът дали записът изобщо е трябвало да
    бъде ingest-нат не беше зададен.

    Отворена позиция дава end=None → блокира всичко след себе си, т.е.
    предишното поведение е запазено точно. Новото е, че отговорът вече не
    зависи от МОМЕНТА на оценяване.

    Съзнателно позволено: ако блокираща позиция резолвира с дата ПРЕДИ датата
    на кандидата (късно открита резолюция — виж `discovered_date`), кандидатът
    става легитимен нов вход. Това е правилно — първата сделка реално е
    приключила преди втория вход.
    """
    for rec in tracker.values():
        if rec.get("ticker") != ticker:
            continue
        start = rec.get("entry_date")
        if not start or start > entry_date:
            continue
        end = rec.get("resolution_date")
        if end is None or entry_date <= end:
            return True
    return False


def _ingest_action_list(tracker: dict, entry_date: str, action_list: list[dict]) -> None:
    """Ingest-ва ЕДИН ден's Action списък (от snapshot файл ИЛИ директно in-memory) в tracker-а."""
    for c in action_list or []:
        ticker = c.get("ticker")
        plan = c.get("plan") or {}
        entry_range = plan.get("entry_range")
        target_1 = plan.get("target_1")
        stop_loss = plan.get("stop_loss")
        if not (ticker and entry_range and len(entry_range) == 2
               and target_1 is not None and stop_loss is not None):
            continue

        key = f"{ticker}_{entry_date}"
        if key in tracker:
            continue
        if _is_continuation(tracker, ticker, entry_date):
            continue  # продължение на съществуваща позиция, не нова сделка

        tracker[key] = {
            "ticker": ticker,
            "entry_date": entry_date,
            "status": "open",
            "entry_price": round((entry_range[0] + entry_range[1]) / 2, 2),
            "target_1": target_1,
            "stop_loss": stop_loss,
            "target1_hit_date": None,
            "resolution_date": None,
            "discovered_date": None,
            "realized_r": None,
        }


def _ingest_new_positions(tracker: dict, today_action: list[dict] | None = None,
                          today_date: str | None = None) -> None:
    for path in _snapshot_files():
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[backtest] snapshot {path.name} нечетим, пропускам: {e}")
            continue
        entry_date = snap.get("date") or path.stem
        _ingest_action_list(tracker, entry_date, snap.get("action", []))

    # FIX 2026-08-01 (ден+1 overlap бъг — FITB/JPM/HWM): main.py вика
    # apply_hard_rules() (→ _live_positions() → чете tracker-а) ПРЕДИ
    # update_backtest_tracker() в СЪЩИЯ run, а файловият ingest по-горе не вижда
    # днешния snapshot — той се пише СЛЕД тази функция, по-късно в същия run.
    # Резултат: тикър, избран за Action днес, оставаше невидим за
    # _live_positions() цял допълнителен run (утрешния), позволявайки дублиран
    # Action избор точно "ден+1" (виж FIXES файла за трите потвърдени случая).
    # Директно ingest-ване на днешния in-memory action списък тук елиминира
    # закъснението — утрешният run вече ще завари тикъра в tracker-а.
    if today_action and today_date:
        _ingest_action_list(tracker, today_date, today_action)


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 2: резолюция на живите позиции (batch price fetch, двуфазово)
# ──────────────────────────────────────────────────────────────────────────
def _resolve_position(rec: dict, h: "pd.Series", l: "pd.Series", c: "pd.Series",
                      today: dt.date) -> None:
    """
    Мутира rec на място. Фаза 1 → евентуален преход във Фаза 2 в СЪЩИЯ проход.

    FIX 2026-08-02 (точки 6/7/10 — общ корен): `resolution_date` е историческата
    дата по цените (кога РЕАЛНО е ударен stop/target), но `_ingest_new_positions`
    може да ingest-не позиция със СЕДМИЦИ закъснение — ако друга жива позиция за
    същия тикър я е блокирала (_is_continuation), тя стои неingest-ната, докато
    по-старата не резолвира. Веднъж отблокирана, тя може да резолвира В СЪЩИЯ run,
    с resolution_date дълбоко назад, без никога да се е показвала "open" в бриф.
    Потвърдено на CAT_2026-06-19: entry 19.06, resolved (по цени) 17.07, но
    реално ingest-ната и резолвирана едва на 21.07 run-а — total_resolved скочи
    незабелязано, а "Резолюции тази седмица" (keyed по resolution_date) не я
    показа, защото 17.07 е в предишна ISO седмица спрямо 21.07. `discovered_date`
    записва КОГА pipeline-ът реално я е засякъл (= "today" на този run) —
    отделно от resolution_date, за да "Резолюции тази седмица" да отразява
    реално откритото тази седмица, не историческата дата на пазарното събитие.

    ВАЖНО за горния пример (добавено 2026-09-18): CAT_2026-06-19 всъщност НЕ е
    трябвало да бъде ingest-ната изобщо — 19.06 попада в живота на
    CAT_2026-06-18 [18.06 .. 17.07], т.е. е продължение на същата позиция, не
    отделна сделка. През 08/2026 това беше диагностицирано само като timing/
    reporting проблем (оттам `discovered_date`), а въпросът дали записът е
    валиден не беше зададен; фантомът остана в статистиката като реална -1.0R
    загуба. _is_continuation() вече го блокира — виж нейния docstring.
    `discovered_date` остава нужен: ЛЕГИТИМЕН нов вход (след като предходната
    позиция реално е приключила) все още може да се ingest-не със закъснение.
    """
    if rec["status"] == "open":
        entry_dt = pd.Timestamp(rec["entry_date"])
        h1, l1 = h[h.index > entry_dt], l[l.index > entry_dt]

        hit_target1 = False
        for day in h1.index:
            if day not in l1.index:
                continue
            if bool(l1.loc[day] <= rec["stop_loss"]):   # gap ден — stop печели консервативно
                rec["status"] = "stopped"
                rec["resolution_date"] = day.date().isoformat()
                rec["discovered_date"] = today.isoformat()
                rec["realized_r"] = -1.0
                return
            if bool(h1.loc[day] >= rec["target_1"]):
                rec["status"] = "trailing"
                rec["target1_hit_date"] = day.date().isoformat()
                hit_target1 = True
                break

        if not hit_target1:
            entry_cutoff = entry_dt.date() + dt.timedelta(weeks=config.BACKTEST_MAX_HOLD_WEEKS)
            if today >= entry_cutoff:
                rec["status"] = "expired"
                rec["resolution_date"] = entry_cutoff.isoformat()
                rec["discovered_date"] = today.isoformat()
                rec["realized_r"] = None
            return

    if rec["status"] == "trailing":
        entry_price = rec["entry_price"]
        original_stop = rec["stop_loss"]
        target1_dt = pd.Timestamp(rec["target1_hit_date"])
        dma10 = c.rolling(10).mean()
        after = c[c.index > target1_dt]

        for day in after.index:
            avg = dma10.loc[day] if day in dma10.index else float("nan")
            if avg != avg:            # NaN guard без нужда от отделен math/numpy импорт
                continue
            close_val = float(c.loc[day])
            if close_val < avg:
                rec["status"] = "trailing_stop_exit"
                rec["resolution_date"] = day.date().isoformat()
                rec["discovered_date"] = today.isoformat()
                rec["realized_r"] = round((close_val - entry_price) / (entry_price - original_stop), 2)
                return

        entry_dt = pd.Timestamp(rec["entry_date"])
        entry_cutoff = entry_dt.date() + dt.timedelta(weeks=config.BACKTEST_MAX_HOLD_WEEKS)
        # FIX 2026-09-23: последният ВАЛИДЕН Close, не .iloc[-1] на суровата
        # серия. Единственият call site вече подава closes.dropna(), така че
        # в текущия път NaN не може да стигне дотук — това е защита в
        # дълбочина, за да не зависи коректността на функцията от извикващия.
        # Контекст: на 23.09 Yahoo върна частичен бар (Close = NaN).
        valid = c.dropna()
        if today >= entry_cutoff and len(valid):
            last_close = float(valid.iloc[-1])
            rec["status"] = "expired_in_trail"
            rec["resolution_date"] = entry_cutoff.isoformat()
            rec["discovered_date"] = today.isoformat()
            rec["realized_r"] = round((last_close - entry_price) / (entry_price - original_stop), 2)


def _unapplied_splits(rec: dict) -> list[dict] | None:
    """
    FIX 2026-09-23: ВСИЧКИ сплитове след entry, които още НЕ са приложени към
    този запис. `None` при провал на fetch-а (различимо от "няма сплитове" = []).
    Замества _split_since_entry (FIX 2026-08-11), който връщаше само първия
    сплит и водеше до замразяване без срок.

    Историята (от FIX 2026-08-11): yfinance ретроактивно split-коригира ЦЯЛАТА
    историческа OHLC серия при всяко теглене, независимо от auto_adjust
    (потвърдено емпирично), докато stop_loss/target_1/entry_price остават в
    ценовата скала от момента на entry-то. Сравнение на замразен стоп срещу
    прещъртани цени дава фалшива резолюция — потвърден случай MNST_2026-07-02,
    2:1 сплит на 11.08.2026, фалшив "stopped" 4 дни след entry.

    Филтрирането по вече приложените е задължително: сплитът остава "след entry"
    завинаги, така че без него вторият run би разделил entry-то на коефициента
    втори път.
    """
    try:
        splits = net_utils.fetch_with_timeout(lambda: yf.Ticker(rec["ticker"]).splits)
    except Exception as e:
        print(f"[backtest] split check {rec['ticker']}: {e}")
        return None
    if splits is None:
        return None
    if splits.empty:
        return []
    entry_ts = pd.Timestamp(rec["entry_date"])
    if entry_ts.tzinfo is None and splits.index.tz is not None:
        entry_ts = entry_ts.tz_localize(splits.index.tz)
    applied = {s["date"] for s in (rec.get("split_adjusted") or {}).get("splits", [])}
    return [{"date": d.date().isoformat(), "ratio": float(r)}
            for d, r in splits[splits.index > entry_ts].items()
            if d.date().isoformat() not in applied and float(r) > 0]


def _apply_split_adjustment(rec: dict, splits: list[dict], closes: "pd.Series",
                            today: dt.date) -> bool:
    """
    FIX 2026-09-23: вместо да замразява позицията завинаги, коригира entry /
    stop / target по кумулативния коефициент на сплитовете. True → записът е
    коригиран и може да се резолвира нормално; False → остава във флаг.

    Защо корекцията е вярна: yfinance split-коригира ЦЯЛАТА историческа OHLC
    серия ретроактивно (потвърдено 11.08, виж _unapplied_splits), така че
    всички барове вече са в новата скала — замразените нива просто трябва да
    се преместят в нея.

    Санитарна проверка, преди да се приложи: коригираният entry се сравнява със
    split-коригирания Close на entry деня. Минава само ако (а) е в границата
    config.SPLIT_SANITY_MAX_DEV И (б) е по-близо от НЕкоригирания. (б) пази
    сляпото място на (а): за малки коефициенти (напр. 1.05 — stock dividend,
    който Yahoo записва като сплит) и двата варианта попадат в 15%, и само
    сравнението между тях показва коя скала е историята. Ако проверката падне
    — историята още не е коригирана и корекцията би била грешна; записът
    остава флагнат и се преразглежда при всеки следващ run.

    Оригиналните стойности се пазят в split_adjusted.original (само веднъж —
    при първата корекция) за одит.
    """
    ratio = 1.0
    for s in splits:
        ratio *= s["ratio"]
    entry = rec["entry_price"]
    hist = closes[closes.index >= pd.Timestamp(rec["entry_date"])]
    prev_flag = rec.get("needs_manual_review") or {}
    since = prev_flag.get("since") or prev_flag.get("split_date") or today.isoformat()

    def flag(reason: str, sanity: dict | None = None) -> bool:
        rec["needs_manual_review"] = {
            "reason": reason, "split_date": splits[0]["date"], "split_ratio": ratio,
            "since": since, **({"sanity": sanity} if sanity else {}),
        }
        print(f"[backtest] {rec['ticker']}: split {ratio:g}:1 — корекцията НЕ е приложена "
              f"({reason}), остава needs_manual_review от {since}")
        return False

    if hist.empty:
        return flag("no_history_at_entry")
    hist_close = float(hist.iloc[0])
    adj = entry / ratio
    dev_adj = abs(adj - hist_close) / hist_close
    dev_raw = abs(entry - hist_close) / hist_close
    sanity = {"hist_close": round(hist_close, 4), "dev_adjusted": round(dev_adj, 4),
              "dev_unadjusted": round(dev_raw, 4)}
    if not (dev_adj <= config.SPLIT_SANITY_MAX_DEV and dev_adj < dev_raw):
        return flag("split_sanity_failed", sanity)

    sa = rec.setdefault("split_adjusted", {
        "original": {"entry_price": entry, "stop_loss": rec["stop_loss"],
                     "target_1": rec["target_1"]},
        "splits": [],
    })
    sa["splits"] += [{**s, "applied_on": today.isoformat()} for s in splits]
    sa["sanity"] = sanity
    rec["entry_price"] = round(entry / ratio, 4)
    rec["stop_loss"] = round(rec["stop_loss"] / ratio, 4)
    rec["target_1"] = round(rec["target_1"] / ratio, 4)
    rec.pop("needs_manual_review", None)
    print(f"[backtest] {rec['ticker']}: split {ratio:g}:1 — коригирано автоматично "
          f"(entry {entry} → {rec['entry_price']}, разлика спрямо историята "
          f"{dev_adj * 100:.1f}% при {dev_raw * 100:.1f}% некоригирано)")
    return True


def _normalize_price_columns(data: "pd.DataFrame", tickers: list[str],
                             fields: tuple[str, ...]) -> dict[str, "pd.DataFrame | None"]:
    """
    yf.download за списък с ЕДИН тикър понякога връща плосък DataFrame
    (директни Open/High/Low/Close колони, без ticker ниво) вместо MultiIndex.
    Опаковаме в единична ticker-именувана колона, за да работи еднакво
    result[field][ticker] надолу по кода, независимо от формата.
    """
    if isinstance(data.columns, pd.MultiIndex):
        return {f: data.get(f) for f in fields}
    only_ticker = tickers[0]
    return {f: (data[[f]].rename(columns={f: only_ticker}) if f in data.columns else None)
           for f in fields}


def _resolve_open_positions(tracker: dict) -> None:
    live_items = [(key, rec) for key, rec in tracker.items() if rec.get("status") in _LIVE_STATUSES]
    if not live_items:
        return

    tickers = sorted({rec["ticker"] for _, rec in live_items})
    earliest = min(rec["entry_date"] for _, rec in live_items)
    try:
        data = yf.download(tickers, start=earliest, progress=False, auto_adjust=False)
    except Exception as e:
        print(f"[backtest] batch price fetch failed за {tickers}: {e}")
        return
    if data is None or data.empty:
        print("[backtest] price fetch върна празен резултат")
        return

    cols = _normalize_price_columns(data, tickers, ("High", "Low", "Close"))
    highs, lows, closes = cols.get("High"), cols.get("Low"), cols.get("Close")
    if highs is None or lows is None or closes is None:
        print("[backtest] price fetch не върна High/Low/Close колони")
        return

    today = dt.date.today()
    for _, rec in live_items:
        ticker = rec["ticker"]
        if ticker not in getattr(highs, "columns", []):
            print(f"[backtest] {ticker}: няма данни в batch резултата — пропускам (остава {rec['status']})")
            continue
        # FIX 2026-09-23: сплит → автоматична корекция със санитарна проверка,
        # вместо замразяване завинаги (виж _apply_split_adjustment). Дотук
        # флагнат запис се прескачаше при всеки run без срок и без напомняне —
        # MNST стоя 43 дни "отворена", макар да е пробила коригирания си стоп
        # на 09.09. Флагнатите записи вече се преразглеждат всеки run.
        new_splits = _unapplied_splits(rec)
        if new_splits is None:
            # Провал на split fetch-а. Флагнат запис остава флагнат (не бива
            # транзиентна мрежова грешка да го плъзне в резолюция в грешна
            # скала); нефлагнат продължава нормално, както и преди.
            if rec.get("needs_manual_review"):
                continue
        elif new_splits:
            if not _apply_split_adjustment(rec, new_splits, closes[ticker].dropna(), today):
                continue
        elif rec.get("needs_manual_review"):
            continue  # флаг без видим неприложен сплит — консервативно остава
        # FIX 2026-09-23: `discovered_date` се слага при резолюцията както винаги
        # — корекция днес + стоп в миналото = late_discovery в брифа (MNST).
        try:
            _resolve_position(rec, highs[ticker].dropna(), lows[ticker].dropna(),
                              closes[ticker].dropna(), today)
        except Exception as e:
            print(f"[backtest] {ticker}: резолюция неуспешна, остава {rec['status']}: {e}")
            continue


def _fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """
    Batch fetch на последната налична Close цена за списък тикъри (за
    unrealized % на отворените позиции). Graceful: провал на целия fetch
    или на конкретен тикър → просто липсва в резултата, не гърми.
    """
    if not tickers:
        return {}
    try:
        data = yf.download(tickers, period="5d", progress=False, auto_adjust=False)
    except Exception as e:
        print(f"[backtest] current price fetch failed за {tickers}: {e}")
        return {}
    if data is None or data.empty:
        return {}

    closes = _normalize_price_columns(data, tickers, ("Close",)).get("Close")
    if closes is None:
        return {}

    out: dict[str, float] = {}
    for t in tickers:
        if t not in getattr(closes, "columns", []):
            continue
        series = closes[t].dropna()
        if len(series):
            out[t] = float(series.iloc[-1])
    return out


# ──────────────────────────────────────────────────────────────────────────
# Публично API
# ──────────────────────────────────────────────────────────────────────────
def resolve_positions_only() -> None:
    """
    FIX 2026-09-17: САМО резолюция на живите позиции, без ingest — за да може
    да се извика РАНО в pipeline-а, преди каквото и да било да чете статусите.

    Потвърденият случай (17.09.2026): Track Record показа FITB и ONB като
    "stopped" на 16.09, докато COT секцията в СЪЩИЯ бриф ги описваше като
    "вече отворени позиции" (E-mini Russell 2000 и 2-Year Treasury тезите),
    с цитирани точни entry дати. Tracker-ът на диска сутринта наистина казваше
    "open" — стопът е настъпил по цените от 16.09, но е бил открит едва в
    днешния run (`late_discovery: true` в самите записи). UMBF, в същата теза
    и нерезолвиран днес, беше реферирана коректно — контролът, който показва,
    че проблемът е специфично при same-day резолюции.

    Причината беше чист ordering gap: COT контекстът се сглобяваше на main.py
    ред ~172 от _live_positions() (чете tracker-а ОТ ДИСКА), а резолюцията се
    случваше едва на ред ~273 в update_backtest_tracker(). 101 реда разлика,
    две секции в един бриф четат едно поле в две различни състояния.

    Разделянето е възможно, защото _resolve_open_positions() приема само
    tracker — не чете `action`. Свързаността с _ingest_new_positions() (който
    ИЗИСКВА `action`, наличен чак след apply_hard_rules()) беше по конвенция,
    не техническа.

    Мрежова цена: нула допълнителна. _RESOLVED_THIS_RUN гарантира, че
    update_backtest_tracker() по-късно не прави втори yf.download().

    ИЗВЪН ОБХВАТА, съзнателно: main.apply_hard_rules() (ред ~62) чете същия
    snapshot през свой собствен _live_positions() и след този фикс ще вижда
    вече резолвиран tracker — т.е. FITB/ONB биха могли да получат нов Action
    план вместо Watchlist с OPEN✓. Това е поправка, но и промяна в sizing
    поведението, която заслужава собствено обсъждане. Записана е като ОТДЕЛНА
    находка за следваща сесия; не се третира тук.

    Graceful: провал → tracker-ът на диска остава последното успешно състояние.
    """
    global _RESOLVED_THIS_RUN
    today = dt.date.today().isoformat()
    if _RESOLVED_THIS_RUN == today:
        return
    tracker = _load_tracker()
    try:
        _resolve_open_positions(tracker)
        _save_tracker(tracker)
        _RESOLVED_THIS_RUN = today
        live = sum(1 for r in tracker.values() if r.get("status") in _LIVE_STATUSES)
        print(f"[backtest] ранна резолюция готова — {live} живи позиции остават")
    except Exception as e:
        print(f"[backtest] resolve_positions_only failed: {e}")


def update_backtest_tracker(today_action: list[dict] | None = None,
                            today_date: str | None = None) -> None:
    """
    Ingest на нови Action позиции (с дедупликация) + резолюция на живите.
    Провал някъде в средата → tracker-ът на диска остава последното успешно
    записано състояние (не презаписваме частично/счупено).

    today_action/today_date: днешният in-memory Action списък (main.py) —
    ingest-ва се директно, БЕЗ да чака утрешното файлово четене на
    data/{today}.json (виж FIX 2026-08-01 в _ingest_new_positions).
    """
    tracker = _load_tracker()
    try:
        _ingest_new_positions(tracker, today_action, today_date)
        # FIX 2026-09-17: ако resolve_positions_only() вече е минал в този run,
        # не плащаме втори yf.download(). Днес ingest-натите позиции остават
        # нерезолвирани до утрешния run — доказуемо безвредно: позиция, влязла
        # днес, не може да е стопната по вчерашни дневни барове.
        if _RESOLVED_THIS_RUN == dt.date.today().isoformat():
            print("[backtest] резолюцията вече мина по-рано в този run — "
                  "пропускам втория price fetch")
        else:
            _resolve_open_positions(tracker)
        _save_tracker(tracker)
    except Exception as e:
        print(f"[backtest] update_backtest_tracker failed: {e}")


def _is_late_discovery(rec: dict) -> bool:
    """
    FIX 2026-09-25: резолюцията е открита ПО-КЪСНО от първия възможен run.

    Дотук беше `discovered_date != resolution_date` — и беше вярно за ВСЯКА
    резолюция. Брифът е в 05:30 UTC, преди US отваряне, затова пазарно събитие
    от ден D най-рано се вижда в run-а на следващия работен ден (потвърдено:
    0 от 14 резолюции с discovered == resolution). Измерено в историята на
    "Резолюции тази седмица": 17 True, 6 без поле, нула False — маркерът
    "открито със закъснение" стоеше на всичко и не казваше нищо.

    Сега закъснение = открито СЛЕД първия работен ден след събитието. Това
    покрива и изтичане, паднало в уикенд (срок събота 03.10 → първи run
    понеделник 05.10 → навреме), и нормален стоп (петък → понеделник, вторник →
    сряда — навреме). Реални закъснения остават маркирани — напр. MNST (стоп
    09.09, открит след split корекцията на 24.09) или пропуснат run.
    """
    disc, res = rec.get("discovered_date"), rec.get("resolution_date")
    if not disc or not res:
        return False
    try:
        d = dt.date.fromisoformat(res) + dt.timedelta(days=1)
        while d.weekday() >= 5:          # събота/неделя → следващият понеделник
            d += dt.timedelta(days=1)
        return dt.date.fromisoformat(disc) > d
    except ValueError:
        return False


def get_backtest_summary() -> dict:
    """
    Обобщение за dashboard-а. "Win" = всякакъв терминален изход с
    realized_r > 0 (не само чист target_hit — trailing_stop_exit и
    expired_in_trail може да имат частичен положителен R). Празен/повреден
    tracker → нулеви стойности, никога грешка.

    Забележка: прави batch мрежова заявка (текущи цени за отворените
    позиции, за "open_positions"/unrealized %) — не е чисто локално четене
    от диска както преди. Провал на тази заявка е graceful (виж
    _fetch_current_prices) — не чупи останалата част на summary-то.
    """
    tracker = _load_tracker()
    records = list(tracker.values())

    resolved = [r for r in records if r.get("realized_r") is not None]
    total_resolved = len(resolved)
    wins = [r for r in resolved if r["realized_r"] > 0]
    losses = [r for r in resolved if r["realized_r"] <= 0]
    win_rate = round(len(wins) / total_resolved * 100, 1) if total_resolved else 0.0
    avg_r = round(sum(r["realized_r"] for r in resolved) / total_resolved, 2) if total_resolved else 0.0

    by_status = {}
    for r in records:
        by_status[r.get("status")] = by_status.get(r.get("status"), 0) + 1

    # "recent" = само тази ISO седмица (пон-нед) — иначе стара резолюция може
    # да "залепне" в топ-10 с дни наред, ако няма нови след нея. Кумулативната
    # статистика по-горе (total_resolved/win_rate/avg_r/by_status) НЕ се
    # ресетва седмично — трупа се от началото на tracking-а.
    # FIX 2026-08-02 (точки 6/7/10): ключуване по resolution_date (историческа
    # дата по цените) пропускаше late-ingested резолюции — виж коментара в
    # _resolve_position за пълния механизъм (потвърдено на CAT_2026-06-19).
    # discovered_date (кога pipeline-ът РЕАЛНО е засякъл резолюцията) е
    # правилният сигнал за "тази седмица"; fallback към resolution_date за
    # записи отпреди този фикс (нямат новото поле — graceful, без миграция).
    today = dt.date.today()
    monday_this_week = (today - dt.timedelta(days=today.weekday())).isoformat()

    def _effective_date(r: dict) -> str:
        return r.get("discovered_date") or r["resolution_date"]

    recent_pool = [r for r in records
                  if r.get("status") not in _LIVE_STATUSES and r.get("resolution_date")
                  and _effective_date(r) >= monday_this_week]
    recent_pool.sort(key=_effective_date, reverse=True)
    recent = [{"ticker": r["ticker"], "entry_date": r["entry_date"], "resolution": r["status"],
              "resolution_date": r["resolution_date"], "realized_r": r.get("realized_r"),
              # закъсняла резолюция (ingest-ната седмици след реалната пазарна дата) —
              # dashboard-ът може да го отбележи, вместо да изглежда като "прескочен" брояч.
              "late_discovery": _is_late_discovery(r)}
             for r in recent_pool[:20]]  # горен таван само като edge-case защита, не нормално поведение

    # Живи позиции + текуща цена (batch fetch) за unrealized % изгледа в dashboard-а.
    live_records = [r for r in records if r.get("status") in _LIVE_STATUSES]
    open_positions = []
    if live_records:
        tickers = sorted({r["ticker"] for r in live_records})
        prices = _fetch_current_prices(tickers)
        for r in live_records:
            entry_price = r.get("entry_price")
            cur = prices.get(r["ticker"])
            # FIX 2026-08-10: round(-0.04, 1) == -0.0 в Python — str(-0.0) е "-0.0",
            # а -0.0 >= 0 е True (IEEE 754), затова темплейтният "+" prefix logic
            # ("+" if pct >= 0 else "") произвежда "+-0.0%" (потвърдено живо: ROST
            # на 10.08.2026, unrealized_pct=-0.0 в реалния persisted JSON). "+ 0.0"
            # нормализира -0.0 → 0.0 на източника, не само козметично в темплейта.
            # FIX 2026-08-11: needs_manual_review означава entry_price е замразен
            # в предишна ценова скала (split-artifact, виж _unapplied_splits) —
            # unrealized_pct спрямо текущата (нова-скала) цена би бил също толкова
            # подвеждащ, колкото самата автоматична резолюция, която този флаг
            # съществува да предотврати. Потискаме изчислението, не само текста.
            needs_review = r.get("needs_manual_review")
            unrealized_pct = (round((cur - entry_price) / entry_price * 100, 1) + 0.0
                              if (cur is not None and entry_price and not needs_review) else None)
            # FIX 2026-09-23: видим брояч за всичко, което остане във флаг —
            # дотук флагът нямаше нито срок, нито напомняне. Стари флагове без
            # `since` броят от датата на сплита.
            if needs_review:
                since = needs_review.get("since") or needs_review.get("split_date")
                try:
                    needs_review = {**needs_review, "frozen_days":
                                    (today - dt.date.fromisoformat(since)).days}
                except (TypeError, ValueError):
                    pass
            open_positions.append({
                "ticker": r["ticker"],
                "entry_date": r["entry_date"],
                "entry_price": entry_price,
                "current_price": round(cur, 2) if cur is not None else None,
                "unrealized_pct": unrealized_pct,
                "needs_manual_review": needs_review,
                # FIX 2026-08-13: entry_date филтърът е премахнат — единен
                # recency праг за Case 1 И Case 2 (виж enrich.earnings_recap
                # docstring-а, дискусията 2026-08-13).
                "earnings_recap": enrich.earnings_recap(r["ticker"]),
            })
        open_positions.sort(key=lambda r: r["entry_date"])  # възходящо — най-старите първи

    return {
        "total_resolved": total_resolved,
        "win_rate_pct": win_rate,
        "wins": len(wins),
        "losses": len(losses),
        "stopped": by_status.get("stopped", 0),
        "trailing_stop_exit": by_status.get("trailing_stop_exit", 0),
        "expired_in_trail": by_status.get("expired_in_trail", 0),
        "expired": by_status.get("expired", 0),
        "still_open": by_status.get("open", 0),
        "trailing": by_status.get("trailing", 0),
        "avg_realized_r": avg_r,
        "recent": recent,
        "open_positions": open_positions,
    }


if __name__ == "__main__":
    update_backtest_tracker()
    summary = get_backtest_summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
