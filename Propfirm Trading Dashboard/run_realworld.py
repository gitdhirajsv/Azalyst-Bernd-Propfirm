# -*- coding: utf-8 -*-
"""
Real-World Walk-Forward Scanner -- Jan 2026 to Apr 2026
=======================================================
Replays the Blueprint engine at four monthly snapshot dates.
For each snapshot the fetcher is called with end=snapshot_date so the
engine sees only information that would have been available on that date.

Usage:
    cd "Propfirm Trading Dashboard"
    python run_realworld.py                  # weekly strategy (default)
    python run_realworld.py --strategy daily
    python run_realworld.py --verbose        # per-indicator detail
    python run_realworld.py --symbol GC=F   # single symbol only

Output:
    run_realworld_results.json   (machine-readable)
    Console summary table
"""

import sys
import os
import json
import yaml
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from BP_data_fetcher import DataFetcher, get_cftc_code
from BP_rules_engine import RulesEngine

# -- ANSI helpers (ASCII escape sequences only, no unicode box chars) ----------
RESET   = "\033[0m"
BOLD    = "\033[1m"
GREEN   = "\033[92m"
RED     = "\033[91m"
YELLOW  = "\033[93m"
CYAN    = "\033[96m"
DIM     = "\033[90m"
MAGENTA = "\033[95m"

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleMode(
            ctypes.windll.kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(SCRIPT_DIR / "realworld.log",
                                  encoding="utf-8")]
)
logger = logging.getLogger("realworld")

# -- Snapshot dates (last tradeable day of each month) -------------------------
SNAPSHOTS = [
    ("2026-01-30", "January 2026"),
    ("2026-02-27", "February 2026"),
    ("2026-03-31", "March 2026"),
    ("2026-04-30", "April 2026"),
]

# -- Watchlist -----------------------------------------------------------------
WATCHLIST_RAW: List[Dict] = [
    {"symbol": "6E=F",  "name": "EUR/USD",        "asset_class": "forex"},
    {"symbol": "6B=F",  "name": "GBP/USD",        "asset_class": "forex"},
    {"symbol": "6J=F",  "name": "USD/JPY",        "asset_class": "forex"},
    {"symbol": "6A=F",  "name": "AUD/USD",        "asset_class": "forex"},
    {"symbol": "6C=F",  "name": "USD/CAD",        "asset_class": "forex"},
    {"symbol": "6S=F",  "name": "USD/CHF",        "asset_class": "forex"},
    {"symbol": "GC=F",  "name": "Gold",           "asset_class": "precious_metals"},
    {"symbol": "SI=F",  "name": "Silver",         "asset_class": "precious_metals"},
    {"symbol": "CL=F",  "name": "Crude Oil WTI",  "asset_class": "energies"},
    {"symbol": "NG=F",  "name": "Natural Gas",    "asset_class": "energies"},
    {"symbol": "ES=F",  "name": "S&P 500 E-mini", "asset_class": "equity_indices"},
    {"symbol": "NQ=F",  "name": "Nasdaq 100",     "asset_class": "equity_indices"},
    {"symbol": "YM=F",  "name": "Dow Jones",      "asset_class": "equity_indices"},
    {"symbol": "ZB=F",  "name": "30Y Bond",       "asset_class": "interest_rates"},
    {"symbol": "ZN=F",  "name": "10Y Note",       "asset_class": "interest_rates"},
    {"symbol": "ZC=F",  "name": "Corn",           "asset_class": "commodities"},
    {"symbol": "ZW=F",  "name": "Wheat",          "asset_class": "commodities"},
    {"symbol": "ZS=F",  "name": "Soybeans",       "asset_class": "commodities"},
    {"symbol": "KC=F",  "name": "Coffee",         "asset_class": "commodities"},
    {"symbol": "CC=F",  "name": "Cocoa",          "asset_class": "commodities"},
]

# Deduplicate
_seen: set = set()
WATCHLIST = []
for _entry in WATCHLIST_RAW:
    if _entry["symbol"] not in _seen:
        _seen.add(_entry["symbol"])
        WATCHLIST.append(_entry)

