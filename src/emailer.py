"""
Имейл доставка: Gmail SMTP с app password (по подразбиране — нула
зависимости) или SendGrid API (free tier, 100 имейла/ден).
"""
from __future__ import annotations
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


def send_brief(html: str, subject: str) -> bool:
    if not config.EMAIL_TO:
        print("[email] EMAIL_TO липсва — пропускам доставка")
        return False
    if config.EMAIL_METHOD == "sendgrid":
        return _send_sendgrid(html, subject)
    return _send_smtp(html, subject)


def _send_smtp(html: str, subject: str) -> bool:
    if not (config.GMAIL_USER and config.GMAIL_APP_PASSWORD):
        print("[email] GMAIL_USER / GMAIL_APP_PASSWORD липсват")
        return False
    msg = MIMEMultipart("alternative")
    # кирилицата в Subject се енкодва по RFC2047, иначе темата излиза нечетима
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = config.GMAIL_USER
    msg["To"] = config.EMAIL_TO
    # MIMEText с "utf-8" дава Content-Type: text/html; charset="utf-8"
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            s.sendmail(config.GMAIL_USER, [config.EMAIL_TO], msg.as_string())
        print(f"[email] изпратен до {config.EMAIL_TO}")
        return True
    except Exception as e:
        print(f"[email] SMTP failed: {e}")
        return False


def _send_sendgrid(html: str, subject: str) -> bool:
    if not config.SENDGRID_API_KEY:
        print("[email] SENDGRID_API_KEY липсва")
        return False
    try:
        r = requests.post("https://api.sendgrid.com/v3/mail/send", headers={
            "Authorization": f"Bearer {config.SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        }, json={
            "personalizations": [{"to": [{"email": config.EMAIL_TO}]}],
            "from": {"email": config.GMAIL_USER or "brief@example.com",
                     "name": "AI Инвестиционен Бриф"},
            "subject": subject,
            # SendGrid праща UTF-8 по подразбиране; charset идва от <meta> в HTML-а.
            # (полето type очаква чист MIME type — "; charset" може да върне 400)
            "content": [{"type": "text/html", "value": html}],
        }, timeout=30)
        r.raise_for_status()
        print(f"[email] SendGrid → {config.EMAIL_TO}")
        return True
    except Exception as e:
        print(f"[email] SendGrid failed: {e}")
        return False
