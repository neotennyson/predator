from __future__ import annotations

from datetime import date, time, timedelta

import pandas as pd

from . import calendar as cal
from . import calendar_in
from . import data
from .config import build_config
from .report import print_summary, save_outputs, summarize
from .risk import RiskGovernor
from .strategy import CatalystMomentum

FORCE_CLOSE = time(15, 55)


def _events_for(cfg: dict, start: date, end: date) -> list:
    if str(cfg.get("market", "US")).upper() == "IN":
        return calendar_in.indian_events(start, end, us_catalysts=cal.ALL)
    return cal.catalysts_between(start, end)


def _exit_reason_prem(bars: pd.DataFrame, sig, strat: CatalystMomentum, sigma: float) -> tuple[float, str]:
    remaining = 1.0
    realized = 0.0
    tp1_done = False
    reason = "eod"
    path = bars[bars.index >= sig.entry_time]
    for ts, row in path.iterrows():
        prem = strat.premium_at(float(row["Close"]), sig.strike, ts, sigma, sig.side)
        is_last = ts == bars.index[-1] or ts.time() >= FORCE_CLOSE
        if prem <= sig.stop_premium:
            realized += remaining * (sig.stop_premium / sig.premium)
            remaining = 0.0
            reason = "stop"
            break
        if not tp1_done and prem >= sig.tp1_premium:
            realized += strat.tp1_frac * (sig.tp1_premium / sig.premium)
            remaining -= strat.tp1_frac
            tp1_done = True
        if tp1_done and prem >= sig.runner_premium:
            realized += remaining * (prem / sig.premium)
            remaining = 0.0
            reason = "runner"
            break
        if is_last:
            realized += remaining * (prem / sig.premium)
            remaining = 0.0
            reason = "runner" if tp1_done else "eod"
            break
    if remaining > 0:
        realized += remaining
    return realized, reason


def run_intraday(cfg: dict) -> None:
    end = date.today()
    start = end - timedelta(days=65)
    events = _events_for(cfg, start, end)
    tz = cfg.get("tz") or ("Asia/Kolkata" if str(cfg.get("market")).upper() == "IN" else "America/New_York")
    print(f"mode=intraday market={cfg.get('market','US')} symbol={cfg['symbol']} window={start}..{end} events={len(events)}")
    strat = CatalystMomentum(cfg)
    rm = RiskGovernor(cfg)
    trades: list[dict] = []
    for cat in events:
        bars = data.get_intraday(cfg["symbol"], cat.day, tz=tz)
        if bars is None or len(bars) < 10:
            print(f"{cat.label:<28} SKIP no-bars")
            continue
        vix = data.get_prev_vix(cat.day, cfg["vix_symbol"])
        sig = strat.generate(bars, cat, vix)
        if sig is None:
            print(f"{cat.label:<24} FLAT no-breakout")
            rm.register_day_result(0.0)
            continue
        if not rm.can_trade():
            print(f"{cat.label:<24} HALTED risk-governor")
            continue
        stake = rm.stake()
        sigma = (vix / 100.0) if vix else cfg["sigma_floor"]
        exit_mult, reason = _exit_reason_prem(bars, sig, strat, sigma)
        pnl = round(stake * (exit_mult - 1.0), 2)
        rm.register_trade_result(pnl)
        rm.register_day_result(pnl)
        trade = {
            "date": cat.day.isoformat(),
            "event": cat.name,
            "side": sig.side,
            "entry_spot": round(sig.entry_spot, 2),
            "strike": sig.strike,
            "entry_premium": round(sig.premium, 3),
            "stake": stake,
            "exit_mult": round(exit_mult, 3),
            "reason": reason,
            "r_multiple": round(exit_mult - 1.0, 3),
            "pnl": pnl,
            "equity_after": round(rm.equity, 2),
        }
        trades.append(trade)
        print(f"{cat.label:<28} {sig.side.upper():4} stake={stake:>9.0f} x{exit_mult:>6.2f} [{reason}] pnl={pnl:>12.2f} eq={rm.equity:>12.2f}")
        if rm.ruined:
            print("RUIN FLOOR HIT — governor halted the account.")
            break
    summary = summarize(trades, rm.equity, rm.start_equity)
    save_outputs(trades, summary)
    print_summary(summary)


