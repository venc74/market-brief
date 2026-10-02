"""
Пазарен термометър (Секция 4).
Осем индикатора + обща препоръка Offensive / Defensive / Cash.
Всеки индикатор връща {value, status, label} където status ∈ green/yellow/red.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import time
import requests
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src.screener import build_universe


def spy_trend() -> dict:
    """
    FIX 2026-07-15: NaN от Yahoo даваше price > ma50 == False (NaN сравнения
    са винаги False) → тих фалшив "red" с етикет "SPY nan | под 50DMA". Сега:
    липсващи/NaN данни → hide=True (unknown), НЕ фалшив сигнал в нито посока.
    """
    try:
        hist = yf.Ticker("SPY").history(period="1y")
        if hist.empty or len(hist) < 200:
            raise ValueError("insufficient SPY history")
        close = hist["Close"]
        price = float(close.iloc[-1])
        ma50 = float(close.rolling(50).mean().iloc[-1])
        ma200 = float(close.rolling(200).mean().iloc[-1])
        if any(math.isnan(v) for v in (price, ma50, ma200)):
            raise ValueError("NaN в SPY цена/MA — невалидни данни от източника")
        above50, above200 = price > ma50, price > ma200
        status = "green" if (above50 and above200) else ("yellow" if above200 else "red")
        # FIX 2026-09-28: разстояние до 52-седмичния връх (затваряния) — за
        # бележката за разминаване с Market Breadth; не влияе на статуса
        high_52w = float(close.iloc[-252:].max())
        return {
            "name": "SPY тренд", "value": round(price, 2),
            "pct_from_high": round((1 - price / high_52w) * 100, 2),
            "ma50": round(ma50, 2), "ma200": round(ma200, 2),
            "above_50dma": above50, "above_200dma": above200, "status": status,
            "label": f"SPY {price:.0f} | {'над' if above50 else 'под'} 50DMA, "
                     f"{'над' if above200 else 'под'} 200DMA",
        }
    except Exception as e:
        print(f"[thermo] SPY trend failed: {e}")
        return {"name": "SPY тренд", "value": None, "status": "yellow",
                "hide": True, "label": ""}


def vix_level() -> dict:
    """
    FIX 2026-08-02 (точка 11): AI-то само отбеляза методологична дупка на
    24.07.2026 — "VIX е зелен по абсолютна стойност (18.7), но 5-дневната
    промяна е +24.4%". За разлика от move_index() по-долу, тук нямаше spike
    detection — статичен праг само по ниво, без оглед на скоростта на промяна.
    Добавен symmetric spike флаг (config.VIX_SPIKE_WEEKLY_PCT, калиброван на
    2г реална VIX история — виж коментара в config.py), mirroring move_spike:
    рязка 5-дневна % промяна форсира status="red" независимо от абсолютното
    ниво. Заедно с това: period="10d"/iloc[0] замених с period="1mo"/iloc[-6]
    (same похват като move_index()) — старото давашe fuzzy "около 5 дни"
    прозорец (calendar days, не trading days), новото е точно 5 търговски дни.
    """
    try:
        hist = yf.Ticker("^VIX").history(period="1mo")
        if hist.empty or len(hist) < 6:
            raise ValueError("insufficient VIX history")
        vix = float(hist["Close"].iloc[-1])
        week_ago = float(hist["Close"].iloc[-6])
        if math.isnan(vix) or math.isnan(week_ago):
            raise ValueError("NaN VIX — невалидни данни от източника")
    except Exception as e:
        print(f"[thermo] VIX failed: {e}")
        return {"name": "VIX", "value": None, "status": "yellow",
                "hide": True, "label": ""}

    pct_5d = (vix - week_ago) / week_ago * 100 if week_ago else None
    spike = pct_5d is not None and pct_5d >= config.VIX_SPIKE_WEEKLY_PCT

    if vix < config.VIX_RISK_ON:
        status = "green"
    elif vix < config.VIX_RISK_OFF:
        status = "yellow"
    else:
        status = "red"
    if spike:
        status = "red"

    spike_note = " ⚠ рязък скок" if spike else ""
    return {
        "name": "VIX", "value": round(vix, 2), "chg_5d": round(vix - week_ago, 2),
        "pct_5d": round(pct_5d, 1) if pct_5d is not None else None,
        "spike": spike, "status": status,
        "label": f"VIX {vix:.1f} ({'risk-on' if status == 'green' else 'risk-off' if status == 'red' else 'неутрално'})"
                 f"{spike_note}",
    }


def market_put_call() -> dict:
    """
    Пазарен P/C ratio — апроксимация чрез SPY опционната верига
    (CBOE total P/C изисква платен фийд). >1.1 = страх, <0.8 = алчност.
    """
    try:
        spy = yf.Ticker("SPY")
        exp = spy.options[0]
        chain = spy.option_chain(exp)
        put_vol = int(chain.puts["volume"].fillna(0).sum())
        call_vol = int(chain.calls["volume"].fillna(0).sum())
        pc = put_vol / call_vol if call_vol else None
        if pc is None:
            raise ValueError("no volume")
        status = "green" if pc > 1.1 else ("red" if pc < 0.7 else "yellow")
        return {"name": "Put/Call (SPY)", "value": round(pc, 2), "status": status,
                "label": f"P/C {pc:.2f}"}
    except Exception as e:
        print(f"[thermo] P/C failed: {e}")
        return {"name": "Put/Call (SPY)", "value": None, "status": "yellow",
                "label": "P/C: няма данни"}


def _is_stale(last_ts) -> bool:
    """
    True ако последният ред от yf .history() е по-стар от
    config.STALENESS_THRESHOLD_DAYS календарни дни спрямо днес. Пази срещу
    low-liquidity тикъри (^MOVE, ^VIX9D, ^VIX3M), при които Yahoo понякога
    спира да публикува нови точки за дни наред, а .iloc[-1] тихо продължава
    да връща същата стара стойност като "текуща" (потвърдено емпирично —
    ^MOVE/^VIX9D/^VIX3M блокираха на 2026-07-02 за >1 седмица).
    """
    last_date = last_ts.date() if hasattr(last_ts, "date") else last_ts
    return (dt.date.today() - last_date).days > config.STALENESS_THRESHOLD_DAYS


def _nan_last_close(hist) -> bool:
    """True ако последният Close е NaN (частичен бар от Yahoo — виж 23.09)."""
    try:
        return math.isnan(float(hist["Close"].iloc[-1]))
    except (TypeError, ValueError, IndexError, KeyError):
        return True


def move_index() -> dict:
    """
    ICE BofA MOVE Index — имплицитна волатилност на UST (2/5/10/30г опции).
    Измерва стреса в самия колатерал (трежъри), върху който стъпва целият
    репо/маржин механизъм — структурно изпреварва VIX при системни кризи
    (SVB март 2023: MOVE 130→200 за 48ч, VIX едва 26). Прагове: <100 нормално,
    100-150 повишен стрес, >150 нестабилност. Отделно следим 1-седмичен delta —
    скоростта на промяна, не само нивото, е ранният сигнал.
    """
    try:
        hist = yf.Ticker("^MOVE").history(period="1mo")
        if hist.empty or len(hist) < 6:
            raise ValueError("insufficient history")
        if _is_stale(hist.index[-1]):
            raise ValueError(f"stale data — последен ред {hist.index[-1].date()}")
        val = float(hist["Close"].iloc[-1])
        # FIX 2026-09-25: прозорецът е по ДАТА, не по позиция. Дотук беше
        # `.iloc[-6]` — пет БАРА назад. На 25.09 барът за 22.09 липсваше изцяло
        # в историята на ^MOVE, и "седмица назад" стигна до 16.09 вместо до
        # 17.09 (делта +23.8 вместо +28.4). Един липсващ бар премества прозореца
        # тихо и при граничен случай може да създаде или да скрие скок.
        # Котвата е ДАТАТА НА ПОСЛЕДНИЯ БАР, не датата на run-а: така разликата
        # между двете наблюдения е винаги точно 7 календарни дни. С котва "днес"
        # run-ът в понеделник (последен бар петък) би сравнил петък с миналия
        # понеделник — 4 дни вместо 7.
        prior = hist["Close"].loc[hist.index <= hist.index[-1] - dt.timedelta(days=7)].dropna()
        if prior.empty:
            raise ValueError("няма стойност на или преди 7 дни назад")
        week_ago = float(prior.iloc[-1])
        # FIX 2026-09-23: NaN тук е ПО-ЛОШ от видимия "nan" при IEI/HYG.
        # Сравненията с NaN са винаги False, затова статусът пада в else-клона
        # → "red" — фалшив червен, който влиза в броенето за режима ("2
        # червени → Defensive, 3+ → Cash"). Hard override-ът не е засегнат
        # (`move_val > 150` с NaN е False), но броенето е.
        if math.isnan(val) or math.isnan(week_ago):
            raise ValueError(f"NaN Close — последен ред {hist.index[-1].date()}")
        delta = val - week_ago
        spike = delta >= config.MOVE_SPIKE_WEEKLY_DELTA

        if val < config.MOVE_YELLOW_THRESHOLD:
            status = "green"
        elif val < config.MOVE_RED_THRESHOLD:
            status = "yellow"
        else:
            status = "red"
        if spike:
            status = "red"

        spike_note = " ⚠ рязък скок" if spike else ""
        return {
            "name": "MOVE (Bond Vol)", "value": round(val, 1),
            "delta_1w": round(delta, 1), "spike": spike, "status": status,
            # FIX 2026-09-28: изрично "пункта" — на 28.09 макро текстът цитира
            # делтата (+15.4 пункта) като "+15.4%" (реалната % промяна е +19.05%)
            "label": f"MOVE {val:.0f} ({delta:+.0f} пункта/седмица){spike_note}",
        }
    except Exception as e:
        print(f"[thermo] MOVE failed: {e}")
        return {"name": "MOVE (Bond Vol)", "value": None, "status": "yellow",
                "hide": True, "label": ""}


def vix_term_structure() -> dict:
    """
    VIX term structure — форма на кривата на имплицитна волатилност
    (^VIX9D 9-дневна, ^VIX 30-дневна, ^VIX3M 3-месечна). Нормално: contango
    (VIX9D < VIX < VIX3M) — пазарът очаква повече несигурност в бъдещето,
    отколкото сега. Backwardation (VIX9D > VIX3M, низходяща крива) означава,
    че краткосрочният страх е по-голям от дългосрочния — класически ранен
    сигнал за остър, непосредствен стрес (вижда се точно преди/по време на
    резки корекции). Следим ratio = VIX9D / VIX3M вместо самите нива.
    """
    try:
        hist9d = yf.Ticker("^VIX9D").history(period="5d")
        hist_mid = yf.Ticker("^VIX").history(period="5d")
        hist3m = yf.Ticker("^VIX3M").history(period="5d")
        if hist9d.empty or hist_mid.empty or hist3m.empty:
            raise ValueError("insufficient VIX9D/VIX/VIX3M data")
        if _is_stale(hist9d.index[-1]) or _is_stale(hist3m.index[-1]):
            raise ValueError(f"stale data — VIX9D {hist9d.index[-1].date()} / "
                             f"VIX3M {hist3m.index[-1].date()}")
        vix9d = float(hist9d["Close"].iloc[-1])
        vix_mid = float(hist_mid["Close"].iloc[-1])
        vix3m = float(hist3m["Close"].iloc[-1])
        # FIX 2026-09-23: `not vix9d` НЕ хваща NaN — NaN е truthy. Без тази
        # проверка ratio=NaN пада в else-клона → "backwardation — остър стрес",
        # фалшив червен, който влиза в броенето за режима (виж move_index).
        if any(math.isnan(v) for v in (vix9d, vix_mid, vix3m)):
            raise ValueError(f"NaN Close — VIX9D {vix9d} / VIX {vix_mid} / VIX3M {vix3m}")
        if not vix9d or not vix3m:
            raise ValueError("insufficient VIX9D/VIX3M data")
        ratio = vix9d / vix3m

        if ratio < config.VIX_TERM_WARNING_THRESHOLD:
            status, note = "green", "contango, нормално"
        elif ratio < config.VIX_TERM_BACKWARDATION_THRESHOLD:
            status, note = "yellow", "леко изравняване"
        else:
            status, note = "red", "backwardation — остър стрес ⚠"

        return {
            "name": "VIX Term Structure", "value": round(ratio, 3), "status": status,
            "label": f"VIX9D {vix9d:.1f} / VIX {vix_mid:.1f} / VIX3M {vix3m:.1f} "
                     f"→ ratio {ratio:.2f} ({note})",
        }
    except Exception as e:
        print(f"[thermo] VIX term structure failed: {e}")
        return {"name": "VIX Term Structure", "value": None, "status": "yellow",
                "hide": True, "label": ""}


def _percentile_rank(history: list[float], current: float) -> float:
    """Same конвенция като cot.py: _percentile_rank — среща умишлено дублирана
    локално вместо cross-module import на частна функция (self-contained
    модули, виж останалите src/*.py)."""
    if not history:
        return 50.0
    below_or_eq = sum(1 for v in history if v <= current)
    return round(100.0 * below_or_eq / len(history), 1)


def _evaluate_credit_spread(ratio) -> dict:
    """
    Чисто изчисление върху вече изтеглена, дата-сортирана IEI/HYG ratio
    серия — разделено от credit_spread_proxy() (fetch+orchestration), за да
    може backtest/regression тестове да го викат directamente с исторически
    ratio срез, БЕЗ да пипат мрежата (same принцип като cot._market_extreme
    vs cot.get_extremes(), glb_screener._evaluate_ticker vs screen()).

    Level компонент: percentile на текущия ratio спрямо trailing
    IEI_HYG_LOOKBACK_DAYS прозорец (изключвайки самия current ред от
    референтната история, same конвенция като COT percentile-a) — ниска
    percentile (ratio близо до дъното на скорошния си range = spreads
    исторически tight) = late-cycle complacency флаг.

    RoC компонент: IEI_HYG_ROC_WINDOW_DAYS-дневен % change, самият той
    percentile-ranked спрямо собствения trailing прозорец — self-calibrating
    спрямо конкретния режим, не фиксирана магнитуда (backtest потвърди: по-
    леки събития като Aug'24 yen carry unwind никога не прекосяват фиксиран
    % праг калибриран за GFC/COVID сериозност).
    """
    need = config.IEI_HYG_LOOKBACK_DAYS + config.IEI_HYG_ROC_WINDOW_DAYS + 1
    if len(ratio) < need:
        raise ValueError(f"недостатъчна история ({len(ratio)} дни, нужни ≥{need})")

    window_all = ratio.iloc[-(config.IEI_HYG_LOOKBACK_DAYS + 1):]
    current = float(window_all.iloc[-1])
    level_pct = _percentile_rank(window_all.iloc[:-1].tolist(), current)

    roc = ratio.pct_change(config.IEI_HYG_ROC_WINDOW_DAYS) * 100
    roc_window_all = roc.iloc[-(config.IEI_HYG_LOOKBACK_DAYS + 1):].dropna()
    current_roc = float(roc_window_all.iloc[-1])
    roc_pct = _percentile_rank(roc_window_all.iloc[:-1].tolist(), current_roc)

    spike = roc_pct >= config.IEI_HYG_ROC_SPIKE_PERCENTILE
    complacency = level_pct <= config.IEI_HYG_LEVEL_PERCENTILE_LOW

    if spike:
        status = "red"
    elif complacency:
        status = "yellow"
    else:
        status = "green"

    note = (" ⚠ рязък credit spread spike" if spike else
           (" (late-cycle complacency)" if complacency else ""))
    return {
        "name": "IEI/HYG (Credit Spread)", "value": round(current, 4),
        "level_percentile": level_pct, "roc_10d_pct": round(current_roc, 2),
        "roc_percentile": roc_pct, "spike": spike, "status": status,
        "label": f"IEI/HYG {current:.3f} ({level_pct:.0f}. percentile) · "
                 f"{config.IEI_HYG_ROC_WINDOW_DAYS}д RoC {current_roc:+.1f}% "
                 f"({roc_pct:.0f}. percentile){note}",
    }


def credit_spread_proxy() -> dict:
    """
    IEI/HYG — 3-7г Treasury спрямо High-Yield Corporate Bond ETF, established
    credit spread proxy. Backtest (Venci, 2026-08-2x, 4 известни кризисни
    прозореца — GFC 2007-08, late-2018 selloff, COVID crash 2020, Aug'24 yen
    carry unwind) потвърди паттърна directamente — виж _evaluate_credit_
    spread() и config.py IEI_HYG_* коментарите за пълния rationale.

    Hard override (виж build_thermometer): spike форсира Defensive, НЕЗАВИСИМ
    трети тригер до VIX>30/MOVE, не дублиране на MOVE логиката. MOVE мери
    имплицитна волатилност в UST опциите — bond PRICE volatility, деривативен
    пазар. IEI/HYG spike мери разширяване на CREDIT RISK PREMIUM-а между
    risk-free и high-yield — реален cash-bond пазар, компенсация за default
    риск, различен ъгъл на стреса. Двата индикатора могат легитимно да се
    разминат (MOVE спокоен, докато credit spreads вече горят, или обратното)
    — затова е трети независим тригер, не redundant echo на MOVE.
    """
    try:
        iei = yf.Ticker("IEI").history(period="3y")
        hyg = yf.Ticker("HYG").history(period="3y")
        if iei.empty or hyg.empty:
            raise ValueError("insufficient IEI/HYG history")
        if _is_stale(iei.index[-1]) or _is_stale(hyg.index[-1]):
            raise ValueError(f"stale data — IEI {iei.index[-1].date()} / "
                             f"HYG {hyg.index[-1].date()}")
        # FIX 2026-09-23: трети случай, който двете проверки по-горе не хващат —
        # непразен frame със СВЕЖ индекс, но NaN в Close. Потвърдено на 23.09:
        # Yahoo върна частичен бар за 22.09 (High/Low налични, Close = NaN), и
        # индикаторът излезе като видим "nan" вместо скрит. Случвало се е и на
        # 04.09. NaN = липсващи данни → hide, както при празен/застоял frame.
        if _nan_last_close(iei) or _nan_last_close(hyg):
            raise ValueError(f"NaN Close в последния ред — IEI {iei.index[-1].date()} / "
                             f"HYG {hyg.index[-1].date()}")

        common = iei.index.intersection(hyg.index)
        ratio = (iei.loc[common, "Close"] / hyg.loc[common, "Close"]).sort_index()
        return _evaluate_credit_spread(ratio)
    except Exception as e:
        print(f"[thermo] IEI/HYG credit spread failed: {e}")
        return {"name": "IEI/HYG (Credit Spread)", "value": None, "status": "yellow",
                "hide": True, "label": ""}


def market_breadth() -> dict:
    """
    Market Breadth (% над 40dMA) — 9-ти термометър индикатор. Собствено
    изчислен breadth proxy, inspired by T2108 методологията (Worden/TC2000
    — % NYSE тикъри над 40-дневната им MA), НО изчислен върху НАШИЯ ВЕЧЕ
    съществуващ universe (screener.build_universe() — S&P500+Nasdaq100+
    MidCap400), НЕ буквален NYSE T2108. Feasibility проверка 2026-08-15
    потвърди: няма готов безплатен T2108 feed (нито yfinance ^T2108/^NYSI/
    ^NYMO/^NYAD — всички 404, нито друг безплатен API — T2108 е proprietary
    TC2000/Worden). Explicit различно име навсякъде — nашият universe е по-
    широк и Nasdaq-тежък спрямо истинския NYSE-специфичен T2108, структурно
    различна (макар корелирана) мярка — не бива да се представя за буквален
    T2108. "methodology_note" по-долу се показва като tooltip в dashboard-а
    (виж dashboard.html.j2).

    Reuse на screener.build_universe() + established batch fetch паттърн
    (batch_size, group_by="ticker", threads=True, sleep между batch-овете —
    виж screener.technical_screen()/glb_screener.screen()). period="3mo" е
    достатъчно за 40-дневна MA, много по-лек payload от GLB-ския period="max".
    Empирично тествано 2026-08-15: 903 тикъра, 38s, 0 грешки, 0 rate limiting.

    Mean-reverting zoни (за разлика от повечето останали индикатори, "по-
    високо не е по-добре"):
      >80%    жълто — overbought, твърде много акции разтегнати над MA
      40-80%  зелено — здравословна ширина
      20-40%  жълто — слаба/тясна ширина (FIX 2026-09-28; до тогава зелено)
      10-20%  жълто — приближава капитулация
      <10%    "red" МЕХАНИЧНО (участва в regime броенето като останалите
              индикатори — краткосрочен breadth collapse си остава risk-off
              сигнал за самия термометър), НО текстовият тон е explicit
              contrarian bullish ("исторически bottoming зона"), не паника
              — приложено само към label текста, не към status полето
              (изричен избор — виж дискусията с юзъра, 2026-08-15).

    Graceful: провал на universe fetch, batch download, или под sanity
    прага BREADTH_MIN_VALID_TICKERS валидни тикъри → hide=True, same
    паттърн като move_index()/vix_term_structure().
    """
    try:
        universe = build_universe()
        if not universe:
            raise ValueError("празен universe")

        above, total = 0, 0
        for i in range(0, len(universe), config.BREADTH_BATCH_SIZE):
            batch = universe[i:i + config.BREADTH_BATCH_SIZE]
            try:
                data = yf.download(batch, period="3mo", progress=False,
                                   auto_adjust=True, group_by="ticker", threads=True)
            except Exception as e:
                print(f"[thermo] breadth batch {i} fetch грешка: {e}")
                continue
            for sym in batch:
                try:
                    df = data[sym].dropna() if len(batch) > 1 else data.dropna()
                    if len(df) < 40:
                        continue
                    close = df["Close"]
                    sma40 = float(close.rolling(40).mean().iloc[-1])
                    last = float(close.iloc[-1])
                    if math.isnan(sma40):
                        continue
                    total += 1
                    if last > sma40:
                        above += 1
                except Exception:
                    continue
            time.sleep(1)  # не дразним Yahoo, same дисциплина като screener.py

        if total < config.BREADTH_MIN_VALID_TICKERS:
            raise ValueError(f"твърде малко валидни тикъри ({total}) за надежден %")

        pct = above / total * 100
    except Exception as e:
        print(f"[thermo] Market Breadth failed: {e}")
        return {"name": "Market Breadth (% над 40dMA)", "value": None,
                "status": "yellow", "hide": True, "label": ""}

    if pct < config.BREADTH_CAPITULATION_THRESHOLD:
        status, note = "red", "extreme капитулация — исторически bottoming зона, contrarian bullish"
    elif pct < config.BREADTH_HEALTHY_LOW:
        status, note = "yellow", "приближава капитулация"
    elif pct < config.BREADTH_WEAK_THRESHOLD:
        status, note = "yellow", "слаба/тясна ширина"  # FIX 2026-09-28, виж config.py
    elif pct <= config.BREADTH_OVERBOUGHT_THRESHOLD:
        status, note = "green", "здравословна ширина"
    else:
        status, note = "yellow", "overbought — разтегнато над 40dMA"

    return {
        "name": "Market Breadth (% над 40dMA)", "value": round(pct, 1),
        "universe_size": total, "status": status,
        "label": f"{pct:.1f}% над 40dMA ({note})",
        "methodology_note": ("Inspired by T2108 методология (Worden/TC2000), но изчислено "
                             "върху собствен universe (S&P500+Nasdaq100+MidCap400) — "
                             "НЕ буквален NYSE T2108."),
    }


def _breadth_divergence(indicators: list[dict]) -> None:
    """
    FIX 2026-09-28: бележка при разминаване — SPY близо до 52-седмичния връх,
    а под BREADTH_WEAK_THRESHOLD% от акциите са над 40dMA (тесен пазар).
    Само етикет + поле "divergence"; статусът и броенето не се пипат.
    """
    spy = next((i for i in indicators if i.get("name") == "SPY тренд"), None)
    br = next((i for i in indicators if i.get("name", "").startswith("Market Breadth")), None)
    if not (spy and br) or spy.get("hide") or br.get("hide"):
        return
    gap, val = spy.get("pct_from_high"), br.get("value")
    if gap is None or val is None:
        return
    if val < config.BREADTH_WEAK_THRESHOLD and gap <= config.SPY_NEAR_HIGH_PCT:
        br["divergence"] = True
        br["label"] += (f" · ⚠ разминаване: SPY е на {gap:.1f}% от 52-седм. връх, "
                        f"а ширината е под {config.BREADTH_WEAK_THRESHOLD:.0f}%")


# ══════════════════════════════════════════════════════════════════════════
# Хистерезис за delta/RoC-базираните override-и (MOVE spike, IEI/HYG spike)
# FIX 2026-10-01 (т.1 от прегледа на 01.10):
#
# И двата spike флага идват от прозорец, който се плъзга всеки ден (MOVE:
# today − преди точно 7 календарни дни; IEI/HYG: 10-дневна RoC, percentile-
# ранкната спрямо rolling прозорец) — щом еднократният скок "изпадне" от
# прозореца, флагът пада САМ, дори нивото на стрес да не се е реално
# успокоило (напр. 01.10: MOVE=110, вече под червения праг 150 — само spike
# флагът държи override-а; той би паднал до ~седмица чисто календарно, без
# MOVE да мръдне). "2 поредни дни под прага" НЕ поправя тази динамика (пак е
# чисто календарна по решение — виж прегледа, "без логика за отдръпване от
# пика") — пази override-а само от едно гранично отчитане (whipsaw), а
# exit_rule текстът вече казва честно какво точно значи "отпада", вместо да
# го представя като реално успокояване.
_OVERRIDE_STATE_FILE = config.DATA_DIR / "regime_override_state.json"
_REGIME_SEVERITY = {"Offensive": 0, "Defensive": 1, "Cash": 2}


def _load_override_state() -> dict:
    """
    FIX 2026-10-01 (отговор на прегледа на партида 1, т.1): fail-safe при
    липсващ/повреден state файл — ВИНАГИ връща dict (никога не гърми нагоре),
    и логва изрично двата различни случая (липсва vs повреден), за да се
    вижда в Actions лога, а не да се предполага тихо.
    """
    if not _OVERRIDE_STATE_FILE.exists():
        print(f"[thermo] override state файл липсва ({_OVERRIDE_STATE_FILE.name}) — "
              f"fail-safe старт: override-ите тръгват все едно днес е 1-ви ден под "
              f"прага (остават активни, не се третират като изтекли)")
        return {}
    try:
        data = json.loads(_OVERRIDE_STATE_FILE.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"очакван dict на top-level, получен {type(data).__name__}")
        return data
    except Exception as e:
        print(f"[thermo] ⚠ override state файл повреден ({type(e).__name__}: {e}) — "
              f"fail-safe: override-ите тръгват все едно днес е 1-ви ден под прага "
              f"(остават активни, не се третират като изтекли)")
        return {}


def _save_override_state(state: dict) -> None:
    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _OVERRIDE_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[thermo] override hysteresis state write failed: {e}")


def _hysteresis_effective(key: str, raw_today: bool, today_iso: str) -> tuple[bool, int]:
    """
    streak_below = последователни дни (ВКЛЮЧИТЕЛНО днес), в които raw флагът
    е бил False. Override-ът остава ефективно активен, докато streak_below < 2
    — един граничен ден не го маха, трябва ВТОРИ пореден ден под прага.
    Идемпотентно спрямо повторен run СЪЩИЯ ден (last_date проверка) — ръчно
    повторно пускане същия ден не брои двойно.

    Fail-safe по конструкция (виж _load_override_state): липсващ/повреден
    файл → празен state → всеки ключ стартира от streak_below=0 "преди днес",
    т.е. ДНЕС винаги излиза като streak<2 → override ефективно активен,
    НЕЗАВИСИМО от raw_today. Единственият начин override да излезе неактивен
    е при ЗДРАВ файл, потвърждаващ 2 реални поредни дни под прага — загубата
    на данни никога не бърза да го изключи, най-много го държи активен по-дълго.
    Отделно: ако конкретен запис в state е с повреден формат (не dict), същият
    fail-safe се прилага САМО за този ключ, с лог.
    """
    state = _load_override_state()
    raw_entry = state.get(key)
    if raw_entry is not None and not isinstance(raw_entry, dict):
        print(f"[thermo] ⚠ override state за '{key}' е в повреден формат ({raw_entry!r}) — "
              f"fail-safe reset само за този ключ")
        raw_entry = None
    entry = raw_entry or {"streak_below": 0, "last_date": None}
    if entry.get("last_date") != today_iso:
        prev_streak = entry.get("streak_below", 0)
        entry = {"streak_below": 0 if raw_today else prev_streak + 1, "last_date": today_iso}
        state[key] = entry
        _save_override_state(state)
    effective = raw_today or entry.get("streak_below", 0) < 2
    return effective, entry.get("streak_below", 0)


def _merge_regime(count_regime: str, count_reason: str, counts: str,
                  overrides: list[dict]) -> tuple[str, str, str]:
    """
    Чиста функция (без мрежа) — FIX 2026-10-01 (т.1 от прегледа на 01.10):
    override-ите само ПОВДИГАТ пода до Defensive, не трябва да смекчават
    регим, който броенето вече е определило като по-строг (01.10: count=Cash,
    overrides=MOVE+IEI/HYG → преди този фикс финалният regime ставаше
    "Defensive", по-мек от самото броене). Изнесена отделно от build_thermometer,
    за да се тества директно с реални/синтетични (count_regime, overrides)
    комбинации, без да се мокват деветте мрежови indicator fetch-а.
    """
    if not overrides:
        return count_regime, count_reason, f"Режимът е по броенето ({counts}). Няма активен автоматичен override."

    override_exit_desc = "; ".join(f"{o['trigger']}: {o['exit_condition']}" for o in overrides)
    if _REGIME_SEVERITY[count_regime] > _REGIME_SEVERITY["Defensive"]:
        # единственият count_regime по-строг от Defensive е "Cash" (reds >= 3) —
        # прагът за подобрение до Defensive е винаги "под 3 червени"
        act = [o["trigger"] for o in overrides if o.get("state", "active") == "active"]
        hyst = [o["trigger"] for o in overrides if o.get("state") == "hysteresis"]
        parts = []
        if act:
            parts.append(f"override-и също активни ({', '.join(act)})")
        if hyst:
            parts.append(f"в хистерезис ({', '.join(hyst)})")
        regime = count_regime
        reason = (f"{count_reason} — {'; '.join(parts)}; те сами биха "
                 f"форсирали само Defensive, но броенето вече е по-строго ({count_regime}).")
        exit_rule = (
            f"Регимът в момента се определя от броенето ({count_reason}), не от "
            f"override-ите — те сами биха дали само Defensive. За подобрение трябва "
            f"ИЛИ броенето да падне под 3 червени, ИЛИ override-ите да паднат: "
            f"{override_exit_desc}.")
    else:
        regime = "Defensive"
        # първо реално активният тригер (списъкът е сортиран active-first), след
        # него тези в хистерезис — не губим информацията, че още държат override
        active = [o for o in overrides if o.get("state", "active") == "active"]
        hyst = [o for o in overrides if o.get("state") == "hysteresis"]
        lead = (active or hyst)[0]
        reason = lead["text"]
        hyst_rest = hyst if active else hyst[1:]
        if hyst_rest:
            reason += (" · в хистерезис: " if active else " · също в хистерезис: ") + \
                      "; ".join(o["text"] for o in hyst_rest)
        exit_rule = (
            f"Override-ът пада, когато ВСИЧКИ условия отпаднат: {override_exit_desc}. "
            f"След това режимът се определя от броенето — в момента то дава "
            f"{count_regime} ({counts}).")
    return regime, reason, exit_rule


def build_thermometer(macro: dict, today: dt.date | None = None) -> dict:
    """
    Сглобява 9-те индикатора + правилото за режим (8-ми, Market Breadth,
    добавен 2026-08-15; 9-ти, IEI/HYG Credit Spread, добавен 2026-08-25 —
    виж market_breadth()/credit_spread_proxy() докстринговете за пълния
    methodology rationale):
    - VIX > 30 → задължително Defensive (Секция 8)
    - MOVE > 150 или рязък седмичен скок → задължително Defensive (институционален
      стрес в колатералната система бие останалите сигнали, аналогично на VIX правилото)
    - IEI/HYG spike (10д RoC в топ percentile) → задължително Defensive — трети,
      НЕЗАВИСИМ hard-override тригер до VIX/MOVE (credit risk premium, не bond
      price volatility — виж credit_spread_proxy() докстринга защо не е
      дублиране на MOVE логиката); 4/4 известни кризи, 0 false positives в
      backtest-а (Venci, 2026-08-2x)
    - 4+ зелени при 0 червени → Offensive; 3+ червени → Cash; 2 червени → Defensive;
      всичко останало → Defensive (недостатъчно потвърждение)
    Броенето е само върху ВИДИМИТЕ индикатори (hide=True не участва); жълтите и
    скритите се отчитат изрично в regime_reason. Sizing factor пада за всеки
    не-Offensive режим, не само за принудителните.
    """
    spread = macro.get("spread_2s10s", {})
    nl = macro.get("net_liquidity", {})

    # FIX 2026-07-15: паднал FRED даваше status="unknown" → != "inverted" → GREEN,
    # т.е. фалшив зелен сигнал от липсващи данни. Сега: None → hide (unknown).
    if spread.get("value") is None:
        spread_ind = {"name": "2Y/10Y спред", "value": None,
                      "status": "yellow", "hide": True, "label": ""}
    else:
        spread_ind = {
            "name": "2Y/10Y спред",
            "value": spread.get("value"),
            "status": "red" if spread.get("status") == "inverted" else "green",
            "label": (f"{spread.get('value', '?')}% "
                      f"({'инверсия' if spread.get('status') == 'inverted' else 'нормален'}, "
                      f"{spread.get('direction', '')})"),
        }
    if nl.get("value") is None:
        nl_ind = {"name": "Fed Net Liquidity", "value": None,
                  "status": "yellow", "hide": True, "label": ""}
    else:
        nl_ind = {
            "name": "Fed Net Liquidity",
            "value": nl.get("value"),
            "status": "green" if nl.get("trend") == "up" else
                      ("red" if nl.get("trend") == "down" else "yellow"),
            "label": f"${nl.get('value', '?')} млрд ({'↑' if nl.get('trend') == 'up' else '↓'})",
        }

    indicators = [spy_trend(), vix_level(), market_put_call(), spread_ind,
                  nl_ind, move_index(), vix_term_structure(), credit_spread_proxy()]
    if config.ENABLE_MARKET_BREADTH:
        indicators.append(market_breadth())
        _breadth_divergence(indicators)

    # FIX 2026-07-15: броим само ВИДИМИТЕ индикатори; жълтите и скритите се
    # отчитат изрично в съобщението, вместо да изчезват тихо от "X зелени / Y червени".
    visible = [i for i in indicators if not i.get("hide")]
    visible_count = len(visible)
    hidden_count = len(indicators) - visible_count
    greens = sum(1 for i in visible if i["status"] == "green")
    yellows = sum(1 for i in visible if i["status"] == "yellow")
    reds = sum(1 for i in visible if i["status"] == "red")
    counts = f"{greens} зелени / {yellows} жълти / {reds} червени от {visible_count} видими"
    if hidden_count:
        counts += f" ({hidden_count} скрити — невалидни/застояли данни)"

    vix_val = next((i["value"] for i in indicators if i["name"] == "VIX"), None)
    move_ind = next((i for i in indicators if i["name"] == "MOVE (Bond Vol)"), None)
    move_val = move_ind.get("value") if move_ind else None
    move_spike_raw = bool(move_ind and move_ind.get("spike"))
    credit_ind = next((i for i in indicators if i["name"] == "IEI/HYG (Credit Spread)"), None)
    credit_spike_raw = bool(credit_ind and credit_ind.get("spike"))

    # хистерезис САМО върху delta/RoC-базираните spike флагове (виж бележката
    # над build_thermometer) — VIX и MOVE-ниво нямат "ages out" артефакт, не
    # се пипат
    today_iso = (today or dt.date.today()).isoformat()  # today — само за тестове
    move_spike, move_spike_streak = _hysteresis_effective("move_spike", move_spike_raw, today_iso)
    credit_spike, credit_spike_streak = _hysteresis_effective("credit_spike", credit_spike_raw, today_iso)

    vix_forces_defensive = vix_val is not None and vix_val > config.VIX_DEFENSIVE_THRESHOLD
    move_forces_defensive = move_val is not None and (move_val > config.MOVE_RED_THRESHOLD or move_spike)

    # Режимът САМО по броенето — изчислява се винаги, дори при override.
    # FIX 2026-07-15: премахнат недокументиран fallback "greens >= 3 → Offensive",
    # който противоречеше на правилото в docstring-а ("4+ зелени → Offensive; иначе
    # Defensive") и на 2026-07-15 произведе Offensive при 3 зелени + 1 (фалшив) червен.
    if greens >= 4 and reds == 0:
        count_regime, count_reason = "Offensive", counts
    elif reds >= 3:
        count_regime, count_reason = "Cash", f"{counts} — капиталът е позиция"
    elif reds >= 2:
        count_regime, count_reason = "Defensive", f"{counts} — намален риск"
    else:
        count_regime, count_reason = "Defensive", f"{counts} — недостатъчно потвърждение за Offensive"

    # FIX 2026-09-25: всички АКТИВНИ override-и, всеки с условието си за изход,
    # изчислено от кода. Дотук условието не съществуваше никъде — промптът
    # виждаше value/delta/spike, но не и правилото, и на 25.09 макро текстът
    # измисли "единственото, което би отменило Defensive, е MOVE под 85". 85 не
    # е праг никъде в кода; реалният изход дори не изисква спад — само MOVE да
    # спре да расте. Същият клас като старите "20-и percentile" и "2026-09-15":
    # AI-то формулира условия, които не идват от кода. Условията са събрани в
    # списък, защото при два активни override-а изходът изисква ДВЕТЕ да паднат.
    overrides: list[dict] = []
    if vix_forces_defensive:
        overrides.append({
            "trigger": "VIX",
            "text": f"VIX {vix_val:.0f} > {config.VIX_DEFENSIVE_THRESHOLD:.0f} — автоматичен Defensive режим, sizing −50%",
            "exit_condition": (f"VIX падне до {config.VIX_DEFENSIVE_THRESHOLD:.0f} или под "
                               f"(сега {vix_val:.1f})"),
        })
    if move_forces_defensive:
        exits = []
        if move_val > config.MOVE_RED_THRESHOLD:
            exits.append(f"MOVE падне до {config.MOVE_RED_THRESHOLD:.0f} пункта или под "
                         f"(сега {move_val:.1f})")
        if move_spike:
            # FIX 2026-10-01: честен текст за хистерезиса (виж бележката над
            # build_thermometer) — "седмичният ръст се забави" звучеше като
            # реално успокояване; реално делтата пада САМА до ~седмица чисто
            # защото прозорецът се плъзга, дори MOVE да стои непроменено високо
            exits.append(
                f"седмичната делта (сега {move_ind.get('delta_1w'):+.1f} пункта) да е под "
                f"+{config.MOVE_SPIKE_WEEKLY_DELTA:.0f} пункта два поредни дни (хистерезис — "
                f"в момента {min(move_spike_streak, 2)}/2); без нов скок това става до около "
                "седмица — това е прозорецът, не непременно реално успокояване на стреса")
        # FIX 2026-10-02 (т.1 от прегледа на 02.10): текстът описва РЕАЛНОТО
        # състояние. Преди, при хистерезис (raw spike=False, ниво под 150), падаше
        # в else-клона на "рязък скок" и казваше "MOVE 108 > 150" — невярно
        # (108 < 150, MOVE е жълт). Три различни състояния, три различни текста.
        level_active = move_val > config.MOVE_RED_THRESHOLD
        if level_active or move_spike_raw:
            head = f"MOVE {move_val:.0f}"
            if level_active:
                head += f" > {config.MOVE_RED_THRESHOLD:.0f}"
            if move_spike_raw:
                head += (" и " if level_active else " ") + (
                    f"(рязък седмичен скок, {move_ind.get('delta_1w'):+.1f} пункта)")
            move_text = (head + " — стрес в колатералната система (UST), "
                         "автоматичен Defensive режим, sizing −50%")
            move_state = "active"
        else:
            move_text = (f"MOVE {move_val:.0f}: спайкът отшумява (делта "
                         f"{move_ind.get('delta_1w'):+.1f} пункта, под прага +"
                         f"{config.MOVE_SPIKE_WEEKLY_DELTA:.0f}), хистерезис "
                         f"{min(move_spike_streak, 2)}/2 — override още активен, sizing −50%")
            move_state = "hysteresis"
        overrides.append({
            "trigger": "MOVE",
            "state": move_state,
            "text": move_text,
            "exit_condition": " И ".join(exits),
        })
    if credit_spike:
        if credit_spike_raw:
            credit_text = (f"IEI/HYG credit spread spike ({credit_ind['roc_10d_pct']:+.1f}% за "
                           f"{config.IEI_HYG_ROC_WINDOW_DAYS}д, {credit_ind['roc_percentile']:.0f}. percentile) — "
                           "рязко разширяване на credit risk premium, автоматичен Defensive режим, sizing −50%")
            credit_state = "active"
        else:
            credit_text = (f"IEI/HYG: spike-ът отшумява ({credit_ind['roc_10d_pct']:+.1f}% за "
                           f"{config.IEI_HYG_ROC_WINDOW_DAYS}д, {credit_ind['roc_percentile']:.0f}. percentile, "
                           f"под {config.IEI_HYG_ROC_SPIKE_PERCENTILE:.0f}.), хистерезис "
                           f"{min(credit_spike_streak, 2)}/2 — override още активен, sizing −50%")
            credit_state = "hysteresis"
        overrides.append({
            "trigger": "IEI/HYG",
            "state": credit_state,
            "text": credit_text,
            "exit_condition": (
                f"{config.IEI_HYG_ROC_WINDOW_DAYS}-дневната RoC percentile (сега "
                f"{credit_ind['roc_percentile']:.0f}.) да е под {config.IEI_HYG_ROC_SPIKE_PERCENTILE:.0f}. "
                f"percentile два поредни дни (хистерезис — в момента {min(credit_spike_streak, 2)}/2); "
                f"без нов скок това става до около {config.IEI_HYG_ROC_WINDOW_DAYS} дни — това е "
                "прозорецът на изчислението, не непременно реално успокояване"),
        })

    # реално активните тригери първо, тези в хистерезис след тях (стабилна
    # сортировка — VIX/MOVE/IEI-HYG редът се пази вътре във всяка група)
    overrides.sort(key=lambda o: o.get("state", "active") != "active")

    regime, reason, exit_rule = _merge_regime(count_regime, count_reason, counts, overrides)

    # FIX 2026-07-15: преди sizing_factor падаше САМО при принудителен Defensive
    # (VIX/MOVE); нормален Defensive/Cash по броя сигнали оставаше на 1.0 —
    # противоречие със семантиката на режима. Сега всеки не-Offensive → фактор.
    sizing_factor = 1.0 if regime == "Offensive" else config.DEFENSIVE_SIZING_FACTOR

    return {"indicators": indicators, "regime": regime,
            "regime_reason": reason, "sizing_factor": sizing_factor,
            # FIX 2026-09-25: броенето винаги, override-ите с изхода си, и какво
            # би дало броенето само по себе си — за header-а и за макро промпта.
            "counts": counts, "overrides": overrides,
            "regime_by_count": count_regime,
            "exit_rule": exit_rule,
            }


if __name__ == "__main__":
    import json
    from macro_layer import collect_macro_layer
    print(json.dumps(build_thermometer(collect_macro_layer()),
                     indent=2, ensure_ascii=False, default=str))
