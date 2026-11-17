"""
17.11.2026 (пакет 1, т. 2г): картата на SEC „нормализирано име на компания → тикър“ (company_tickers.json, кеш месечно в data/sec_tickers.json) — преместена
дословно от src/dataroma.py, когато 13F модулът беше махнат. Ползва я етикетът „купувач в сделка“ (spinoff_watch.buyer_ticker); имената на наблюдаваните
тикъри са в data/watch_list.json и не зависят от нея. Мрежа: config.EDGAR_UA; провал → {} (graceful).
"""
from __future__ import annotations
import datetime as dt
import json
import re
import sys, pathlib

import requests

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_EDGAR_UA = {"User-Agent": config.EDGAR_UA, "Accept-Encoding": "gzip, deflate"}
_TMAP_CACHE = config.DATA_DIR / "sec_tickers.json"


def norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", "", str(name).lower())
    for w in (" inc", " corp", " corporation", " co", " ltd", " plc", " the",
              " class a", " class b", " holdings", " group", " company"):
        # word-boundary anchor (\s|$) — без него " corp" изяжда префикса на
        # " corporation" (naive substring replace: "chevron corporation" →
        # "chevronoration" вместо "chevron")
        s = re.sub(re.escape(w) + r"(?=\s|$)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def ticker_map() -> dict[str, str]:
    """SEC company_tickers.json → {нормализирано име: тикър}. Кеш месечно."""
    if _TMAP_CACHE.exists():
        try:
            c = json.loads(_TMAP_CACHE.read_text())
            if c.get("month") == dt.date.today().isoformat()[:7]:
                return c["map"]
        except Exception:
            pass
    out = {}
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         timeout=20, headers=_EDGAR_UA)
        r.raise_for_status()
        for v in (r.json() or {}).values():
            t = (v.get("ticker") or "").upper()
            title = v.get("title") or ""
            if t and title:
                key = norm(title)
                # един емитент може да има няколко тикъра (common + preferred
                # класове) със СЪЩОТО SEC заглавие (напр. BAC/BAC-PK/BAC-PL/
                # BAC-PS всички = "BANK OF AMERICA CORP /DE/") — предпочитаме
                # "чист" тикър без "-" (обикновено common stock) пред preferred,
                # независимо от реда в SEC JSON-а
                if key not in out or ("-" in out[key] and "-" not in t):
                    out[key] = t
        config.DATA_DIR.mkdir(exist_ok=True)
        _TMAP_CACHE.write_text(json.dumps({"month": dt.date.today().isoformat()[:7],
                                           "map": out}, ensure_ascii=False, default=str))
    except Exception as e:
        print(f"[edgar] ticker map: {e}")
    return out
