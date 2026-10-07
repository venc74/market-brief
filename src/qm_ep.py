"""
Qullamaggie Episodic Pivot (EP) — САМО НАБЛЮДЕНИЕ в сутрешния бриф (06.10.2026): гаповете нагоре СЛЕД затваряне (after-hours) ≥ 10% за тикъри от универса, при "пренебрегване"
(ръст ≤ 20% за предходните ~3 месеца) и с лимит на стопа ≤ 1×ADR като информация. Без Track Record (EP се печели в деня на гапа — виж DESIGN.md на проучването: входът по
отварянето +4.0%/сделка, на другия ден +0.7%/−0.1%); без AI решение — AI само класифицира катализатора от заглавията, а всяко число в прозата се проверява от кода.

Първоизточници на правилата (qullamaggie.com): https://qullamaggie.com/how-to-master-a-setup-episodic-pivots/ (гап ≥ 10%, огромен обем, "пренебрегване" 3–6 месеца, стоп ≤ 1–1.5× ADR) и
https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/ .

Какво е възможно в 07:30 Берлин: Yahoo дава 5-минутни барове с prepost=True — post-market е до 19:55 ET = 01:55 Берлин, premarket започва в 10:00 Берлин. Т.е. виждат се after-hours реакциите
на отчети СЛЕД затваряне (AMC), но не premarket-ът на отчетите ПРЕДИ отваряне. After-hours ОБЕМЪТ в Yahoo е нула в повечето бар-ове (измерено: 43% от тикър-сесиите имат обем > 0), затова
"огромният обем" не може да се провери — картата го казва. Дневникът (data/ep_ah_log.json) пази after-hours гапа срещу реалния гап на отварянето на следващия ден — за решение след 4–6
седмици дали си струва отделно по-късно пускане.

Чисти функции (extract_ah / scan_after_hours / enrich_gappers / parse_rss / verify_ai_item / лог) + мрежа само във fetch_*. Graceful: всяка стъпка е в try/except и връща частичен резултат.
"""
from __future__ import annotations
import datetime as dt
import json
import re
import statistics
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import setup_rules
from src import trade_levels

try:
    import yfinance as yf
except Exception:                                    # pragma: no cover
    yf = None

NY = "America/New_York"
CATALYSTS = {
    "earnings_guidance": "Отчет / guidance",
    "fda_biotech": "FDA / биотех",
    "contract_partnership": "Договор / партньорство",
    "regulatory_political": "Регулации / политика",
    "sector_move": "Секторен ход",
    "m_and_a": "Придобиване (оферта) — цената се връзва към офертата, не е класически EP",
    "unknown": "Неясен катализатор",
}
SURPRISE = ("yes", "no", "unclear")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
NOTE_BG = ("Само наблюдение (без Track Record): after-hours гап в 01:55 Берлин, не гарантира гап на отварянето; After-hours обемът в Yahoo е нула в повечето бар-ове — "
           "\"огромният обем\" не може да се провери; входът (opening range high) и стопът (low of day) са в сесията.")


# ──────────────────────────────────────────────────────────────────────────
# After-hours гап от 5-минутни барове
# ──────────────────────────────────────────────────────────────────────────
def extract_ah(df: pd.DataFrame) -> dict | None:
    """
    За ЕДИН тикър (5-минутни барове с prepost, индекс с часова зона): най-новата сесия, която има и редовни, и post-market (≥ 16:00 ET) барове. Връща {session, prev_close (последният
    редовен бар), ah_price (последният post-market бар), ah_high, ah_low, ah_bars, ah_volume, ah_last_et} или None.
    """
    if df is None or df.empty:
        return None
    ix = df.index.tz_convert(NY) if df.index.tz is not None else df.index.tz_localize("UTC").tz_convert(NY)
    mins = ix.hour * 60 + ix.minute
    for d in sorted(set(ix.date), reverse=True):
        m = ix.date == d
        reg = df[m & (mins >= 570) & (mins < 960)]
        ah = df[m & (mins >= 960)]
        if len(ah) and len(reg):
            return {"session": d.isoformat(), "prev_close": float(reg["Close"].iloc[-1]), "ah_price": float(ah["Close"].iloc[-1]), "ah_high": float(ah["High"].max()),
                    "ah_low": float(ah["Low"].min()), "ah_bars": int(len(ah)), "ah_volume": float(ah["Volume"].fillna(0).sum()),
                    "ah_last_et": ix[m][-1].strftime("%H:%M")}
    return None


