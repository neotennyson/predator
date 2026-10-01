DEFAULTS = {
    "symbol": "SPY",
    "market": "US",
    "start_equity": 100_000.0,
    "risk_pct": 0.20,
    "max_risk_pct": 0.25,
    "daily_loss_cap": 0.25,
    "lose_streak_halt": 2,
    "ruin_floor": 0.50,
    "buffer_pct": 0.0008,
    "impulse_minutes": 15,
    "min_impulse_pct": 0.0015,
    "stop_frac": 0.45,
    "tp1_mult": 2.0,
    "tp1_frac": 0.40,
    "runner_mult": 25.0,
    "sigma_floor": 0.08,
    "daily_gap_min": 0.003,
    "vix_min": 0.0,
    "vix_symbol": "^VIX",
    "strike_step": 1,
    "confirm_bars": 2,
    "trail_giveback_pct": 0.30,
    "max_premium_pct_spot": 0.012,
    "est_costs_per_trade": 60,
}

MARKET_PROFILES = {
    "US": {"symbol": "SPY", "vix_symbol": "^VIX", "strike_step": 1, "session_start": "09:30", "session_end": "16:00", "force_close": "15:55", "morning_cutoff": "11:30"},
    "IN": {"symbol": "^NSEI", "vix_symbol": "^INDIAVIX", "strike_step": 50, "session_start": "09:15", "session_end": "15:30", "force_close": "15:20", "morning_cutoff": "11:00"},
    "IN_SENSEX": {"symbol": "^BSESN", "vix_symbol": "^INDIAVIX", "strike_step": 100, "session_start": "09:15", "session_end": "15:30", "force_close": "15:20", "morning_cutoff": "11:00"},
}


def build_config(**overrides) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    profile = MARKET_PROFILES.get(str(cfg.get("market", "US")).upper(), MARKET_PROFILES["US"])
    for key, value in profile.items():
        override_keys = {k for k in overrides if overrides.get(k) is not None}
        if key not in override_keys:
            cfg[key] = value
    return cfg
