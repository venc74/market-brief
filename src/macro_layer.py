"""
Слой 1: Глобален макро контекст.
Събира сурови данни от FRED и yfinance (NewsAPI е махнат на 2026-10-03). Синтезът на естествен
език се прави по-късно от ai_brief.py — този модул връща само факти.
"""
from __future__ import annotations
import datetime as dt
import requests
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src.series_utils import last_and_week_ago

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def _fred_series(series_id: str, days: int = 90) -> list[tuple[str, float]]:
    """Връща (дата, стойност) наблюдения от FRED за последните N дни."""
    if not config.FRED_API_KEY:
        return []
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    try:
        r = requests.get(FRED_BASE, params={
            "series_id": series_id, "api_key": config.FRED_API_KEY,
            "file_type": "json", "observation_start": start,
        }, timeout=20)
        r.raise_for_status()
        out = []
        for obs in r.json().get("observations", []):
            if obs["value"] not in (".", ""):
                out.append((obs["date"], float(obs["value"])))
        return out
    except Exception as e:
        print(f"[macro] FRED {series_id} failed: {e}")
        return []


def _wednesday_points(walcl, tga, rrp) -> list[dict]:
    """
    Пакет 2 т.2: седмични точки Net Liquidity, и трите компонента към ЕДНА сряда. walcl/tga са
    (дата, млн $) "Wednesday level"; rrp е дневна (дата, млрд $). За всяка сряда на WALCL е нужно TGA
    ниво на същата дата; RRP е стойността на същия ден или на последния работен ден до 4 дни назад
    (празник в сряда). Седмица, на която липсва компонент, се пропуска (не се приближава).
    Връща възходящ списък {date, nl_bn, walcl_bn, tga_bn, rrp_bn}.
    """
    tga_by = dict(tga)
    rrp_sorted = sorted((dt.date.fromisoformat(d), v) for d, v in rrp)
    out = []
    for d, w in sorted(walcl):
        t_val = tga_by.get(d)
        if t_val is None:
            continue
        day = dt.date.fromisoformat(d)
        r_val = None
        for rd, rv in reversed(rrp_sorted):
            if rd <= day:
                if (day - rd).days <= 4:
                    r_val = rv
                break
        if r_val is None:
            continue
        out.append({"date": d, "nl_bn": round(w / 1000 - r_val - t_val / 1000, 1),
                    "walcl_bn": round(w / 1000, 1), "tga_bn": round(t_val / 1000, 1), "rrp_bn": round(r_val, 1)})
    return out


def _liquidity_color(change_pct: float) -> str:
    change_pct = round(change_pct, 6)               # граница ±1.00% точно, без float шум (5050/5000-1 = 1.0000000000000009)
    dz = config.NET_LIQ_DEAD_ZONE_PCT
    return "green" if change_pct > dz else ("red" if change_pct < -dz else "yellow")


def _confirmed_color(raw: list[str], weeks: int) -> str:
    """
    Цветът за показване със закъснение: нов цвят се приема едва след `weeks` ПОРЕДНИ седмици със същия
    сурови цвят; докато това не стане, остава предишният. Започва от първия цвят на серията.
    """
    shown = raw[0]
    run, cand = 1, raw[0]
    for c in raw[1:]:
        if c == cand:
            run += 1
        else:
            cand, run = c, 1
        if run >= weeks:
            shown = cand
    return shown


def liquidity_signal(points: list[dict]) -> dict:
    """
    Информативният сигнал върху седмичните точки (виж _wednesday_points): промяна за NET_LIQ_WINDOW_WEEKS
    седмици в % от нивото, мъртва зона ±NET_LIQ_DEAD_ZONE_PCT% → жълто, показван цвят с потвърждение от
    NET_LIQ_CONFIRM_WEEKS поредни седмици. Без достатъчно история → value=None, hide=True.
    """
    n, w = len(points), config.NET_LIQ_WINDOW_WEEKS
    if n < w + 1:
        return {"value": None, "trend": "unknown", "history": [], "hide": True}
    raw = []
    for i in range(w, n):
        base = points[i - w]["nl_bn"]
        raw.append(_liquidity_color((points[i]["nl_bn"] / base - 1) * 100) if base else "yellow")
    last, base = points[-1], points[-1 - w]
    change = round((last["nl_bn"] / base["nl_bn"] - 1) * 100, 6) if base["nl_bn"] else 0.0
    color = _confirmed_color(raw, config.NET_LIQ_CONFIRM_WEEKS)
    dz = config.NET_LIQ_DEAD_ZONE_PCT
    return {
        "value": last["nl_bn"], "prev": base["nl_bn"], "as_of": last["date"],
        "change_4w_pct": round(change, 2), "window_weeks": w, "dead_zone_pct": dz,
        "raw_color": raw[-1], "color": color,
        "trend": "up" if change > dz else ("down" if change < -dz else "flat"),
        "components": {"fed_balance_bn": last["walcl_bn"], "rrp_bn": last["rrp_bn"], "tga_bn": last["tga_bn"]},
        "history": points[-8:], "informational": True,
    }


