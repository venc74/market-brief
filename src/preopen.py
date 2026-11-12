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


def premarket_missing_reason(df: pd.DataFrame | None, now_utc) -> str:
    """
    10.11.2026 (т. 2): защо premarket_point() дава None — за реда „няма премаркет цена (Yahoo): …“ при сутрешен EP кандидат. Същите условия като
    premarket_point (редовният бар на предишната сесия, премаркет бар днес преди now и преди 09:30 Ню Йорк). Чиста функция.
    """
    from src import sessions
    if df is None or len(df) == 0 or "Close" not in df:
        return "Yahoo не върна 5-минутни бари"
    now = _ny(now_utc)
    ix = pd.DatetimeIndex(df.index)
    ix = (ix.tz_localize("UTC") if ix.tz is None else ix).tz_convert(NY)
    mins = ix.hour * 60 + ix.minute
    today, prev = now.date(), sessions.prev_session(now.date())
    if len(df[(ix.date == prev) & (mins >= OPEN_MIN) & (mins < CLOSE_MIN)]["Close"].dropna()) == 0:
        return f"няма бар от редовната сесия на {prev:%d.%m}"
    if len(df[(ix.date == today) & (mins < OPEN_MIN) & (ix < now)]["Close"].dropna()) == 0:
        return f"няма премаркет бари днес до {now:%H:%M} Ню Йорк"
    return "непозната причина"


def ep_morning(brief: dict | None, pts: dict, frames5: dict | None, shown: list[dict], now_utc) -> list[dict]:
    """
    10.11.2026 (т. 2, SANM 10.11): всеки сутрешен EP кандидат (brief["qm_ep"]["rows"]), който НЕ е сред гаповете в карето, остава с ред — не изпада тихо.
    С премаркет цена → гапът сега и защо не е в гаповете (под прага / малко бари / извън първите PREOPEN_MAX_ROWS); без → „няма премаркет цена (Yahoo): <причината>“.
    → [{ticker, ah_gap_pct, pm_gap_pct?, pm_price?, prev_close?, pm_last_ny?, no_price, why, text}]. Чиста функция.
    """
    seen = {g.get("ticker") for g in shown or []}
    out = []
    for r in ((brief or {}).get("qm_ep") or {}).get("rows") or []:
        t = r.get("ticker")
        if not t or t in seen:
            continue
        seen.add(t)
        ah = r.get("gap_pct")
        row = {"ticker": t, "ah_gap_pct": round(ah, 2) if ah is not None else None, "no_price": False}
        p = (pts or {}).get(t)
        if p:
            g = (p["pm_price"] / p["prev_close"] - 1) * 100 if p.get("prev_close") else None
            row.update(pm_gap_pct=round(g, 2) if g is not None else None, pm_price=p["pm_price"], prev_close=p["prev_close"], pm_last_ny=p["pm_last_ny"])
            if g is None or g < config.PREOPEN_GAP_PCT:
                row["why"] = f"под прага +{config.PREOPEN_GAP_PCT:g}%"
            elif p["pm_bars"] < config.PREOPEN_MIN_PM_BARS:
                row["why"] = f"само {p['pm_bars']} бара в премаркета (< {config.PREOPEN_MIN_PM_BARS})"
            else:
                row["why"] = f"извън първите {config.PREOPEN_MAX_ROWS} гапа"
            pm = f"премаркет {g:+.1f}%" if g is not None else "премаркет"
            what = f"{pm} (${p['pm_price']:.2f} в {p['pm_last_ny']} Ню Йорк; затваряне ${p['prev_close']:.2f}) — {row['why']}"
        else:
            row["no_price"] = True
            row["why"] = premarket_missing_reason((frames5 or {}).get(t), now_utc)
            what = f"няма премаркет цена (Yahoo): {row['why']}"
        row["text"] = (f"сутрин AH {ah:+.1f}% → " if ah is not None else "") + what
        out.append(row)
    return out


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


