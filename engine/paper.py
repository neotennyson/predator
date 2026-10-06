from __future__ import annotations

import csv
import time as time_mod
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

from . import calendar as cal
from . import calendar_in
from . import data
from .config import build_config
from .strategy import CatalystMomentum

from .notify import send as _tg


def _notify(text: str) -> None:
    try:
        _tg(text)
    except Exception:
        pass

JOURNAL = Path(__file__).resolve().parent.parent / "results" / "paper_journal.csv"

MARKET_CLOCK = {
    "US": {"tz": "America/New_York", "start": time(9, 30), "force_close": time(15, 55), "close": time(16, 0), "no_trade_after": time(15, 45)},
    "IN": {"tz": "Asia/Kolkata", "start": time(9, 15), "force_close": time(15, 20), "close": time(15, 30), "no_trade_after": time(14, 45)},
    "IN_SENSEX": {"tz": "Asia/Kolkata", "start": time(9, 15), "force_close": time(15, 20), "close": time(15, 30), "no_trade_after": time(14, 45)},
}

LOT_SIZE = {"NIFTY": 75, "BANKNIFTY": 35, "SENSEX": 20}


def _t(hhmm: str) -> time:
    h, m = (int(x) for x in hhmm.split(":"))
    return time(h, m)


def _catalyst_today(day, market: str):
    if market == "IN_SENSEX":
        if day.weekday() == 3:
            from .calendar import Catalyst

            return Catalyst(day, "SENSEX-EXPIRY", "09:15")
        return None
    if market == "IN":
        events = calendar_in.indian_events(day - timedelta(days=1), day + timedelta(days=1), include_monthly_expiry=True)
        for c in events:
            if c.day == day:
                return c
        return None
    return cal.catalyst_on(day)


def _journal_write(row: list) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL, "a", newline="") as fh:
        writer = csv.writer(fh)
        if fh.tell() == 0:
            writer.writerow(["timestamp", "event", "symbol", "mode", "side", "strike", "pnl"])
        writer.writerow(row)


