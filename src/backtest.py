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

Track Record v2 (пакет 1, 2026-10-03): плановете с method == "v2" не влизат с
"entry = средата на entry_range", а като buy-stop на pivot (виж trade_sim.py):
статус "pending" до първата сесия с High >= pivot в прозорец от 5 сесии (вкл. деня на
брифа), вход по max(Open, pivot); иначе "not_triggered" (извън статистиката).
Състоянието се преизчислява БЕЗ памет от сигнала при всеки run (чиста функция на
плана и дневните барове) — затова не зависи от пропуснати run-ове. v1 записите
(без "method") се резолвират както досега.

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
from src import trade_sim

_TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
_LIVE_STATUSES = ("open", "trailing")
# Пакет 1б (05.10): втора, НЕЗАВИСИМА книга в същия tracker — Watchlist buy-stop кандидатите ("buystop"). Запис без "category" е Action
# (всичко, записано до пакет 1б). Всеки четец на позиции (OPEN✓, RE-ENTRY, COT, обобщението на Action) гледа само is_action_record().
CATEGORY_ACTION, CATEGORY_BUYSTOP = "action", "buystop"
# v2: "pending" още няма позиция (чака buy-stop), но трябва да се резолвира всеки run
_RESOLVABLE_STATUSES = _LIVE_STATUSES + ("pending",)

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


def _state_path() -> pathlib.Path:
    return config.DATA_DIR / "track_record_state.json"


def load_state() -> dict:
    """
    Състоянието на Track Record методологията (виж tracker_switch.py). Липсващ/повреден
    файл → {} (методология v1, т.е. още не е превключено). Път от config.DATA_DIR при всяко
    извикване, не при импорт.
    """
    p = _state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[backtest] state JSON повреден, считам методология v1: {e}")
    return {}


def methodology() -> str:
    return "v2" if load_state().get("methodology") == "v2" else "v1"


def record_category(rec: dict) -> str:
    return rec.get("category") or CATEGORY_ACTION


def is_action_record(rec: dict) -> bool:
    """Запис от Action книгата (без "category" или "action"). Buy-stop кандидатите НЕ са позиции — не се чете като такива никъде."""
    return record_category(rec) == CATEGORY_ACTION


def _snapshot_files() -> list[pathlib.Path]:
    """Само YYYY-MM-DD.json — изключва кеш файлове (cot_cache.json и т.н.)."""
    return sorted(p for p in config.DATA_DIR.glob("*.json") if _SNAPSHOT_RE.match(p.name))


# ──────────────────────────────────────────────────────────────────────────
# Стъпка 1: нови позиции от Action snapshot-ите (с дедупликация)
# ──────────────────────────────────────────────────────────────────────────
def _is_continuation(tracker: dict, ticker: str, entry_date: str, category: str = CATEGORY_ACTION) -> bool:
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
        if record_category(rec) != category:     # пакет 1б: книгите са независими — buy-stop запис не блокира Action и обратно
            continue
        start = rec.get("entry_date")
        if not start or start > entry_date:
            continue
        end = rec.get("resolution_date")
        if end is None or entry_date <= end:
            return True
    return False


_V2_PLAN_KEYS = ("buy_stop", "max_chase", "stop_loss", "target_1", "entry_mid")


def _new_v2_record(ticker: str, entry_date: str, plan: dict) -> dict:
    """
    v2 запис: entry_date = датата на брифа (препоръката); реалният вход е fill_date /
    fill_price (след buy-stop). entry_price = планиращият вход (сигналният close) до
    входа, после реалната цена на входа — така старите потребители на полето (таблицата
    с отворени позиции, OPEN✓ текстът) показват реалното.
    """
    return {
        "method": "v2", "ticker": ticker, "entry_date": entry_date, "status": "pending",
        "signal_price": plan["entry_mid"], "entry_price": plan["entry_mid"],
        "buy_stop": plan["buy_stop"], "max_chase": plan["max_chase"],
        "stop_loss": plan["stop_loss"], "target_1": plan["target_1"],
        "window_sessions": plan.get("window_sessions") or config.BUY_STOP_WINDOW_SESSIONS,
        "valid_through": plan.get("valid_through"),
        "fill_date": None, "fill_price": None, "risk_per_share": None,
        "target1_hit_date": None, "partial_price": None, "partial_fraction": 0.0,
        "exit_date": None, "exit_price": None,
        "resolution_date": None, "discovered_date": None,
        "realized_r": None, "current_r": None,
        # т.8: доходност върху входа (с частичната продажба) и на SPY за същите периоди
        "return_pct": None, "spy_return_pct": None, "alpha_pct": None,
    }


