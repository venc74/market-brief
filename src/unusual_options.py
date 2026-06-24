"""
Unusual Options Volume — Поправка 2.

Старият Market Chameleon scrape връщаше празно (блокиран). Тук PRIMARY е yfinance:
за универс от S&P500 + NDX тикъри теглим опционните вериги (tk.options →
expirations; tk.option_chain(exp) → calls/puts с volume и openInterest) и мерим
„необичайност".

Бележка за метриката: yfinance НЕ дава историческа опционна обемна крива, затова
20-дневна средна за опционния обем не е директно достъпна. Използваме надеждния
proxy: днешен опционен обем спрямо open interest (vol/OI). Висок vol/OI = свежо
позициониране днес спрямо натрупаните позиции = необичайна активност. Допълнително
показваме и отношението на обема на АКЦИЯТА спрямо 20-дневната ѝ средна (това
yfinance го дава) като втори сигнал. Топ 10 по vol/OI влизат в секцията.

Сканирането на вериги е бавно → ограничаваме до config.UNUSUAL_OPTIONS_SCAN_LIMIT
тикъра на ден. FALLBACK: Market Chameleon scrape, ако yfinance върне нищо.

Graceful degradation: липсват ли данни за тикър — пропуска се; празно → секцията се крие.
"""
from __future__ import annotations
import datetime as dt
import io
import json
import re
import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

try:
    import pandas as pd
except Exception:
    pd = None
try:
    import yfinance as yf
except Exception:
    yf = None

_MC_URL = "https://marketchameleon.com/Reports/UnusualOptionVolumeReport"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
       "Accept": "text/html,application/xhtml+xml"}
_CACHE = config.DATA_DIR / "unusual_options_cache.json"
_UNIV_CACHE = config.DATA_DIR / "sp500_ndx_universe.json"


def _bias(call_vol: float, put_vol: float) -> tuple[str, str]:
    if call_vol > put_vol * 1.5:
        return "calls", "Обемът е предимно в кол опции — bullish наклон."
    if put_vol > call_vol * 1.5:
        return "puts", "Обемът е предимно в пут опции — внимание/хедж."
    return "mixed", "Балансиран call/put обем."


def _oi_label(ratio: float) -> str:
    """Кратко обяснение какво означава vol/OI съотношението за непрофесионалист."""
    if ratio < 1:
        return "нормална активност"
    if ratio < 2:
        return "леко повишена активност"
    if ratio < 4:
        return "силно ново позициониране"
    return "екстремна, необичайна активност"


