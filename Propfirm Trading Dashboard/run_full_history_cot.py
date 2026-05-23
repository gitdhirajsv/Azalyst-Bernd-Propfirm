#!/usr/bin/env python3
"""
Full-history COT analysis — "pull as much data as you can"
(Bernd Skorupinski methodology)

Fetches ALL available CFTC history (~30 years for major contracts) via
paginated API calls and shows where current PRODUCER vs RETAILER positioning
sits relative to the ENTIRE available dataset.

This gives the three-band context Bernd uses:
  Band 1 — Rolling 26w/52w index  (standard real-time signal)
  Band 2 — 156-week extreme overlay (3yr historic comparison)
  Band 3 — ALL-TIME extreme         (30yr context — this script)

Usage:
    python run_full_history_cot.py              (all major contracts)
    python run_full_history_cot.py GC=F SI=F    (selected symbols only)
    python run_full_history_cot.py --csv        (save output to full_history_cot.csv)
"""

import sys
import os
import logging
import pandas as pd
from datetime import datetime

# Suppress info-level log noise during output
logging.basicConfig(level=logging.WARNING)

# Make sure the dashboard module is importable whether run from here or parent
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from BP_data_fetcher import DataFetcher, get_cftc_code
from BP_indicators import COTIndex


# ─── Symbol list + class mapping ───────────────────────────────────────────
MAJOR_SYMBOLS = [
    # Precious Metals
    'GC=F',   # Gold
    'SI=F',   # Silver
    'PL=F',   # Platinum
    'PA=F',   # Palladium
    # Energy
    'CL=F',   # Crude Oil WTI
    'NG=F',   # Natural Gas
    'HO=F',   # Heating Oil
    # Equity Indices
    'ES=F',   # S&P 500
    'NQ=F',   # Nasdaq 100
    'YM=F',   # Dow Jones
    'RTY=F',  # Russell 2000
    # Rates
    'ZB=F',   # 30Y Bond
    'ZN=F',   # 10Y Note
    # Currencies
    '6E=F',   # Euro
    '6B=F',   # GBP
    '6J=F',   # JPY
    '6A=F',   # AUD
    '6C=F',   # CAD
    '6S=F',   # CHF
    # Agriculturals
    'ZC=F',   # Corn
    'ZW=F',   # Wheat
    'ZS=F',   # Soybeans
    'CT=F',   # Cotton
    'KC=F',   # Coffee
    'SB=F',   # Sugar
    'CC=F',   # Cocoa
    # Base Metals
    'HG=F',   # Copper
]

ASSET_CLASS = {
    'GC=F': 'precious_metals', 'SI=F': 'precious_metals',
    'PL=F': 'precious_metals', 'PA=F': 'precious_metals',
    'CL=F': 'energies',        'NG=F': 'nat_gas',
    'HO=F': 'energies',        'RB=F': 'energies',
    'ES=F': 'equity_indices',  'NQ=F': 'equity_indices',
    'YM=F': 'equity_indices',  'RTY=F': 'equity_indices',
    'ZB=F': 'interest_rates',  'ZN=F': 'interest_rates',
    '6E=F': 'forex',           '6B=F': 'forex',
    '6J=F': 'forex',           '6A=F': 'forex',
    '6C=F': 'forex',           '6S=F': 'forex',
    '6N=F': 'forex',
    'ZC=F': 'commodities',     'ZW=F': 'commodities',
    'ZS=F': 'commodities',     'CT=F': 'commodities',
    'KC=F': 'soft_commodities','SB=F': 'soft_commodities',
    'CC=F': 'soft_commodities','HG=F': 'commodities',
}