def _ingest_action_list(tracker: dict, entry_date: str, action_list: list[dict]) -> None:
    """Ingest-ва ЕДИН ден's Action списък (от snapshot файл ИЛИ директно in-memory) в tracker-а."""
    for c in action_list or []:
        ticker = c.get("ticker")
        plan = c.get("plan") or {}
        if plan.get("method") == "v2":                    # пакет 1, т.2: buy-stop запис
            if not (ticker and all(plan.get(k) is not None for k in _V2_PLAN_KEYS)):
                continue
            key = f"{ticker}_{entry_date}"
            if key in tracker or _is_continuation(tracker, ticker, entry_date):
                continue
            tracker[key] = _new_v2_record(ticker, entry_date, plan)
            continue
        if methodology() == "v2":
            # стар (v1) план от архивните snapshot-и (data/YYYY-MM-DD.json се четат наново
            # при всеки run): след чистия старт НЕ влиза в Track Record-а — иначе всичките
            # ~50 исторически позиции щяха да се върнат като нови v1 записи
            continue
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


def _ingest_buystop_list(tracker: dict, entry_date: str, watchlist: list[dict], regime: str | None = None) -> None:
    """
    Пакет 1б: ingest-ва Watchlist картите с buy-stop (setup.kind == "below_pivot", валиден plan_preview) като категория "buystop" —
    ЕДИН запис на (тикър, ден на брифа), със същата v2 форма като Action (плановите ключове идват от plan_preview, т.е. са същите
    стоп/цел, които картата показва). Дедупът е в рамките на категорията (_is_continuation с category): картата, която стои във
    Watchlist няколко дни с едно и също ниво, е ЕДИН запис, докато не се резолвира; след резолюция/изтекъл прозорец е нов. Записва се
    във всички режими (Cash/Defensive/Offensive) — режимът е само таг ("regime"). Карта без валиден план се пропуска (graceful).
    """
    if not config.TRACK_BUYSTOP:
        return
    for c in watchlist or []:
        ticker = c.get("ticker")
        setup = c.get("setup") or {}
        plan = c.get("plan_preview") or {}
        if not (ticker and setup.get("kind") == "below_pivot" and setup.get("buy_stop")
                and plan.get("valid") and plan.get("method") == "v2"
                and all(plan.get(k) is not None for k in _V2_PLAN_KEYS)):
            continue
        key = f"{ticker}_{entry_date}_{CATEGORY_BUYSTOP}"
        if key in tracker or _is_continuation(tracker, ticker, entry_date, CATEGORY_BUYSTOP):
            continue
        rec = _new_v2_record(ticker, entry_date, plan)
        rec.update({"category": CATEGORY_BUYSTOP, "regime": regime, "pct_from_pivot": setup.get("pct_from_pivot")})
        tracker[key] = rec


def _ingest_new_positions(tracker: dict, today_action: list[dict] | None = None,
                          today_date: str | None = None, today_watchlist: list[dict] | None = None,
                          today_regime: str | None = None) -> None:
    for path in _snapshot_files():
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[backtest] snapshot {path.name} нечетим, пропускам: {e}")
            continue
        entry_date = snap.get("date") or path.stem
        _ingest_action_list(tracker, entry_date, snap.get("action", []))
        # пакет 1б: Watchlist картите със заснет plan_preview (по-старите snapshot-и нямат такъв → не влизат); чисто временно правило —
        # същият резултат без значение кога се оценява (резолюцията е функция на плана и баровете), както при Action
        _ingest_buystop_list(tracker, entry_date, snap.get("watchlist", []), (snap.get("thermometer") or {}).get("regime"))

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
    if today_watchlist and today_date:
        _ingest_buystop_list(tracker, today_date, today_watchlist, today_regime)


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


_V2_RESULT_KEYS = ("status", "fill_date", "fill_price", "risk_per_share", "target1_hit_date",
                   "partial_price", "partial_fraction", "exit_date", "exit_price", "realized_r",
                   "current_r", "return_pct", "last_close", "last_close_date")


