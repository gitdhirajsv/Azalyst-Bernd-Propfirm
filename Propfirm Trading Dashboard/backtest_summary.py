#!/usr/bin/env python3
"""
Post-process a walk-forward CSV (from run_walk_forward_30yr.py) and print
prop-firm-relevant statistics:

    - Total trades / weeks elapsed / trades per week
    - Win rate, avg R, expectancy
    - Max consecutive losses  (sizing the daily-loss limit)
    - Max drawdown in R       (sizing the total-drawdown limit)
    - Per-asset signal frequency
    - Worst rolling 4-week and 12-week stretches

Usage:
    python backtest_summary.py backtest_10yr_full.csv
"""

import sys
import csv
from collections import defaultdict
from datetime import datetime


def load(path):
    trades = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                row["r"] = float(row.get("r") or 0)
                row["date_obj"] = datetime.fromisoformat(row["date"]).date()
            except Exception:
                continue
            trades.append(row)
    trades.sort(key=lambda t: t["date_obj"])
    return trades


def main():
    if len(sys.argv) < 2:
        print("Usage: python backtest_summary.py <results.csv>")
        sys.exit(1)
    trades = load(sys.argv[1])
    if not trades:
        print("No trades found in CSV.")
        return

    start = trades[0]["date_obj"]
    end = trades[-1]["date_obj"]
    weeks = max(1, (end - start).days / 7)

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = sum(1 for t in trades if t["outcome"] == "LOSS")
    opens = sum(1 for t in trades if t["outcome"] == "OPEN")
    closed = wins + losses
    wr = wins / closed * 100 if closed else 0
    total_r = sum(t["r"] for t in trades)
    avg_r = total_r / closed if closed else 0

    # Max consecutive losses
    streak = max_streak = 0
    for t in trades:
        if t["outcome"] == "LOSS":
            streak += 1
            max_streak = max(max_streak, streak)
        elif t["outcome"] == "WIN":
            streak = 0

    # Max drawdown in R (peak-to-trough on cumulative R curve)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t["r"]
        peak = max(peak, cum)
        dd = peak - cum
        max_dd = max(max_dd, dd)

    # Worst rolling 4-week and 12-week stretches (in R)
    def worst_window(weeks_n):
        worst = 0.0
        for i, t in enumerate(trades):
            window_end = t["date_obj"]
            window_start = window_end.toordinal() - weeks_n * 7
            r_in_window = sum(
                u["r"] for u in trades[: i + 1]
                if u["date_obj"].toordinal() >= window_start
            )
            worst = min(worst, r_in_window)
        return worst

    worst_4w = worst_window(4)
    worst_12w = worst_window(12)

    # Per-asset signal frequency
    per_ac = defaultdict(lambda: {"n": 0, "w": 0, "l": 0, "r": 0.0})
    for t in trades:
        ac = t.get("asset_class", "?")
        per_ac[ac]["n"] += 1
        per_ac[ac]["r"] += t["r"]
        if t["outcome"] == "WIN":
            per_ac[ac]["w"] += 1
        elif t["outcome"] == "LOSS":
            per_ac[ac]["l"] += 1

    print()
    print("=" * 64)
    print("  PROP-FIRM PLANNING SUMMARY")
    print("=" * 64)
    print(f"  Period:          {start} -> {end}  ({weeks:.0f} weeks)")
    print(f"  Total signals:   {len(trades)}")
    print(f"  Trades / week:   {len(trades) / weeks:.2f}")
    print(f"  Closed:          {closed}  (W:{wins}  L:{losses}  Open:{opens})")
    print(f"  Win rate:        {wr:.1f}%")
    print(f"  Avg R (closed):  {avg_r:+.2f}R")
    print(f"  Total R:         {total_r:+.1f}R")
    print(f"  Expectancy:      {avg_r:+.2f}R per trade")
    print()
    print(f"  --- RISK SIZING (for challenge limits) ---")
    print(f"  Max consec losses:   {max_streak}")
    print(f"  Max DD (R):          {max_dd:.1f}R")
    print(f"  Worst 4-week R:      {worst_4w:+.1f}R")
    print(f"  Worst 12-week R:     {worst_12w:+.1f}R")
    print()
    print(f"  Rough $-translation @ 1% risk per trade on $100k account:")
    print(f"    Each R = $1,000")
    print(f"    Max DD = ${max_dd * 1000:,.0f}")
    print(f"    Worst 4-week = ${worst_4w * 1000:,.0f}")
    print()
    print(f"  --- BY ASSET CLASS ---")
    print(f"  {'Class':<22}{'N':>5}{'W':>4}{'L':>4}{'WR%':>7}{'TotR':>8}{'R/sig':>7}")
    for ac, d in sorted(per_ac.items(), key=lambda x: -x[1]["n"]):
        cl = d["w"] + d["l"]
        ac_wr = d["w"] / cl * 100 if cl else 0
        r_per = d["r"] / d["n"] if d["n"] else 0
        print(f"  {ac:<22}{d['n']:>5}{d['w']:>4}{d['l']:>4}"
              f"{ac_wr:>7.1f}{d['r']:>+8.1f}{r_per:>+7.2f}")
    print()


if __name__ == "__main__":
    main()