def fed_net_liquidity() -> dict:
    """
    Net Liquidity = WALCL − RRP − TGA, в млрд $ — ИНФОРМАТИВЕН индикатор (не влиза в броенето за режима).
    Сметката е върху седмични нива към една и съща сряда (WALCL "Wednesday level", TGA "Wednesday level"
    = WDTGAL, не WTREGEN, която е седмична СРЕДНА; RRPONTSYD от същия ден), 4-седмична промяна,
    мъртва зона ±1% и цвят с потвърждение от 2 седмици — виж config.NET_LIQ_* и liquidity_signal().

    FIX 2026-08-18: staleness guard — WALCL/WDTGAL са седмични (config.FED_LIQUIDITY_STALENESS_DAYS),
    RRPONTSYD е дневна (config.STALENESS_THRESHOLD_DAYS). Застояли/липсващи данни → value=None, hide=True.
    """
    # 13.10.2026: скритият индикатор носи ПРИЧИНАТА (hide_reason) — картата на термометъра я показва; до 13.10 изчезваше без ред и без банер
    hide = lambda why: {"value": None, "trend": "unknown", "history": [], "hide": True, "hide_reason": why}
    days = config.NET_LIQ_HISTORY_DAYS
    walcl = _fred_series("WALCL", days=days)                       # млн $, седмична, сряда
    tga = _fred_series(config.NET_LIQ_TGA_SERIES, days=days)       # млн $, седмична, сряда
    rrp = _fred_series("RRPONTSYD", days=days)                     # млрд $, дневна
    if not (walcl and rrp and tga):
        missing = [n for n, sr in (("WALCL", walcl), (config.NET_LIQ_TGA_SERIES, tga), ("RRPONTSYD", rrp)) if not sr]
        return hide(f"FRED не върна данни за {', '.join(missing)}")
    from src.setup_rules import sessions_between
    for label, series, threshold in (
        ("WALCL", walcl, config.FED_LIQUIDITY_STALENESS_DAYS),
        (config.NET_LIQ_TGA_SERIES, tga, config.FED_LIQUIDITY_STALENESS_DAYS),
        ("RRPONTSYD", rrp, None),
    ):
        d = dt.date.fromisoformat(series[-1][0])
        # 13.10.2026: RRP (дневна) — по сесии като 2s10s (допуск config.FRED_DAILY_MAX_LAG_SESSIONS = 2), не 3 календарни дни: на 13.10 последната точка беше
        # 09.10 (Columbus Day 12.10 — облигационен празник, NYSE работи) → 4 дни > 3 → индикаторът изчезна. Седмичните — непроменени (календарни дни).
        stale = (sessions_between(d, dt.date.today()) > config.FRED_DAILY_MAX_LAG_SESSIONS) if threshold is None else _is_stale(d, threshold)
        if stale:
            limit = f"{config.FRED_DAILY_MAX_LAG_SESSIONS} сесии" if threshold is None else f"{threshold}д"
            print(f"[macro] Net Liquidity: {label} stale (последно наблюдение {d}, праг {limit})")
            return hide(f"{label} застояла — последно наблюдение {d.strftime('%d.%m')} (праг {limit})")
    points = _wednesday_points(walcl, tga, rrp)
    if points and _is_stale(dt.date.fromisoformat(points[-1]["date"]), config.FED_LIQUIDITY_STALENESS_DAYS):
        print(f"[macro] Net Liquidity: няма цяла сряда с трите компонента след {points[-1]['date']}")
        return hide(f"няма цяла сряда с трите компонента след {dt.date.fromisoformat(points[-1]['date']).strftime('%d.%m')}")
    return liquidity_signal(points)


