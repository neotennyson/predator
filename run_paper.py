import argparse

from engine.config import build_config
from engine.paper import run_paper


def cli():
    parser = argparse.ArgumentParser(description="catalyst-engine paper/live trader")
    parser.add_argument("--market", choices=["us", "in"], default="in")
    parser.add_argument("--date", default=None, help="override day (YYYY-MM-DD)")
    parser.add_argument("--poll", type=int, default=60)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--risk-pct", type=float, default=0.20)
    parser.add_argument("--live", action="store_true", help="route orders to Dhan (requires DHAN_CLIENT_ID; token auto-fetched via token API)")
    args = parser.parse_args()
    cfg = build_config(market=args.market.upper(), symbol=args.symbol, risk_pct=args.risk_pct)
    run_paper(cfg=cfg, poll_seconds=args.poll, date_override=args.date, live=args.live)


if __name__ == "__main__":
    cli()
