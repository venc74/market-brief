"""
Рендериране: dashboard HTML (docs/index.html за GitHub Pages)
+ архивно копие docs/archive/YYYY-MM-DD.html + имейл HTML.
"""
from __future__ import annotations
import datetime as dt
import html as _html
import re
from jinja2 import Environment, FileSystemLoader

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config
from src import names
from src import watchlist_exits
from src import setup_rules
from src import sector_claims
from src import qm_breakout
from src import enrich as enrich_mod

WEEKDAYS_BG = ["понеделник", "вторник", "сряда", "четвъртък",
               "петък", "събота", "неделя"]

# 2026-10-03 (пакет 4а т.8): autoescape=True. Външен текст (RSS заглавия, AI текст, имена на компании, причини)
# влиза в HTML — без escape един "<" или кавичка в заглавие чупи страницата или атрибут (title="..."), а
# злонамерен текст би се изпълнил. Проверено срещу всичките 78 реални брифа (шаблонът се прекомпилира при всяко
# превключване): таговете, атрибутите и видимият текст са идентични с и без escape — данните никъде не носят
# умишлен HTML, шаблонът не ползва |safe. (Реалните AI текстове вече съдържат "<1%" — без escape това беше
# невалиден HTML, който браузърът прощаваше по късмет.)
env = Environment(loader=FileSystemLoader(config.ROOT / "templates"),
                  autoescape=True)
env.filters["field_words"] = sector_claims.field_words     # 19.10.2026 (т. 18): сурови имена на полета в прозата на модела → думи
env.filters["horizon_text"] = sector_claims.horizon_text   # 19.10.2026 (т. 18): хоризонтът на модела ([4, 12], "2-6", 4) → текст
env.globals["book_plan_note"] = setup_rules.book_plan_note   # 19.10.2026 (т. 18б): планът на книгата, когато се различава от днешния на картата
def _red_8k(filings):
    """10.11.2026 (т. 1, AAON 09.11): червеното предупреждение за 8-K т. 4.02 — qm_ep.red_8k (вносът е тук, без цикъл при зареждането)."""
    from src import qm_ep
    return qm_ep.red_8k(filings)


env.globals["red_8k"] = _red_8k


def _big_sell_text(b):
    """10.11.2026 (т. 5): „продава ≥25% от дела си: …“ — watch_monitor.big_sell_text."""
    from src import watch_monitor
    return watch_monitor.big_sell_text(b)


env.globals["big_sell_text"] = _big_sell_text


def _neglect_label(ret63_pct, neglect):
    """11.11.2026 (т. 3): „сринала се, не забравена“ под −30% за 3 месеца — qm_ep.neglect_label."""
    from src import qm_ep
    return qm_ep.neglect_label(ret63_pct, neglect)


env.globals["neglect_label"] = _neglect_label
env.filters["cname"] = names.display_name            # 08.10: име на компания за показване — без правни окончания, рязане по граница на дума с «…»
_NAME_LOGGED: set = set()


def cname_t(company, ticker, limit=None, strip=True) -> str:
    """
    17.11.2026 (пакет 1, т. 5): името на компанията за показване до тикъра — никога тикърът втори път („CSX CSX“: „CSX Corporation“ → „CSX“). Името = тикъра или
    липсва → "" (само тикърът) и ред в лога (веднъж на тикър).
    """
    out = names.display_name(company, limit, strip) if company else ""
    if not out or out.strip().upper() == str(ticker or "").upper():
        if ticker and ticker not in _NAME_LOGGED:
            _NAME_LOGGED.add(ticker)
            print(f"[names] {ticker}: " + ("името съвпада с тикъра" if out else "без име") + " — показва се само тикърът")
        return ""
    return out


env.filters["cname_t"] = cname_t




