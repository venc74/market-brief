"""
CUSIP → тикър през OpenFIGI (19.10.2026, етап 2, доп. т. 8 + т. 17а) — за 13F редовете (dataroma).

Защо: 13F носи CUSIP и името на емитента така, както го е подал мениджърът. По име (SEC company_tickers.json) тикърът не се намира за ~22% от новите позиции (19.10: 8 от 36 —
Seagate "SEAGATE TECHNOLOGY HLDNGS PL", Mastercard "MASTERCARD INCORPORATED", Applied Materials "APPLIED MATLS INC", TSMC, On Holding, TJX "TJX COS INC NEW"), а понякога името е
на друг емитент: Oaktree подава PUT на SPY (CUSIP 78462F103) като "STATE STREET CORP" — по име ставаше STT. CUSIP е идентификаторът на ценната книга.

OpenFIGI v3 /mapping (без API ключ: до 10 задачи в заявка, 25 заявки в минута): филтър exchCode=US (американският композитен ред — без него първият запис може да е чужда борса,
QQQ излизаше "NDQ"); кодовете, които започват с буква, са CINS (чуждестранни емитенти: Seagate G7997R103, On Holding H5919C104) → idType ID_CINS (с ID_CUSIP: "No identifier found").
Тикърът на Bloomberg с "/" ("BRK/B") се пише с "-" (BRK-B), както в Yahoo.

Кеш по CUSIP (config.DATA_DIR / config.CUSIP_MAP_CACHE_NAME — пътят се смята при извикване): намереното се опреснява след CUSIP_MAP_REFRESH_DAYS, ненамереното — след CUSIP_MAP_NOTFOUND_DAYS. Бюджет на run-а CUSIP_MAP_BUDGET_SEC;
каквото не стигне — от кеша / без тикър днес. Провал → {} за липсващите (graceful), LAST_STATUS казва колко.
"""
from __future__ import annotations

import datetime as dt
import json
import time

import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

LAST_STATUS: dict = {}


def jobs(cusips: list[str]) -> list[dict]:
    """Задачите за /mapping: CINS (започва с буква) или CUSIP, само американският композитен ред."""
    return [{"idType": "ID_CINS" if c[:1].isalpha() else "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in cusips]


def parse(cusips: list[str], response: list) -> dict[str, dict | None]:
    """
    Отговорът на /mapping (списък в реда на задачите) → {cusip: {"ticker", "name", "type"} или None (няма съвпадение)}. Чиста функция — тества се върху реален отговор.
    Записът с exchCode "US" е първи избор; тикър с "/" → "-".
    """
    out: dict[str, dict | None] = {}
    for c, item in zip(cusips, response or []):
        data = (item or {}).get("data") if isinstance(item, dict) else None
        if not data:
            out[c] = None
            continue
        e = next((d for d in data if d.get("exchCode") == "US"), data[0])
        t = (e.get("ticker") or "").strip().replace("/", "-")
        out[c] = {"ticker": t, "name": e.get("name") or "", "type": e.get("securityType") or ""} if t else None
    return out


def cache_path() -> pathlib.Path:
    return pathlib.Path(config.DATA_DIR) / config.CUSIP_MAP_CACHE_NAME


def _load_cache() -> dict:
    try:
        return json.loads(cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        cache_path().parent.mkdir(exist_ok=True)
        cache_path().write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    except Exception as e:
        print(f"[cusip] кешът не се записа: {e}")


def _fresh(entry: dict, today: dt.date) -> bool:
    try:
        age = (today - dt.date.fromisoformat(entry.get("date", ""))).days
    except ValueError:
        return False
    return age <= (config.CUSIP_MAP_REFRESH_DAYS if entry.get("ticker") else config.CUSIP_MAP_NOTFOUND_DAYS)


def _post(batch_jobs: list[dict]) -> list:
    r = requests.post(config.CUSIP_MAP_URL, json=batch_jobs, timeout=20, headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def resolve(cusips, *, post=None, today: dt.date | None = None, sleep=time.sleep, clock=time.monotonic) -> dict[str, dict]:
    """
    {cusip: {"ticker", "name", "type"}} за намерените (от кеша или OpenFIGI); ненамерените и неопитаните днес липсват. `post` / `sleep` / `clock` — за тестовете (без мрежа).
    """
    today = today or dt.date.today()
    want = sorted({c.strip().upper() for c in cusips if isinstance(c, str) and len(c.strip()) == 9})
    LAST_STATUS.clear()
    LAST_STATUS.update({"requested": len(want), "from_cache": 0, "fetched": 0, "not_found": 0, "skipped": 0, "error": None})
    if not config.CUSIP_MAP_ENABLED or not want:
        return {}
    cache = _load_cache()
    out: dict[str, dict] = {}
    todo = []
    for c in want:
        e = cache.get(c)
        if isinstance(e, dict) and _fresh(e, today):
            LAST_STATUS["from_cache"] += 1
            if e.get("ticker"):
                out[c] = {k: e[k] for k in ("ticker", "name", "type") if k in e}
        else:
            todo.append(c)
    post = post or _post
    start = clock()
    dirty = False
    for i in range(0, len(todo), config.CUSIP_MAP_BATCH):
        if i and clock() - start + config.CUSIP_MAP_PAUSE_SEC > config.CUSIP_MAP_BUDGET_SEC:
            LAST_STATUS["skipped"] = len(todo) - i
            print(f"[cusip] бюджетът от {config.CUSIP_MAP_BUDGET_SEC}s свърши — {len(todo) - i} CUSIP-а остават за следващия run")
            break
        if i:
            sleep(config.CUSIP_MAP_PAUSE_SEC)                    # без ключ: 25 заявки в минута
        batch = todo[i:i + config.CUSIP_MAP_BATCH]
        try:
            got = parse(batch, post(jobs(batch)))
        except Exception as e:
            LAST_STATUS["error"] = f"{type(e).__name__}: {e}"
            LAST_STATUS["skipped"] = len(todo) - i
            print(f"[cusip] OpenFIGI: {LAST_STATUS['error']} — тикърите по име за останалите {len(todo) - i}")
            break
        for c in batch:
            v = got.get(c)
            cache[c] = {**v, "date": today.isoformat()} if v else {"date": today.isoformat()}
            dirty = True
            if v:
                out[c] = v
                LAST_STATUS["fetched"] += 1
            else:
                LAST_STATUS["not_found"] += 1
    if dirty:
        _save_cache(cache)
    return out
