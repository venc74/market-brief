"""
Пазарен термометър (Секция 4).
Осем индикатора + обща препоръка Offensive / Defensive / Cash.
Всеки индикатор връща {value, status, label} където status ∈ green/yellow/red.
"""
from __future__ import annotations
import datetime as dt
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
        return {
            "name": "SPY тренд", "value": round(price, 2),
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
        week_ago = float(hist["Close"].iloc[-6])
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
            "label": f"MOVE {val:.0f} ({delta:+.0f}/седмица){spike_note}",
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
      20-80%  зелено — здравословна ширина
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


def build_thermometer(macro: dict) -> dict:
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
    move_spike = move_ind.get("spike") if move_ind else False
    credit_ind = next((i for i in indicators if i["name"] == "IEI/HYG (Credit Spread)"), None)
    credit_spike = bool(credit_ind and credit_ind.get("spike"))

    vix_forces_defensive = vix_val is not None and vix_val > config.VIX_DEFENSIVE_THRESHOLD
    move_forces_defensive = move_val is not None and (move_val > config.MOVE_RED_THRESHOLD or move_spike)

    # FIX 2026-07-15: премахнат недокументиран fallback "greens >= 3 → Offensive",
    # който противоречеше на правилото в docstring-а ("4+ зелени → Offensive; иначе
    # Defensive") и на 2026-07-15 произведе Offensive при 3 зелени + 1 (фалшив) червен.
    if vix_forces_defensive:
        regime, reason = "Defensive", f"VIX {vix_val:.0f} > 30 — автоматичен Defensive режим, sizing −50%"
    elif move_forces_defensive:
        regime, reason = "Defensive", (
            f"MOVE {move_val:.0f}" + (" (рязък седмичен скок)" if move_spike else " > 150")
            + " — стрес в колатералната система (UST), автоматичен Defensive режим, sizing −50%")
    elif credit_spike:
        regime, reason = "Defensive", (
            f"IEI/HYG credit spread spike ({credit_ind['roc_10d_pct']:+.1f}% за "
            f"{config.IEI_HYG_ROC_WINDOW_DAYS}д, {credit_ind['roc_percentile']:.0f}. percentile) — "
            "рязко разширяване на credit risk premium, автоматичен Defensive режим, sizing −50%")
    elif greens >= 4 and reds == 0:
        regime, reason = "Offensive", counts
    elif reds >= 3:
        regime, reason = "Cash", f"{counts} — капиталът е позиция"
    elif reds >= 2:
        regime, reason = "Defensive", f"{counts} — намален риск"
    else:
        regime, reason = "Defensive", f"{counts} — недостатъчно потвърждение за Offensive"

    # FIX 2026-07-15: преди sizing_factor падаше САМО при принудителен Defensive
    # (VIX/MOVE); нормален Defensive/Cash по броя сигнали оставаше на 1.0 —
    # противоречие със семантиката на режима. Сега всеки не-Offensive → фактор.
    sizing_factor = 1.0 if regime == "Offensive" else config.DEFENSIVE_SIZING_FACTOR

    return {"indicators": indicators, "regime": regime,
            "regime_reason": reason, "sizing_factor": sizing_factor}


if __name__ == "__main__":
    import json
    from macro_layer import collect_macro_layer
    print(json.dumps(build_thermometer(collect_macro_layer()),
                     indent=2, ensure_ascii=False, default=str))