def funding_spread(sofr: list[tuple[str, float]], ioer: list[tuple[str, float]], iorb: list[tuple[str, float]], today: dt.date | None = None) -> dict:
    """
    16.10.2026 · SOFR − IORB (до config.FUNDING_STRESS_IORB_FROM — IOER) в б.п. — чиста функция върху (дата, %) сериите. Ставката на Fed е стъпаловидна: за всеки ден на SOFR се взема
    последната известна стойност ≤ датата. Перцентил и z-score на последната точка спрямо всички предишни (от config.FUNDING_STRESS_FROM); промяна за седмица — по ДАТА (last_and_week_ago).
    Застояла SOFR (> FRED_DAILY_MAX_LAG_SESSIONS NYSE сесии — SOFR за D−1 излиза в 08:00 ET на D, т.е. в 07:30 Берлин последната е D−2) или липсващ IORB → hide с причина.
    """
    import statistics as st
    import pandas as pd
    from src.setup_rules import sessions_between
    hide = lambda why: {"value": None, "hide": True, "hide_reason": why}
    if not sofr:
        return hide("FRED не върна SOFR")
    if not iorb:
        return hide("FRED не върна IORB")
    today = today or dt.date.today()
    last_d = dt.date.fromisoformat(sofr[-1][0])
    if sessions_between(last_d, today) > config.FRED_DAILY_MAX_LAG_SESSIONS:
        return hide(f"SOFR застояла — последно наблюдение {last_d.strftime('%d.%m')} (праг {config.FRED_DAILY_MAX_LAG_SESSIONS} сесии)")
    rate = sorted([(d, v) for d, v in ioer if d < config.FUNDING_STRESS_IORB_FROM] + [(d, v) for d, v in iorb if d >= config.FUNDING_STRESS_IORB_FROM])
    if not rate or rate[-1][0] < config.FUNDING_STRESS_IORB_FROM:
        return hide("IORB липсва след 29.07.2021")
    pts, j, cur = [], 0, None
    for d, v in sofr:
        if d < config.FUNDING_STRESS_FROM:
            continue
        while j < len(rate) and rate[j][0] <= d:
            cur = rate[j][1]; j += 1
        if cur is not None:
            pts.append((d, round((v - cur) * 100, 2), v, cur))
    if len(pts) < 260:
        return hide(f"историята е твърде къса ({len(pts)} дни)")
    vals = [p[1] for p in pts]
    last, hist = vals[-1], vals[:-1]
    pct = round(100.0 * sum(1 for x in hist if x <= last) / len(hist), 1)
    sd = st.pstdev(hist)
    z = round((last - st.mean(hist)) / sd, 2) if sd else None
    s = pd.Series(vals, index=pd.to_datetime([p[0] for p in pts]))
    _, week_ago, _ = last_and_week_ago(s)
    status = "red" if pct >= config.FUNDING_STRESS_PCT_RED else "yellow" if pct >= config.FUNDING_STRESS_PCT_YELLOW else "green"
    return {"value": round(last, 1), "as_of": pts[-1][0], "sofr": pts[-1][2], "iorb": pts[-1][3], "percentile": pct, "zscore": z,
            "chg_1w_bp": round(last - week_ago, 1) if week_ago is not None else None, "n_history": len(hist), "history_from": pts[0][0], "status": status, "hide": False,
            "streak": report_streak(vals)}


def report_streak(vals: list[float]) -> dict:
    """
    29.10.2026 (разходката, т. 2, добавка към т. 5): колко поредни отчета (дневни стойности) поред спредът е ПО-ВИСОК (или по-нисък) от предишния — броят завършва с последния.
    {"dir": "up" | "down" | "flat", "n"}; равен на предишния → {"dir": "flat", "n": 0}. Стойностите са закръглени до 0.1 б.п. (SOFR и IORB са с 2 знака). Чиста функция.
    РЕАЛНО (брифовете): към 27.10 — −2, −2, 0, +2, +3, +5 б.п. (20.10 → 27.10) → "up", 4.
    """
    v = [round(float(x), 1) for x in vals or []]
    if len(v) < 2 or v[-1] == v[-2]:
        return {"dir": "flat", "n": 0}
    up = v[-1] > v[-2]
    n = 0
    for a, b in zip(reversed(v[:-1]), reversed(v[1:])):
        if (b > a) if up else (b < a):
            n += 1
        else:
            break
    return {"dir": "up" if up else "down", "n": n}


