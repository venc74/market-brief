"""
22.10.2026 (етап 4 — решение от 22.10): САМО ЗАПИС на опционните данни за „необичайна активност извън картите“ — нищо в брифа; доклад след ~20 сесии.
Yahoo дава само текущата верига, без история на опционния обем, затова „над собствения 90-и перцентил“ иска първо собствена история. Всяка сесия се записват:
  • топ OPTIONS_RECORD_TOP_N (200) тикъра по оборот (close × обем, средно за 20 сесии) + кандидатите от (а) — ход ≥ ±5% при обем ≥ 2× средния за 50 сесии;
  • за всеки: най-близките OPTIONS_RECORD_EXPIRIES (2) падежа — обем и OI на call и put, последната сделка във веригата (за проверка коя сесия е обемът).
Часът: веригата на Yahoo носи ЦЕЛИЯ обем на предишната сесия преди отварянето (на 22.10 в 09:12 ET последната сделка беше 16:00 ET на 21.10); следобедната снимка (~12:00 ET) е частична.
Файл: config.DATA_DIR / options_daily.json — {"version", "sessions": {сесия: {"taken_utc", "tickers", "candidates", "errors"}}}, последните OPTIONS_RECORD_KEEP сесии.
Всяка грешка → записът за деня е непълен с причина (graceful); нищо не вдига.

26.10.2026 (етап 4б, т. 9 — решение от 26.10): включено в сутрешния run (ENABLE_OPTIONS_RECORD = 1) със САМОПРОВЕРКА, без отделен експеримент: последната сделка във веригите (максимумът
на lastTradeDate) трябва да е от затварянето на записваната сесия — 16:00 ET (15:59 и след него; при ранно затваряне — 13:00 ET), не по-късно от 16:15 ET, а снимката — преди отварянето
на следващата сесия. Тогава денят е пълен и влиза
в "sessions"; иначе — "incomplete" (само дата, час, причина и броят вериги — без данните), не влиза в историята и стъпката е частична. Реално на 22.10 (09:12 ET): последната сделка
21.10 19:59:59–20:00:00 UTC = 15:59:59–16:00:00 ET.
"""
from __future__ import annotations

import datetime as dt
import json
import time

import config

LAST_STATUS: dict = {}


