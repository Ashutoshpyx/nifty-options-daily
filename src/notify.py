"""Optional Telegram message. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (as GitHub secrets) to enable."""
import os

import requests


def send(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text}, timeout=20)
        return r.status_code == 200
    except Exception:
        return False