def berlin_clock(now: dt.datetime | None = None) -> tuple[str, str]:
    """
    ("HH:MM", "CET"|"CEST") по берлинско време.

    FIX 2026-10-03 (пакет 2 т.8): страницата казваше "генериран HH:MM CET", но `dt.datetime.now()` е времето на машината —
    на GitHub runner-а UTC (в 79-те архивни страници: 68 са "05:xx CET", а реално е 07:xx CEST), при локално пускане —
    местното. Сега винаги Europe/Berlin, със сезонния етикет (CET зимата, CEST лятото). Ако няма tz база данни
    (zoneinfo без tzdata) — честен резервен вариант: UTC с етикет "UTC", не грешно "CET".
    `now` — за тестове; наивно време се счита за UTC.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo("Europe/Berlin"))
        return local.strftime("%H:%M"), local.tzname() or "CET"
    except Exception as e:
        print(f"[render] Europe/Berlin недостъпна ({type(e).__name__}) — часът е в UTC")
        return now.astimezone(dt.timezone.utc).strftime("%H:%M"), "UTC"


def premarket_note(now: dt.datetime | None = None) -> str:
    """
    Текстът за часа до US pre-market в заглавието (08.10.2026, code-queue): преди беше твърдото "90 мин преди US pre-market", а pre-market започва в 04:00 Ню Йорк (10:00 CEST през лятото,
    09:00 CET в двете седмици, когато САЩ са още на лятно, а Европа вече на зимно време) и брифът излиза около 07:30 берлинско време, т.е. ~2.5 часа преди. Смята се от момента на генериране:
    преди 04:00 ET на същия ден → «2 ч 30 мин до US pre-market (04:00 ET)»; pre-market тече (04:00–09:30 ET) → «US pre-market тече»; след 09:30 ET → празно (текстът няма смисъл).
    Празно и при липса на tz база. `now` — за тестове (наивно време = UTC).
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        ny = now.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        return ""
    open_pm = ny.replace(hour=4, minute=0, second=0, microsecond=0)
    open_rth = ny.replace(hour=9, minute=30, second=0, microsecond=0)
    if ny < open_pm:
        mins = int((open_pm - ny).total_seconds() // 60)
        h, m = divmod(mins, 60)
        return "{} до US pre-market (04:00 ET)".format(f"{h} ч {m} мин" if h else f"{m} мин")
    if ny < open_rth:
        return "US pre-market тече"
    return ""


def _asset(name: str) -> str:
    """Съдържанието на templates/<name> (JS за оразмеряването) — вгражда се в страницата; липсващ файл → празно (страницата работи без оразмеряване)."""
    try:
        return (config.ROOT / "templates" / name).read_text(encoding="utf-8")
    except Exception as e:
        print(f"[render] липсва templates/{name}: {e}")
        return ""


def _ew_html(card: dict) -> str:
    """Предупреждението за отчет (earnings_move) като ред под картата в имейла; без предупреждение → празно."""
    w = (card or {}).get("earnings_warning")
    return f'<br><span style="color:#b45309;font-size:12px">{_e(w["text"])}</span>' if w and w.get("text") else ""


def _corp_html(card: dict) -> str:
    """Маркерът за корпоративно действие (corp_actions) като ред под картата в имейла; без маркер → празно."""
    ca = (card or {}).get("corp_action")
    return f'<br><span style="color:#b45309;font-size:12px">{_e(ca["text"])}</span>' if ca and ca.get("text") else ""


def _spinoff_html(card: dict) -> str:
    """13.10.2026: предупреждението за ПРЕДСТОЯЩО отделяне (spinoff_watch, EDGAR 8-K) като ред под картата в имейла; без предупреждение → празно."""
    sw = (card or {}).get("spinoff_warning")
    return f'<br><span style="color:#b45309;font-size:12px">{_e(sw["text"])}</span>' if sw and sw.get("text") else ""


def _merger_html(card: dict) -> str:
    """21.10.2026: маркерът „цел на придобиване (купувач, дата на обявяване)“ (spinoff_watch, EDGAR 8-K) като ред под картата в имейла; без маркер → празно."""
    mt = (card or {}).get("merger_target")
    return f'<br><span style="color:#b45309;font-size:12px">{_e(mt["text"])}</span>' if mt and mt.get("text") else ""




def _stop_rule_html(plan) -> str:
    """06.11.2026 (пакет 05–06.11, т. 1): „стоп: $X или 8% под цената на влизане — по-високото“ като ред за имейла; стар план — нищо."""
    if not isinstance(plan, dict) or plan.get("stop_rule") != "fill" or not plan.get("stop_basis"):
        return ""
    return f'<br><span style="color:#6b7280;font-size:12px">{_e(plan["stop_basis"][0:1].upper() + plan["stop_basis"][1:])}</span>'


def _lv_warn_html(lv) -> str:
    """Предупрежденията от нивата като редове за имейла (само текст)."""
    return "".join(f'<br><span style="color:#b45309;font-size:12px">⚠ {_e(w)}</span>' for w in ((lv or {}).get("warnings") or []))


def _book_note_html(card: dict) -> str:
    """12.10: потвърден пробив с жив запис в buy-stop книгата — неутралният ред от картата и в имейла (трети преглед, 16.10: EXPD "в buy-stop книгата: отворена от 09.10 по $194.59")."""
    note = (card.get("setup") or {}).get("book_note")
    return f'<br><span style="color:#6b7280;font-size:12px">{_e(note)}</span>' if note else ""


def _watchlist_email_html(watchlist: list[dict]) -> tuple[str, str]:
    """
    Watchlist в имейла (трети преглед, 16.10): както обещава историята (docs/HISTORY.md, 07.10: "Имейлът: само вход, стоп, стоп % и предупрежденията"; 4б: отчетът и в имейла) — до 16.10 имейлът
    даваше само тикърите. Карта с buy-stop → buy-stop, таван, валидност, стоп и стоп %; задействан запис в книгата → текстът на кода; отчет / корпоративно действие / отделяне /
    обратен COT залог / бележка за книгата — както при Action. 30.10.2026 (т. 9–10): (HTML на „Чака пробив“, HTML на „На радара“) — split_canslim, както на страницата;
    редът на радара е „тикър — причината от кода“ (radar_reason) и отчетът.
    """
    cards, compact = split_canslim(watchlist)
    out = ""
    for st in cards:
        setup, lv, ew = st.get("setup") or {}, st.get("levels") or {}, st.get("earnings_warning")
        if setup.get("triggered"):
            txt = f'<span style="color:#0e9f6e">{_e(setup.get("trigger_text"))}</span>'
        elif setup.get("buy_stop") and isinstance(lv.get("stop"), (int, float)):
            valid = setup.get("valid_label") or (f'до {setup["valid_through"][8:10]}.{setup["valid_through"][5:7]}' if setup.get("valid_through") else "")
            txt = (f'Buy-stop ${setup["buy_stop"]:.2f}' + (f' (таван ${setup["max_chase"]:.2f}' + (f', валиден {_e(valid)}' if valid else "") + ")" if setup.get("max_chase") else "")
                   + f' · Stop ${lv["stop"]:.2f} (−{lv.get("stop_pct")}%)' + _stop_rule_html(st.get("plan_preview")) + _lv_warn_html(lv))
            bn = setup_rules.book_plan_note(setup, st.get("plan_preview"), lv)              # 19.10.2026 (т. 18б)
            if bn:
                txt += f'<br><span style="color:#6b7280;font-size:12px">{_e(bn)}</span>'
        else:
            txt = _e((st.get("ai") or {}).get("watchlist_trigger") or setup.get("trigger_text") or "")
        if ew:
            txt += f'<br><span style="color:#b45309;font-size:12px">{_e(ew["text"])}</span>'
        if enrich_mod.no_date(st):                                                    # 06.11.2026 (т. 3)
            txt += f'<br><span style="color:#b45309;font-size:12px">{_e(enrich_mod.NO_DATE_TEXT)}</span>'
        txt += _corp_html(st) + _spinoff_html(st) + _merger_html(st) + _book_note_html(st)
        if st.get("volume_alarm"):                                                    # 17.11.2026 (пакет 2, т. 2): аларма с обем
            txt += f'<br><span style="color:#b45309;font-size:12px">{_e(st["volume_alarm"]["text"])}</span>'
        if is_trend(st):                                                              # 17.11.2026 (пакет 2, т. 1): второто ниво — с етикета
            txt += f'<br><span style="color:#b45309;font-size:12px">Тренд без ръст — {_e(st["tier"].get("label"))} (не е CANSLIM)</span>'
        out += (f'<tr><td style="padding:6px 8px 6px 0;font-family:monospace;font-weight:bold;vertical-align:top;white-space:nowrap">{_e(st.get("ticker"))}</td>'
                f'<td style="padding:6px 0;font-size:12.5px;font-family:monospace">{txt}</td></tr>')
    html = f'<table cellpadding="0" cellspacing="0" style="margin-top:6px">{out}</table>' if out else ' <span style="font-family:monospace">—</span>'
    radar = ' <span style="font-family:monospace">—</span>'
    if compact:
        rows = []
        for r in compact:
            t = f'<b>{_e(r["ticker"])}</b> — {_e(r["reason"])}'
            if r.get("earnings"):
                d = r["earnings"]["date"]
                t += f', отчет {d[8:10]}.{d[5:7]}' + (f' (±{r["earnings"]["pct"]}%)' if r["earnings"].get("pct") is not None else "")
            if r.get("earnings_unknown"):                                             # 06.11.2026 (т. 3)
                t += f' · {enrich_mod.NO_DATE_TEXT}'
            if r.get("spinoff"):
                sp = r["spinoff"]
                t += f', ⚠ отделяне {sp["distribution"][8:10]}.{sp["distribution"][5:7]} (запис {sp["record"][8:10]}.{sp["record"][5:7]})'
            if r.get("merger") and r.get("kind") != "deal":
                mg = r["merger"]
                t += f', ⚠ цел на придобиване ({_e(mg["buyer"])}, {mg["announced"][8:10]}.{mg["announced"][5:7]}.{mg["announced"][:4]})'
            rows.append(t)
        radar = f'<div style="margin-top:4px;font-size:12.5px;color:#6b7280">{" · ".join(rows)}</div>'
    return html, radar


def _futures_line(brief: dict) -> str | None:
    try:
        from src import macro_layer
        return macro_layer.futures_quotes_line(((brief.get("macro") or {}).get("global_signals")))
    except Exception:
        return None


def short_name(ticker: str | None, company: str | None = None, name_map: dict | None = None, limit: int = 26) -> str:
    """
    16.11.2026 (пакет 16.11, т. 14): краткото име след тикъра — „R · Ryder“, „SAIC · Science Applications Intl“: името от картата (Yahoo), иначе от таблиците на Wikipedia
    (brief["names"]); без правните окончания и без „(Class A)“; име, равно на тикъра, или без име → "". Чиста функция.
    """
    n = company if company and str(company).strip() and str(company).strip().upper() != str(ticker or "").upper() else (name_map or {}).get(ticker)
    if n and str(n).isupper() and (name_map or {}).get(ticker):                   # името на SEC с главни букви („BERKSHIRE HATHAWAY INC DEL“) — Wikipedia има предимство
        n = name_map[ticker]
    if not n:
        return ""
    n = re.sub(r"\s*\((?:Class|Series) [A-Z]\)", "", str(n)).strip()
    n = re.sub(r"^([A-Z][\w&.-]*) \(([A-Z][a-z]+)\)$", r"\2 \1", n)            # Wikipedia: „Lilly (Eli)“ → „Eli Lilly“
    n = re.sub(r"\s*\(The\)$", "", n)                                             # Wikipedia: „Estée Lauder Companies (The)“
    toks = n.split()
    while len(toks) > 1 and toks[-1].lower().strip(".,") in ("new", "del"):       # Yahoo / SEC: „Berkshire Hathaway Inc. New“, „… INC DEL“
        toks.pop()
    n = re.sub(r"[\s,]+(?:&|and)$", "", names.strip_legal(" ".join(toks)), flags=re.I).strip()   # „Merck & Company, Inc.“ → „Merck“, „Eli Lilly and Company“ → „Eli Lilly“ (реплеят 16.11)
    out = names.cut_words(n, limit) if limit else n
    if out.upper() == str(ticker or "").upper():
        return ""
    return out


def why_here(c: dict | None) -> str:
    """
    17.11.2026 (пакет 1, т. 2а — решение след стратегическия преглед): „Защо е тук“ — само от полетата на картата, без AI (той беше махнат): RS rating, RS линията,
    Stage 2 и trend template, EPS и приходите г/г, секторът (водещ — по SECT✓), разстоянието до 52-седмичния връх. Липсващо поле се пропуска. Чиста функция.
    """
    c = c or {}
    parts = []
    r = c.get("rs_rating")
    if isinstance(r, (int, float)):
        parts.append(f"RS {r:.0f} (перцентил в универса)")
    rs = {"new_high": "RS линията на нов връх", "near_high": "RS линията близо до върха"}.get(c.get("rs_status"))
    if rs:
        parts.append(rs)
    stg = (["Stage 2"] if c.get("weinstein_stage") == 2 else []) + (["trend template ✓"] if c.get("trend_template_applied") else [])
    if stg:
        parts.append(", ".join(stg))
    fund = [f"{lab} {v:+.0f}% г/г" for lab, v in (("EPS", c.get("eps_growth_yoy")), ("приходи", c.get("revenue_growth_yoy"))) if isinstance(v, (int, float))]
    if fund:
        parts.append(", ".join(fund))
    sec = c.get("sector")
    etf = next((e for e, m in config.SECTOR_ETF_YAHOO.items() if sec and sec in (m.get("sector") or [])), None)
    if etf:
        name = config.SECTOR_ETFS.get(etf, etf)
        parts.append(f"{name} — водещ сектор ({etf})" if c.get("macro_tailwind") else f"{name} ({etf})")
    hi = c.get("pct_below_52w_high")
    if isinstance(hi, (int, float)):
        parts.append(f"{hi:.1f}% под 52-седм. връх")
    return " · ".join(parts)


env.globals["why_here"] = why_here


def offering_lines(brief: dict) -> list[str]:
    """16.11.2026 (т. 13): „KDP — ⚠ емисия на акции — 424B5 от 16.11: …“ за тикърите с емисия, които нямат карта (книгите, наблюдаваните). Чиста функция."""
    ow = brief.get("offering_warnings") or {}
    cards = {c.get("ticker") for k in ("action", "watchlist", "qm_breakout", "glb_candidates") for c in (brief.get(k) or []) if isinstance(c, dict)}
    return [f"{t} — {txt}" for t, txt in sorted(ow.items()) if t not in cards]


def _week_calendar_ctx(wc: dict | None) -> dict | None:
    """16.11.2026 (т. 8): календарът на седмицата за шаблона и имейла — дните с готовите редове (econ_calendar.day_lines). Стар бриф без полето → None."""
    if not isinstance(wc, dict):
        return None
    try:
        from src import econ_calendar
        days = [{"date": d["date"], "weekday": d["weekday"], "lines": econ_calendar.day_lines(d)} for d in wc.get("days") or []]
    except Exception as e:
        print(f"[render] календарът на седмицата: {type(e).__name__}: {e}")
        days = []
    return {"ok": wc.get("ok"), "source": wc.get("source"), "errors": wc.get("errors") or [], "weights_note": wc.get("weights_note"), "days": days, "cap_min_bn": wc.get("cap_min_bn")}


def _week_calendar_email(wc: dict | None) -> str:
    """16.11.2026 (т. 8): календарът на седмицата в имейла — ден по ден; провал → червен ред."""
    c = _week_calendar_ctx(wc)
    if not c:
        return ""
    out = '<div style="margin-top:12px;font-size:13px"><b>Календар на седмицата</b> <span style="color:#6b7280;font-size:12px">(' + _e(c["source"] or "") + ')</span>'
    if c["errors"]:
        out += f'<div style="color:#991b1b;font-size:12.5px">⚠ Календарът е непълен: {_e("; ".join(c["errors"]))} — празното НЕ значи, че няма събития.</div>'
    for d in c["days"]:
        out += f'<div style="margin-top:4px"><b>{_e(d["weekday"])} {d["date"][8:10]}.{d["date"][5:7]}</b>: ' + (_e(" · ".join(d["lines"])) if d["lines"] else '<span style="color:#6b7280">нищо от следените</span>') + "</div>"
    return out + "</div>"


def _put_call_line(brief: dict) -> str | None:
    """16.11.2026 (пакет 16.11, т. 2): изречението за Put/Call под разказа — от кода (thermometer.put_call_sentence). Graceful: провал → None."""
    try:
        from src import thermometer
        ind = next((i for i in (brief.get("thermometer") or {}).get("indicators") or [] if str(i.get("name", "")).startswith("Put/Call")), None)
        return thermometer.put_call_sentence(ind)
    except Exception:
        return None


def _paragraphs(text: str) -> list[str]:
    """29.10.2026: абзаците на макро разказа — разделени с празен ред (същото като ai_brief.paragraphs; тук без зависимост от ai_brief)."""
    return [x.strip() for x in re.split(r"\n\s*\n", text or "") if x.strip()]


def _e(x) -> str:
    """HTML escape на външен/AI текст за имейла (f-string HTML, където Jinja autoescape не важи)."""
    return _html.escape("" if x is None else str(x), quote=True)






def form4_line(cards: dict | None, positions: dict | None, watched: dict | None = None) -> str | None:
    """
    21.10.2026 (етап 4, ритъм на данните): видим ред за Form 4 и при нула покупки — „Form 4: проверени N тикъра от картите и M позиции — X покупки ≥ $100 000 от ключови лица
    за 30 дни“. Провал → „проверката не мина днес (…) — нулата не значи, че няма покупки“; непълно (ok_partial) → бележката в скоби. Без статуси → None.
    03.11.2026 (поправки след брифа, т. 6): и наблюдаваните тикъри — „… и K наблюдавани“ (същата проверка, insider_buying.insider_for).
    """
    from src import insider_buying
    parts, found, bad = [], 0, []
    for st, what in ((cards, "от картите"), (positions, "позиции"), (watched, "наблюдавани")):
        st = st or {}
        if not st or (st.get("kind") != "failed" and not st.get("requested")):   # няма тикъри за проверка (реално 06–08.10: без карти) — без част в реда
            continue
        if st.get("kind") == "failed":
            bad.append(f"{what}: {st.get('note') or 'тегленето не мина'}")
            continue
        parts.append(f"{st.get('requested', 0)} {'тикъра ' + what if what == 'от картите' else what}")
        found += int(st.get("found") or 0)
        if st.get("kind") == "ok_partial" and st.get("note"):
            bad.append(f"{what}, непълно: {st['note']}")
    if not parts and not bad:
        return None
    word = "покупка" if found == 1 else "покупки"
    head = (f"Form 4: проверени {' и '.join(parts)} — {found} {word} ≥ ${config.INSIDER_MIN_VALUE:,.0f} от ключови лица (officers / клъстер) за {insider_buying._LOOKBACK_DAYS} дни"
            .replace(",", " ") if parts else "Form 4: проверката не мина днес")
    if found:
        where = [w for st, w in ((cards, "на картите"), (positions, "на позициите")) if int((st or {}).get("found") or 0)]
        tf = (watched or {}).get("tickers_found") or []
        where += [f"на наблюдаваните ({', '.join(tf)})"] if tf else (["на наблюдаваните"] if int((watched or {}).get("found") or 0) else [])
        head += " — маркерът INS✓ " + " и ".join(where or ["на картите"])
    if bad:
        head += " (" + "; ".join(bad) + (" — нулата не значи, че няма покупки" if not parts or any("непълно" not in b for b in bad) else "") + ")"
    return head


def _qm_open_html(c: dict) -> str:
    """22.10.2026: имейлът — QM карта с жив запис в книгата (както на страницата)."""
    b = (c or {}).get("book_open")
    if not b or not b.get("since"):
        return ""
    price = f" @ ${b['price']:.2f}" if isinstance(b.get("price"), (int, float)) else ""
    moved = ""
    if isinstance(b.get("level0"), (int, float)) and isinstance(c.get("trigger"), (int, float)) and abs(b["level0"] - c["trigger"]) > 0.005 and b.get("level0_date"):
        moved = f'<br><span style="color:#6b7280;font-size:12px">ниво от {b["level0_date"][8:10]}.{b["level0_date"][5:7]} ${b["level0"]:.2f} → днес ${c["trigger"]:.2f}</span>'
    filled = b["filled"] if "filled" in b else b.get("status") not in ("pending", None)        # стар бриф без полето — по статуса на записа
    if not filled:                                                               # 20.11.2026 (пакет 20.11, т. 4): без реален вход — не „OPEN“
        d = b.get("level0_date") or b["since"]
        return f'<br><span style="color:#6b7280;font-size:12px">в книгата · чака пробив (от {d[8:10]}.{d[5:7]})</span>' + moved
    return f'<br><span style="color:#1d4ed8;font-size:12px">📈 OPEN — вход в книгата от {b["since"][8:10]}.{b["since"][5:7]}{price} — новото ниво не е нов вход</span>' + moved


# 03.11.2026 (разходката, т. 17): cot_quote (цитатът на модела в COT cross тезата) — махнат заедно с тезите


def _publish_history(brief: dict) -> None:
    """
    GitHub Pages сервира от /docs, затова data/ в root-а НЕ е достъпен по HTTP.
    Огледалваме дневния пакет в docs/data/<date>.json (за програмен достъп) и
    поддържаме docs/data/index.json манифест с наличните дати. Манифестът се
    гради от docs/archive/*.html — точно файловете, които календарът отваря
    (Секция 3.5), така че всеки архивиран ден е избираем, не само от-v2-нататък.
    """
    import json, re
    hist_dir = config.DOCS_DIR / "data"
    hist_dir.mkdir(parents=True, exist_ok=True)
    date = brief["date"]
    (hist_dir / f"{date}.json").write_text(
        json.dumps(brief, ensure_ascii=False, default=str), encoding="utf-8")

    archive = config.DOCS_DIR / "archive"
    dates = set()
    if archive.exists():
        for f in archive.glob("*.html"):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.stem):
                dates.add(f.stem)
    dates.add(date)
    (hist_dir / "index.json").write_text(
        json.dumps(sorted(dates), ensure_ascii=False), encoding="utf-8")


