"""
Пазарен термометър (Секция 4).
Осем индикатора + обща препоръка Offensive / Defensive / Cash.
Всеки индикатор връща {value, status, label} където status ∈ green/yellow/red.
"""
from __future__ import annotations
import datetime as dt
import io
import math
import os
from functools import lru_cache
import requests
import yfinance as yf

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


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
    try:
        hist = yf.Ticker("^VIX").history(period="10d")
        if hist.empty:
            raise ValueError("empty VIX history")
        vix = float(hist["Close"].iloc[-1])
        wk = float(hist["Close"].iloc[0])
        if math.isnan(vix):
            raise ValueError("NaN VIX — невалидни данни от източника")
    except Exception as e:
        print(f"[thermo] VIX failed: {e}")
        return {"name": "VIX", "value": None, "status": "yellow",
                "hide": True, "label": ""}
    if vix < config.VIX_RISK_ON:
        status = "green"
    elif vix < config.VIX_RISK_OFF:
        status = "yellow"
    else:
        status = "red"
    return {
        "name": "VIX", "value": round(vix, 2), "chg_5d": round(vix - wk, 2),
        "status": status,
        "label": f"VIX {vix:.1f} ({'risk-on' if status == 'green' else 'risk-off' if status == 'red' else 'неутрално'})",
    }


# ── NAAIM източници (приоритет: Nasdaq Data Link [API key] → naaim.org scrape) ──
# naaim.org CSV (USE_Data_since_Inception.csv) е премахнат — върна 404 (файлът е
# изтрит/преместен). Останаха два източника: оторизиран Nasdaq endpoint и scrape.
NAAIM_NASDAQ_URL = "https://data.nasdaq.com/api/v3/datasets/NAAIM/NAAIM.json"
NAAIM_PAGE_URL = "https://naaim.org/programs/naaim-exposure-index/"
_NAAIM_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _parse_date_safe(s: str):
    """Връща (sort_key, оригинален_низ). sort_key=ISO низ ако се разпознае, иначе None."""
    s = (s or "").strip()
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d.%m.%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d"), s
        except ValueError:
            continue
    return None, s


def _naaim_from_nasdaq() -> list[dict]:
    """
    Primary: Nasdaq Data Link (Quandl) — изисква API ключ (anonymous достъп е спрян,
    връща 403). Ключът идва от env var NASDAQ_API_KEY и се подава като query параметър.
    Ако ключът липсва → чист skip (връщаме [] без да правим заявка), за да паднем
    тихо към следващия източник, вместо да генерираме 403 грешка.
    Структура: dataset.column_names + dataset.data (newest-first по подразбиране).
    Нормализираме до хронологичен ascending списък [{date, value}].
    """
    api_key = os.getenv("NASDAQ_API_KEY")
    if not api_key:
        print("[thermo] NAAIM: NASDAQ_API_KEY липсва — пропускам Nasdaq source")
        return []
    r = requests.get(NAAIM_NASDAQ_URL, timeout=20, headers=_NAAIM_HEADERS,
                     params={"api_key": api_key})
    r.raise_for_status()
    ds = r.json().get("dataset", {})
    cols = [str(c).lower() for c in ds.get("column_names", [])]
    data = ds.get("data", [])
    val_idx = next((i for i, c in enumerate(cols)
                    if any(k in c for k in ("mean", "average", "naaim number"))), 1)
    pts = []
    for row in data:
        if not row or len(row) <= val_idx:
            continue
        try:
            val = float(row[val_idx])
        except (TypeError, ValueError):
            continue
        sort_key, raw = _parse_date_safe(str(row[0]))
        pts.append({"date": sort_key or raw, "value": round(val, 1), "_k": sort_key or raw})
    pts.sort(key=lambda p: p["_k"])
    for p in pts:
        p.pop("_k", None)
    return pts


def _looks_like_date(s) -> bool:
    """Бърза проверка дали низ прилича на дата (за JSON евристиката)."""
    if not isinstance(s, str):
        return False
    return _parse_date_safe(s)[0] is not None


def _points_from_json_obj(obj, out: list[dict]) -> None:
    """
    Рекурсивно обхожда произволна JSON структура и събира двойки (дата, число)
    които приличат на времева серия. Покрива честите chart формати:
      • [{"date": "...", "value": N}, ...]  (Chart.js / WP плъгини)
      • [{"x": "...", "y": N}, ...]         (Highcharts/plotly)
      • [["YYYY-MM-DD", N], ...]            (двойки)
    Стойностите се ограничават до [-250, 250] (NAAIM е приблизително [-200, 200]).
    """
    if isinstance(obj, dict):
        date_val = next((obj[k] for k in ("date", "Date", "x", "t", "time", "label")
                         if k in obj and _looks_like_date(obj.get(k))), None)
        if date_val is not None:
            num = next((obj[k] for k in ("value", "y", "mean", "naaim", "close", "v")
                        if isinstance(obj.get(k), (int, float))), None)
            if num is not None and -250 <= num <= 250:
                _, raw = _parse_date_safe(date_val)
                out.append({"date": raw, "value": round(float(num), 1),
                            "_k": _parse_date_safe(date_val)[0]})
        for v in obj.values():
            _points_from_json_obj(v, out)
    elif isinstance(obj, list):
        if (len(obj) == 2 and _looks_like_date(obj[0])
                and isinstance(obj[1], (int, float)) and -250 <= obj[1] <= 250):
            _, raw = _parse_date_safe(obj[0])
            out.append({"date": raw, "value": round(float(obj[1]), 1),
                        "_k": _parse_date_safe(obj[0])[0]})
        for v in obj:
            _points_from_json_obj(v, out)


