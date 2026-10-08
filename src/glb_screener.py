"""
GLB (Green Line Breakout) скрийнър — Classic + Momentum варианти, ПАРАЛЕЛНО
(не се избира един за сметка на другия, виж config.py секцията за пълния
design rationale). Вдъхновено от Eric Wish (wishingwealthblog.com), но
преработено след backtest диагностика в experiments/glb_backtest.py и
experiments/glb_monthly_check.py (2026-08-12/13 discussion).

Универсален гейт (и за трите изхода по-долу): месечен duration-only критерий
— ATH close unpenetrated >= GLB_MIN_MONTHS_UNPENETRATED последователни
месеца, после close над него. glb_type има ТРИ, не два, изхода:
  "classic"              — дневният tightness overlay СЪЩО минава на same
                            breakout момент (тесен, удържан base).
  "momentum"              — overlay-ът е ИЗЧИСЛЕН, но НЕ минава прага
                            (реално потвърден бърз/волатилен пробив).
  "insufficient_history"  — overlay-ът НЕ е могъл да се изчисли изобщо
                            (< GLB_MIN_CONSOLIDATION_DAYS дневни бара
                            налични) — explicit различно от "momentum",
                            за да не се бърка "не проверихме" с "проверихме
                            и няма база" (виж _evaluate_ticker).
Класификацията е ПО SETUP, не по възраст на тикъра — виж config.py защо
(WDC's 47г история не спаси overlay-а от провал на собствения ѝ 2025
breakout; age-based gating би скрил точно този случай).

Screening и AI синтез остават разделени, same принцип като screener.py —
този модул е чисто механичен, нула AI извиквания.

Универс: reuse-ва src.screener.build_universe() — САМО дефиниционния
Wikipedia S&P500/Nasdaq100/MidCap400 списък, НЕ технически изчислени
резултати (никаква coupling на screener.py's 2y OHLCV данни или Stage2/RS
преценка). OHLCV fetch-ът тук е напълно независим: собствени yf.download
batch извиквания с GLB_HISTORY_PERIOD (default "max") — screener.py тегли
само 2г, структурно недостатъчно за multi-decade ATH detection (WDC
сигналът изисква данни чак до 2014 г.).

Хистерезис (пакет 4б т.е, 06.10.2026): вход само при close >= линията x (1 + GLB_ENTRY_MARGIN_PCT%); кандидатът остава, докато close >= линията x
(1 - GLB_EXIT_MARGIN_PCT%). Събитието (линия, дата на входа, тип, детайли) се пази в data/glb_state.json (apply_hysteresis — чиста функция), затова не мига
около линията и не се нулира при смяна на месеца. Картата показва "GLB от <дата>, +X% над линията".

Graceful degradation: провал на batch fetch или единичен тикър -> пропусни,
print диагностика, продължи с останалите (Секция 7).
"""
from __future__ import annotations
import datetime as dt
import json
import time

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src.screener import build_universe
from src.ai_brief import _verified_company_name

import numpy as np
import pandas as pd
import yfinance as yf

RISK_NOTES = {
    "classic": (
        f"Наш филтър (не на Wish): поне {config.GLB_MIN_BAND_HOLD_PCT:.0f}% от последните {config.GLB_MIN_CONSOLIDATION_DAYS} затваряния преди пробива са не по-ниско от "
        f"{config.GLB_APPROACH_PCT:.0f}% под линията (band_hold). Диапазонът на тези дни е показан като число — не е доказателство за \"тесен\" base."
    ),
    "momentum": (
        "Дълъг период без нов връх, но по-малко от "
        f"{config.GLB_MIN_BAND_HOLD_PCT:.0f}% от последните {config.GLB_MIN_CONSOLIDATION_DAYS} затваряния преди пробива са близо до линията (наш филтър, не на Wish) — "
        "бърз/волатилен пробив. По-висок очакван drawdown риск спрямо стандартните Action кандидати — обмисли намален size."
    ),
    "insufficient_history": (
        "Недостатъчна дневна история (< GLB_MIN_CONSOLIDATION_DAYS дни "
        "налични) за оценка на близостта до линията — НЕ е потвърдено нито Classic, нито Momentum, просто не сме "
        "проверили. Третирай предпазливо като непроверен случай."
    ),
}


