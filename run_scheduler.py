from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from engine import calendar_in
from engine.notify import send
from engine.secrets_store import load

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
STATE_PATH = RESULTS / "scheduler_state.json"
IST = ZoneInfo("Asia/Kolkata")

PROCESS_START = time.time()
_LAST_CODE_CHECK = [0.0]


def _code_is_stale() -> bool:
    """True if any project .py file changed on disk after this process started."""
    now = time.time()
    if now - _LAST_CODE_CHECK[0] < 600:
        return False
    _LAST_CODE_CHECK[0] = now
    try:
        for path in [ROOT / "run_scheduler.py", *(ROOT / "engine").glob("*.py"), ROOT / "tokens.py"]:
            if path.stat().st_mtime > PROCESS_START:
                return True
    except Exception:
        pass
    return False


def _self_replace() -> None:
    send("🔄 PREDATOR code updated on disk — hot-reloading autopilot so the new logic runs tomorrow.")
    os.execv(sys.executable, [sys.executable] + sys.argv)

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

    def _hunt_for(self, day: date) -> tuple[object, str] | None:
        """(catalyst, market) for a day. NIFTY events take precedence over SENSEX Thursdays."""
        try:
            import engine.calendar as cal_us

            us = cal_us.catalysts_between(day - timedelta(days=7), day + timedelta(days=1))
        except Exception:
            us = []
        events = calendar_in.indian_events(day, day, include_monthly_expiry=True, us_catalysts=us)
        if events:
            return events[0], "in"
        if day.weekday() == 3:
            from engine.calendar import Catalyst

            return Catalyst(day, "SENSEX-EXPIRY", "09:15"), "in_sensex"
        return None

    def _today_catalyst(self, day: date):
        hunt = self._hunt_for(day)
        return hunt[0] if hunt else None

    def _engine_running(self) -> bool:
        """True if a PREDATOR engine (and only one) is already alive, child or not."""
        try:
            out = subprocess.run(
                ["pgrep", "-f", str(ROOT / "run_predator.py")],
                capture_output=True, text=True, timeout=5,
            ).stdout.split()
            own = str(self.proc.pid) if self.proc else None
            return any(p != own for p in out)
        except Exception:
            return False

    def _kill_orphans(self) -> int:
        """Terminate stray predator engines not spawned by this scheduler."""
        import os
        import signal

        killed = 0
        try:
            out = subprocess.run(
                ["pgrep", "-f", str(ROOT / "run_predator.py")],
                capture_output=True, text=True, timeout=5,
            ).stdout.split()
            own = str(self.proc.pid) if self.proc else None
            for pid in out:
                if pid != own:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        killed += 1
                    except Exception:
                        pass
        except Exception:
            pass
        return killed

    def _start_engine(self, live: bool, risk_pct: float, market: str = "in") -> bool:
        if self.proc and self.proc.poll() is None:
            return False
        cmd = [sys.executable, "-u", str(ROOT / "run_predator.py"), "--market", market, "--risk-pct", str(risk_pct)]
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
        if _code_is_stale():
            _self_replace()
        now = _now()
        today = now.date()
        t = (now.hour, now.minute)
        hunt = self._hunt_for(today)
        market = hunt[1] if hunt else "in"
        cat = hunt[0] if hunt else None
        secrets = load()
        st = self.state

        if t >= (20, 0) and st.get("heartbeat") != today.isoformat():
            try:
                import engine.calendar as cal_us

                us = cal_us.catalysts_between(today + timedelta(days=1), today + timedelta(days=45))
            except Exception:
                us = []
            try:
                end = today.replace(month=12, day=31)
            except ValueError:
                end = today
            nxt = calendar_in.indian_events(today + timedelta(days=1), end, include_monthly_expiry=True, us_catalysts=us)
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
            is_live_mode = secrets.get("mode", "practice") == "live"
            tail = (
                f"Paste a fresh Dhan token here: {url}\nEngine auto-arms at 09:07 IST."
                if is_live_mode
                else "Practice mode — no token needed. Engine auto-arms at 09:07 IST."
            )
            send(
                f"🐺 <b>PREDATOR MORNING CHECK</b>\n"
                f"Hunt today: <b>{label}</b>{rating_line}\n\n{tail}"
            )
            return f"reminder sent for {label}"

        if t >= START_AT and st.get("started") != today.isoformat():
            live = secrets.get("mode", "practice") == "live"
            token = ""
            if live:
                try:
                    import tokens as token_store

                    token = token_store.get_token("dhan")
                except Exception:
                    token = ""
            if live and not token:
                if t >= GIVE_UP_AT:
                    st["started"] = today.isoformat()
                    _save_state(st)
                    send(f"⛔ Skipping {label} — no fresh Dhan token was pasted. Paste earlier next hunt day.")
                    return "skipped — no token"
                if now.minute % 15 == 0:
                    send(f"⏳ Still waiting for today's Dhan token — live mode cannot arm without it. {secrets.get('dashboard_url', '')}")
                return "waiting for token"
            if not live or token:
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
                if st.get("rated") != today.isoformat():
                    try:
                        from engine.validation import rate_day

                        r = rate_day(cat.name)
                        st["rated"] = today.isoformat()
                        _save_state(st)
                        if float(r["multiplier"]) <= 0:
                            st["started"] = today.isoformat()
                            _save_state(st)
                            send(
                                f"⛔ Day rated <b>{r['grade']}</b> at arm time — engine stands down.\n"
                                + "\n".join("• " + x for x in r["reasons"])
                            )
                            return f"day rated C at arm — skipped {label}"
                    except Exception as exc:
                        print(f"arm rating error: {exc}")
                if self._engine_running():
                    st["started"] = today.isoformat()
                    _save_state(st)
                    send(f"🐺 Engine already active for {label} — adopted. No double-arm.")
                    return "engine already running — adopted"
                risk = float(secrets.get("risk_pct", 0.05))
                if self._start_engine(live, risk, market):
                    self._watch_engine()
                    st["started"] = today.isoformat()
                    _save_state(st)
                    send(f"🚀 <b>AUTO-ARMED</b> for {label}\nmode: {'REAL MONEY' if live else 'PRACTICE'} · risk {risk:.0%}")
                    return f"engine started for {label}"

        if t >= KILL_AT:
            strays = self._kill_orphans()
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                return "engine terminated (safety kill)"
            if strays:
                return f"safety kill — terminated {strays} stray engine(s)"

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
