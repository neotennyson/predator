from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
MEMORY_PATH = RESULTS / "sentinel_memory.json"
RATING_PATH = RESULTS / "day_rating.json"

EVENT_WEIGHT = {
    "RBI-MPC": 2,
    "BUDGET": 2,
    "CPI+FOMC": 2,
    "US-CPI-GAP": 1,
    "US-FOMC-GAP": 1,
    "US-NFP-GAP": 1,
    "FNO-EXPIRY": 1,
    "SENSEX-EXPIRY": 1,
    "LS_RESULTS": 2,
    "EARN-HDFCBANK-GAP": 0,
    "EARN-RELIANCE-GAP": 0,
    "EARN-INFOSYS-GAP": 0,
    "EARN-TCS-GAP": 0,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def remember(items: list[dict], keep_hours: int = 48) -> None:
    mem: list[dict] = []
    try:
        mem = json.loads(MEMORY_PATH.read_text())
    except Exception:
        pass
    now = _utcnow().isoformat()
    for it in items:
        mem.append({"t": now, "s": it.get("score", 0), "d": it.get("dir", 0), "red": it.get("red", False), "title": it.get("title", "")[:140]})
    cutoff = (_utcnow() - timedelta(hours=keep_hours)).isoformat()
    mem = [m for m in mem if m.get("t", "") > cutoff]
    RESULTS.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(mem[-500:]))


def recent_sentiment(hours: int = 6) -> dict:
    try:
        mem = json.loads(MEMORY_PATH.read_text())
    except Exception:
        return {"net": 0, "count": 0, "red_recent": False}
    cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
    recent = [m for m in mem if m.get("t", "") > cutoff]
    net = sum(1 if m.get("d", 0) > 0 else (-1 if m.get("d", 0) < 0 else 0) for m in recent)
    red = any(m.get("red") for m in recent)
    return {"net": net, "count": len(recent), "red_recent": red}


def check_confluence(side: str, hours: int = 4, threshold: int = 2) -> dict:
    sent = recent_sentiment(hours)
    net = sent["net"]
    if sent["count"] < 2:
        verdict = "neutral"
    elif net >= threshold:
        verdict = "bullish"
    elif net <= -threshold:
        verdict = "bearish"
    else:
        verdict = "neutral"
    contradict = (side == "call" and verdict == "bearish") or (side == "put" and verdict == "bullish")
    confirm = (side == "call" and verdict == "bullish") or (side == "put" and verdict == "bearish")
    if contradict:
        action = "skip"
    elif confirm:
        action = "confirm"
    else:
        action = "proceed"
    return {"verdict": verdict, "net": net, "count": sent["count"], "action": action}


def rate_day(catalyst_name: str | None = None) -> dict:
    from . import data
    from .sentinel import veto_active

    reasons = []
    score = EVENT_WEIGHT.get(catalyst_name or "", 0)
    if score >= 2:
        reasons.append(f"major event {catalyst_name} (+{score})")
    elif score == 1:
        reasons.append(f"event {catalyst_name} (+1)")

    vix = None
    try:
        vix = data.get_prev_vix(date.today(), "^INDIAVIX")
    except Exception:
        pass
    if vix is None:
        reasons.append("India VIX unavailable (0)")
    elif vix < 9:
        score += 0
        reasons.append(f"India VIX {vix:.1f} too calm (+0)")
    elif vix <= 22:
        score += 1
        reasons.append(f"India VIX {vix:.1f} healthy (+1)")
    else:
        score += 0
        reasons.append(f"India VIX {vix:.1f} elevated (+0)")

    sent = recent_sentiment(hours=14)
    if sent["red_recent"] or veto_active():
        score -= 3
        reasons.append("red-flag news active (-3)")
    elif sent["count"] >= 2:
        if sent["net"] >= 2:
            score += 1
            reasons.append(f"news flow positive ({sent['net']:+d}) (+1)")
        elif sent["net"] <= -2:
            score -= 1
            reasons.append(f"news flow negative ({sent['net']:+d}) (-1)")
        else:
            reasons.append(f"news flow mixed ({sent['net']:+d}) (0)")
    else:
        reasons.append("little overnight news (0)")

    if score >= 3:
        grade, mult = "A", 1.0
    elif score >= 1:
        grade, mult = "B", 0.5
    else:
        grade, mult = "C", 0.0

    rating = {
        "date": date.today().isoformat(),
        "catalyst": catalyst_name,
        "grade": grade,
        "multiplier": mult,
        "score": score,
        "vix": vix,
        "reasons": reasons,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    RATING_PATH.write_text(json.dumps(rating))
    return rating


def get_day_multiplier() -> float:
    try:
        r = json.loads(RATING_PATH.read_text())
        if r.get("date") == date.today().isoformat():
            return float(r.get("multiplier", 1.0))
    except Exception:
        pass
    return 1.0