def _monthly_duration_check(monthly_close, margin_pct: float = 0.0) -> dict | None:
    """
    Буквален Wish критерий, приложен на месечно орязана Close серия
    (последният елемент = текущият/последният наличен месец). Връща None
    ако текущият месец НЕ е валиден GLB breakout момент.
    margin_pct (пакет 4б т.е): 0 = буквалното close > линията; > 0 = close >= линията x (1 + margin_pct/100) (буфер за ВХОД).
    """
    if len(monthly_close) < config.GLB_MIN_MONTHS_UNPENETRATED + 2:
        return None
    i = len(monthly_close) - 1
    window_before = monthly_close.iloc[:i]
    prior_high = float(window_before.max())
    prior_high_pos = int(window_before.values.argmax())
    months_unpenetrated = i - prior_high_pos - 1
    this_close = float(monthly_close.iloc[i])
    breakout = this_close > prior_high if not margin_pct else this_close >= prior_high * (1 + margin_pct / 100)
    if not (breakout and months_unpenetrated >= config.GLB_MIN_MONTHS_UNPENETRATED):
        return None
    return {
        "prior_high": round(prior_high, 2),
        "prior_high_month": monthly_close.index[prior_high_pos].strftime("%Y-%m"),
        "months_unpenetrated": months_unpenetrated,
    }


def _tightness_overlay(daily_close, daily_high, daily_low, prior_high: float) -> dict | None:
    """
    Дневен overlay — мажоритарен rolling критерий, изчислен ВИНАГИ (когато
    има достатъчно дневна история), независимо дали ще мине Classic прага.
    Trailing прозорец = последните GLB_MIN_CONSOLIDATION_DAYS дни ПРЕДИ
    последния ред (= "днес", breakout деня). None само при недостатъчна
    дневна история — ЯВНО РАЗЛИЧНО от "проверихме и не мина" (виж
    _evaluate_ticker: None -> "insufficient_history" label, не мълчаливо
    "momentum" — "не знаем" не бива тихо да се превръща в "знаем, и е X").
    """
    n = config.GLB_MIN_CONSOLIDATION_DAYS
    if len(daily_close) < n + 1:
        return None
    recent_close = daily_close.iloc[-(n + 1):-1]
    recent_high = daily_high.iloc[-(n + 1):-1]
    recent_low = daily_low.iloc[-(n + 1):-1]
    band_floor = prior_high * (1 - config.GLB_APPROACH_PCT / 100)
    band_hold_pct = float((recent_close >= band_floor).sum()) / n * 100
    tightness_range_pct = float((recent_high.max() - recent_low.min()) / prior_high * 100)
    return {
        "band_hold_pct": round(band_hold_pct, 1),
        "tightness_range_pct": round(tightness_range_pct, 2),
        "meets_tightness": band_hold_pct >= config.GLB_MIN_BAND_HOLD_PCT,
    }


def breakout_volume_ratio(hist) -> float | None:
    """
    Обемът на последния бар (деня на пробива) ÷ средния обем на предишните config.GLB_VOLUME_AVG_BARS бара (последният не влиза в средната). None при липсващ обем/недостатъчна история/нулева средна. Информативно поле
    (09.10.2026): Wish не изисква обем за пробива, нашият Action изисква ≥ 1.5×; тук се показва, без да филтрира.
    """
    try:
        n = config.GLB_VOLUME_AVG_BARS
        vol = hist["Volume"].dropna()
        if len(vol) < n + 1:
            return None
        avg = float(vol.iloc[-(n + 1):-1].mean())
        return round(float(vol.iloc[-1]) / avg, 2) if avg > 0 else None
    except Exception:
        return None


