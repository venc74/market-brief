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

Пакет 4б т.а (06.10.2026): ЗНАМЕНАТЕЛЯТ е сравним между дните. Преди: "най-близките 2 падежа" — петъчният седмичен падеж държи 60–70% от OI
и влиза/излиза от двойката според деня от седмицата (TSLA 626 692 в четвъртък → 114 346 в понеделник; на жива верига ×15–×26 за една
седмица). Сега: ВСИЧКИ падежи в прозорец (ден на брифа, ден на брифа + UNUSUAL_OPTIONS_HORIZON_DAYS]; изтекъл или изтичащ в деня на брифа
падеж не участва; обемът и OI са по едни и същи падежи (падеж без OI в снимката отпада и от двете страни); снимка в стария формат (първите 4
падежа) не се ползва — съотношението от нея не е сравнимо.

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


def window_expiries(expiries, brief_date: dt.date, horizon_days: int | None = None, max_n: int | None = None) -> list[str]:
    """
    Падежите в прозореца (brief_date, brief_date + horizon_days]: строго СЛЕД деня на брифа (изтеклите и изтичащите в деня на брифа не участват —
    обемът им е roll/гама шум, а OI им умира), най-много max_n. Чиста функция.
    """
    horizon = config.UNUSUAL_OPTIONS_HORIZON_DAYS if horizon_days is None else horizon_days
    cap = config.UNUSUAL_OPTIONS_MAX_EXPIRIES if max_n is None else max_n
    hi = brief_date + dt.timedelta(days=horizon)
    out = []
    for e in sorted({str(x) for x in (expiries or [])}):
        try:
            d = dt.date.fromisoformat(e)
        except ValueError:
            continue
        if brief_date < d <= hi:
            out.append(e)
    return out[:cap]


def window_ratio(vol_by_exp: dict, oi_by_exp: dict, expiries: list[str]) -> dict:
    """
    Съотношението обем/OI по ЕДНИ И СЪЩИ падежи: падеж без обем или без OI (>0) в снимката отпада и от числителя, и от знаменателя
    (dropped). Чиста функция. ratio е None, ако не е останал нито един падеж с OI.
    """
    used = [e for e in expiries if e in vol_by_exp and (oi_by_exp.get(e) or 0) > 0]
    dropped = [e for e in expiries if e not in used]
    vol = float(sum(vol_by_exp[e] for e in used))
    oi = float(sum(oi_by_exp[e] for e in used))
    return {"used": used, "dropped": dropped, "volume": vol, "oi": oi, "ratio": (vol / oi) if oi > 0 else None}


def snapshot_in_window_format(snap: dict | None) -> bool:
    """Снимка с OI за целия времеви прозорец (нов формат: horizon_days). Старата — първите 4 падежа — не дава сравнимо съотношение."""
    return bool(snap) and (snap.get("horizon_days") or 0) >= config.UNUSUAL_OPTIONS_HORIZON_DAYS + 4


def analyze_ticker(sym: str, tk, snap: dict | None, brief_date: dt.date, snap_missing: str = "") -> dict | None:
    """
    Обем/OI на един тикър по правилото на прозореца (виж модулния docstring). tk е yfinance.Ticker (или негов заместител: .options,
    .option_chain(exp)). Връща None без падежи; иначе речник: ticker, call_vol, put_vol, total_vol, ratio (None + why при проблем),
    used/dropped (падежи), oi_used, live_oi (сутрешният OI, само за сравнение), window.
    """
    exps = tk.options
    if not exps:
        return None
    window = window_expiries(exps, brief_date)
    call_vol = put_vol = live_oi = 0.0
    vol_by_exp: dict[str, float] = {}
    for exp in window:
        ch = tk.option_chain(exp)
        for df, is_call in ((ch.calls, True), (ch.puts, False)):
            if df is None or df.empty:
                continue
            v = float(df.get("volume").fillna(0).sum()) if "volume" in df else 0
            live_oi += float(df.get("openInterest").fillna(0).sum()) if "openInterest" in df else 0
            vol_by_exp[exp] = vol_by_exp.get(exp, 0) + v
            if is_call:
                call_vol += v
            else:
                put_vol += v
    snap_oi = ((snap or {}).get("tickers") or {}).get(sym)
    why = ""
    if not window:
        why = "няма падеж в прозореца на брифа"
    elif snap is None:
        why = snap_missing or "следобедната OI снимка липсва"
    elif not snapshot_in_window_format(snap):
        why = "снимката е в стария формат (първите 4 падежа) — съотношението не е сравнимо между дните"
    elif snap_oi is None:
        why = "тикърът не е в следобедната снимка"
    res = window_ratio(vol_by_exp, snap_oi or {}, window)
    if not why and not res["used"]:
        why = "падежите не съвпадат със следобедната снимка"
    if not why and res["oi"] < 50:
        why = "OI в следобедната снимка е под 50 договора"
    return {"ticker": sym, "call_vol": call_vol, "put_vol": put_vol, "total_vol": call_vol + put_vol,
            "ratio": None if why else res["ratio"], "why": why, "used": res["used"], "dropped": res["dropped"],
            "oi_used": res["oi"] if not why else 0, "live_oi": int(live_oi), "window": window}


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
    reasons: dict[str, str] = {}
    for sym in scan_list:
        try:
            tk = yf.Ticker(sym)
            a = analyze_ticker(sym, tk, snap, dt.date.today(), snap_missing)
            if a is None:
                continue
            call_vol, put_vol, total_vol = a["call_vol"], a["put_vol"], a["total_vol"]
            if total_vol < 1000:  # отсяваме неликвидни
                continue
            ratio, why = a["ratio"], a["why"]
            snap_total, total_oi = a["oi_used"], a["live_oi"]
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
                         "_used": a["used"],
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
        # пакет 4б т.а: по кои падежи е съотношението (обем и OI — едни и същи) и размерът на прозореца
        "expiries_used": {r["ticker"]: r["_used"] for r in top},
        "window_days": config.UNUSUAL_OPTIONS_HORIZON_DAYS,
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
        for k in ("_ratio", "_oi", "_live_oi", "_oi_suspect", "_used"):
            r.pop(k, None)
    return top


