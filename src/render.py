"""
Рендериране: dashboard HTML (docs/index.html за GitHub Pages)
+ архивно копие docs/archive/YYYY-MM-DD.html + имейл HTML.
"""
from __future__ import annotations
import datetime as dt
from jinja2 import Environment, FileSystemLoader

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

WEEKDAYS_BG = ["понеделник", "вторник", "сряда", "четвъртък",
               "петък", "събота", "неделя"]

env = Environment(loader=FileSystemLoader(config.ROOT / "templates"),
                  autoescape=False)


def render_dashboard(brief: dict) -> str:
    today = dt.date.today()
    tpl = env.get_template("dashboard.html.j2")
    html = tpl.render(
        date_human=f"{today.strftime('%d.%m.%Y')}, {WEEKDAYS_BG[today.weekday()]}",
        generated_at=dt.datetime.now().strftime("%H:%M"),
        regime=brief["thermometer"]["regime"],
        regime_reason=brief["thermometer"]["regime_reason"],
        thermometer=brief["thermometer"],
        macro_brief=brief["ai_macro"]["macro_brief"],
        regime_comment=brief["ai_macro"].get("regime_comment", ""),
        sector_logic=brief["ai_macro"].get("sector_logic", []),
        action=brief["action"],
        watchlist=brief["watchlist"],
    )
    config.DOCS_DIR.mkdir(exist_ok=True)
    (config.DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
    archive = config.DOCS_DIR / "archive"
    archive.mkdir(exist_ok=True)
    (archive / f"{today.isoformat()}.html").write_text(html, encoding="utf-8")
    return html


def render_email(brief: dict) -> str:
    """
    Имейл = summary + линк (Секция 6.3). Inline CSS, таблична структура —
    единственото, което email клиентите рендерират надеждно. Светла тема,
    защото Gmail често чупи тъмни фонове.
    """
    today = dt.date.today()
    t = brief["thermometer"]
    regime = t["regime"]
    color = {"Offensive": "#0e9f6e", "Defensive": "#d97706", "Cash": "#dc2626"}[regime]

    rows = ""
    for st in brief["action"]:
        p = st["plan"]
        rows += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;
                     font-family:monospace;font-weight:bold;color:{color}">{st['ticker']}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:13px">
              {st['company']}<br>
              <span style="color:#6b7280">{st['base_type']} · RS {'нов макс' if st['rs_status']=='new_high' else 'близо до макс'}</span></td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;
                     font-family:monospace;font-size:13px;white-space:nowrap">
              Entry ${p['entry_range'][0]}–{p['entry_range'][1]}<br>
              Stop ${p['stop_loss']} · Цел ${p['target_1']}<br>
              {p['shares']} акции (${p['total_investment']:,.0f})</td>
        </tr>"""
    if not brief["action"]:
        rows = """<tr><td colspan="3" style="padding:14px;color:#6b7280">
                  Днес няма Action кандидати. Кешът е позиция.</td></tr>"""

    watch = ", ".join(st["ticker"] for st in brief["watchlist"]) or "—"
    dot_color = {"green": "#0e9f6e", "yellow": "#d97706", "red": "#dc2626"}
    thermo_dots = "".join(
        f'<span title="{i["name"]}" style="display:inline-block;width:11px;height:11px;'
        f'border-radius:50%;margin-right:5px;background:{dot_color.get(i["status"], "#d97706")}"></span>'
        for i in t["indicators"])

    return f"""<!DOCTYPE html>
<html lang="bg"><body style="margin:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif">
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
      {regime.upper()}</span>
    <span style="margin-left:12px">{thermo_dots}</span>
    <div style="color:#374151;font-size:13px;margin-top:10px">{t['regime_reason']}</div>
  </td></tr>

  <tr><td style="padding:20px 28px;font-size:14px;color:#111827;line-height:1.6">
    {brief['ai_macro']['macro_brief']}
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
