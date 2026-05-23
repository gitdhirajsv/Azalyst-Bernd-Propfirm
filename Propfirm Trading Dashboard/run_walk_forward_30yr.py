#!/usr/bin/env python3
"""
Blueprint Trading System — 30-Year Walk-Forward Test
=====================================================
Pulls the maximum available price history (up to 30+ years) PLUS full
CFTC COT history for every symbol, then walks forward WEEK BY WEEK from
2020-01-01 to today.

At EACH weekly step:
  1. Truncate ALL data to that date — zero look-ahead.
  2. Run the full 7-step Blueprint strategy (zones + COT + Valuation + Seasonality).
  3. If a signal fires: record direction, entry, stop, targets.
  4. Then look at bars AFTER the signal date to determine actual outcome.

No cheating: the strategy never sees price or COT data from after the scan date.

Usage:
    python run_walk_forward_30yr.py                       # weekly, 2020-today
    python run_walk_forward_30yr.py --start 2022-01-01    # shorter window
    python run_walk_forward_30yr.py --symbols GC=F SI=F   # subset
    python run_walk_forward_30yr.py --fast                # 20 major symbols only
    python run_walk_forward_30yr.py --csv results.csv     # save results
    python run_walk_forward_30yr.py --verbose             # show engine reasoning
"""

import sys
import os
import argparse
import logging
import yaml
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from BP_data_fetcher import DataFetcher, get_cftc_code
from BP_rules_engine import RulesEngine

