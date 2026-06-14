"""
Unusual Options Volume.

PRIMARY: Tradier API (безплатен tier на tradier.com, ключ през env TRADIER_API_KEY).
Tradier няма готов „unusual" репорт, затова го изчисляваме честно: за универс от
ликвидни тикъри (config.UNUSUAL_OPTIONS_UNIVERSE) дърпаме веригата за най-близкия
expiration и смятаме общ опционен обем спрямо open interest. Когато дневният обем е
голям спрямо стоящия OI (vol/OI ≥ праг), това е свежо позициониране = „необичайно".
Call-heavy → bullish наклон; put-heavy → внимание/хедж.

FALLBACK: Market Chameleon (marketchameleon.com/Reports/UnusualOptionVolumeReport)
scrape през pandas.read_html — ако Tradier ключ липсва или API падне.

Употреба:
  • маркер 'UOV✓' за тикър, който е и в нашия CANSLIM скринер;
  • отделен dashboard раздел „Unusual Options Yesterday" (данните отразяват
    приключилата вчерашна сесия, тъй като брифът се прави преди US open).

Имената на колоните/полетата се парсват устойчиво; при провал → празен списък
(graceful degradation), системата продължава без секцията.
"""
from __future__ import annotations
import datetime as dt
import io
import json
import re
import requests
import pandas as pd

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_MC_URL = "https://marketchameleon.com/Reports/UnusualOptionVolumeReport"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
       "Accept": "text/html,application/xhtml+xml"}
_CACHE = config.DATA_DIR / "unusual_options_cache.json"


# ──────────────────────────────────────────────────────────────────────────
# Bias помощник
# ──────────────────────────────────────────────────────────────────────────
def _bias(call_vol: float, put_vol: float) -> tuple[str, str]:
    if call_vol > put_vol * 1.5:
        return "calls", "Обемът е предимно в кол опции — bullish наклон."
    if put_vol > call_vol * 1.5:
        return "puts", "Обемът е предимно в пут опции — внимание/хедж."
    return "mixed", "Балансиран call/put обем."


# ──────────────────────────────────────────────────────────────────────────
# PRIMARY · Tradier
# ──────────────────────────────────────────────────────────────────────────
def _tradier_get(path: str, params: dict) -> dict | None:
    try:
        r = requests.get(f"{config.TRADIER_BASE}{path}", params=params, timeout=15,
                         headers={"Authorization": f"Bearer {config.TRADIER_API_KEY}",
                                  "Accept": "application/json"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[unusual_options] Tradier {path}: {e}")
        return None


def _nearest_expiration(sym: str) -> str | None:
    data = _tradier_get("/markets/options/expirations", {"symbol": sym})
    try:
        dates = (data or {}).get("expirations", {}).get("date")
        if isinstance(dates, str):
            dates = [dates]
        return sorted(dates)[0] if dates else None
    except Exception:
        return None


def _fetch_tradier(limit: int) -> list[dict]:
    if not config.TRADIER_API_KEY:
        return []
    rows = []
    for sym in config.UNUSUAL_OPTIONS_UNIVERSE:
        exp = _nearest_expiration(sym)
        if not exp:
            continue
        data = _tradier_get("/markets/options/chains",
                            {"symbol": sym, "expiration": exp, "greeks": "false"})
        try:
            options = (data or {}).get("options", {}).get("option")
            if not options:
                continue
            if isinstance(options, dict):
                options = [options]
            call_vol = put_vol = total_oi = 0
            for o in options:
                vol = o.get("volume") or 0
                oi = o.get("open_interest") or 0
                total_oi += oi
                if o.get("option_type") == "call":
                    call_vol += vol
                else:
                    put_vol += vol
            total_vol = call_vol + put_vol
            if total_vol <= 0:
                continue
            ratio = total_vol / max(total_oi, 1)
            if ratio < config.UNUSUAL_OPTIONS_MIN_RATIO:
                continue
            bias, note = _bias(call_vol, put_vol)
            rows.append({"ticker": sym, "call_put_bias": bias,
                         "note": f"{note} Обем {total_vol:,} ≈ {ratio:.1f}× OI.",
                         "_ratio": round(ratio, 2)})
        except Exception as e:
            print(f"[unusual_options] Tradier parse {sym}: {e}")
            continue
    rows.sort(key=lambda r: r.get("_ratio", 0), reverse=True)
    for r in rows:
        r.pop("_ratio", None)
    return rows[:limit]


# ──────────────────────────────────────────────────────────────────────────
# FALLBACK · Market Chameleon scrape
# ──────────────────────────────────────────────────────────────────────────
def _fetch_marketchameleon(limit: int) -> list[dict]:
    rows: list[dict] = []
    try:
        html = requests.get(_MC_URL, timeout=20, headers=_UA).text
        for tbl in pd.read_html(io.StringIO(html)):
            cols = [str(c).lower() for c in tbl.columns]
            sym_col = next((tbl.columns[i] for i, c in enumerate(cols)
                            if "symbol" in c or "ticker" in c), None)
            if sym_col is None:
                continue
            call_col = next((tbl.columns[i] for i, c in enumerate(cols)
                             if "call" in c and "vol" in c), None)
            put_col = next((tbl.columns[i] for i, c in enumerate(cols)
                            if "put" in c and "vol" in c), None)
            for _, r in tbl.iterrows():
                sym = re.sub(r"[^A-Z\.\-]", "", str(r[sym_col]).upper())
                if not sym or len(sym) > 6:
                    continue
                bias, note = None, "Необичаен опционен обем."
                if call_col is not None and put_col is not None:
                    try:
                        cv = float(str(r[call_col]).replace(",", ""))
                        pv = float(str(r[put_col]).replace(",", ""))
                        bias, note = _bias(cv, pv)
                    except Exception:
                        pass
                rows.append({"ticker": sym, "call_put_bias": bias, "note": note})
            break
    except Exception as e:
        print(f"[unusual_options] Market Chameleon failed: {e}")
        return []
    return rows[:limit]


# ──────────────────────────────────────────────────────────────────────────
# Публично API · Tradier primary → Market Chameleon fallback
# ──────────────────────────────────────────────────────────────────────────
def fetch_unusual_options(limit: int = 25) -> list[dict]:
    """
    Връща [{ticker, call_put_bias, note}] подреден по необичайност. Кешира за деня.
    """
    today = dt.date.today().isoformat()
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if cached.get("date") == today:
                return cached.get("rows", [])[:limit]
        except Exception:
            pass

    rows = _fetch_tradier(limit)
    source = "tradier"
    if not rows:
        rows = _fetch_marketchameleon(limit)
        source = "marketchameleon"

    # дедупликация, запазвайки реда
    seen, dedup = set(), []
    for r in rows:
        if r["ticker"] not in seen:
            seen.add(r["ticker"])
            dedup.append(r)

    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _CACHE.write_text(json.dumps({"date": today, "source": source, "rows": dedup},
                                     ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[unusual_options] cache write: {e}")

    return dedup[:limit]


def unusual_set(rows: list[dict] | None = None) -> dict[str, dict]:
    """Речник ticker → ред, за бърза проверка в enrich."""
    rows = rows if rows is not None else fetch_unusual_options()
    return {r["ticker"]: r for r in rows}


if __name__ == "__main__":
    res = fetch_unusual_options()
    print(f"Unusual options: {len(res)}")
    for r in res[:15]:
        print(" ", r)
