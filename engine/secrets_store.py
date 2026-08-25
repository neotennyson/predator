from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = ROOT / "secrets.json"

DEFAULTS = {
    "dhan_client_id": "",
    "dhan_access_token": "",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "dashboard_key": "",
    "dashboard_url": "http://127.0.0.1:8787",
    "mode": "practice",
    "risk_pct": 0.05,
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(SECRETS_PATH.read_text()))
    except Exception:
        pass
    return data


def save(update: dict) -> dict:
    data = load()
    for key, value in update.items():
        if key in DEFAULTS and value is not None:
            data[key] = value
    SECRETS_PATH.write_text(json.dumps(data, indent=2))
    return data


def mask(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "•" * len(value)
    return value[:keep] + "…" + "•" * 6
