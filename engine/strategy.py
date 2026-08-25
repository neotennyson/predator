from dataclasses import dataclass
from datetime import time

import pandas as pd

from .calendar import Catalyst
from .greeks import bs_price


@dataclass
class Signal:
    catalyst: Catalyst
    side: str
    entry_time: pd.Timestamp
    entry_spot: float
    strike: float
    premium: float
    stop_premium: float
    tp1_premium: float
    runner_premium: float


class CatalystMomentum:
    def __init__(self, cfg: dict):
        self.buffer_pct = cfg.get("buffer_pct", 0.0008)
        self.impulse_minutes = int(cfg.get("impulse_minutes", 15))
        self.min_impulse_pct = cfg.get("min_impulse_pct", 0.0015)
        self.stop_frac = cfg.get("stop_frac", 0.45)
        self.tp1_mult = cfg.get("tp1_mult", 2.0)
        self.tp1_frac = cfg.get("tp1_frac", 0.40)
        self.runner_mult = cfg.get("runner_mult", 25.0)
        self.sigma_floor = cfg.get("sigma_floor", 0.08)
        self.strike_step = float(cfg.get("strike_step", 1))
        self.confirm_bars = int(cfg.get("confirm_bars", 2))

        def _t(key, default):
            h, m = (int(x) for x in cfg.get(key, default).split(":"))
            return time(h, m)

        self.session_start = _t("session_start", "09:30")
        self.session_end = _t("session_end", "16:00")
        self.morning_cutoff = _t("morning_cutoff", "11:30")
        self.force_close = _t("force_close", "15:55")

    def _minutes_to_close(self, ts: pd.Timestamp) -> float:
        close_dt = ts.normalize() + pd.Timedelta(hours=self.session_end.hour, minutes=self.session_end.minute)
        return max((close_dt - ts).total_seconds() / 60.0, 10.0)

    def premium_at(self, spot: float, strike: float, ts: pd.Timestamp, sigma: float, side: str) -> float:
        t_years = max(self._minutes_to_close(ts) / (390.0 * 252.0), 10.0 / (390.0 * 252.0))
        return bs_price(spot, strike, t_years, max(sigma, self.sigma_floor), side == "call")

    def generate(self, bars: pd.DataFrame, catalyst: Catalyst, vix: float | None) -> Signal | None:
        if bars is None or len(bars) < 5:
            return None
        release_h, release_m = (int(x) for x in catalyst.release_hhmm.split(":"))
        day = bars.index[0].date()
        release_ts = pd.Timestamp(year=day.year, month=day.month, day=day.day, hour=release_h, minute=release_m, tz=bars.index.tz)
        session_open_ts = release_ts.replace(hour=self.session_start.hour, minute=self.session_start.minute)
        session_start = session_open_ts if release_ts < session_open_ts else release_ts
        impulse_end = session_start + pd.Timedelta(minutes=self.impulse_minutes)
        impulse = bars[(bars.index >= session_start) & (bars.index < impulse_end)]
        if len(impulse) < 3:
            return None
        imp_hi = float(impulse["High"].max())
        imp_lo = float(impulse["Low"].min())
        imp_mid = (imp_hi + imp_lo) / 2.0
        if imp_mid <= 0 or (imp_hi - imp_lo) / imp_mid < self.min_impulse_pct:
            return None
        up_level = imp_hi * (1.0 + self.buffer_pct)
        dn_level = imp_lo * (1.0 - self.buffer_pct)
        close_guard = release_ts.replace(hour=self.force_close.hour, minute=self.force_close.minute) - pd.Timedelta(minutes=10)
        cutoff = min(release_ts + pd.Timedelta(hours=3), close_guard)
        scan = bars[(bars.index >= impulse_end) & (bars.index <= cutoff)]
        sigma = (vix / 100.0) if vix else self.sigma_floor
        pending = None
        for ts, row in scan.iterrows():
            close = float(row["Close"])
            side = None
            if close > up_level:
                side = "call"
            elif close < dn_level:
                side = "put"
            if side is None:
                pending = None
                continue
            if pending is not None and pending["side"] == side and (ts - pending["ts"]).total_seconds() <= 900:
                entry_time = ts
                strike = round(close / self.strike_step) * self.strike_step
                premium = self.premium_at(close, strike, entry_time, sigma, side)
                return Signal(
                    catalyst=catalyst,
                    side=side,
                    entry_time=entry_time,
                    entry_spot=close,
                    strike=float(strike),
                    premium=premium,
                    stop_premium=premium * self.stop_frac,
                    tp1_premium=premium * self.tp1_mult,
                    runner_premium=premium * self.runner_mult,
                )
            pending = {"side": side, "ts": ts}
        return None
