from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import date, timedelta
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
            with open(RESULTS / "engine_live.log", "a") as fh:
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
        cmd = [sys.executable, "-u", str(ROOT / "run_paper.py"), "--market", req.market, "--risk-pct", str(req.risk_pct)]
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
    "LS_RESULTS": {
        "title": "Election Results Day",
        "what": "Vote counting for a major election, with results flowing in through the session.",
        "why": "Political outcomes reprice sectors violently. Among the biggest single-day ranges in Indian market history.",
    },
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
    if not os.environ.get("DHAN_CLIENT_ID") or not os.environ.get("DHAN_ACCESS_TOKEN"):
        return {"connected": False, "reason": "Credentials not loaded. Paste the two export lines (DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN) in the terminal, then restart the dashboard."}
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
    ev_in = [_event_payload(c, "IN") for c in calendar_in.indian_events(today, today + timedelta(days=75))[:7]]
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


@app.get("/api/health")
def health():
    with state["lock"]:
        engine_running = state["proc"] is not None and state["proc"].poll() is None
    return {
        "engine": engine_running or _pgrep("run_paper.py"),
        "autopilot": _pgrep("run_scheduler.py"),
        "sentinel": _pgrep("engine.sentinel"),
    }


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