def x_from_low52(close: float, low52) -> float | None:
    """Цената ÷ най-ниското дневно Low на последните 252 сесии ("× от 52-седмичното дъно"); информативно поле, смята се всеки ден."""
    try:
        return round(float(close) / float(low52), 2) if low52 and float(low52) > 0 else None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────
# Книга "GLB по Уиш" (09.10.2026): БУКВАЛНОТО правило, без нашите филтри — сигнал, разделен от картите (хистерезис, Classic/Momentum)
# ──────────────────────────────────────────────────────────────────────────
LAST_WISH_SIGNALS: list[dict] = []          # свежите пробиви от последния screen() (main ги подава на книгата); [] при провал


def wish_table(close: "pd.Series") -> "pd.DataFrame":
    """
    Дневна таблица на буквалното правило на Wish върху дневните затваряния (ЕДНА векторизирана функция за живия сигнал и за историческия реплей):
      line          — най-високият месечен close на ПРЕДХОДНИТЕ календарни месеци (не включва месеца на деня);
      months_unpen  — месеци между месеца на този максимум и текущия (същото като `months_unpenetrated` в _monthly_duration_check);
      signal        — close > линията (БЕЗ буфер, за разлика от хистерезисния вход) И months_unpen >= GLB_MIN_MONTHS_UNPENETRATED (при >= GLB_MIN_MONTHS_UNPENETRATED + 1 предходни месеца);
      fresh         — сигнал в този бар, който не е продължение (предишният бар не е бил сигнал при същата линия): само пробивът, не седмиците над линията.
    Празна/кратка серия → празна таблица. Чиста функция, без мрежа.
    """
    c = close.dropna()
    cols = ["close", "line", "months_unpen", "prior_high_month", "signal", "fresh"]
    if len(c) == 0:
        return pd.DataFrame(columns=cols)
    mc = c.resample("ME").last().dropna()
    n = len(mc)
    vals = mc.to_numpy(dtype=float)
    line_m = np.full(n, np.nan)
    pos_m = np.full(n, -1)
    best, bpos = -np.inf, -1
    for m in range(n):
        if m:
            line_m[m], pos_m[m] = best, bpos
        if vals[m] > best:                       # строго по-голям: при равенство остава ПЪРВИЯТ максимум (както argmax в _monthly_duration_check)
            best, bpos = vals[m], m
    midx = mc.index.to_period("M").get_indexer(c.index.to_period("M"))
    ok = midx >= 0
    line = np.where(ok, line_m[np.where(ok, midx, 0)], np.nan)
    pos = np.where(ok, pos_m[np.where(ok, midx, 0)], -1)
    unpen = np.where(pos >= 0, midx - pos - 1, -1)
    enough = midx >= config.GLB_MIN_MONTHS_UNPENETRATED + 1           # len(series) >= GLB_MIN_MONTHS_UNPENETRATED + 2, както в _monthly_duration_check
    cv = c.to_numpy(dtype=float)
    signal = enough & (cv > line) & (unpen >= config.GLB_MIN_MONTHS_UNPENETRATED)
    prev = np.concatenate([[False], signal[:-1]])
    prev_line = np.concatenate([[np.nan], line[:-1]])
    fresh = signal & ~(prev & (prev_line == line))
    names = np.array([mc.index[k].strftime("%Y-%m") if k >= 0 else "" for k in range(n)] + [""])
    return pd.DataFrame({"close": cv, "line": line, "months_unpen": unpen, "prior_high_month": names[np.where(pos >= 0, pos, n)], "signal": signal, "fresh": fresh}, index=c.index)