def run_daily_gap(cfg: dict, years_back: int = 5) -> None:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=365 * years_back)
    print(f"mode=daily-gap window={start}..{end} vix_min={cfg['vix_min']}")
    daily = data.get_daily(cfg["symbol"], start - timedelta(days=60), end)
    if daily is None or len(daily) < 50:
        print("no daily data available")
        return
    idx = pd.DatetimeIndex(daily.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    daily.index = idx.normalize()
    vix_daily = None
    vix_by_date: dict = {}
    if cfg["vix_min"] > 0:
        vix_daily = data.get_daily(cfg["vix_symbol"], start - timedelta(days=60), end)
        if vix_daily is not None:
            vidx = pd.DatetimeIndex(vix_daily.index)
            if vidx.tz is not None:
                vidx = vidx.tz_localize(None)
            vix_daily.index = vidx.normalize()
            vix_by_date = {ts.date(): i for i, ts in enumerate(vix_daily.index)}
    closes = daily["Close"]
    rets = closes.pct_change()
    vol10 = rets.rolling(10).std().shift(1) * (252 ** 0.5)
    rm = RiskGovernor(cfg)
    trades: list[dict] = []
    strat = CatalystMomentum(cfg)
    index_by_date = {ts.date(): i for i, ts in enumerate(daily.index)}
    events = [c for c in _events_for(cfg, start, end) if c.day in index_by_date]
    for cat in events:
        loc = index_by_date[cat.day]
        if loc < 11:
            continue
        if vix_by_date and cat.day in vix_by_date:
            vloc = vix_by_date[cat.day]
            if vloc >= 1:
                prev_vix = float(vix_daily["Close"].iloc[vloc - 1])
                if prev_vix < cfg["vix_min"]:
                    print(f"{cat.label:<24} SKIP vix={prev_vix:.1f}<{cfg['vix_min']}")
                    continue
        prev_close = float(daily["Close"].iloc[loc - 1])
        row = daily.iloc[loc]
        open_px, close_px = float(row["Open"]), float(row["Close"])
        gap = open_px / prev_close - 1.0
        if abs(gap) < cfg["daily_gap_min"]:
            print(f"{cat.label:<24} FLAT gap={gap:+.2%}")
            rm.register_day_result(0.0)
            continue
        if not rm.can_trade():
            print(f"{cat.label:<24} HALTED risk-governor")
            continue
        side = "call" if gap > 0 else "put"
        strike = round(open_px)
        sigma = max(float(vol10.iloc[loc]) if not pd.isna(vol10.iloc[loc]) else cfg["sigma_floor"], cfg["sigma_floor"])
        entry_ts = daily.index[loc].replace(hour=9, minute=30)
        close_ts = entry_ts.replace(hour=15, minute=55)
        prem_in = strat.premium_at(open_px, strike, entry_ts, sigma, side == "call")
        prem_out = strat.premium_at(close_px, strike, close_ts, sigma, side == "call")
        stake = rm.stake()
        exit_mult = prem_out / prem_in
        pnl = round(stake * (exit_mult - 1.0), 2)
        rm.register_trade_result(pnl)
        rm.register_day_result(pnl)
        trades.append(
            {
                "date": cat.day.isoformat(),
                "event": cat.name,
                "side": side,
                "gap_pct": round(gap * 100, 2),
                "strike": strike,
                "entry_premium": round(prem_in, 3),
                "exit_premium": round(prem_out, 3),
                "stake": stake,
                "exit_mult": round(exit_mult, 3),
                "reason": "eod",
                "r_multiple": round(exit_mult - 1.0, 3),
                "pnl": pnl,
                "equity_after": round(rm.equity, 2),
            }
        )
        print(f"{cat.label:<24} {side.upper():4} gap={gap:+.2%} x{exit_mult:>6.2f} pnl={pnl:>12.2f} eq={rm.equity:>12.2f}")
        if rm.ruined:
            print("RUIN FLOOR HIT — governor halted the account.")
            break
    summary = summarize(trades, rm.equity, rm.start_equity)
    save_outputs(trades, summary)
    print_summary(summary)


def main(mode: str = "intraday", symbol: str | None = None, risk_pct: float | None = None, years_back: int = 5) -> None:
    cfg = build_config(symbol=symbol, risk_pct=risk_pct)
    if mode == "daily":
        run_daily_gap(cfg, years_back=years_back)
    else:
        run_intraday(cfg)


if __name__ == "__main__":
    main()