def _qm_replay_line() -> str:
    """12.10.2026: ред за имейла — числата от реплея с новата формула за R (config.QM_REPLAY_STATS); празен низ без тях."""
    q = getattr(config, "QM_REPLAY_STATS", None)
    if not q:
        return ""
    return (f"Реплей {q['period']} ({q['trades']} сделки), R = печалба ÷ max(вход − дъното на деня, {config.QM_R_RISK_FLOOR_ADR:g}×ADR): среден R {q['avg_r']:+.2f} "
            f"(pess {q['avg_r_pess']:+.2f}), доходност на сделка средно {q['avg_return_pct']:+.2f}%; досегашният среден R ({q['old_avg_r']:+.2f}) беше раздут от сделки с нищожен риск "
            f"({q['floored_trades']} сделки = {q['floored_share_of_sum_r_pct']}% от ΣR). ")


def _dm(iso) -> str:
    iso = str(iso or "")
    return f"{iso[8:10]}.{iso[5:7]}" if len(iso) >= 10 and iso[4] == "-" else iso


_WD = ["пн", "вт", "ср", "чт", "пт", "сб", "нд"]


def _utc_short(iso: str | None) -> str | None:
    """"2026-10-30T08:46Z" / "...+00:00" → "пт 30.10 08:46" (UTC). Лош вход → None."""
    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None
    return f"{_WD[t.weekday()]} {t:%d.%m %H:%M}"


def news_window_hours(nw: dict | None, key: str = "hours", default: int = 24) -> int:
    """02.11.2026 (т. 4): часовете в заглавието на раздела („последните 72ч“) — закръглени; стар бриф без прозорец → default (24). Чиста функция."""
    try:
        return int(round(float((nw or {}).get(key))))
    except Exception:
        return default


def crypto_window_note(nw: dict | None, pool_sources: dict | None) -> str | None:
    """
    04.11.2026 (четвърти преглед, С5): бележката под крипто новините — както news_window_note: само фийдовете, които не стигат до началото на крипто прозореца (най-старото заглавие
    в пула по-късно от началото с над config.NEWS_REACH_TOLERANCE_MIN минути) или нямат нито едно заглавие. Началото = началото на прозореца на новините + (часовете на новините −
    часовете на крипто). РЕАЛНО 03.11: прозорец 30 ч от 02.11 00:30 UTC; Cointelegraph (28 заглавия) — до 02.11 01:51, CoinDesk (25) — до 05:18; заглавието казваше „последните 30ч“
    без уговорка. Без прозорец / без pool_sources (стар бриф) → None. Чиста функция.
    """
    nw = nw or {}
    try:
        since = dt.datetime.fromisoformat(str(nw["since"]).replace("Z", "+00:00"))
        hours, c_hours = float(nw["hours"]), float(nw.get("crypto_hours") or nw["hours"])
    except Exception:
        return None
    if not pool_sources:
        return None
    start = since + dt.timedelta(hours=hours - c_hours)
    tol = dt.timedelta(minutes=config.NEWS_REACH_TOLERANCE_MIN)
    short = []
    for name, v in pool_sources.items():
        if not (v or {}).get("count"):
            short.append(f"{name} — без заглавия в прозореца")
            continue
        old = (v or {}).get("oldest")
        try:
            t = dt.datetime.fromisoformat(str(old).replace("Z", "+00:00"))
        except Exception:
            short.append(f"{name} — заглавията са без дата")
            continue
        if t - start > tol:
            short.append(f"{name} — до {_utc_short(old)} ({v['count']} заглавия)")
    if not short:
        return None
    return (f"Прозорец: {news_window_hours({'hours': c_hours})} ч (от {_utc_short(start.isoformat())} UTC). Не стигат до началото му: " + " · ".join(short)
            + " — фийдът държи само последните си заглавия; по-старото не е проверено.")


def news_window_note(nw: dict | None) -> str | None:
    """
    02.11.2026 (поправки след брифа, т. 4): бележката под новините. Всички източници стигат до началото на прозореца → само „Прозорец: 72 ч (от предишния бриф)“; иначе —
    и началото, и САМО източниците, които не стигат до него, с докъде стигат (най-старото заглавие в пула): по-късно от началото с над config.NEWS_REACH_TOLERANCE_MIN минути,
    или без нито едно заглавие в прозореца (източник от config.NEWS_RSS_FEEDS, който липсва в обхвата). До прегледа на 02.11 прагът беше 10% от прозореца (72 ч → 7.2 ч) и
    Reuters (най-старото — пт 08:46 при начало 06:30: денят на Google започва в полунощ тихоокеанско време — 07:00 UTC до 01.11, 08:00 UTC след това — и от заявката за деня
    влизат първите 50 от 100 заглавия) не беше отбелязан. Без прозорец (стар бриф) → None. Чиста функция.
    """
    nw = nw or {}
    start = _utc_short(nw.get("since"))
    if not start:
        return None
    try:
        since = dt.datetime.fromisoformat(str(nw["since"]).replace("Z", "+00:00"))
    except Exception:
        return None
    src = nw.get("sources") or {}
    tol = dt.timedelta(minutes=config.NEWS_REACH_TOLERANCE_MIN)
    short = []
    for name, v in src.items():
        old = _utc_short(v.get("oldest"))
        if not old:
            short.append(f"{name} — заглавията са без дата")
        elif dt.datetime.fromisoformat(str(v["oldest"]).replace("Z", "+00:00")) - since > tol:
            short.append(f"{name} — до {old}")
    short += [f"{name} — без заглавия в прозореца" for name in config.NEWS_RSS_FEEDS if name not in src]
    head = f"Прозорец: {news_window_hours(nw)} ч (от предишния бриф"
    if not short:
        return head + ")"
    return f"{head}, {start} UTC). Не стигат до началото му: " + " · ".join(short) + "."


def news_sources_alert(nw: dict | None) -> str | None:
    """
    18.11.2026 (спешно, т. 1): празен или паднал източник на новините — видим червен ред, никога тихо. Всеки фийд от config.NEWS_RSS_FEEDS с 0 заглавия в прозореца
    („fetched“ от gather_raw, иначе обхватът „sources“), с грешката (HTTP ≠ 200, изключение), ако има. Всички с заглавия / стар бриф без „fetched“ и „sources“ → None. Чиста функция.
    """
    nw = nw or {}
    fetched, reach = nw.get("fetched"), nw.get("sources")
    if fetched is None and reach is None:
        return None
    errs = {d.get("source"): d.get("error") for d in nw.get("dead") or [] if isinstance(d, dict)}
    bad = []
    for name in config.NEWS_RSS_FEEDS:
        n = (fetched or {}).get(name) if fetched is not None else ((reach or {}).get(name) or {}).get("count", 0)
        if not n:
            bad.append(f"{name} — 0 заглавия" + (f" ({errs[name]})" if errs.get(name) else " в прозореца"))
    return ("⚠ Източници без заглавия днес: " + " · ".join(bad) + " — подборът е без тях; празното НЕ значи, че няма новини.") if bad else None


def news_pool_note(nw: dict | None, diag: dict | None) -> str | None:
    """
    18.11.2026 (спешно, т. 1): колко заглавия стигнаха до подбора по източник (таванът реже след редуването) и колко от избраните паднаха при проверките на кода и защо.
    Реално, 18.11: 100 от 139 (Reuters 50 върнати), моделът избра 8, показани 6 — 2 паднаха („индексът не съвпада със заглавието“: апострофите, сред тях Nvidia).
    Без „to_model“ (стар бриф) → None. Чиста функция.
    """
    nw, diag = nw or {}, diag or {}
    to, fetched = nw.get("to_model"), nw.get("fetched") or {}
    if not to:
        return None
    parts = [f"{k} {v}" + (f" от {fetched[k]}" if fetched.get(k) and fetched[k] != v else "") for k, v in to.items()]
    out = f"Към подбора: {nw.get('pool_used', sum(to.values()))} от {nw.get('pool_total', sum(to.values()))} заглавия ({', '.join(parts)})"
    pr = nw.get("priority") or {}
    if pr.get("in_pool"):                                                       # 18.11.2026 (поправка): заглавията за нашите тикъри — първи
        tk = pr.get("tickers") or []
        out += (f"; първи — {pr['in_pool']} за нашите тикъри и компании ({', '.join(tk[:8])}{' …' if len(tk) > 8 else ''})"
                + (f", от тях {pr['beyond_limit']} след тавана на източника" if pr.get("beyond_limit") else ""))
    main_drops = [d for d in diag.get("dropped") or [] if isinstance(d, dict) and (d.get("pool_title") or d.get("reason") in ("няма валиден индекс в пула", "празно why", "ехото е по-кратко от 3 думи"))]
    if diag.get("returned") is not None:
        out += f"; подборът избра {diag['returned']}, показани {diag.get('kept', 0)}"
        if main_drops:
            why = sorted({d["reason"] for d in main_drops})
            out += f" — {len(main_drops)} паднаха при проверката на кода ({'; '.join(why)})"
    return out + "."


def news_path_note(diag: dict | None) -> dict | None:
    """
    23.11.2026 (пакет 23.11, т. 1): кой път на подбора е ползван — {"text", "level"}; стар бриф (без "path") → None. Към текста — опитите (пул, резултат). Чиста функция.
    """
    d = diag or {}
    path = d.get("path")
    if path not in ("ai", "ai_retry", "code"):
        return None
    from src.data_warnings import NEWS_PATH_TEXT
    txt = NEWS_PATH_TEXT[path]
    tries = [f"{a.get('pool')} заглавия — {'отрязан отговор' if a.get('result') == 'TruncatedResponse' else ('ok' if a.get('result') == 'ok' else a.get('result'))}"
             for a in d.get("attempts") or []]
    if path != "ai" and tries:
        txt = txt[:-1] + f" (опити: {'; '.join(tries)})."
    pb = d.get("picked_by") or {}
    if path == "code" and pb:
        txt = txt[:-1] + " · " + ", ".join(f"{ {'theme': 'теми', 'ours': 'нашите тикъри', 'front': 'първа страница'}[k] } {v}" for k, v in pb.items()) + "."
    return {"text": txt, "level": "muted" if path == "ai" else "warn"}


def overnight_ctx(o: dict | None) -> dict | None:
    """
    18.11.2026 (спешно, т. 2): блокът „Нощта“ за шаблона и имейла — компаниите с „ТИКЪР · Име“ (names.display_name) и готовите редове; пазарът — един ред. Без блок / стар
    бриф → None. Чиста функция.
    """
    if not isinstance(o, dict) or not o.get("session"):
        return None
    comp = [{**c, "label": c.get("ticker", "") + (f" · {names.display_name(c['name'], 28)}" if c.get("name") else "")} for c in o.get("companies") or []]
    s = o["session"]
    return {"session": s, "day": f"{s[8:10]}.{s[5:7]}", "companies": comp, "market": " · ".join(m.get("text", "") for m in o.get("market") or []),
            "notes": o.get("notes") or [], "source": o.get("source")}


def themes_ctx(themes: list | None) -> list[dict] | None:
    """
    19.11.2026 (пакет 19.11, т. 2): редът „Топ теми“ — до config.THEME_MAX теми: дословното заглавие, източникът му, колко издателя и заглавия, кога е последното (UTC).
    Без теми / стар бриф → None. Чиста функция.
    """
    if not themes:
        return None
    out = []
    for t in themes:
        p = t.get("published") or ""
        when = f"{p[8:10]}.{p[5:7]} {p[11:16]} UTC" if len(p) >= 16 else ""
        out.append({"headline": t.get("headline"), "source": t.get("source"), "n_publishers": t.get("n_publishers"), "publishers": ", ".join(t.get("publishers") or []),
                    "n_headlines": t.get("n_headlines"), "when": when, "front": t.get("front"), "key": t.get("key")})
    return out