def wish_signal(hist, today: str | None = None) -> dict | None:
    """
    Свеж пробив на ПОСЛЕДНИЯ ЦЯЛ бар по буквалното правило на Wish (wish_table) → речник за книгата, иначе None. Бар с дата >= today (частичната сесия при ръчно пускане в хода на деня) не е затваряне и се
    отрязва. Типът (classic/momentum/insufficient_history) е САМО таг (нашият overlay), не филтър. Грешка → None (graceful).
    """
    try:
        close = hist["Close"].dropna()
        if today:
            close = close[close.index < pd.Timestamp(today)]
        if len(close) < 60:
            return None
        t = wish_table(close)
        last = t.iloc[-1]
        if not bool(last["fresh"]):
            return None
        h = hist.loc[:close.index[-1]]
        ov = _tightness_overlay(h["Close"], h["High"], h["Low"], float(last["line"])) if {"High", "Low"} <= set(h.columns) else None
        return {"signal_date": close.index[-1].date().isoformat(), "close": round(float(last["close"]), 4), "line": round(float(last["line"]), 4),
                "prior_high_month": str(last["prior_high_month"]), "months_unpenetrated": int(last["months_unpen"]),
                "glb_type": "insufficient_history" if ov is None else ("classic" if ov["meets_tightness"] else "momentum"),
                "band_hold_pct": None if ov is None else ov["band_hold_pct"]}
    except Exception as e:
        print(f"[glb_screener] wish_signal: {type(e).__name__}: {e}")
        return None


# Цени за GLB: yf.download(..., auto_adjust=False) — БЕЗ ръчна корекция за сплитове.
# История (2026-08-24, GLB dividend-drift одит): auto_adjust=True ретроактивно dividend-adjust-ва ЦЯЛАТА историческа Close/High/Low серия при всяко ex-div събитие (NWE ex-div 17.08.2026: prior_high $71.66→$70.99
# в същия ден; SO 1981 close $0.27 срещу реалните $3.67 — 13.6× изкривяване). За price-breakout искаме цени, коригирани за сплитове, а НЕ за дивиденти → auto_adjust=False.
# Тогава (24.08) към това добавихме ръчна split-only корекция (делене на всички редове преди сплита), в предположение, че auto_adjust=False връща СУРОВИ цени. Не е така: Yahoo `Close` (и Open/High/Low/Volume) при
# auto_adjust=False е вече ретроактивно split-коригиран — открито при реплея на 08.10.2026 (NVDA 07.06.2024 = 120.89; AAPL 28.08.2020 = 124.81; AMZN 02.06.2022 = 125.51; yfinance 1.5.2 и 1.7.0), затова ръчната корекция делеше ВТОРИ път (NVDA 12.09, AAPL 31.20,
# AMZN 6.28) и занижаваше линията на акции със сплит. Функцията `_split_only_adjust` и колоната "Stock Splits" (actions=True) са махнати; тестът върху реалните NVDA/AAPL/AMZN е test_split_not_doubled.py.


def _evaluate_ticker(sym: str, hist, entry_margin_pct: float = 0.0) -> dict | None:
    """
    hist = пълен OHLCV df за sym (вече изтеглен batch-ово от screen()).
    Прилага универсалния месечен гейт, после класифицира Classic/Momentum
    по дневния overlay. Връща None ако тикърът не е GLB кандидат въобще.
    """
    if hist is None or hist.empty or len(hist) < 60:
        return None

    monthly_close = hist["Close"].resample("ME").last().dropna()
    m_result = _monthly_duration_check(monthly_close, entry_margin_pct)
    if m_result is None:
        return None

    history_years = (hist.index[-1] - hist.index[0]).days / 365.25
    ath_label = ("all_time_high" if history_years >= config.GLB_MIN_ATH_HISTORY_YEARS
                else "new_high_since_listing")

    overlay = _tightness_overlay(hist["Close"], hist["High"], hist["Low"], m_result["prior_high"])
    if overlay is None:
        glb_type = "insufficient_history"     # НЕ проверихме overlay-а — различно от "проверихме, не мина"
    elif overlay["meets_tightness"]:
        glb_type = "classic"
    else:
        glb_type = "momentum"

    company = _verified_company_name(sym)["name"]  # reuse — same lookup като COT секцията (ai_brief.py)
    volume_ratio = breakout_volume_ratio(hist)

    return {
        "ticker": sym,
        "company": company,
        "glb_type": glb_type,
        "price": round(float(hist["Close"].iloc[-1]), 2),
        "prior_high": m_result["prior_high"],
        "prior_high_month": m_result["prior_high_month"],
        "months_unpenetrated": m_result["months_unpenetrated"],
        "ath_label": ath_label,
        "history_years": round(history_years, 1),
        "breakout_volume_ratio": volume_ratio,      # 09.10: обемът на деня на пробива ÷ средния обем на предишните GLB_VOLUME_AVG_BARS бара; САМО информация, не филтър
        "tightness": overlay,  # None ако няма достатъчно дневна история за overlay-а
        "risk_note": RISK_NOTES[glb_type],
    }