# -- Valuation references by asset class ---------------------------------------
VALUATION_REFS = {
    "forex":            ["DX-Y.NYB"],
    "equity_indices":   ["DX-Y.NYB", "ZN=F", "ZB=F"],
    "equities":         ["ZN=F", "ZB=F", "GC=F"],
    "commodities":      ["DX-Y.NYB", "GC=F", "ZB=F"],
    "soft_commodities": ["DX-Y.NYB", "GC=F", "ZB=F"],
    "precious_metals":  ["DX-Y.NYB", "GC=F", "ZB=F"],
    "energies":         ["DX-Y.NYB", "GC=F", "ZB=F"],
    "interest_rates":   ["^TNX"],
    "crypto":           ["DX-Y.NYB"],
}

STRATEGY_TIMEFRAMES = {
    "monthly":  {"htf": "1mo", "ltf": "1wk"},
    "weekly":   {"htf": "1wk", "ltf": "1d"},
    "daily":    {"htf": "1d",  "ltf": "60m"},
    "intraday": {"htf": "60m", "ltf": "15m"},
}


# -- Date-bounded OHLCV fetch --------------------------------------------------
def fetch_bounded_ohlcv(fetcher: DataFetcher, symbol: str, interval: str,
                        snap_date: str, years_back: int = 5):
    """Fetch OHLCV up to snap_date using the fetcher's private _fetch_one."""
    snap_dt  = datetime.strptime(snap_date, "%Y-%m-%d")
    start_dt = snap_dt - timedelta(days=365 * years_back)
    end_dt   = snap_dt + timedelta(days=1)   # inclusive of snap_date

    return fetcher._fetch_one(
        symbol, interval,
        period=None,
        start=start_dt.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
        retries=3,
    )


def filter_cot_to_date(cot_df, snap_date: str):
    """Keep only COT rows on or before snap_date."""
    if cot_df is None or cot_df.empty:
        return cot_df
    import pandas as pd
    return cot_df[cot_df.index <= pd.Timestamp(snap_date)]


# -- Colour helpers ------------------------------------------------------------
def _bias_color(bias: str) -> str:
    if bias == "bullish":
        return GREEN
    if bias == "bearish":
        return RED
    return YELLOW


def _dir_str(direction: str) -> str:
    if direction == "bullish":
        return "LONG "
    if direction == "bearish":
        return "SHORT"
    return "HOLD "


