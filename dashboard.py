from __future__ import annotations

import csv
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from engine import calendar as cal_us
from engine import calendar_in
from engine.secrets_store import load as secrets_load, save as secrets_save, mask as secrets_mask

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
STATIC = ROOT / "static"

app = FastAPI(title="PREDATOR")

state = {
    "proc": None,
    "log": deque(maxlen=800),
    "lock": threading.Lock(),
    "meta": {},
    "phase": "standby",
    "position": None,
    "session_pnl": 0.0,
    "last_action": None,
    "alerts": [],
}


def _parse_stream(text: str) -> None:
    low = text.lower()
    if "engine armed" in low:
        state["phase"] = "watching"
        state["last_action"] = "Engine armed — waiting for breakout"
    elif low.startswith("open ") or " OPEN " in text:
        state["phase"] = "in_position"
        side = "CALL" if "CALL" in text else "PUT"
        m = re.search(r"strike=([\d.]+)", text)
        state["position"] = {"side": side, "strike": m.group(1) if m else "—"}
        state["last_action"] = text
    elif "tp1 hit" in low:
        state["phase"] = "managing"
        state["last_action"] = text
    elif low.startswith("close [") or "CLOSE [" in text:
        m = re.search(r"total_pnl=(-?[\d.]+)", text)
        if m:
            state["session_pnl"] += float(m.group(1))
        state["phase"] = "done"
        state["position"] = None
        state["last_action"] = text
    elif "no trade today" in low or "session over" in low or "not a catalyst day" in low:
        state["phase"] = "done"
        state["last_action"] = text if "not a catalyst" not in low else "Not a catalyst day — engine idle"
    elif "live order" in low:
        state["last_action"] = text
    elif "failed" in low or "error" in low:
        state["alerts"].append(text[:200])
        if len(state["alerts"]) > 10:
            state["alerts"] = state["alerts"][-10:]


def _reader(proc: subprocess.Popen) -> None:
    for line in iter(proc.stdout.readline, ""):
        text = line.rstrip()
        with state["lock"]:
            state["log"].append(text)
            _parse_stream(text)
        try:
            log_path = RESULTS / "engine_live.log"
            if log_path.exists() and log_path.stat().st_size > 1_000_000:
                rotated = RESULTS / "engine_live.log.1"
                rotated.unlink(missing_ok=True)
                log_path.replace(rotated)
            with open(log_path, "a") as fh:
                fh.write(text + "\n")
        except Exception:
            pass
    with state["lock"]:
        state["proc"] = None
        if state["phase"] in ("watching", "in_position", "managing"):
            state["phase"] = "done"


class StartReq(BaseModel):
    market: str = "in"
    live: bool = False
    risk_pct: float = 0.05


class SecretsReq(BaseModel):
    dhan_client_id: str | None = None
    dhan_access_token: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    dashboard_key: str | None = None
    dashboard_url: str | None = None
    mode: str | None = None
    risk_pct: float | None = None


def _guard(key_header: str | None) -> None:
    key = secrets_load().get("dashboard_key")
    if key and key_header != key:
        raise HTTPException(status_code=401, detail="bad engine key")