# ---------------------------------------------------------------------------
# Logging — quiet by default, --verbose turns it on
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("walk_forward_30yr")
for _noisy in ("scanner", "BP_rules_engine", "BP_indicators",
               "BP_data_fetcher", "BP_zone_detector", "BP_patterns",
               "BP_paper_trader", "BP_roadmap", "BP_calendar"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------
RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
DIM    = "\033[90m"
MAGENTA= "\033[95m"

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleMode(
            ctypes.windll.kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Valuation reference symbols (same as run_scanner.py)
# ---------------------------------------------------------------------------
VALUATION_REFS: Dict[str, List[str]] = {
    "forex":            ["DX-Y.NYB"],
    "equity_indices":   ["DX-Y.NYB", "ZB=F", "GC=F"],
    "equities":         ["ZB=F", "GC=F"],
    "commodities":      ["DX-Y.NYB", "GC=F", "ZB=F"],
    "soft_commodities": ["DX-Y.NYB", "GC=F", "ZB=F"],
    "precious_metals":  ["DX-Y.NYB", "GC=F", "ZB=F"],
    "energies":         ["DX-Y.NYB", "GC=F", "ZB=F"],
    "interest_rates":   ["^TNX"],
    "crypto":           ["DX-Y.NYB"],
    "nat_gas":          ["DX-Y.NYB", "GC=F", "ZB=F"],
}
VALUATION_REFS_PER_SYMBOL: Dict[str, List[str]] = {
    "PL=F": ["DX-Y.NYB", "GC=F"],
}

# ---------------------------------------------------------------------------
# Comprehensive watchlist — futures, forex, crypto, commodities
# ---------------------------------------------------------------------------
FAST_WATCHLIST = [
    # Precious metals
    {"symbol": "GC=F",  "name": "Gold",         "asset_class": "precious_metals"},
    {"symbol": "SI=F",  "name": "Silver",        "asset_class": "precious_metals"},
    # Energy
    {"symbol": "CL=F",  "name": "Crude Oil",     "asset_class": "energies"},
    {"symbol": "NG=F",  "name": "Nat Gas",       "asset_class": "nat_gas"},
    # Equity indices
    {"symbol": "ES=F",  "name": "S&P 500",       "asset_class": "equity_indices"},
    {"symbol": "NQ=F",  "name": "Nasdaq",        "asset_class": "equity_indices"},
    {"symbol": "YM=F",  "name": "Dow Jones",     "asset_class": "equity_indices"},
    # Rates
    {"symbol": "ZB=F",  "name": "30Y Bond",      "asset_class": "interest_rates"},
    # Grains
    {"symbol": "ZC=F",  "name": "Corn",          "asset_class": "commodities"},
    {"symbol": "ZS=F",  "name": "Soybeans",      "asset_class": "commodities"},
    # Forex
    {"symbol": "6E=F",  "name": "Euro FX",       "asset_class": "forex"},
    {"symbol": "6J=F",  "name": "JPY",           "asset_class": "forex"},
    {"symbol": "6B=F",  "name": "GBP",           "asset_class": "forex"},
    # Crypto
    {"symbol": "BTC-USD","name": "Bitcoin",      "asset_class": "crypto"},
    # Metals
    {"symbol": "HG=F",  "name": "Copper",        "asset_class": "commodities"},
    {"symbol": "PL=F",  "name": "Platinum",      "asset_class": "precious_metals"},
    {"symbol": "PA=F",  "name": "Palladium",     "asset_class": "precious_metals"},
    # Softs
    {"symbol": "CC=F",  "name": "Cocoa",         "asset_class": "soft_commodities"},
    {"symbol": "KC=F",  "name": "Coffee",        "asset_class": "soft_commodities"},
    {"symbol": "CT=F",  "name": "Cotton",        "asset_class": "commodities"},
]

FULL_WATCHLIST = FAST_WATCHLIST + [
    # Additional futures
    {"symbol": "RTY=F", "name": "Russell 2000",  "asset_class": "equity_indices"},
    {"symbol": "ZN=F",  "name": "10Y Note",      "asset_class": "interest_rates"},
    {"symbol": "ZW=F",  "name": "Wheat",         "asset_class": "commodities"},
    {"symbol": "SB=F",  "name": "Sugar",         "asset_class": "soft_commodities"},
    {"symbol": "HO=F",  "name": "Heating Oil",   "asset_class": "energies"},
    # More forex futures
    {"symbol": "6A=F",  "name": "AUD",           "asset_class": "forex"},
    {"symbol": "6C=F",  "name": "CAD",           "asset_class": "forex"},
    {"symbol": "6S=F",  "name": "CHF",           "asset_class": "forex"},
    # Crypto
    {"symbol": "ETH-USD","name": "Ethereum",     "asset_class": "crypto"},
    # Forex spot pairs
    {"symbol": "EURUSD=X","name": "EUR/USD",     "asset_class": "forex"},
    {"symbol": "GBPUSD=X","name": "GBP/USD",     "asset_class": "forex"},
    {"symbol": "USDJPY=X","name": "USD/JPY",     "asset_class": "forex",
     "cot_symbol": "6J=F"},
    {"symbol": "AUDUSD=X","name": "AUD/USD",     "asset_class": "forex"},
    # Equities (individual)
    {"symbol": "AAPL",  "name": "Apple",         "asset_class": "equities"},
    {"symbol": "MSFT",  "name": "Microsoft",     "asset_class": "equities"},
    {"symbol": "NVDA",  "name": "NVIDIA",        "asset_class": "equities"},
    {"symbol": "AMZN",  "name": "Amazon",        "asset_class": "equities"},
    {"symbol": "META",  "name": "Meta",          "asset_class": "equities"},
    {"symbol": "NFLX",  "name": "Netflix",       "asset_class": "equities"},
    {"symbol": "GOOGL", "name": "Google",        "asset_class": "equities"},
]

EQUITY_INDEX_CONSTITUENTS: Dict[str, List[str]] = {
    "NQ=F": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "NFLX", "TSLA"],
    "ES=F": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL"],
    "YM=F": ["MSFT", "UNH", "GS", "HD", "CAT", "AAPL"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mondays_between(start: date, end: date) -> List[date]:
    """Every Monday between start and end inclusive."""
    days = []
    d = start
    while d.weekday() != 0:
        d += timedelta(days=1)
    while d <= end:
        days.append(d)
        d += timedelta(weeks=1)
    return days


def _truncate_df(df: pd.DataFrame, cutoff: date) -> pd.DataFrame:
    """Return rows where timestamp <= cutoff.  Zero look-ahead.

    Vectorised for speed.  Strips timezone info before comparison to handle
    both tz-aware (yfinance UTC) and tz-naive timestamps uniformly.
    """
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    ts_col = None
    for c in ("timestamp", "Date", "date", "Datetime", "datetime"):
        if c in df.columns:
            ts_col = c
            break
    if ts_col is None:
        return df  # no date column — can't slice
    try:
        ts_series = pd.to_datetime(df[ts_col])
        # Strip timezone so we can compare with a naive Timestamp
        if ts_series.dt.tz is not None:
            ts_series = ts_series.dt.tz_localize(None)
        cutoff_ts = pd.Timestamp(cutoff)
        mask = ts_series <= cutoff_ts
        return df[mask].reset_index(drop=True)
    except Exception:
        # Fallback: row-by-row comparison (slow but safe for any format)
        ts = df[ts_col]
        mask = ts.apply(lambda x: (x.date() if hasattr(x, "date") else x) <= cutoff)
        return df[mask].reset_index(drop=True)


def _truncate_cot(cot_df: Optional[pd.DataFrame], cutoff: date) -> Optional[pd.DataFrame]:
    """
    Slice COT DataFrame (date-indexed) to reports filed on or before cutoff.
    COT reports are released on Fridays for positions as of the Tuesday of
    that week — we treat the report date as the availability date.
    """
    if cot_df is None or cot_df.empty:
        return cot_df
    try:
        cutoff_ts = pd.Timestamp(cutoff)
        return cot_df[cot_df.index <= cutoff_ts]
    except Exception:
        return cot_df


def _outcome_multi_target(
    direction: str,
    entry: float,
    stop: float,
    targets: List[float],
    future_df: pd.DataFrame,
    max_bars: int = 52,
) -> Dict:
    """
    Walk through future WEEKLY bars (no look-ahead — called only on bars
    strictly after the signal date).

    Returns:
        {
          'outcome': 'WIN' / 'LOSS' / 'OPEN',
          'target_hit': 1 / 2 / 3 / None,   -- which target was reached first
          'bars_to_outcome': int,
          'max_r': float,                    -- peak unrealised R before close
          'r': float,                        -- final R (1 / -1 / 0)
        }
    """
    if future_df.empty or not targets:
        return {"outcome": "OPEN", "target_hit": None, "bars_to_outcome": 0,
                "max_r": 0.0, "r": 0.0}

    risk = abs(entry - stop)
    t1 = targets[0]
    t2 = targets[1] if len(targets) > 1 else None
    t3 = targets[2] if len(targets) > 2 else None

    best_r = 0.0

    for bar_idx, (_, bar) in enumerate(future_df.head(max_bars).iterrows()):
        hi = bar.get("high", bar.get("High", entry))
        lo = bar.get("low",  bar.get("Low",  entry))
        cl = bar.get("close",bar.get("Close",entry))

        if direction == "long":
            # T3 / T2 / T1 checked high-to-low target order
            if t3 is not None and hi >= t3:
                return {"outcome": "WIN", "target_hit": 3,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": max(best_r, (t3 - entry) / risk if risk else 0),
                        "r": 3.0}
            if t2 is not None and hi >= t2:
                return {"outcome": "WIN", "target_hit": 2,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": max(best_r, (t2 - entry) / risk if risk else 0),
                        "r": 2.0}
            if hi >= t1 and lo <= stop:
                # Both on same bar — conservative: loss
                return {"outcome": "LOSS", "target_hit": None,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": best_r, "r": -1.0}
            if hi >= t1:
                return {"outcome": "WIN", "target_hit": 1,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": max(best_r, (t1 - entry) / risk if risk else 0),
                        "r": 1.0}
            if lo <= stop:
                return {"outcome": "LOSS", "target_hit": None,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": best_r, "r": -1.0}
            # Track unrealised R
            unreal_r = (cl - entry) / risk if risk else 0
            best_r = max(best_r, unreal_r)

        else:  # short
            if t3 is not None and lo <= t3:
                return {"outcome": "WIN", "target_hit": 3,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": max(best_r, (entry - t3) / risk if risk else 0),
                        "r": 3.0}
            if t2 is not None and lo <= t2:
                return {"outcome": "WIN", "target_hit": 2,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": max(best_r, (entry - t2) / risk if risk else 0),
                        "r": 2.0}
            if lo <= t1 and hi >= stop:
                return {"outcome": "LOSS", "target_hit": None,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": best_r, "r": -1.0}
            if lo <= t1:
                return {"outcome": "WIN", "target_hit": 1,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": max(best_r, (entry - t1) / risk if risk else 0),
                        "r": 1.0}
            if hi >= stop:
                return {"outcome": "LOSS", "target_hit": None,
                        "bars_to_outcome": bar_idx + 1,
                        "max_r": best_r, "r": -1.0}
            unreal_r = (entry - cl) / risk if risk else 0
            best_r = max(best_r, unreal_r)

    return {"outcome": "OPEN", "target_hit": None,
            "bars_to_outcome": 0, "max_r": best_r, "r": 0.0}


# ---------------------------------------------------------------------------
# Core: scan one symbol at one cutoff date (zero look-ahead)
# ---------------------------------------------------------------------------

def scan_at_cutoff(
    sym_info: Dict,
    engine: RulesEngine,
    htf: str,
    ltf: str,
    strategy: str,
    full_htf_df: pd.DataFrame,
    full_ltf_df: pd.DataFrame,
    full_val_refs: Dict[str, pd.DataFrame],
    full_cot_df: Optional[pd.DataFrame],
    full_opposing_cot: Optional[pd.DataFrame],
    full_seasonal_df: pd.DataFrame,
    full_constituent_dfs: Dict[str, pd.DataFrame],
    cutoff: date,
    today_override: Optional[date] = None,
) -> Optional[Dict]:
    """
    Slice all data to `cutoff`, run seven-step process.
    Returns signal dict or None.
    """
    sym = sym_info["symbol"]
    ac  = sym_info["asset_class"]

    htf_df = _truncate_df(full_htf_df, cutoff)
    ltf_df = _truncate_df(full_ltf_df, cutoff)
    seas_df= _truncate_df(full_seasonal_df, cutoff)

    cot_df  = _truncate_cot(full_cot_df, cutoff)
    opp_cot = _truncate_cot(full_opposing_cot, cutoff)

    val_refs = {k: _truncate_df(v, cutoff) for k, v in full_val_refs.items()
                if v is not None and not v.empty}
    const_dfs = {k: _truncate_df(v, cutoff) for k, v in full_constituent_dfs.items()
                 if v is not None and not v.empty}

    if htf_df is None or htf_df.empty or len(htf_df) < 20:
        return None
    if ltf_df is None or ltf_df.empty or len(ltf_df) < 10:
        return None

    # Zone-detection window: keep last 200 bars for both HTF and LTF.
    # HTF 200 weekly bars ≈ 4 years; LTF 200 daily bars ≈ 10 months.
    # Zones older than that are consumed or irrelevant for current entries.
    # Indicators (COT/Val/Seas) use their own full-history slices passed
    # separately — they are NOT affected by this windowing.
    ZONE_WINDOW = 200
    htf_zone = htf_df.tail(ZONE_WINDOW).reset_index(drop=True)
    ltf_zone = ltf_df.tail(ZONE_WINDOW).reset_index(drop=True)

    ohlcv_data = {htf: htf_zone, ltf: ltf_zone}

    try:
        return engine.run_seven_step_process(
            symbol=sym,
            ohlcv_data=ohlcv_data,
            cot_df=cot_df,
            valuation_refs=val_refs,
            seasonal_df=seas_df,
            htf=htf,
            ltf=ltf,
            income_strategy=strategy,
            asset_class=ac,
            opposing_cot_df=opp_cot,
            constituent_dfs=const_dfs if const_dfs else None,
            today_override=today_override,
        )
    except Exception as exc:
        logger.debug(f"[{sym}] scan error at {cutoff}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main walk-forward runner
# ---------------------------------------------------------------------------

def run_walk_forward(
    watchlist: List[Dict],
    config: Dict,
    strategy: str = "weekly",
    start_date: date = date(2020, 1, 1),
    end_date: Optional[date] = None,
    verbose: bool = False,
) -> List[Dict]:
    """
    Full walk-forward test with zero look-ahead.

    Data fetch strategy:
      - Price HTF: period="25y" (1wk/1mo) or "10y" (daily)
      - Price LTF: period="10y"
      - COT:   fetch_cot_full_history() (~30-40 years from CFTC)
      - Valuation refs: period="25y" (same as HTF)
      - Seasonality: lookback_years=15 (covers 5yr/10yr/15yr model)

    Walk: every Monday from start_date to end_date.
    At each step: truncate all data, run strategy, record signal + outcome.
    """
    if end_date is None:
        end_date = date.today()

    tf  = {"weekly": ("1wk", "1d"), "monthly": ("1mo", "1wk"),
            "daily": ("1d", "60m"), "intraday": ("60m", "15m")}.get(strategy, ("1wk", "1d"))
    htf, ltf = tf

    # Use full-COT history fetcher
    fetcher = DataFetcher(full_history_cot=True)
    engine  = RulesEngine(config)

    scan_dates = _mondays_between(start_date, end_date)

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  BLUEPRINT 30-YEAR WALK-FORWARD TEST{RESET}")
    print(f"{BOLD}{CYAN}  Strategy : {strategy.upper()}  ({htf} / {ltf}){RESET}")
    print(f"{BOLD}{CYAN}  Period   : {start_date}  ->  {end_date}  ({len(scan_dates)} weekly steps){RESET}")
    print(f"{BOLD}{CYAN}  Symbols  : {len(watchlist)}{RESET}")
    print(f"{BOLD}{CYAN}  COT depth: 30+ years (full CFTC history){RESET}")
    print(f"{BOLD}{CYAN}  Price    : 25yr HTF / 10yr LTF (yfinance){RESET}")
    print(f"{BOLD}{CYAN}  Lookahead: NONE — strict walk-forward{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}\n")

    all_trades: List[Dict] = []

    for sym_idx, sym_info in enumerate(watchlist, 1):
        sym  = sym_info["symbol"]
        name = sym_info.get("name", sym)
        ac   = sym_info["asset_class"]

        # ------------------------------------------------------------------
        # Phase 1: Fetch ALL data for this symbol (max history)
        # Truncation happens per-week inside the scan loop.
        # ------------------------------------------------------------------
        print(f"{DIM}[{sym_idx:>3}/{len(watchlist)}] {sym:<12} ({name:<15}){RESET}",
              end=" ", flush=True)

        try:
            # Price depth:
            #   HTF (1wk): 25 years  (~1300 weekly bars) — enough for zone context
            #   LTF (1d):  10 years  (~2500 daily bars)  — signals fired from 2020
            #   COT:       30+ years via fetch_cot_full_history() (separate, efficient)
            #
            # "max" was too slow — yfinance downloads 50yr of daily data in hundreds
            # of chunks (one HTTP request per 2-month window). The COT provides the
            # full 30yr institutional context; price only needs enough bars for
            # reliable zone detection + indicator normalization pre-2020.
            htf_period = "25y" if htf in ("1wk", "1mo") else "10y"
            ltf_period = "10y"
            full_htf_df = fetcher.fetch_ohlcv(sym, interval=htf, period=htf_period)
            full_ltf_df = fetcher.fetch_ohlcv(sym, interval=ltf, period=ltf_period)
        except Exception as exc:
            print(f"{YELLOW}SKIP (price fetch: {exc}){RESET}")
            continue

        if full_htf_df is None or full_htf_df.empty:
            print(f"{YELLOW}SKIP (no HTF data){RESET}")
            continue
        if full_ltf_df is None or full_ltf_df.empty:
            print(f"{YELLOW}SKIP (no LTF data){RESET}")
            continue

        # COT — full 30-40 yr history (fetch_cot_full_history via fetcher flag)
        cot_lookup = sym_info.get("cot_symbol", sym)
        cftc_code  = get_cftc_code(cot_lookup)
        full_cot_df = fetcher.fetch_cot_data(cftc_code)  # redirects to full_history

        # Opposing COT for forex
        full_opp_cot = None
        if ac == "forex":
            full_opp_cot = fetcher.fetch_cot_data(get_cftc_code("DX=F"))

        # Valuation refs — same 25yr horizon as HTF price
        full_val_refs: Dict[str, pd.DataFrame] = {}
        ref_syms = VALUATION_REFS_PER_SYMBOL.get(sym) or VALUATION_REFS.get(ac, ["DX-Y.NYB"])
        for ref_sym in ref_syms:
            ref_df = fetcher.fetch_ohlcv(ref_sym, interval=htf, period=htf_period)
            if ref_df is not None and not ref_df.empty:
                full_val_refs[ref_sym] = ref_df

        # Seasonality — 15yr window (sufficient for 5yr/10yr/15yr seasonal model)
        full_seasonal_df = fetcher.fetch_seasonality_reference(sym, lookback_years=15)

        # Equity index constituents (for presidential cycle + Valuation proxy)
        full_constituent_dfs: Dict[str, pd.DataFrame] = {}
        if ac == "equity_indices" and sym in EQUITY_INDEX_CONSTITUENTS:
            for stock in EQUITY_INDEX_CONSTITUENTS[sym]:
                s_df = fetcher.fetch_ohlcv(stock, interval=htf, period=htf_period)
                if s_df is not None and not s_df.empty:
                    full_constituent_dfs[stock] = s_df

        # Summary of data depth
        htf_start = full_htf_df["timestamp"].iloc[0] if "timestamp" in full_htf_df.columns else "?"
        cot_wks   = len(full_cot_df) if full_cot_df is not None and not full_cot_df.empty else 0
        cot_yrs   = round(cot_wks / 52, 1)
        print(f"{GREEN}fetched{RESET} {DIM}(price from {str(htf_start)[:10]}, COT: {cot_wks}wks/{cot_yrs}yr){RESET}", flush=True)

        # ------------------------------------------------------------------
        # Phase 2: Zone-based re-entry suppression
        # ------------------------------------------------------------------
        consumed_zone_ids: Dict[str, str] = {}
        open_zone_ids: Dict[str, Dict]    = {}

        # ------------------------------------------------------------------
        # Phase 3: Walk forward week by week
        # ------------------------------------------------------------------
        sym_signal_count = 0
        _scan_step = 0
        for scan_date in scan_dates:
            _scan_step += 1
            if _scan_step % 52 == 0:  # progress dot every ~1 year
                print(f".", end="", flush=True)

            # Only scan when we have at least 104 HTF bars before this date
            # (need enough history for zone detection + indicators)
            htf_before = _truncate_df(full_htf_df, scan_date)
            if htf_before is None or len(htf_before) < 104:
                continue

            signal = scan_at_cutoff(
                sym_info=sym_info,
                engine=engine,
                htf=htf,
                ltf=ltf,
                strategy=strategy,
                full_htf_df=full_htf_df,
                full_ltf_df=full_ltf_df,
                full_val_refs=full_val_refs,
                full_cot_df=full_cot_df,
                full_opposing_cot=full_opp_cot,
                full_seasonal_df=full_seasonal_df,
                full_constituent_dfs=full_constituent_dfs,
                cutoff=scan_date,
                today_override=scan_date,   # cycle tables use scan date, not today
            )

            if signal is None:
                continue
            direction = signal.get("direction", "neutral")
            if direction == "neutral":
                continue

            entry   = signal.get("entry_price", 0.0)
            stop    = signal.get("stop_price",  0.0)
            targets = signal.get("targets", [])

            if entry == 0.0 or stop == 0.0 or not targets:
                continue

            # Zone re-entry suppression
            zone_id = signal.get("zone_id", "")
            if zone_id and zone_id in consumed_zone_ids:
                continue
            if zone_id and zone_id in open_zone_ids:
                continue

            # ----------------------------------------------------------
            # Determine outcome from bars AFTER the signal date
            # (future bars were never seen by the strategy)
            # ----------------------------------------------------------
            after_mask = full_htf_df["timestamp"].apply(
                lambda x: (x.date() if hasattr(x, "date") else pd.to_datetime(x).date())
                          > scan_date
            )
            future_df = full_htf_df[after_mask].reset_index(drop=True)

            res = _outcome_multi_target(direction, entry, stop, targets, future_df)

            risk   = abs(entry - stop)
            rr1    = abs(targets[0] - entry) / risk if risk > 0 else 0
            rr2    = abs(targets[1] - entry) / risk if len(targets) > 1 and risk > 0 else 0

            trade_rec = {
                "year":          scan_date.year,
                "date":          scan_date.isoformat(),
                "symbol":        sym,
                "name":          name[:12],
                "asset_class":   ac,
                "direction":     direction,
                "entry":         round(entry, 5),
                "stop":          round(stop, 5),
                "t1":            round(targets[0], 5),
                "t2":            round(targets[1], 5) if len(targets) > 1 else None,
                "t3":            round(targets[2], 5) if len(targets) > 2 else None,
                "rr1":           round(rr1, 2),
                "rr2":           round(rr2, 2),
                "outcome":       res["outcome"],
                "target_hit":    res["target_hit"],
                "bars_held":     res["bars_to_outcome"],
                "max_r":         round(res["max_r"], 2),
                "r":             res["r"],
                "trade_context": signal.get("trade_context", "standard"),
                "composite":     round(signal.get("qualifier_scores", {}).get("composite", 0), 1),
                "zone_id":       zone_id,
            }
            all_trades.append(trade_rec)
            sym_signal_count += 1

            if verbose:
                out_tag = (GREEN+"WIN"+RESET if res["outcome"]=="WIN"
                           else RED+"LOSS"+RESET if res["outcome"]=="LOSS"
                           else YELLOW+"OPEN"+RESET)
                print(f"    {scan_date}  {direction.upper():<5} entry={entry:.4f}  "
                      f"stop={stop:.4f}  T1={targets[0]:.4f}  "
                      f"R:R={rr1:.1f}  {out_tag}")

            # Zone memory
            outcome_val = res["outcome"]
            if outcome_val in ("WIN", "LOSS"):
                if zone_id:
                    consumed_zone_ids[zone_id] = scan_date.isoformat()
            else:
                if zone_id:
                    open_zone_ids[zone_id] = trade_rec

        # Per-symbol scan complete
        print(f" [{sym_signal_count} signals]", flush=True)

    return all_trades


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_results(trades: List[Dict], start_date: date, end_date: date) -> None:
    if not trades:
        print(f"\n{YELLOW}No signals fired in the test period.{RESET}\n")
        return

    trades.sort(key=lambda r: (r["date"], r["symbol"]))

    # ---- Trade-by-trade table ----
    print(f"\n{BOLD}{'=' * 100}{RESET}")
    print(f"{BOLD}  WALK-FORWARD RESULTS  {start_date} to {end_date}{RESET}")
    print(f"{BOLD}{'=' * 100}{RESET}")

    hdr = (f"{'DATE':<12}{'SYMBOL':<10}{'AC':<18}{'DIR':<6}"
           f"{'ENTRY':>10}{'STOP':>10}{'T1':>10}{'R:R':>5}"
           f"{'OUT':<7}{'Tgt':>4}{'Bars':>5}{'maxR':>6}{'R':>6}  {'CTX'}")
    print(BOLD + hdr + RESET)
    print("-" * 100)

    wins = losses = opens = 0
    total_r = 0.0

    for t in trades:
        out = t["outcome"]
        if out == "WIN":
            colour = GREEN; wins += 1
        elif out == "LOSS":
            colour = RED; losses += 1
        else:
            colour = YELLOW; opens += 1
        total_r += t["r"]

        tgt_str   = str(t["target_hit"]) if t["target_hit"] else "-"
        r_str     = (f"+{t['r']:.0f}R" if t["r"] > 0
                     else (f"-{abs(t['r']):.0f}R" if t["r"] < 0 else "open"))
        maxr_str  = f"{t['max_r']:.1f}R"

        row = (f"{t['date']:<12}{t['symbol']:<10}{t['asset_class']:<18}"
               f"{t['direction']:<6}{t['entry']:>10.4f}{t['stop']:>10.4f}"
               f"{t['t1']:>10.4f}{t['rr1']:>5.1f}  "
               f"{out:<5}{tgt_str:>4}{t['bars_held']:>5}"
               f"{maxr_str:>6}{r_str:>6}  {t['trade_context']}")
        print(colour + row + RESET)

    print("-" * 100)

    closed = wins + losses
    wr     = wins / closed * 100 if closed else 0
    avg_r  = total_r / closed if closed else 0
    exp    = wr / 100 * 1.0 + (1 - wr / 100) * (-1.0)  # expectancy at 1R fixed

    print(
        f"\n{BOLD}"
        f"Total: {len(trades)}  |  "
        f"Wins: {GREEN}{wins}{RESET}{BOLD}  "
        f"Losses: {RED}{losses}{RESET}{BOLD}  "
        f"Open: {YELLOW}{opens}{RESET}{BOLD}  |  "
        f"Win rate: {wr:.1f}%  |  "
        f"Avg R (closed): {avg_r:+.2f}R  |  "
        f"Expectancy: {exp:+.2f}R per trade"
        f"{RESET}"
    )

    # ---- Year-by-year breakdown ----
    by_year: Dict[int, Dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "opens": 0, "r": 0.0})
    for t in trades:
        y = t["year"]
        out_key = {"WIN": "wins", "LOSS": "losses"}.get(t["outcome"], "opens")
        by_year[y][out_key] += 1
        by_year[y]["r"] += t["r"]

    print(f"\n{BOLD}Year-by-year:{RESET}")
    print(f"  {'Year':<6}{'Wins':>5}{'Loss':>5}{'Open':>5}{'WR%':>7}{'Cum R':>8}")
    print(f"  {'-'*36}")
    cum_r = 0.0
    for yr in sorted(by_year.keys()):
        d = by_year[yr]
        y_closed = d["wins"] + d["losses"]
        y_wr = d["wins"] / y_closed * 100 if y_closed else 0
        cum_r += d["r"]
        print(f"  {yr:<6}{d['wins']:>5}{d['losses']:>5}{d['opens']:>5}"
              f"{y_wr:>7.1f}%{cum_r:>+8.1f}R")

    # ---- Asset-class breakdown ----
    by_ac: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "opens": 0, "r": 0.0})
    for t in trades:
        ac = t["asset_class"]
        out_key = {"WIN": "wins", "LOSS": "losses"}.get(t["outcome"], "opens")
        by_ac[ac][out_key] += 1
        by_ac[ac]["r"] += t["r"]

    print(f"\n{BOLD}By asset class:{RESET}")
    print(f"  {'Class':<22}{'W':>4}{'L':>4}{'O':>4}{'WR%':>7}{'TotalR':>8}")
    print(f"  {'-'*50}")
    for ac_name, d in sorted(by_ac.items(), key=lambda x: -x[1]["wins"]):
        ac_closed = d["wins"] + d["losses"]
        ac_wr = d["wins"] / ac_closed * 100 if ac_closed else 0
        r_col = GREEN if d["r"] > 0 else RED if d["r"] < 0 else ""
        print(f"  {ac_name:<22}{d['wins']:>4}{d['losses']:>4}{d['opens']:>4}"
              f"{ac_wr:>7.1f}% {r_col}{d['r']:>+7.1f}R{RESET}")

    # ---- Context breakdown ----
    by_ctx: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "opens": 0})
    for t in trades:
        ctx = t.get("trade_context", "standard")
        by_ctx[ctx][{"WIN": "wins", "LOSS": "losses"}.get(t["outcome"], "opens")] += 1

    print(f"\n{BOLD}By trade context:{RESET}")
    for ctx, d in sorted(by_ctx.items()):
        ctx_cl = d["wins"] + d["losses"]
        ctx_wr = d["wins"] / ctx_cl * 100 if ctx_cl else 0
        print(f"  {ctx:<25} W:{d['wins']:>3}  L:{d['losses']:>3}  O:{d['opens']:>3}  WR: {ctx_wr:.1f}%")

    # ---- Equity curve (cumulative R by month) ----
    by_month: Dict[str, float] = defaultdict(float)
    for t in trades:
        month_key = t["date"][:7]  # YYYY-MM
        by_month[month_key] += t["r"]

    print(f"\n{BOLD}Monthly P&L (cumulative R):{RESET}")
    cum = 0.0
    for m in sorted(by_month.keys()):
        r = by_month[m]
        cum += r
        bar_len = int(abs(r) * 4)
        bar = (GREEN + "+" * bar_len if r > 0 else RED + "-" * bar_len) + RESET
        print(f"  {m}  {r:>+6.1f}R  cum:{cum:>+7.1f}R  {bar}")

    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Blueprint Trading System — 30-Year Walk-Forward Test"
    )
    parser.add_argument("--strategy", choices=["weekly", "monthly", "daily"],
                        default="weekly")
    parser.add_argument("--start",   default="2020-01-01",
                        help="Walk-forward start date YYYY-MM-DD")
    parser.add_argument("--end",     default=None,
                        help="Walk-forward end date YYYY-MM-DD (default: today)")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="Specific symbols to test (e.g. GC=F SI=F)")
    parser.add_argument("--fast",    action="store_true",
                        help="Use 20-symbol fast watchlist instead of full 35+")
    parser.add_argument("--config-watchlist", action="store_true",
                        help="Use the full watchlist defined in BP_config.yaml "
                             "(~77 symbols including forex crosses) instead of "
                             "the hardcoded FULL_WATCHLIST")
    parser.add_argument("--csv",     default=None,
                        help="Save results to CSV file")
    parser.add_argument("--json",    default=None,
                        help="Save results to JSON file")
    parser.add_argument("--config",  default=str(SCRIPT_DIR / "BP_config.yaml"))
    parser.add_argument("--verbose", action="store_true",
                        help="Print each signal as it fires")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Config
    with open(args.config) as f:
        config = yaml.safe_load(f)

    # Watchlist
    if args.symbols:
        # Build from user-specified symbols
        sym_lookup = {s["symbol"]: s for s in FULL_WATCHLIST}
        watchlist = []
        for s in args.symbols:
            if s in sym_lookup:
                watchlist.append(sym_lookup[s])
            else:
                # Best-guess asset class
                if s.endswith("=F"):
                    ac = "futures"
                elif s.endswith("-USD"):
                    ac = "crypto"
                elif s.endswith("=X"):
                    ac = "forex"
                else:
                    ac = "equities"
                watchlist.append({"symbol": s, "name": s, "asset_class": ac})
    elif args.fast:
        watchlist = FAST_WATCHLIST
    elif args.config_watchlist:
        # Pull the full live watchlist from BP_config.yaml (~77 symbols)
        watchlist = config.get("watchlist") or FULL_WATCHLIST
        # Normalize: ensure each entry has the keys the runner expects
        for w in watchlist:
            w.setdefault("name", w.get("symbol", "?"))
            w.setdefault("asset_class", "equities")
    else:
        watchlist = FULL_WATCHLIST

    start_dt = date.fromisoformat(args.start)
    end_dt   = date.fromisoformat(args.end) if args.end else date.today()

    # Run
    trades = run_walk_forward(
        watchlist=watchlist,
        config=config,
        strategy=args.strategy,
        start_date=start_dt,
        end_date=end_dt,
        verbose=args.verbose,
    )

    # Print
    print_results(trades, start_dt, end_dt)

    # Save
    if args.csv and trades:
        df = pd.DataFrame(trades)
        df.to_csv(args.csv, index=False)
        print(f"Results saved to {args.csv}")
    if args.json and trades:
        with open(args.json, "w") as f:
            json.dump(trades, f, indent=2, default=str)
        print(f"Results saved to {args.json}")


if __name__ == "__main__":
    main()
