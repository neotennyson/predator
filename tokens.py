"""Self-service broker token access via the private token API.

Stdlib only. Never logs or returns the API key. Tokens are cached at
~/.broker_tokens.json (chmod 600) with a fetched_at timestamp and reused
for < 6 hours.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API_BASE = "https://tokens.example.invalid"
CACHE_PATH = Path.home() / ".broker_tokens.json"
CACHE_TTL = 6 * 3600
VALID_BROKERS = ("dhan", "groww")
_ROOT_ENV = Path(__file__).resolve().parent / ".env"


def _load_env() -> None:
    """Parse the project .env into os.environ.

    Later non-empty lines win (so an appended real key overrides an empty
    placeholder). Existing real env vars are never overridden.
    """
    try:
        raw = _ROOT_ENV.read_text()
    except OSError:
        return
    parsed: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value:
            parsed[key] = value
    for key, value in parsed.items():
        if key not in os.environ:
            os.environ[key] = value


def _api_key() -> str:
    _load_env()
    key = os.environ.get("TOKEN_API_KEY", "")
    if not key:
        raise RuntimeError(
            "TOKEN_API_KEY not set — paste the key line into the project .env"
        )
    return key


def _read_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def _write_cache(cache: dict) -> None:
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2))
    try:
        tmp.chmod(0o600)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        CACHE_PATH.write_text(json.dumps(cache, indent=2))
        try:
            CACHE_PATH.chmod(0o600)
        except OSError:
            pass


def _fetch(broker: str) -> str:
    req = urllib.request.Request(
        f"{API_BASE}/token/{broker}",
        headers={"X-API-Key": _api_key(), "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode())
    token = str(payload.get("token", "")).strip()
    if not token:
        raise RuntimeError(f"token API returned empty token for {broker}")
    cache = _read_cache()
    cache[broker] = {"token": token, "fetched_at": time.time()}
    _write_cache(cache)
    return token


def _epoch(value) -> float | None:
    """Accept epoch seconds or ISO-8601 timestamps; None if unparseable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _is_fresh(entry: dict) -> bool:
    if not entry.get("token"):
        return False
    fetched = _epoch(entry.get("fetched_at"))
    if fetched is None:
        return False
    if time.time() - fetched >= CACHE_TTL:
        return False
    expires = _epoch(entry.get("expiry"))
    if expires is not None and expires <= time.time():
        return False
    return True


def get_token(broker: str) -> str:
    """Return a cached-or-fresh token for broker ('dhan' or 'groww')."""
    broker = broker.lower().strip()
    if broker not in VALID_BROKERS:
        raise ValueError(f"unknown broker: {broker}")
    entry = _read_cache().get(broker) or {}
    if _is_fresh(entry):
        return str(entry["token"])
    return _fetch(broker)


def force_refresh(broker: str) -> str:
    """POST /refresh, wait 5s, refetch and return the regenerated token."""
    broker = broker.lower().strip()
    req = urllib.request.Request(
        f"{API_BASE}/refresh",
        headers={"X-API-Key": _api_key(), "Content-Type": "application/json", "Accept": "application/json"},
        data=json.dumps({"broker": broker}).encode(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (200, 202, 204):
            raise
    time.sleep(5)
    return _fetch(broker)


def refresh_on_auth_error(broker: str) -> str:
    """Recovery path for 401/403/token-expired: refresh once and return new token."""
    return force_refresh(broker)
