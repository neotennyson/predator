from __future__ import annotations

import os
import requests

from .secrets_store import load


def telegram_creds() -> tuple[str, str]:
    data = load()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or data.get("telegram_bot_token") or ""
    chat = os.environ.get("TELEGRAM_CHAT_ID") or data.get("telegram_chat_id") or ""
    return token, chat


def send(text: str) -> bool:
    token, chat = telegram_creds()
    if not token or not chat:
        return False
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return True
    except Exception:
        return False
