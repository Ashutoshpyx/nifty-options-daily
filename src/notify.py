"""Sends the daily brief to Gmail (with the full dashboard attached).

Set these as GitHub secrets to enable it:
  GMAIL_ADDRESS       the Gmail address that sends the mail
  GMAIL_APP_PASSWORD  16-character Google App Password (NOT your normal password)
  EMAIL_TO            where to receive it (can be the same address; commas allowed for several)

Telegram still works if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set. Both are optional.
"""
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent


def _send_email(text):
    user = os.getenv("GMAIL_ADDRESS", "").strip()
    pwd = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    to = os.getenv("EMAIL_TO", "").strip() or user
    if not (user and pwd and to):
        return False
    try:
        msg = EmailMessage()
        first_line = text.splitlines()[0].lstrip("# ").strip() if text else "Nifty options brief"
        msg["Subject"] = first_line or "Nifty options brief"
        msg["From"] = user
        msg["To"] = to
        msg.set_content(text + "\n\nFull dashboard is attached. Open it in your browser.")
        page = ROOT / "docs" / "index.html"
        if page.exists():
            msg.add_attachment(page.read_bytes(), maintype="text", subtype="html",
                               filename="nifty_report.html")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
        print("Email sent to", to)
        return True
    except Exception as e:
        print("Email failed:", e)
        return False


def _send_telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text}, timeout=20)
        return r.status_code == 200
    except Exception:
        return False


def send(text):
    ok_email = _send_email(text)
    ok_tg = _send_telegram(text)
    return ok_email or ok_tg
