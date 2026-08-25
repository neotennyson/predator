# PREDATOR — Project Note

> An autonomous catalyst-day options trading engine.
> Built: August 2026 · Status: validated components, paper-trading stage, pre-live.

---

## THE GOAL

Turn **₹1,00,000 into ₹1,00,00,000** as fast as legally possible — without gambling blindly.

The honest math: nothing legal produces 100x in a month through margins or skill alone. The only instruments where 100x-in-weeks *physically happens* are high-variance ones (0DTE options, leveraged crypto). So the design decision was:

**Don't remove the variance — remove the indiscipline.**

PREDATOR is a machine that plays the highest-variance legal game (event-day options buying) with institutional-grade risk controls, news validation, and survival mechanics. The expected outcome distribution is wide — but the downside per trade is capped, the account cannot tilt, and every decision is logged.

**The final target model:** small consistent wins (2x partial bookings) + rare monster runners (up to 25x), compounded under a governor that makes ruin mathematically slow. One 20x+ hit on a full-risk day ≈ ₹4L. Several, compounded, is the crores path. No promises — just the cheapest honest tickets in every raffle, held by a machine that never tilts.

---

## THE JOURNEY (how we got here)

1. **Strategy research** — mapped every legal path to 100x/month: lotteries, prediction markets, memecoins, prop firms, bug bounties, 0DTE options. Chose event-day options: real market, legal, deepest liquidity on earth (NSE = world's largest derivatives exchange).
2. **Broker selection** — researched Indian algo APIs (Dhan, Fyers, Zerodha, Angel One). Critical discovery: **Indian residents cannot trade US options under RBI's LRS rules** — so SPY 0DTE was out; NIFTY weeklies via **Dhan** (free API, 25 req/s, best rate limits) won.
3. **Engine built** (`engine/`) — catalyst calendar → live data → breakout signals → Black-Scholes premium simulation → risk governor → backtester → paper trader → live Dhan execution.
4. **Dashboard** (`dashboard.py` + `static/`) — mission-control web UI: dual-world theme (misty forest = practice, blood dimension = real money), clickable event explainers, kill sheet, funds, controls. Zero terminal needed on trading days.
5. **The brain** — news sentinel (Google News RSS, impact + direction scoring), red-flag veto, trade confluence check, morning A/B/C day-rating that sizes the day before it starts.
6. **Autopilot** (`run_scheduler.py`) — Telegram morning brief with day grade → token paste → auto-arm at 09:07 → hunt → 15:25 safety kill → day report. Plus cool-off after losing streaks and dead-token pre-flight.

---

## WHAT WAS BUILT (inventory)

| Component | File | What it does |
|---|---|---|
| Event calendar | `engine/calendar.py`, `calendar_in.py` | RBI MPC, Budget, F&O expiries, election days, US CPI/FOMC mapped to next-session gaps. Extensible via CSV |
| Market data | `engine/data.py` | yfinance candles + VIX/IndiaVIX, cached locally |
| Option pricer | `engine/greeks.py` | Black-Scholes premium/delta simulation for backtests |
| Strategy | `engine/strategy.py` | Impulse-range breakout: measure first 15 min after release, enter ATM call/put on confirmed break, ladder exits |
| Risk governor | `engine/risk.py` | Fixed-fractional sizing, loss-streak halt, ruin floor at −50%, daily loss cap |
| Backtester | `engine/backtest.py` | Intraday (5m) + multi-year daily-gap modes, per-event logs, equity curve |
| News sentinel | `engine/sentinel.py` | 24/7 RSS polling, 0–10 impact scoring, bullish/bearish direction, red-flag detection, Telegram alerts |
| Validation brain | `engine/validation.py` | News memory → pre-entry confluence check → morning A/B/C day rating (100%/50%/0% risk) |
| Broker adapter | `engine/broker_dhan.py` | Dhan v2 REST: option chain, ATM pick, lot sizing, market orders, LTP, exits |
| Telegram | `engine/notify.py` | Armed/open/TP1/close/session/heartbeat alerts |
| Secrets vault | `engine/secrets_store.py` | Local `secrets.json`, masked in UI |
| Autopilot | `run_scheduler.py` | 08:30 reminder → 09:07 auto-arm → 15:25 kill → heartbeat → cool-offs |
| Dashboard | `dashboard.py`, `static/index.html` | Full mission control in browser |
| Entry point | `run_paper.py`, `run_backtest.py`, `run_dashboard.py` | Paper/live trader, backtester, UI launcher |

---

## THE FINAL LOCKED MODEL

### The hunt
- **Only trade catalyst days**: RBI MPC (10:00 IST), monthly F&O expiry, Union Budget, election results, US CPI/FOMC (as next-morning gap plays).
- **Quiet days = flat.** No positions, no watching, no exceptions.

### The entry
1. Measure the impulse range (first 15 min after release/session open).
2. Range must be ≥ 0.15% wide (chop filter) or the day is skipped.
3. Enter **only on confirmed breakout**: close above range-high +0.08% → ATM CALL; below range-low −0.08% → ATM PUT. Scan window closes 3h after release.
4. One position at a time.

### The validation gate (news brain)
- **Red-flag veto**: war/crash/emergency headline → no new entries for 45 min (and emergency exit if holding).
- **Confluence check**: last-4h news direction must not contradict the trade (bullish news kills put entries, bearish kills calls).
- **Day grade** (08:30 IST): event weight + India VIX band + overnight news flow → **A = 100% risk, B = 50%, C = stand down.**

### The exits
- **Stop**: −55% of option premium. Non-negotiable.
- **TP1**: +100% (2x) — book 40%, runner rides.
- **Runner**: +2400% (25x) hard target **or** trailing exit (give back 30% from peak) **or** 15:20 IST force-flat, whichever first.
- **Costs**: ₹60 estimated charges deducted in every reported P&L. Net, not gross.

### The sizing
- Default risk: **5% of equity per trade** (user-adjustable 1–25%), scaled by day-grade multiplier.
- **Sizing guard**: if one lot costs > 110% of the risk budget, the trade is blocked (NIFTY lot = 75; SENSEX lot = 20 for small accounts).
- **Streak halt**: 2 consecutive losing event-days → skip the next hunt.
- **Cool-off**: 2 consecutive losing days (scheduler level) → forced rest day.
- **Ruin floor**: equity at −50% of start → engine locks itself. Manual reset only.

### The automation loop (D-day flow)
```
08:30 IST  Telegram: "Hunt today: <event> — Day rating: A/B/C"
           (C → engine stands down, day over)
<user>     pastes fresh Dhan token (tokens die daily by design)
09:07      pre-flight: token check → sizing check → cool-off check
           → AUTO-ARM (practice or live, per saved setting)
09:15+     impulse measured → breakout watched → validation gates
OPEN       Telegram alert → managed automatically (stop/TP1/trail/EOD)
CLOSE      Telegram: gross · costs · NET → kill sheet updated
15:25      safety kill, session report
20:00      daily heartbeat: alive + next hunt date
```

### What is deliberately NOT in the model
- No overnight positions. No averaging down. No adding to losers. No revenge trades (machine can't tilt). No trading non-catalyst days. No US markets (RBI LRS law). No unvalidated parameter changes mid-flight.

---

## HONEST LIMITATIONS (as locked today)

1. **Edge is not yet proven.** Backtests: intraday sample is small (free data window); daily-gap variant showed negative expectancy on NIFTY and was deprioritized. Option premiums are simulated (Black-Scholes + VIX), not real historical chains — **no IV crush, no spread modeling**. Real-money sizing waits for the paper journal to show positive net expectancy across 10+ hunts.
2. **Yahoo feed delay** on NSE (up to ~15 min) — live candle migration to Dhan's data API is queued (top of roadmap).
3. **Keyword-based news scoring** — v1 brain; LLM scoring is the upgrade path.
4. **Daily token ritual** is unavoidable (broker 2FA design).

## ROADMAP (priority order)
1. Dhan data API for live candles (kill the Yahoo dependency)
2. Real historical options backtest (validate the edge for real)
3. Second entry attempt per day (re-break logic)
4. Weekly analytics report (which events/sides/hours pay)
5. LLM headline scoring + morning brief

---

## OPERATING RHYTHM
```bash
cd /Users/USER/Documents/GitHub/predator
./.venv/bin/python run_scheduler.py     # autopilot (keep alive)
./.venv/bin/python -m engine.sentinel   # news watcher (keep alive)
./.venv/bin/python run_dashboard.py     # mission control (keep alive)
```
Machine must stay awake. VPS + Cloudflare Tunnel = permanent home (dashboard key-lock enabled).

---

*Built with ox-alpha. The predator only eats on days the market is forced to move — and only when the news says it's safe to pounce.*