# ──────────────────────────────────────────────────────────────────────────
# Универс: S&P500 + NDX (Wikipedia), с кеш и статичен fallback
# ──────────────────────────────────────────────────────────────────────────
def _sp500_ndx_universe() -> list[str]:
    if _UNIV_CACHE.exists():
        try:
            cached = json.loads(_UNIV_CACHE.read_text())
            if cached.get("date", "")[:7] == dt.date.today().isoformat()[:7]:  # обновяваме месечно
                return cached["tickers"]
        except Exception:
            pass
    tickers: list[str] = []
    if pd is not None:
        for url, idx in (("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 0),
                         ("https://en.wikipedia.org/wiki/Nasdaq-100", None)):
            try:
                tables = pd.read_html(url)
                for tbl in tables:
                    col = next((c for c in tbl.columns
                                if str(c).lower() in ("symbol", "ticker")), None)
                    if col is not None:
                        tickers += [str(s).replace(".", "-").upper() for s in tbl[col].tolist()]
                        break
            except Exception as e:
                print(f"[unusual_options] universe {url}: {e}")
    # дедупликация + статичен fallback
    tickers = sorted(set(t for t in tickers if re.fullmatch(r"[A-Z\-]{1,6}", t)))
    if not tickers:
        tickers = config.UNUSUAL_OPTIONS_UNIVERSE
    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _UNIV_CACHE.write_text(json.dumps({"date": dt.date.today().isoformat(),
                                           "tickers": tickers}, ensure_ascii=False))
    except Exception:
        pass
    return tickers


# ──────────────────────────────────────────────────────────────────────────
# PRIMARY · yfinance опционни вериги
# ──────────────────────────────────────────────────────────────────────────
def _stock_vol_ratio(tk) -> float | None:
    """Обем на акцията днес спрямо 20-дневната ѝ средна (втори сигнал)."""
    try:
        h = tk.history(period="1mo")
        if h is None or h.empty or "Volume" not in h:
            return None
        last = float(h["Volume"].iloc[-1])
        avg20 = float(h["Volume"].tail(20).mean())
        return round(last / avg20, 2) if avg20 > 0 else None
    except Exception:
        return None


def _yf_unusual(symbols: list[str], top_n: int) -> list[dict]:
    if yf is None:
        return []
    rows = []
    for sym in symbols[:config.UNUSUAL_OPTIONS_SCAN_LIMIT]:
        try:
            tk = yf.Ticker(sym)
            exps = tk.options
            if not exps:
                continue
            call_vol = put_vol = total_oi = 0
            for exp in exps[:2]:  # най-близките 2 падежа
                ch = tk.option_chain(exp)
                for df, is_call in ((ch.calls, True), (ch.puts, False)):
                    if df is None or df.empty:
                        continue
                    v = float(df.get("volume").fillna(0).sum()) if "volume" in df else 0
                    oi = float(df.get("openInterest").fillna(0).sum()) if "openInterest" in df else 0
                    total_oi += oi
                    if is_call:
                        call_vol += v
                    else:
                        put_vol += v
            total_vol = call_vol + put_vol
            if total_vol < 1000:  # отсяваме неликвидни
                continue
            # total_oi може да е 0 при ранен сутрешен fetch (OI още не е обновен) —
            # в този случай пропускаме vol/OI съотношението вместо да показваме
            # подвеждащо число (обем делен на защитния delitel 1).
            has_oi = total_oi > 0
            ratio = (total_vol / total_oi) if has_oi else None
            bias, note = _bias(call_vol, put_vol)
            svr = _stock_vol_ratio(tk)
            extra = f" Обем на акцията {svr}× 20д средна." if svr else ""
            oi_part = f" ≈ {ratio:.1f}× OI ({_oi_label(ratio)})." if ratio is not None else "."
            rows.append({"ticker": sym, "call_put_bias": bias,
                         "note": f"{note} Опц. обем {int(total_vol):,}{oi_part}{extra}",
                         "_ratio": round(ratio, 2) if ratio is not None else 0})
        except Exception as e:
            print(f"[unusual_options] yf {sym}: {e}")
            continue
    rows.sort(key=lambda r: r.get("_ratio", 0), reverse=True)
    for r in rows:
        r.pop("_ratio", None)
    return rows[:top_n]


# ──────────────────────────────────────────────────────────────────────────
# FALLBACK · Market Chameleon scrape
# ──────────────────────────────────────────────────────────────────────────
def _fetch_marketchameleon(limit: int) -> list[dict]:
    if pd is None:
        return []
    rows: list[dict] = []
    try:
        html = requests.get(_MC_URL, timeout=20, headers=_UA).text
        for tbl in pd.read_html(io.StringIO(html)):
            cols = [str(c).lower() for c in tbl.columns]
            sym_col = next((tbl.columns[i] for i, c in enumerate(cols)
                            if "symbol" in c or "ticker" in c), None)
            if sym_col is None:
                continue
            for _, r in tbl.iterrows():
                sym = re.sub(r"[^A-Z\.\-]", "", str(r[sym_col]).upper())
                if sym and len(sym) <= 6:
                    rows.append({"ticker": sym, "call_put_bias": None,
                                 "note": "Необичаен опционен обем (Market Chameleon)."})
            break
    except Exception as e:
        print(f"[unusual_options] Market Chameleon failed: {e}")
        return []
    return rows[:limit]


# ──────────────────────────────────────────────────────────────────────────
# Публично API · yfinance primary → Market Chameleon fallback
# ──────────────────────────────────────────────────────────────────────────
def fetch_unusual_options(limit: int = 10) -> list[dict]:
    """Връща топ [{ticker, call_put_bias, note}] по необичайност. Кешира за деня."""
    today = dt.date.today().isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today:
                return cached.get("rows", [])[:limit]
        except Exception:
            pass

    universe = _sp500_ndx_universe()
    rows = _yf_unusual(universe, limit)
    source = "yfinance"
    if not rows:
        rows = _fetch_marketchameleon(limit)
        source = "marketchameleon"

    seen, dedup = set(), []
    for r in rows:
        if r["ticker"] not in seen:
            seen.add(r["ticker"]); dedup.append(r)

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "source": source, "rows": dedup},
                                     ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[unusual_options] cache write: {e}")
    return dedup[:limit]


def unusual_set(rows: list[dict] | None = None) -> dict[str, dict]:
    rows = rows if rows is not None else fetch_unusual_options()
    return {r["ticker"]: r for r in rows}


if __name__ == "__main__":
    res = fetch_unusual_options()
    print(f"Unusual options: {len(res)}")
    for r in res:
        print(" ", r["ticker"], r["call_put_bias"], "·", r["note"])
