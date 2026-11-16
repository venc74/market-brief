"""
16.11.2026 (пакет 16.11, т. 13): проверка за ЕМИСИИ НА АКЦИИ в EDGAR за тикърите в картите, книгите и наблюдаваните — като проверката за отделяне / 8-K (spinoff_watch).
Реално: KDP обяви емисия за $2 млрд на 12.11 (−7%), а брифът мълчеше — 424B5 на 12.11 („Preliminary Prospectus Supplement … $2,000,000,000 Common Stock“) и окончателният на 16.11
(„57,971,015 Shares Common Stock“, по $34.50).

Правилата (submissions JSON на EDGAR — същият, който spinoff_watch вече тегли за run-а, общият речник `subs`):
  • 424B1 / 424B3 / 424B4 / 424B5 / 424B7 в последните config.OFFERING_LOOKBACK_DAYS дни → обложката на документа (първите ~200 KB): акции („Common Stock“, „Ordinary Shares“,
    „American Depositary Shares“) → ред „⚠ емисия на акции“; дълг („Notes due“, „Debentures“) → нищо (не разводнява); неясно → ред с „виж документа“.
  • S-1 / S-3 / F-1 / F-3 → по-лек ред „регистрация на ценни книжа (S-3) — може да последва емисия“.
  • 424B2 (структурирани бележки на банките — десетки на ден) и S-3ASR (рутинната автоматична регистрация на големите, на 3 години) — пропускат се.
Мрежа: spinoff_watch._http_get (config.EDGAR_UA); кеш по документ (data/offering_cache.json). Graceful: провал → LAST_DIAG ok False и редът за проверката в брифа.
"""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import pathlib
import re

import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

PROSPECTUS = ("424B1", "424B3", "424B4", "424B5", "424B7")
REGISTRATION = ("S-1", "S-3", "F-1", "F-3", "S-1/A", "S-3/A", "F-1/A", "F-3/A")
_EQUITY = re.compile(r"\bcommon stock\b|\bordinary shares\b|\bamerican depositary shares\b|\bclass [a-c] (?:common )?shares\b", re.I)
_DEBT = re.compile(r"\bnotes due\b|\bsenior notes\b|\bdebentures\b|\bsubordinated notes\b|% notes\b", re.I)
_TITLE = re.compile(r"((?:\$\s?[\d,]{5,}(?:\.\d+)?|[\d,]{5,}\s+Shares)\s+(?:of\s+)?(?:Class [A-C]\s+)?(?:Common Stock|Ordinary Shares|American Depositary Shares))", re.I)
LAST_DIAG: dict = {}