def scan_after_hours(frames5: dict[str, pd.DataFrame], gap_pct: float | None = None, min_bars: int | None = None) -> tuple[list[dict], dict]:
    """Гаповете нагоре ≥ gap_pct от after-hours (последната сесия с post-market данни в повечето тикъри). Връща (редове по гап, diag)."""
    gap_pct = config.QM_EP_GAP_PCT if gap_pct is None else gap_pct
    min_bars = config.QM_EP_MIN_AH_BARS if min_bars is None else min_bars
    ext = {t: e for t, df in frames5.items() if (e := extract_ah(df))}
    sessions = [e["session"] for e in ext.values()]
    session = max(set(sessions), key=sessions.count) if sessions else None                      # сесията, която е най-често (изключва стари/спрели тикъри)
    rows = []
    for t, e in ext.items():
        if e["session"] != session or e["ah_bars"] < min_bars:
            continue
        g = (e["ah_price"] / e["prev_close"] - 1) * 100
        if g >= gap_pct:
            rows.append({"ticker": t, **e, "gap_pct": g})
    rows.sort(key=lambda r: -r["gap_pct"])
    return rows, {"session": session, "tickers_with_ah": len(ext), "in_session": sessions.count(session) if session else 0, "gappers": len(rows),
                  "zero_volume_share": round(float(np.mean([e["ah_volume"] == 0 for e in ext.values()])), 2) if ext else None}


def fetch_5m(universe: list[str], batch_size: int | None = None) -> tuple[dict[str, pd.DataFrame], dict]:
    """5-минутни барове с prepost за последните 5 дни, на партиди (~30 s за 903 тикъра). Връща (кадри, {batches, batches_failed})."""
    batch_size = batch_size or config.QM_EP_BATCH
    frames, st = {}, {"batches": 0, "batches_failed": 0}
    if yf is None:
        return frames, st
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i + batch_size]
        st["batches"] += 1
        try:
            data = yf.download(batch, period="5d", interval="5m", prepost=True, group_by="ticker", progress=False, threads=True, auto_adjust=False)
            if data is None or data.empty:
                raise ValueError("празен резултат")
        except Exception as e:
            st["batches_failed"] += 1
            print(f"[qm_ep] 5м партида {i // batch_size + 1} не се изтегли: {type(e).__name__}: {e}")
            continue
        for sym in batch:
            try:
                df = (data[sym] if isinstance(data.columns, pd.MultiIndex) else data).dropna(subset=["Close"])
                if len(df):
                    frames[sym] = df[["Open", "High", "Low", "Close", "Volume"]]
            except Exception:
                continue
    return frames, st