def gaps_all(gaps: list[dict], shown: list[dict]) -> list[dict]:
    """
    12.11.2026 (т. 2, CRWV 11.11): всички гапове ≥ PREOPEN_GAP_PCT (и извън първите PREOPEN_MAX_ROWS) в компактен вид за дневника на EP; за показаните — официалното
    затваряне и гапът спрямо него от ep_rows (qm_ep.enrich_gappers), пренебрегването. Чиста функция.
    """
    by = {g["ticker"]: g for g in shown or []}
    out = []
    for g in gaps or []:
        e = by.get(g["ticker"]) or {}
        pc, gp = e.get("prev_close") or g["prev_close"], e.get("gap_pct") if e.get("gap_pct") is not None else g["gap_pct"]
        out.append({"ticker": g["ticker"], "session": g["session"], "prev_close": round(float(pc), 4), "pm_price": round(float(g["pm_price"]), 4), "gap_pct": round(float(gp), 2),
                    "pm_bars": g.get("pm_bars"), "pm_last_ny": g.get("pm_last_ny"), "neglect": e.get("neglect"), "ret63_pct": e.get("ret63_pct")})
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


def neglect_label(ret63_pct, neglect) -> str | None:
    """11.11.2026 (т. 3): „сринала се, не забравена“ / „пренебрегнат“ / „не е пренебрегнат“ — qm_ep.neglect_label."""
    from src import qm_ep
    return qm_ep.neglect_label(ret63_pct, neglect)


def _pending_deals() -> set:
    """11.11.2026 (т. 1): висящите сделки (data/deal_state.json) — graceful: провал → празно."""
    try:
        from src import spinoff_watch
        return set(spinoff_watch.pending_tickers())
    except Exception as e:
        print(f"[preopen] висящите сделки не се прочетоха: {type(e).__name__}: {e}")
        return set()


def red_8k(filings: list | None) -> list[str]:
    """10.11.2026 (т. 1): червеното предупреждение за 8-K т. 4.02 — qm_ep.red_8k."""
    from src import qm_ep
    return qm_ep.red_8k(filings)


def qm_ep_sources_note(row: dict) -> str | None:
    """04.11.2026 (С1): „8-K: не се провери (…) · заглавия: не се провериха (…)“ — qm_ep.sources_note."""
    from src import qm_ep
    return qm_ep.sources_note(row)


# 10.11.2026 (т. 3): заглавие за икономически данни — по вида; измерено върху 2 923 реални заглавия на Reuters и AP (Google News, 01.10–10.11.2026):
# 23 попадения, всички за американски данни (или очакването им), нито едно странично; чуждите данни (UK, Индия, Китай, Бразилия) — вън.
_ECON_RX = {
    "CPI": r"\bCPI\b|consumer[- ]prices?\b|\binflation (data|report|figures|numbers|reading|print)\b"
           r"|\binflation (ran|runs|rose|rises|heats? up|heated up|cool(s|ed)|eas(es|ed)|accelerat\w+|slow(s|ed)|jump(s|ed)|worsen(s|ed)|tick(s|ed))\b",
    "PPI": r"\bPPI\b|producer[- ]prices?\b|wholesale (prices|inflation)\b",
    "заетост": r"\bpayrolls?\b|\bnonfarm\b|\bjobs (report|data|numbers|figures)\b|\bjobless\b|\bunemployment (rate|claims|benefits|ticks|rises|rose|falls|fell|drops?|climbs?)\b"
               r"|\binitial claims\b|\bjob (growth|gains)\b|\bhiring (slows|slowed|picks up|picked up|surges|surged|jumps|jumped|rebounds)\b",
    "JOLTS": r"\bJOLTS\b|\bjob (openings|postings)\b",
    "ISM": r"\bISM\b|\bPMI\b|purchasing managers|\b(factory|services) activity\b",
    "retail sales": r"\bretail sales\b",
}
_ECON_FOREIGN = (r"\b(UK|U\.K\.|Britain|British|euro ?zone|Europe\w*|ECB|Lagarde|German\w*|France|French|Ital\w+|Spain|Spanish|Japan\w*|BOJ|China|Chinese|India\w*|RBI|"
                 r"Brazil\w*|Canad\w+|Australia\w*|Mexic\w*|Russia\w*|Turk\w+|Korea\w*|Swiss|Sweden|Swedish|Norw\w+|Global|world)\b")
_ECON_US = r"\bUS\b|\bU\.S\.|\bAmerica\w*|\bWall St|\bFed\b|\bS&P\b|\bNasdaq\b|\bDow\b|\bTreasur"


def econ_kind(title: str | None) -> str | None:
    """10.11.2026 (т. 3): видът икономически данни в заглавието (CPI / PPI / заетост / JOLTS / ISM / retail sales) или None; чужда държава без US белег → None. Чиста функция."""
    import re
    t = title or ""
    for k, rx in _ECON_RX.items():
        if re.search(rx, t, re.I):
            return None if re.search(_ECON_FOREIGN, t, re.I) and not re.search(_ECON_US, t, re.I) else k
    return None