def _dm(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


def recent_filings(sub: dict, since: str, until: str) -> list[dict]:
    """Подаванията от prospectus / регистрация в прозореца [since, until] → [{form, date, acc, doc}], най-новите първи. Чиста функция върху submissions JSON."""
    r = (sub or {}).get("filings", {}).get("recent", {})
    out = []
    for i, f in enumerate(r.get("form", [])):
        if f not in PROSPECTUS and f not in REGISTRATION:
            continue
        d = r["filingDate"][i]
        if since <= d <= until:
            out.append({"form": f, "date": d, "acc": r["accessionNumber"][i], "doc": (r.get("primaryDocument") or [""] * len(r["form"]))[i]})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def cover_text(html_text: str, n: int = 4000) -> str:
    """Началото на документа като текст (обложката) — без тагове и HTML ентитита. Чиста функция."""
    t = re.sub(r"<[^>]+>", " ", html_text or "")
    t = _html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()[:n]


def classify(cover: str) -> dict:
    """Обложката → {"kind": "акции" | "дълг" | "неясно", "title" (дословно, ако се чете), "preliminary"}. Акциите — преди дълга (обложка с двете е за акции + бележки). Чиста функция."""
    eq, debt = _EQUITY.search(cover or ""), _DEBT.search(cover or "")
    kind = "акции" if eq and (not debt or eq.start() < debt.start()) else ("дълг" if debt else "неясно")
    m = _TITLE.search(cover or "")
    return {"kind": kind, "title": re.sub(r"\s+", " ", m.group(1)).strip() if m else None, "preliminary": bool(re.search(r"preliminary prospectus supplement|subject to completion", cover or "", re.I))}


def line(hits: list[dict]) -> str | None:
    """Редът за картата / реда в книгата: „⚠ емисия на акции — 424B5 от 16.11: „57,971,015 Shares Common Stock“ (и предварителен от 12.11)“. Чиста функция."""
    eq = [h for h in hits if h.get("kind") == "акции"]
    unk = [h for h in hits if h.get("kind") == "неясно"]
    reg = [h for h in hits if h.get("kind") == "регистрация"]
    if eq:
        h = eq[0]
        t = f"⚠ емисия на акции — {h['form']} от {_dm(h['date'])}" + (" (предварителен)" if h.get("preliminary") else "") + (f": „{h['title']}“" if h.get("title") else "")
        more = [x for x in eq[1:]]
        if more:
            t += " · и " + ", ".join(f"{x['form']} от {_dm(x['date'])}" + (" (предварителен)" if x.get("preliminary") else "") for x in more)
        return t
    if unk:
        h = unk[0]
        return f"⚠ проспект за ценни книжа — {h['form']} от {_dm(h['date'])}: видът не се чете от обложката (виж документа в EDGAR)"
    if reg:
        h = reg[0]
        return f"регистрация на ценни книжа — {h['form']} от {_dm(h['date'])} (може да последва емисия)"
    return None


def check(tickers, today=None, get=None, cik_map=None, subs: dict | None = None) -> dict[str, dict]:
    """
    {тикър: {"text", "hits": [...]}} за тикърите с емисия / регистрация в прозореца. get(url) → текст и cik_map {тикър: CIK} — подменят се в тестовете; subs — речникът
    {url: submissions JSON} на run-а (споделен със spinoff_watch). Кеш по документ (data/offering_cache.json). Не вдига: провал → {} и LAST_DIAG ok False.
    """
    LAST_DIAG.clear()
    LAST_DIAG.update(ok=True, requested=0, checked=0, fetched=0, errors=[], unchecked=[], hits=[])
    today = today if isinstance(today, dt.date) else dt.date.fromisoformat(str(today or dt.date.today())[:10])
    tickers = list(dict.fromkeys(t for t in (tickers or []) if t))
    LAST_DIAG["requested"] = len(tickers)
    if not tickers or not config.ENABLE_OFFERING_WATCH:
        return {}
    try:
        from src import spinoff_watch
        get = get or spinoff_watch._http_get
        if cik_map is None:
            from src import insider_buying
            cik_map = insider_buying._ticker_cik_map()
        cache_p = pathlib.Path(config.DATA_DIR) / config.OFFERING_CACHE_NAME
        try:
            cache = json.loads(cache_p.read_text(encoding="utf-8"))
        except Exception:
            cache = {"version": 1, "docs": {}}
        since = (today - dt.timedelta(days=config.OFFERING_LOOKBACK_DAYS)).isoformat()
        out: dict[str, dict] = {}
        for t in tickers:
            cik = (cik_map or {}).get(t)
            if not cik:
                LAST_DIAG["unchecked"].append(t)
                continue
            LAST_DIAG["checked"] += 1
            url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
            try:
                sub = subs[url] if subs is not None and url in subs else json.loads(get(url))
                if subs is not None:
                    subs[url] = sub
            except Exception as e:
                LAST_DIAG["errors"].append({"ticker": t, "error": f"submissions: {type(e).__name__}"})
                continue
            hits = []
            for f in recent_filings(sub, since, today.isoformat()):
                if f["form"] in REGISTRATION:
                    hits.append({**f, "kind": "регистрация"})
                    continue
                c = cache["docs"].get(f["acc"])
                if c is None:
                    try:
                        doc = get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['acc'].replace('-', '')}/{f['doc']}")
                        c = cache["docs"][f["acc"]] = {"ticker": t, "date": f["date"], **classify(cover_text(doc))}
                        LAST_DIAG["fetched"] += 1
                    except Exception as e:
                        LAST_DIAG["errors"].append({"ticker": t, "accession": f["acc"], "error": type(e).__name__})
                        c = {"kind": "неясно", "title": None, "preliminary": False}
                if c.get("kind") != "дълг":
                    hits.append({**f, **{k: c.get(k) for k in ("kind", "title", "preliminary")}})
            text = line(hits)
            if text:
                out[t] = {"text": text, "hits": hits}
                LAST_DIAG["hits"].append({"ticker": t, "text": text})
        cache["docs"] = {k: v for k, v in cache["docs"].items() if v.get("date", "") >= since}
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        if LAST_DIAG["errors"] and not LAST_DIAG["checked"] - len(LAST_DIAG["errors"]):
            LAST_DIAG.update(ok=False, error="EDGAR не върна нито един списък с подавания")
        for t, h in out.items():
            print(f"[offering] {t}: {h['text']}")
        return out
    except Exception as e:
        LAST_DIAG.update(ok=False, error=f"{type(e).__name__}: {e}")
        print(f"[offering] проверката пропусната: {LAST_DIAG['error']}")
        return {}


def annotate(groups, found: dict[str, dict]) -> int:
    """row["offering_warning"] = текстът — върху картите, редовете на книгите и наблюдаваните; връща броя."""
    n = 0
    for g in groups or []:
        for c in g or []:
            h = found.get(c.get("ticker")) if isinstance(c, dict) else None
            if h:
                c["offering_warning"] = h["text"]
                n += 1
    return n