@app.post("/api/start")
def start_engine(req: StartReq, x_engine_key: str | None = Header(default=None)):
    _guard(x_engine_key)
    with state["lock"]:
        if state["proc"] is not None:
            return JSONResponse({"ok": False, "error": "engine already running"}, status_code=400)
        cmd = [sys.executable, "-u", str(ROOT / "run_predator.py"), "--market", req.market, "--risk-pct", str(req.risk_pct)]
        if req.live:
            cmd.append("--live")
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=os.environ.copy())
        state["proc"] = proc
        state["meta"] = {"market": req.market, "live": req.live, "risk_pct": req.risk_pct, "pid": proc.pid, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        state["log"].clear()
        state["phase"] = "starting"
        state["position"] = None
        state["session_pnl"] = 0.0
        state["last_action"] = "Engine launching…"
        state["alerts"] = []
        threading.Thread(target=_reader, args=(proc,), daemon=True).start()
    return {"ok": True}


@app.post("/api/stop")
def stop_engine(x_engine_key: str | None = Header(default=None)):
    _guard(x_engine_key)
    with state["lock"]:
        proc = state["proc"]
        if proc is None:
            return {"ok": False, "error": "not running"}
        proc.terminate()
        state["last_action"] = "Stop requested by user"
    return {"ok": True}


EVENTS_INFO = {
    "RBI-MPC": {
        "title": "RBI Interest Rate Decision",
        "what": "The Reserve Bank of India announces whether it is raising, cutting or holding the repo rate, plus its official view on inflation and the economy.",
        "why": "Rate decisions reprice the whole market within minutes. NIFTY regularly swings 0.5-1.5% in the hour after the 10 AM announcement. Prime hunting day.",
    },
    "FNO-EXPIRY": {
        "title": "Options Expiry Day",
        "what": "NIFTY weekly options contracts officially expire today at 3:30 PM. Every trader holding them must close, roll or let them die — forcing heavy buying and selling all day.",
        "why": "Forced flows + exploding option gamma = wildest intraday ranges of the week. The engine's 0DTE trades are literally built for this day.",
    },
    "CPI": {
        "title": "US Inflation Report (CPI)",
        "what": "America's official inflation number drops at 8:30 AM ET. Hotter-than-expected inflation = US markets fall; cooler = they rally.",
        "why": "Moves US markets overnight; NIFTY reacts the next morning through gap trades. The engine maps this to the next Indian session.",
    },
    "FOMC": {
        "title": "US Federal Reserve Decision",
        "what": "The US central bank announces its interest rate decision at 2 PM ET, followed by a press conference.",
        "why": "The biggest scheduled volatility event on earth. Indian markets digest it overnight and gap at open — mapped to the next session.",
    },
    "BUDGET": {
        "title": "Union Budget",
        "what": "India's annual tax and spending announcement. Changes to capital gains tax, duties and sector allocations land mid-session.",
        "why": "Sector-wide repricing all day. Historically one of the highest-volatility Indian sessions of the year.",
    },
    "US-CPI-GAP": {
        "title": "US CPI → NIFTY morning gap",
        "what": "US inflation dropped last evening (IST). NIFTY opens this morning digesting that news — the engine reads the gap direction at open.",
        "why": "Gap-and-go mornings after US events offer clean directional momentum for option trades.",
    },
    "US-FOMC-GAP": {
        "title": "Fed decision → NIFTY morning gap",
        "what": "The US Fed decided rates overnight (IST). NIFTY opens this morning reacting to it.",
        "why": "Fed surprises produce the sharpest NIFTY gaps — strong material for the morning breakout engine.",
    },
    "US-NFP-GAP": {
        "title": "US Jobs Report (NFP) → NIFTY morning gap",
        "what": "America's monthly jobs number dropped at 8:30 PM IST yesterday. Strong jobs = rate-hike fears = US down; weak = US rallies.",
        "why": "First-Friday gap mornings give the engine an extra scheduled catalyst window between CPI and FOMC weeks.",
    },
    "SENSEX-EXPIRY": {
        "title": "SENSEX Weekly Expiry (BSE)",
        "what": "BSE's SENSEX weekly options expire today (Thursday). Smaller lots (20) and heavy gamma flows on the BSE side.",
        "why": "Adds a second gamma day every week at half the capital per lot — doubling scheduled hunt days without touching the model.",
    },
    "EARN-HDFCBANK-GAP": {
        "title": "HDFC Bank results → morning gap",
        "what": "NIFTY's largest weight reported results outside market hours. NIFTY opens this morning repricing the entire banking complex.",
        "why": "A 13% index weight moving can swing NIFTY 0.5-1%. Only trades if overnight news confirms the reaction (graded B/C otherwise).",
    },
    "EARN-RELIANCE-GAP": {
        "title": "Reliance results → morning gap",
        "what": "Reliance (second-largest NIFTY weight) reported post-close. Oil-to-telecom conglomerate results move the index broadly.",
        "why": "Second gap-add from India's most-followed stock. News-confirmed only — no coverage, no trade.",
    },
    "EARN-INFOSYS-GAP": {
        "title": "Infosys results → morning gap",
        "what": "Infosys guidance landed after close. IT sentiment spills across the tech complex and NIFTY's IT weight.",
        "why": "IT guidance shocks routinely gap NIFTY. News-confirmed only.",
    },
    "EARN-TCS-GAP": {
        "title": "TCS results → morning gap",
        "what": "TCS reported post-close; the IT bellwether sets the tone for the sector and IT-heavy NIFTY weights.",
        "why": "News-confirmed only — the grader needs actual coverage of the results before risking capital.",
    },
    "LS_RESULTS": {
        "title": "Election Results Day",
        "what": "Vote counting for a major election, with results flowing in through the session.",
        "why": "Political outcomes reprice sectors violently. Among the biggest single-day ranges in Indian market history.",
    },
}


def cal_in_ish(day: date) -> dict:
    info = EVENTS_INFO["SENSEX-EXPIRY"]
    return {
        "date": day.isoformat(),
        "name": "SENSEX-EXPIRY",
        "time": "09:15",
        "market": "IN",
        "title": info["title"],
        "what": info["what"],
        "why": info["why"],
    }


def _event_payload(c, market: str) -> dict:
    info = EVENTS_INFO.get(c.name.replace("US-", "").replace("-GAP", ""), None)
    if c.name in EVENTS_INFO:
        info = EVENTS_INFO[c.name]
    return {
        "date": c.day.isoformat(),
        "name": c.name,
        "time": c.release_hhmm,
        "market": market,
        "title": (info or {}).get("title", c.name),
        "what": (info or {}).get("what", ""),
        "why": (info or {}).get("why", ""),
    }


def _dhan() -> dict:
    def fetch():
        try:
            import tokens as token_store

            token_store.get_token("dhan")
        except Exception as exc:
            return {"connected": False, "reason": f"Token API unavailable ({str(exc)[:80]})"}
        try:
            from engine.broker_dhan import DhanBroker

            fl = DhanBroker().fund_limit()
            return {
                "connected": True,
                "available": fl.get("availabelBalance"),
                "sod": fl.get("sodLimit"),
                "withdrawable": fl.get("withdrawableBalance"),
            }
        except Exception as exc:
            raw = str(exc)
            if "401" in raw or "403" in raw:
                reason = "Token expired or invalid. Generate a fresh access token: web.dhan.co → Profile → DhanHQ Trading APIs."
            elif "404" in raw:
                reason = "Dhan endpoint not found — check for engine updates."
            else:
                reason = raw[:180]
            return {"connected": False, "reason": reason}

    return _ttl_cache("dhan", 60, fetch)


def _backtest_block() -> dict:
    summary = None
    try:
        summary = json.load(open(RESULTS / "summary.json"))
    except Exception:
        pass
    curve: list[float] = []
    trades: list[dict] = []
    try:
        with open(RESULTS / "journal.csv", newline="") as fh:
            trades = list(csv.DictReader(fh))
        curve = [float(t["equity_after"]) for t in trades if t.get("equity_after")]
    except Exception:
        pass
    return {"summary": summary, "curve": curve, "trades": trades[-15:][::-1], "total": len(trades)}


def _paper_block() -> dict:
    rows: list[dict] = []
    try:
        with open(RESULTS / "paper_journal.csv", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except Exception:
        pass
    parsed = []
    for r in rows:
        try:
            pnl = float(r.get("pnl") or 0)
        except Exception:
            pnl = 0.0
        parsed.append({**r, "pnl_num": pnl})
    wins = [p for p in parsed if p["pnl_num"] > 0]
    total_pnl = sum(p["pnl_num"] for p in parsed)
    running: list[float] = []
    eq = 0.0
    for p in parsed:
        eq += p["pnl_num"]
        running.append(eq)
    return {
        "rows": parsed[-15:][::-1],
        "journal_full": parsed[::-1],
        "total": len(parsed),
        "wins": len(wins),
        "win_rate": (len(wins) / len(parsed)) if parsed else None,
        "total_pnl": total_pnl,
        "curve": running,
        "live_count": sum(1 for p in parsed if p.get("mode") == "live"),
        "paper_count": sum(1 for p in parsed if p.get("mode") == "virtual"),
    }


@app.post("/api/secrets")
def save_secrets(req: SecretsReq, x_engine_key: str | None = Header(default=None)):
    _guard(x_engine_key)
    data = secrets_save(req.model_dump(exclude_none=True))
    return {
        "ok": True,
        "dhan_client_id": secrets_mask(data.get("dhan_client_id", "")),
        "dhan_access_token": secrets_mask(data.get("dhan_access_token", "")),
        "telegram_bot_token": secrets_mask(data.get("telegram_bot_token", "")),
        "telegram_chat_id": secrets_mask(data.get("telegram_chat_id", "")),
        "telegram_ready": bool(data.get("telegram_bot_token") and data.get("telegram_chat_id")),
    }


@app.get("/api/secrets")
def get_secrets():
    data = secrets_load()
    return {
        "dhan_client_id": secrets_mask(data.get("dhan_client_id", "")),
        "dhan_access_token": secrets_mask(data.get("dhan_access_token", "")),
        "telegram_bot_token": secrets_mask(data.get("telegram_bot_token", "")),
        "telegram_chat_id": secrets_mask(data.get("telegram_chat_id", "")),
        "telegram_ready": bool(data.get("telegram_bot_token") and data.get("telegram_chat_id")),
        "dashboard_url": data.get("dashboard_url"),
        "mode": data.get("mode", "practice"),
        "risk_pct": data.get("risk_pct", 0.05),
        "key_set": bool(data.get("dashboard_key")),
    }


@app.get("/api/activity")
def activity():
    entries: list[dict] = []
    log_path = RESULTS / "engine_live.log"
    try:
        for line in log_path.read_text().splitlines()[-500:]:
            if "paper mode" in line and "day=" in line:
                day = line.split("day=")[1].split()[0]
                entries.append({"date": day, "event": "", "status": "started", "detail": ""})
            elif "engine armed" in line and entries:
                try:
                    entries[-1]["event"] = line.split("catalyst=")[1].split()[0]
                except Exception:
                    pass
                entries[-1]["status"] = "armed"
            elif "not a catalyst day" in line and entries:
                entries[-1]["status"] = "quiet"
            elif line.startswith("OPEN") and entries:
                entries[-1]["status"] = "traded"
                entries[-1]["detail"] = line[:120]
            elif "CLOSE [" in line and entries:
                entries[-1]["detail"] = line[:120]
    except Exception:
        pass
    deduped: list[dict] = []
    for e in entries:
        if deduped and deduped[-1]["date"] == e["date"] and deduped[-1]["status"] == e["status"]:
            continue
        deduped.append(e)
    return {"sessions": deduped[-40:][::-1]}


@app.get("/api/status")
def status():
    with state["lock"]:
        running = state["proc"] is not None and state["proc"].poll() is None
        payload = {
            "running": running,
            "meta": dict(state["meta"]),
            "phase": state["phase"] if running or state["phase"] == "standby" else state["phase"],
            "position": state["position"],
            "session_pnl": state["session_pnl"],
            "last_action": state["last_action"],
            "alerts": list(state["alerts"]),
        }
    today = date.today()
    try:
        us_for_gaps = cal_us.catalysts_between(today - timedelta(days=7), today + timedelta(days=1))
    except Exception:
        us_for_gaps = []
    in_cats = calendar_in.indian_events(today, today + timedelta(days=75), us_catalysts=us_for_gaps)
    sensex_rows = []
    seen_days = {c.day for c in in_cats}
    probe = today
    while probe <= today + timedelta(days=75) and len(sensex_rows) < 6:
        if probe.weekday() == 3 and probe not in seen_days:
            sensex_rows.append(cal_in_ish(probe))
        probe += timedelta(days=1)
    ev_in = [_event_payload(c, "IN") for c in in_cats[:9]] + sensex_rows
    ev_in.sort(key=lambda e: e["date"])
    ev_us = [_event_payload(c, "US") for c in cal_us.upcoming(today, 4)]
    today_event = next((e for e in ev_in if e["date"] == today.isoformat()), None)
    return {
        **payload,
        "today": today.isoformat(),
        "today_event": today_event,
        "events_in": ev_in,
        "events_us": ev_us,
        "dhan": _dhan(),
        "backtest": _backtest_block(),
        "paper": _paper_block(),
    }


def _pgrep(pattern: str) -> bool:
    try:
        result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _launchd_alive(label: str) -> bool | None:
    """macOS: exact launchd label check. Returns None on non-mac/error."""
    if platform.system() != "Darwin":
        return None
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5).stdout
        return any(line.split("\t")[-1].strip() == label for line in out.splitlines())
    except Exception:
        return None


def _service(label: str, pattern: str) -> bool:
    alive = _launchd_alive(label)
    if alive is not None:
        return alive
    return _pgrep(pattern)


_CACHE: dict[str, tuple[float, object]] = {}


def _ttl_cache(key: str, ttl: float, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = fn()
    _CACHE[key] = (now, value)
    return value


@app.get("/api/feed")
def feed():
    """Live agent feed: scheduler log + engine log + journal, newest first."""
    entries: list[dict] = []

    def add(ts: str, kind: str, text: str) -> None:
        entries.append({"ts": ts, "kind": kind, "text": text})

    today = date.today().isoformat()
    eng_path = RESULTS / "engine_live.log"
    try:
        cur_day = today
        for line in eng_path.read_text().splitlines()[-150:]:
            m = re.search(r"day=(\d{4}-\d{2}-\d{2})", line)
            if m:
                cur_day = m.group(1)
            if "paper mode" in line:
                add(f"{cur_day}T09:00:00", "session", f"Session started · {'REAL MONEY' if 'live=True' in line else 'paper mode'} · {cur_day}")
            elif "— engine armed" in line:
                cm = re.search(r"catalyst=\S+\s+(\S+)", line)
                name = cm.group(1) if cm else "hunt day"
                add(f"{cur_day}T09:07:00", "arm", f"Armed for {name}")
            elif "session over" in line:
                add(f"{cur_day}T15:25:00", "eod", "Session closed — flat by 15:20, no overnight")
    except Exception:
        pass

    sched_log = Path.home() / "Library" / "Logs" / "predator" / "predator-scheduler.log"
    try:
        for line in sched_log.read_text().splitlines()[-400:]:
            m = re.match(r"\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\] (.*)", line)
            if not m:
                continue
            ts, msg = f"{m.group(1)}T{m.group(2)}", m.group(3)
            if "quiet day — no hunt" in msg:
                add(ts, "quiet", "Quiet day — no hunt scheduled, wolf resting")
            elif "reminder sent" in msg or "MORNING CHECK" in msg:
                add(ts, "brief", "Morning brief: day graded & dispatched")
            elif "rated C" in msg or "stand down" in msg:
                add(ts, "skip", "Day graded C — standing down, no risk taken")
            elif "engine started" in msg or "AUTO-ARMED" in msg:
                add(ts, "arm", "Auto-armed at 09:07 — engine hunting")
            elif "cool-off" in msg:
                add(ts, "halt", "Cool-off — two losing days, governor forces rest")
            elif "adopted" in msg:
                add(ts, "arm", "Engine already active — adopted, no double-arm")
            elif "terminated" in msg or "safety kill" in msg:
                add(ts, "kill", "Safety kill — everything flat at 15:25")
            elif "heartbeat" in msg:
                add(ts, "beat", "Daily heartbeat — all systems alive")
    except Exception:
        pass

    try:
        with open(RESULTS / "paper_journal.csv", newline="") as fh:
            for r in csv.DictReader(fh):
                pnl = float(r.get("pnl") or 0)
                ts = (r.get("timestamp") or today)[:19]
                add(ts, "trade", f"Closed {(r.get('side') or '').upper()} {r.get('strike')} — {'+' if pnl >= 0 else ''}₹{inr_f(pnl)} net")
    except Exception:
        pass

    entries.sort(key=lambda e: e["ts"], reverse=True)
    seen: set[str] = set()
    deduped = []
    for e in entries:
        day = e["ts"][:10]
        if e["kind"] in ("quiet", "brief", "beat", "skip", "kill", "eod", "halt"):
            key = f"{day}|{e['kind']}"
        else:
            key = e["ts"] + e["text"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    return {"feed": deduped[:80], "now": f"{today}T{datetime.now().strftime('%H:%M:%S')}"}
def inr_f(n: float) -> str:
    return f"{abs(int(round(n))):,}"


@app.get("/api/health")
def health():
    def compute():
        with state["lock"]:
            engine_running = state["proc"] is not None and state["proc"].poll() is None
        own_engine = str(ROOT / "run_predator.py")
        return {
            "engine": engine_running or _pgrep(own_engine),
            "autopilot": _service("com.predator.scheduler", str(ROOT / "run_scheduler.py")),
            "sentinel": _service("com.predator.sentinel", "engine.sentinel"),
        }

    return _ttl_cache("health", 10, compute)


@app.get("/")
def index():
    return FileResponse(
        STATIC / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