def stock_side(frames: dict) -> tuple[list[str], list[dict]]:
    """
    От дневните барове (тикър → DataFrame с Close, Volume; само цели сесии): (топ N по оборот за 20 сесии, кандидатите от (а) за последната сесия).
    Кандидат: |промяна| ≥ OPTIONS_RECORD_MOVE_PCT и обем ≥ OPTIONS_RECORD_VOL_X × средния за 50 сесии преди деня. Чиста функция.
    """
    dv, cand = {}, []
    for t, df in frames.items():
        try:
            c, v = df["Close"].dropna(), df["Volume"].dropna()
            if len(c) < 52 or len(v) < 52:
                continue
            dv[t] = float((c * v).iloc[-20:].mean())
            ret = (float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100
            avg = float(v.iloc[-51:-1].mean())
            vx = float(v.iloc[-1]) / avg if avg > 0 else 0.0
            if abs(ret) >= config.OPTIONS_RECORD_MOVE_PCT and vx >= config.OPTIONS_RECORD_VOL_X:
                cand.append({"ticker": t, "ret_pct": round(ret, 2), "vol_x": round(vx, 2), "date": c.index[-1].date().isoformat()})
        except Exception:
            continue
    top = sorted(dv, key=dv.get, reverse=True)[:config.OPTIONS_RECORD_TOP_N]
    return top, sorted(cand, key=lambda x: -abs(x["ret_pct"]))


def chain_row(tk) -> dict:
    """Най-близките OPTIONS_RECORD_EXPIRIES падежа на тикъра: {"exp": {падеж: {cv, pv, coi, poi}}, "cv", "pv", "coi", "poi", "last_trade"} (сборове). Вдига при грешка — викащият я брои."""
    out = {"exp": {}, "cv": 0.0, "pv": 0.0, "coi": 0.0, "poi": 0.0, "last_trade": None}
    for e in list(tk.options or [])[:config.OPTIONS_RECORD_EXPIRIES]:
        ch = tk.option_chain(e)
        row = {"cv": float(ch.calls["volume"].fillna(0).sum()), "pv": float(ch.puts["volume"].fillna(0).sum()),
               "coi": float(ch.calls["openInterest"].fillna(0).sum()), "poi": float(ch.puts["openInterest"].fillna(0).sum())}
        out["exp"][e] = row
        for k in ("cv", "pv", "coi", "poi"):
            out[k] += row[k]
        lt = [str(x) for x in list(ch.calls["lastTradeDate"]) + list(ch.puts["lastTradeDate"]) if str(x) != "NaT"]
        if lt:
            out["last_trade"] = max([out["last_trade"]] + lt if out["last_trade"] else lt)
    return out


def completeness(rows: dict, session: str, taken=None) -> dict:
    """
    26.10.2026 (етап 4б, т. 9): пълен ли е денят — последната сделка във веригите (максимумът на last_trade, ET) е от затварянето на сесията: в [затваряне − 1 мин, затваряне + 15 мин]
    на датата на сесията (затваряне 16:00 ET или ранното от config.NYSE_EARLY_CLOSES); и снимката (taken, UTC) е ПРЕДИ отварянето на следващата сесия (09:30 ET) — след него
    обемът на веригата е на новия ден (ROKU на 22.10 в 09:37 ET: последната сделка още 15:59 на 21.10, а сесията вече тече). {"complete", "last_trade_et", "reason"}. Чиста функция.
    """
    import pandas as pd
    from src import sessions
    lts = []
    for r in (rows or {}).values():
        try:
            if r.get("last_trade"):
                t = pd.Timestamp(r["last_trade"])
                lts.append(t.tz_localize("UTC") if t.tzinfo is None else t)
        except Exception:
            continue
    if not lts:
        return {"complete": False, "last_trade_et": None, "reason": "веригите нямат време на последната сделка"}
    last = max(lts).tz_convert("America/New_York")
    hh, mm = map(int, config.NYSE_EARLY_CLOSES.get(session, "16:00").split(":"))
    close = pd.Timestamp(f"{session} {hh:02d}:{mm:02d}", tz="America/New_York")
    txt = last.strftime("%d.%m %H:%M ET")
    if last < close - pd.Timedelta(minutes=1):
        return {"complete": False, "last_trade_et": last.isoformat(), "reason": f"последната сделка е от {txt} — преди затварянето на сесията {session[8:10]}.{session[5:7]} ({hh:02d}:{mm:02d} ET)"}
    if last > close + pd.Timedelta(minutes=15):
        return {"complete": False, "last_trade_et": last.isoformat(), "reason": f"последната сделка е от {txt} — след сесията {session[8:10]}.{session[5:7]} (веригите носят по-нова сесия)"}
    if taken is not None:
        t = pd.Timestamp(taken)
        t = (t.tz_localize("UTC") if t.tzinfo is None else t).tz_convert("America/New_York")
        nxt = pd.Timestamp(f"{sessions.next_session(dt.date.fromisoformat(session)).isoformat()} 09:30", tz="America/New_York")
        if t >= nxt:
            return {"complete": False, "last_trade_et": last.isoformat(), "reason": f"снимката е от {t.strftime('%d.%m %H:%M ET')} — след отварянето на следващата сесия (обемът е на новия ден)"}
    return {"complete": True, "last_trade_et": last.isoformat(), "reason": None}


def merge(history: dict, session: str, rec: dict, keep: int | None = None) -> dict:
    """Нова сесия в историята (заменя същата сесия) и само последните keep сесии; 26.10.2026: "incomplete" се пази (без същата сесия, щом вече е пълна). Чиста функция."""
    keep = keep or config.OPTIONS_RECORD_KEEP
    s = dict((history or {}).get("sessions") or {})
    s[session] = rec
    inc = {k: v for k, v in ((history or {}).get("incomplete") or {}).items() if k != session}
    out = {"version": 1, "sessions": {k: s[k] for k in sorted(s)[-keep:]}}
    if inc:
        out["incomplete"] = {k: inc[k] for k in sorted(inc)[-keep:]}
    return out


def mark_incomplete(history: dict, session: str, meta: dict, keep: int | None = None) -> dict:
    """26.10.2026 (етап 4б, т. 9): непълният ден — само в "incomplete" (без данните на веригите); историята ("sessions") не се пипа. Чиста функция."""
    keep = keep or config.OPTIONS_RECORD_KEEP
    inc = dict((history or {}).get("incomplete") or {})
    inc[session] = meta
    out = {"version": 1, "sessions": dict((history or {}).get("sessions") or {})}
    out["incomplete"] = {k: inc[k] for k in sorted(inc)[-keep:]}
    return out


def record(universe: list[str], today: str | None = None, *, download=None, ticker=None, path=None, sleep=time.sleep) -> dict:
    """
    Записът за последната цяла сесия преди today. download(tickers) → {тикър: DataFrame}; ticker(sym) → обект с .options / .option_chain (по подразбиране yfinance).
    Връща статуса {"ok", "session", "tickers", "candidates", "errors", "sec", "complete", "last_trade_et"} (и го пише в LAST_STATUS); непълен ден → complete False с причина.
    """
    from src import sessions
    t0 = time.time()
    today = today or dt.date.today().isoformat()
    session = sessions.prev_session(dt.date.fromisoformat(today)).isoformat()
    st = {"ok": False, "session": session, "tickers": 0, "candidates": 0, "errors": 0, "sec": None, "reason": None, "complete": None, "last_trade_et": None}
    LAST_STATUS.clear(); LAST_STATUS.update(st)
    try:
        if download is None or ticker is None:
            import yfinance as yf
            download = download or (lambda ts: _yf_frames(yf, ts, today))
            ticker = ticker or yf.Ticker
        frames = download(universe)
        top, cand = stock_side(frames)
        names = list(dict.fromkeys(top + [c["ticker"] for c in cand]))
        rows, errors = {}, {}
        for i, s in enumerate(names):
            try:
                rows[s] = chain_row(ticker(s))
            except Exception as e:
                errors[s] = f"{type(e).__name__}: {str(e)[:60]}"
            if i % 25 == 24:
                sleep(0.5)
        p = path or (config.DATA_DIR / "options_daily.json")
        try:
            hist = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except Exception:
            hist = {}
        now = dt.datetime.now(dt.timezone.utc)
        taken = now.strftime("%Y-%m-%d %H:%M")
        chk = completeness(rows, session, now)                                      # 26.10.2026 (етап 4б, т. 9): самопроверката — само пълен ден влиза в историята
        if rows and chk["complete"]:
            rec = {"taken_utc": taken, "last_trade_et": chk["last_trade_et"], "top_n": len(top), "tickers": rows, "candidates": cand, "errors": errors}
            new = merge(hist, session, rec)
        else:
            new = mark_incomplete(hist, session, {"taken_utc": taken, "last_trade_et": chk["last_trade_et"], "reason": chk["reason"] if rows else "нито една верига",
                                                  "tickers": len(rows), "candidates": len(cand), "errors": len(errors)})
        p.write_text(json.dumps(new, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        st.update(ok=bool(rows), tickers=len(rows), candidates=len(cand), errors=len(errors), complete=bool(rows and chk["complete"]), last_trade_et=chk["last_trade_et"],
                  reason=None if rows and chk["complete"] else (chk["reason"] if rows else "нито една верига"))
    except Exception as e:
        st["reason"] = f"{type(e).__name__}: {e}"
        print(f"[options_record] {st['reason']}")
    st["sec"] = round(time.time() - t0, 1)
    LAST_STATUS.clear(); LAST_STATUS.update(st)
    print(f"[options_record] сесия {session}: вериги {st['tickers']}, кандидати (а) {st['candidates']}, грешки {st['errors']}, {st['sec']} s"
          + ("" if st["complete"] else f" — НЕПЪЛЕН, не влиза в историята ({st['reason']})"))
    return st


def _yf_frames(yf, tickers: list[str], today: str) -> dict:
    """Дневни барове за 3 месеца на батчове; само цели сесии (дата < today)."""
    import pandas as pd
    out = {}
    for i in range(0, len(tickers), 200):
        batch = tickers[i:i + 200]
        try:
            data = yf.download(batch, period="4mo", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        except Exception as e:
            print(f"[options_record] батч {i}: {type(e).__name__}: {e}")
            continue
        for s in batch:
            try:
                df = (data[s] if len(batch) > 1 else data)[["Close", "Volume"]].dropna()
                out[s] = df[df.index < pd.Timestamp(today)]
            except Exception:
                continue
    return out