# -- Scan one symbol at one snapshot -------------------------------------------
def scan_symbol_snapshot(sym_info: Dict, fetcher: DataFetcher, engine: RulesEngine,
                         htf: str, ltf: str, strategy: str,
                         snap_date: str, verbose: bool = False) -> Dict:
    sym = sym_info["symbol"]
    ac  = sym_info["asset_class"]

    try:
        htf_years = 10 if htf in ("1mo", "1wk") else 5
        htf_df = fetch_bounded_ohlcv(fetcher, sym, htf, snap_date, years_back=htf_years)
        if htf_df.empty:
            return {"symbol": sym, "snap_date": snap_date,
                    "error": "No HTF data", "bias": "N/A", "has_signal": False}

        ltf_years = 2 if ltf == "1d" else 1
        ltf_df = fetch_bounded_ohlcv(fetcher, sym, ltf, snap_date, years_back=ltf_years)
        if ltf_df.empty:
            return {"symbol": sym, "snap_date": snap_date,
                    "error": "No LTF data", "bias": "N/A", "has_signal": False}

        ohlcv = {htf: htf_df, ltf: ltf_df}

        # COT (filtered to snap date)
        cftc_code = get_cftc_code(sym)
        cot_raw   = fetcher.fetch_cot_data(cftc_code)
        cot_df    = filter_cot_to_date(cot_raw, snap_date)

        # Opposing COT for forex
        opposing_cot_df = None
        if ac == "forex":
            opp_raw = fetcher.fetch_cot_data(get_cftc_code("DX=F"))
            opposing_cot_df = filter_cot_to_date(opp_raw, snap_date)

        # Valuation references (date-bounded)
        ref_syms = VALUATION_REFS.get(ac, ["DX-Y.NYB"])
        val_refs = {}
        for ref_sym in ref_syms:
            ref_df = fetch_bounded_ohlcv(fetcher, ref_sym, htf, snap_date,
                                         years_back=htf_years)
            if not ref_df.empty:
                val_refs[ref_sym] = ref_df

        # Seasonality (full history is fine -- patterns don't use "future" data)
        seasonal_df = fetcher.fetch_seasonality_reference(sym, lookback_years=15)

        # Run the engine
        signal = engine.run_seven_step_process(
            symbol=sym,
            ohlcv_data=ohlcv,
            cot_df=cot_df,
            valuation_refs=val_refs,
            seasonal_df=seasonal_df,
            htf=htf,
            ltf=ltf,
            income_strategy=strategy,
            asset_class=ac,
            opposing_cot_df=opposing_cot_df,
            constituent_dfs=None,
        )

        result = {
            "symbol":      sym,
            "name":        sym_info["name"],
            "asset_class": ac,
            "snap_date":   snap_date,
            "error":       None,
        }

        if signal:
            result.update({
                "bias":         signal.get("bias", "hold"),
                "direction":    signal.get("direction", "hold"),
                "entry":        signal.get("entry"),
                "stop":         signal.get("stop"),
                "target1":      signal.get("target1"),
                "target2":      signal.get("target2"),
                "zone_score":   signal.get("zone_score"),
                "zone_type":    signal.get("zone_type"),
                "trade_context":signal.get("trade_context", "standard"),
                "loc":          signal.get("location"),
                "val":          signal.get("valuation"),
                "cot":          signal.get("cot_bias"),
                "seas":         signal.get("seasonality_bias"),
                "trend":        signal.get("trend"),
                "has_signal":   True,
            })
        else:
            # Pull Stage-1 bias even when no full signal fires
            htf_analysis = getattr(engine, "_last_htf_analysis", {}) or {}
            result.update({
                "bias":         htf_analysis.get("bias", "hold"),
                "direction":    htf_analysis.get("bias", "hold"),
                "loc":          htf_analysis.get("location"),
                "val":          htf_analysis.get("valuation"),
                "cot":          htf_analysis.get("cot_bias"),
                "seas":         htf_analysis.get("seasonality_bias"),
                "trend":        htf_analysis.get("trend"),
                "has_signal":   False,
                "entry":        None,
                "stop":         None,
                "target1":      None,
                "target2":      None,
                "zone_score":   None,
                "zone_type":    None,
                "trade_context":"no_signal",
            })

        return result

    except Exception as exc:
        logger.exception(f"Error scanning {sym} @ {snap_date}: {exc}")
        return {"symbol": sym, "name": sym_info.get("name", sym),
                "asset_class": ac, "snap_date": snap_date,
                "error": str(exc), "bias": "N/A", "has_signal": False}


# -- Pretty-print one snapshot -------------------------------------------------
def print_snapshot_summary(snap_label: str, results: List[Dict], verbose: bool):
    print()
    print(f"{BOLD}{CYAN}{'='*62}{RESET}")
    print(f"{BOLD}{CYAN}  {snap_label}{RESET}")
    print(f"{BOLD}{CYAN}{'='*62}{RESET}")

    sig_count = sum(1 for r in results if r.get("has_signal"))
    print(f"  Full signals: {BOLD}{GREEN}{sig_count}{RESET} / {len(results)}")
    print()

    hdr = (f"  {'Symbol':<10} {'Class':<18} {'Bias':<12} "
           f"{'Signal':<8} {'Zone':<12} {'Score':<7} {'Entry':>10}")
    print(f"{DIM}{hdr}{RESET}")
    print(f"  {'-'*72}")

    for r in results:
        if r.get("bias") == "N/A":
            err = (r.get("error") or "err")[:30]
            print(f"  {r['symbol']:<10} {'ERROR':<18} {RED}{err}{RESET}")
            continue

        bias   = r.get("bias", "hold") or "hold"
        bc     = _bias_color(bias)
        sig_s  = f"{GREEN}FULL{RESET}" if r.get("has_signal") else f"{DIM}bias{RESET}"
        zone_s = (r.get("zone_type") or "--")[:12]
        score_s= f"{r.get('zone_score',0) or 0:.1f}" if r.get("zone_score") else "  --"
        entry_s= f"{r.get('entry',0) or 0:.4f}" if r.get("entry") else "      --"

        print(f"  {r['symbol']:<10} {r.get('asset_class','?'):<18} "
              f"{bc}{bias:<12}{RESET} {sig_s:<8} {zone_s:<12} "
              f"{score_s:<7} {entry_s:>10}")

        if verbose and bias not in ("hold", "N/A", None):
            d = (f"     loc={r.get('loc','?'):<10} val={r.get('val','?'):<10}"
                 f" cot={r.get('cot','?'):<10} seas={r.get('seas','?'):<10}"
                 f" trend={r.get('trend','?')}")
            print(f"{DIM}{d}{RESET}")

    # Full signal detail
    sigs = [r for r in results if r.get("has_signal")]
    if sigs:
        print()
        print(f"  {BOLD}** Full Tradeable Signals:{RESET}")
        for r in sigs:
            bc  = _bias_color(r.get("bias", "hold"))
            dir_= _dir_str(r.get("direction", "hold"))
            ctx = r.get("trade_context", "standard")
            e   = r.get("entry", 0.0) or 0.0
            s   = r.get("stop",  0.0) or 0.0
            t2  = r.get("target2", 0.0) or 0.0
            rr  = abs((t2 - e) / (e - s)) if s and e and abs(e - s) > 1e-9 else 0.0
            print(f"    {bc}{dir_}{RESET}  {r['symbol']:8} "
                  f"[{r.get('zone_type','?'):12}]  "
                  f"E={e:.4f}  S={s:.4f}  T2={t2:.4f}  "
                  f"R:R={rr:.1f}  ({ctx})")


