"""
Обновяване ПРЕДИ ОТВАРЯНЕТО (03.11.2026, т. 10 — решения от 03.11): в 09:05 Ню Йорк (15:05 Берлин, през зимата; 14:05 до края на октомври и от март), като ОТДЕЛНА стъпка в
options_record.yml — провал на записа на опциите не спира обновяването и обратно. Сутрешният бриф е в 07:30 Берлин (01:30 Ню Йорк) — тогава премаркетът (от 04:00 Ню Йорк)
още не е започнал: отчетите преди отварянето (BMO) не се виждат. Измерено 08.10–02.11: от 13 отваряния ≥ +10% в универса EP сутрин хвана 2; в 09:05 Ню Йорк в премаркета
се виждаха 10.

Три неща, от ЕДНО теглене на 5-минутни бари с премаркет (prepost) за универса + наблюдаваните + тикърите в книгите / картите:
  (а) EP — гапове ≥ +config.PREOPEN_GAP_PCT в премаркета спрямо затварянето на предишната сесия, с пренебрегването (ръст за ~3 месеца, както сутрин — qm_ep.enrich_gappers) и
      катализатора БЕЗ AI: 8-K след затварянето (точките, qm_ep.company_filings) и първото заглавие за компанията — дословно (Yahoo RSS, qm_ep.rank_headlines);
  (б) нивата: „Чака пробив“ (buy-stop), картите по Kullamägi (нивото) и живите записи в книгите — чакащ запис над нивото си, отворен под стопа си, „GLB по Уиш“ под линията;
  (в) наблюдаваните с гап ≥ ±config.PREOPEN_WATCH_GAP_PCT.
Изход: data/preopen/<дата>.json; карето „Преди отварянето“ най-горе на страницата (docs/index.html се рендерира наново от сутрешния бриф + карето — стои до следващия сутрешен
бриф); кратък имейл САМО ако (а), (б) или (в) има нещо — веднъж на ден (отметката е в JSON-а).

Чисти функции (premarket_point / scan / level_checks / watch_gaps / email_html) + мрежа само в fetch_* и main. Graceful: всяка част е в try/except и дава частичен резултат.
"""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import time

import pandas as pd

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

NY = "America/New_York"
OPEN_MIN, CLOSE_MIN = 9 * 60 + 30, 16 * 60