def funding_stress() -> dict:
    """SOFR, IOER и IORB от FRED (един път, от config.FUNDING_STRESS_FROM) → funding_spread. Graceful: провал → hide с причина."""
    try:
        days = (dt.date.today() - dt.date.fromisoformat(config.FUNDING_STRESS_FROM)).days + 5
        return funding_spread(_fred_series("SOFR", days=days), _fred_series("IOER", days=days), _fred_series("IORB", days=days))
    except Exception as e:
        print(f"[macro] SOFR − IORB: {type(e).__name__}: {e}")
        return {"value": None, "hide": True, "hide_reason": f"грешка ({type(e).__name__})"}


def treasury_spread_2s10s() -> dict:
    """T10Y2Y от FRED — директно спредът в %."""
    obs = _fred_series("T10Y2Y", days=30)
    if not obs:
        return {"value": None, "status": "unknown"}
    # втори преглед (10.10.2026): "седмица назад" по ДАТА (series_utils.last_and_week_ago — котва 7 календарни дни от последното наблюдение), не
    # obs[-6] (пет наблюдения назад — около празници прозорецът ставаше 8–9 дни), + проверка за застояли данни в NYSE сесии (допуск 2 — облигационни празници)
    import pandas as pd
    from src.setup_rules import sessions_between
    try:
        ser = pd.Series([v for _, v in obs], index=pd.to_datetime([d for d, _ in obs]))
        val, prev, last_date = last_and_week_ago(ser)
    except ValueError as e:
        print(f"[macro] 2s10s: {e}")
        return {"value": None, "status": "unknown"}
    if sessions_between(last_date, dt.date.today()) > config.FRED_DAILY_MAX_LAG_SESSIONS:
        print(f"[macro] 2s10s stale — последно наблюдение {last_date}")
        return {"value": None, "status": "unknown", "stale": True, "last_date": last_date.isoformat()}
    # FIX 2026-09-12 (findings log 04-11.09, т.5): "steepening" if val > prev
    # else "flattening" няма tie клон — потвърдено на живо (09.09, 10.09):
    # val == prev буквално (0.41==0.41, 0.40==0.40), но else клонът тихо
    # label-ва точен tie като "flattening", подвеждащо (tie не е
    # "flattening" по никакъв смислен начин — спредът не се е стеснил).
    if val > prev:
        direction = "steepening"
    elif val < prev:
        direction = "flattening"
    else:
        direction = "stable"
    return {
        "value": val,
        "prev_week": prev,
        "as_of": last_date.isoformat(),
        # FIX 2026-10-03 (пакет 2 т.5): седмичната промяна е готова в б.п. — AI-то да не я смята наум
        "change_1w_bp": round((val - prev) * 100, 1),
        "status": "inverted" if val < 0 else "normal",
        "direction": direction,
    }


_MONTHS_BG = ["януари", "февруари", "март", "април", "май", "юни", "юли",
              "август", "септември", "октомври", "ноември", "декември"]