# ──────────────────────────────────────────────────────────────────────────
# Хистерезис и състояние (пакет 4б т.е)
# ──────────────────────────────────────────────────────────────────────────
def load_state(path=None) -> dict:
    """{тикър: събитие} от data/glb_state.json; липсващ/повреден файл -> {} (чист старт, без грешка)."""
    p = path or config.GLB_STATE_FILE
    try:
        return dict(json.loads(pathlib.Path(p).read_text(encoding="utf-8")).get("events") or {})
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[glb_screener] state нечетим, започвам от празен: {type(e).__name__}: {e}")
        return {}


def load_seed_meta(path=None) -> dict:
    """{version, sessions, from, to} на последното начално състояние от историята (08.10.2026) или {}."""
    try:
        return dict(json.loads(pathlib.Path(path or config.GLB_STATE_FILE).read_text(encoding="utf-8")).get("seed") or {})
    except Exception:
        return {}


def save_state(events: dict, today: str, path=None, seed: dict | None = None) -> None:
    p = pathlib.Path(path or config.GLB_STATE_FILE)
    try:
        p.parent.mkdir(exist_ok=True)
        payload = {"updated": today, "events": events}
        meta = seed if seed is not None else load_seed_meta(p)               # обикновен ден: белегът за началното състояние се пази
        if meta:
            payload["seed"] = meta
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except Exception as e:
        print(f"[glb_screener] state не се записа: {type(e).__name__}: {e}")


def _row(ev: dict, close: float, low52=None) -> dict:
    """Редът за показване: събитието от входа + днешната цена, разстоянието до линията и (информативно, 09.10) "× от 52-седмичното дъно"."""
    return {**ev, "price": round(float(close), 2), "pct_vs_line": round((float(close) / ev["line"] - 1) * 100, 1),
            "x_from_52w_low": x_from_low52(close, low52)}


def apply_hysteresis(events: dict, observations: dict, today: str, exit_margin_pct: float | None = None) -> tuple[dict, list[dict], dict]:
    """
    Чиста функция. events: състоянието {тикър: събитие}; observations: {тикър: {"close": последният close, "entry": резултат от _evaluate_ticker с буфер за вход, или None}}.
      • тикър със събитие: остава, докато close >= линията x (1 - EXIT%); под това — отпада (и може да влезе пак само през правилото за вход);
        без наблюдение днес (липсват данни) — събитието се пази, но не се показва (не се губи заради провал на теглене);
      • тикър без събитие и с "entry" (close >= линията x (1 + ENTRY%) при валиден месечен гейт) — НОВО събитие: линия, дата на входа, тип и детайли се замразяват.
    Връща (нови събития, редове за показване, {"entered": [...], "dropped": [...], "held_unseen": [...]}).
    """
    exit_m = config.GLB_EXIT_MARGIN_PCT if exit_margin_pct is None else exit_margin_pct
    new: dict = {}
    rows: list[dict] = []
    ch: dict = {"entered": [], "dropped": [], "held_unseen": []}
    for sym, ev in events.items():
        ob = observations.get(sym)
        if ob is None or ob.get("close") is None:
            new[sym] = ev
            ch["held_unseen"].append(sym)
        elif ob["close"] >= ev["line"] * (1 - exit_m / 100):
            new[sym] = ev
            rows.append(_row(ev, ob["close"], ob.get("low52")))
        else:
            ch["dropped"].append(sym)
    for sym, ob in observations.items():
        if sym in events or not ob.get("entry"):
            continue
        e = ob["entry"]
        ev = {**{k: v for k, v in e.items() if k not in ("price",)}, "line": e["prior_high"], "since": today}
        new[sym] = ev
        rows.append(_row(ev, ob["close"], ob.get("low52")))
        ch["entered"].append(sym)
    return new, rows, ch


