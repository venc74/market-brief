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
тикъра на ден. Изборът НЕ е азбучен (иначе всеки ден се сканират само A–C
имена) — универсът се сортира по среден 20-дневен обем на АКЦИЯТА (ликвидност)
низходящо и се взима топ N; резултатът се кешира за деня, за да не тегли обема
повторно при повторни пускания. FALLBACK: Market Chameleon scrape, ако
yfinance върне нищо.

Graceful degradation: липсват ли данни за тикър — пропуска се; празно → секцията се крие.

FIX 2026-09-29: знаменателят OI идва от следобедната снимка на СЪЩАТА сесия
(src/oi_snapshot.py, отделен GitHub Actions job), не от сутрешния fetch — в
05:30–05:55 UTC Yahoo връща празен/непълен OI. Липсва ли снимка/тикър/падеж →
без съотношение, с причина в diag и на страницата.
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
_VOLUME_RANK_CACHE = config.DATA_DIR / "unusual_options_volume_rank_cache.json"
# FIX 2026-09-28: диагностика на последния fetch (виж _yf_unusual) → брифа
LAST_DIAG: dict = {}


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


def _stock_vol_label(svr: float) -> str:
    """Кратко обяснение какво означава обема на акцията спрямо 20д средна."""
    if svr < 1.0:
        return "под нормалното"
    if svr < 1.3:
        return "нормално"
    if svr < 2.0:
        return "повишен интерес"
    return "екстремен интерес"


# ──────────────────────────────────────────────────────────────────────────
# Универс: S&P500 (live Wikipedia scrape) + NDX100 (статичен списък), с кеш
# ──────────────────────────────────────────────────────────────────────────
def _sp500_ndx_universe() -> list[str]:
    """
    S&P500 (live Wikipedia scrape, UA header — pd.read_html(url) директно гърми
    с 403, Wikipedia блокира заявки без browser-like User-Agent) + NDX100
    (config.NDX100_STATIC_TICKERS — Wikipedia премахна структурираната
    компонентна таблица от Nasdaq-100 статията, вече не е скрейпваем източник,
    виж коментара при константата за ръчно обновяване). Кешира месечно; при
    провал на S&P500 scrape-а пада само на NDX100 статичния списък, а при
    напълно празен резултат — config.UNUSUAL_OPTIONS_UNIVERSE.
    """
    if _UNIV_CACHE.exists():
        try:
            cached = json.loads(_UNIV_CACHE.read_text())
            if cached.get("date", "")[:7] == dt.date.today().isoformat()[:7]:  # обновяваме месечно
                return cached["tickers"]
        except Exception:
            pass

    tickers: list[str] = list(config.NDX100_STATIC_TICKERS)
    if pd is not None:
        try:
            html = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                               headers=_UA, timeout=20).text
            tables = pd.read_html(io.StringIO(html))
            for tbl in tables:
                col = next((c for c in tbl.columns
                            if str(c).lower() in ("symbol", "ticker")), None)
                if col is not None:
                    tickers += [str(s).replace(".", "-").upper() for s in tbl[col].tolist()]
                    break
        except Exception as e:
            print(f"[unusual_options] S&P500 universe scrape: {e}")

    # дедупликация + статичен fallback (само ако дори NDX100 списъкът излезе празен)
    tickers = sorted(set(t for t in tickers if re.fullmatch(r"[A-Z\-]{1,6}", t)))
    if not tickers:
        tickers = config.UNUSUAL_OPTIONS_UNIVERSE
    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _UNIV_CACHE.write_text(json.dumps({"date": dt.date.today().isoformat(),
                                           "tickers": tickers}, ensure_ascii=False, default=str))
    except Exception:
        pass
    return tickers


# ──────────────────────────────────────────────────────────────────────────
# Ранжиране на универса по ликвидност (обем на АКЦИЯТА, не на опциите)
# ──────────────────────────────────────────────────────────────────────────
def _avg_volumes(symbols: list[str], batch_size: int = 200) -> dict[str, float]:
    """Среден 20-дневен обем на акцията за целия универс, на батчове (евтино спрямо опционни вериги)."""
    out: dict[str, float] = {}
    if yf is None:
        return out
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            data = yf.download(batch, period="1mo", progress=False,
                               auto_adjust=True, threads=True)["Volume"]
        except Exception as e:
            print(f"[unusual_options] volume batch {i} failed: {e}")
            continue
        if pd is not None and isinstance(data, pd.Series):
            data = data.to_frame(name=batch[0])
        for sym in batch:
            if sym not in data.columns:
                continue
            series = data[sym].dropna()
            if len(series):
                out[sym] = float(series.mean())
    return out


