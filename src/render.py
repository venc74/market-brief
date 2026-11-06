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
env.filters["cname"] = names.display_name            # 08.10: име на компания за показване — без правни окончания, рязане по граница на дума с «…»


def cot_label(c: dict) -> str:
    """26.10.2026 (етап 4б, т. 8): етикетът на COT реда по знака на нетната позиция (cot.position_label) — и за стар бриф без полето."""
    from src import cot
    c = c or {}
    return c.get("position_label") or cot.position_label(c.get("direction"), c.get("net_position", c.get("net")), c.get("percentile"), c.get("weeks_of_history", c.get("weeks")))


env.filters["cot_label"] = cot_label


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


def _paragraphs(text: str) -> list[str]:
    """29.10.2026: абзаците на макро разказа — разделени с празен ред (същото като ai_brief.paragraphs; тук без зависимост от ai_brief)."""
    return [x.strip() for x in re.split(r"\n\s*\n", text or "") if x.strip()]


def _e(x) -> str:
    """HTML escape на външен/AI текст за имейла (f-string HTML, където Jinja autoescape не важи)."""
    return _html.escape("" if x is None else str(x), quote=True)


def _money_short(v):
    """1234567 → '$1.2 млн' (за стойности на superinvestor сделки)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    for unit, div in (("млрд", 1e9), ("млн", 1e6), ("хил", 1e3)):
        if abs(v) >= div:
            return f"${v / div:.1f} {unit}"
    return f"${v:.0f}"


env.filters["money_short"] = _money_short




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
    return f'<br><span style="color:#1d4ed8;font-size:12px">📈 вече отворена в книгата от {b["since"][8:10]}.{b["since"][5:7]}{price} — новото ниво не е нов вход</span>'


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


def radar_reason(c: dict) -> str:
    """
    30.10.2026 (разходката, т. 9–10): причината на реда в „На радара“ — от кода, с числото: „широк стоп · 15.3%“ (too_wide; до 02.11 „разтегната · стоп“), „пробив без обем · 0.9×“, „блокирана от режима“,
    отчет в прозореца, запис в книгата, сделка; неутралният ред за жив запис в buy-stop книгата (setup.book_note) — след нея, както в досегашния компактен ред. Чиста функция.
    """
    why = _radar_reason(c)
    note = (c.get("setup") or {}).get("book_note")
    return f"{why}; {note}" if note and note not in why else why


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


def thirteenf_rows(moves: list[dict] | None, exits: dict | None, ours: list[str] | None) -> list[dict]:
    """
    03.11.2026 (разходката, т. 18–19): една таблица за 13F — по ред на (мениджър, тикър): {manager, ticker, company, action ("нова" / "увеличена" / "изход"), value, pct_of_portfolio,
    change_pct, in_screener, late, period, ticker_source, cusip}. Покупките — по стойност (собственият ред на всеки мениджър, dataroma "by_manager"; стар бриф без него — редът на тикъра,
    мениджърът с „+N“), после изходите по стойност в предишния 13F (промяна −100%, делът — в предишния портфейл). Чиста функция.
    """
    ours = set(ours or [])
    base = lambda r: {"ticker": r.get("ticker"), "company": r.get("company"), "in_screener": r.get("ticker") in ours, "ticker_source": r.get("ticker_source"), "cusip": r.get("cusip")}
    word = lambda a: "нова" if a == "нова позиция" else (a or "—")
    buys = []
    for r in moves or []:
        own = r.get("by_manager")
        if own:
            buys += [{**base(r), "manager": m.get("manager"), "action": word(m.get("action")), "value": m.get("value"), "pct_of_portfolio": m.get("pct_of_portfolio"),
                      "change_pct": m.get("change_pct"), "late": m.get("late"), "period": m.get("period")} for m in own]
        else:
            extra = (r.get("count") or 1) - 1
            buys.append({**base(r), "manager": (r.get("manager") or "—") + (f" +{extra}" if extra > 0 else ""), "action": word(r.get("action")), "value": r.get("value"),
                         "pct_of_portfolio": r.get("pct_of_portfolio"), "change_pct": r.get("change_pct"), "late": r.get("late"), "period": r.get("period")})
    gone = [{**base(r), "manager": r.get("manager"), "action": "изход", "value": r.get("prior_value"), "pct_of_portfolio": r.get("prior_pct_of_portfolio"), "change_pct": -100.0,
             "late": r.get("late"), "period": r.get("period")} for r in (exits or {}).get("exits") or []]
    by_value = lambda x: -(x.get("value") or 0)
    return sorted(buys, key=by_value) + sorted(gone, key=by_value)


env.globals["thirteenf_rows"] = thirteenf_rows


def fundamentals_note(status: dict | None) -> str | None:
    """06.11.2026 (пакет 05–06.11, т. 2): редът „фундаментите не са проверени за N имена“ и кои са с най-висок RS (screener.LAST_STATUS["fundamentals_not_checked"]). Няма такива / стар бриф → None. Чиста функция."""
    nc = (status or {}).get("fundamentals_not_checked") or {}
    n = nc.get("n")
    if not n:
        return None
    top = ", ".join(f'{x["ticker"]} (RS {x["rs_rating"]})' for x in nc.get("top") or [] if x.get("ticker"))
    return (f'Фундаментите не са проверени за {n} {"име" if n == 1 else "имена"} (таван {nc.get("max")} заради Yahoo — проверяват се най-силните по RS)'
            + (f'; с най-висок RS от тях: {top}' if top else "") + " — те не са в списъците по-горе.")


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
    gen_time, gen_tz = generated or berlin_clock()         # един вик — часът и етикетът са от един и същи момент
    html = tpl.render(
        closed_notice=closed_notice,
        calendar_note=brief.get("market_calendar_note"),      # 16.10.2026 (В2б): утре / в понеделник борсата не работи или затваря рано
        preopen=brief.get("preopen"), preopen_gap=config.PREOPEN_GAP_PCT, preopen_watch_gap=config.PREOPEN_WATCH_GAP_PCT,    # 03.11.2026 (т. 10): карето преди отварянето
        date_human=f"{today.strftime('%d.%m.%Y')}, {WEEKDAYS_BG[today.weekday()]}",
        generated_at=gen_time,
        generated_tz=gen_tz,
        premarket_note=premarket_note(),
        ny_open_berlin=setup_rules.ny_time_in_berlin(today, 9, 30),            # 16.10.2026: "Проверката е отварянето (15:30 CEST / 09:30 ET)" — от часовите зони
        regime=brief["thermometer"]["regime"],
        regime_reason=brief["thermometer"]["regime_reason"],
        thermometer=brief["thermometer"],
        macro_brief=brief["ai_macro"]["macro_brief"],
        futures_line=_futures_line(brief),                                  # 19.10.2026: договорът и часът на цената на фючърсите (WTI …) — от кода
        macro_paragraphs=_paragraphs(brief["ai_macro"].get("macro_brief") or ""),   # 29.10.2026: разказът по абзаци; regime_comment е махнат
        sector_logic=brief["ai_macro"].get("sector_logic", []),
        fundamentals_note=fundamentals_note(brief.get("screener_status")),   # 06.11.2026 (т. 2)
        no_date_text=enrich_mod.NO_DATE_TEXT,                                # 06.11.2026 (т. 3)
        sector_board=brief.get("sector_board") or {}, sector_board_lag=config.SECTOR_BOARD_RANK_LAG,   # 30.10.2026 (т. 7): секторната карта от кода
        rs_dz=config.RS_WORD_DEAD_ZONE,                                          # 30.10.2026 (т. 7): мъртвата зона на RS (сиво, „в крак с пазара“)
        sector_card=brief.get("sector_card") or {},                             # 19.10.2026 (т. 18): водещите по кода; без него (стар бриф) — веригите на модела
        action=brief["action"],
        watchlist=brief["watchlist"],                                          # 30.10.2026 (т. 9–10): целият Watchlist (за „наш“ при QM / GLB — до 30.10 без компактните редове)
        waiting=split_canslim(brief["watchlist"])[0],                         # 30.10.2026 (т. 9–10): „Чака пробив“ — карти с buy-stop
        radar=split_canslim(brief["watchlist"])[1],                           # „На радара (N)“ — сгъната таблица, причината от кода
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
        superinvestor_moves=brief.get("superinvestor_moves", []),
        superinvestor_exits=brief.get("superinvestor_exits", {"exits": [], "stopped_managers": []}),
        dataroma_major_exit_pct=config.DATAROMA_MAJOR_EXIT_PCT,
        superinvestor_status=brief.get("superinvestor_status") or {},
        thirteenf_rhythm=brief.get("thirteenf_rhythm") or {},          # 21.10 (етап 4): ред и свити секции без нов 13F
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
        qm_ep_gap=config.QM_EP_GAP_PCT, qm_ep_neglect=config.QM_EP_NEGLECT_RET63_PCT, qm_ep_stop_adr=config.QM_EP_STOP_ADR,
        news=brief.get("news", []),
        news_window_note=news_window_note(brief.get("news_window")),     # 02.11.2026 (т. 4): прозорецът и обхватът на източниците
        news_h=news_window_hours(brief.get("news_window")), crypto_h=news_window_hours(brief.get("news_window"), "crypto_hours"),
        crypto_window_note=crypto_window_note(brief.get("news_window"), (brief.get("crypto") or {}).get("pool_sources")),     # 04.11.2026 (С5)
        crypto=brief.get("crypto") or {},                              # 22.10.2026 (етап 4): крипто секцията
        cot=brief.get("cot", []),
        cot_status=brief.get("cot_status") or {},
        cot_rhythm=brief.get("cot_rhythm") or {},                   # 21.10 (етап 4): ред „без нови данни“ в дните след първия бриф с отчета
        cot_summary=brief.get("cot_summary"),
        cot_all=brief.get("cot_all") or [],                         # 03.11.2026 (т. 17): всички 40 пазара — сгънатата таблица
        cot_low=config.COT_PERCENTILE_LOW, cot_high=config.COT_PERCENTILE_HIGH, cot_confirm_weeks=config.COT_CONFIRM_LOOKBACK_WEEKS,
        correlation_flags=brief.get("correlation_flags", []),
        short_frozen=(brief.get("short_tracker") or {}).get("frozen") or {},     # 19.10.2026 (т. 19): замразеният short модул — един ред
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
                name = c.get("company") if c.get("company") and c.get("company") != c["ticker"] else ""
                rows += (f'<tr><td style="{td};font-family:monospace;font-weight:bold">{_e(c["ticker"])}{badge if c["ticker"] in ours else ""}'
                         f'{f"<br><span style=font-weight:normal;font-family:Arial;color:#6b7280>{_e(names.display_name(name, 26))}</span>" if name else ""}</td>'
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
                             f'<td style="{td}">{_e(hl)}<br><span style="color:#6b7280">{_e(r.get("catalyst_label") or "Неясен катализатор")}'
                             f'{(" — " + _e(r["summary_bg"])) if r.get("summary_bg") else ""}</span></td>'
                             f'<td style="{td};white-space:nowrap">3 м. {r["ret63_pct"]:+.0f}%<br><span style="color:#6b7280">стоп ${r["max_stop"]:.2f}'
                             f'{sz}</span></td></tr>')
                body += f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>'
            else:
                body += '<div style="color:#6b7280;font-size:12.5px">Няма after-hours гапове ≥ 10% при „пренебрегнати“ тикъри.</div>'
            yd = (ep.get("log") or {}).get("yesterday") or []
            line = f"<b>Проверката е отварянето</b> ({setup_rules.ny_time_in_berlin(dt.date.today(), 9, 30)}): гапът се доказва едва тогава."     # 16.10.2026: от часовите зони
            if yd:
                line += " Вчера, AH срещу отваряне: " + "; ".join(
                    f'{_e(y["ticker"])} {y["ah_gap_pct"]:+.1f}% → {y["open_gap_pct"]:+.1f}% ({"издържа" if y.get("held") else "не издържа"})' for y in yd) + "."
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
        f" · {_e(t['counts'])}" if t.get("overrides") and t.get("counts") else "")
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
        rows += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;
                     font-family:monospace;font-weight:bold;color:{color}">{_e(st['ticker'])}{mk}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">
              {_e(names.display_name(st['company']))}<br>
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
    si = brief.get("superinvestor_moves", [])[:8]
    if si:
        si_txt = ", ".join(dict.fromkeys(_e(r.get("ticker") or f'без тикър ({names.display_name(r.get("company") or "")})') for r in si))     # 19.10.2026: неразпознат CUSIP/име
        signals_rows += (
            '<div style="margin-top:6px"><span style="color:#6b7280">Superinvestor покупки (13F):</span> '
            f'<span style="font-family:monospace;color:#111827">{si_txt}</span></div>')
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
            + f'<span style="color:#6b7280"> — {_e(n.get("why",""))}</span></li>' for n in news)
        news_block = (
            '<tr><td style="padding:16px 28px 4px">'
            '<div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;'
            'color:#6b7280;font-weight:bold;margin-bottom:8px">Значими новини</div>'
            f'<ul style="margin:0;padding-left:18px;font-size:13px;color:#111827;line-height:1.5">{items}</ul>'
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

  {news_block}

  <tr><td style="padding:20px 28px;font-size:14px;color:#111827;line-height:1.6">
    {"<br><br>".join(_e(x) for x in _paragraphs(brief['ai_macro']['macro_brief'] or "")) or _e(brief['ai_macro']['macro_brief'])}
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
