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


def _split_only_adjust(close, high, low, splits):
    """
    FIX 2026-08-24 (GLB dividend-drift одит, Venci): auto_adjust=True
    ретроактивно dividend-adjust-ва ЦЯЛАТА историческа Close/High/Low серия
    при всяко ex-div събитие — потвърдено на живо (NWE ex-div 17.08.2026,
    prior_high $71.66→$70.99 в СЪЩИЯ ден, нулева промяна в реалната пазарна
    цена). Скалата е широка: за 44г-стар high-yield платец (SO/Southern Co)
    auto_adjust=True показва 1981 close $0.27 срещу реалните $3.67
    (auto_adjust=False) — 13.6× изкривяване. За price-breakout детекция
    (Weinstein/Wish методология) искаме SPLIT-adjusted, НЕ dividend-adjusted
    цени — total-return adjustment е грешен инструмент тук, price-level
    пробив трябва да е спрямо реално търгуваната цена.

    Ръчна split-only корекция върху auto_adjust=False суровите данни:
    за всяка split дата, всички редове ПРЕДИ нея се делят на ratio-то.
    Множество splits се композират коректно (всеки следващ split дели
    и по-старите редове отново — ред на итерация няма значение, маските
    са независими по абсолютна дата).
    """
    if splits is None or splits.empty:
        return close, high, low
    close, high, low = close.copy(), high.copy(), low.copy()
    for split_date, ratio in splits.items():
        if not ratio or ratio == 1:
            continue
        mask = close.index < split_date
        close.loc[mask] = close.loc[mask] / ratio
        high.loc[mask] = high.loc[mask] / ratio
        low.loc[mask] = low.loc[mask] / ratio
    return close, high, low


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
            # FIX 2026-08-24: auto_adjust=False + actions=True (виж
            # _split_only_adjust docstring-а за пълния rationale) — сурови
            # Close/High/Low, split историята идва БЕЗПЛАТНО в СЪЩИЯ batch
            # call (Stock Splits колона), без нужда от отделна per-ticker
            # yf.Ticker(sym).splits заявка.
            data = yf.download(batch, period=config.GLB_HISTORY_PERIOD, progress=False,
                               auto_adjust=False, actions=True, group_by="ticker",
                               threads=True)
        except Exception as e:
            print(f"[glb_screener] batch {i} fetch грешка: {e}")
            continue

        for sym in batch:
            try:
                df = (data[sym] if len(batch) > 1 else data).dropna(
                    subset=["Close", "High", "Low"])
                splits = df["Stock Splits"]
                close, high, low = _split_only_adjust(
                    df["Close"], df["High"], df["Low"], splits[splits != 0])
                df = df.assign(Close=close, High=high, Low=low)
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