def _resolve_position_v2(rec: dict, bars: "pd.DataFrame", today: dt.date,
                         spy_bars: "pd.DataFrame | None" = None) -> None:
    """
    v2: преизчислява състоянието от сигнала с trade_sim.simulate() (чиста функция на плана
    и дневните барове) — не наслагва върху старото състояние. Мутира rec на място.
    resolution_date е датата на събитието (изход / последна сесия на прозореца);
    discovered_date — първият run, който го вижда (както във v1).
    """
    res = trade_sim.simulate(rec, bars, today)
    for k in _V2_RESULT_KEYS:
        rec[k] = res.get(k)
    # т.8: SPY за същите периоди (graceful: без SPY барове → None, останалото не се засяга)
    rec["spy_return_pct"] = trade_sim.spy_return_pct(res, spy_bars) if spy_bars is not None else None
    rec["alpha_pct"] = (round(res["return_pct"] - rec["spy_return_pct"], 2)
                        if rec["spy_return_pct"] is not None and res.get("return_pct") is not None else None)
    if res.get("fill_price") is not None:
        rec["entry_price"] = res["fill_price"]
    elif rec.get("signal_price") is not None:
        rec["entry_price"] = rec["signal_price"]
    if res["status"] in trade_sim.LIVE:
        rec["resolution_date"] = None
    else:
        rec["resolution_date"] = res["resolution_date"]
        if not rec.get("discovered_date"):
            rec["discovered_date"] = today.isoformat()


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
    # v2: сигналният бар е ПРЕДИ entry_date, затова сплит с ex-date == entry_date
    # (първата сесия) вече е "след" сигнала; v1 влиза в entry_date и го пропуска
    after = (splits.index >= entry_ts) if rec.get("method") == "v2" else (splits.index > entry_ts)
    return [{"date": d.date().isoformat(), "ratio": float(r)}
            for d, r in splits[after].items()
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


def _apply_split_adjustment_v2(rec: dict, splits: list[dict], closes: "pd.Series",
                               today: dt.date) -> bool:
    """
    v2 обвивка около _apply_split_adjustment(): тя коригира entry_price / stop_loss /
    target_1 (+ санитарната проверка и одита); тук се мащабират и останалите нива на
    плана — buy_stop, max_chase, signal_price. Входът/изходът се преизчисляват от
    сигнала при следващата резолюция, затова fill/exit не се пипат.
    """
    ratio = 1.0
    for s in splits:
        ratio *= s["ratio"]
    before = {k: rec.get(k) for k in ("signal_price", "buy_stop", "max_chase")}
    if not _apply_split_adjustment(rec, splits, closes, today):
        return False
    sa = rec.get("split_adjusted") or {}
    sa.setdefault("original", {}).update({k: v for k, v in before.items() if v is not None})
    for k, v in before.items():
        if v is not None:
            rec[k] = round(v / ratio, 4)
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


def _resolve_open_positions(tracker: dict, today: dt.date | None = None) -> None:
    live_items = [(key, rec) for key, rec in tracker.items() if rec.get("status") in _RESOLVABLE_STATUSES]
    if not live_items:
        return

    tickers = sorted({rec["ticker"] for _, rec in live_items})
    # 30 календарни дни ПРЕДИ най-ранния запис: 10DMA на trailing-а трябва да е пълна от
    # първия ден след входа (v2 симулацията ползва същата серия, както реплеят)
    earliest = (dt.date.fromisoformat(min(rec["entry_date"] for _, rec in live_items))
                - dt.timedelta(days=30)).isoformat()
    # т.8: SPY за сравнението със v2 позициите — във ВСЕКИ случай в същия batch (нула втори fetch)
    dl = tickers + (["SPY"] if "SPY" not in tickers and any(r.get("method") == "v2" for _, r in live_items) else [])
    try:
        data = yf.download(dl, start=earliest, progress=False, auto_adjust=False)
    except Exception as e:
        print(f"[backtest] batch price fetch failed за {tickers}: {e}")
        return
    if data is None or data.empty:
        print("[backtest] price fetch върна празен резултат")
        return

    cols = _normalize_price_columns(data, dl, ("Open", "High", "Low", "Close"))
    opens, highs, lows, closes = cols.get("Open"), cols.get("High"), cols.get("Low"), cols.get("Close")
    if highs is None or lows is None or closes is None:
        print("[backtest] price fetch не върна High/Low/Close колони")
        return
    spy_bars = None
    if "SPY" in dl and opens is not None and "SPY" in getattr(opens, "columns", []):
        spy_bars = pd.DataFrame({"Open": opens["SPY"], "High": highs["SPY"], "Low": lows["SPY"],
                                 "Close": closes["SPY"]}).dropna()

    today = today or dt.date.today()
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
            adjust = _apply_split_adjustment_v2 if rec.get("method") == "v2" else _apply_split_adjustment
            if not adjust(rec, new_splits, closes[ticker].dropna(), today):
                continue
        elif rec.get("needs_manual_review"):
            continue  # флаг без видим неприложен сплит — консервативно остава
        # FIX 2026-09-23: `discovered_date` се слага при резолюцията както винаги
        # — корекция днес + стоп в миналото = late_discovery в брифа (MNST).
        try:
            if rec.get("method") == "v2":
                if opens is None or ticker not in getattr(opens, "columns", []):
                    print(f"[backtest] {ticker}: няма Open в batch резултата — пропускам v2 резолюцията")
                    continue
                bars = pd.DataFrame({"Open": opens[ticker], "High": highs[ticker],
                                     "Low": lows[ticker], "Close": closes[ticker]}).dropna()
                _resolve_position_v2(rec, bars, today, spy_bars)
            else:
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


def _fetch_closes_on_or_before(items: list[tuple[str, str]]) -> dict[tuple[str, str], float]:
    """
    Последният Close на или ПРЕДИ дадена дата — за mark-to-market на изтекли позиции
    (tracker_switch). items = [(тикър, ISO дата)], резултат {(тикър, дата): Close}. Един batch
    за всички. Graceful: провал на fetch-а или липсващ тикър → просто липсва в резултата.
    """
    if not items:
        return {}
    tickers = sorted({t for t, _ in items})
    dates = [dt.date.fromisoformat(d) for _, d in items]
    lo, hi = min(dates) - dt.timedelta(days=10), max(dates) + dt.timedelta(days=1)   # end е изключителен
    try:
        data = yf.download(tickers, start=lo.isoformat(), end=hi.isoformat(), progress=False, auto_adjust=False)
    except Exception as e:
        print(f"[backtest] close-on-date fetch failed за {tickers}: {e}")
        return {}
    if data is None or data.empty:
        return {}
    closes = _normalize_price_columns(data, tickers, ("Close",)).get("Close")
    if closes is None:
        return {}
    out: dict[tuple[str, str], float] = {}
    for t, d in items:
        if t not in getattr(closes, "columns", []):
            continue
        series = closes[t].dropna()
        series = series[series.index <= pd.Timestamp(d)]
        if len(series):
            out[(t, d)] = float(series.iloc[-1])
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
                            today_date: str | None = None, today_watchlist: list[dict] | None = None,
                            today_regime: str | None = None) -> None:
    """
    Ingest на нови Action позиции (с дедупликация) + резолюция на живите.
    Провал някъде в средата → tracker-ът на диска остава последното успешно
    записано състояние (не презаписваме частично/счупено).

    today_action/today_date: днешният in-memory Action списък (main.py) —
    ingest-ва се директно, БЕЗ да чака утрешното файлово четене на
    data/{today}.json (виж FIX 2026-08-01 в _ingest_new_positions).
    today_watchlist/today_regime (пакет 1б): днешният Watchlist и режимът — buy-stop кандидатите се записват като отделна книга.
    """
    tracker = _load_tracker()
    try:
        _ingest_new_positions(tracker, today_action, today_date, today_watchlist, today_regime)
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