# -- Entry point ---------------------------------------------------------------
def main():
    print()
    print(f"{BOLD}{CYAN}{'='*62}{RESET}")
    print(f"{BOLD}{CYAN}  Blueprint Real-World Walk-Forward Scanner{RESET}")
    print(f"{BOLD}{CYAN}  January to April 2026  |  "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M')}{RESET}")
    print(f"{BOLD}{CYAN}{'='*62}{RESET}")

    # -- CLI args
    strategy   = "weekly"
    verbose    = "--verbose" in sys.argv
    sym_filter = None

    if "--strategy" in sys.argv:
        try:
            i = sys.argv.index("--strategy")
            strategy = sys.argv[i + 1].lower()
        except IndexError:
            pass

    if "--symbol" in sys.argv:
        try:
            i = sys.argv.index("--symbol")
            sym_filter = sys.argv[i + 1].upper()
        except IndexError:
            pass

    if strategy not in STRATEGY_TIMEFRAMES:
        print(f"{RED}Unknown strategy '{strategy}'. "
              f"Valid: {list(STRATEGY_TIMEFRAMES.keys())}{RESET}")
        sys.exit(1)

    tf        = STRATEGY_TIMEFRAMES[strategy]
    htf, ltf  = tf["htf"], tf["ltf"]

    print(f"\n  Strategy : {BOLD}{strategy.upper()}{RESET}  (HTF={htf}, LTF={ltf})")
    print(f"  Verbose  : {verbose}")

    # -- Load config
    config_path = SCRIPT_DIR / "BP_config.yaml"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # -- Filter watchlist
    watchlist = WATCHLIST
    if sym_filter:
        watchlist = [s for s in watchlist if s["symbol"] == sym_filter]
        if not watchlist:
            print(f"{RED}Symbol '{sym_filter}' not in watchlist.{RESET}")
            sys.exit(1)
        print(f"  Symbol filter: {sym_filter}")

    print(f"  Watchlist: {len(watchlist)} symbols")
    print(f"  Snapshots: {[s[0] for s in SNAPSHOTS]}")

    # -- Shared engine (one fetcher per snapshot for cache isolation)
    engine = RulesEngine(config)

    all_results: Dict[str, List[Dict]] = {}

    for snap_date, snap_label in SNAPSHOTS:
        print(f"\n{BOLD}{MAGENTA}  >> Scanning snapshot: "
              f"{snap_label} ({snap_date})...{RESET}")
        fetcher     = DataFetcher()
        snap_results = []

        for i, sym_info in enumerate(watchlist, 1):
            sym = sym_info["symbol"]
            print(f"    [{i:2}/{len(watchlist)}] "
                  f"{sym:10} {sym_info['name'][:22]:<22}", end="", flush=True)

            r    = scan_symbol_snapshot(sym_info, fetcher, engine, htf, ltf,
                                        strategy, snap_date, verbose)
            bias = (r.get("bias") or "?") if r else "ERR"
            has_s= r.get("has_signal", False) if r else False
            bc   = _bias_color(bias)
            sig_mark = f"  {GREEN}** SIGNAL **{RESET}" if has_s else ""
            print(f"  -> {bc}{bias}{RESET}{sig_mark}")

            if r:
                snap_results.append(r)

        all_results[snap_date] = snap_results
        print_snapshot_summary(snap_label, snap_results, verbose)

    # -- Overall summary
    print()
    print(f"{BOLD}{CYAN}{'='*62}{RESET}")
    print(f"{BOLD}{CYAN}  WALK-FORWARD SUMMARY  (Jan to Apr 2026){RESET}")
    print(f"{BOLD}{CYAN}{'='*62}{RESET}")
    print()

    total_signals  = 0
    bias_counts: Dict[str, int] = {}
    signal_log: List[Dict]      = []

    for snap_date, results in all_results.items():
        snap_label = next((sl for sd, sl in SNAPSHOTS if sd == snap_date), snap_date)
        for r in results:
            b = (r.get("bias") or "hold")
            bias_counts[b] = bias_counts.get(b, 0) + 1
        sigs = [r for r in results if r.get("has_signal")]
        total_signals += len(sigs)
        for r in sigs:
            signal_log.append({"date": snap_date, "label": snap_label, **r})

    print(f"  Total full-signal fires : {BOLD}{GREEN}{total_signals}{RESET}")
    print(f"  Bias distribution (all snapshots x symbols):")
    for bias_key, count in sorted(bias_counts.items()):
        bc = _bias_color(bias_key)
        print(f"    {bc}{bias_key:<12}{RESET}: {count}")

    if signal_log:
        print()
        print(f"  {BOLD}All Full Signals Generated:{RESET}")
        for s in signal_log:
            bc  = _bias_color(s.get("bias", "hold"))
            dir_= _dir_str(s.get("direction", "hold"))
            e   = s.get("entry",  0.0) or 0.0
            st  = s.get("stop",   0.0) or 0.0
            t2  = s.get("target2",0.0) or 0.0
            rr  = abs((t2 - e) / (e - st)) if st and e and abs(e - st) > 1e-9 else 0.0
            print(f"    {s['label']:16}  {bc}{dir_}{RESET}  "
                  f"{s['symbol']:8} [{s.get('zone_type','?'):12}]  "
                  f"E={e:.4f}  S={st:.4f}  T2={t2:.4f}  R:R={rr:.1f}")
    else:
        print()
        print(f"  {YELLOW}No full trade signals fired across any snapshot.{RESET}")
        print(f"  {DIM}This is normal -- the system is conservative by design.{RESET}")
        print(f"  {DIM}Stage-1 bias (directional brain) shown per snapshot above.{RESET}")

    # -- By-asset-class Stage-1 breakdown
    print()
    print(f"  {BOLD}Stage-1 Bias by Asset Class (all snapshots):{RESET}")
    class_totals: Dict[str, Dict] = {}
    for results in all_results.values():
        for r in results:
            ac = r.get("asset_class", "unknown")
            if ac not in class_totals:
                class_totals[ac] = {"bullish": 0, "bearish": 0, "hold": 0, "N/A": 0}
            b = (r.get("bias") or "hold")
            class_totals[ac][b] = class_totals[ac].get(b, 0) + 1

    for ac, counts in sorted(class_totals.items()):
        bull = counts.get("bullish", 0)
        bear = counts.get("bearish", 0)
        hold = counts.get("hold", 0)
        total= bull + bear + hold + counts.get("N/A", 0)
        print(f"    {ac:<20}: {GREEN}{bull}B{RESET} / "
              f"{RED}{bear}S{RESET} / {YELLOW}{hold}H{RESET}  "
              f"(of {total})")

    # -- Save JSON
    out_path = SCRIPT_DIR / "run_realworld_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated":     datetime.now().isoformat(),
            "strategy":      strategy,
            "htf":           htf,
            "ltf":           ltf,
            "total_signals": total_signals,
            "bias_counts":   bias_counts,
            "signal_log":    signal_log,
            "snapshots":     {k: v for k, v in all_results.items()},
        }, f, indent=2, default=str)

    print()
    print(f"  {DIM}Full results --> {out_path.name}{RESET}")
    print()


if __name__ == "__main__":
    main()
