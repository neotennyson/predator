import json
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def summarize(trades: list[dict], final_equity: float, start_equity: float) -> dict:
    if not trades:
        return {"trades": 0, "final_equity": round(final_equity, 2)}
    rs = [t["r_multiple"] for t in trades]
    wins = [r for r in rs if r > 0]
    equity_curve = []
    eq = start_equity
    for t in trades:
        eq += t["pnl"]
        equity_curve.append(eq)
    peak = start_equity
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(trades), 4),
        "avg_r": round(sum(rs) / len(rs), 3),
        "median_r": round(sorted(rs)[len(rs) // 2], 3),
        "best_r": round(max(rs), 2),
        "worst_r": round(min(rs), 2),
        "tail_hits_r10": sum(1 for r in rs if r >= 10),
        "expectancy_per_trade_pct": round(sum(t["pnl"] for t in trades) / sum(t["stake"] for t in trades), 4),
        "final_equity": round(final_equity, 2),
        "return_multiple": round(final_equity / start_equity, 3),
        "max_drawdown": round(max_dd, 4),
    }


def save_outputs(trades: list[dict], summary: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if trades:
        import csv

        with open(RESULTS_DIR / "journal.csv", "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(trades[0].keys()))
            writer.writeheader()
            writer.writerows(trades)
    with open(RESULTS_DIR / "summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)


def print_summary(summary: dict) -> None:
    print("\n===== PERFORMANCE SUMMARY =====")
    for key, value in summary.items():
        print(f"{key:>28}: {value}")