def news_meta(n: dict) -> dict | None:
    """
    20.11.2026 (пакет 20.11, т. 1): под заглавието — преводът (или „преводът е пропуснат — несъответствие“), източникът, часът (UTC) и кои наши тикъри засяга. Само за новите
    редове (с поле „ours“); старите брифове — без промяна. Чиста функция.
    """
    if not isinstance(n, dict) or "ours" not in n:
        return None
    p = n.get("published") or ""
    return {"bg": n.get("headline_bg"), "note": n.get("translation_note"), "when": f"{p[8:10]}.{p[5:7]} {p[11:16]} UTC" if len(p) >= 16 else "",
            "ours": ", ".join(n.get("ours") or []) or "няма"}


def news_meta_email(n: dict) -> str:
    m = news_meta(n)
    if not m:
        return ""
    line = (f'<div style="color:#111827;font-size:12.5px">{_e(m["bg"])}</div>' if m["bg"] else
            f'<div style="color:#b45309;font-size:12px">{_e(m["note"] or "")}</div>' if m["note"] else "")
    return line + (f'<div style="color:#6b7280;font-size:11.5px">{_e(n.get("source") or "")}' + (f' · {m["when"]}' if m["when"] else "") + f' · наши тикъри: {_e(m["ours"])}</div>')


def _f(x, fmt="{:.2f}", pre="$") -> str | None:
    return (pre + fmt.format(x)) if isinstance(x, (int, float)) else None


def _tier_label(c: dict) -> str | None:
    t = ((c or {}).get("tier") or {}).get("tier")
    return "Тренд без ръст" if t == "trend" else ("CANSLIM" if t == "canslim" else None)


def novelty_tile(screener: str, c: dict) -> dict:
    """
    20.11.2026 (пакет 20.11, т. 2): еднаквата плочка „Нови днес“ — тикър · име · скрийнър · ниво / аларма · стоп · цел · разстояние · „Защо е тук“ · отчет ⚠ · ниво (CANSLIM / Тренд
    без ръст); стар с нов статус — етикет „от ДД.ММ — днес …“. Полетата — от картата на скрийнъра. Чиста функция.
    """
    from src import novelty
    nv = c.get("novelty") or {}
    t = {"ticker": c.get("ticker"), "name": names.display_name(c.get("company") or c.get("name"), 32) if (c.get("company") or c.get("name")) else "",
         "screener": novelty.LABELS.get(screener, screener), "label": nv.get("label"), "status": nv.get("status"),
         "earnings": (c.get("earnings_gate") or {}).get("text") if (c.get("earnings_gate") or {}).get("soon") else None, "tier": _tier_label(c), "levels": c.get("levels")}
    if screener == "canslim":
        s, p, pp = c.get("setup") or {}, c.get("plan") or {}, c.get("plan_preview") or {}
        if p and nv.get("status") == "вход днес":
            t.update(level=f"вход ≈ {_f(p.get('entry_mid'))}", stop=_f(p.get("stop_loss")), target=_f(p.get("target_1")), dist=None)
        else:
            t.update(level=f"аларма над {_f(s.get('buy_stop'))} — вход само с обем" if s.get("buy_stop") else "—", stop=_f(pp.get("stop_loss") or s.get("stop")),
                     target=_f(pp.get("target_1")), dist=(f"{nv['dist']:+.1f}% до buy-stop" if isinstance(nv.get("dist"), (int, float)) else None))
        t["why"] = why_here(c)
    elif screener == "qm":
        t.update(level=f"ниво на пробива {_f(c.get('trigger'))}", stop=(f"{_f(c.get('max_stop'))} (макс. 1×ADR)" if isinstance(c.get("max_stop"), (int, float)) else None),
                 target=f"частична на {config.QM_PARTIAL_DAYS}-ия ден, после SMA10 / SMA20",
                 dist=(f"{nv['dist']:+.1f}% до нивото" if isinstance(nv.get("dist"), (int, float)) else None),
                 why=" · ".join(x for x in (f"ръст +{c['runup_pct']:.0f}% преди базата" if isinstance(c.get("runup_pct"), (int, float)) else None,
                                            f"база {c['base_days']} дни" if c.get("base_days") else None,
                                            f"стягане {c['tight']:.2f}×ADR" if isinstance(c.get("tight"), (int, float)) else None) if x))
    elif screener.startswith("glb"):
        t.update(level=f"линия {_f(c.get('line'))}", stop="затваряне под линията", target=None,
                 dist=(f"{c['pct_vs_line']:+.1f}% над линията" if isinstance(c.get("pct_vs_line"), (int, float)) else None),
                 why=" · ".join(x for x in (f"{c['months_unpenetrated']} месеца без връх" if c.get("months_unpenetrated") is not None else None,
                                            f"обем на пробива {c['breakout_volume_ratio']:.1f}×" if isinstance(c.get("breakout_volume_ratio"), (int, float)) else None,
                                            f"сесия {c['sessions']} от {c['max_sessions']}" if c.get("sessions") and c.get("max_sessions") else None) if x))
    else:
        t.update(level=f"after-hours {_f(c.get('ah_price'))}", stop=_f(c.get("max_stop")), target=None,
                 dist=(f"гап {c['gap_pct']:+.1f}%" if isinstance(c.get("gap_pct"), (int, float)) else None), why=c.get("catalyst_label") or "")
    return t


def novelty_row(screener: str, c: dict, today: str) -> dict:
    """Компактният ред „Още валидни“: тикър · име · предложен ДД.ММ · валиден до · разстояние до входа."""
    from src import sessions
    nv = c.get("novelty") or {}
    fs = nv.get("first_seen") or ""
    if screener == "canslim":
        vt = (c.get("setup") or {}).get("valid_through")
    elif screener == "qm":
        vt = today                                                               # входът е за една сесия; новият ден е нов ден в прозореца
    elif screener.startswith("glb") and c.get("sessions") and c.get("max_sessions"):
        d = __import__("datetime").date.fromisoformat(today)
        for _ in range(max(0, int(c["max_sessions"]) - int(c["sessions"]))):
            d = sessions.next_session(d)
        vt = d.isoformat()
    else:
        vt = None
    dist = nv.get("dist")
    unit = {"canslim": "до buy-stop", "qm": "до нивото"}.get(screener, "над линията" if screener.startswith("glb") else "")
    return {"ticker": c.get("ticker"), "name": names.display_name(c.get("company") or c.get("name"), 28) if (c.get("company") or c.get("name")) else "",
            "since": f"{fs[8:10]}.{fs[5:7]}" if fs else "", "valid": f"{vt[8:10]}.{vt[5:7]}" if vt else "—",
            "dist": f"{dist:+.1f}% {unit}".strip() if isinstance(dist, (int, float)) else "—", "status": nv.get("status"),
            "earnings": (c.get("earnings_gate") or {}).get("text") if (c.get("earnings_gate") or {}).get("soon") else None}


def market_gap_day(brief: dict | None) -> dict | None:
    """
    23.11.2026 (пакет 23.11, т. 4): денят е „ден на пазарен гап“ (карето в 15:05 — brief["preopen"]["market_gap"]) → {"text", "moves": {тикър: True — EP без собствена новина}};
    иначе None. Сутрешната страница (07:30) още не знае — етикетът идва с обновяването в 15:05. Чиста функция.
    """
    mg = ((brief or {}).get("preopen") or {}).get("market_gap")
    if not (isinstance(mg, dict) and mg.get("gap")):
        return None
    from src import market_gap
    moves = {r.get("ticker"): True for r in ((brief.get("qm_ep") or {}).get("rows")) or [] if not market_gap.own_news(r)}
    return {"text": mg.get("text"), "moves": moves}


def premarket_missing(brief: dict | None) -> str | None:
    """
    27.11.2026 (уикенд пакет, т. 3): карето в 15:05 е без премаркет (под config.PREOPEN_MIN_PM_SHARE от поисканите) или без фючърси → банер във всяка секция (CANSLIM, Kullamägi,
    GLB, EP): „премаркет липсва — денят на пазарен гап не може да се провери“ + с колко. Сутрин (без каре) / нормален премаркет → None. Чиста функция.
    """
    p = (brief or {}).get("preopen")
    if not isinstance(p, dict):
        return None
    cov, m = p.get("coverage") or {}, p.get("market") or {}
    n, k = cov.get("requested") or (p.get("diag") or {}).get("requested") or 0, cov.get("with_pm") if cov.get("with_pm") is not None else (p.get("diag") or {}).get("with_pm")
    low = bool(n) and (k or 0) < config.PREOPEN_MIN_PM_SHARE * n
    no_fut = bool(m.get("futures_missing")) and not m.get("futures")
    if not (low or no_fut):
        return None
    parts = ([f"премаркет за {k or 0} от {n} тикъра"] if low else []) + ([f"фючърсите ({', '.join(m['futures_missing'])}) — без цена"] if no_fut else [])
    return "премаркет липсва — денят на пазарен гап не може да се провери (" + "; ".join(parts) + ")"


def cash_block(brief: dict | None) -> str | None:
    """23.11.2026 (пакет 23.11, т. 5): режим Cash → config.CASH_BLOCK_TEXT (картите и „Нови днес“ — без размер); иначе None. Чиста функция."""
    return config.CASH_BLOCK_TEXT if ((brief or {}).get("thermometer") or {}).get("regime") == "Cash" else None


def novelty_ctx(brief: dict) -> dict | None:
    """{скрийнър: {"label", "tiles", "old", "dropped"}} за шаблона; стар бриф без brief["novelty"] → None (страницата — както досега). Чиста функция."""
    nov = brief.get("novelty")
    if not isinstance(nov, dict):
        return None
    from src import novelty
    today = str(brief.get("date") or "")[:10]
    cards = {"canslim": list(brief.get("action") or []) + list(brief.get("watchlist") or []), "qm": brief.get("qm_breakout") or [],
             "glb_classic": [c for c in brief.get("glb_candidates") or [] if not (c.get("glb_type") or "").lower().startswith("mom")],
             "glb_momentum": [c for c in brief.get("glb_candidates") or [] if (c.get("glb_type") or "").lower().startswith("mom")],
             "ep": ((brief.get("qm_ep") or {}).get("rows")) or []}
    out = {}
    for s in novelty.SCREENERS:
        n = nov.get(s) or {}
        by = {c.get("ticker"): c for c in cards[s] if c.get("novelty")}
        out[s] = {"label": novelty.LABELS[s], "tiles": [{**novelty_tile(s, by[t]), "cash": cash_block(brief)} for t in n.get("new") or [] if t in by],
                  "market_gap": (market_gap_day(brief) or {}).get("text"),                       # 23.11.2026 (т. 4): новите сигнали от ден на пазарен гап
                  "old": [novelty_row(s, by[t], today) for t in n.get("old") or [] if t in by], "dropped": n.get("dropped") or []}
    return out


def _themes_email(themes: list | None) -> str:
    c = themes_ctx(themes)
    if not c:
        return ""
    rows = "".join(f'<div style="margin:3px 0">„{_e(x["headline"])}“ <span style="color:#6b7280">({_e(x["source"])} · {x["n_publishers"]} източника: {_e(x["publishers"])} · '
                   f'{x["n_headlines"]} заглавия{" · последно " + _e(x["when"]) if x["when"] else ""})</span></div>' for x in c)
    return (f'<tr><td style="padding:12px 28px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#111827"><div style="font-weight:bold;margin-bottom:4px">Топ теми</div>{rows}'
            f'<div style="color:#9ca3af;font-size:11px;margin-top:4px">От кода: заглавията от всички източници, групирани по общи имена (≥ 3 издателя или ≥ 6 заглавия)</div></td></tr>')


def _overnight_email(o: dict | None) -> str:
    c = overnight_ctx(o)
    if not c:
        return ""
    rows = "".join(f'<div style="margin:4px 0"><b>{_e(x["label"])}</b>' + (f' <span style="color:#6b7280">· {_e(x["why"])}</span>' if x.get("why") else "")
                   + f': {_e(" · ".join(x.get("lines") or []))}</div>' for x in c["companies"])
    notes = "".join(f'<div style="color:#6b7280;font-size:12px">{_e(n)}</div>' for n in c["notes"])
    return (f'<tr><td style="padding:16px 28px;border-bottom:1px solid #e5e7eb;font-size:13px;color:#111827">'
            f'<div style="font-weight:bold;margin-bottom:6px">Нощта · отчетите след затварянето на {c["day"]} и фючърсите</div>{rows}'
            f'<div style="margin:6px 0 2px"><b>Пазарът през нощта:</b> {_e(c["market"])}</div>{notes}'
            f'<div style="color:#9ca3af;font-size:11px;margin-top:4px">Източник: {_e(c["source"] or "")}</div></td></tr>')