def _wilson_ci_pct(wins: int, n: int, z: float = 1.96) -> list[float] | None:
    """95% интервал на Wilson за дял (в %), None без наблюдения."""
    if not n:
        return None
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def get_buystop_summary() -> dict:
    """
    Пакет 1б: обобщение на ОТДЕЛНАТА книга "buystop" (Watchlist buy-stop кандидати) — не е препоръка и не е позиция. Чисто локално четене
    (без мрежа; текущи цени не се теглят). Win rate (с интервал на Wilson), медианата на R, сравнението със SPY и разбивката по режим се
    попълват чак при поне config.BUYSTOP_MIN_CLOSED_FOR_WINRATE ЗАТВОРЕНИ записа (stats_visible); дотогава — само броят и средният R.
    "Не се задействаха" е важна част от картината (кандидат, чиято цена не пробива pivot в прозореца), затова се показва като дял от
    записите с приключил прозорец. Празен/изключен → {} / нулеви стойности, никога грешка.
    """
    if not config.TRACK_BUYSTOP:
        return {}
    records = [r for r in _load_tracker().values() if r.get("method") == "v2" and record_category(r) == CATEGORY_BUYSTOP]
    by_status: dict = {}
    for r in records:
        by_status[r.get("status")] = by_status.get(r.get("status"), 0) + 1
    closed = [r for r in records if r.get("realized_r") is not None]
    triggered = [r for r in records if r.get("fill_date")]
    not_triggered = by_status.get("not_triggered", 0)
    skipped = by_status.get("skipped_extended", 0) + by_status.get("invalid_risk", 0)
    window_done = len(triggered) + not_triggered + skipped
    min_closed = config.BUYSTOP_MIN_CLOSED_FOR_WINRATE
    visible = len(closed) >= min_closed
    rs = sorted(r["realized_r"] for r in closed)
    wins = sum(1 for x in rs if x > 0)

    spy_compare = None
    cmp_recs = [r for r in closed if r.get("return_pct") is not None and r.get("spy_return_pct") is not None]
    if visible and cmp_recs:
        n_c = len(cmp_recs)
        avg_ret = sum(r["return_pct"] for r in cmp_recs) / n_c
        avg_spy = sum(r["spy_return_pct"] for r in cmp_recs) / n_c
        spy_compare = {"n": n_c, "avg_return_pct": round(avg_ret, 2), "avg_spy_pct": round(avg_spy, 2),
                       "avg_alpha_pct": round(avg_ret - avg_spy, 2),
                       "beat_spy_pct": round(sum(1 for r in cmp_recs if r["return_pct"] > r["spy_return_pct"]) / n_c * 100, 1)}

    by_regime: dict = {}
    for r in records:
        g = by_regime.setdefault(r.get("regime") or "н/д", {"records": 0, "closed": 0, "_rs": []})
        g["records"] += 1
        if r.get("realized_r") is not None:
            g["closed"] += 1
            g["_rs"].append(r["realized_r"])
    for g in by_regime.values():
        rs_g = g.pop("_rs")
        g["avg_r"] = round(sum(rs_g) / len(rs_g), 2) if (visible and rs_g) else None

    def _row(r: dict) -> dict:
        return {"ticker": r["ticker"], "entry_date": r["entry_date"], "status": r.get("status"), "buy_stop": r.get("buy_stop"),
                "max_chase": r.get("max_chase"), "stop_loss": r.get("stop_loss"), "target_1": r.get("target_1"),
                "valid_through": r.get("valid_through"), "fill_date": r.get("fill_date"), "fill_price": r.get("fill_price"),
                "current_r": r.get("current_r"), "regime": r.get("regime")}

    live = sorted((_row(r) for r in records if r.get("status") in _RESOLVABLE_STATUSES), key=lambda x: (x["entry_date"], x["ticker"]))
    recent = sorted(({**_row(r), "resolution_date": r.get("resolution_date"), "resolution": r.get("status"),
                      "realized_r": r.get("realized_r")} for r in closed),
                    key=lambda x: (x["resolution_date"] or "", x["ticker"]), reverse=True)[:10]
    return {
        "enabled": True, "records": len(records),
        "pending": by_status.get("pending", 0), "open": by_status.get("open", 0) + by_status.get("trailing", 0),
        "closed": len(closed), "triggered": len(triggered), "not_triggered": not_triggered, "skipped": skipped,
        "not_triggered_pct": round(100 * not_triggered / window_done, 1) if window_done else None,
        "avg_realized_r": round(sum(rs) / len(rs), 2) if rs else None,
        "min_closed": min_closed, "stats_visible": visible,
        "wins": wins if visible else None, "losses": (len(rs) - wins) if visible else None,
        "win_rate_pct": round(100 * wins / len(rs), 1) if visible else None,
        "win_ci_pct": _wilson_ci_pct(wins, len(rs)) if visible else None,
        "median_realized_r": round((rs[len(rs) // 2] if len(rs) % 2 else (rs[len(rs) // 2 - 1] + rs[len(rs) // 2]) / 2), 2) if visible else None,
        "spy_compare": spy_compare, "by_regime": by_regime, "live": live, "recent": recent,
    }


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
    # пакет 1, т.7: Track Record-ът е само v2; v1 записите (ако още са в tracker-а) са
    # извън статистиката — v1 е един архивен ред (виж по-долу и tracker_switch.py)
    records = [r for r in tracker.values() if r.get("method") == "v2" and is_action_record(r)]   # пакет 1б: buy-stop книгата е отделна

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
            if r.get("return_pct") is not None and not needs_review:
                # v2: претеглена с частичната продажба доходност (виж trade_sim); ако 50% са
                # продадени на целта, "цена спрямо входа" би подценила реалния резултат
                unrealized_pct = round(r["return_pct"], 1) + 0.0
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
                # v2: показваме РЕАЛНИЯ вход (fill_date); entry_date е датата на препоръката
                "entry_date": r.get("fill_date") or r["entry_date"],
                "signal_date": r["entry_date"],
                "entry_price": entry_price,
                "current_price": round(cur, 2) if cur is not None else None,
                "unrealized_pct": unrealized_pct,
                "spy_return_pct": r.get("spy_return_pct"),
                "alpha_pct": r.get("alpha_pct"),
                "needs_manual_review": needs_review,
                # FIX 2026-08-13: entry_date филтърът е премахнат — единен
                # recency праг за Case 1 И Case 2 (виж enrich.earnings_recap
                # docstring-а, дискусията 2026-08-13).
                "earnings_recap": enrich.earnings_recap(r["ticker"]),
            })
        open_positions.sort(key=lambda r: r["entry_date"])  # възходящо — най-старите първи

    # т.8: доходност спрямо SPY за СЪЩИТЕ периоди — само затворените позиции с R и с SPY данни
    cmp_recs = [r for r in records if r.get("realized_r") is not None
                and r.get("return_pct") is not None and r.get("spy_return_pct") is not None]
    spy_compare = None
    if cmp_recs:
        n_c = len(cmp_recs)
        avg_ret = sum(r["return_pct"] for r in cmp_recs) / n_c
        avg_spy = sum(r["spy_return_pct"] for r in cmp_recs) / n_c
        spy_compare = {"n": n_c, "avg_return_pct": round(avg_ret, 2), "avg_spy_pct": round(avg_spy, 2),
                       "avg_alpha_pct": round(avg_ret - avg_spy, 2),
                       "beat_spy_pct": round(sum(1 for r in cmp_recs if r["return_pct"] > r["spy_return_pct"]) / n_c * 100, 1)}

    # v2: препоръки, които още чакат buy-stop (няма позиция, не е в статистиката)
    pending_positions = sorted(
        ({"ticker": r["ticker"], "entry_date": r["entry_date"], "buy_stop": r.get("buy_stop"),
          "max_chase": r.get("max_chase"), "valid_through": r.get("valid_through"),
          "stop_loss": r.get("stop_loss"), "target_1": r.get("target_1")}
         for r in records if r.get("status") == "pending"),
        key=lambda r: r["entry_date"])

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
        # v2: чакат buy-stop / прозорецът изтече без вход / над тавана за вход — не са
        # позиции и не влизат в win rate и средния R
        # т.4: колко позиции са минали през частична продажба на цел 1 и колко от "stopped"
        # са излезли на стопа ЧЕ СЛЕД нея (печалба по R, макар статусът да е "stopped")
        "partial_taken": sum(1 for r in records if r.get("partial_price") is not None),
        "stopped_after_partial": sum(1 for r in records if r.get("status") == "stopped"
                                     and r.get("partial_price") is not None),
        "pending": by_status.get("pending", 0),
        "methodology": {"version": methodology(), "switched_on": load_state().get("switched_on")},
        "spy_compare": spy_compare,
        "v1_archive": load_state().get("v1_stats"),
        "not_triggered": by_status.get("not_triggered", 0),
        "skipped_extended": by_status.get("skipped_extended", 0) + by_status.get("invalid_risk", 0),
        "pending_positions": pending_positions,
        "avg_realized_r": avg_r,
        "recent": recent,
        "open_positions": open_positions,
    }


if __name__ == "__main__":
    update_backtest_tracker()
    summary = get_backtest_summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
