from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .notify import send

ROOT = Path(__file__).resolve().parent.parent
SEEN_PATH = ROOT / "results" / "sentinel_seen.json"
STATE_PATH = ROOT / "results" / "sentinel_state.json"

FEEDS = [
    "https://news.google.com/rss/search?q=RBI+OR+Reserve+Bank+of+India+when:1d&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=NIFTY+OR+Sensex+market+when:1d&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Federal+Reserve+OR+inflation+OR+CPI+when:1d&hl=en&gl=US&ceid=US:en",
]

IMPACT_WORDS = {
    3: ["rate cut", "rate hike", "repo rate", "emergency meeting", "war", "strike", "attack",
        "crash", "plunge", "surge", "record high", "cpi", "inflation data", "gdp", "resignation",
        "default", "sanctions", "ban", "stimulus", "quantitative"],
    2: ["rbi", "federal reserve", "fed ", "powell", "governor", "finance ministry", "budget",
        "fii", "dii", "tariff", "oil prices", "rupee", "earnings"],
    1: ["market", "stocks", "sensex", "nifty", "traders", "investors", "bullish", "bearish"],
}

RED_FLAGS = ["war", "attack", "emergency meeting", "crash", "default", "resignation", "strike"]

BULLISH_WORDS = ["rate cut", "dovish", "stimulus", "rally", "surge", "record high", "upgrade", "inflows",
                 "fii buying", "jump", "soar", "beat", "growth", "boost", "recovery", "gains", "rallies",
                 "bullish", "rebound", "rises", "rise", "climbs", "strong"]
BEARISH_WORDS = ["rate hike", "hawkish", "crash", "plunge", "fall", "falls", "drop", "slump", "downgrade",
                 "outflows", "fii selling", "recession", "default", "war", "tariff", "warning", "slide",
                 "sink", "loss", "bearish", "tumbles", "tumble", "weak", "fears", "selloff", "sell-off"]


def _direction(title: str) -> int:
    t = title.lower()
    bull = sum(1 for w in BULLISH_WORDS if w in t)
    bear = sum(1 for w in BEARISH_WORDS if w in t)
    if bull > bear:
        return 1
    if bear > bull:
        return -1
    return 0


def _score(headline: str) -> int:
    h = headline.lower()
    score = 0
    for weight, words in IMPACT_WORDS.items():
        for w in words:
            if w in h:
                score += weight
    return min(score, 10)


def _is_red(headline: str) -> bool:
    h = headline.lower()
    return any(w in h for w in RED_FLAGS)


def fetch_headlines() -> list[dict]:
    out = []
    for feed in FEEDS:
        try:
            resp = requests.get(feed, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(resp.content)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                pub = item.findtext("pubDate") or ""
                link = item.findtext("link") or ""
                if title:
                    out.append({"title": title, "link": link, "pub": pub})
        except Exception:
            continue
    return out


def _load_seen() -> dict:
    try:
        return json_loads(SEEN_PATH.read_text())
    except Exception:
        return {}


def json_loads(text: str) -> dict:
    import json
    return json.loads(text)


def scan(min_score: int = 5, max_items: int = 5) -> list[dict]:
    import json

    seen = _load_seen()
    now = datetime.now(timezone.utc)
    alerts = []
    all_new = []
    red_now = False
    for item in fetch_headlines():
        key = item["title"][:120]
        if key in seen:
            continue
        score = _score(item["title"])
        seen[key] = now.isoformat()
        red = _is_red(item["title"])
        if red:
            red_now = True
        entry = {**item, "score": score, "red": red}
        all_new.append(entry)
        if score >= min_score:
            alerts.append(entry)
    cutoff = (now - timedelta(days=2)).isoformat()
    seen = {k: v for k, v in seen.items() if v > cutoff}
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen))
    alerts.sort(key=lambda a: -a["score"])
    try:
        from .validation import remember
        remember([{**a, "dir": _direction(a["title"])} for a in all_new])
    except Exception:
        pass
    for a in alerts[:max_items]:
        flag = " 🚨RED FLAG" if a["red"] else ""
        arrow = "▲" if a.get("dir", 0) > 0 else ("▼" if a.get("dir", 0) < 0 else "•")
        send(f"📰 <b>IMPACT {a['score']}/10</b> {arrow}{flag}\n{a['title']}")
    if red_now:
        state = {"red_until": (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()}
        STATE_PATH.write_text(json.dumps(state))
        send("🚨 <b>RED FLAG active — engine entries vetoed for 45 min.</b>")
    return alerts


def veto_active() -> bool:
    try:
        import json

        state = json.loads(STATE_PATH.read_text())
        until = datetime.fromisoformat(state.get("red_until", "2000-01-01T00:00:00+00:00"))
        return datetime.now(timezone.utc) < until
    except Exception:
        return False


def run_forever(poll_seconds: int = 180):
    print(f"sentinel on — polling news every {poll_seconds}s")
    send("🛰️ News sentinel online — watching headlines for the predator.")
    while True:
        try:
            found = scan()
            if found:
                print(f"[{datetime.now().strftime('%H:%M')}] {len(found)} impact headlines")
        except Exception as exc:
            print(f"sentinel error: {exc}")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    run_forever()