def core_inflation() -> dict:
    """
    FIX 2026-09-27: основна инфлация — Dallas Fed Trimmed Mean PCE (12м, % г/г).
    Информативна: не влиза в броенето на термометъра и не влияе на режима.

    Месечна серия с ~1 месец закъснение → НЕ ползва дневния _is_stale().
    Застояла е, ако от края на отчетния месец са минали повече от
    config.CORE_PCE_STALENESS_DAYS дни (виж config.py коментара).
    При провал/застой → {"value": None}: картата показва "няма данни",
    брифът продължава.
    """
    empty = {"value": None}
    try:
        obs = _fred_series(config.CORE_PCE_SERIES, days=400)
        if not obs:
            print("[macro] core PCE: няма данни от FRED")
            return empty
        last_d = dt.date.fromisoformat(obs[-1][0])
        # край на отчетния месец
        nxt = (last_d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        age = (dt.date.today() - (nxt - dt.timedelta(days=1))).days
        if age > config.CORE_PCE_STALENESS_DAYS:
            print(f"[macro] core PCE stale — последно наблюдение {last_d} "
                  f"({age}д от края на месеца, праг {config.CORE_PCE_STALENESS_DAYS}д)")
            return {**empty, "stale": True, "last_date": last_d.isoformat(),
                    "last_month": _MONTHS_BG[last_d.month - 1], "age_days": age}
        val = obs[-1][1]
        out = {
            "value": round(val, 2),
            "date": last_d.isoformat(),
            "month": _MONTHS_BG[last_d.month - 1],
            "age_days": age,
        }
        # FIX 2026-09-28: посока от средни стойности, не от една точка
        n = config.CORE_PCE_AVG_MONTHS
        if len(obs) >= 2 * n:
            recent, prior = obs[-n:], obs[-2 * n:-n]
            a = sum(v for _, v in recent) / n
            b = sum(v for _, v in prior) / n
            chg = a - b
            month = lambda d: _MONTHS_BG[dt.date.fromisoformat(d).month - 1]
            out.update({
                "avg_recent": round(a, 2),
                "avg_prior": round(b, 2),
                "change_pp": round(chg, 2),
                "recent_span": f"{month(recent[0][0])}–{month(recent[-1][0])}",
                "prior_span": f"{month(prior[0][0])}–{month(prior[-1][0])}",
                "direction": ("up" if chg > config.CORE_PCE_FLAT_PP
                              else "down" if chg < -config.CORE_PCE_FLAT_PP else "flat"),
                "flat_threshold_pp": config.CORE_PCE_FLAT_PP,
            })
        return out
    except Exception as e:
        print(f"[macro] core PCE failed: {e}")
        return empty


def _is_stale(last_ts, threshold_days: int | None = None) -> bool:
    """
    Огледало на thermometer._is_stale (дублирано локално, за да няма
    cross-module coupling). Пази срещу застояли Yahoo/FRED серии — виж
    коментара в thermometer.py за ^MOVE/^VIX9D/^VIX3M инцидента.

    FIX 2026-08-18: опционален threshold_days (по подразбиране config.
    STALENESS_THRESHOLD_DAYS, same поведение както преди) — fed_net_
    liquidity() подава config.FED_LIQUIDITY_STALENESS_DAYS за WALCL/WTREGEN
    (легитимно седмични серии, стандартният 3-дневен праг би ги флагвал
    като "stale" всяка нормална седмица).
    """
    last_date = last_ts.date() if hasattr(last_ts, "date") else last_ts
    if threshold_days is None:
        # С1 (10.10.2026): дневните серии (global signals, RRP) — в NYSE сесии, както thermometer._is_stale
        from src.setup_rules import is_stale_daily
        return is_stale_daily(last_date)
    return (dt.date.today() - last_date).days > threshold_days        # седмичните серии с изричен праг (WALCL/WTREGEN) — календарни дни


# сигналите, които са ДОХОДНОСТИ (ниво в %, промяна в базисни пунктове — не относителен %)
_YIELD_SIGNALS = {"US10Y"}

# 19.10.2026 (етап 2, доп. т. 9): кой фючърсен договор е "=F" символът днес. Yahoo сменя договора сам: CL=F в 07:30 на 16.10 вече беше декемврийският (CLZ26), а Reuters котира
# ноемврийския (CLX26) — на 19.10 брифът показа $97.45 (дек., жива цена в нощната сесия) срещу $101.41 (ноем., затварянето в петък). Месецът и часът на цената се показват до нея.
_MONTH_CODES = {c: i for i, c in enumerate("FGHJKMNQUVXZ", 1)}
_BG_MONTHS = ("ян.", "февр.", "март", "апр.", "май", "юни", "юли", "авг.", "септ.", "окт.", "ноем.", "дек.")


_EN_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def futures_contract(info: dict | None, symbol: str | None = None) -> dict | None:
    """
    yfinance .info на "=F" символ → {"contract": "CLZ26", "contract_month": "дек. 2026"} по underlyingSymbol ("CLZ26.NYM"); иначе None. Чиста функция.
    26.10.2026 (решение по етап 4б, т. 3): без underlyingSymbol (26.10 в 06:20 UTC — и за трите фючърса) — резерв по името на договора (shortName "Crude Oil Dec 26") и корена на
    символа ("CL=F" → "CL"): {"contract": "CLZ26", …, "contract_source": "shortName"}.
    """
    import re
    sym = str((info or {}).get("underlyingSymbol") or "").split(".")[0].upper()
    m = re.fullmatch(r"([A-Z]{1,3})([FGHJKMNQUVXZ])(\d{2})", sym)
    if m:
        month, year = _MONTH_CODES[m.group(2)], 2000 + int(m.group(3))
        return {"contract": sym, "contract_month": f"{_BG_MONTHS[month - 1]} {year}"}
    root = re.fullmatch(r"([A-Z]{1,3})=F", str(symbol or "").upper())
    n = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+'?(\d{2})\s*$", str((info or {}).get("shortName") or ""))
    if root and n:
        month, year = _EN_MONTHS[n.group(1)], 2000 + int(n.group(2))
        code = "FGHJKMNQUVXZ"[month - 1]
        return {"contract": f"{root.group(1)}{code}{year % 100:02d}", "contract_month": f"{_BG_MONTHS[month - 1]} {year}", "contract_source": "shortName"}
    return None


def _price_time(info: dict | None) -> str | None:
    """regularMarketTime (epoch) → ISO UTC — кога е цената (в 07:30 Берлин това е нощната сесия на Globex, не затварянето от вчера)."""
    try:
        return dt.datetime.fromtimestamp(int((info or {})["regularMarketTime"]), tz=dt.timezone.utc).isoformat(timespec="minutes")
    except Exception:
        return None


def global_market_signals() -> dict:
    """
    DXY, VIX, gold, oil, copper, 10Y yield, MOVE — снимка + 5-дневна промяна.
    FIX 2026-07-15: staleness проверка. Преди: термометърът отхвърляше
    застоял ^MOVE (hide=True), а този модул теглеше СЪЩИЯ ^MOVE без
    проверка → AI макро наративът цитираше отхвърлената стойност като
    текуща ("MOVE падна до 69.55") — двоен стандарт за същите данни.

    FIX 2026-08-26: period="10d" + iloc[0] даваше fuzzy "~5 дни" прозорец
    (calendar days, не търговски дни) — same паттърн, вече диагностициран и
    поправен в thermometer.py: vix_level() (FIX 2026-08-02), но никога не
    пренесен тук. Потвърдено на живо 2026-08-26: VIX +6.19% оттук срещу
    -2.5% в thermometer-a за СЪЩИЯ ден в СЪЩИЯ AI промпт — обратен знак, не
    просто разлика в прецизността (VIX whipsaw между двата различни anchor-а
    в рамките на прозореца). Same fix, приложен еднакво за всичките 7
    сигнала тук (не само VIX, всичките споделяха стария паттърн):
    period="1mo" + iloc[-6] — точен 5-търговски-дневен прозорец.

    FIX 2026-10-03 (пакет 2 т.9): и `iloc[-6]` се оказа позиционен (пет БАРА, не пет търговски дни — бар, който
    липсва, го мести) и без NaN проверка → прозорецът вече е по ДАТА (7 календарни дни от последния бар), виж
    series_utils.last_and_week_ago(). Името на полето остава chg_5d_*.
    """
    tickers = {
        "DXY": "DX-Y.NYB", "VIX": "^VIX", "Gold": "GC=F",
        "Oil_WTI": "CL=F", "Copper": "HG=F", "US10Y": "^TNX", "MOVE": "^MOVE",
    }
    out = {}
    for name, symbol in tickers.items():
        try:
            hist = yf.Ticker(symbol).history(period="1mo")
            if len(hist) >= 6:
                if _is_stale(hist.index[-1]):
                    print(f"[macro] {name} stale — последен ред "
                          f"{hist.index[-1].date()}, пропускам")
                    continue
                # FIX 2026-10-03 (пакет 2 т.9): `.iloc[-6]` (пет бара назад) беше позиционно и без NaN проверка —
                # липсващ бар мести прозореца, NaN в последния бар стигаше до AI като "nan". Сега: последният бар
                # на или преди 7 календарни дни назад (като MOVE от 25.09) и ValueError при NaN/липса → сигналът
                # се пропуска с ред в лога (виж series_utils.last_and_week_ago).
                last, wk, _ = last_and_week_ago(hist["Close"])
                if name in _YIELD_SIGNALS:
                    # FIX 2026-10-03 (пакет 2 т.5): доходностите се движат в БАЗИСНИ ПУНКТОВЕ, не в относителен %
                    # (^TNX 5.24 → 5.32 е +8 б.п., а относителното "+1.5%" се чете като 1.5 пункта доходност).
                    # Затова САМО chg_5d_bp, без chg_5d_pct. ^TNX е в % годишна доходност (5.24 = 5.24%).
                    out[name] = {
                        "value": round(last, 2),
                        "chg_5d_bp": round((last - wk) * 100, 1),
                    }
                    continue
                out[name] = {
                    "value": round(last, 2),
                    "chg_5d_pct": round((last / wk - 1) * 100, 2),
                    "bar_date": hist.index[-1].date().isoformat(),
                }
                if symbol.endswith("=F"):                       # 19.10.2026: кой договор и кога е цената — отделно, без да сваля сигнала
                    out[name]["chg_5d_basis"] = "continuous"
                    try:
                        info = yf.Ticker(symbol).info
                        out[name].update(futures_contract(info, symbol) or {})
                        if not out[name].get("contract"):              # 26.10.2026 (етап 4б, т. 7): защо договорът липсва — за реда под макро текста
                            u = (info or {}).get("underlyingSymbol")
                            out[name]["contract_reason"] = (f"непознат underlyingSymbol ({u})" if u else "Yahoo не върна underlyingSymbol")
                        if _price_time(info):
                            out[name]["price_time_utc"] = _price_time(info)
                        # 19.10.2026 (етап 2, т. 4): 5-дневната промяна по СЪЩИЯ договор — "=F" е спойка: на 19.10 CL=F (дек.) срещу CL=F отпреди седмица (ноем.) даде +3.96%,
                        # по декемврийския договор е +4.9%. Без серията на договора — по непрекъснатия символ, изрично отбелязано (chg_5d_basis "continuous").
                        und = str(info.get("underlyingSymbol") or "")
                        if not und and out[name].get("contract_source") == "shortName":     # 26.10.2026: договорът по името — серията му е "<договор>.<борса>"
                            ex = {"CL": "NYM", "GC": "CMX", "HG": "CMX"}.get(symbol.split("=")[0])
                            und = f"{out[name]['contract']}.{ex}" if ex else ""
                        if und:
                            ch = yf.Ticker(und).history(period="1mo")
                            if len(ch) >= 6 and not _is_stale(ch.index[-1]):
                                l2, w2, _ = last_and_week_ago(ch["Close"])
                                out[name].update(chg_5d_pct=round((l2 / w2 - 1) * 100, 2), chg_5d_basis="contract")
                    except Exception as e:
                        out[name].setdefault("contract_reason", f"договорът не се прочете ({type(e).__name__})")
                        print(f"[macro] {name}: договорът не се прочете ({type(e).__name__}: {e}) — 5-дневната промяна е по непрекъснатия символ")
        except Exception as e:
            print(f"[macro] {name} failed: {e}")
    return out


_FUT_LABELS = (("Oil_WTI", "WTI", 2), ("Gold", "злато", 0), ("Copper", "мед", 2))


def futures_quotes_line(global_signals: dict | None) -> str | None:
    """
    19.10.2026: ред от кода под макро текста — фючърсите с договора и часа на цената: "WTI $97.45 — дек. 2026 (CLZ26), цена от 19.10 01:30 ET". Без данни за договора → None.
    26.10.2026 (етап 4б, т. 7): договорът неизвестен днес (на 26.10 в 06:20 UTC .info на Yahoo нямаше underlyingSymbol за CL=F, GC=F и HG=F; следобед — пак имаше), а сигналът е от
    кода от 21.10 насам (chg_5d_basis) → изрично "договорът не е известен днес, промяната е по непрекъснатия символ", не тишина. Стар бриф без chg_5d_basis — без ред, както досега.
    """
    from zoneinfo import ZoneInfo
    parts = []
    for key, label, nd in _FUT_LABELS:
        g = (global_signals or {}).get(key) or {}
        if g.get("value") is None or (not g.get("contract") and not g.get("chg_5d_basis")):
            continue
        t = ""
        if g.get("price_time_utc"):
            try:
                et = dt.datetime.fromisoformat(g["price_time_utc"]).astimezone(ZoneInfo("America/New_York"))
                t = f", цена от {et:%d.%m %H:%M} ET"
            except ValueError:
                t = ""
        v = f"{g['value']:,.{nd}f}".replace(",", " ")                    # хиляди с интервал (българският запис)
        chg = g.get("chg_5d_pct")
        five = ("" if not isinstance(chg, (int, float)) else
                f", {chg:+.1f}% за 5 дни по същия договор" if g.get("chg_5d_basis") == "contract" else
                f", {chg:+.1f}% за 5 дни по непрекъснатия символ (може да смесва договори)")
        if not g.get("contract"):
            parts.append(f"{label} ${v}{t} — договорът не е известен днес, промяната е по непрекъснатия символ"
                         + (f": {chg:+.1f}% за 5 дни" if isinstance(chg, (int, float)) else ""))
            continue
        by_name = ", по името на договора" if g.get("contract_source") == "shortName" else ""        # 26.10.2026: резервът (без underlyingSymbol)
        parts.append(f"{label} ${v} — {g['contract_month']} ({g['contract']}{by_name}){t}{five}")
    return ("Фючърси (Yahoo, договорът, който символът „=F“ дава днес): " + " · ".join(parts) + ".") if parts else None


def collect_macro_layer() -> dict:
    """Пълният Слой 1 пакет — подава се на AI синтеза и термометъра."""
    return {
        "date": dt.date.today().isoformat(),
        "net_liquidity": fed_net_liquidity(),
        "spread_2s10s": treasury_spread_2s10s(),
        "global_signals": global_market_signals(),
        # промптът реже macro JSON-а на 6000 знака — core_inflation е последна преди края
        "core_inflation": core_inflation() if config.ENABLE_CORE_INFLATION else None,
        "funding_stress": funding_stress() if config.ENABLE_FUNDING_STRESS else None,     # 16.10.2026: след core_inflation — в термометъра е целият (промптът реже macro на 6000 знака)
        # 2026-10-03 (пакет 2 т.4): NewsAPI е махнат (macro.headlines беше празен във всичките 78 брифа);
        # новините са curated (news_aggregator.significant_news) и влизат в макро промпта отделно, ПРЕДИ брифа.
    }


if __name__ == "__main__":
    import json
    print(json.dumps(collect_macro_layer(), indent=2, ensure_ascii=False, default=str))


# ══════════════════════════════════════════════════════════════════════════
# v2 НАДСТРОЙКА · Секция 5 — Thesis Monitor
# Проверява дали текущите макро условия активират тематичните кошници от
# config.THESIS_BASKETS и обяснява верижната логика. Additive — не пипа
# съществуващите функции по-горе.
# ══════════════════════════════════════════════════════════════════════════
def _trigger_fires(trigger: str | None, macro: dict) -> tuple[bool, str]:
    """Връща (активиран ли е тригерът, кратко обяснение защо)."""
    if trigger is None:
        return False, ""
    g = macro.get("global_signals", {})
    oil = (g.get("Oil_WTI") or {}).get("chg_5d_pct")
    gold = (g.get("Gold") or {}).get("chg_5d_pct")
    vix = (g.get("VIX") or {}).get("value")
    spread = macro.get("spread_2s10s", {})

    if trigger == "oil_shock":
        if oil is not None and oil >= 5:
            return True, f"Петролът (WTI) +{oil:.1f}% за 5 дни — енергиен шок в развитие."
        return False, ""
    if trigger == "geopolitical_stress":
        if vix is not None and vix >= 25 and (gold or 0) > 0:
            return True, f"VIX {vix:.0f} + злато нагоре ({gold:+.1f}%) — бягство към сигурност."
        return False, ""
    if trigger == "curve_steepening":
        if spread.get("direction") == "steepening":
            return True, f"2s10s спредът се разкривява ({spread.get('value')}%)."
        return False, ""
    return False, ""


def thesis_review(b: dict, today: dt.date | None = None) -> dict:
    """21.10.2026 (етап 4): {"reviewed", "review_by", "overdue", "overdue_text"} — срокът е "review_by" или "reviewed" + THESIS_REVIEW_DAYS; без дата → без етикет. Чиста функция."""
    try:
        rev = b.get("reviewed")
        if not rev:
            return {"reviewed": None, "review_by": None, "overdue": False, "overdue_text": None}
        by = b.get("review_by") or (dt.date.fromisoformat(rev) + dt.timedelta(days=config.THESIS_REVIEW_DAYS)).isoformat()
        overdue = (today or dt.date.today()).isoformat() > by
        return {"reviewed": rev, "review_by": by, "overdue": overdue,
                "overdue_text": f"остаряла, не е преглеждана от {rev[8:10]}.{rev[5:7]}.{rev[:4]}" if overdue else None}
    except (ValueError, TypeError):
        return {"reviewed": b.get("reviewed"), "review_by": None, "overdue": False, "overdue_text": None}


def thesis_monitor(macro: dict, today: dt.date | None = None) -> list[dict]:
    """
    Връща списък активни/структурни/наблюдавани тези с обяснение на веригата.
    Подава се на секторния бриф и dashboard-а (нов раздел). 21.10.2026: + датите на прегледа (thesis_review).
    """
    out = []
    for b in config.THESIS_BASKETS:
        status = b.get("default_status", "watch")
        fired, why = _trigger_fires(b.get("trigger"), macro)
        if fired:
            status = "active"
        out.append({
            "name": b["name"],
            "tickers": b["tickers"],
            "status": status,          # active | structural | watch
            "chain": b["chain"],
            "trigger_reason": why,
            **thesis_review(b, today),
        })
    # активните най-отгоре, после структурните, после наблюдаваните
    order = {"active": 0, "structural": 1, "watch": 2}
    out.sort(key=lambda t: order.get(t["status"], 3))
    return out
