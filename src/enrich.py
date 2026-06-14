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


# ──────────────────────────────────────────────────────────────────────────
# Earnings (Секция 3.2 + правило за blackout от Секция 8)
# ──────────────────────────────────────────────────────────────────────────
def earnings_info(sym: str) -> dict:
    out = {"next_earnings": None, "days_to_earnings": None,
           "in_blackout": False, "eps_estimate": None}
    try:
        tk = yf.Ticker(sym)
        cal = tk.calendar
        ed = None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or []
            if dates:
                ed = dates[0]
        if ed is None:
            df = tk.get_earnings_dates(limit=8)
            if df is not None and len(df):
                future = df[df.index > dt.datetime.now(df.index.tz)]
                if len(future):
                    ed = future.index[-1].date()
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
    except Exception as e:
        print(f"[enrich] earnings {sym}: {e}")
    return out


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
        ivs = []
        for df in (atm_call, atm_put):
            if len(df) and not math.isnan(df["impliedVolatility"].iloc[0]):
                ivs.append(float(df["impliedVolatility"].iloc[0]))
        iv = round(sum(ivs) / len(ivs) * 100, 1) if ivs else None
        out["iv"] = iv

        # P/C по обем за тикъра
        pv = float(puts["volume"].fillna(0).sum())
        cv = float(calls["volume"].fillna(0).sum())
        out["put_call_ratio"] = round(pv / cv, 2) if cv else None

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
        ivr = out["iv_rank"]
        if iv is None:
            out["strategy"], out["strategy_reason"] = "акции", \
                "Без надеждни IV данни — стой в акциите."
        elif ivr is not None and ivr <= 30:
            out["strategy"] = "long call / bull call spread"
            out["strategy_reason"] = (f"IVR {ivr:.0f} е нисък — опционният premium е евтин, "
                                      "купуването на опции дава по-добър leverage от акции.")
        elif ivr is not None and ivr >= 60:
            out["strategy"] = "cash-secured put / акции"
            out["strategy_reason"] = (f"IVR {ivr:.0f} е висок — premium-ът е скъп. "
                                      "Продаването на CSP под pivot или директно акции.")
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
def _build_crosscheck_sets() -> dict:
    """
    Тегли веднъж скъпите/глобални източници. Всеки е обвит в toggle + try/except
    за graceful degradation (Секция 7): провал на един източник не убива брифа.
    """
    sets = {"mf": set(), "uov": {}, "splits": {}, "si": {}}
    if config.ENABLE_MAGIC_FORMULA:
        try:
            sets["mf"] = magic_formula.top_set()
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
        markers.append({"tag": "MF✓", "title": "Magic Formula топ — потвърждение от втори независим метод (Greenblatt)."})

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
    sets = _build_crosscheck_sets()

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