def replay_observations(sym: str, hist, n_sessions: int, entry_margin_pct: float) -> dict:
    """
    Началното състояние от историята (08.10.2026): за последните n сесии на тикъра — {дата: {"close", "entry"}} така, както би го видял всеки дневен run: месечната серия до деня = затворените месеци + close-а на деня
    (текущият месец), входът е _evaluate_ticker върху историята ДО деня (линия/дълъг период/overlay към тази дата). Бърза проверка преди скъпата: close >= (най-високия месечен close преди месеца) x (1 + буфера).
    Чиста функция върху hist (без мрежа, освен лукапа на името в _evaluate_ticker за тикъри, които влизат).
    """
    close = hist["Close"].dropna()
    if len(close) < 60:
        return {}
    mc = close.resample("ME").last().dropna()
    per = mc.index.to_period("M")
    out = {}
    for d in close.index[-n_sessions:]:
        cur = float(close.loc[d])
        prior = mc[per < d.to_period("M")]
        entry = None
        if len(prior) and cur >= float(prior.max()) * (1 + entry_margin_pct / 100):
            series = pd.concat([prior, pd.Series([cur], index=[d])])
            if _monthly_duration_check(series, entry_margin_pct) is not None:
                entry = _evaluate_ticker(sym, hist.loc[:d], entry_margin_pct)
        low = hist["Low"].loc[:d].iloc[-252:].min() if "Low" in hist else None
        out[d.date().isoformat()] = {"close": cur, "entry": entry, "low52": None if low is None or low != low else float(low)}
    return out


def replay_state(replays: dict[str, dict]) -> tuple[dict, list[dict], dict]:
    """
    Ден по ден apply_hysteresis (същата чиста функция като в дневния run) върху replays {тикър: {дата: {close, entry}}}, от най-старата към най-новата сесия. Връща (събития, редове за последния ден,
    {"entered": [...], "dropped": [...], "held_unseen": [...]} за ПОСЛЕДНИЯ ден) — "since" е реалният ден на входа, не денят на първия run.
    """
    dates = sorted({d for r in replays.values() for d in r})
    events: dict = {}
    rows: list[dict] = []
    ch: dict = {"entered": [], "dropped": [], "held_unseen": []}
    for d in dates:
        obs = {s: r[d] for s, r in replays.items() if d in r}
        events, rows, ch = apply_hysteresis(events, obs, d)
    return events, rows, ch


