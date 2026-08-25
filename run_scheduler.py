from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from engine import calendar_in
from engine.notify import send
from engine.secrets_store import load

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
STATE_PATH = RESULTS / "scheduler_state.json"
IST = ZoneInfo("Asia/Kolkata")

REMIND_AT = (8, 30)
START_AT = (9, 7)
GIVE_UP_AT = (9, 45)
KILL_AT = (15, 25)


def _now() -> datetime:
    return datetime.now(IST)


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=2))


class Autopilot:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.state = _load_state()

    def _today_catalyst(self, day: date):
        events = calendar_in.indian_events(day, day, include_monthly_expiry=True)
        return events[0] if events else None

    def _start_engine(self, live: bool, risk_pct: float) -> bool:
        if self.proc and self.proc.poll() is None:
            return False
        cmd = [sys.executable, "-u", str(ROOT / "run_paper.py"), "--market", "in", "--risk-pct", str(risk_pct)]
        if live:
            cmd.append("--live")
        self.proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        return True

    def _watch_engine(self):
        def run():
            if not self.proc:
                return
            self.proc.wait()
            row = ""
            try:
                lines = (RESULTS / "paper_journal.csv").read_text().strip().splitlines()
                if len(lines) >= 2:
                    row = lines[-1]
            except Exception:
                pass
            send(f"🐺 Engine finished for today.\nLast journal row: {row or 'no trades'}")
        threading.Thread(target=run, daemon=True).start()

    def tick(self) -> str:
        now = _now()
        today = now.date()
        t = (now.hour, now.minute)
        cat = self._today_catalyst(today)
        secrets = load()
        st = self.state

        if t >= (20, 0) and st.get("heartbeat") != today.isoformat():
            nxt = calendar_in.indian_events(today, today.replace(month=12, day=31), include_monthly_expiry=True)
            nxt_label = nxt[0].label if nxt else "none scheduled"
            st["heartbeat"] = today.isoformat()
            _save_state(st)
            send(f"💚 PREDATOR alive — news sentinel watching, autopilot standing by.\nNext hunt: {nxt_label}")

        if not cat:
            if st.get("last_quiet_note") != today.isoformat():
                st["last_quiet_note"] = today.isoformat()
                _save_state(st)
                return f"{today} quiet day — no hunt"
            return f"{today} quiet day"

        label = f"{cat.name} ({cat.release_hhmm} IST)"

        if t >= REMIND_AT and st.get("reminded") != today.isoformat() and t < START_AT:
            st["reminded"] = today.isoformat()
            _save_state(st)
            url = secrets.get("dashboard_url", "http://127.0.0.1:8787")
            rating_line = ""
            try:
                from engine.validation import rate_day
                r = rate_day(cat.name)
                grade = r["grade"]
                mult = float(r["multiplier"])
                rating_line = f"\n\nDay rating: <b>{grade}</b> ({'full' if mult == 1 else 'half' if mult >= 0.5 else 'no'} risk)\n" + "\n".join("• " + x for x in r["reasons"])
                if mult <= 0:
                    st["started"] = today.isoformat()
                    _save_state(st)
                    send(f"🐺 <b>PREDATOR MORNING CHECK</b>\nHunt today: <b>{label}</b>{rating_line}\n\n⛔ Day rated C — engine will stand down. No token needed today.")
                    return f"day rated C — skipped {label}"
            except Exception as exc:
                print(f"rating error: {exc}")
            send(
                f"🐺 <b>PREDATOR MORNING CHECK</b>\n"
                f"Hunt today: <b>{label}</b>{rating_line}\n\n"
                f"Paste a fresh Dhan token here: {url}\n"
                f"Engine auto-arms at 09:07 IST."
            )
            return f"reminder sent for {label}"

        if t >= START_AT and st.get("started") != today.isoformat():
            token = secrets.get("dhan_access_token") or ""
            if token:
                live = secrets.get("mode", "practice") == "live"
                if live:
                    try:
                        from engine.broker_dhan import DhanBroker
                        DhanBroker().fund_limit()
                    except Exception as exc:
                        if now.minute % 15 == 0:
                            send(f"🔴 <b>Token check FAILED</b> — live arm blocked. ({str(exc)[:120]})\nPaste a fresh token: {secrets.get('dashboard_url', '')}")
                        return "live blocked — dead token"
                try:
                    import csv as _csv
                    with open(RESULTS / "paper_journal.csv", newline="") as fh:
                        rows = list(_csv.DictReader(fh))
                    recent = [r for r in rows if r.get("pnl")][-2:]
                    if len(recent) == 2 and all(float(r["pnl"]) < 0 for r in recent):
                        st["started"] = today.isoformat()
                        _save_state(st)
                        send("🧊 <b>COOL-OFF</b> — two consecutive losing days. Governor forces rest. Next hunt resumes fresh.")
                        return "cool-off — 2 losing days"
                except Exception:
                    pass
                risk = float(secrets.get("risk_pct", 0.05))
                if self._start_engine(live, risk):
                    self._watch_engine()
                    st["started"] = today.isoformat()
                    _save_state(st)
                    send(f"🚀 <b>AUTO-ARMED</b> for {label}\nmode: {'REAL MONEY' if live else 'PRACTICE'} · risk {risk:.0%}")
                    return f"engine started for {label}"
            elif t >= GIVE_UP_AT:
                st["started"] = today.isoformat()
                _save_state(st)
                send(f"⛔ Skipping {label} — no fresh Dhan token was pasted. Paste earlier next hunt day.")
                return "skipped — no token"
            else:
                if now.minute % 15 == 0:
                    send(f"⏳ Still waiting for today's Dhan token — engine cannot arm without it. {secrets.get('dashboard_url', '')}")
                return "waiting for token"

        if t >= KILL_AT and self.proc and self.proc.poll() is None:
            self.proc.terminate()
            return "engine terminated (safety kill)"

        return f"{t[0]:02d}:{t[1]:02d} holding · hunt={cat.name} · started={st.get('started') == today.isoformat()}"

    def run_forever(self, poll_seconds: int = 30):
        print(f"autopilot on — IST clock, poll {poll_seconds}s. Ctrl+C to stop.")
        send("🟢 PREDATOR autopilot online.")
        while True:
            try:
                msg = self.tick()
                print(f"[{_now().strftime('%H:%M:%S')}] {msg}")
            except Exception as exc:
                print(f"tick error: {exc}")
            time.sleep(poll_seconds)


if __name__ == "__main__":
    ap = Autopilot()
    if "--once" in sys.argv:
        print(ap.tick())
    else:
        ap.run_forever()