def _ny(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return (t.tz_localize("UTC") if t.tzinfo is None else t).tz_convert(NY)


def premarket_point(df: pd.DataFrame | None, now_utc) -> dict | None:
    """
    Един тикър (5-минутни бари с премаркет, индекс с часова зона): затварянето на ПРЕДИШНАТА сесия (последният ѝ редовен бар) и последната цена в премаркета ДНЕС до now
    (бар, започнал преди now и преди 09:30 Ню Йорк). → {session, prev_close, pm_price, pm_bars, pm_volume (None при нулев обем), pm_last_ny}; без едното → None. Чиста функция.
    """
    from src import sessions
    if df is None or len(df) == 0 or "Close" not in df:
        return None
    now = _ny(now_utc)
    ix = pd.DatetimeIndex(df.index)
    ix = (ix.tz_localize("UTC") if ix.tz is None else ix).tz_convert(NY)
    mins = ix.hour * 60 + ix.minute
    today, prev = now.date(), sessions.prev_session(now.date())
    reg = df[(ix.date == prev) & (mins >= OPEN_MIN) & (mins < CLOSE_MIN)]["Close"].dropna()
    pm_mask = (ix.date == today) & (mins < OPEN_MIN) & (ix < now)
    pm = df[pm_mask]
    pmc = pm["Close"].dropna()
    if len(reg) == 0 or len(pmc) == 0:
        return None
    vol = float(pm["Volume"].fillna(0).sum()) if "Volume" in pm else 0.0
    return {"session": prev.isoformat(), "prev_close": float(reg.iloc[-1]), "pm_price": float(pmc.iloc[-1]), "pm_bars": int(len(pmc)),
            "pm_volume": vol or None, "pm_last_ny": ix[pm_mask][-1].strftime("%H:%M")}


def scan(frames5: dict, now_utc) -> tuple[dict, list[dict], dict]:
    """
    Всички тикъри → ({тикър: premarket_point}, гаповете ≥ PREOPEN_GAP_PCT с поне PREOPEN_MIN_PM_BARS бара в премаркета, по гап; diag). Чиста функция.
    """
    pts = {t: p for t, df in (frames5 or {}).items() if (p := premarket_point(df, now_utc))}
    gaps = []
    for t, p in pts.items():
        g = (p["pm_price"] / p["prev_close"] - 1) * 100 if p["prev_close"] else 0
        if g >= config.PREOPEN_GAP_PCT and p["pm_bars"] >= config.PREOPEN_MIN_PM_BARS:
            gaps.append({"ticker": t, **p, "gap_pct": g})
    gaps.sort(key=lambda r: -r["gap_pct"])
    diag = {"tickers": len(frames5 or {}), "with_pm": len(pts), "gappers": len(gaps),
            "zero_volume_share": round(sum(1 for p in pts.values() if not p["pm_volume"]) / len(pts), 2) if pts else None}
    return pts, gaps, diag


def _pct(a, b) -> float:
    return round((a / b - 1) * 100, 2)


def level_checks(pts: dict, waiting: list[dict], qm_cards: list[dict], records: list[dict], today: str | None = None) -> list[dict]:
    """
    (б) Само пресичанията в премаркета: „Чака пробив“ и чакащ запис — цената над buy-stop нивото (ще се задейства на отварянето); карта по Kullamägi — над нивото на пробива;
    отворен запис — под стопа; „GLB по Уиш“ — под линията (изходът е по затваряне — само информация). → [{ticker, what, kind, level, pm_price, pct}]. Чиста функция.
    """
    out = []

    def add(t, what, kind, level):
        p = pts.get(t)
        if p and isinstance(level, (int, float)) and level > 0:
            hit = p["pm_price"] >= level if kind == "над нивото" else p["pm_price"] < level      # „под стопа“, „под стопа (break-even)“, „под линията“
            if hit:
                out.append({"ticker": t, "what": what, "kind": kind, "level": round(float(level), 2), "pm_price": round(p["pm_price"], 2), "pct": _pct(p["pm_price"], level),
                            "pm_volume": p["pm_volume"]})

    for c in waiting or []:
        add(c.get("ticker"), "Чака пробив", "над нивото", (c.get("setup") or {}).get("buy_stop"))
    for c in qm_cards or []:
        add(c.get("ticker"), "Kullamägi", "над нивото", c.get("trigger"))
    names = {"action": "книга Action", "buystop": "книга buy-stop", "qm_breakout": "книга QM", "glb_wish_high": "книга GLB по Уиш"}
    for r in records or []:
        cat, st = r.get("category") or "action", r.get("status")
        what = names.get(cat)
        if not what or r.get("needs_manual_review"):              # 04.11.2026 (С2): сплит / отделяне след входа — нивата са в старата скала, не се сравняват
            continue
        if st == "pending" and cat != "glb_wish_high":
            # 04.11.2026 (прегледът, т. 5): чакащ запис с изтекъл срок не е ниво за днес. Реално 04.11: SN_2026-10-12_qm (срок 12.10, ниво $186.75, премаркет $210.50) — записът се роди
            # сутринта от стария snapshot (5-минутните бари скъсиха предишния SN до 09.10) и се резолвира чак в следващия бриф; карето го показа „над нивото“.
            vt = r.get("valid_through")
            if today and vt and str(vt) < today:
                continue
            add(r.get("ticker"), what, "над нивото", r.get("buy_stop"))
        elif st in ("open", "trailing"):
            if cat == "glb_wish_high":
                add(r.get("ticker"), what, "под линията", r.get("line_used") or r.get("line"))
            elif cat == "qm_breakout" and st == "trailing":
                # 04.11.2026 (четвърти преглед, С2): след частичната продажба стопът на qm_breakout е break-even = входът (trade_sim.simulate_qm); до 04.11 — първоначалният
                # stop_loss (DOCU 70.885 срещу 72.76, UTHR 545.58 срещу 560.00 — РЕАЛНО, книгата към 03.11)
                be = [x for x in (r.get("stop_loss"), r.get("fill_price") or r.get("entry_price")) if isinstance(x, (int, float))]
                add(r.get("ticker"), what, "под стопа (break-even)", max(be) if be else None)          # = max(стоп, вход) — както trade_sim
            else:
                add(r.get("ticker"), what, "под стопа", r.get("stop_loss"))
    seen, uniq = set(), []
    for x in out:                                                                   # един ред на (тикър, какво, вид)
        k = (x["ticker"], x["what"], x["kind"])
        if k not in seen:
            seen.add(k); uniq.append(x)
    return uniq


def watch_closes(brief: dict | None) -> dict:
    """03.11.2026 (прегледа на т. 10, 3): официалното затваряне на наблюдаваните от сутрешния бриф (brief["watch"] → facts.price {date, close}) — без нова заявка. Чиста функция."""
    out = {}
    for w in (brief or {}).get("watch") or []:
        pr = ((w or {}).get("facts") or {}).get("price") or {}
        if w.get("ticker") and isinstance(pr.get("close"), (int, float)) and pr.get("date"):
            out[w["ticker"]] = {"close": float(pr["close"]), "date": str(pr["date"])}
    return out


def watch_gaps(pts: dict, watched: list[str], closes: dict | None = None) -> list[dict]:
    """
    (в) Наблюдаваните с гап ≥ ±PREOPEN_WATCH_GAP_PCT в премаркета. Базата — официалното затваряне от сутрешния бриф (closes = watch_closes(brief)), когато е за същата сесия
    (close_src "brief"); иначе — последният редовен 5-минутен бар (close_src "5m", с бележка в реда). Чиста функция.
    """
    out = []
    for t in watched or []:
        p = pts.get(t)
        if not p:
            continue
        c = (closes or {}).get(t) or {}
        base, src = (c["close"], "brief") if c.get("date") == p["session"] and c.get("close") else (p["prev_close"], "5m")
        if base:
            g = _pct(p["pm_price"], base)
            if abs(g) >= config.PREOPEN_WATCH_GAP_PCT:
                out.append({"ticker": t, "gap_pct": g, "pm_price": round(p["pm_price"], 2), "prev_close": round(base, 2), "close_src": src, "pm_last_ny": p["pm_last_ny"],
                            "pm_volume": p["pm_volume"]})
    return sorted(out, key=lambda x: -abs(x["gap_pct"]))


def filing_line(f: dict) -> str:
    """03.11.2026 (прегледа на т. 10, 2; разходката, т. 0б): „8-K (SEC), 02.11 16:27 ET: 2.02 — финансови резултати“ — същият ред като в сутрешната EP карта (qm_ep.filing_headline)."""
    from src import qm_ep
    return qm_ep.filing_headline(f)["title"]


def ep_rows(gaps: list[dict], *, daily_fn=None, filings_fn=None, headlines_fn=None, name_lookup=None, now_utc=None) -> list[dict]:
    """
    (а) Гаповете → пренебрегването (qm_ep.enrich_gappers — както сутрин), 8-K след затварянето (точките) и първото заглавие за компанията, ДОСЛОВНО (без AI). Graceful по тикър.
    """
    from src import qm_ep
    gaps = gaps[:config.PREOPEN_MAX_ROWS]
    if not gaps:
        return []
    rows = [{**g, "ah_price": g["pm_price"]} for g in gaps]                        # enrich_gappers очаква after-hours цената — тук е премаркетът
    try:
        daily = (daily_fn or qm_ep.fetch_daily)([g["ticker"] for g in gaps])
    except Exception as e:
        print(f"[preopen] дневните данни за гаповете: {type(e).__name__}: {e}")
        daily = {}
    out = []
    for e in qm_ep.enrich_gappers(rows, daily):
        t = e["ticker"]
        row = {k: e.get(k) for k in ("ticker", "session", "prev_close", "pm_price", "pm_bars", "pm_volume", "pm_last_ny", "gap_pct", "ret63_pct", "neglect", "liquid", "adr")}
        row["gap_pct"] = round(row["gap_pct"], 2) if row.get("gap_pct") is not None else None
        try:
            row["company"] = (name_lookup(t) if name_lookup else None) or t
        except Exception:
            row["company"] = t
        since = dt.datetime.combine(dt.date.fromisoformat(e["session"]), dt.time(0, 0)) - dt.timedelta(days=1)
        src = qm_ep.catalyst_sources(t, e["session"], since, filings_fn=filings_fn, headlines_fn=headlines_fn, now_utc=now_utc)   # 04.11.2026 (С1): „не се провери“ ≠ „няма“
        try:
            row["filings_8k"] = [{"accepted_et": f["accepted_et"], "items": [f"{c}" for c, *_ in f["items"]], "text": filing_line(f)} for f in src["filings_8k"]]
        except Exception as ex:
            print(f"[preopen] 8-K {t}: {type(ex).__name__}: {ex}")
            row["filings_8k"], src["filings_error"] = [], f"8-K не се прочете ({type(ex).__name__})"
        row["filings_error"] = src["filings_error"]
        try:
            hl = qm_ep.rank_headlines(src["headlines_raw"], t, row["company"])
            row["headline"] = {k: hl[0].get(k) for k in ("title", "source", "published", "link")} if hl else None
        except Exception as ex:
            print(f"[preopen] заглавия {t}: {type(ex).__name__}: {ex}")
            row["headline"], src["headlines_error"] = None, f"заглавията не се подредиха ({type(ex).__name__})"
        row["headlines_error"] = src["headlines_error"]
        out.append(row)
    return out


def morning_generated(page_html: str | None) -> tuple[str, str] | None:
    """Часът „генериран HH:MM CET“ на сутрешния бриф от текущата страница — заглавието го пази, когато карето се добавя наново (иначе би казало 15:05). Чиста функция."""
    import re
    m = re.search(r"генериран (\d{2}:\d{2}) (CET|CEST|UTC)", page_html or "")
    return (m.group(1), m.group(2)) if m else None


def volume_note(res: dict) -> str | None:
    """
    03.11.2026 (прегледа на т. 10): EP иска обем, а в премаркета Yahoo често дава 0 (на 03.11 — при 682 от 682 тикъра с премаркет). Тикърите в карето без обем → редът
    „Обемът в премаркета не е наличен (Yahoo) — провери го в първите минути“ (за всички) или „… за X, Y — …“ (за част от тях); с обем при всички / празно каре → None. Чиста функция.
    """
    rows = (res.get("gaps") or []) + (res.get("levels") or []) + (res.get("watch") or [])
    vol = {}
    for r in rows:
        vol[r["ticker"]] = vol.get(r["ticker"]) or r.get("pm_volume")
    missing = [t for t, v in vol.items() if not v]
    if not missing:
        return None
    who = "" if len(missing) == len(vol) else f" за {', '.join(missing)}"
    return f"Обемът в премаркета не е наличен (Yahoo){who} — провери го в първите минути"


def qm_ep_sources_note(row: dict) -> str | None:
    """04.11.2026 (С1): „8-K: не се провери (…) · заглавия: не се провериха (…)“ — qm_ep.sources_note."""
    from src import qm_ep
    return qm_ep.sources_note(row)


def has_news(res: dict) -> bool:
    return bool(res.get("gaps") or res.get("levels") or res.get("watch"))


def email_html(res: dict) -> str:
    """Краткият имейл — само ако има нещо (has_news). Чиста функция."""
    e = _html.escape
    li = lambda xs: "<ul style='margin:4px 0 10px;padding-left:18px'>" + "".join(f"<li style='margin:2px 0'>{x}</li>" for x in xs) + "</ul>"
    parts = [f"<div style='font-family:Arial,sans-serif;font-size:13px;color:#111'><b>Преди отварянето · {e(res['date'][8:10])}.{e(res['date'][5:7])}, "
             f"{e(res.get('time_ny', ''))} Ню Йорк ({e(res.get('time_berlin', ''))} Берлин)</b><br><span style='color:#6b7280'>Само информация, не препоръка. Цените са от премаркета "
             f"(Yahoo, 5-минутни бари); обемът там често липсва.</span>"]
    if volume_note(res):
        parts.append(f"<div style='margin-top:6px;color:#92400e'>⚠ {e(volume_note(res))}.</div>")
    cov = res.get("coverage") or {}
    if cov.get("partial"):                                                          # 04.11.2026 (С3)
        parts.append(f"<div style='margin-top:6px;color:#991b1b'>⚠ Частично: {e(cov['reason'])} — празното НЕ значи, че няма гапове.</div>")
    if res.get("gaps"):
        parts.append("<div style='margin-top:10px'><b>EP — гапове ≥ +%g%% в премаркета</b></div>" % config.PREOPEN_GAP_PCT)
        parts.append(li([f"<b>{e(g['ticker'])}</b> {g['gap_pct']:+.1f}% (${g['pm_price']:.2f}; затваряне ${g['prev_close']:.2f})"
                         + (f" · обем в премаркета {g['pm_volume']:,.0f}".replace(",", " ") if g.get("pm_volume") else "")
                         + (f" · {'пренебрегнат' if g.get('neglect') else 'не е пренебрегнат'} (3 мес. {g['ret63_pct']:+.0f}%)" if g.get("ret63_pct") is not None else "")
                         + "".join(f"<br><span style='color:#374151'>{e(f['text'])}</span>" for f in g.get("filings_8k") or [])
                         + (f"<br><span style='color:#374151'>„{e(g['headline']['title'])}“" + (f" · {e(g['headline']['source'])}" if g["headline"].get("source") else "") + "</span>"
                            if g.get("headline") else "")
                         + (f"<br><span style='color:#92400e'>{e(qm_ep_sources_note(g))}</span>" if qm_ep_sources_note(g) else "")      # 04.11.2026 (С1)
                         for g in res["gaps"]]))
    if res.get("levels"):
        parts.append("<div><b>Нивата в премаркета</b></div>")
        parts.append(li([f"<b>{e(x['ticker'])}</b> · {e(x['what'])} — {e(x['kind'])} ${x['level']:.2f} (премаркет ${x['pm_price']:.2f}, {x['pct']:+.1f}%)" for x in res["levels"]]))
    if res.get("watch"):
        parts.append("<div><b>Наблюдаваните (гап ≥ ±%g%%)</b></div>" % config.PREOPEN_WATCH_GAP_PCT)
        parts.append(li([f"<b>{e(x['ticker'])}</b> {x['gap_pct']:+.1f}% (${x['pm_price']:.2f}; затваряне ${x['prev_close']:.2f}"
                         + (" — последният 5-мин. бар, няма го в сутрешния бриф" if x.get("close_src") == "5m" else "") + ")" for x in res["watch"]]))
    return "".join(parts) + "</div>"


LAST_FETCH: dict = {}          # 04.11.2026 (С3): {"batches", "batches_failed"} от последното fetch_5m


def fetch_5m(tickers: list[str], batch_size: int | None = None) -> dict:
    """5-минутни бари с премаркет за последните 2 дни, на партиди (както qm_ep.fetch_5m). Партида с провал — ред в лога и LAST_FETCH (04.11.2026, С3), останалите минават."""
    import yfinance as yf
    out = {}
    bs = batch_size or config.QM_EP_BATCH
    LAST_FETCH.clear()
    LAST_FETCH.update(batches=(len(tickers) + bs - 1) // bs, batches_failed=0)
    for i in range(0, len(tickers), bs):
        batch = tickers[i:i + bs]
        try:
            data = yf.download(batch, period="2d", interval="5m", prepost=True, group_by="ticker", progress=False, threads=True, auto_adjust=False)
        except Exception as e:
            LAST_FETCH["batches_failed"] += 1
            print(f"[preopen] партида {i // bs + 1}: {type(e).__name__}: {e}")
            continue
        for t in batch:
            try:
                df = (data[t] if isinstance(data.columns, pd.MultiIndex) else data).dropna(subset=["Close"])
                if len(df):
                    out[t] = df[["Open", "High", "Low", "Close", "Volume"]]
            except Exception:
                continue
    return out


def coverage(diag: dict, fetch: dict | None = None, universe_note: str | None = None) -> dict:
    """
    04.11.2026 (четвърти преглед, С3): {"with_pm", "requested", "batches", "batches_failed", "partial", "reason"} — „частично“ при паднала партида, непълен универс или под
    config.PREOPEN_MIN_PM_SHARE от поисканите с бари в премаркета. До 04.11 ok = „поне един тикър“ и карето казваше „Нищо за отбелязване … в универса“ и при 5 от 918. Чиста функция.
    """
    n, k = diag.get("requested") or 0, diag.get("with_pm") or 0
    fetch = fetch or {}
    why = []
    if fetch.get("batches_failed"):
        why.append(f"{fetch['batches_failed']} от {fetch.get('batches')} партиди не се изтеглиха")
    if n and k < config.PREOPEN_MIN_PM_SHARE * n:
        why.append(f"премаркет само за {k} от {n} тикъра")
    if universe_note:
        why.append(universe_note)
    return {"with_pm": k, "requested": n, "batches": fetch.get("batches"), "batches_failed": fetch.get("batches_failed"), "partial": bool(why), "reason": "; ".join(why) or None}


def run(now_utc=None, *, frames5: dict | None = None, fetch5=None, brief: dict | None = None, records: list[dict] | None = None, watched: list[str] | None = None,
        universe: list[str] | None = None, daily_fn=None, filings_fn=None, headlines_fn=None, name_lookup=None, universe_note: str | None = None) -> dict:
    """
    Целият резултат (без запис и без имейл): {date, time_ny, time_berlin, session, ok, diag, gaps, levels, watch, seconds}. frames5 — готовите 5-минутни бари (тестове, реплей);
    иначе fetch5(тикъри) / fetch_5m. brief — сутрешният бриф (за „Чака пробив“ и картите по Kullamägi); records — живите записи в книгите; watched — наблюдаваните. Не вдига.
    """
    from src import setup_rules
    t0 = time.monotonic()
    now = _ny(now_utc or dt.datetime.now(dt.timezone.utc))
    res = {"date": now.date().isoformat(), "time_ny": now.strftime("%H:%M"), "time_berlin": now.tz_convert("Europe/Berlin").strftime("%H:%M"),
           "ok": False, "diag": {}, "gaps": [], "levels": [], "watch": [], "notes": []}
    try:
        brief = brief or {}
        try:
            from src import render
            waiting, _ = render.split_canslim(brief.get("watchlist") or [])
        except Exception as e:
            waiting = []
            res["notes"].append(f"„Чака пробив“ не се прочете ({type(e).__name__})")
        qm_cards = brief.get("qm_breakout") or []
        extra = [c.get("ticker") for c in waiting + qm_cards] + [r.get("ticker") for r in records or []] + list(watched or [])
        tickers = list(dict.fromkeys([t for t in list(universe or []) + extra if t]))
        LAST_FETCH.clear()
        if frames5 is None:
            frames5 = (fetch5 or fetch_5m)(tickers)
        pts, gaps, diag = scan(frames5, now)
        res["diag"] = {**diag, "requested": len(tickers)}
        res["coverage"] = coverage(res["diag"], dict(LAST_FETCH), universe_note)          # 04.11.2026 (С3): „премаркет за N от M“ и „частично“
        res["session"] = next(iter(pts.values()))["session"] if pts else None
        res["ok"] = bool(pts)
        res["gaps"] = ep_rows(gaps, daily_fn=daily_fn, filings_fn=filings_fn, headlines_fn=headlines_fn, name_lookup=name_lookup, now_utc=now.tz_convert("UTC").to_pydatetime())
        res["levels"] = level_checks(pts, waiting, qm_cards, records or [], res["date"])
        res["watch"] = watch_gaps(pts, watched or [], watch_closes(brief))
        res["volume_note"] = volume_note(res)
    except Exception as e:
        res["notes"].append(f"{type(e).__name__}: {e}")
        print(f"[preopen] пропадна: {type(e).__name__}: {e}")
    res["seconds"] = round(time.monotonic() - t0, 1)
    if (res.get("coverage") or {}).get("partial"):
        print(f"::warning::[preopen] частично: {res['coverage']['reason']}")
    print(f"[preopen] {res['date']} {res['time_ny']} Ню Йорк: тикъри с премаркет {res['diag'].get('with_pm')} от {res['diag'].get('requested')}, гапове ≥ "
          f"{config.PREOPEN_GAP_PCT:g}% {len(res['gaps'])}, нива {len(res['levels'])}, наблюдавани {len(res['watch'])} ({res['seconds']} s)")
    return res


def skip_reason(now_utc) -> str | None:
    """
    03.11.2026 (прегледа на т. 10, 4): прозорецът е СЪЩИЯТ като на записа на опциите — options_record.skip_reason (ден със сесия, 09:00–09:30 Ню Йорк), без проверката „сесията
    вече е записана“ (тя е за историята на опциите). Графикът в cron-job.org е по Берлин („5 14,15 * * 1-5“) — от двете пускания на ден точно едното е в 09:05 Ню Йорк, и в
    седмиците с разминаване на смяната на часа (САЩ / Европа); другото (08:05 или 10:05 Ню Йорк) прескача — второ обновяване няма. Чиста функция.
    """
    from src import options_record
    return options_record.skip_reason(now_utc, None)


def late_reason(now_utc) -> str | None:
    """
    04.11.2026 (четвърти преглед, Н6): закъсняло пускане — ден със сесия и час в Ню Йорк от отварянето (09:30) до config.PREOPEN_LATE_UNTIL_NY → причината; иначе None. Чиста функция.
    """
    from src import sessions
    ny = _ny(now_utc)
    lh, lm = map(int, config.PREOPEN_LATE_UNTIL_NY.split(":"))
    if sessions.is_session(ny.date()) and (9, 30) <= (ny.hour, ny.minute) < (lh, lm):
        return f"пускането стартира в {ny.strftime('%H:%M')} Ню Йорк — след отварянето; премаркетът не е проверен днес"
    return None


def _late_box(now, day: str, why: str) -> None:
    """04.11.2026 (Н6): закъсняло пускане → data/preopen/<дата>.json с ok False / late True и карето на страницата (без имейл), ако днес още няма успешно обновяване."""
    from src import render
    path = config.DATA_DIR / "preopen" / f"{day}.json"
    try:
        prev = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        prev = {}
    if prev.get("ok"):
        return
    n = _ny(now)
    res = {"date": day, "time_ny": n.strftime("%H:%M"), "time_berlin": n.tz_convert("Europe/Berlin").strftime("%H:%M"), "ok": False, "late": True, "diag": {},
           "gaps": [], "levels": [], "watch": [], "notes": [why], "email": prev.get("email") or {"sent": False}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    bp = config.DATA_DIR / f"{day}.json"
    try:
        brief = json.loads(bp.read_text(encoding="utf-8")) if bp.exists() else {}
        if brief:
            brief["preopen"] = res
            page = config.DOCS_DIR / "index.html"
            render.render_dashboard(brief, publish=False, as_of=dt.date.fromisoformat(day), generated=morning_generated(page.read_text(encoding="utf-8") if page.exists() else None))
    except Exception as e:
        print(f"::warning::[preopen] страницата не се рендерира: {type(e).__name__}: {e}")


def main(now_utc=None) -> int:
    """
    Входната точка (options_record.yml, отделна стъпка): прозорецът (09:00–09:30 Ню Йорк, ден със сесия — както записа на опциите) → run → data/preopen/<дата>.json →
    docs/index.html наново (сутрешният бриф + карето) → имейл, ако има нещо и още не е пратен днес. Изход 1 само при провал на тегленето.
    """
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    why = skip_reason(now)
    if why:
        late = late_reason(now)                                                    # 04.11.2026 (Н6): закъсняло пускане — каре, не само ред в лога
        if late:
            print(f"::warning::[preopen] {late}")
            try:
                _late_box(now, _ny(now).date().isoformat(), late)
            except Exception as e:
                print(f"::warning::[preopen] карето за закъснялото пускане не се записа: {type(e).__name__}: {e}")
            return 0
        print(f"::notice::[preopen] {why}")
        return 0
    from src import screener, backtest, watch_monitor, render, emailer
    day = _ny(now).date().isoformat()
    path = config.DATA_DIR / "preopen" / f"{day}.json"
    prev = {}
    try:
        prev = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        prev = {}
    bp = config.DATA_DIR / f"{day}.json"
    brief = {}
    try:                                                                            # 04.11.2026 (четвърти преглед, Н1): повреден JSON не сваля стъпката с traceback
        brief = json.loads(bp.read_text(encoding="utf-8")) if bp.exists() else {}
    except Exception as e:
        print(f"::warning::[preopen] сутрешният бриф за {day} не се прочете ({type(e).__name__}: {e})")
        brief = {}
    if not brief:
        print(f"::warning::[preopen] няма сутрешен бриф за {day} — без „Чака пробив“ и картите по Kullamägi; карето не се рендерира")
    try:
        records = [r for cat in (backtest.CATEGORY_ACTION, backtest.CATEGORY_BUYSTOP, backtest.CATEGORY_QM, backtest.CATEGORY_GLB_WISH_HIGH)
                   for r in backtest.book_records(cat, statuses=("pending", "open", "trailing"))]
    except Exception as e:
        print(f"[preopen] книгите не се прочетоха: {type(e).__name__}: {e}")
        records = []
    universe, universe_note = [], None                                             # 04.11.2026 (С3): банерът за универса (както сутрешният бриф — screener.LAST_UNIVERSE_SOURCES)
    try:
        universe = screener.build_universe()
        bad = [v for v in screener.LAST_UNIVERSE_SOURCES.values() if not v.get("ok")]
        if bad:
            universe_note = "универсът е непълен — " + "; ".join(f"{v.get('name')}: {v.get('reason')}" for v in bad)
    except Exception as e:
        universe_note = f"универсът не се зареди ({type(e).__name__}) — проверени са само картите, книгите и наблюдаваните"
        print(f"::warning::[preopen] {universe_note}: {e}")
    res = run(now, brief=brief, records=records, watched=watch_monitor.load_watch_list(), universe=universe,
              name_lookup=lambda t: watch_monitor.load_watch_names().get(t), universe_note=universe_note)
    res["email"] = prev.get("email") or {"sent": False}
    if has_news(res) and not res["email"].get("sent"):
        subj = (f"Преди отварянето · {day[8:10]}.{day[5:7]} — " + ", ".join(x for x in (f"{len(res['gaps'])} гапа" if res["gaps"] else "",
                f"{len(res['levels'])} нива" if res["levels"] else "", f"{len(res['watch'])} наблюдавани" if res["watch"] else "") if x))
        ok = emailer.send_brief(email_html(res), subj)
        res["email"] = {"sent": bool(ok), "subject": subj, "at_utc": now.strftime("%H:%M")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if brief:
        try:
            brief["preopen"] = res
            page = config.DOCS_DIR / "index.html"
            gen = morning_generated(page.read_text(encoding="utf-8") if page.exists() else None)
            render.render_dashboard(brief, publish=False, as_of=dt.date.fromisoformat(day), generated=gen)   # само docs/index.html — карето стои до следващия сутрешен бриф
        except Exception as e:
            print(f"::warning::[preopen] страницата не се рендерира: {type(e).__name__}: {e}")
    if not res["ok"]:
        print(f"::error::[preopen] премаркетът не се изтегли ({'; '.join(res['notes']) or 'празно'})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
