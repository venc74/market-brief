"""
22.10.2026 (етап 4 — решение от 22.10): САМО ЗАПИС на опционните данни за „необичайна активност извън картите“ — нищо в брифа; доклад след ~20 сесии.
Yahoo дава само текущата верига, без история на опционния обем, затова „над собствения 90-и перцентил“ иска първо собствена история. Всяка сесия се записват:
  • топ OPTIONS_RECORD_TOP_N (200) тикъра по оборот (close × обем, средно за 20 сесии) + кандидатите от (а) — ход ≥ ±5% при обем ≥ 2× средния за 50 сесии;
  • за всеки: най-близките OPTIONS_RECORD_EXPIRIES (2) падежа — обем и OI на call и put, последната сделка във веригата (за проверка коя сесия е обемът).
Часът: веригата на Yahoo носи ЦЕЛИЯ обем на предишната сесия преди отварянето (на 22.10 в 09:12 ET последната сделка беше 16:00 ET на 21.10); следобедната снимка (~12:00 ET) е частична.
Файл: config.DATA_DIR / options_daily.json — {"version", "sessions": {сесия: {"taken_utc", "tickers", "candidates", "errors"}}}, последните OPTIONS_RECORD_KEEP сесии.
Всяка грешка → записът за деня е непълен с причина (graceful); нищо не вдига.
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


def merge(history: dict, session: str, rec: dict, keep: int | None = None) -> dict:
    """Нова сесия в историята (заменя същата сесия) и само последните keep сесии. Чиста функция."""
    keep = keep or config.OPTIONS_RECORD_KEEP
    s = dict((history or {}).get("sessions") or {})
    s[session] = rec
    return {"version": 1, "sessions": {k: s[k] for k in sorted(s)[-keep:]}}


def record(universe: list[str], today: str | None = None, *, download=None, ticker=None, path=None, sleep=time.sleep) -> dict:
    """
    Записът за последната цяла сесия преди today. download(tickers) → {тикър: DataFrame}; ticker(sym) → обект с .options / .option_chain (по подразбиране yfinance).
    Връща статуса {"ok", "session", "tickers", "candidates", "errors", "sec"} (и го пише в LAST_STATUS).
    """
    from src import sessions
    t0 = time.time()
    today = today or dt.date.today().isoformat()
    session = sessions.prev_session(dt.date.fromisoformat(today)).isoformat()
    st = {"ok": False, "session": session, "tickers": 0, "candidates": 0, "errors": 0, "sec": None, "reason": None}
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
        rec = {"taken_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), "top_n": len(top), "tickers": rows, "candidates": cand, "errors": errors}
        p.write_text(json.dumps(merge(hist, session, rec), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        st.update(ok=bool(rows), tickers=len(rows), candidates=len(cand), errors=len(errors), reason=None if rows else "нито една верига")
    except Exception as e:
        st["reason"] = f"{type(e).__name__}: {e}"
        print(f"[options_record] {st['reason']}")
    st["sec"] = round(time.time() - t0, 1)
    LAST_STATUS.clear(); LAST_STATUS.update(st)
    print(f"[options_record] сесия {session}: вериги {st['tickers']}, кандидати (а) {st['candidates']}, грешки {st['errors']}, {st['sec']} s")
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