def _top_by_volume(universe: list[str], top_n: int) -> list[str]:
    """
    Топ N тикъра по среден 20-дневен обем на акцията (ликвидност), низходящо —
    вместо предишния азбучен ред (който винаги сканираше само A–C имена).
    Кешира се за деня, за да не тегли обемните данни повторно при повторни
    пускания same day.
    """
    today = dt.date.today().isoformat()
    if _VOLUME_RANK_CACHE.exists():
        try:
            cached = json.loads(_VOLUME_RANK_CACHE.read_text())
            if cached.get("date") == today and cached.get("ranked"):
                return cached["ranked"][:top_n]
        except Exception:
            pass

    volumes = _avg_volumes(universe)
    if not volumes:
        # без обемни данни — пази стария ред, вместо да строши сканирането
        print("[unusual_options] volume ranking неуспешен — пазя оригиналния ред")
        return universe[:top_n]

    ranked = sorted(volumes, key=volumes.get, reverse=True)
    ranked += [s for s in universe if s not in volumes]  # без данни → накрая, не се губят

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _VOLUME_RANK_CACHE.write_text(json.dumps({"date": today, "ranked": ranked},
                                                  ensure_ascii=False, default=str))
    except Exception as e:
        print(f"[unusual_options] volume rank cache write: {e}")

    return ranked[:top_n]


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


# ──────────────────────────────────────────────────────────────────────────
# FIX 2026-09-29: OI от следобедна снимка (src/oi_snapshot.py, отделен Actions job)
# ──────────────────────────────────────────────────────────────────────────
def last_session_date() -> dt.date | None:
    """Датата на последната (или текущата) US сесия — последният дневен бар на SPY."""
    if yf is None:
        return None
    try:
        h = yf.Ticker("SPY").history(period="5d")
        return h.index[-1].date() if h is not None and not h.empty else None
    except Exception as e:
        print(f"[unusual_options] датата на последната сесия: {e}")
        return None


def load_oi_snapshots() -> dict:
    try:
        return json.loads(config.UNUSUAL_OPTIONS_OI_SNAPSHOT_FILE.read_text()).get("snapshots", {})
    except Exception:
        return {}


def _snapshot_for_yesterday(today: dt.date) -> tuple[dict | None, str, str]:
    """
    Сутрешният обем е от последната сесия → OI трябва да е снимката от СЪЩАТА
    сесия (началото ѝ). Връща (снимка, сесия, причина при липса).
    """
    snaps = load_oi_snapshots()
    session = last_session_date()
    if session is not None:
        snap = snaps.get(session.isoformat())
        if snap:
            return snap, session.isoformat(), ""
        return None, session.isoformat(), (f"следобедната OI снимка за сесията "
                                           f"{session.strftime('%d.%m')} липсва")
    # без дата на сесията — най-новата снимка отпреди днес, ако е до 4 дни стара
    older = sorted(d for d in snaps if d < today.isoformat())
    if older and (today - dt.date.fromisoformat(older[-1])).days <= 4:
        return snaps[older[-1]], older[-1], ""
    return None, "", "следобедната OI снимка липсва (датата на сесията не е известна)"