def run_paper(cfg: dict | None = None, poll_seconds: int = 60, date_override: str | None = None, live: bool = False, underlying: str | None = None) -> None:
    cfg = cfg or build_config()
    market = str(cfg.get("market", "US")).upper()
    if underlying is None:
        underlying = "SENSEX" if market == "IN_SENSEX" else "NIFTY"
    clock = MARKET_CLOCK[market]
    symbol = cfg["symbol"]
    broker = None
    if live:
        from .broker_dhan import DhanBroker

        broker = DhanBroker()
    if date_override:
        day = pd.Timestamp(date_override).date()
    else:
        now0 = pd.Timestamp.now(tz=clock["tz"])
        day = now0.date()
    cat = _catalyst_today(day, market)
    print(f"paper mode market={market} symbol={symbol} day={day} live={live}")
    if cat is None:
        print("not a catalyst day.")
        return
    strat = CatalystMomentum(cfg)
    release_ts = strat.release_ts_for(cat, clock["tz"])
    vix_sigma = None
    try:
        from . import data as _data
        vix = _data.get_prev_vix(day, cfg.get("vix_symbol", "^INDIAVIX"))
        vix_sigma = (vix / 100.0) if vix else None
    except Exception:
        vix_sigma = None
    position: dict | None = None
    realized_pnl = 0.0
    remaining_frac = 1.0
    tp1_done = False
    exit_reason = None
    print(f"catalyst={cat.label} release={cat.release_hhmm} — engine armed")
    _notify(f"🐺 <b>PREDATOR ARMED</b> — {cat.name} · {'REAL MONEY' if broker else 'PRACTICE'} mode")

    while True:
        now = pd.Timestamp.now(tz=clock["tz"])
        bars = data.today_intraday(symbol, tz=clock["tz"])
        tag = ""
        if bars is not None and len(bars):
            last_ts = bars.index[-1]
            last_close = float(bars["Close"].iloc[-1])
            if position is None:
                sig = strat.generate(bars, cat, None)
                if sig is not None and now.time() >= clock["start"]:
                    try:
                        from .sentinel import veto_active
                        if veto_active():
                            print("VETO — red-flag news active, standing down")
                            _notify("🚨 <b>Trade vetoed</b> — red-flag news active. Predator stands down.")
                            sig = None
                    except Exception:
                        pass
                if sig is not None and now.time() >= clock["start"]:
                    try:
                        from .validation import check_confluence, get_day_multiplier
                        conf = check_confluence(sig.side)
                        if conf["action"] == "skip":
                            print(f"VETO — news contradicts {sig.side}: net {conf['net']:+d} over {conf['count']} headlines")
                            _notify(f"🚨 <b>Trade vetoed</b> — news contradicts {sig.side.upper()} (net {conf['net']:+d}).")
                            sig = None
                        elif conf["action"] == "confirm":
                            print(f"confluence CONFIRMS {sig.side} (net {conf['net']:+d})")
                            _notify(f"✅ News confluence confirms {sig.side.upper()} (net {conf['net']:+d}).")
                    except Exception:
                        pass
                if sig is not None and now.time() >= clock["start"]:
                    if sig.premium > sig.entry_spot * cfg.get("max_premium_pct_spot", 0.012):
                        print(f"PREMIUM TOO FAT — {sig.premium:.2f} > {cfg.get('max_premium_pct_spot', 0.012):.2%} of spot; move already priced in, skipping")
                        _notify(f"⚠️ Skipped {sig.side.upper()} — premium too expensive (IV pumped). No edge.")
                        sig = None
                if sig is not None and now.time() >= clock["start"]:
                    day_mult = 1.0
                    try:
                        from .validation import get_day_multiplier
                        day_mult = get_day_multiplier()
                    except Exception:
                        day_mult = 1.0
                    if day_mult <= 0:
                        print("DAY RATING C — standing down today (multiplier 0)")
                        _notify("🚨 <b>Day rated C</b> — conditions poor. Engine stands down for the session.")
                        sig = None
                    stake = round(cfg["start_equity"] * min(cfg["risk_pct"], cfg["daily_loss_cap"]) * day_mult, 2)
                    position = {
                        "side": sig.side,
                        "strike": sig.strike,
                        "premium": sig.premium,
                        "stake": stake,
                        "stop": sig.stop_premium,
                        "tp1": sig.tp1_premium,
                        "runner": sig.runner_premium,
                    }
                    if broker is not None:
                        expiry_list = broker.expiries(underlying)
                        if not expiry_list:
                            raise RuntimeError(f"no expiries returned for {underlying}")
                        expiry_str = str(expiry_list[0])[:10]
                        chain = broker.option_chain(underlying, expiry_str)
                        opt_type = "CE" if sig.side == "call" else "PE"
                        sec_id, strike, opt_ltp = broker.atm_option(chain, sig.entry_spot, sig.side, cfg.get("strike_step", 50))
                        opt_ltp = opt_ltp or max(sig.premium, 0.05)
                        lots = max(1, int(stake / (opt_ltp * LOT_SIZE[underlying])))
                        qty = lots * LOT_SIZE[underlying]
                        lot_cost = opt_ltp * LOT_SIZE[underlying]
                        if stake < lot_cost * 1.1:
                            msg = (f"⛔ SIZING GUARD: 1 lot of {underlying} costs ₹{lot_cost:.0f} "
                                   f"but risk budget is ₹{stake:.0f}. Trade skipped — switch to SENSEX (lot 20) "
                                   f"or raise risk %. Account protected.")
                            print(msg)
                            _notify(f"⛔ <b>Sizing guard</b> — 1 lot ₹{lot_cost:.0f} > budget ₹{stake:.0f}. Skipped, account protected.")
                            return
                        order = broker.buy_option(sec_id, qty, pd.Timestamp(expiry_str).date(), opt_type, underlying)
                        position.update({
                            "security_id": sec_id,
                            "lots": lots,
                            "qty": qty,
                            "expiry": expiry_str,
                            "option_type": opt_type,
                            "underlying": underlying,
                            "order_segment": "NSE_FNO" if underlying != "SENSEX" else "BSE_FNO",
                            "premium": opt_ltp,
                        })
                        print(f"LIVE ORDER orderId={order.get('orderId')} {sig.side.upper()} strike={strike} lots={lots} ltp={opt_ltp:.2f}")
                    position["entry_time"] = str(sig.entry_time)
                    print(f"OPEN {sig.side.upper()} @ {last_close:.2f} strike={position['strike']} prem={position['premium']:.2f} stake={stake:.0f}")
                    _notify(f"🐺 <b>PREDATOR OPEN</b> ({'LIVE' if broker else 'PRACTICE'})\n{sig.side.upper()} NIFTY {position['strike']:.0f}\npremium ≈ {position['premium']:.2f} · stake ₹{stake:.0f}")
            else:
                if broker is not None and position.get("security_id"):
                    prem = broker.ltp(position["security_id"], position.get("order_segment", "NSE_FNO"))
                else:
                    mtm_sigma = strat.sigma_at(last_ts, release_ts, vix_sigma)
                    prem = strat.premium_at(last_close, position["strike"], last_ts, mtm_sigma, position["side"] == "call")
                position["peak"] = max(position.get("peak", prem), prem)
                try:
                    from .sentinel import veto_active as _red
                    if _red():
                        exit_reason, fill = "news_red", prem
                        print("RED FLAG while in position — bailing out")
                        _notify("🚨 <b>Red-flag news while holding</b> — emergency exit.")
                except Exception:
                    pass
                if exit_reason is None and prem <= position["stop"]:
                    exit_reason, fill = "stop", position["stop"]
                elif exit_reason is None and not tp1_done and prem >= position["tp1"]:
                    tp1_done = True
                    frac = strat.tp1_frac
                    realized_pnl += position["stake"] * frac * (position["tp1"] / position["premium"] - 1.0)
                    remaining_frac -= frac
                    tag = f"TP1 hit prem={prem:.2f} banked={realized_pnl:.2f}"
                    _notify(f"✅ <b>TP1 HIT</b> — booked ₹{realized_pnl:.0f}, runner riding")
                elif exit_reason is None and tp1_done and prem >= position["runner"]:
                    exit_reason, fill = "runner", prem
                elif exit_reason is None and tp1_done and prem <= position["peak"] * (1.0 - cfg.get("trail_giveback_pct", 0.30)):
                    exit_reason, fill = "trail", prem
                    print(f"trail stop — giving back {cfg.get('trail_giveback_pct', 0.30):.0%} from peak {position['peak']:.2f}")
                elif exit_reason is None and now.time() >= clock["force_close"]:
                    exit_reason, fill = "eod", prem
                else:
                    tag = f"prem={prem:.2f} peak={position['peak']:.2f}"
                if exit_reason:
                    pnl = realized_pnl + position["stake"] * remaining_frac * (fill / position["premium"] - 1.0)
                    costs = float(cfg.get("est_costs_per_trade", 60))
                    net_total = pnl - costs
                    realized_pnl += pnl
                    print(f"CLOSE [{exit_reason}] prem={fill:.2f} gross={pnl:.2f} costs={costs:.0f} net={net_total:.2f}")
                    _notify(f"🏁 <b>CLOSE [{exit_reason}]</b>\ngross ₹{pnl:.0f} · costs ₹{costs:.0f} · <b>net ₹{net_total:.0f}</b>")
                    if broker is not None and position.get("security_id"):
                        try:
                            broker.exit_option(position["security_id"], position["qty"], pd.Timestamp(position["expiry"]).date(), position["option_type"], position.get("underlying", "NIFTY"))
                            print("live exit order placed")
                        except Exception as exc:
                            print(f"EXIT ORDER FAILED: {exc} — CHECK DHAN APP")
                    _journal_write([datetime.now().isoformat(), cat.name, symbol, "live" if broker else "virtual", position["side"], position["strike"], round(net_total, 2)])
                    return
                if tag:
                    print(tag)
        if now.time() >= clock["close"] or (position is None and now.time() > clock["no_trade_after"]):
            print("session over" if position is None else "session ended without forced close — check feed")
            _notify(f"🐺 Session over — {cat.name} {'· no trade taken' if position is None else f'· day P&L ₹{realized_pnl:.0f}'}")
            return
        time_mod.sleep(poll_seconds)


if __name__ == "__main__":
    run_paper()