def fetch_daily(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Дневни данни (1 година, raw) за малък списък тикъри — за ADR, ръста за 3 месеца и официалното затваряне."""
    out: dict[str, pd.DataFrame] = {}
    if yf is None or not tickers:
        return out
    try:
        data = yf.download(list(tickers), period="1y", interval="1d", group_by="ticker", progress=False, auto_adjust=False, threads=True)
    except Exception as e:
        print(f"[qm_ep] дневните данни не се изтеглиха: {type(e).__name__}: {e}")
        return out
    for t in tickers:
        try:
            df = (data[t] if isinstance(data.columns, pd.MultiIndex) else data).dropna(subset=["Close", "High", "Low"])
            out[t] = df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception:
            continue
    return out


def enrich_gappers(rows: list[dict], daily: dict[str, pd.DataFrame]) -> list[dict]:
    """
    Добавя "пренебрегване" (ръст за предходните 63 бара ≤ QM_EP_NEGLECT_RET63_PCT), ADR20 и информативния максимален стоп (1× ADR под after-hours цената; негово: стоп ≤ 1–1.5× ADR).
    Гапът се преизчислява спрямо ОФИЦИАЛНОТО затваряне на сесията от дневните данни (ако го има). Липсват ли дневни данни → neglect None (не се показва като "пренебрегнат").
    """
    out = []
    for r in rows:
        d = daily.get(r["ticker"])
        e = {**r, "ret63_pct": None, "adr": None, "dollar_volume": None, "neglect": None, "max_stop": None, "max_stop_pct": None, "liquid": None,
             "levels": None}
        if d is not None and len(d):
            pos = d.index.searchsorted(pd.Timestamp(r["session"]))
            if pos < len(d) and pd.Timestamp(d.index[pos]).date().isoformat() == r["session"] and pos >= 63:
                c, h, l, v = (d[k].to_numpy(dtype=float) for k in ("Close", "High", "Low", "Volume"))
                i = pos
                official = float(c[i])
                e["prev_close"] = official
                e["gap_pct"] = (r["ah_price"] / official - 1) * 100
                e["ret63_pct"] = float((c[i] / c[i - 63] - 1) * 100)
                e["adr"] = float(100 * (np.mean(h[i - 19:i + 1] / l[i - 19:i + 1]) - 1))
                e["dollar_volume"] = float(np.mean(c[i - 19:i + 1] * v[i - 19:i + 1]))
                e["neglect"] = bool(e["ret63_pct"] <= config.QM_EP_NEGLECT_RET63_PCT)
                e["max_stop_pct"] = round(config.QM_EP_STOP_ADR * e["adr"], 1)
                e["max_stop"] = round(r["ah_price"] * (1 - config.QM_EP_STOP_ADR * e["adr"] / 100), 2)
                e["liquid"] = bool(e["dollar_volume"] >= config.QM_DOLLAR_VOLUME_MIN and official >= config.QM_PRICE_MIN)
                # 07.10.2026: вход = after-hours цената, стоп за оразмеряване = вход × (1 − ADR); размерът на позицията е в браузъра на читателя (не се смята и не се публикува тук)
                e["levels"] = trade_levels.kullamagi_levels(r["ah_price"], e["adr"], stop_adr=config.QM_EP_STOP_ADR, entry_label="after-hours цена")
        out.append(e)
    return out


# ──────────────────────────────────────────────────────────────────────────
# Катализатор: заглавия (Yahoo Finance RSS по тикър) + AI класификация, проверена от кода
# ──────────────────────────────────────────────────────────────────────────
def parse_rss(xml_text: str, since: dt.datetime | None = None, limit: int = 6) -> list[dict]:
    """[{title, published}] от RSS на Yahoo Finance за тикъра, най-новите първи; since — само по-нови от тази дата (UTC)."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    since_ts = None
    if since is not None:
        t = pd.Timestamp(since)
        since_ts = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        pub = it.findtext("pubDate")
        try:
            when = pd.Timestamp(pub).tz_convert("UTC") if pub else None
        except Exception:
            when = None
        if not title or (since_ts is not None and when is not None and when < since_ts):
            continue
        out.append({"title": title, "published": when.strftime("%Y-%m-%d %H:%M") if when is not None else None})
    return out[:limit]


def fetch_headlines(sym: str, since: dt.datetime | None = None) -> list[dict]:
    """Заглавията за тикъра от публичния RSS на Yahoo Finance (graceful: провал → [])."""
    try:
        import requests
        r = requests.get(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US", headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        return parse_rss(r.text, since)
    except Exception as e:
        print(f"[qm_ep] заглавия {sym}: {type(e).__name__}: {e}")
        return []


def _nums(text: str) -> set[str]:
    return {m.replace(",", ".") for m in NUM_RE.findall(text or "")}


def verify_ai_item(item: dict, headlines: list[dict], tickers: set[str]) -> tuple[dict | None, str | None]:
    """
    Проверка от кода на отговора на AI за един тикър: тикърът е от заявката; катализаторът е от затворения списък; "изненада" е yes/no/unclear; резюмето е до 220 знака и НЕ съдържа число,
    което го няма в заглавията (всяко число в прозата се проверява). Връща ({catalyst, summary_bg, surprise}, причина за отхвърляне на резюмето | None) или (None, причина).
    """
    if not isinstance(item, dict) or str(item.get("ticker", "")).upper() not in tickers:
        return None, "тикър извън заявката"
    cat = item.get("catalyst") if item.get("catalyst") in CATALYSTS else "unknown"
    surprise = item.get("surprise") if item.get("surprise") in SURPRISE else "unclear"
    text = " ".join(h["title"] for h in headlines)
    summary, why = str(item.get("summary_bg") or "").strip(), None
    if summary:
        extra = _nums(summary) - _nums(text)
        if extra:
            why = f"резюмето съдържа число извън заглавията ({', '.join(sorted(extra))})"
            summary = ""
        elif len(summary) > 220:
            summary = summary[:217].rstrip() + "…"
    return {"ticker": str(item["ticker"]).upper(), "catalyst": cat, "catalyst_label": CATALYSTS[cat], "summary_bg": summary or None, "surprise": surprise}, why


SYSTEM_EP = ("Ти си помощник, който връща САМО валиден JSON. Класифицираш катализатора на голям after-hours гап нагоре на акция ВЪРХУ ЗАГЛАВИЯТА, които са ти дадени. "
             "Не измисляй факти и не добавяй числа, цени, дати или проценти, които не са дословно в заглавията. Не давай препоръка за покупка или продажба.")


def _build_prompt(batch: list[dict]) -> str:
    cats = "\n".join(f'- "{k}": {v}' for k, v in CATALYSTS.items())
    payload = [{"ticker": r["ticker"], "headlines": [h["title"] for h in r["headlines"]]} for r in batch]
    return (f"АКЦИИ С ГАП НАГОРЕ СЛЕД ЗАТВАРЯНЕ (заглавия от Yahoo Finance): {json.dumps(payload, ensure_ascii=False)}\n\nКАТАЛИЗАТОРИ (ползвай САМО тези ключове; "
            f"ако заглавията не дават ясна причина — \"unknown\"):\n{cats}\n\nЗа ВСЯКА акция върни: \"catalyst\" (ключ), \"summary_bg\" (ЕДНО изречение на български до 200 знака, САМО по "
            f"заглавията, БЕЗ числа и проценти освен ако са дословно в заглавията), \"surprise\" (\"yes\"/\"no\"/\"unclear\" — изненада ли е новината за пазара според заглавията).\n\n"
            f"Връщай само JSON: {{\"items\": [{{\"ticker\": \"...\", \"catalyst\": \"...\", \"summary_bg\": \"...\", \"surprise\": \"...\"}}]}}")


def classify_catalysts(rows: list[dict], ai_call=None, batch_size: int = 5) -> tuple[dict[str, dict], list[str]]:
    """
    AI класифицира катализатора от заглавията — на batch-ове (правило 4 от CLAUDE.md); отговорът минава през verify_ai_item. Редове без заглавия не се пращат ("unknown", без AI).
    ai_call(system, user) -> JSON текст; по подразбиране ai_brief._call_claude + _parse_json. Връща ({тикър: резултат}, бележки за отхвърлено/пропаднало).
    """
    out: dict[str, dict] = {}
    notes: list[str] = []
    todo = [r for r in rows if r.get("headlines")]
    for r in rows:
        if not r.get("headlines"):
            out[r["ticker"]] = {"ticker": r["ticker"], "catalyst": "unknown", "catalyst_label": CATALYSTS["unknown"], "summary_bg": None, "surprise": "unclear"}
    if not todo:
        return out, notes
    if ai_call is None:
        try:
            from src import ai_brief
            ai_call = lambda system, user: ai_brief._call_claude(system, user, max_tokens=1500)
            parse = ai_brief._parse_json
        except Exception as e:
            notes.append(f"AI не е достъпен ({type(e).__name__})")
            for r in todo:
                out[r["ticker"]] = {"ticker": r["ticker"], "catalyst": "unknown", "catalyst_label": CATALYSTS["unknown"], "summary_bg": None, "surprise": "unclear"}
            return out, notes
    else:
        parse = json.loads
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        tickers = {r["ticker"] for r in batch}
        try:
            data = parse(ai_call(SYSTEM_EP, _build_prompt(batch)))
            items = data.get("items") if isinstance(data, dict) else data
        except Exception as e:
            notes.append(f"AI партида {i // batch_size + 1} пропадна: {type(e).__name__}")
            items = []
        by = {str(x.get("ticker", "")).upper(): x for x in (items or []) if isinstance(x, dict)}
        for r in batch:
            v, why = verify_ai_item(by.get(r["ticker"]) or {}, r["headlines"], tickers) if r["ticker"] in by else (None, "няма отговор")
            if v is None:
                v = {"ticker": r["ticker"], "catalyst": "unknown", "catalyst_label": CATALYSTS["unknown"], "summary_bg": None, "surprise": "unclear"}
            if why:
                notes.append(f"{r['ticker']}: {why}")
            out[r["ticker"]] = v
    return out, notes


# ──────────────────────────────────────────────────────────────────────────
# Дневник: after-hours гап срещу реалния гап на отварянето (за решение след 4–6 седмици)
# ──────────────────────────────────────────────────────────────────────────
LOG_MAX = 500


def next_session(d: dt.date) -> dt.date:
    d = d + dt.timedelta(days=1)
    while not setup_rules.is_session(d):
        d += dt.timedelta(days=1)
    return d


def load_log(path=None) -> dict:
    p = pathlib.Path(path or config.QM_EP_LOG_FILE)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d.get("entries"), list) else {"entries": []}
    except FileNotFoundError:
        return {"entries": []}
    except Exception as e:
        print(f"[qm_ep] дневникът е нечетим, започвам от празен: {type(e).__name__}: {e}")
        return {"entries": []}


def save_log(log: dict, path=None) -> None:
    p = pathlib.Path(path or config.QM_EP_LOG_FILE)
    try:
        p.parent.mkdir(exist_ok=True)
        log["entries"] = log["entries"][-LOG_MAX:]
        p.write_text(json.dumps(log, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except Exception as e:
        print(f"[qm_ep] дневникът не се записа: {type(e).__name__}: {e}")


def add_entries(log: dict, rows: list[dict], brief_date: str) -> int:
    """Записва ВСИЧКИ after-hours гапове ≥ прага (и "непренебрегнатите") — по тикър и сесия, без дубликати. Връща броя нови."""
    have = {(e["ticker"], e["session"]) for e in log["entries"]}
    n = 0
    for r in rows:
        if (r["ticker"], r["session"]) in have:
            continue
        log["entries"].append({"ticker": r["ticker"], "session": r["session"], "brief_date": brief_date,
                               "gap_session": next_session(dt.date.fromisoformat(r["session"])).isoformat(), "prev_close": round(r["prev_close"], 4),
                               "ah_price": round(r["ah_price"], 4), "ah_gap_pct": round(r["gap_pct"], 2), "ah_bars": r["ah_bars"], "ah_volume": r["ah_volume"],
                               "neglect": r.get("neglect"), "ret63_pct": None if r.get("ret63_pct") is None else round(r["ret63_pct"], 1),
                               "open_gap_pct": None, "close_pct": None, "high_pct": None, "resolved_on": None})
        n += 1
    return n


def resolve_entries(log: dict, today: dt.date, daily_fetch=None) -> int:
    """Попълва реалния гап на отварянето (Open на gap_session спрямо затварянето на сесията), деня (close %, high %) за записите, чиято gap_session вече е минала. Връща броя разрешени."""
    daily_fetch = daily_fetch or fetch_daily
    todo = [e for e in log["entries"] if e.get("open_gap_pct") is None and dt.date.fromisoformat(e["gap_session"]) < today]
    if not todo:
        return 0
    daily = daily_fetch(sorted({e["ticker"] for e in todo}))
    n = 0
    for e in todo:
        d = daily.get(e["ticker"])
        if d is None or d.empty:
            continue
        ts = pd.Timestamp(e["gap_session"])
        if ts not in d.index:
            continue
        row = d.loc[ts]
        pc = e["prev_close"]
        e.update(open_gap_pct=round((float(row["Open"]) / pc - 1) * 100, 2), close_pct=round((float(row["Close"]) / pc - 1) * 100, 2),
                 high_pct=round((float(row["High"]) / pc - 1) * 100, 2), resolved_on=today.isoformat())
        n += 1
    return n


def summarize_log(entries: list[dict]) -> dict:
    """AH гап срещу реалния гап на отварянето: колко са разрешени, колко отварят ≥ прага, медианно разминаване, корелация."""
    res = [e for e in entries if e.get("open_gap_pct") is not None]
    out = {"entries": len(entries), "resolved": len(res), "held_at_open": None, "held_share_pct": None, "median_diff_pp": None, "corr": None, "median_open_gap_pct": None}
    if not res:
        return out
    thr = config.QM_EP_GAP_PCT
    held = [e for e in res if e["open_gap_pct"] >= thr]
    diffs = [e["open_gap_pct"] - e["ah_gap_pct"] for e in res]
    out.update(held_at_open=len(held), held_share_pct=round(100 * len(held) / len(res), 0), median_diff_pp=round(statistics.median(diffs), 2),
               median_open_gap_pct=round(statistics.median(e["open_gap_pct"] for e in res), 2))
    if len(res) >= 3:
        a, b = np.array([e["ah_gap_pct"] for e in res]), np.array([e["open_gap_pct"] for e in res])
        out["corr"] = round(float(np.corrcoef(a, b)[0, 1]), 2) if a.std() > 0 and b.std() > 0 else None
    return out


# ──────────────────────────────────────────────────────────────────────────
# Оркестрация
# ──────────────────────────────────────────────────────────────────────────
def run(universe: list[str], today: dt.date | None = None, *, fetch_5m_fn=None, fetch_daily_fn=None, headlines_fn=None, ai_call=None, name_lookup=None, log_path=None) -> dict:
    """
    След затваряне → гапове ≥ 10% → (нейният) ръст за 3 месеца, ADR, максимален стоп → заглавия + AI класификация на катализатора за показаните → дневник. Връща
    {"ok", "session", "rows" (показаните — "пренебрегнати", най-много QM_EP_MAX_ROWS), "not_neglected" (останалите гапове ≥ 10%), "diag", "log" (обобщение), "notes"}. Не вдига.
    """
    today = today or dt.date.today()
    out = {"ok": False, "session": None, "rows": [], "not_neglected": [], "diag": {}, "log": {}, "notes": []}
    try:
        f5, st = (fetch_5m_fn or fetch_5m)(universe)
        gappers, diag = scan_after_hours(f5)
        diag.update(st)
        out.update(session=diag.get("session"), diag=diag, ok=bool(f5) and st.get("batches_failed", 0) < max(1, st.get("batches", 1)))
        daily = (fetch_daily_fn or fetch_daily)([g["ticker"] for g in gappers]) if gappers else {}
        allrows = enrich_gappers(gappers, daily)
        shown = [r for r in allrows if r["neglect"] and r["liquid"] and r["gap_pct"] >= config.QM_EP_GAP_PCT][:config.QM_EP_MAX_ROWS]
        out["not_neglected"] = [{"ticker": r["ticker"], "gap_pct": round(r["gap_pct"], 1), "ret63_pct": None if r["ret63_pct"] is None else round(r["ret63_pct"], 0),
                                 "why": "липсват дневни данни" if r["neglect"] is None else f"ръст {r['ret63_pct']:.0f}% за 3 месеца > {config.QM_EP_NEGLECT_RET63_PCT:g}%"}
                                for r in allrows if r not in shown and (r["neglect"] is not True or not r["liquid"])]
        since = dt.datetime.combine(dt.date.fromisoformat(diag["session"]) if diag.get("session") else today, dt.time(0, 0)) - dt.timedelta(days=1)
        for r in shown:
            r["headlines"] = (headlines_fn or fetch_headlines)(r["ticker"], since)
            if name_lookup:
                try:
                    r["company"] = name_lookup(r["ticker"]) or r["ticker"]
                except Exception:
                    r["company"] = r["ticker"]
        cls, notes = classify_catalysts(shown, ai_call)
        out["notes"] += notes
        for r in shown:
            r.update({k: v for k, v in (cls.get(r["ticker"]) or {}).items() if k != "ticker"})
            r["ah_volume_available"] = bool(r["ah_volume"] and r["ah_volume"] > 0)
            r["headlines"] = r.get("headlines", [])[:3]
        out["rows"] = shown
        # дневник: ВСИЧКИ гапове; разрешаване на по-старите; обобщение
        log = load_log(log_path)
        added = add_entries(log, allrows, today.isoformat())
        resolved = resolve_entries(log, today, fetch_daily_fn)
        save_log(log, log_path)
        yesterday = [{"ticker": x["ticker"], "session": x["session"], "gap_session": x["gap_session"], "ah_gap_pct": x["ah_gap_pct"], "open_gap_pct": x["open_gap_pct"],
                      "close_pct": x.get("close_pct"), "held": bool(x["open_gap_pct"] >= config.QM_EP_GAP_PCT)}
                     for x in log["entries"] if x.get("resolved_on") == today.isoformat() and x.get("open_gap_pct") is not None]
        out["log"] = {**summarize_log(log["entries"]), "added_today": added, "resolved_today": resolved, "yesterday": yesterday}
        print(f"[qm_ep] сесия {diag.get('session')}: {len(gappers)} after-hours гапа ≥ {config.QM_EP_GAP_PCT:g}%, показани {len(shown)} (пренебрегнати), "
              f"останали {len(out['not_neglected'])}; дневник: {out['log']['entries']} записа, {out['log']['resolved']} разрешени")
    except Exception as e:
        out["notes"].append(f"{type(e).__name__}: {e}")
        out["ok"] = False
        print(f"[qm_ep] наблюдението пропадна: {type(e).__name__}: {e}")
    return out
