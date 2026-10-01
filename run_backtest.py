import argparse

from engine.config import build_config

MARKET_ALIASES = {"US": "US", "IN": "IN", "INDIA": "IN", "NSE": "IN", "IN_SENSEX": "IN_SENSEX", "SENSEX": "IN_SENSEX"}


def cli():
    parser = argparse.ArgumentParser(description="PREDATOR backtester")
    parser.add_argument("--mode", choices=["intraday", "daily"], default="intraday")
    parser.add_argument("--market", choices=["us", "in", "in_sensex"], default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--risk-pct", type=float, default=None)
    parser.add_argument("--years-back", type=int, default=5)
    parser.add_argument("--vix-min", type=float, default=None)
    args = parser.parse_args()
    market = MARKET_ALIASES.get(args.market.upper()) if args.market else None
    cfg = build_config(market=market, symbol=args.symbol, risk_pct=args.risk_pct, vix_min=args.vix_min)
    if args.mode == "daily":
        from engine.backtest import run_daily_gap

        run_daily_gap(cfg, years_back=args.years_back)
    else:
        from engine.backtest import run_intraday

        run_intraday(cfg)


if __name__ == "__main__":
    cli()
