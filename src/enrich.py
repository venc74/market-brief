"""
Обогатяване на финалистите: earnings календар (3.2) и опции данни (3.6).
IV Rank изисква история — системата си я гради сама: всеки ден записва
ATM IV на всеки разглеждан тикър в data/iv_history.json. Докато се
натрупа година, IVR се изчислява спрямо наличния прозорец и се маркира
като 'partial'.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

# v2 надстройка — нови източници (Секция 3.1–3.4 + dataroma)
from src import magic_formula, borrow_data, unusual_options, splits_calendar, dataroma
from src import net_utils


# ──────────────────────────────────────────────────────────────────────────
# Earnings (Секция 3.2 + правило за blackout от Секция 8)
# + Earnings Season Recap (Секция [нова], v1 — виж дискусията 2026-08-12)
# ──────────────────────────────────────────────────────────────────────────
def _nan_to_none(v):
    """
    NaN -> None; иначе каства към native Python float (не numpy.float64 —
    numpy.float64 Е instance на float в Python, isinstance проверката минава,
    но json.dumps(..., default=str) би го сериализирал като STRING, не число,
    ако не се кастне явно тук; потвърдено на живо: EPS Estimate/Surprise(%)
    от pandas Series идват като numpy.float64, Reported EPS вече минаваше
    през round(float(...), 2) отделно и затова не показваше проблема).
    """
    if v is None:
        return None
    f = float(v)
    return None if f != f else f  # f != f само за NaN


def _quarter_dict(date_ts, row) -> dict:
    """Единичен ред от get_earnings_dates() -> плосък dict, EPS частта."""
    return {
        "date": date_ts.date().isoformat(),
        "eps_estimate": _nan_to_none(row.get("EPS Estimate")),
        "eps_actual": _nan_to_none(row.get("Reported EPS")),
        "eps_surprise_pct": _nan_to_none(row.get("Surprise(%)")),
    }


def _find_yoy_row(past_sorted, ref_date: "dt.date"):
    """
    Намира TIMESTAMP-а на реда в past_sorted (МИНАЛИ редове), чиято дата е
    НАЙ-БЛИЗО до ref_date - 365 дни, в рамките на
    config.EARNINGS_YOY_TOLERANCE_DAYS. НЕ фиксирана позиция "N реда назад"
    — фискалните календари могат да се разминават между компании (виж
    дискусията 2026-08-13). Връща None ако няма ред в толеранса.
    """
    if not len(past_sorted):
        return None
    target = ref_date - dt.timedelta(days=365)
    candidates = [(abs((ts.date() - target).days), ts)
                 for ts in past_sorted.index if ts.date() != ref_date]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    best_diff, best_ts = candidates[0]
    return best_ts if best_diff <= config.EARNINGS_YOY_TOLERANCE_DAYS else None


def _reactions_for_dates(sym: str, dates: list[str]) -> dict[str, dict]:
    """
    Ценова реакция (close-to-close + обем спрямо предходните 5 дни) за
    НЯКОЛКО дати наведнъж — ЕДИН .history() fetch, покриващ целия диапазон,
    вместо отделен fetch на дата (обичайно до 5 дати: 4 тримесечия + YoY
    ред) — same дух на пестене на мрежови заявки като reuse-а на
    get_earnings_dates() (виж FIX 2026-08-12).

    v1 приближение (договорено 2026-08-12): earnings датата = реакционния
    ден, без BMO/AMC разграничение. При AMC (after market close) отчет
    реалната реакция е на СЛЕДВАЩИЯ ден — приемлив компромис за v1 срещу
    допълнителни network calls; прецизиране само ако на практика видим
    системно подвеждащи "нулеви" реакции.

    Graceful: провал на fetch-а → {} (нито една дата не получава реакция,
    EPS частта на recap-а си остава валидна без нея).
    """
    if not dates:
        return {}
    try:
        parsed = [dt.date.fromisoformat(d) for d in dates]
        start = (min(parsed) - dt.timedelta(days=10)).isoformat()
        end = (max(parsed) + dt.timedelta(days=5)).isoformat()
        hist = net_utils.fetch_with_timeout(
            lambda: yf.Ticker(sym).history(start=start, end=end))
        if hist is None or hist.empty:
            return {}
        idx_dates = [ts.date() for ts in hist.index]
        out = {}
        for d, ed in zip(dates, parsed):
            if ed not in idx_dates:
                continue
            i = idx_dates.index(ed)
            if i == 0:
                continue
            close_today = float(hist["Close"].iloc[i])
            close_prev = float(hist["Close"].iloc[i - 1])
            vol_today = float(hist["Volume"].iloc[i])
            vol_avg = float(hist["Volume"].iloc[max(0, i - 5):i].mean())
            out[d] = {
                "reaction_pct": round((close_today / close_prev - 1) * 100, 2),
                "reaction_volume_ratio": round(vol_today / vol_avg, 2) if vol_avg else None,
            }
        return out
    except Exception as e:
        print(f"[enrich] earnings reactions {sym}: {e}")
        return {}


def _quality(eps_surprise_pct, reaction_pct) -> str | None:
    """
    3-way traffic light за иконата (потвърдено 2026-08-13):
      зелено  = EPS beat  И  позитивна реакция (и двете добри)
      червено = EPS miss  И  негативна реакция (и двете лоши)
      жълто   = разминаване в която и да е посока (beat+negative reaction,
                ИЛИ miss+positive reaction) — точно несъответствието,
                което трябва да е видимо на пръв поглед, не общ "средно"
    Граничен случай (потвърдено): точно 0% surprise се брои за "beat"
    страна, точно 0.0% реакция се брои за "позитивна" страна (>= 0 и за
    двете) — никакво недефинирано трето поведение на границата.
    """
    if eps_surprise_pct is None or reaction_pct is None:
        return None
    beat = eps_surprise_pct >= 0
    positive = reaction_pct >= 0
    if beat and positive:
        return "green"
    if not beat and not positive:
        return "red"
    return "yellow"


def earnings_info(sym: str) -> dict:
    out = {"next_earnings": None, "days_to_earnings": None,
           "in_blackout": False, "eps_estimate": None, "recap": None}
    try:
        tk = yf.Ticker(sym)
        cal = tk.calendar
        ed = None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or []
            if dates:
                ed = dates[0]
        # FIX 2026-07-15: Yahoo календарът понякога връща ПОСЛЕДНИЯ (минал) отчет
        # (ALL: 2026-04-29 при днешна дата 2026-07-15 → days=-77 → "няма blackout").
        # Минала дата се отхвърля и падаме към get_earnings_dates() fallback-а.
        if ed is not None:
            if isinstance(ed, dt.datetime):
                ed = ed.date()
            if ed < dt.date.today():
                print(f"[enrich] earnings {sym}: календарът върна минала дата "
                      f"{ed} — падам към get_earnings_dates()")
                ed = None

        # FIX 2026-08-12 (Earnings Season Recap, Case 1): df се тегли БЕЗУСЛОВНО
        # сега (преди: само при calendar fallback) — recap-ът (миналите редове
        # от СЪЩАТА DataFrame) е нужен независимо дали tk.calendar вече е дал
        # валидна бъдеща дата.
        df = net_utils.fetch_with_timeout(lambda: tk.get_earnings_dates(limit=8))
        if ed is None and df is not None and len(df):
            future = df[df.index > dt.datetime.now(df.index.tz)]
            if len(future):
                # .min() = най-близката бъдеща дата, независимо от реда на сортиране
                ed = future.index.min().date()
        if ed is not None:
            if isinstance(ed, dt.datetime):
                ed = ed.date()
            days = (ed - dt.date.today()).days
            # 5 РАБОТНИ дни ≈ 7 календарни
            out.update({
                "next_earnings": ed.isoformat(),
                "days_to_earnings": days,
                "in_blackout": 0 <= days <= 7,
            })
        info = tk.info or {}
        out["eps_estimate"] = info.get("epsCurrentYear") or info.get("forwardEps")

        out["recap"] = earnings_recap(sym)
    except Exception as e:
        print(f"[enrich] earnings {sym}: {e}")
    return out


def earnings_recap(sym: str) -> dict | None:
    """
    FIX 2026-08-13: единна recap функция за Case 1 (Action картата) И Case 2
    (track record) — consolidation след премахването на entry_date филтъра.
    Двата UI пътя вече имат идентична логика (recency праг), единствената
    разлика беше entry_date филтъра, който вече не съществува — виж
    дискусията 2026-08-13.

    Самостоятелна (собствен get_earnings_dates() fetch) — earnings_info()
    я вика отделно от собствената си calendar/get_earnings_dates() логика
    за next_earnings/days_to_earnings/in_blackout (ТЯХ трябва да работят
    ВСЕКИ ден, не само когато има скорошен отчет — затова остават отделни,
    не се delegate-ват на recap-а).

    Recency праг: връща None ЦЯЛОСТНО (не само display), ако последният
    отчет е по-стар от config.EARNINGS_RECAP_RECENCY_DAYS дни — пести
    мрежовите заявки за multi-quarter история/реакции на дни, в които
    recap-ът така или иначе няма да се покаже.

    Структура на резултата:
      quality: "green"/"yellow"/"red"/None (виж _quality)
      quarters: до 4 обекта {date, eps_estimate, eps_actual,
                eps_surprise_pct, reaction_pct, reaction_volume_ratio},
                най-новото първо
      yoy: same структура за тримесечието ПРЕДХОДНАТА ГОДИНА спрямо
           quarters[0] (търсено по близост, не фиксирана позиция — виж
           _find_yoy_row), или None
      yoy_summary: {current_date, yoy_date, eps_current, eps_yoy,
                    yoy_growth_pct} или None (division-by-zero guard, ако
                    eps_yoy е 0)
      forward: {next_earnings, days_to_earnings, in_blackout,
                consensus_eps, yoy_date, yoy_eps, expected_growth_pct}
                или None — консенсус EPS за следващия отчет вече е в
                future редовете на СЪЩИЯ df (потвърдено 2026-08-13),
                нулев допълнителен network call за тази част.

    Graceful: провал/липсваща история/твърде стар последен отчет → None.
    """
    try:
        df = net_utils.fetch_with_timeout(
            lambda: yf.Ticker(sym).get_earnings_dates(limit=16))
        if df is None or not len(df):
            return None

        now = dt.datetime.now(df.index.tz)
        past = df[df.index <= now].sort_index(ascending=False)
        if not len(past):
            return None

        latest_date = past.index[0].date()
        if (dt.date.today() - latest_date).days > config.EARNINGS_RECAP_RECENCY_DAYS:
            return None
        if _nan_to_none(past.iloc[0].get("Reported EPS")) is None:
            return None  # отчетен ден е минал, но данните още не са публикувани

        # ── Последните до 4 тримесечия ───────────────────────────────────
        quarters_slice = past.iloc[:4]
        quarters = [_quarter_dict(quarters_slice.index[i], quarters_slice.iloc[i])
                   for i in range(len(quarters_slice))
                   if _nan_to_none(quarters_slice.iloc[i].get("Reported EPS")) is not None]
        if not quarters:
            return None

        # ── YoY ред спрямо най-новото тримесечие (quarters[0]) ────────────
        yoy_ts = _find_yoy_row(past, quarters_slice.index[0].date())
        yoy = _quarter_dict(yoy_ts, past.loc[yoy_ts]) if yoy_ts is not None else None
        yoy_summary = None
        if yoy is not None and quarters[0]["eps_actual"] is not None and yoy["eps_actual"]:
            eps_cur, eps_yoy = quarters[0]["eps_actual"], yoy["eps_actual"]
            yoy_summary = {
                "current_date": quarters[0]["date"], "yoy_date": yoy["date"],
                "eps_current": eps_cur, "eps_yoy": eps_yoy,
                "yoy_growth_pct": round((eps_cur - eps_yoy) / abs(eps_yoy) * 100, 1),
            }

        # ── Forward-looking консенсус блок ────────────────────────────────
        future = df[df.index > now].sort_index()
        forward = None
        if len(future):
            f_ts = future.index[0]
            f_date = f_ts.date()
            days = (f_date - dt.date.today()).days
            consensus = _nan_to_none(future.iloc[0].get("EPS Estimate"))
            forward = {
                "next_earnings": f_date.isoformat(), "days_to_earnings": days,
                "in_blackout": 0 <= days <= 7, "consensus_eps": consensus,
            }
            f_yoy_ts = _find_yoy_row(past, f_date)
            if f_yoy_ts is not None and consensus is not None:
                f_yoy_eps = _nan_to_none(past.loc[f_yoy_ts].get("Reported EPS"))
                if f_yoy_eps:
                    forward.update({
                        "yoy_date": f_yoy_ts.date().isoformat(), "yoy_eps": f_yoy_eps,
                        "expected_growth_pct": round((consensus - f_yoy_eps) / abs(f_yoy_eps) * 100, 1),
                    })

        # ── Ценова реакция — ЕДИН fetch за всичките дати наведнъж ─────────
        all_dates = [q["date"] for q in quarters] + ([yoy["date"]] if yoy else [])
        reactions = _reactions_for_dates(sym, all_dates)
        for q in quarters:
            if q["date"] in reactions:
                q.update(reactions[q["date"]])
        if yoy and yoy["date"] in reactions:
            yoy.update(reactions[yoy["date"]])

        return {
            "quality": _quality(quarters[0].get("eps_surprise_pct"), quarters[0].get("reaction_pct")),
            "quarters": quarters,
            "yoy": yoy,
            "yoy_summary": yoy_summary,
            "forward": forward,
        }
    except Exception as e:
        print(f"[enrich] earnings_recap {sym}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────
# Опции (Секция 3.6) — IV, IVR, P/C, OI, препоръка за стратегия
# ──────────────────────────────────────────────────────────────────────────
def _load_iv_history() -> dict:
    if config.IV_HISTORY_FILE.exists():
        return json.loads(config.IV_HISTORY_FILE.read_text())
    return {}


def _save_iv_history(hist: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    config.IV_HISTORY_FILE.write_text(json.dumps(hist, indent=1))


def options_info(sym: str, price: float) -> dict:
    out = {"iv": None, "iv_rank": None, "iv_rank_quality": None,
           "put_call_ratio": None, "oi_near_money": [],
           "strategy": None, "strategy_reason": None}
    try:
        tk = yf.Ticker(sym)
        expirations = tk.options
        if not expirations:
            out["strategy"] = "акции"
            out["strategy_reason"] = "Няма ликвидни опции — само акции."
            return out

        # експирация 30-60 дни напред (стандарт за суинг)
        today = dt.date.today()
        target = None
        for e in expirations:
            d = dt.date.fromisoformat(e)
            if 25 <= (d - today).days <= 70:
                target = e
                break
        target = target or expirations[min(1, len(expirations) - 1)]

        chain = tk.option_chain(target)
        calls, puts = chain.calls, chain.puts

        # ATM IV = средно на най-близките до парите call и put
        calls["dist"] = (calls["strike"] - price).abs()
        puts["dist"] = (puts["strike"] - price).abs()
        atm_call = calls.nsmallest(1, "dist")
        atm_put = puts.nsmallest(1, "dist")
        # FIX 2026-07-17: pre-market timing bug, не ликвидност на тикъра. Cron-ът
        # тръгва ~05:30-06:30 UTC, US опциите отварят в 13:30 UTC — по това време
        # bid/ask са и за двата 0.0 (борсата още не публикува live котировки),
        # само lastPrice/volume от ВЧЕРАШНОТО затваряне остават. Yahoo смята
        # impliedVolatility от bid/ask, не от lastPrice → без валидна котировка
        # деградира в near-нулев placeholder (наблюдавано: 0.00001, 0.015625,
        # 0.03125, 0.0625 — степени на 2, solver artifact, не пазарна стойност).
        # Потвърдено емпирично за BAC/GS — идентичен pattern, независимо от
        # реалната им (изключително висока) ликвидност. IV_SANITY_MIN_PCT
        # прагът по-долу хваща само деградиралите стойности, паднали СЛУЧАЙНО
        # под прага — съседни strikes от същия „развален“ chain дават 6.25%/
        # 12.5%, над прага, но също толкова невалидни. Затова проверяваме bid/
        # ask валидност на самия избран контракт, преди изобщо да му вярваме.
        # FIX 2026-08-02: обратната посока на горния проблем — контракт МОЖЕ да има
        # bid>0/ask>0 (технически "жив"), но да е фактически мъртъв. Потвърдено
        # живо на ONB: ATM put bid=2.65/ask=5.70, openInterest=1 → IV=133.9%,
        # докато съседният ликвиден ATM call (активно търгуван) даде разумни 36.9%.
        # Same solver-artifact клас като pre-market бъга (FIXES_2026-07-17.md), само
        # в обратна посока — тук стойността е абсурдно ВИСОКА, не ниска.
        # ПЪРВИ ОПИТ бе спред/mid праг (>60%) — отхвърлен СЛЕД проверка на реални
        # ликвидни имена: GRMN (mega-cap, vol=22, OI=20, търгуван вчера) има 118%
        # спред на ATM put-а — легитимен активен пазар, не боклук. Спредът НЕ
        # разграничава надеждно. Реалният разграничител е СТАРОСТТА на последната
        # сделка: ONB PUT последно търгуван преди 179 ДНИ (lastTradeDate), докато
        # всички проверени легитимни тикъри (GRMN, NTRS, JPM, BAC, AIZ, DINO) са
        # търгувани в рамките на ≤16 дни — чиста разделителна линия в реалните
        # данни. Отхвърляме leg-а по СТАРОСТ на котировката (config.
        # IV_MAX_QUOTE_AGE_DAYS), не по спред.
        ivs = []
        no_live_quote = True
        stale_quote_rejected = False
        for df in (atm_call, atm_put):
            if not len(df):
                continue
            row = df.iloc[0]
            bid, ask = row.get("bid") or 0, row.get("ask") or 0
            has_live_quote = bid > 0 or ask > 0
            if not has_live_quote:
                continue
            no_live_quote = False
            last_trade = row.get("lastTradeDate")
            quote_age_days = None
            if last_trade is not None and last_trade == last_trade:  # изключва NaT/NaN
                try:
                    now = (dt.datetime.now(last_trade.tzinfo)
                          if getattr(last_trade, "tzinfo", None) else dt.datetime.now())
                    quote_age_days = (now - last_trade).days
                except Exception:
                    quote_age_days = None
            if quote_age_days is not None and quote_age_days > config.IV_MAX_QUOTE_AGE_DAYS:
                print(f"[enrich] options {sym}: последна сделка преди {quote_age_days}д "
                      f"> {config.IV_MAX_QUOTE_AGE_DAYS}д sanity праг — leg отхвърлен "
                      "като застоял/нетъргуван")
                stale_quote_rejected = True
                continue
            if not math.isnan(row["impliedVolatility"]):
                ivs.append(float(row["impliedVolatility"]))
        iv = round(sum(ivs) / len(ivs) * 100, 1) if ivs else None
        # iv_reject_reason захранва специфично съобщение по-долу вместо генеричното
        # "без надеждни IV данни" — потребителят вижда КОЯ от причините е (виж
        # FIXES_2026-07-17.md за pre-market bid/ask контекста; stale_quote е
        # FIX 2026-08-02, виж коментара при цикъла по-горе).
        if iv is None and no_live_quote:
            iv_reject_reason = "no_live_quote"
        elif iv is None and stale_quote_rejected:
            iv_reject_reason = "stale_quote"
        else:
            iv_reject_reason = None
        # FIX 2026-07-15: yfinance връща боклук близо до нулата от застояли
        # котировки (ALL: ATM IV "1.6%" — физически невъзможно за акция).
        # Под sanity прага IV се отхвърля, за да не замърсява IVR историята
        # и да не произвежда категорични опционни препоръки от шум.
        if iv is not None and iv < config.IV_SANITY_MIN_PCT:
            print(f"[enrich] options {sym}: ATM IV {iv}% < {config.IV_SANITY_MIN_PCT}% "
                  f"sanity праг — отхвърлен като невалиден")
            iv = None
            iv_reject_reason = "sanity_floor"
        out["iv"] = iv

        # P/C по обем за тикъра
        # FIX 2026-07-15: минимален общ обем — P/C 41.19 при шепа контракта е
        # математически верен и информационно безполезен.
        # FIX 2026-08-02: same pre-market проблем като IV (FIXES_2026-07-17.md), но
        # никога не бе gate-нат тук. Потвърдено на FITB (20.07.2026 P/C=17.12,
        # 21.07.2026 P/C=11.12) — и двата дни IV коректно показваше "pre-market,
        # bid/ask=0" (no_live_quote), докато P/C ratio-то тихо смяташе от volume
        # полетата на same заявка, без връзка с no_live_quote сигнала. Възпроизведено
        # синтетично с идентичен резултат (17.12) — pre-market snapshot носи volume
        # числа, отвъд PC_MIN_TOTAL_VOLUME прага, но не по-надеждни от bid/ask-а на
        # same заявка. Ако цялата верига е "мъртва" (no_live_quote), P/C-то също не
        # се доверява, независимо от абсолютния обем сбор.
        pv = float(puts["volume"].fillna(0).sum())
        cv = float(calls["volume"].fillna(0).sum())
        out["put_call_ratio"] = (round(pv / cv, 2)
                                 if (not no_live_quote and cv
                                     and (pv + cv) >= config.PC_MIN_TOTAL_VOLUME)
                                 else None)

        # OI около парите: 3 страйка под и над
        near = calls[(calls["strike"] >= price * 0.93) &
                     (calls["strike"] <= price * 1.07)]
        out["oi_near_money"] = [
            {"strike": float(r["strike"]),
             "call_oi": int(r["openInterest"] or 0)}
            for _, r in near.iterrows()][:6]

        # ── IVR от собствената история ───────────────────────────────────
        if iv is not None:
            hist = _load_iv_history()
            series = hist.setdefault(sym, {})
            series[today.isoformat()] = iv
            # пазим само последните 380 записа
            if len(series) > 380:
                for k in sorted(series)[:-380]:
                    del series[k]
            _save_iv_history(hist)

            vals = list(series.values())
            if len(vals) >= 2:
                lo, hi = min(vals), max(vals)
                ivr = round((iv - lo) / (hi - lo) * 100, 0) if hi > lo else 50.0
                out["iv_rank"] = ivr
                out["iv_rank_quality"] = ("full" if len(vals) >= 200
                                          else f"partial ({len(vals)} дни история)")

        # ── Стратегия (логиката от спека) ────────────────────────────────
        # FIX 2026-07-15: категорична IVR-базирана препоръка ("premium-ът е
        # евтин/скъп") САМО при достатъчна история — IVR 5 от 12 дни данни
        # не е нисък IVR, а липса на извадка, представена като сигнал.
        ivr = out["iv_rank"]
        try:
            n_hist = len(vals)          # vals съществува само ако имаше валиден IV
        except NameError:
            n_hist = 0
        ivr_reliable = ivr is not None and n_hist >= config.IVR_MIN_DAYS_FOR_STRATEGY
        if iv is None:
            if iv_reject_reason == "no_live_quote":
                out["strategy"], out["strategy_reason"] = "акции", (
                    "Опционните котировки още не са активни (pre-market, bid/ask=0) — "
                    "IV данните ще са надеждни след отварянето на US пазара.")
            elif iv_reject_reason == "sanity_floor":
                out["strategy"], out["strategy_reason"] = "акции", (
                    f"Изчисленото IV е под {config.IV_SANITY_MIN_PCT:.0f}% "
                    "(физически неправдоподобно за тази акция) — вероятно застояла "
                    "котировка, отхвърлено. Без надеждни IV данни — стой в акциите.")
            elif iv_reject_reason == "stale_quote":
                out["strategy"], out["strategy_reason"] = "акции", (
                    f"Последната сделка по достъпните контракти е преди над "
                    f"{config.IV_MAX_QUOTE_AGE_DAYS} дни (вероятно неликвиден/нетъргуван "
                    "контракт) — IV отхвърлено като ненадеждно. Без надеждни IV данни — "
                    "стой в акциите.")
            else:
                out["strategy"], out["strategy_reason"] = "акции", \
                    "Без надеждни IV данни — стой в акциите."
        elif ivr_reliable and ivr <= 30:
            out["strategy"] = "long call / bull call spread"
            out["strategy_reason"] = (f"IVR {ivr:.0f} е нисък — опционният premium е евтин, "
                                      "купуването на опции дава по-добър leverage от акции.")
        elif ivr_reliable and ivr >= 60:
            out["strategy"] = "cash-secured put / акции"
            out["strategy_reason"] = (f"IVR {ivr:.0f} е висок — premium-ът е скъп. "
                                      "Продаването на CSP под pivot или директно акции.")
        elif ivr is None:
            # FIX 2026-08-02: потвърден бъг (ONB, 30.07.2026) — при <2 дни история
            # IVR блокът по-горе никога не сетва out["iv_rank"] (остава None), но
            # старият elif верижен ред нямаше clause за ТОЗИ случай — падаше в
            # generic-ия долен else и твърдеше "IV в средата на диапазона", докато
            # диапазон изобщо не съществува (0 или 1 ден история). Разграничено
            # от "IVR изчислен, но ненадежден поради малко дни" clause-а по-долу.
            out["strategy"] = "акции / bull call spread"
            out["strategy_reason"] = (f"IV {iv}% — все още няма достатъчно история за IVR "
                                      "(първи ден с данни за този тикър); акции по "
                                      "подразбиране, spread при нужда от дефиниран риск.")
        elif ivr is not None and not ivr_reliable:
            out["strategy"] = "акции / bull call spread"
            out["strategy_reason"] = (f"IVR {ivr:.0f} върху само {n_hist} дни история — "
                                      "недостатъчна извадка за категорична опционна препоръка; "
                                      "акции по подразбиране, spread при нужда от дефиниран риск.")
        else:
            out["strategy"] = "акции / bull call spread"
            out["strategy_reason"] = (f"IV {iv}% в средата на диапазона — акции по подразбиране; "
                                      "spread ако искаш дефиниран риск.")
    except Exception as e:
        print(f"[enrich] options {sym}: {e}")
        out["strategy"] = "акции"
        out["strategy_reason"] = "Опционните данни недостъпни — акции."
    return out


def short_interest_view(row: dict) -> dict:
    """Интерпретация на short данните от screener-а (Секция 3.5)."""
    spf = row.get("short_pct_float") or 0
    dtc = row.get("short_ratio_dtc") or 0
    if spf >= 15 and dtc >= 5:
        interp = (f"Висок short interest ({spf}% от float, {dtc} дни за покриване) — "
                  "реален squeeze потенциал при пробив, но и сигнал че умни пари залагат против.")
    elif spf >= 8:
        interp = f"Умерен short interest ({spf}%) — гориво при пробив с обем."
    else:
        interp = f"Нисък short interest ({spf}%) — без squeeze динамика, но и без активна опозиция."
    return {"short_pct_float": spf, "days_to_cover": dtc, "interpretation": interp}


# ──────────────────────────────────────────────────────────────────────────
# v2 надстройка — глобални cross-check множества (строят се веднъж на пускане)
# ──────────────────────────────────────────────────────────────────────────
def _build_crosscheck_sets(candidate_tickers: list[str]) -> dict:
    """
    Тегли веднъж скъпите/глобални източници. Всеки е обвит в toggle + try/except
    за graceful degradation (Секция 7): провал на един източник не убива брифа.
    FIX 2026-07-15: MF проверката вече ранкира самите кандидати спрямо
    референтния универс (value_confirmed), вместо да търси пресичане със
    статичен топ списък, което беше структурно невъзможно.
    """
    sets = {"mf": set(), "uov": {}, "splits": {}, "si": {}}
    if config.ENABLE_MAGIC_FORMULA:
        try:
            sets["mf"] = magic_formula.value_confirmed(candidate_tickers)
        except Exception as e:
            print(f"[enrich] magic_formula skipped: {e}")
    if config.ENABLE_UNUSUAL_OPTIONS:
        try:
            sets["uov"] = unusual_options.unusual_set()
        except Exception as e:
            print(f"[enrich] unusual_options skipped: {e}")
    if config.ENABLE_SPLITS_CALENDAR:
        try:
            sets["splits"] = splits_calendar.splits_map()
        except Exception as e:
            print(f"[enrich] splits_calendar skipped: {e}")
    if config.ENABLE_DATAROMA:
        try:
            sets["si"] = dataroma.superinvestor_map()
        except Exception as e:
            print(f"[enrich] dataroma skipped: {e}")
    return sets


def _apply_markers(row: dict, sets: dict) -> None:
    """Слага визуалните convergence маркери MF✓ / UOV✓ / SPLIT✓ върху картата."""
    sym = row["ticker"]
    markers = row.setdefault("markers", [])

    if sym in sets["mf"]:
        markers.append({"tag": "MF✓", "title": "Value confirmed — кандидатът е в топ дециала по Greenblatt (EY × ROC) спрямо референтния универс."})

    uov = sets["uov"].get(sym)
    if uov:
        bias = uov.get("call_put_bias")
        suffix = " (calls)" if bias == "calls" else " (puts)" if bias == "puts" else ""
        markers.append({"tag": f"UOV✓{suffix}", "title": uov.get("note", "Необичаен опционен обем днес.")})

    sp = sets["splits"].get(sym)
    if sp:
        ratio = f" {sp['ratio']}" if sp.get("ratio") else ""
        markers.append({"tag": "SPLIT✓", "title": f"Предстоящ сплит{ratio} на {sp.get('date', '—')}."})
        # запазваме детайла; инжектира се в катализаторите СЛЕД AI merge (виж main.py)
        row["_split_catalyst"] = (
            f"Предстоящ stock split{ratio} ({sp.get('date', 'скоро')}) — момент на momentum.")

    si = sets["si"].get(sym)
    if si:
        who = ", ".join(dict.fromkeys(si.get("managers", [])))  # уникални, запазен ред
        val = f" · ${si['value']:,.0f}" if si.get("value") else ""
        n = si.get("count", 1)
        tag = "SI✓" if n == 1 else f"SI✓×{n}"
        markers.append({"tag": tag,
                        "title": f"Superinvestor покупка ({si.get('action', 'Buy')}){val}: {who}"})


def inject_split_catalysts(candidates: list[dict]) -> list[dict]:
    """
    Извиква се в main.py СЛЕД ai_brief.merge_narratives — добавя споменаване на
    предстоящ сплит в катализаторите на картата (Секция 3.4). Отделено от
    _apply_markers, защото при enrich() ключът 'ai' още не съществува.
    """
    for row in candidates:
        mention = row.pop("_split_catalyst", None)
        if mention and isinstance(row.get("ai"), dict):
            row["ai"].setdefault("catalysts", [])
            if mention not in row["ai"]["catalysts"]:
                row["ai"]["catalysts"].append(mention)
    return candidates


def enrich(candidates: list[dict]) -> list[dict]:
    sets = _build_crosscheck_sets([c["ticker"] for c in candidates])

    for row in candidates:
        sym = row["ticker"]
        row["earnings"] = earnings_info(sym)
        row["options"] = options_info(sym, row["price"])
        row["short_view"] = short_interest_view(row)

        # 3.2 borrow rate → влиза в short_view секцията
        if config.ENABLE_BORROW_DATA:
            try:
                borrow = borrow_data.borrow_info(sym)
            except Exception as e:
                print(f"[enrich] borrow {sym}: {e}")
                borrow = {"available": False}
            row["borrow"] = borrow
            if borrow.get("available") and borrow.get("interpretation"):
                row["short_view"]["borrow"] = borrow["interpretation"]
        else:
            row["borrow"] = {"available": False}

        # 3.1 / 3.3 / 3.4 convergence маркери
        _apply_markers(row, sets)

    return candidates