def run_analysis(symbols=None, save_csv=False):
    if symbols is None:
        symbols = MAJOR_SYMBOLS

    fetcher = DataFetcher(allow_cot_simulation=False)

    # Use 52w lookback for rolling signal; 156w extreme overlay; alltime added below
    cot_engine_52 = COTIndex(lookback_weeks=52, extreme_lookback=156)
    cot_engine_26 = COTIndex(lookback_weeks=26, extreme_lookback=156)

    rows = []

    header = (
        f"\n{'=' * 110}\n"
        f"FULL-HISTORY COT — PRODUCER vs RETAILER (ALL-TIME CONTEXT)\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'=' * 110}"
    )
    print(header)

    col_hdr = (
        f"{'Symbol':<8} {'Yrs':>5} {'Wks':>5}  "
        f"{'CommPct':>7} {'RetPct':>7}  "
        f"{'Comm@All':>9} {'Ret@All':>8}  "
        f"{'Roll52w':>8} {'156w-ext':>9}  "
        f"SIGNAL"
    )
    print(col_hdr)
    print("-" * 110)

    for symbol in symbols:
        cftc = get_cftc_code(symbol)
        if not cftc:
            print(f"{symbol:<8}  No CFTC code — skipped")
            continue

        asset_class = ASSET_CLASS.get(symbol, 'commodities')

        # Fetch full CFTC history (paginated — may take a few seconds per symbol)
        print(f"{symbol:<8}  Fetching full history...", end='\r', flush=True)
        full_df = fetcher.fetch_cot_full_history(cftc)

        if full_df.empty:
            print(f"{symbol:<8}  [FAILED — API unreachable or no data]")
            continue

        # ── Calculate COT on full history ──────────────────────────────────
        # Using the full dataset for the rolling windows gives the richest
        # all-time comparison.  The 52w and 156w windows are still "rolling"
        # but normalised against the same history.
        cot_all = cot_engine_52.calculate(full_df)

        # Producer vs retailer summary using global min/max of full dataset
        summary = cot_engine_52.producer_vs_retailer_summary(full_df)

        # Rolling 52w bias (uses only last 260 rows so the signal matches
        # what the live scanner computes — same window, same answer)
        recent_df = full_df.iloc[-260:] if len(full_df) > 260 else full_df
        cot_recent = cot_engine_52.calculate(recent_df)
        bias52, str52 = cot_engine_52.get_bias(cot_recent, asset_class, return_strength=True)

        # 156w extreme on full history
        latest = cot_all.iloc[-1]
        comm_156 = latest.get('comm_net_extreme', None)
        comm_156_str = f"{comm_156:6.1f}" if comm_156 is not None and not pd.isna(comm_156) else "  N/A "

        bias_tag = f"{bias52[:4].upper():>4}/{str52[:4]:>4}"
        signal   = summary.get('signal', 'NEUTRAL')
        detail   = summary.get('detail', '')

        # Color-code the signal for terminal readability
        RESET  = '\033[0m'
        GREEN  = '\033[92m'
        RED    = '\033[91m'
        YELLOW = '\033[93m'
        if 'STRONG BUY' in signal:
            sig_colored = f"{GREEN}{signal}{RESET}"
        elif 'STRONG SELL' in signal:
            sig_colored = f"{RED}{signal}{RESET}"
        elif signal == 'BULLISH':
            sig_colored = f"{GREEN}BULLISH{RESET}"
        elif signal == 'BEARISH':
            sig_colored = f"{RED}BEARISH{RESET}"
        else:
            sig_colored = f"{YELLOW}{signal}{RESET}"

        line = (
            f"{symbol:<8} {summary['years_of_data']:>5.1f} {summary['total_weeks']:>5}  "
            f"{summary['comm_percentile']:>7.1f} {summary['sspec_percentile']:>7.1f}  "
            f"{summary['alltime_comm_index']:>9.1f} {summary['alltime_sspec_index']:>8.1f}  "
            f"{bias_tag:>8} {comm_156_str:>9}  "
            f"{sig_colored}"
        )
        print(line)

        rows.append({
            'symbol':             symbol,
            'asset_class':        asset_class,
            'years_of_data':      summary['years_of_data'],
            'total_weeks':        summary['total_weeks'],
            'comm_percentile':    summary['comm_percentile'],
            'sspec_percentile':   summary['sspec_percentile'],
            'lspec_percentile':   summary.get('lspec_percentile', None),
            'alltime_comm_index': summary['alltime_comm_index'],
            'alltime_sspec_index':summary['alltime_sspec_index'],
            'alltime_lspec_index':summary.get('alltime_lspec_index', None),
            'rolling_52w_bias':   bias52,
            'rolling_52w_strength': str52,
            'comm_156w_ext':      float(comm_156) if comm_156 is not None and not pd.isna(comm_156) else None,
            'signal':             signal,
            'detail':             detail,
        })

    print("=" * 110)

    # ── Highlight the strongest all-time signals ───────────────────────────
    strong = [r for r in rows if r['signal'] in ('STRONG BUY', 'STRONG SELL')]
    bullish = [r for r in rows if r['signal'] == 'BULLISH']
    bearish = [r for r in rows if r['signal'] == 'BEARISH']

    if strong or bullish or bearish:
        print("\n*** ACTIONABLE SIGNALS (all-time context):")
        if strong:
            print(f"\n  STRONG (Commercials + Retailers at OPPOSITE all-time extremes):")
            for r in strong:
                arrow = "^" if r['signal'] == 'STRONG BUY' else "v"
                print(f"    {arrow} {r['symbol']:<8}  {r['detail']}")
        if bullish:
            print(f"\n  BULLISH:")
            for r in bullish:
                print(f"    ^ {r['symbol']:<8}  {r['detail']}")
        if bearish:
            print(f"\n  BEARISH:")
            for r in bearish:
                print(f"    v {r['symbol']:<8}  {r['detail']}")

    print("\nLEGEND:")
    print("  CommPct   = Commercials net position percentile vs ALL-TIME history (100=all-time high net long)")
    print("  RetPct    = Retailers net position percentile vs ALL-TIME history   (0=all-time high net short)")
    print("  Comm@All  = COT V2 score (-20 to +120) using all-time min/max.  >=80 = historic extreme LONG")
    print("  Ret@All   = Same for retailers.                                   <=20 = historic extreme SHORT")
    print("  Roll52w   = Standard 52-week rolling bias (bias/strength) - matches live scanner")
    print("  156w-ext  = Commercials 156w extreme band value (Phase 17/18 trigger threshold)")
    print("  SIGNAL    = Cross-category signal on all-time scale")
    print("  STRONG BUY  = Comm all-time extreme LONG + Retailers all-time extreme SHORT simultaneously")
    print("  STRONG SELL = Comm all-time extreme SHORT + Retailers all-time extreme LONG simultaneously")
    print()

    if save_csv and rows:
        out = pd.DataFrame(rows)
        fname = f"full_history_cot_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        out.to_csv(fname, index=False)
        print(f"  Saved to {fname}")

    return rows


if __name__ == '__main__':
    args = sys.argv[1:]
    save_csv = '--csv' in args
    symbols_arg = [a for a in args if not a.startswith('--')]

    symbols = symbols_arg if symbols_arg else None
    run_analysis(symbols=symbols, save_csv=save_csv)