def econ_since(now_utc) -> pd.Timestamp:
    """Началото на прозореца — днес PREOPEN_ECON_SINCE_NY (08:30) Ню Йорк, като UTC."""
    now = _ny(now_utc)
    h, m = (int(x) for x in config.PREOPEN_ECON_SINCE_NY.split(":"))
    return now.normalize().replace(hour=h, minute=m).tz_convert("UTC")


def _title_source(item: dict) -> tuple[str, str]:
    """Google News слага издателя в края („… - Reuters“, „… - AP News“) — заглавието без него и издателят; иначе заглавието и името на фийда."""
    t, src = str(item.get("title") or "").strip(), str(item.get("source") or "")
    if " - " in t:
        head, tail = t.rsplit(" - ", 1)
        if tail.strip() and len(tail.split()) <= 3 and tail.strip().split()[0].lower() in src.lower():
            return head.strip(), tail.strip()
    return t, src


def econ_headlines(items: list[dict], now_utc, max_n: int | None = None) -> list[dict]:
    """
    10.11.2026 (т. 3): заглавията за икономически данни в прозореца [econ_since, now] — дословно (без издателя в края при Google News), с източника и часа
    (Ню Йорк и Берлин), първите по време (първото е обикновено самото съобщение); едно и също заглавие от два фийда — веднъж. Без AI. Чиста функция.
    → [{title, source, kind, published, time_ny, time_berlin, link?}]
    """
    since, now = econ_since(now_utc), pd.Timestamp(now_utc).tz_convert("UTC") if pd.Timestamp(now_utc).tzinfo else pd.Timestamp(now_utc).tz_localize("UTC")
    rows, seen = [], set()
    for it in items or []:
        try:
            ts = pd.Timestamp(it.get("published")).tz_convert("UTC") if it.get("published") else None
        except Exception:
            ts = None
        if ts is None or ts < since or ts > now:
            continue
        title, src = _title_source(it)
        k = econ_kind(title)
        key = title.lower()[:90]
        if not k or key in seen:
            continue
        seen.add(key)
        row = {"title": title, "source": src, "kind": k, "published": ts.strftime("%Y-%m-%dT%H:%MZ"),
               "time_ny": ts.tz_convert(NY).strftime("%H:%M"), "time_berlin": ts.tz_convert("Europe/Berlin").strftime("%H:%M")}
        if it.get("link"):
            row["link"] = it["link"]
        rows.append(row)
    rows.sort(key=lambda r: r["published"])
    return rows[:max_n or config.PREOPEN_ECON_MAX]


def fetch_econ(now_utc) -> dict:
    """10.11.2026 (т. 3): заглавията от config.NEWS_RSS_FEEDS след econ_since (мрежа; всеки фийд в try/except в news_aggregator._fetch_rss) → {"items", "feeds", "feeds_empty"}."""
    from src import news_aggregator
    since = econ_since(now_utc).timestamp()
    items, empty = [], []
    for src, url in config.NEWS_RSS_FEEDS.items():
        got = news_aggregator._fetch_rss(url, src, 2, limit=100, since_ts=since)
        (items.extend(got) if got else empty.append(src))
    return {"items": items, "feeds": len(config.NEWS_RSS_FEEDS), "feeds_empty": empty}


def econ_block(fetched: dict | None, now_utc) -> tuple[list[dict], str | None]:
    """Заглавията и бележка при провал: нито един фийд не върна нищо след 08:30 Ню Йорк → „не се провериха“ (≠ „няма“)."""
    f = fetched or {}
    if f.get("feeds") and len(f.get("feeds_empty") or []) >= f["feeds"]:
        return [], f"нито един от {f['feeds']} фийда не върна заглавия след {config.PREOPEN_ECON_SINCE_NY} Ню Йорк"
    return econ_headlines(f.get("items") or [], now_utc), None


def econ_line(x: dict) -> str:
    """„„US consumer prices rise above expectations in October“ · Reuters · 08:46 Ню Йорк (14:46 Берлин)“ — страницата и имейлът."""
    return f"„{x['title']}“ · {x['source']} · {x['time_ny']} Ню Йорк ({x['time_berlin']} Берлин)"


