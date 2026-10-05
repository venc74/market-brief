"""
Рендериране: dashboard HTML (docs/index.html за GitHub Pages)
+ архивно копие docs/archive/YYYY-MM-DD.html + имейл HTML.
"""
from __future__ import annotations
import datetime as dt
import html as _html
from jinja2 import Environment, FileSystemLoader

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

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


def render_dashboard(brief: dict) -> str:
    today = dt.date.today()
    tpl = env.get_template("dashboard.html.j2")
    gen_time, gen_tz = berlin_clock()                      # един вик — часът и етикетът са от един и същи момент
    html = tpl.render(
        date_human=f"{today.strftime('%d.%m.%Y')}, {WEEKDAYS_BG[today.weekday()]}",
        generated_at=gen_time,
        generated_tz=gen_tz,
        regime=brief["thermometer"]["regime"],
        regime_reason=brief["thermometer"]["regime_reason"],
        thermometer=brief["thermometer"],
        macro_brief=brief["ai_macro"]["macro_brief"],
        regime_comment=brief["ai_macro"].get("regime_comment", ""),
        sector_logic=brief["ai_macro"].get("sector_logic", []),
        action=brief["action"],
        watchlist=brief["watchlist"],
        # v2 нови блокове
        theses=brief.get("theses", []),
        watch=brief.get("watch", []),
        model_info=brief.get("model_info", {}),
        ai_truncations=brief.get("ai_truncations", []),
        data_warnings=brief.get("data_warnings", []),
        unusual_options=brief.get("unusual_options", []),
        unusual_options_diag=brief.get("unusual_options_diag"),
        unusual_min_ratios=config.UNUSUAL_OPTIONS_MIN_RATIOS,
        buy_stop_window=config.BUY_STOP_WINDOW_SESSIONS,          # пакет 1б: текстът на блока за buy-stop кандидатите
        buyable_zone_pct=config.BUYABLE_ZONE_MAX_PCT,
        splits=brief.get("splits", []),
        splits_report=brief.get("splits_report"),
        splits_min_price=config.SPLITS_MIN_PRICE,
        splits_min_cap_m=config.SPLITS_MIN_MARKET_CAP / 1e6,
        superinvestor_moves=brief.get("superinvestor_moves", []),
        superinvestor_exits=brief.get("superinvestor_exits", {"exits": [], "stopped_managers": []}),
        dataroma_major_exit_pct=config.DATAROMA_MAJOR_EXIT_PCT,
        insider_buying=brief.get("insider_buying", []),
        insider_status=brief.get("insider_buying_status") or {},
        superinvestor_status=brief.get("superinvestor_status") or {},
        glb_candidates=brief.get("glb_candidates", []),
        news=brief.get("news", []),
        cot=brief.get("cot", []),
        cot_status=brief.get("cot_status") or {},
        cot_summary=brief.get("cot_summary"),
        correlation_flags=brief.get("correlation_flags", []),
        distribution_days=brief.get("distribution_days"),
        core_inflation=(brief.get("macro") or {}).get("core_inflation"),
        backtest=brief.get("backtest", {}),
        available_dates=brief.get("date") and [brief.get("date")],
    )
    config.DOCS_DIR.mkdir(exist_ok=True)
    (config.DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
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
        # FIX 2026-10-03 (пакет 1, т.3): v2 план — buy-stop с таван, стоп с процент, цел за 50%
        if p.get("method") == "v2":
            plan_txt = (f"Buy-stop ${p['buy_stop']} (таван ${p['max_chase']})<br>"
                        f"Stop ${p['stop_loss']} (−{p['risk_pct']}%) · Цел ${p['target_1']} ({p['target_1_fraction'] * 100:.0f}%)<br>"
                        f"{p['shares']} акции (${p['total_investment']:,.0f})")
        else:
            plan_txt = (f"Entry ${p['entry_range'][0]}–{p['entry_range'][1]}<br>"
                        f"Stop ${p['stop_loss']} · Цел ${p['target_1']}<br>"
                        f"{p['shares']} акции (${p['total_investment']:,.0f})")
        mk = "".join(
            f'<span style="display:inline-block;background:#eef2ff;color:#3730a3;'
            f'font-size:10px;font-weight:bold;padding:1px 6px;border-radius:3px;'
            f'margin:3px 3px 0 0">{_e(m["tag"])}</span>'
            for m in st.get("markers", []))
        mk = f'<div style="margin-top:4px">{mk}</div>' if mk else ""
        rows += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;
                     font-family:monospace;font-weight:bold;color:{color}">{_e(st['ticker'])}{mk}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">
              {_e(st['company'])}<br>
              <span style="color:#6b7280">{_e(st['base_type'])} · RS {'нов макс' if st['rs_status']=='new_high' else 'близо до макс'}</span></td>
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
                  Днес няма Action кандидати. Кешът е позиция.</td></tr>""")

    watch = ", ".join(_e(st["ticker"]) for st in brief["watchlist"]) or "—"
    dot_color = {"green": "#0e9f6e", "yellow": "#d97706", "red": "#dc2626"}
    thermo_dots = "".join(
        f'<span title="{_e(i["name"])}{" (информативен, не се брои)" if i.get("informational") else ""}" '
        f'style="display:inline-block;width:{7 if i.get("informational") else 11}px;height:{7 if i.get("informational") else 11}px;'
        f'border-radius:50%;margin-right:5px;'
        + (f'border:2px solid {dot_color.get(i["status"], "#d97706")};background:#ffffff"' if i.get("informational")
           else f'background:{dot_color.get(i["status"], "#d97706")}"') + '></span>'
        for i in t["indicators"])

    # v2 · компактна секция „Сигнали днес" (Секции 3.3 + 3.4) — само ако има данни
    uo = [r["ticker"] for r in brief.get("unusual_options", [])][:8]
    # FIX 2026-09-27: заглавието казваше "30 дни", а списъкът е само текущата
    # седмица; + сплитовете на отворени позиции/наблюдавани, както на dashboard-а
    sr = brief.get("splits_report") or {}
    sp = (sr.get("rows") if sr else brief.get("splits", []))[:6]
    sp_prio = sr.get("priority", [])
    signals_rows = ""
    if uo:
        signals_rows += (
            '<div style="margin-bottom:6px"><span style="color:#6b7280">Необичаен опционен обем:</span> '
            f'<span style="font-family:monospace;color:#111827">{", ".join(_e(x) for x in uo)}</span></div>')
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
        si_txt = ", ".join(dict.fromkeys(_e(r["ticker"]) for r in si))
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
        items = "".join(
            f'<li style="margin-bottom:6px"><b>{_e(n.get("headline",""))}</b>'
            f'<span style="color:#6b7280"> — {_e(n.get("why",""))}</span></li>' for n in news)
        news_block = (
            '<tr><td style="padding:16px 28px 4px">'
            '<div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;'
            'color:#6b7280;font-weight:bold;margin-bottom:8px">Значими новини</div>'
            f'<ul style="margin:0;padding-left:18px;font-size:13px;color:#111827;line-height:1.5">{items}</ul>'
            '</td></tr>')

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
  </td></tr>

  {warn_block}

  {news_block}

  <tr><td style="padding:20px 28px;font-size:14px;color:#111827;line-height:1.6">
    {_e(brief['ai_macro']['macro_brief'])}
  </td></tr>

  <tr><td style="padding:0 28px 8px">
    <div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;
                color:#6b7280;font-weight:bold;margin-bottom:6px">
      Action · {len(brief['action'])} тикъра</div>
    <table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
  </td></tr>

  <tr><td style="padding:14px 28px;font-size:13px;color:#374151">
    <b>Watchlist:</b> <span style="font-family:monospace">{watch}</span>
  </td></tr>

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