def screen(universe: list[str] | None = None, batch_size: int = 50, state_path=None, today: str | None = None) -> list[dict]:
    """
    Главна входна точка. universe=None -> reuse-ва screener.build_universe()
    (само СПИСЪКА от тикъри, виж модул docstring-а). batch_size по-малък от
    screener.py's 100 нарочно — period="max" на тикър е много по-тежък
    payload от screener.py's period="2y".

    Връща списък от dict-ове, ВСЕКИ explicit маркиран с "glb_type"
    ("classic"/"momentum") — Двата типа остават заедно в резултата,
    разделянето/визуализацията е грижа на извикващия код (dashboard).
    """
    global LAST_WISH_SIGNALS
    LAST_WISH_SIGNALS = []                       # книгата "GLB по Уиш": нов списък на всяко извикване (при провал остава празен)
    wish_signals: list[dict] = []
    if universe is None:
        universe = build_universe()

    hyst = config.GLB_HYSTERESIS
    seed = bool(hyst and config.GLB_SEED_SESSIONS and load_seed_meta(state_path).get("version", 0) < config.GLB_SEED_VERSION)   # еднократно: състоянието се гради от историята
    events = load_state(state_path) if (hyst and not seed) else {}
    replays: dict = {}
    observations: dict = {}
    today = today or dt.date.today().isoformat()
    results = []
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i + batch_size]
        try:
            # auto_adjust=False: цени, коригирани за сплитове, но НЕ за дивиденти (виж бележката над _evaluate_ticker). Без ръчна корекция — Yahoo вече е коригирал сплитовете.
            data = yf.download(batch, period=config.GLB_HISTORY_PERIOD, progress=False,
                               auto_adjust=False, group_by="ticker",
                               threads=True)
        except Exception as e:
            print(f"[glb_screener] batch {i} fetch грешка: {e}")
            continue

        for sym in batch:
            try:
                df = (data[sym] if len(batch) > 1 else data).dropna(
                    subset=["Close", "High", "Low"])
                if config.TRACK_GLB_WISH:
                    w = wish_signal(df, today)                       # книгата "GLB по Уиш": сигналът върху същите цени като картите
                    if w:
                        wish_signals.append({"ticker": sym, **w})
                if hyst and seed:
                    replays[sym] = replay_observations(sym, df, config.GLB_SEED_SESSIONS, config.GLB_ENTRY_MARGIN_PCT)
                    continue
                if hyst:
                    last = float(df["Close"].iloc[-1]) if len(df) else None
                    # тикър със събитие не се оценява наново (линията е замразена); нов вход — само с буфера над линията
                    observations[sym] = {"close": last, "entry": None if sym in events else _evaluate_ticker(sym, df, config.GLB_ENTRY_MARGIN_PCT),
                                         "low52": float(df["Low"].iloc[-252:].min()) if len(df) else None}
                    continue
                r = _evaluate_ticker(sym, df)
            except Exception as e:
                print(f"[glb_screener] {sym}: {e}")
                continue
            if r:
                results.append(r)
        time.sleep(1)  # не дразним Yahoo, same дисциплина като screener.py

    if hyst and seed:
        events, results, ch = replay_state(replays)
        dates = sorted({d for r in replays.values() for d in r})
        save_state(events, today, state_path, seed={"version": config.GLB_SEED_VERSION, "sessions": len(dates), "from": dates[0] if dates else None, "to": dates[-1] if dates else None})
        print(f"[glb_screener] НАЧАЛНО състояние от историята ({len(dates)} сесии {dates[0] if dates else '?'} → {dates[-1] if dates else '?'}): {len(events)} събития, "
              f"показват се {len(results)}; в последния ден: нови {len(ch['entered'])}, отпаднали {len(ch['dropped'])} {ch['dropped'] or ''}")
    elif hyst:
        events, results, ch = apply_hysteresis(events, observations, today)
        save_state(events, today, state_path)
        print(f"[glb_screener] хистерезис: нови {len(ch['entered'])}, отпаднали {len(ch['dropped'])} {ch['dropped'] or ''}, "
              f"пазени без данни днес {len(ch['held_unseen'])}")

    LAST_WISH_SIGNALS = wish_signals
    if config.TRACK_GLB_WISH:
        print(f"[glb_screener] GLB по Уиш: {len(wish_signals)} свежи пробива на последния цял бар " + (f"({', '.join(w['ticker'] for w in wish_signals[:12])}{'…' if len(wish_signals) > 12 else ''})" if wish_signals else ""))
    classic = [r for r in results if r["glb_type"] == "classic"]
    momentum = [r for r in results if r["glb_type"] == "momentum"]
    insufficient = [r for r in results if r["glb_type"] == "insufficient_history"]
    print(f"[glb_screener] {len(results)} GLB кандидати ({len(classic)} classic, "
         f"{len(momentum)} momentum, {len(insufficient)} insufficient_history) "
         f"от {len(universe)} тикъра")
    return results


if __name__ == "__main__":
    import json
    # Бърз smoke test само върху познатите 4 тикъра (SNDK/WDC/MU/STX) —
    # пълният universe scan е скъп (500+ тикъра × period="max"), за
    # production run виж screen() без universe= аргумент.
    out = screen(universe=["SNDK", "WDC", "MU", "STX"])
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
