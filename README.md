# vajra

Catalyst-day 0DTE options system: event calendar -> breakout signals -> Black-Scholes premium simulation -> risk-governed compounding -> paper trading loop.

## Setup

    python3 -m venv .venv
    ./.venv/bin/pip install -r requirements.txt

## Commands

Backtest intraday breakout mode (needs 5m data, ~60d free-history window):

    ./.venv/bin/python run_backtest.py --mode intraday --market us --symbol SPY
    ./.venv/bin/python run_backtest.py --mode intraday --market in

Backtest event-day gap mode over years (daily bars):

    ./.venv/bin/python run_backtest.py --mode daily --market us --years-back 5
    ./.venv/bin/python run_backtest.py --mode daily --market in --years-back 3
    ./.venv/bin/python run_backtest.py --mode daily --market us --years-back 5 --vix-min 20

Paper-trade the next catalyst day live (virtual fills, journal appended):

    ./.venv/bin/python run_paper.py --market in
    ./.venv/bin/python run_paper.py --market us

Go LIVE via Dhan (NSE options, market orders, INTRADAY product):

    export DHAN_CLIENT_ID=...      # from Dhan dashboard
    export DHAN_ACCESS_TOKEN=...   # regenerate daily from web.dhan.co
    ./.venv/bin/python run_paper.py --market in --live

List upcoming catalysts:

    ./.venv/bin/python -c "from engine import calendar as c; [print(x.label, x.release_hhmm) for x in c.upcoming(__import__('datetime').date.today(), 8)]"

Add your own events via `catalysts_extra.csv` (`date,name,time`).
India calendar: RBI MPC decisions (10:00 IST), Union Budget, monthly F&O expiry,
US CPI/FOMC mapped to next-session gaps. Verify upcoming MPC dates against RBI press releases.

Dhan execution notes: NIFTY lot = 75; ATM strike auto-picked from live option chain;
nearest weekly expiry used; orders are MARKET / INTRADAY product.

## Web dashboard

    ./.venv/bin/python run_dashboard.py

Opens `http://127.0.0.1:8787` — start/stop engine, pick market/risk/live mode,
watch the live console, see Dhan funds, upcoming catalysts, backtest summary and journal.
Set `DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN` env vars first to see funds and trade live from the UI.

## Outputs

- `results/journal.csv` — every simulated trade
- `results/summary.json` — win rate, expectancy, drawdown, return multiple
- `cache/` — downloaded market data

## Tuning knobs (engine/config.py)

risk_pct, stop_frac, tp1_mult/frac, runner_mult, buffer_pct, impulse_minutes,
min_impulse_pct, lose_streak_halt, ruin_floor, vix_min.