# ──────────────────────────────────────────────────────────────────────────
# Пакет 4б т.б: маркер UOV✓ върху НАШИ тикъри (кандидати и позиции) — вместо списъка "Unusual Options Yesterday"
# 08.10.2026: относителен праг — перцентил спрямо референтната кошница за деня и (когато има история) спрямо собствената история (виж config.py)
# ──────────────────────────────────────────────────────────────────────────
LAST_MARKER_DIAG: dict = {}


def percentile(values: list[float], q: float) -> float | None:
    """q-ти перцентил (0–100) с линейна интерполация, без numpy; None за празен списък. Чиста функция."""
    s = sorted(float(v) for v in values)
    if not s:
        return None
    k = (len(s) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def percent_rank(prior: list[float], x: float) -> float | None:
    """Колко процента от наблюденията са под x (равните се броят наполовина) — перцентилът на x в собствената история. None за празен списък."""
    if not prior:
        return None
    below = sum(1 for v in prior if v < x)
    equal = sum(1 for v in prior if v == x)
    return 100.0 * (below + 0.5 * equal) / len(prior)


def load_ratio_history(path=None) -> dict:
    """{тикър: {дата на сесията: съотношение}}; липсващ/повреден файл → празно (с лог), никога изключение."""
    path = pathlib.Path(path or config.UNUSUAL_OPTIONS_HISTORY_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        t = data.get("tickers")
        if not isinstance(t, dict):
            raise ValueError("няма 'tickers'")
        return {k: {d: float(v) for d, v in (obs or {}).items()} for k, obs in t.items() if isinstance(obs, dict)}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[unusual_options] историята на съотношенията е нечетима ({type(e).__name__}: {e}) — започва се начисто")
        return {}


def record_ratios(history: dict, session: str, ratios: dict[str, float], keep: int | None = None) -> dict:
    """Добавя съотношенията на сесията към историята (презаписва същата дата — идемпотентно) и пази най-много `keep` най-нови дати на тикър. Връща нов речник."""
    keep = config.UNUSUAL_OPTIONS_HISTORY_KEEP if keep is None else keep
    out = {t: dict(obs) for t, obs in history.items()}
    for sym, r in ratios.items():
        obs = out.setdefault(sym, {})
        obs[session] = round(float(r), 4)
        if len(obs) > keep:
            for d in sorted(obs)[:len(obs) - keep]:
                del obs[d]
    return out


def save_ratio_history(history: dict, path=None) -> None:
    """Атомичен запис; провал → лог, не изключение."""
    import os, tempfile
    path = pathlib.Path(path or config.UNUSUAL_OPTIONS_HISTORY_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".uov_hist_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "tickers": {t: dict(sorted(o.items())) for t, o in sorted(history.items())}}, f, ensure_ascii=False, indent=0)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[unusual_options] историята на съотношенията не се записа: {type(e).__name__}: {e}")


_ANALYSIS_MEMO: dict = {}          # (тикър, ден на брифа, снимка) → резултат на analyze_ticker: един тикър е и в кошницата, и сред нашите — една верига на run
_BASKET_MEMO: dict = {}            # (сесия, ден на брифа, снимка) → резултат на reference_basket: кошницата се смята веднъж на run (кандидати и позиции викат candidate_markers поотделно)


def _analysis_memo(sym: str, snap: dict | None, brief_date: dt.date, snap_missing: str) -> dict | None:
    key = (sym, brief_date.isoformat(), (snap or {}).get("fetched_at_utc"))
    if key not in _ANALYSIS_MEMO:
        _ANALYSIS_MEMO[key] = analyze_ticker(sym, yf.Ticker(sym), snap, brief_date, snap_missing)
    return _ANALYSIS_MEMO[key]


def reference_basket(snap: dict | None, session: str, brief_date: dt.date, snap_missing: str = "", budget_sec: float | None = None,
                     clock=None) -> dict:
    """
    Референтната кошница за деня: съотношенията обем/OI на най-ликвидните тикъри (snap["reference"], снимани заедно с нашите) за същата сесия и прозорец.
    Връща {reference, valid, ratios {тикър: съотношение}, p (праг: UNUSUAL_OPTIONS_MARKER_PERCENTILE-ият перцентил или None), median, missing {тикър: причина},
    reason (защо няма праг), stopped (спряно по бюджета)}. Сканирането е ограничено по време (UNUSUAL_OPTIONS_REFERENCE_BUDGET_SEC); провал на тикър → пропуска се.
    Праг има само при поне config.UNUSUAL_OPTIONS_REFERENCE_MIN_VALID валидни съотношения.
    """
    import time
    key = (session, brief_date.isoformat(), (snap or {}).get("fetched_at_utc"))
    if key in _BASKET_MEMO:
        return _BASKET_MEMO[key]
    clock = clock or time.monotonic
    budget = config.UNUSUAL_OPTIONS_REFERENCE_BUDGET_SEC if budget_sec is None else budget_sec
    ref = [t for t in ((snap or {}).get("reference") or []) if isinstance(t, str)]
    out: dict = {"reference": len(ref), "valid": 0, "ratios": {}, "p": None, "median": None, "missing": {}, "reason": "", "stopped": False}
    if not ref:
        out["reason"] = "снимката няма референтна кошница" if snap else (snap_missing or "няма снимка")
    elif yf is None:
        out["reason"] = "yfinance липсва"
    else:
        t0 = clock()
        for sym in ref:
            if clock() - t0 > budget:
                out["stopped"] = True
                break
            try:
                a = _analysis_memo(sym, snap, brief_date, snap_missing)
            except Exception as e:
                out["missing"][sym] = f"{type(e).__name__}: {e}"
                continue
            if a is None or a["why"] or a["ratio"] is None:
                out["missing"][sym] = (a or {}).get("why") or "няма опционна верига"
            elif a["ratio"] > config.UNUSUAL_OPTIONS_MAX_OI_RATIO:
                out["missing"][sym] = "OI вероятно неактуален/непълен (нереалистично съотношение)"
            else:
                out["ratios"][sym] = round(a["ratio"], 4)
        out["valid"] = len(out["ratios"])
        if out["valid"] >= config.UNUSUAL_OPTIONS_REFERENCE_MIN_VALID:
            out["p"] = round(percentile(list(out["ratios"].values()), config.UNUSUAL_OPTIONS_MARKER_PERCENTILE), 4)
            out["median"] = round(percentile(list(out["ratios"].values()), 50), 4)
        else:
            out["reason"] = (f"валидни съотношения в кошницата {out['valid']} от {out['reference']} (нужни ≥ {config.UNUSUAL_OPTIONS_REFERENCE_MIN_VALID})"
                             + (" — спряно по бюджета" if out["stopped"] else ""))
    _BASKET_MEMO[key] = out
    return out


def marker_decision(sym: str, ratio: float, basket: dict, prior: list[float]) -> dict:
    """
    Решението за маркер на един наш тикър (чиста функция). prior — собствените му наблюдения ПРЕДИ днешната сесия.
      • абсолютен път: ratio ≥ UNUSUAL_OPTIONS_MARKER_MIN_RATIO (2.0);
      • по история: ≥ UNUSUAL_OPTIONS_HISTORY_MIN_DAYS наблюдения → перцентил спрямо тях ≥ UNUSUAL_OPTIONS_MARKER_PERCENTILE;
      • за деня: иначе, ако кошницата има праг → ratio ≥ P на кошницата.
    Връща {marked, mode ("absolute"/"history"/"day"/None), percentile (спрямо историята или кошницата, или None), threshold, why (при marked=False и липсващ път)}.
    """
    q = config.UNUSUAL_OPTIONS_MARKER_PERCENTILE
    out = {"marked": False, "mode": None, "percentile": None, "threshold": None, "history_days": len(prior), "why": ""}
    if len(prior) >= config.UNUSUAL_OPTIONS_HISTORY_MIN_DAYS:
        pr = percent_rank(prior, ratio)
        out.update(mode="history", percentile=round(pr, 1), threshold=round(percentile(prior, q), 4), marked=pr >= q)
    elif basket.get("p") is not None:
        vals = list(basket["ratios"].values())
        pr = 100.0 * sum(1 for v in vals if v <= ratio) / len(vals)
        out.update(mode="day", percentile=round(pr, 1), threshold=basket["p"], marked=ratio >= basket["p"])
    else:
        out["why"] = f"няма с какво да се сравни: {basket.get('reason') or 'кошницата няма праг'}; собствена история {len(prior)} от {config.UNUSUAL_OPTIONS_HISTORY_MIN_DAYS} дни"
    if not out["marked"] and ratio >= config.UNUSUAL_OPTIONS_MARKER_MIN_RATIO:
        out.update(marked=True, mode="absolute")
    return out


def _fmt_ratio(x: float) -> str:
    """Съотношението с достатъчно знаци: 0.83, 0.26, 0.014 (под 0.1 — три знака), 3.25."""
    return f"{x:.3f}" if abs(x) < 0.1 else f"{x:.2f}"


def _marker_basis(dec: dict, basket: dict) -> str:
    q = f"{config.UNUSUAL_OPTIONS_MARKER_PERCENTILE:g}"
    if dec["mode"] == "absolute":
        return f"над абсолютния праг от {config.UNUSUAL_OPTIONS_MARKER_MIN_RATIO:g}× (силно ново позициониране)"
    if dec["mode"] == "history":
        return f"над {q}-ия перцентил на собствената му история (праг {_fmt_ratio(dec['threshold'])}×, {dec['history_days']} дни)"
    return f"над {q}-ия перцентил на {basket['valid']} ликвидни тикъра за деня (праг {_fmt_ratio(dec['threshold'])}×)"


def _marker_note(a: dict, ratio: float, session: str, dec: dict | None = None, basket: dict | None = None) -> str:
    """Текстът при hover/клик: колко, спрямо какво е необичайно, по какви падежи, с каква посока и кога е снимката на OI."""
    bias, bias_note = _bias(a["call_vol"], a["put_vol"])
    calls_pct = (100 * a["call_vol"] / a["total_vol"]) if a["total_vol"] else 0
    used = a["used"]
    basis = _marker_basis(dec, basket or {}) if dec else _oi_label(ratio)
    return (f"Необичаен опционен обем вчера: ≈ {_fmt_ratio(ratio)}× OI — {basis}; върху {len(used)} падежа до {used[-1][8:10]}.{used[-1][5:7]} "
            f"(без изтеклите и изтичащите днес). Обем {int(a['total_vol']):,} / OI {int(a['oi_used']):,} договора; calls {calls_pct:.0f}% от обема — {bias_note} "
            f"OI е от следобедната снимка на сесията {session[8:10]}.{session[5:7]}.")


def candidate_markers(tickers: list[str], today: dt.date | None = None) -> tuple[dict, dict]:
    """
    Съотношението обем/OI (по прозореца на падежите, виж analyze_ticker) за НАШИТЕ тикъри; маркер за онези, които минават marker_decision (перцентил спрямо
    референтната кошница за деня или собствената история; абсолютният праг 2.0 остава като допълнителен път).
    Връща ({тикър: {ticker, ratio, call_put_bias, note, expiries, mode, percentile}}, diag). diag: scanned, with_ratio, marked, ratios (ВСИЧКИ пресметнати),
    missing {тикър: причина} (тикър без съотношение НЕ значи "без необичаен обем"), basket {reference, valid, p, median, reason, stopped}, decisions {тикър: решение},
    snapshot_session/…_fetched_at_utc, snapshot_missing_reason. Историята на съотношенията (кошница + нашите) се допълва с днешната сесия.
    Graceful: провал на тикър/снимка/кошница → празен резултат за него, не чупи run-а.
    """
    today = today or dt.date.today()
    tickers = list(dict.fromkeys(t for t in tickers if t))[:config.UNUSUAL_OPTIONS_MARKER_MAX_TICKERS]
    diag: dict = {"requested": len(tickers), "scanned": 0, "with_ratio": 0, "marked": 0, "ratios": {}, "missing": {}, "decisions": {}, "no_basis": {},
                  "window_days": config.UNUSUAL_OPTIONS_HORIZON_DAYS, "min_ratio": config.UNUSUAL_OPTIONS_MARKER_MIN_RATIO,
                  "percentile": config.UNUSUAL_OPTIONS_MARKER_PERCENTILE, "history_min_days": config.UNUSUAL_OPTIONS_HISTORY_MIN_DAYS, "basket": None,
                  "snapshot_session": None, "snapshot_fetched_at_utc": None, "snapshot_missing_reason": ""}
    markers: dict[str, dict] = {}
    if yf is None or not tickers:
        return markers, diag
    try:
        snap, session, snap_missing = _snapshot_for_yesterday(today)
    except Exception as e:
        snap, session, snap_missing = None, "", f"снимката не се зареди: {type(e).__name__}"
    diag.update(snapshot_session=session or None, snapshot_fetched_at_utc=(snap or {}).get("fetched_at_utc"), snapshot_missing_reason=snap_missing)
    try:
        basket = reference_basket(snap, session or today.isoformat(), today, snap_missing)
    except Exception as e:
        basket = {"reference": 0, "valid": 0, "ratios": {}, "p": None, "median": None, "missing": {}, "reason": f"кошницата не се пресметна: {type(e).__name__}: {e}", "stopped": False}
        print(f"[unusual_options] референтна кошница: {type(e).__name__}: {e}")
    diag["basket"] = {k: basket.get(k) for k in ("reference", "valid", "p", "median", "reason", "stopped")}
    history = load_ratio_history()
    exact: dict[str, float] = {}                                            # точните съотношения на нашите тикъри (diag["ratios"] е закръглен до 2 знака) — за историята
    for sym in tickers:
        try:
            a = _analysis_memo(sym, snap, today, snap_missing)
        except Exception as e:
            diag["missing"][sym] = f"{type(e).__name__}: {e}"
            print(f"[unusual_options] маркер {sym}: {e}")
            continue
        if a is None:
            diag["missing"][sym] = "няма опционна верига"
            continue
        diag["scanned"] += 1
        if a["why"]:
            diag["missing"][sym] = a["why"]
            continue
        ratio = a["ratio"]
        if ratio > config.UNUSUAL_OPTIONS_MAX_OI_RATIO:                    # същият таван като преди: OI вероятно неактуален/непълен
            diag["missing"][sym] = "OI вероятно неактуален/непълен (нереалистично съотношение)"
            continue
        diag["with_ratio"] += 1
        diag["ratios"][sym] = round(ratio, 2)
        exact[sym] = ratio
        prior = [v for d, v in (history.get(sym) or {}).items() if d < (session or today.isoformat())]
        dec = marker_decision(sym, ratio, basket, prior)
        diag["decisions"][sym] = {k: dec[k] for k in ("marked", "mode", "percentile", "threshold", "history_days")}
        if dec["why"]:                                                      # има съотношение, но няма с какво да се сравни (не е "без съотношение")
            diag["no_basis"][sym] = dec["why"]
        if dec["marked"]:
            bias, _ = _bias(a["call_vol"], a["put_vol"])
            markers[sym] = {"ticker": sym, "ratio": round(ratio, 2), "call_put_bias": bias, "expiries": a["used"], "mode": dec["mode"], "percentile": dec["percentile"],
                            "note": _marker_note(a, ratio, session or today.isoformat(), dec, basket)}
    diag["marked"] = len(markers)
    # историята: днешната сесия за кошницата и за нашите тикъри (идемпотентно по дата); без известна сесия не се записва нищо
    if session:
        try:
            obs = {**basket.get("ratios", {}), **exact}
            if obs:
                save_ratio_history(record_ratios(history, session, obs))
        except Exception as e:
            print(f"[unusual_options] историята не се допълни: {type(e).__name__}: {e}")
    LAST_MARKER_DIAG.clear(); LAST_MARKER_DIAG.update(diag)
    b = diag["basket"] or {}
    print(f"[unusual_options] маркери UOV✓: {len(markers)} от {diag['requested']} (съотношение за {diag['with_ratio']}; кошница {b.get('valid')}/{b.get('reference')}, "
          f"P{config.UNUSUAL_OPTIONS_MARKER_PERCENTILE:g} = {b.get('p')}{', ' + b['reason'] if b.get('reason') else ''}; без съотношение: {diag['missing'] or '—'})")
    return markers, diag


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