def radar_reason(c: dict) -> str:
    """
    30.10.2026 (разходката, т. 9–10): причината на реда в „На радара“ — от кода, с числото: „широк стоп · 15.3%“ (too_wide; до 02.11 „разтегната · стоп“), „пробив без обем · 0.9×“, „блокирана от режима“,
    отчет в прозореца, запис в книгата, сделка; неутралният ред за жив запис в buy-stop книгата (setup.book_note) — след нея, както в досегашния компактен ред. Чиста функция.
    """
    why = _radar_reason(c)
    note = (c.get("setup") or {}).get("book_note")
    why = f"{why}; {note}" if note and note not in why else why
    dc = (c.get("earnings") or {}).get("date_conflict")                    # 17.11.2026 (пакет 1, т. 8): Yahoo и Nasdaq се разминават за датата на отчета
    return f"{why} · ⚠ {dc}" if dc else why


def _radar_reason(c: dict) -> str:
    setup, ai = c.get("setup") or {}, c.get("ai") or {}
    kind, rt = setup.get("kind"), ai.get("watchlist_reason_type")
    if rt == "existing_position":
        return ai.get("watchlist_trigger") or "запис в книгата — не е нов вход"
    bk = setup.get("book") if setup.get("triggered") else None
    if bk and isinstance(bk.get("fill_price"), (int, float)) and isinstance(bk.get("stop_loss"), (int, float)) and bk["fill_price"] > 0:
        # същият текст като досегашния компактен ред (12.10 / 27.10): стопът е на книгата, днешният сетъп — допълнение
        r, fd = bk.get("current_r"), _dm(bk.get("fill_date"))
        today_txt = f"в позиция от {fd}; днес под pivot" if kind == "below_pivot" else f"днес: {watchlist_exits.setup_text(setup) or kind}"
        return (f"✅ задействан в buy-stop книгата на {fd} по ${bk['fill_price']:.2f}, стоп ${bk['stop_loss']:.2f} "
                f"({(bk['fill_price'] - bk['stop_loss']) / bk['fill_price'] * 100:.1f}% под входа)" + (f", текущо {r:+.1f}R" if isinstance(r, (int, float)) else "") + f"; {today_txt}")
    if kind == "deal":
        d = setup.get("deal") or {}
        return "сделка — цел на придобиване" + (f" ({d['buyer']})" if d.get("buyer") else "")
    if kind == "too_wide":
        sr = setup.get("struct_risk_pct")
        return "широк стоп" + (f" · {sr:.1f}%" if isinstance(sr, (int, float)) else "")        # 02.11.2026 (т. 5): до 02.11 „разтегната · стоп X%“ — „над зоната“ е extended
    if kind == "extended":
        pct = setup.get("pct_from_pivot", c.get("pct_from_pivot"))
        return "над зоната за покупка" + (f" · {pct:+.1f}% (> +{config.BUYABLE_ZONE_MAX_PCT:g}%)" if isinstance(pct, (int, float)) else "")
    if kind == "no_volume":
        vr = c.get("volume_ratio")
        return "пробив без обем · " + (f"{vr:.1f}×" if isinstance(vr, (int, float)) else "?") + f" (< {config.BREAKOUT_VOLUME_MULT:g}×)"
    if kind == "confirmed":
        e = c.get("earnings") or {}
        if rt in ("regime_block", "regime_gate"):
            return "блокирана от режима"
        if rt == "earnings_blackout":
            d = e.get("days_to_earnings")
            return f"отчет на {enrich_mod.earnings_dm(e.get('next_earnings'), e.get('earnings_estimate'))}" + (f" ({int(d)} дни)" if isinstance(d, (int, float)) else "") + " — вход след отчета"
        if rt == "earnings_recent":
            return "отчет в последната сесия — нивата са отпреди реакцията"
        if rt == "earnings_unknown":
            return "датата на отчета не се изтегли"
        return ai.get("watchlist_trigger") or "потвърден пробив"                     # лимит на Action / сектора, невалиден план, затворена днес
    if kind == "below_pivot":
        return "под pivot — чака buy-stop"
    if kind == "no_data":
        return "няма цена / pivot"
    return ai.get("watchlist_trigger") or "—"                                          # стар бриф без сетъп


def glb_groups(cands: list[dict] | None, book: dict | None) -> dict:
    """
    03.11.2026 (разходката, т. 13–14): GLB картите по тип → {"classic" | "momentum" | "insufficient": {"cards": [...], "open": [...] | None}}. Картите — по обема на пробива (най-силните
    горе; без обем — накрая), без филтър. "open" — отворените и чакащите записи на книгата „GLB по Уиш“ от същия тип (book["open_by_type"]; стар бриф без него — book["live"] по glb_type);
    без книгата → None (няма ред „Отворени в книгата“). Чиста функция.
    """
    key = {"classic": "classic", "momentum": "momentum", "insufficient_history": "insufficient"}
    out = {k: {"cards": [], "open": None} for k in ("classic", "momentum", "insufficient")}
    for g in cands or []:
        out[key.get(g.get("glb_type"), "insufficient")]["cards"].append(g)
    for k in out:
        out[k]["cards"].sort(key=lambda g: (g.get("breakout_volume_ratio") is None, -(g.get("breakout_volume_ratio") or 0)))
    if book and book.get("enabled"):
        obt = book.get("open_by_type")
        if obt is None:
            obt = {}
            for r in book.get("live") or []:
                obt.setdefault(r.get("glb_type") or "н/д", []).append(r)
        for t, k in key.items():
            out[k]["open"] = list(obt.get(t) or [])
        out["insufficient"]["open"] += list(obt.get("н/д") or [])
    return out


def glb_market_line(t: dict | None) -> str | None:
    """03.11.2026 (т. 13, 1): редът за пазара в GLB — QQQ спрямо SMA10 / SMA20 (както при Kullamägi), без твърдението за неговото правило. Чиста функция."""
    if not t:
        return None
    if t["above10"] and t["above20"]:
        return "Nasdaq над 10/20 DMA"
    if not t["above10"] and not t["above20"]:
        return "Nasdaq под 10/20 DMA"
    return "Nasdaq над 20 DMA, под 10 DMA" if t["above20"] else "Nasdaq над 10 DMA, под 20 DMA"


env.globals["glb_groups"] = glb_groups




def excluded_deals(rows) -> list[dict]:
    """09.11.2026 (ROKU): редът „Извън универса (приключила сделка / делистване)“ — само наскоро приключилите (до 10 дни след датата). Чиста функция."""
    from src import spinoff_watch
    out = []
    for r in rows or []:
        if isinstance(r, dict) and r.get("ticker"):
            out.append({"ticker": r["ticker"], "text": spinoff_watch.closed_text(r)})
    return out


def fundamentals_all_checked(status: dict | None) -> str | None:
    """
    12.11.2026 (т. 4): при 0 непроверени — „Фундаменти: проверени всички 79 (21 от кеша).“ (реално 12.11: 58 нови заявки + 21 от кеша), вместо редът да изчезне; кандидатите,
    за които Yahoo не върна данни — изрично. Стар бриф без броя (fundamentals_checked) / без кандидати → None. Чиста функция.
    """
    st = status or {}
    total = st.get("fundamentals_checked")
    if st.get("fundamentals_not_checked") is None or not isinstance(total, int) or total <= 0:
        return None
    fc = st.get("fundamentals_cache") or {}
    cache = f' ({fc["hits"]} от кеша)' if isinstance(fc.get("hits"), int) else ""
    un = st.get("fundamentals_unavailable") or []
    tail = f'; за {len(un)} Yahoo не върна данни ({", ".join(un[:5])}{", …" if len(un) > 5 else ""}) — те не са оценени' if un else ""
    return f"Фундаменти: проверени всички {total}{cache}{tail}."


def fundamentals_note(status: dict | None) -> str | None:
    """06.11.2026 (пакет 05–06.11, т. 2): редът „фундаментите не са проверени за N имена“ и кои са с най-висок RS (screener.LAST_STATUS["fundamentals_not_checked"]). Няма такива / стар бриф → None. Чиста функция."""
    nc = (status or {}).get("fundamentals_not_checked") or {}
    n = nc.get("n")
    if not n:
        return fundamentals_all_checked(status)                         # 12.11.2026 (т. 4): 0 непроверени — ред, не тишина
    top = ", ".join(f'{x["ticker"]} (RS {x["rs_rating"]})' for x in nc.get("top") or [] if x.get("ticker"))
    fc = (status or {}).get("fundamentals_cache") or {}                 # 10.11.2026 (т. 7): таванът е за новите заявки; записите от кеша не го броят
    cap = (f'таван {nc.get("max")} нови заявки към Yahoo на ден — проверяват се най-силните по RS; още {fc["hits"]} — от кеша до следващия отчет'
           if fc.get("hits") else f'таван {nc.get("max")} заради Yahoo — проверяват се най-силните по RS')
    return (f'Фундаментите не са проверени за {n} {"име" if n == 1 else "имена"} ({cap})'
            + (f'; с най-висок RS от тях: {top}' if top else "") + " — те не са в списъците по-горе.")


def is_trend(c: dict | None) -> bool:
    """17.11.2026 (пакет 2, т. 1 — А5): картата е от нивото „Тренд без ръст“ (стар бриф без полето — CANSLIM, както досега)."""
    return ((c or {}).get("tier") or {}).get("tier") == "trend"


def trend_rows(action: list[dict] | None, watchlist: list[dict] | None) -> list[dict]:
    """
    17.11.2026 (пакет 2, т. 1): подсекцията „Тренд без ръст“ — по един ред: {ticker, company, state, label, why}. state — „Купува се днес: вход $X, стоп $Y“, „Чака пробив:
    аларма над $X“ или причината от радара (radar_reason). Чиста функция.
    """
    out = []
    for c in (action or []):
        if is_trend(c):
            p = c.get("plan") or {}
            st = "Купува се днес" + (f": buy-stop ${p['buy_stop']:.2f}, стоп ${p['stop_loss']:.2f}" if p.get("buy_stop") and p.get("stop_loss") else "")
            out.append({"ticker": c.get("ticker"), "company": c.get("company"), "state": st, "label": c["tier"].get("label"), "why": why_here(c)})
    for c in (watchlist or []):
        if is_trend(c):
            s = c.get("setup") or {}
            st = (f"Чака пробив: аларма над ${s['buy_stop']:.2f}" + (f" до {_dm(s['valid_through'])}" if s.get("valid_through") else "")
                  if s.get("kind") == "below_pivot" and s.get("buy_stop") and not s.get("triggered") else radar_reason(c))
            out.append({"ticker": c.get("ticker"), "company": c.get("company"), "state": st, "label": c["tier"].get("label"), "why": why_here(c)})
    return out


