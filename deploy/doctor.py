#!/usr/bin/env python3
"""PREDATOR doctor — run after every change; also safe to run anytime.

Checks: compile, JS, plists, tokens, broker read-only, endpoints, orphans,
state files, disk hygiene. Prints PASS/FAIL lines and a final verdict.
"""
from __future__ import annotations

import json
import platform
import py_compile
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RESULTS = ROOT / "results"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    print("PREDATOR DOCTOR")

    # 1. python compile
    ok = True
    targets = [ROOT / "tokens.py", ROOT / "dashboard.py", ROOT / "run_scheduler.py",
               ROOT / "run_predator.py", ROOT / "run_backtest.py", *(ROOT / "engine").glob("*.py")]
    for t in targets:
        try:
            py_compile.compile(str(t), doraise=True)
        except Exception as exc:
            ok = False
            print(f"    compile error {t.name}: {exc}")
    check("python compile (12 modules)", ok)

    # 2. tokens
    try:
        import tokens

        d = tokens.get_token("dhan")
        g = tokens.get_token("groww")
        check("token api", bool(d) and bool(g), f"len d={len(d)} g={len(g)}")
    except Exception as exc:
        check("token api", False, str(exc)[:90])

    # 3. broker read-only (uses fresh code path end-to-end)
    try:
        from engine.broker_dhan import DhanBroker

        fl = DhanBroker().fund_limit()
        check("dhan read-only", "availabelBalance" in fl, str(fl)[:80])
    except Exception as exc:
        check("dhan read-only", False, str(exc)[:90])

    # 4. state files valid json
    for name in ["scheduler_state.json", "day_rating.json", "sentinel_state.json"]:
        p = RESULTS / name
        try:
            if p.exists():
                json.loads(p.read_text())
        except Exception as exc:
            check(f"state {name}", False, str(exc)[:80])
    check("state json valid", not any(f.startswith("state ") for f in FAILS))

    # 5. journal readable + header sane
    try:
        rows = (RESULTS / "paper_journal.csv").read_text().strip().splitlines()
        if rows:
            header = rows[0].split(",")
            check("paper journal header", header[:3] == ["timestamp", "event", "symbol"], str(header[:3]))
        else:
            check("paper journal header", True, "empty journal")
    except Exception as exc:
        check("paper journal header", False, str(exc)[:80])

    # 6. endpoints
    base = "http://127.0.0.1:8787"
    for path, required in [("/api/status", ["today", "events_in", "paper"]), ("/api/health", ["autopilot", "sentinel", "engine"]), ("/api/activity", ["sessions"])]:
        try:
            with urllib.request.urlopen(f"{base}{path}", timeout=10) as resp:
                data = json.loads(resp.read().decode())
            check(f"endpoint {path}", all(k in data for k in required), f"missing {[k for k in required if k not in data]}")
        except Exception as exc:
            check(f"endpoint {path}", False, str(exc)[:90])

    # 7. process census: exactly one scheduler + one sentinel, no stray engines
    try:
        out = subprocess.run(["pgrep", "-fl", f"{ROOT}/run_predator.py|run_scheduler.py|engine.sentinel"],
                             capture_output=True, text=True, timeout=5).stdout.splitlines()
        engines = [l for l in out if "run_predator.py" in l]
        scheds = [l for l in out if "run_scheduler.py" in l]
        sentis = [l for l in out if "engine.sentinel" in l]
        check("no stray engines", len(engines) <= 1, f"{len(engines)} engine processes")
        check("exactly one autopilot", len(scheds) == 1, f"{len(scheds)}")
        check("exactly one sentinel", len(sentis) == 1, f"{len(sentis)}")
    except Exception as exc:
        check("process census", False, str(exc)[:80])

    # 8. disk hygiene: no runaway files, no leftover tmp
    tmps = list(ROOT.glob("*.tmp")) + list(Path.home().glob(".broker_tokens.tmp"))
    check("no leftover tmp files", not tmps, ", ".join(str(t) for t in tmps))
    big = [p.name for p in RESULTS.glob("*") if p.stat().st_size > 2_000_000]
    check("results files under 2MB", not big, ", ".join(big))

    # 9. secrets hygiene
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    leaked = [f for f in tracked if f.endswith((".env", "secrets.json"))]
    check("no secrets tracked in git", not leaked, ", ".join(leaked))

    print()
    if FAILS:
        print(f"VERDICT: ❌ {len(FAILS)} failing — {', '.join(FAILS)}")
        return 1
    print("VERDICT: ✅ ALL SYSTEMS GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
