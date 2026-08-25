class RiskGovernor:
    def __init__(self, cfg: dict):
        self.start_equity = float(cfg.get("start_equity", 100_000.0))
        self.risk_pct = float(cfg.get("risk_pct", 0.20))
        self.max_risk_pct = float(cfg.get("max_risk_pct", 0.25))
        self.daily_loss_cap = float(cfg.get("daily_loss_cap", 0.25))
        self.lose_streak_halt = int(cfg.get("lose_streak_halt", 2))
        self.ruin_floor = float(cfg.get("ruin_floor", 0.50))
        self.equity = self.start_equity
        self.peak = self.start_equity
        self.consecutive_loss_days = 0
        self.pending_skip = False
        self.ruined = False

    def stake(self) -> float:
        if self.ruined:
            return 0.0
        return round(self.equity * min(self.risk_pct, self.max_risk_pct, self.daily_loss_cap), 2)

    def can_trade(self) -> bool:
        if self.ruined:
            return False
        if self.pending_skip:
            self.pending_skip = False
            return False
        return self.consecutive_loss_days < self.lose_streak_halt

    def register_trade_result(self, pnl: float) -> None:
        self.equity += pnl
        self.peak = max(self.peak, self.equity)
        if self.equity <= self.start_equity * self.ruin_floor:
            self.ruined = True

    def register_day_result(self, day_pnl: float) -> None:
        if day_pnl < 0:
            self.consecutive_loss_days += 1
            if self.consecutive_loss_days >= self.lose_streak_halt:
                self.pending_skip = True
                self.consecutive_loss_days = 0
        else:
            self.consecutive_loss_days = 0

    def status(self) -> dict:
        return {
            "equity": round(self.equity, 2),
            "peak": round(self.peak, 2),
            "ruined": self.ruined,
            "consecutive_loss_days": self.consecutive_loss_days,
            "pending_skip": self.pending_skip,
        }