def _naaim_from_scrape() -> list[dict]:
    """
    Fallback: scrape на programs страницата. Първо опитва HTML таблици; ако страницата
    е JS-rendered SPA (без таблици / почти празно body), търси вграден JSON в
    <script type="application/json"> (и подобни inline script блокове) като
    алтернативен начин за извличане. Best-effort, подреждаме ascending по дата.
    """
    from bs4 import BeautifulSoup
    r = requests.get(NAAIM_PAGE_URL, timeout=20, headers=_NAAIM_HEADERS)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    pts = []
    tables = soup.find_all("table")
    for table in tables:
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            sort_key, raw = _parse_date_safe(cells[0])
            if sort_key is None:
                continue
            for c in cells[1:]:
                try:
                    val = float(c.replace("%", "").replace(",", "").strip())
                except ValueError:
                    continue
                if -250 <= val <= 250:
                    pts.append({"date": raw, "value": round(val, 1), "_k": sort_key})
                    break

    if not pts:
        import json as _json
        scripts = soup.find_all("script")
        body_text = soup.get_text(" ", strip=True)
        is_spa = (not tables) or (len(body_text) < 600 and len(scripts) > 3)
        if is_spa or scripts:
            for sc in scripts:
                stype = (sc.get("type") or "").lower()
                blob = sc.string or sc.get_text() or ""
                blob = blob.strip()
                if not blob:
                    continue
                candidates = []
                if "json" in stype:
                    candidates.append(blob)
                else:
                    for opener, closer in (("[", "]"), ("{", "}")):
                        i, j = blob.find(opener), blob.rfind(closer)
                        if 0 <= i < j:
                            candidates.append(blob[i:j + 1])
                for cand in candidates:
                    try:
                        data = _json.loads(cand)
                    except (ValueError, TypeError):
                        continue
                    _points_from_json_obj(data, pts)
                if pts:
                    break

    seen, uniq = set(), []
    for p in pts:
        key = (p["date"], p["value"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    uniq.sort(key=lambda p: p.get("_k") or p["date"])
    for p in uniq:
        p.pop("_k", None)
    return uniq


@lru_cache(maxsize=1)
def _naaim_series() -> tuple:
    """
    Връща хронологичен ascending кортеж точки от първия успял източник.
    Кешира се за процеса (lru_cache) → exposure + history теглят мрежата веднъж.
    При пълен провал на трите → празен кортеж (→ graceful hide нагоре по веригата).
    Връща tuple (immutable), за да е hashable/безопасен за кеширане; консумерите
    го третират като последователност (slice/индексиране работят непроменено).
    """
    for name, fn in (("nasdaq", _naaim_from_nasdaq),
                     ("naaim.org scrape", _naaim_from_scrape)):
        try:
            pts = fn()
            if pts:
                return tuple(pts)
            print(f"[thermo] NAAIM source '{name}' върна 0 точки — пробвам следващия")
        except Exception as e:
            print(f"[thermo] NAAIM source '{name}' failed: {e}")
    return ()


def naaim_exposure() -> dict:
    """
    NAAIM Exposure Index — седмичен барометър на експозицията на активните мениджъри.
    <30 = дефанзивни (contrarian bullish при дъна), >90 = еуфория (предупреждение).
    Източници по приоритет: Nasdaq Data Link (API ключ) → naaim.org scrape.
    При провал и на трите картичката се скрива gracefully (hide=True), вместо
    да показва "няма данни" текст.
    """
    pts = _naaim_series()
    if not pts:
        return {"name": "NAAIM", "value": None, "status": "yellow",
                "hide": True, "label": ""}
    last = pts[-1]
    val, date = last["value"], last["date"]
    status = "yellow"
    if val > 90: status = "red"
    elif val < 30: status = "green"
    return {"name": "NAAIM", "value": val, "as_of": date, "status": status,
            "label": f"NAAIM {val:.0f}"}


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


def build_thermometer(macro: dict) -> dict:
    """
    Сглобява 8-те индикатора + правилото за режим:
    - VIX > 30 → задължително Defensive (Секция 8)
    - MOVE > 150 или рязък седмичен скок → задължително Defensive (институционален
      стрес в колатералната система бие останалите сигнали, аналогично на VIX правилото)
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

    indicators = [spy_trend(), vix_level(), naaim_exposure(),
                  market_put_call(), spread_ind, nl_ind, move_index(),
                  vix_term_structure()]

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


# ══════════════════════════════════════════════════════════════════════════
# v2 НАДСТРОЙКА · Секция 6 — NAAIM исторически прозорец (52 седмици)
# naaim_exposure() по-горе чете само последната стойност. Тук връщаме цялата
# поредица за chart в dashboard-а, с маркери за зоните <30 (дъно) и >90 (опасно).
# Additive — съществуващите функции не са пипани.
# ══════════════════════════════════════════════════════════════════════════
def naaim_history(weeks: int | None = None) -> dict:
    """
    Връща {points: [{date, value}], low_zone: 30, high_zone: 90, current}.
    Контрарианска логика: <30 = buy zone, >90 = caution. Празно при провал.
    Ползва същия многоизточников fetcher като naaim_exposure() (Nasdaq Data Link
    → naaim.org CSV → scrape), затова e достатъчно да поправим source-а на едно място.
    """
    weeks = weeks or config.NAAIM_HISTORY_WEEKS
    out = {"points": [], "low_zone": 30, "high_zone": 90, "current": None}
    pts = _naaim_series()
    if pts:
        out["points"] = pts[-weeks:]
        out["current"] = out["points"][-1]["value"]
    return out