def _yf_unusual(symbols: list[str], top_n: int) -> list[dict]:
    if yf is None:
        return []
    rows = []
    scan_list = _top_by_volume(symbols, config.UNUSUAL_OPTIONS_SCAN_LIMIT)
    snap, session, snap_missing = _snapshot_for_yesterday(dt.date.today())
    snap_oi = (snap or {}).get("tickers") or {}
    reasons: dict[str, str] = {}
    for sym in scan_list:
        try:
            tk = yf.Ticker(sym)
            exps = tk.options
            if not exps:
                continue
            call_vol = put_vol = total_oi = 0
            vol_by_exp: dict[str, float] = {}
            for exp in exps[:2]:  # най-близките 2 падежа
                ch = tk.option_chain(exp)
                for df, is_call in ((ch.calls, True), (ch.puts, False)):
                    if df is None or df.empty:
                        continue
                    v = float(df.get("volume").fillna(0).sum()) if "volume" in df else 0
                    oi = float(df.get("openInterest").fillna(0).sum()) if "openInterest" in df else 0
                    total_oi += oi
                    vol_by_exp[exp] = vol_by_exp.get(exp, 0) + v
                    if is_call:
                        call_vol += v
                    else:
                        put_vol += v
            total_vol = call_vol + put_vol
            if total_vol < 1000:  # отсяваме неликвидни
                continue
            # FIX 2026-09-29: съотношението е обем / OI от следобедната снимка на
            # СЪЩАТА сесия, само по падежите, които са и в двете (обем и OI от
            # едни и същи падежи). Сутрешният OI (total_oi) остава само в
            # диагностиката за сравнение — в 05:35 UTC е празен/непълен.
            # Праг от 50 договора избягва абсурдни съотношения от почти-нулев OI.
            why = ""
            if snap is None:
                why = snap_missing
            elif sym not in snap_oi:
                why = "тикърът не е в следобедната снимка"
            matched = [e for e in vol_by_exp if (snap_oi.get(sym) or {}).get(e, 0) > 0]
            if not why and not matched:
                why = "падежите не съвпадат със следобедната снимка"
            snap_total = sum(snap_oi[sym][e] for e in matched) if matched else 0
            if not why and snap_total < 50:
                why = "OI в следобедната снимка е под 50 договора"
            has_oi = not why
            ratio = (sum(vol_by_exp[e] for e in matched) / snap_total) if has_oi else None
            if why:
                reasons[sym] = why
            # FIX 2026-09-12: долният праг (>=50 контракта) хваща само буквална
            # нула/near-нула — потвърдено на живо (08-11.09), yfinance openInterest
            # понякога връща непълни данни за multi-day прозорец, кацащи ТОЧНО над
            # този праг (51, 52, 60 контракта за mega-cap с реален OI в стотици
            # хиляди) — довеждащи до подвеждащи "6900× OI" читания. Горен sanity
            # ceiling third-ира implausibly високо съотношение като вероятно
            # неактуални/непълни OI данни, не като genuine екстремна активност —
            # виж config.UNUSUAL_OPTIONS_MAX_OI_RATIO коментара за пълния rationale.
            oi_suspect = ratio is not None and ratio > config.UNUSUAL_OPTIONS_MAX_OI_RATIO
            bias, note = _bias(call_vol, put_vol)
            svr = _stock_vol_ratio(tk)
            extra = f" Обем на акцията {svr}× 20д средна ({_stock_vol_label(svr)})." if svr else ""
            if oi_suspect:
                oi_part = " OI данните вероятно неактуални/непълни (пропуснато съотношение)."
            elif ratio is not None:
                oi_part = f" ≈ {ratio:.1f}× OI ({_oi_label(ratio)})."
            else:
                oi_part = "."
            rows.append({"ticker": sym, "call_put_bias": bias,
                         "note": f"{note} Опц. обем {int(total_vol):,}{oi_part}{extra}",
                         # FIX 2026-09-28: изрично поле + суров OI за диагностиката
                         "has_oi_ratio": ratio is not None and not oi_suspect,
                         "_oi": snap_total, "_live_oi": int(total_oi), "_oi_suspect": oi_suspect,
                         "_ratio": round(ratio, 2) if (ratio is not None and not oi_suspect) else 0})
        except Exception as e:
            print(f"[unusual_options] yf {sym}: {e}")
            continue
    rows.sort(key=lambda r: r.get("_ratio", 0), reverse=True)
    top = rows[:top_n]
    # FIX 2026-09-28: от 21.09 OI в 05:55 UTC идва празен за 9/10 (до 18.09 —
    # 10/10; в 13:54 UTC на 28.09 OI си беше там) — без съотношение
    # подредбата пада до реда на сканиране = ликвидност на акцията. Диагностика
    # за всеки ден: колко имат съотношение, суровият OI, часът на fetch-а.
    LAST_DIAG.clear()
    LAST_DIAG.update({
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "scanned_with_volume": len(rows),
        "with_ratio": sum(1 for r in top if r.get("has_oi_ratio")),
        "shown": len(top),
        "oi_missing": [r["ticker"] for r in top if r["_oi"] < 50],
        "oi_suspect": [r["ticker"] for r in top if r["_oi_suspect"]],
        # FIX 2026-09-29: raw_oi = OI от следобедната снимка (използваният);
        # live_oi_morning = сутрешният, само за сравнение
        "raw_oi": {r["ticker"]: r["_oi"] for r in top},
        "live_oi_morning": {r["ticker"]: r["_live_oi"] for r in top},
        "oi_source": "afternoon_snapshot",
        "snapshot_session": session,
        "snapshot_fetched_at_utc": (snap or {}).get("fetched_at_utc"),
        "ratio_missing_reasons": {r["ticker"]: reasons[r["ticker"]]
                                  for r in top if r["ticker"] in reasons},
        # една причина за цялата секция, ако снимката липсва изцяло
        "snapshot_missing_reason": snap_missing,
    })
    grouped: dict[str, list[str]] = {}
    for t, why in LAST_DIAG["ratio_missing_reasons"].items():
        grouped.setdefault(why, []).append(t)
    LAST_DIAG["ratio_missing_grouped"] = grouped
    print(f"[unusual_options] {LAST_DIAG['fetched_at_utc']} UTC: съотношение обем/OI за "
          f"{LAST_DIAG['with_ratio']}/{LAST_DIAG['shown']} (OI от снимката на сесия "
          f"{session or '?'}, заснета {LAST_DIAG['snapshot_fetched_at_utc'] or '—'}); "
          f"без съотношение: {LAST_DIAG['ratio_missing_reasons'] or '—'}; "
          f"сутрешен OI за сравнение: {LAST_DIAG['live_oi_morning']}")
    for r in rows:
        for k in ("_ratio", "_oi", "_live_oi", "_oi_suspect"):
            r.pop(k, None)
    return top


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
                LAST_DIAG.clear(); LAST_DIAG.update(cached.get("diag") or {})
                return cached.get("rows", [])[:limit]
        except Exception:
            pass

    LAST_DIAG.clear()
    universe = _sp500_ndx_universe()
    rows = _yf_unusual(universe, limit)
    source = "yfinance"
    if not rows:
        rows = _fetch_marketchameleon(limit)
        source = "marketchameleon"
    LAST_DIAG["source"] = source

    seen, dedup = set(), []
    for r in rows:
        if r["ticker"] not in seen:
            seen.add(r["ticker"]); dedup.append(r)

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "source": source, "rows": dedup,
                                      "diag": LAST_DIAG},
                                     ensure_ascii=False, indent=1, default=str))
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