# ──────────────────────────────────────────────────────────────────────────
# 12.11.2026 (т. 1): „Пазарът преди отварянето“ — фючърсите ES / NQ и компаниите с тегло > 2% в S&P 500 с гап ≥ ±3% (в двете посоки)
# ──────────────────────────────────────────────────────────────────────────
_XLSX = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_MON = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def parse_spy_holdings(data: bytes) -> dict:
    """
    Дневните позиции на SPY (SSGA, xlsx) → {"as_of": "2026-11-11", "rows": [{"ticker", "name", "cusip", "weight"}]}. Без openpyxl: xlsx е zip с XML (xl/sharedStrings.xml +
    xl/worksheets/sheet1.xml). Заглавният ред е този с „Ticker“ и „Weight“; редове без тикър или без число за тегло (бележките под таблицата) отпадат. Тикърът — във вида на
    Yahoo („BRK.B“ → „BRK-B“). Чиста функция; непознат формат → ValueError / KeyError.
    """
    import io
    import re
    import zipfile
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(io.BytesIO(data))
    try:
        shared = ["".join(t.text or "" for t in si.iter(_XLSX + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_XLSX + "si")]
    except KeyError:
        shared = []
    table = []
    for r in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(_XLSX + "row"):
        row = {}
        for c in r.findall(_XLSX + "c"):
            col = re.match(r"[A-Z]+", c.get("r") or "")
            v = c.find(_XLSX + "v")
            if v is not None and v.text is not None:
                x = shared[int(v.text)] if c.get("t") == "s" else v.text
            else:
                t = c.find(f"{_XLSX}is/{_XLSX}t")
                x = t.text if t is not None else None
            if col and x is not None and str(x).strip():
                row[col.group(0)] = str(x).strip()
        table.append(row)
    as_of = None
    for row in table[:10]:
        for v in row.values():
            m = re.search(r"As of (\d{1,2})-([A-Za-z]{3})-(\d{4})", v)
            if m and m.group(2).title() in _MON:
                as_of = dt.date(int(m.group(3)), _MON[m.group(2).title()], int(m.group(1))).isoformat()
    hdr = next((i for i, row in enumerate(table) if "Ticker" in row.values() and "Weight" in row.values()), None)
    if hdr is None:
        raise ValueError("няма заглавен ред с Ticker и Weight")
    cols = {v: k for k, v in table[hdr].items()}
    out = []
    for row in table[hdr + 1:]:
        t = row.get(cols["Ticker"])
        try:
            w = float(row.get(cols["Weight"]))
        except (TypeError, ValueError):
            continue
        if not t or t == "-":
            continue
        out.append({"ticker": t.replace(".", "-").upper(), "name": row.get(cols.get("Name", ""), ""), "cusip": row.get(cols.get("Identifier", ""), ""), "weight": w})
    if not out:
        raise ValueError("няма позиции")
    return {"as_of": as_of, "rows": out}


def company_weights(rows: list[dict], min_pct: float | None = None) -> list[dict]:
    """
    Теглото по КОМПАНИЯ — класовете на една компания заедно (емитентът = първите 6 знака на CUSIP: GOOGL 02079K305 + GOOG 02079K107 = Alphabet). Над min_pct
    (config.PREOPEN_MEGA_WEIGHT_PCT) → [{"ticker" (класът с по-голямото тегло), "tickers", "name", "weight"}], по тегло. Чиста функция.
    """
    min_pct = config.PREOPEN_MEGA_WEIGHT_PCT if min_pct is None else min_pct
    by: dict[str, list[dict]] = {}
    for r in rows or []:
        by.setdefault((r.get("cusip") or "")[:6] or r["ticker"], []).append(r)
    out = []
    for grp in by.values():
        grp = sorted(grp, key=lambda r: -r["weight"])
        w = sum(r["weight"] for r in grp)
        if w > min_pct:
            out.append({"ticker": grp[0]["ticker"], "tickers": [r["ticker"] for r in grp], "name": grp[0].get("name") or grp[0]["ticker"], "weight": round(w, 2)})
    return sorted(out, key=lambda x: -x["weight"])


def last_weights(day: str | None, folder=None) -> dict | None:
    """Последните записани тегла (data/preopen/<дата>.json, market.weights) от ден ПРЕДИ day — резервът, когато днес SSGA не отговори. Нищо → None."""
    d = pathlib.Path(folder or config.DATA_DIR / "preopen")
    try:
        files = sorted(d.glob("*.json"), reverse=True)
    except Exception:
        return None
    for f in files:
        if day and f.stem >= day:
            continue
        try:
            w = (json.loads(f.read_text(encoding="utf-8")).get("market") or {}).get("weights") or {}
            if w.get("companies"):
                return {k: w[k] for k in ("as_of", "source", "companies") if k in w}
        except Exception:
            continue
    return None


def fetch_weights(day: str | None = None, get=None, folder=None) -> dict:
    """
    Теглата (мрежа): позициите на SPY от SSGA (config.SPY_HOLDINGS_URL) → {"as_of", "source", "companies"}. Провал → последните записани (last_weights) с "stale" и
    причината; без тях → {"error": причината}. Не вдига.
    """
    try:
        if get is None:
            import requests
            r = requests.get(config.SPY_HOLDINGS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            r.raise_for_status()
            data = r.content
        else:
            data = get(config.SPY_HOLDINGS_URL)
        p = parse_spy_holdings(data)
        return {"as_of": p["as_of"], "source": "позициите на SPY от SSGA", "companies": company_weights(p["rows"])}
    except Exception as e:
        why = f"SSGA: {type(e).__name__}"
        print(f"[preopen] теглата в S&P 500 не се изтеглиха: {type(e).__name__}: {e}")
    prev = last_weights(day, folder)
    return {**prev, "stale": True, "error": why} if prev else {"error": why}


def fetch_market(symbols: list[str]) -> dict:
    """
    5-минутни бари с премаркет за фючърсите и големите компании — ОТДЕЛНО от универса (LAST_FETCH и покритието не се пипат); 5 дни, защото фючърсите търгуват почти
    денонощно и след уикенда „предишната сесия“ е петък. → {символ: кадър}.
    """
    import yfinance as yf
    out = {}
    data = yf.download(list(symbols), period="5d", interval="5m", prepost=True, group_by="ticker", progress=False, threads=True, auto_adjust=False)
    for t in symbols:
        try:
            df = (data[t] if isinstance(data.columns, pd.MultiIndex) else data).dropna(subset=["Close"])
            if len(df):
                out[t] = df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception:
            continue
    return out


def _num(x: float, nd: int = 2) -> str:
    return f"{x:,.{nd}f}".replace(",", " ")


def market_block(frames: dict, weights: dict | None, now_utc, fetch_error: str | None = None) -> dict:
    """
    Фючърсите (config.PREOPEN_FUTURES) — промяната спрямо 16:00 Ню Йорк на предишната сесия (последният 5-минутен бар на редовната сесия, като при акциите — premarket_point);
    компаниите с тегло > PREOPEN_MEGA_WEIGHT_PCT — с гап ≥ ±PREOPEN_MEGA_GAP_PCT (в двете посоки), другите — изброени като „под“. → {"futures", "futures_missing", "mega",
    "mega_quiet", "mega_missing", "weights", "session", "text"} — "text" са готовите изречения за карето и имейла (едно място). Чиста функция.
    """
    now = _ny(now_utc)
    out = {"futures": [], "futures_missing": [], "mega": [], "mega_quiet": [], "mega_missing": [], "weights": weights or {}, "session": None}
    for sym, label in config.PREOPEN_FUTURES.items():
        p = premarket_point((frames or {}).get(sym), now)
        if not p or not p["prev_close"]:
            out["futures_missing"].append(label)
            continue
        out["session"] = out["session"] or p["session"]
        out["futures"].append({"symbol": sym, "label": label, "price": round(p["pm_price"], 2), "prev_close": round(p["prev_close"], 2),
                               "chg_pct": _pct(p["pm_price"], p["prev_close"]), "last_ny": p["pm_last_ny"]})
    for c in (weights or {}).get("companies") or []:
        p = premarket_point((frames or {}).get(c["ticker"]), now)
        if not p or not p["prev_close"]:
            out["mega_missing"].append(c["ticker"])
            continue
        out["session"] = out["session"] or p["session"]
        g = _pct(p["pm_price"], p["prev_close"])
        row = {**c, "gap_pct": g, "pm_price": round(p["pm_price"], 2), "prev_close": round(p["prev_close"], 2), "pm_last_ny": p["pm_last_ny"]}
        (out["mega"] if abs(g) >= config.PREOPEN_MEGA_GAP_PCT else out["mega_quiet"]).append(row)
    out["mega"].sort(key=lambda x: -abs(x["gap_pct"]))
    out["text"] = market_text(out, fetch_error)
    return out


def market_text(m: dict, fetch_error: str | None = None) -> list[str]:
    """Изреченията за реда „Пазарът преди отварянето“ (каре и имейл). Чиста функция."""
    s = m.get("session")
    when = f" на {s[8:10]}.{s[5:7]}" if s else ""
    lines = []
    fut = [f"{f['label']} {f['chg_pct']:+.2f}% ({_num(f['price'])} в {f['last_ny']})" for f in m.get("futures") or []]
    if fut:
        lines.append("Фючърси: " + ", ".join(fut) + f" — спрямо 16:00 Ню Йорк{when}."
                     + (f" Без данни: {', '.join(m['futures_missing'])}." if m.get("futures_missing") else ""))
    elif m.get("futures_missing"):
        lines.append(f"Фючърсите ({', '.join(m['futures_missing'])}) — без цена в премаркета (Yahoo{': ' + fetch_error if fetch_error else ''}).")
    w = m.get("weights") or {}
    thr, gap = f"{config.PREOPEN_MEGA_WEIGHT_PCT:g}", f"{config.PREOPEN_MEGA_GAP_PCT:g}"
    if not w.get("companies"):
        lines.append(f"Компаниите с тегло > {thr}% в S&P 500 не са проверени — теглата не се изтеглиха ({w.get('error') or 'няма данни'}).")
        return lines
    wa = w.get("as_of")
    src = f"по {w.get('source') or 'SPY'}" + (f", към {wa[8:10]}.{wa[5:7]}" if wa else "") + (f"; днешните не се изтеглиха — {w['error']}" if w.get("stale") else "")
    name = lambda x: x["ticker"] + (f" (с {', '.join(t for t in x['tickers'] if t != x['ticker'])})" if len(x.get("tickers") or []) > 1 else "")
    head = f"С тегло > {thr}% в S&P 500 ({src})"
    if m.get("mega"):
        lines.append(head + f" и гап ≥ ±{gap}%: " + "; ".join(
            f"{name(x)} {x['gap_pct']:+.1f}% (${x['pm_price']:.2f}; затваряне ${x['prev_close']:.2f}; тегло {x['weight']:.1f}%)" for x in m["mega"]) + ".")
        if m.get("mega_quiet"):
            lines.append(f"Под ±{gap}%: " + ", ".join(name(x) for x in m["mega_quiet"]) + ".")
    elif m.get("mega_quiet"):
        lines.append(head + f": няма гап ≥ ±{gap}% (" + ", ".join(f"{name(x)} {x['gap_pct']:+.1f}%" for x in m["mega_quiet"]) + ").")
    if m.get("mega_missing"):
        lines.append(f"Без цена в премаркета: {', '.join(m['mega_missing'])}" + (f" (Yahoo: {fetch_error})" if fetch_error else "") + ".")
    return lines


def market_section(market_fn, weights_fn, now_utc, day: str) -> dict:
    """Теглата → символите (фючърсите + компаниите) → бари → market_block. Провал на тегленето на бари → редът казва „без цена“, не изчезва."""
    weights = weights_fn(day) if weights_fn else None
    syms = list(config.PREOPEN_FUTURES) + [c["ticker"] for c in (weights or {}).get("companies") or []]
    frames, err = {}, None
    try:
        frames = market_fn(syms) if market_fn else {}
    except Exception as e:
        err = type(e).__name__
        print(f"[preopen] фючърсите и големите компании не се изтеглиха: {type(e).__name__}: {e}")
    return market_block(frames, weights, now_utc, err)


def has_news(res: dict) -> bool:
    return bool(res.get("gaps") or res.get("levels") or res.get("watch") or res.get("ep_morning") or res.get("econ"))      # 10.11.2026 (т. 2–3): и сутрешните EP кандидати, и данните


def qm_ep_sector_bounce(gaps: list[dict]) -> list[dict]:
    """06.11.2026 (т. 10): етикетът „секторен отскок“ върху всички гапове на деня (и над PREOPEN_MAX_ROWS). Graceful: провал → без етикет."""
    try:
        from src import qm_ep
        return qm_ep.sector_bounce([g["ticker"] for g in gaps or []])
    except Exception as e:
        print(f"[preopen] секторен отскок: {type(e).__name__}: {e}")
        return []


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
    if (res.get("market") or {}).get("text"):                                      # 12.11.2026 (т. 1)
        parts.append(f"<div style='margin-top:8px'><b>Пазарът преди отварянето:</b> {e(' '.join(res['market']['text']))}</div>")
    if res.get("econ"):                                                             # 10.11.2026 (т. 3)
        parts.append(f"<div style='margin-top:10px'><b>Икономически данни след {config.PREOPEN_ECON_SINCE_NY} Ню Йорк</b> <span style='color:#6b7280'>(заглавията дословно, без AI)</span></div>")
        parts.append(li([e(econ_line(x)) for x in res["econ"]]))
    if res.get("econ_error"):
        parts.append(f"<div style='margin:4px 0;color:#92400e'>Заглавията за икономически данни не се провериха ({e(res['econ_error'])}) — празното НЕ значи, че няма.</div>")
    if res.get("gaps"):
        parts.append("<div style='margin-top:10px'><b>EP — гапове ≥ +%g%% в премаркета</b></div>" % config.PREOPEN_GAP_PCT)
        parts += [f"<div style='margin:4px 0;color:#92400e'>{e(x['text'])}</div>" for x in res.get("sector_bounce") or []]      # 06.11.2026 (т. 10)
        parts.append(li([f"<b>{e(g['ticker'])}</b> {g['gap_pct']:+.1f}% (${g['pm_price']:.2f}; затваряне ${g['prev_close']:.2f})"
                         + (f" · обем в премаркета {g['pm_volume']:,.0f}".replace(",", " ") if g.get("pm_volume") else "")
                         + (f" · {neglect_label(g['ret63_pct'], g.get('neglect'))} (3 мес. {g['ret63_pct']:+.0f}%)" if g.get("ret63_pct") is not None else "")      # 11.11.2026 (т. 3)
                         + "".join(f"<br><span style='color:#374151'>{e(f['text'])}</span>" for f in g.get("filings_8k") or [])
                         + "".join(f"<br><b style='color:#991b1b'>{e(x)}</b>" for x in red_8k(g.get("filings_8k")))      # 10.11.2026 (т. 1)
                         + (f"<br><span style='color:#374151'>„{e(g['headline']['title'])}“" + (f" · {e(g['headline']['source'])}" if g["headline"].get("source") else "") + "</span>"
                            if g.get("headline") else "")
                         + (f"<br><span style='color:#92400e'>{e(qm_ep_sources_note(g))}</span>" if qm_ep_sources_note(g) else "")      # 04.11.2026 (С1)
                         for g in res["gaps"]]))
    if res.get("ep_morning"):                                                       # 10.11.2026 (т. 2, SANM)
        parts.append("<div style='margin-top:10px'><b>Сутрешните EP кандидати извън гаповете</b></div>")
        parts.append(li([f"<b>{e(x['ticker'])}</b> " + (f"<span style='color:#92400e'>{e(x['text'])}</span>" if x.get("no_price") else e(x["text"])) for x in res["ep_morning"]]))
    if res.get("ep_morning_error"):
        parts.append(f"<div style='margin:4px 0;color:#92400e'>Сутрешните EP кандидати не се провериха ({e(res['ep_morning_error'])}).</div>")
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
        universe: list[str] | None = None, daily_fn=None, filings_fn=None, headlines_fn=None, name_lookup=None, universe_note: str | None = None,
        econ_fn=None, exclude: set | None = None, market_fn=None, weights_fn=None) -> dict:
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
        ex = set(exclude or ())                                                        # 11.11.2026 (т. 1): висящите сделки — вън от гаповете, нивата и сутрешните EP редове
        if ex:
            waiting = [c for c in waiting if c.get("ticker") not in ex]
            qm_cards = [c for c in qm_cards if c.get("ticker") not in ex]
            records = [r for r in records or [] if r.get("ticker") not in ex]
            res["excluded_deals"] = sorted(ex)
        extra = [c.get("ticker") for c in waiting + qm_cards] + [r.get("ticker") for r in records or []] + list(watched or [])
        extra += [r.get("ticker") for r in (brief.get("qm_ep") or {}).get("rows") or []]      # 10.11.2026 (т. 2): сутрешните EP кандидати — винаги в заявката
        tickers = list(dict.fromkeys([t for t in list(universe or []) + extra if t and (t not in ex or t in (watched or []))]))
        res["universe_n"] = len([t for t in dict.fromkeys(universe or []) if t not in ex])          # 11.11.2026 (т. 2): универсът отделно от добавените (наблюдаваните и др.)
        LAST_FETCH.clear()
        if frames5 is None:
            frames5 = (fetch5 or fetch_5m)(tickers)
        pts, gaps, diag = scan(frames5, now)
        gaps = [g for g in gaps if g["ticker"] not in ex]
        res["diag"] = {**diag, "requested": len(tickers)}
        res["coverage"] = coverage(res["diag"], dict(LAST_FETCH), universe_note)          # 04.11.2026 (С3): „премаркет за N от M“ и „частично“
        res["coverage"].update(universe=res["universe_n"], extra=len(tickers) - res["universe_n"])      # 11.11.2026 (т. 2)
        res["session"] = next(iter(pts.values()))["session"] if pts else None
        res["ok"] = bool(pts)
        res["gaps"] = ep_rows(gaps, daily_fn=daily_fn, filings_fn=filings_fn, headlines_fn=headlines_fn, name_lookup=name_lookup, now_utc=now.tz_convert("UTC").to_pydatetime())
        res["sector_bounce"] = qm_ep_sector_bounce(gaps)                               # 06.11.2026 (т. 10)
        res["gaps_all"] = gaps_all(gaps, res["gaps"])                                 # 12.11.2026 (т. 2): всички гапове ≥ прага — за дневника на EP (qm_ep.preopen_gaps)
        try:                                                                           # 10.11.2026 (т. 2, SANM): сутрешните EP кандидати извън гаповете — с ред, не изпадат тихо
            res["ep_morning"] = [x for x in ep_morning(brief, pts, frames5, res["gaps"], now) if x["ticker"] not in ex]
        except Exception as e:
            res["ep_morning"], res["ep_morning_error"] = [], f"{type(e).__name__}"
            print(f"[preopen] сутрешните EP кандидати: {type(e).__name__}: {e}")
        res["levels"] = level_checks(pts, waiting, qm_cards, records or [], res["date"])
        res["watch"] = watch_gaps(pts, watched or [], watch_closes(brief))
        res["volume_note"] = volume_note(res)
        if econ_fn is not None:                                                        # 10.11.2026 (т. 3): заглавията за данните; main подава fetch_econ, тестовете — готови
            try:
                res["econ"], err = econ_block(econ_fn(now.tz_convert("UTC").to_pydatetime()), now)
                if err:
                    res["econ_error"] = err
            except Exception as e:
                res["econ"], res["econ_error"] = [], f"{type(e).__name__}"
                print(f"[preopen] заглавията за данните: {type(e).__name__}: {e}")
    except Exception as e:
        res["notes"].append(f"{type(e).__name__}: {e}")
        print(f"[preopen] пропадна: {type(e).__name__}: {e}")
    if market_fn is not None or weights_fn is not None:                                # 12.11.2026 (т. 1): main подава fetch_market / fetch_weights, тестовете — готови
        try:
            res["market"] = market_section(market_fn, weights_fn, now, res["date"])
        except Exception as e:
            res["market"] = {"error": type(e).__name__, "text": [f"Фючърсите и големите компании не се провериха ({type(e).__name__})."]}
            print(f"[preopen] пазарът преди отварянето: {type(e).__name__}: {e}")
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
        universe = screener.scan_universe(day)                                     # 11.11.2026 (т. 1–2): сутрешният универс за деня, без висящите сделки
        if screener.LAST_DAY_UNIVERSE.get("source") == "built":
            print(f"::warning::[preopen] записаният универс за {day} липсва — построен наново от Wikipedia (може да се разминава със сутрешния)")
        bad = [v for v in screener.LAST_UNIVERSE_SOURCES.values() if not v.get("ok")]
        if bad:
            universe_note = "универсът е непълен — " + "; ".join(f"{v.get('name')}: {v.get('reason')}" for v in bad)
    except Exception as e:
        universe_note = f"универсът не се зареди ({type(e).__name__}) — проверени са само картите, книгите и наблюдаваните"
        print(f"::warning::[preopen] {universe_note}: {e}")
    res = run(now, brief=brief, records=records, watched=watch_monitor.load_watch_list(), universe=universe,
              name_lookup=lambda t: watch_monitor.load_watch_names().get(t), universe_note=universe_note, econ_fn=fetch_econ, exclude=_pending_deals(),
              market_fn=fetch_market, weights_fn=fetch_weights)
    if res.get("coverage") is not None:
        res["coverage"]["universe_source"] = screener.LAST_DAY_UNIVERSE.get("source")      # 11.11.2026 (т. 2): "cache" — същият като сутрешния
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