def split_canslim(watchlist: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    30.10.2026 (разходката, т. 9–10): Watchlist → (карти „Чака пробив“, редове „На радара“). Чака пробив: под pivot с buy-stop ниво и срок, незадействан, без запис / чакащ план
    в книгата Action (те са на радара със своята причина). Останалото — по един ред {ticker, sector, price, pct_from_pivot, reason, rs_rating, days, …} с причината от кода
    (radar_reason); без AI текст и без отделни карти. 31.10.2026: картите „Чака пробив“ са най-много config.CANSLIM_WAITING_MAX (в реда на Watchlist — най-близките до pivot);
    над тавана — ред на радара с нивото и срока (не изчезват).
    """
    waiting, radar = [], []
    for c in watchlist or []:
        setup, ai = c.get("setup") or {}, c.get("ai") or {}
        over = None
        if setup.get("kind") == "below_pivot" and setup.get("buy_stop") and not setup.get("triggered") and ai.get("watchlist_reason_type") != "existing_position":
            if len(waiting) < config.CANSLIM_WAITING_MAX:
                waiting.append(c)
                continue
            vt = setup.get("valid_through")
            over = (f"под pivot — buy-stop ${setup['buy_stop']:.2f}" + (f" до {_dm(vt)}" if vt else "")
                    + f" (извън първите {config.CANSLIM_WAITING_MAX} карти „Чака пробив“)")
        ew = c.get("earnings_warning") or {}
        radar.append({"ticker": c.get("ticker"), "sector": c.get("sector"), "price": c.get("price"), "pct_from_pivot": c.get("pct_from_pivot"),
                      "reason": over or radar_reason(c), "rs_rating": c.get("rs_rating"), "days": c.get("radar_days"), "kind": setup.get("kind"),
                      "markers": c.get("markers") or [], "spinoff": c.get("spinoff_warning"), "merger": c.get("merger_target"), "earnings_unknown": enrich_mod.no_date(c),
                      "earnings": ({"date": ew["date"], "pct": ew.get("implied_move_pct")} if ew.get("date") else None)})
    return waiting, radar


# 30.10.2026 (т. 9–10): split_watchlist (карти / компактни редове, 10.10) → split_canslim (Чака пробив / На радара).


def render_dashboard(brief: dict, *, closed_notice: str | None = None, publish: bool = True, as_of: dt.date | None = None,
                     generated: tuple[str, str] | None = None) -> str:
    """
    16.10.2026 (В2а): closed_notice — банер "Борсата е затворена днес …" върху последния бриф; publish=False — пише САМО docs/index.html (без архив за деня и без
    огледалото в docs/data — денят не е бриф); as_of — датата в заглавието (датата на показания бриф).
    03.11.2026 (т. 10): generated — ("HH:MM", "CET") на сутрешния бриф, когато страницата се рендерира наново преди отварянето (иначе — сега).
    """
    today = as_of or dt.date.today()
    tpl = env.get_template("dashboard.html.j2")
    _nm = brief.get("names") or {}
    env.globals["tname"] = lambda t, company=None: short_name(t, company, _nm)          # 16.11.2026 (т. 14): „R · Ryder“ — името след тикъра
    gen_time, gen_tz = generated or berlin_clock()         # един вик — часът и етикетът са от един и същи момент
    html = tpl.render(
        closed_notice=closed_notice,
        calendar_note=None if closed_notice else brief.get("market_calendar_note"),      # 16.10.2026 (В2б): утре / в понеделник борсата не работи или затваря рано; 27.11.2026 (т. 2): в затворен ден бележката от предишния бриф („Утре (26.11)…“) е остаряла — без нея
        preopen=brief.get("preopen"), preopen_gap=config.PREOPEN_GAP_PCT, preopen_watch_gap=config.PREOPEN_WATCH_GAP_PCT,    # 03.11.2026 (т. 10): карето преди отварянето
        date_human=f"{today.strftime('%d.%m.%Y')}, {WEEKDAYS_BG[today.weekday()]}",
        generated_at=gen_time,
        generated_tz=gen_tz,
        premarket_note=premarket_note(),
        ny_open_berlin=setup_rules.ny_time_in_berlin(today, 9, 30),            # 16.10.2026: "Проверката е отварянето (15:30 CEST / 09:30 ET)" — от часовите зони
        regime=brief["thermometer"]["regime"],
        regime_reason=brief["thermometer"]["regime_reason"],
        regime_confirm_days=config.REGIME_OFFENSIVE_CONFIRM_DAYS,                # 17.11.2026 (пакет 3)
        thermometer=brief["thermometer"],
        macro_brief=brief["ai_macro"]["macro_brief"],
        futures_line=_futures_line(brief),                                  # 19.10.2026: договорът и часът на цената на фючърсите (WTI …) — от кода
        put_call_line=_put_call_line(brief),                                # 16.11.2026 (т. 2): Put/Call — от кода, не от AI
        week_calendar=_week_calendar_ctx(brief.get("week_calendar")),       # 16.11.2026 (т. 8): календарът на седмицата
        overnight=overnight_ctx(brief.get("overnight")),                    # 18.11.2026 (спешно, т. 2): „Нощта“ — в началото
        top_themes=themes_ctx(brief.get("top_themes")),                       # 19.11.2026 (пакет 19.11, т. 2): „Топ теми“ — под „Нощта“
        theme_min_pub=config.THEME_MIN_PUBLISHERS, theme_min_n=config.THEME_MIN_HEADLINES,
        offering_warnings=brief.get("offering_warnings") or {},             # 16.11.2026 (т. 13): емисии на акции по тикър
        deal_buyers=brief.get("deal_buyers") or {},                         # 16.11.2026 (т. 15): купувач във висяща сделка
        qm_peak_max_below=config.QM_PEAK_MAX_BELOW_52W_PCT, qm_ret6m_min=config.QM_RET6M_MIN_PCT,   # 16.11.2026 (т. 16): правилото за лидер
        offering_lines=offering_lines(brief), offering_days=config.OFFERING_LOOKBACK_DAYS,   # 16.11.2026 (т. 13): книгите и наблюдаваните без карта
        macro_paragraphs=_paragraphs(brief["ai_macro"].get("macro_brief") or ""),   # 29.10.2026: разказът по абзаци; regime_comment е махнат
        sector_logic=brief["ai_macro"].get("sector_logic", []),
        fundamentals_note=fundamentals_note(brief.get("screener_status")),   # 06.11.2026 (т. 2)
        excluded_deals=excluded_deals(brief.get("deals_closed")),            # 09.11.2026 (ROKU)
        deals_pending_scan=brief.get("deals_pending_scan") or [],            # 11.11.2026 (т. 1): висящите сделки — извън QM, GLB и EP
        no_date_text=enrich_mod.NO_DATE_TEXT,                                # 06.11.2026 (т. 3)
        sector_board=brief.get("sector_board") or {}, sector_board_lag=config.SECTOR_BOARD_RANK_LAG,   # 30.10.2026 (т. 7): секторната карта от кода
        rs_dz=config.RS_WORD_DEAD_ZONE,                                          # 30.10.2026 (т. 7): мъртвата зона на RS (сиво, „в крак с пазара“)
        sector_card=brief.get("sector_card") or {},                             # 19.10.2026 (т. 18): водещите по кода; без него (стар бриф) — веригите на модела
        action=brief["action"],
        action_c=[c for c in brief["action"] if not is_trend(c)],             # 17.11.2026 (пакет 2, т. 1): „Купува се днес“ — само нивото CANSLIM
        trend=trend_rows(brief["action"], brief["watchlist"]),                # „Тренд без ръст“ — отделна подсекция
        canslim_c_min=config.CANSLIM_C_MIN_EPS_PCT,
        qm_first_bar_from=config.QM_FIRST_BAR_RULE_FROM,                       # 17.11.2026 (пакет 2, т. 3): за стар бриф без полето
        watchlist=brief["watchlist"],                                          # 30.10.2026 (т. 9–10): целият Watchlist (за „наш“ при QM / GLB — до 30.10 без компактните редове)
        waiting=split_canslim([c for c in brief["watchlist"] if not is_trend(c)])[0],                         # 30.10.2026 (т. 9–10): „Чака пробив“ — карти с buy-stop
        radar=split_canslim([c for c in brief["watchlist"] if not is_trend(c)])[1],                           # „На радара (N)“ — сгъната таблица, причината от кода
        watchlist_exits=brief.get("watchlist_exits") or {}, watchlist_exits_label=watchlist_exits.label(brief.get("watchlist_exits") or {}, brief.get("date") or ""),
        # v2 нови блокове
        watch=brief.get("watch", []),
        watch_enabled=config.ENABLE_WATCH_MONITOR,           # празен списък ≠ изключен модул: секцията остава с ред
        model_info=brief.get("model_info", {}),
        ai_truncations=brief.get("ai_truncations", []),
        data_warnings=brief.get("data_warnings", []),
        buy_stop_window=config.BUY_STOP_WINDOW_SESSIONS,          # пакет 1б: текстът на блока за buy-stop кандидатите
        buyable_zone_pct=config.BUYABLE_ZONE_MAX_PCT,
        splits=brief.get("splits", []),
        splits_report=brief.get("splits_report"),
        splits_min_price=config.SPLITS_MIN_PRICE,
        splits_min_cap_m=config.SPLITS_MIN_MARKET_CAP / 1e6,
        form4_line=form4_line(brief.get("insider_buying_status"), brief.get("insider_buying_positions_status"), brief.get("insider_buying_watch_status")),   # 21.10 (етап 4): видим ред и при нула; 03.11: + наблюдаваните
        glb_candidates=brief.get("glb_candidates", []),
        glb_status=brief.get("glb_status"),                           # С3 (10.10): провал срещу "няма кандидати"
        corp_excluded=brief.get("corp_excluded") or {},                # 13.10: изключени заради отделяне — ред под секциите
        glb_min_months=config.GLB_MIN_MONTHS_UNPENETRATED, glb_band_hold=f"{config.GLB_MIN_BAND_HOLD_PCT:.0f}", glb_days=config.GLB_MIN_CONSOLIDATION_DAYS,
        glb_approach=f"{config.GLB_APPROACH_PCT:.0f}", glb_vol_bars=config.GLB_VOLUME_AVG_BARS, glb_wish_replay=config.GLB_WISH_REPLAY_STATS, glb_book_name=config.GLB_CLOSE_BOOK_NAME,
        glb_wish_high_replay=config.GLB_WISH_HIGH_REPLAY_STATS, glb_wish_book_name=config.GLB_WISH_BOOK_NAME,
        glb_card_sessions=config.GLB_CARD_MAX_SESSIONS, glb_card_above=config.GLB_CARD_MAX_ABOVE_PCT,                       # 03.11.2026 (т. 13): свежестта в инфото — веднъж
        glb_market_line=glb_market_line(brief.get("qm_market")),                                                             # 03.11.2026 (т. 13, 1): QQQ спрямо SMA10 / SMA20
        # Qullamaggie (06.10): отделната секция — карти, диагностика, EP наблюдение; числата в текста са от config (една истина)
        sizing_core_js=_asset("sizing_core.js"), sizing_ui_js=_asset("sizing_ui.js"),      # 07.10: оразмеряването е в браузъра (localStorage), не в брифа
        qm_cards=brief.get("qm_breakout") or [],
        qm_diag=brief.get("qm_diag") or {},
        qm_market=brief.get("qm_market"), qm_market_line=qm_breakout.nasdaq_line(brief.get("qm_market")),     # 03.11.2026 (т. 11, 2)
        qm_ep=brief.get("qm_ep") or {},
        qm_adr_min=config.QM_ADR_MIN, qm_trigger_bars=config.QM_TRIGGER_BARS, qm_expected_stop_adr=config.QM_EXPECTED_STOP_ADR, qm_max_stop_adr=config.QM_MAX_STOP_ADR,
        qm_max_dist_adr=config.QM_MAX_DIST_ADR, qm_chase_adr=config.QM_CHASE_ADR, qm_adr_stop=config.QM_ADR_STOP,
        qm_partial_days=config.QM_PARTIAL_DAYS, qm_partial_fraction=config.QM_PARTIAL_FRACTION, qm_trail_switch=config.QM_TRAIL_ADR_SWITCH,
        qm_r_floor=f"{config.QM_R_RISK_FLOOR_ADR:g}",                    # 12.10: подът на знаменателя на R в книгата qm_breakout
        qm_replay=config.QM_REPLAY_STATS,                                  # 12.10: числата от реплея с новата формула (банерът на секцията)
        qm_ep_crashed=config.QM_EP_CRASHED_RET63_PCT, insider_big_sell_pct=config.INSIDER_BIG_SELL_PCT, preopen_econ_since=config.PREOPEN_ECON_SINCE_NY, qm_ep_gap=config.QM_EP_GAP_PCT, qm_ep_neglect=config.QM_EP_NEGLECT_RET63_PCT, qm_ep_stop_adr=config.QM_EP_STOP_ADR,
        news=brief.get("news", []),
        news_window_note=news_window_note(brief.get("news_window")),     # 02.11.2026 (т. 4): прозорецът и обхватът на източниците
        news_meta=news_meta,                                              # 20.11.2026 (пакет 20.11, т. 1): превод, час, наши тикъри
        nov=novelty_ctx(brief),                                           # 20.11.2026 (пакет 20.11, т. 2): „Нови днес“ във всеки скрийнър
        news_sources_alert=news_sources_alert(brief.get("news_window")),      # 18.11.2026 (спешно, т. 1): празен / паднал източник — червен ред
        news_pool_note=news_pool_note(brief.get("news_window"), brief.get("news_diag")),
        news_path=news_path_note(brief.get("news_diag")),                    # 23.11.2026 (т. 1): пътят на подбора
        cash_block=cash_block(brief),                                        # 23.11.2026 (т. 5): режим Cash — картите без размер
        premarket_missing=premarket_missing(brief),                          # 27.11.2026 (т. 3): банер във всяка секция
        market_gap=market_gap_day(brief),                                    # 23.11.2026 (т. 4): ден на пазарен гап (след 15:05)     # 18.11.2026 (т. 1): какво стигна до подбора и какво падна
        news_h=news_window_hours(brief.get("news_window")), crypto_h=news_window_hours(brief.get("news_window"), "crypto_hours"),
        crypto_window_note=crypto_window_note(brief.get("news_window"), (brief.get("crypto") or {}).get("pool_sources")),     # 04.11.2026 (С5)
        crypto=brief.get("crypto") or {},                              # 22.10.2026 (етап 4): крипто секцията
        correlation_flags=brief.get("correlation_flags", []),
        distribution_days=brief.get("distribution_days"),
        distribution_days_status=brief.get("distribution_days_status"),
        core_inflation=(brief.get("macro") or {}).get("core_inflation"),
        pce_core=(brief.get("macro") or {}).get("pce_core"),                  # 30.10.2026 (поправки от брифа, т. 6): базов PCE — в „Информативни“
        backtest=brief.get("backtest", {}),
    )
    config.DOCS_DIR.mkdir(exist_ok=True)
    (config.DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
    if not publish:
        return html
    archive = config.DOCS_DIR / "archive"
    archive.mkdir(exist_ok=True)
    (archive / f"{today.isoformat()}.html").write_text(html, encoding="utf-8")
    _publish_history(brief)
    return html


_SPLIT_BADGE_EMAIL = {"position": "📌", "watch": "🔎"}


def _split_when(s: dict) -> str:
    """'11.08 · след 5 дни' — същият текст като badge-а на dashboard-а."""
    d = s.get("days_to_split")
    date = s.get("date") or ""
    dm = f"{date[8:10]}.{date[5:7]}" if len(date) >= 10 else ""
    if d is None:
        rel = ""
    elif d == 0:
        rel = "днес"
    elif d == 1:
        rel = "утре"
    elif d > 1:
        rel = f"след {d} дни"
    else:
        rel = f"преди {-d} {'ден' if d == -1 else 'дни'}"
    return " · ".join(x for x in (dm, rel) if x)


def _qm_email_block(brief: dict) -> str:
    """
    Qullamaggie за имейла: две подсекции веднага след реда "Watchlist" — "Пробиви по Kullamägi (Breakout)" (най-много QM_MAX_CARDS по стягане: тикър, компания, ниво за вход, стоп и %, ADR, акции при риск,
    предходен ръст, дни консолидация, QM✓ ако е и в Action/Watchlist) и "Епизодични пивоти (EP) · гапове след новина" (тикър, AH гап, заглавие на новината, ръст за 3 месеца, стоп лимит и размер; ред, че
    проверката е отварянето, и вчерашният дневник AH срещу отваряне). Отделна стратегия — измерване, не препоръка. Старите брифове без ключовете → "". Всяка грешка → "" (имейлът не пада заради този блок).
    """
    try:
        cards, diag, ep = brief.get("qm_breakout") or [], brief.get("qm_diag") or {}, brief.get("qm_ep") or {}
        qb = (brief.get("backtest") or {}).get("qm_breakout") or {}
        if not (cards or diag or ep.get("rows") or ep.get("not_neglected") or ep.get("log") or (qb and qb.get("enabled"))):
            return ""
        ours = {c.get("ticker") for c in (brief.get("action") or []) + (brief.get("watchlist") or [])}
        td = "padding:6px 8px;border-bottom:1px solid #f3f4f6;font-size:12.5px;vertical-align:top"
        head = lambda txt: (f'<div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;font-weight:bold;margin:{{m}}px 0 4px">{txt}</div>')
        badge = ('<span style="display:inline-block;background:#eef2ff;color:#3730a3;font-size:10px;font-weight:bold;padding:1px 6px;border-radius:3px;margin-left:4px">QM✓</span>')
        body = head("Пробиви по Kullamägi (Breakout)").replace("{m}", "0")
        if cash_block(brief):                                                                                           # 23.11.2026 (т. 5)
            body += f'<div style="color:#991b1b;font-size:12.5px;font-weight:bold;margin-bottom:6px">{_e(cash_block(brief))} — картите са само за наблюдение, без размер.</div>'
        body += ('<div style="font-size:11.5px;color:#92400e;margin-bottom:8px"><b>Измерване, не препоръка. Реплеят е с survivorship (днешният универс) и резултатът зависи от малко големи печалби. '
                 'Алфата не е статистически значима.</b> ' + _qm_replay_line() + 'Отделна стратегия. Входът е по opening range high в сесията, стопът — low of day; брифът дава нивата, не самия вход.</div>')
        mk = brief.get("qm_market")                                                                                     # 03.11.2026 (т. 11, 2): QQQ спрямо SMA10 / SMA20
        if qm_breakout.nasdaq_line(mk):
            body += (f'<div style="font-size:12.5px;margin-bottom:8px"><b>{_e(qm_breakout.nasdaq_line(mk))}</b> <span style="color:#6b7280">· QQQ ${mk["close"]:.2f} на {mk["date"][8:10]}.{mk["date"][5:7]}, '
                     f'SMA10 ${mk["sma10"]:.2f}, SMA20 ${mk["sma20"]:.2f} — само информация</span></div>')
        if diag.get("ok") is False:
            body += '<div style="color:#991b1b;font-size:12.5px">Скенерът не се изпълни — празният списък НЕ значи, че няма кандидати за пробив.</div>'
        elif cards:
            rows = ""
            for c in cards:
                lv = c.get("levels")
                name = cname_t(c.get("company"), c["ticker"], 26)                         # 17.11.2026 (т. 5): никога тикърът втори път
                rows += (f'<tr><td style="{td};font-family:monospace;font-weight:bold">{_e(c["ticker"])}{badge if c["ticker"] in ours else ""}'
                         f'{f"<br><span style=font-weight:normal;font-family:Arial;color:#6b7280>{_e(name)}</span>" if name else ""}</td>'
                         f'<td style="{td};font-family:monospace;white-space:nowrap">вход над ${c["trigger"]:.2f}{f" · до нивото {c['dist_adr']:.2f} ADR" if c.get("dist_adr") is not None else ""}<br><span style="color:#6b7280">стоп (макс. {config.QM_MAX_STOP_ADR:g}×ADR) ${(lv or {}).get("stop", c["max_stop"]):.2f} '
                         f'(−{(lv or {}).get("stop_pct", c["max_risk_pct"]):.1f}%)</span></td>'
                         f'<td style="{td}">ADR {c["adr"]:.1f}% · очакван стоп ({config.QM_EXPECTED_STOP_ADR:g}×ADR) ≈ ${c["expected_stop"]:.2f}<br>'
                         f'<span style="color:#6b7280">ръст +{c["runup_pct"]:.0f}% преди базата · консолидация {c["base_days"]} дни</span>{_qm_open_html(c)}{_ew_html(c)}{_corp_html(c)}{_spinoff_html(c)}{_merger_html(c)}</td></tr>')
            body += f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>'
        else:
            body += '<div style="color:#6b7280;font-size:12.5px">Няма кандидати за пробив днес.</div>'
        if qb and qb.get("enabled") and qb.get("records"):
            avg = ("" if not (qb.get("closed") and qb.get("avg_realized_r") is not None) else
                   f" · среден R {qb['avg_realized_r']:+.2f} (5-минутни бари)" if qb.get("closed_5m") and not qb.get("closed_bounds") else      # 03.11.2026 (т. 11): един R
                   f" · среден R {qb['avg_realized_r']:+.2f} opt / {qb['avg_realized_r_pess']:+.2f} pess" + (f" ({qb['closed_5m']} от {qb['closed']} с 5-минутни бари)" if qb.get("closed_5m") else ""))
            wr = (f" · win rate {qb['win_rate_pct']}% opt / {qb['win_rate_pess_pct']}% pess" if qb.get("stats_visible") else f" · win rate след {qb.get('min_closed')} затворени")
            body += f'<div style="margin-top:8px;font-size:12px;color:#6b7280">Измерване: {qb["records"]} записа · затворени {qb.get("closed", 0)}{avg}{wr}</div>'
        eprows = ep.get("rows") or []
        if ep:
            body += head("Епизодични пивоти (EP) · гапове след новина").replace("{m}", "16")
            body += '<div style="font-size:11.5px;color:#92400e;margin-bottom:6px"><b>Само наблюдение, не препоръка.</b> Обемът в after-hours не е наличен — гапът не е потвърден до отварянето.</div>'
            for x in ep.get("sector_bounce") or []:                                   # 06.11.2026 (т. 10)
                body += f'<div style="font-size:12.5px;color:#92400e;margin-bottom:6px">{_e(x["text"])}</div>'
            if ep.get("ok") is False and not eprows:
                body += '<div style="color:#991b1b;font-size:12.5px">Наблюдението не се изпълни — празният списък НЕ значи, че няма гапове.</div>'
            elif eprows:
                rows = ""
                for r in eprows:
                    hl = (r.get("headlines") or [{}])[0].get("title") or "не е намерено заглавие"
                    lv = r.get("levels") or {}
                    sz = f" (−{lv['stop_pct']:.1f}%)" if lv.get("stop_pct") else (f" (−{r['max_stop_pct']:.1f}%)" if r.get("max_stop_pct") else "")
                    rows += (f'<tr><td style="{td};font-family:monospace;font-weight:bold">{_e(r["ticker"])}{badge if r["ticker"] in ours else ""}</td>'
                             f'<td style="{td};font-family:monospace;white-space:nowrap">AH +{r["gap_pct"]:.1f}%</td>'
                             f'<td style="{td}">{_e(hl)}' + (f'<br><b>{_e(r["earnings_text"])}</b>' if r.get("earnings_text") else "") + f'<br><span style="color:#6b7280">{_e(r.get("catalyst_label") or "Неясен катализатор")}'
                             f'{(" — " + _e(r["summary_bg"])) if r.get("summary_bg") else ""}</span>'
                             + "".join(f'<br><b style="color:#991b1b">{_e(x)}</b>' for x in _red_8k(r.get("filings_8k"))) + '</td>'
                             f'<td style="{td};white-space:nowrap">3 м. {r["ret63_pct"]:+.0f}%'
                             + (f'<br><span style="color:#92400e">{_e(_neglect_label(r["ret63_pct"], r.get("neglect")))}</span>' if r["ret63_pct"] < config.QM_EP_CRASHED_RET63_PCT else "")      # 11.11.2026 (т. 3)
                             + f'<br><span style="color:#6b7280">стоп ${r["max_stop"]:.2f}'
                             f'{sz}</span></td></tr>')
                body += f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>'
            else:
                body += '<div style="color:#6b7280;font-size:12.5px">Няма after-hours гапове ≥ 10% при „пренебрегнати“ тикъри.</div>'
            yd = (ep.get("log") or {}).get("yesterday") or []
            line = f"<b>Проверката е отварянето</b> ({setup_rules.ny_time_in_berlin(dt.date.today(), 9, 30)}): гапът се доказва едва тогава."     # 16.10.2026: от часовите зони
            if yd:
                line += " Вчера, AH срещу отваряне: " + "; ".join(
                    f'{_e(y["ticker"])} {y["ah_gap_pct"]:+.1f}% → {y["open_gap_pct"]:+.1f}% ({"издържа" if y.get("held") else "не издържа"})' for y in yd) + "."
            ypm = (ep.get("log") or {}).get("yesterday_pm") or []                    # 12.11.2026 (т. 2): гаповете от карето в 09:05 Ню Йорк
            if ypm:
                line += " Вчера, премаркет в 09:05 Ню Йорк: " + "; ".join(
                    f'{_e(y["ticker"])} {y["pm_gap_pct"]:+.1f}% → отваряне {y["open_gap_pct"]:+.1f}% ({"издържа" if y.get("held") else "не издържа"})'
                    + (f' → затваряне {y["close_pct"]:+.1f}%' if y.get("close_pct") is not None else "") for y in ypm) + "."
            body += f'<div style="margin-top:6px;font-size:12px;color:#374151">{line}</div>'
        return f'<tr><td style="padding:12px 28px 14px;border-top:1px solid #f3f4f6">{body}</td></tr>'
    except Exception as e:
        print(f"[render] имейл блокът на Qullamaggie пропуснат: {type(e).__name__}: {e}")
        return ""


def render_email(brief: dict) -> str:
    """
    Имейл = summary + линк (Секция 6.3). Inline CSS, таблична структура —
    единственото, което email клиентите рендерират надеждно. Светла тема,
    защото Gmail често чупи тъмни фонове.
    """
    today = dt.date.today()
    t = brief["thermometer"]
    # FIX 2026-09-25: при override броенето не изчезва — добавя се след причината
    regime_line = _e(t["regime_reason"]) + (
        f" · {_e(t['counts'])}" if t.get("overrides") and t.get("counts") and not t.get("rule") else "")       # 17.11.2026 (пакет 3): с правилото — само условията
    regime = t["regime"]
    color = {"Offensive": "#0e9f6e", "Defensive": "#d97706", "Cash": "#dc2626"}[regime]

    rows = ""
    for st in brief["action"]:
        p = st["plan"]
        lv = st.get("levels")                      # 07.10: вход/стоп/ADR/предупреждения; без брой акции (размерът е в браузъра на читателя)
        # FIX 2026-10-03 (пакет 1, т.3): v2 план — buy-stop с таван, стоп с процент, цел за 50%
        if p.get("method") == "v2":
            plan_txt = (f"Buy-stop ${p['buy_stop']} (таван ${p['max_chase']})<br>"
                        f"Вход ≈ ${(lv or {}).get('entry', p['entry_mid'])} · Stop ${(lv or {}).get('stop', p['stop_loss'])} (−{(lv or {}).get('stop_pct', p['risk_pct'])}%)<br>"
                        f"Цел ${p['target_1']} ({p['target_1_fraction'] * 100:.0f}%)" + _stop_rule_html(p) + _lv_warn_html(lv))
        else:
            plan_txt = (f"Entry ${p['entry_range'][0]}–{p['entry_range'][1]}<br>"
                        f"Stop ${p['stop_loss']} · Цел ${p['target_1']}" + _lv_warn_html(lv))
        mk = "".join(
            f'<span style="display:inline-block;background:#eef2ff;color:#3730a3;'
            f'font-size:10px;font-weight:bold;padding:1px 6px;border-radius:3px;'
            f'margin:3px 3px 0 0">{_e(m["tag"])}</span>'
            for m in st.get("markers", []))
        mk = f'<div style="margin-top:4px">{mk}</div>' if mk else ""
        ew = st.get("earnings_warning")
        earn_line = f'<br><span style="color:#b45309;font-size:12px">{_e(ew["text"])}</span>' if ew else ""
        if enrich_mod.no_date(st):                                                    # 06.11.2026 (т. 3)
            earn_line += f'<br><span style="color:#b45309;font-size:12px">{_e(enrich_mod.NO_DATE_TEXT)}</span>'
        earn_line += _corp_html(st) + _spinoff_html(st) + _merger_html(st) + _book_note_html(st)
        if is_trend(st):                                                              # 17.11.2026 (пакет 2, т. 1): второто ниво — с етикета
            earn_line += f'<br><span style="color:#b45309;font-size:12px">Тренд без ръст — {_e(st["tier"].get("label"))} (не е CANSLIM)</span>'
        rows += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;
                     font-family:monospace;font-weight:bold;color:{color}">{_e(st['ticker'])}{mk}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">
              {_e(cname_t(st['company'], st['ticker']))}<br>
              <span style="color:#6b7280">{_e(st['base_type'])} · RS {'нов макс' if st['rs_status']=='new_high' else 'близо до макс'}</span>{earn_line}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;
                     font-family:monospace;font-size:13px;white-space:nowrap">
              {plan_txt}</td>
        </tr>"""
    # пакет 2 т.6: предупреждения за данни (паднал Yahoo и т.н.) — червена кутия най-горе
    warnings = brief.get("data_warnings") or []
    warn_block = ""
    if warnings:
        items = "".join(f'<li style="margin-bottom:4px">{_e(w.get("message", ""))}</li>' for w in warnings)
        warn_block = ('<tr><td style="padding:14px 28px;background:#fef2f2;border-bottom:1px solid #fecaca;'
                      'font-size:12.5px;color:#991b1b"><b>⚠ Проблем с данните днес</b>'
                      f'<ul style="margin:6px 0 0;padding-left:18px">{items}</ul></td></tr>')
    screener_failed = any(w.get("source") == "screener" and w.get("level") == "error" for w in warnings)
    if not brief["action"]:
        rows = ("""<tr><td colspan="3" style="padding:14px;color:#991b1b">
                  Скринингът днес не се изпълни (липсват данни) — празният списък НЕ значи, че няма сетъпи.</td></tr>"""
                if screener_failed else
                """<tr><td colspan="3" style="padding:14px;color:#6b7280">
                  Днес няма потвърден пробив.</td></tr>""")

    waiting, radar = _watchlist_email_html(brief.get("watchlist") or [])          # 30.10.2026 (т. 9–10): „Чака пробив“ и „На радара“
    n_wait, n_radar = (len(x) for x in split_canslim(brief.get("watchlist") or []))
    wx = brief.get("watchlist_exits") or {}
    watch_exits = ("" if not wx.get("from") else
                   f'<br><b>Излязоха от {_e(watchlist_exits.label(wx, brief.get("date") or ""))}:</b> '
                   + ("; ".join(f'{_e(r["ticker"])}: {_e(r["reason"])}' + (f' (вчера: {_e(r["yesterday"])})' if r.get("yesterday") else "") for r in wx.get("rows", [])) or "няма"))
    fund_note = fundamentals_note(brief.get("screener_status"))                   # 06.11.2026 (т. 2)
    if fund_note:
        watch_exits += f'<br><span style="color:#6b7280">{_e(fund_note)}</span>'
    dot_color = {"green": "#0e9f6e", "yellow": "#d97706", "red": "#dc2626"}
    thermo_dots = "".join(
        f'<span title="{_e(i["name"])}{" (информативен, не се брои)" if i.get("informational") else ""}" '
        f'style="display:inline-block;width:{7 if i.get("informational") else 11}px;height:{7 if i.get("informational") else 11}px;'
        f'border-radius:50%;margin-right:5px;'
        + (f'border:2px solid {dot_color.get(i["status"], "#d97706")};background:#ffffff"' if i.get("informational")
           else f'background:{dot_color.get(i["status"], "#d97706")}"') + '></span>'
        for i in t["indicators"] if not i.get("hide"))        # трети преглед (16.10): скрит индикатор (status "yellow" е само запълване) НЕ е жълта точка — ред "Скрити днес"
    hidden = [i for i in t["indicators"] if i.get("hide")]
    hidden_line = ("" if not hidden else
                   '<div style="color:#6b7280;font-size:12px;margin-top:6px">Скрити днес: '
                   + " · ".join(f'{_e(i["name"])} — {_e(i.get("hide_reason") or "няма данни")}' + (" (информативен, не влиза в режима)" if i.get("informational") else "")
                                for i in hidden) + "</div>")

    # v2 · компактна секция „Сигнали днес" (Секции 3.3 + 3.4) — само ако има данни
    # FIX 2026-09-27: заглавието казваше "30 дни", а списъкът е само текущата
    # седмица; + сплитовете на отворени позиции/наблюдавани, както на dashboard-а
    sr = brief.get("splits_report") or {}
    sp = (sr.get("rows") if sr else brief.get("splits", []))[:6]
    sp_prio = sr.get("priority", [])
    signals_rows = ""
    if sp_prio:
        pr_txt = ", ".join(
            f'{_SPLIT_BADGE_EMAIL.get(s.get("badge"), "")} {_e(s["ticker"])}'
            f'{(" " + _e(s["ratio"])) if s.get("ratio") else ""} · {_e(_split_when(s))}' for s in sp_prio)
        signals_rows += (
            '<div style="margin-bottom:6px"><span style="color:#6b7280">Сплитове на отворени позиции / наблюдавани:</span> '
            f'<span style="font-family:monospace;color:#b45309">{pr_txt}</span></div>')
    if sp:
        sp_txt = ", ".join(
            f'{_e(s["ticker"])}{(" " + _e(s["ratio"])) if s.get("ratio") else ""}'
            f'{(" " + _SPLIT_BADGE_EMAIL[s["badge"]]) if s.get("badge") in _SPLIT_BADGE_EMAIL else ""}'
            for s in sp)
        signals_rows += (
            '<div><span style="color:#6b7280">Сплитове тази седмица:</span> '
            f'<span style="font-family:monospace;color:#111827">{sp_txt}</span></div>')
    signals_block = (
        f'<tr><td style="padding:8px 28px 14px;font-size:12.5px;color:#374151;'
        f'border-top:1px solid #f3f4f6">{signals_rows}</td></tr>' if signals_rows else "")

    # Значими новини (news_aggregator) — преди останалия макро анализ
    news = brief.get("news", [])[:8]
    news_block = ""
    if news:
        link = lambda n: n.get("link") if isinstance(n.get("link"), str) and n["link"].startswith(("https://", "http://")) else None
        items = "".join(
            f'<li style="margin-bottom:6px">'
            + (f'<a href="{_e(link(n))}" style="color:#111827;font-weight:bold">{_e(n.get("headline",""))}</a>' if link(n)      # 29.10.2026: заглавието е линк към статията
               else f'<b>{_e(n.get("headline",""))}</b>')                                         # 15.10.2026: дословно от източника
            + (f'<span style="color:#6b7280;font-size:12px"> · +{len(n["also"])} {"източник" if len(n["also"]) == 1 else "източника"}</span>'   # 30.10.2026: само броят, без линкове
               if isinstance(n.get("also"), list) and n["also"] else "")
            + (f'<span style="color:#6b7280"> — {_e(n["why"])}</span>' if n.get("why") else "")      # 06.11.2026 (т. 8): „защо“ може да е празно
            + news_meta_email(n) + "</li>" for n in news)
        news_block = (
            '<tr><td style="padding:16px 28px 4px">'
            '<div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;'
            'color:#6b7280;font-weight:bold;margin-bottom:8px">Значими новини</div>'
            + (f'<div style="color:#b45309;font-size:12px;margin-bottom:6px">⚠ {_e(_np["text"])}</div>'           # 23.11.2026 (т. 1): пътят на подбора
               if (_np := news_path_note(brief.get("news_diag"))) and _np["level"] == "warn" else "")
            + f'<ul style="margin:0;padding-left:18px;font-size:13px;color:#111827;line-height:1.5">{items}</ul>'
            '</td></tr>')

    qm_block = _qm_email_block(brief)

    return f"""<!DOCTYPE html>
<html lang="bg">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Инвестиционен Бриф · {today.strftime('%d.%m.%Y')}</title>
</head>
<body style="margin:0;background:#f3f4f6;font-family:'Arial','Helvetica Neue',Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden">

  <tr><td style="background:#0b1220;padding:22px 28px">
    <div style="color:#ffffff;font-size:18px;font-weight:bold">AI Инвестиционен Бриф</div>
    <div style="color:#9ca3af;font-size:12px;margin-top:4px">
      {today.strftime('%d.%m.%Y')}, {WEEKDAYS_BG[today.weekday()]}</div>
  </td></tr>

  <tr><td style="padding:20px 28px;border-bottom:1px solid #e5e7eb">
    <span style="display:inline-block;background:{color};color:#fff;font-weight:bold;
                 padding:6px 16px;border-radius:4px;font-size:14px;letter-spacing:1px">
      {_e(regime.upper())}</span>
    <span style="margin-left:12px">{thermo_dots}</span>
    <div style="color:#374151;font-size:13px;margin-top:10px">{regime_line}</div>
    {(f'<div style="color:#111827;font-size:13px;margin-top:6px"><b>Какво промени режима:</b> {_e(t["regime_change"]["text"])}</div>') if (t.get("regime_change") or {}).get("text") else ""}
    {hidden_line}
    {(f'<div style="color:#b45309;font-size:13px;margin-top:8px">📅 {_e(brief["market_calendar_note"])}</div>') if brief.get("market_calendar_note") else ""}
  </td></tr>

  {warn_block}

  {_overnight_email(brief.get("overnight"))}

  {_themes_email(brief.get("top_themes"))}

  {news_block}

  <tr><td style="padding:20px 28px;font-size:14px;color:#111827;line-height:1.6">
    {"<br><br>".join(_e(x) for x in _paragraphs(brief['ai_macro']['macro_brief'] or "")) or _e(brief['ai_macro']['macro_brief'])}
    {(f'<div style="color:#374151;font-size:13px;margin-top:8px">{_e(_put_call_line(brief))}</div>') if _put_call_line(brief) else ""}
    {_week_calendar_email(brief.get("week_calendar"))}
    {(f'<div style="color:#6b7280;font-size:12px;margin-top:8px">{_e(_futures_line(brief))}</div>') if _futures_line(brief) else ""}
  </td></tr>

  <tr><td style="padding:0 28px 8px">
    <div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;
                color:#6b7280;font-weight:bold;margin-bottom:6px">
      CANSLIM · купува се днес · {len(brief['action'])}</div>
    <table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
  </td></tr>

  <tr><td style="padding:14px 28px;font-size:13px;color:#374151">
    <b>Чака пробив · {n_wait}:</b>{waiting}
    <br><b>На радара ({n_radar}):</b>{radar}{watch_exits}
  </td></tr>

  {qm_block}

  {signals_block}

  <tr><td align="center" style="padding:24px 28px">
    <a href="{config.DASHBOARD_URL}" style="display:inline-block;background:{color};
       color:#ffffff;text-decoration:none;font-weight:bold;font-size:14px;
       padding:12px 32px;border-radius:6px">Отвори пълния dashboard →</a>
  </td></tr>

  <tr><td style="padding:16px 28px;background:#f9fafb;font-size:11px;color:#9ca3af">
    Само за информационни цели. Не е финансов съвет или инвестиционна препоръка.
    Данните идват от публични източници и могат да съдържат грешки.
  </td></tr>

</table></td></tr></table></body></html>"""
