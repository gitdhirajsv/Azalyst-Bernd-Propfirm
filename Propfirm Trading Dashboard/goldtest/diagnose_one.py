"""
Diagnostic deep-dive on a single case.

Prints raw numeric values for every fundamentals component so we can see
exactly what the engine is computing vs what Bernd states verbally.

Usage:
    python diagnose_one.py AAPL 2024-01-02
    python diagnose_one.py NQ=F 2024-01-02
"""

import sys
import yaml
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from BP_data_fetcher import DataFetcher, get_cftc_code
from BP_rules_engine import RulesEngine
from run_goldtest import (
    fetch_historical_snapshot, slice_cot_to_date,
    fetch_valuation_refs_at_date, ASSET_CLASS_BY_SYMBOL, STRATEGY_TIMEFRAMES,
)


def main():
    if len(sys.argv) < 3:
        print("Usage: python diagnose_one.py <SYMBOL> <YYYY-MM-DD> [strategy]", file=sys.stderr)
        sys.exit(1)
    symbol    = sys.argv[1]
    call_date = datetime.strptime(sys.argv[2], "%Y-%m-%d")
    strategy  = sys.argv[3] if len(sys.argv) > 3 else "monthly"

    asset_class = ASSET_CLASS_BY_SYMBOL.get(symbol, "equities")
    tf = STRATEGY_TIMEFRAMES.get(strategy)
    htf, ltf = tf["htf"], tf["ltf"]

    with open(PROJECT_DIR / "BP_config.yaml") as f:
        config = yaml.safe_load(f)

    fetcher = DataFetcher()
    engine  = RulesEngine(config)

    print(f"\n=== Diagnostic: {symbol} @ {call_date.date()}  [{asset_class}, {strategy}] ===\n")

    # 1. OHLCV
    ohlcv = fetch_historical_snapshot(fetcher, symbol, htf, ltf, call_date)
    print(f"OHLCV bars: " + ", ".join(f"{tf}={len(df)}" for tf, df in ohlcv.items()))

    # 2. COT data
    cot_lookup = symbol
    cftc_code  = get_cftc_code(cot_lookup)
    print(f"CFTC code for {symbol}: {repr(cftc_code)}")
    cot_df = slice_cot_to_date(fetcher.fetch_cot_data(cftc_code), call_date)
    print(f"COT rows: {len(cot_df) if cot_df is not None else 0}")

    # 3. Valuation refs
    val_refs = fetch_valuation_refs_at_date(fetcher, asset_class, symbol, htf, call_date)
    print(f"Valuation refs: {list(val_refs.keys())}")

    # 4. Compute each indicator manually so we can see the actual value
    cot_engine, val_engine = engine._indicators_for_class(asset_class, symbol=symbol)
    print(f"\n--- Engine config for asset_class={asset_class} ---")
    print(f"COT lookback weeks: {cot_engine.lookback_weeks}")
    print(f"COT upper extreme:  {cot_engine.upper_extreme}")
    print(f"COT lower extreme:  {cot_engine.lower_extreme}")
    print(f"Valuation length (ROC period): {val_engine.length}")
    print(f"Valuation overvalued threshold:  {val_engine.overvalued}")
    print(f"Valuation undervalued threshold: {val_engine.undervalued}")

    # ---- Valuation ----
    print(f"\n--- VALUATION ---")
    if val_refs and not ohlcv.get(htf, None) is None:
        val_calc = val_engine.calculate(ohlcv[htf], val_refs)
        if not val_calc.empty:
            tail = val_calc.tail(5)
            print("Last 5 valuation rows:")
            print(tail.to_string())
            # Per-reference latest
            latest = val_calc.iloc[-1]
            print(f"\nLatest values:")
            for col in val_calc.columns:
                if col.startswith("valuation_"):
                    val = latest.get(col)
                    print(f"  {col} = {val}")

            # Bias call
            try:
                val_bias = val_engine.get_bias(val_calc)
                print(f"\nValuation bias output: {val_bias}")
            except Exception as e:
                print(f"Valuation bias error: {e}")
        else:
            print("Valuation dataframe is empty!")
    else:
        print("Skipped: missing val_refs or htf data")

    # ---- COT ----
    print(f"\n--- COT ---")
    if cot_df is not None and not cot_df.empty:
        cot_calc = cot_engine.calculate(cot_df)
        if not cot_calc.empty:
            print("Last 5 COT rows:")
            print(cot_calc.tail(5).to_string())
            latest = cot_calc.iloc[-1]
            print(f"\nLatest commercials_index: {latest.get('commercials_index')}")
            print(f"Latest large_specs_index:   {latest.get('large_specs_index')}")
            print(f"Latest small_specs_index:   {latest.get('small_specs_index')}")
            try:
                cot_bias = cot_engine.get_bias(cot_calc, asset_class=asset_class)
                print(f"\nCOT bias output: {cot_bias}")
            except Exception as e:
                print(f"COT bias error: {e}")
        else:
            print("COT calc is empty!")
    else:
        print(f"No COT data for {symbol} (CFTC code = {cftc_code!r}) — vote will be neutral")

    # ---- Seasonality ----
    print(f"\n--- SEASONALITY ---")
    try:
        import pandas as pd
        seasonal_df = fetcher.fetch_ohlcv(
            symbol, interval="1d", period="",
            start=(call_date - timedelta(days=365 * 15)).strftime("%Y-%m-%d"),
            end=call_date.strftime("%Y-%m-%d"),
        )
        if not seasonal_df.empty:
            ts = pd.to_datetime(seasonal_df["timestamp"])
            if hasattr(ts.dt, "tz") and ts.dt.tz is not None:
                ts = ts.dt.tz_localize(None)
            seasonal_df = seasonal_df[ts.values < pd.Timestamp(call_date)].copy()
            multi = engine.seasonality.calculate_multi(seasonal_df, timeframe=strategy if strategy in ('weekly','monthly','daily') else 'weekly')
            print(f"Seasonality lookbacks computed: {list(multi.keys())}")
            current_bin = engine.seasonality.get_current_bin(seasonal_df, strategy if strategy in ('weekly','monthly','daily') else 'weekly')
            print(f"Current bin: {current_bin}")
            for years, df in multi.items():
                if not df.empty:
                    if 'bin' in df.columns:
                        cur = df[df['bin'] == current_bin]
                        if not cur.empty:
                            v = cur.iloc[0].get('seasonal_value', 'n/a')
                            print(f"  {years}y -> seasonal_value at current bin: {v}")
            try:
                seas_bias = engine.seasonality.get_bias_multi(seasonal_df, current_bin, timeframe=strategy if strategy in ('weekly','monthly','daily') else 'weekly')
                print(f"\nSeasonality bias output: {seas_bias}")
            except Exception as e:
                print(f"Seasonality bias error: {e}")
        else:
            print("No seasonality data")
    except Exception as e:
        import traceback
        print(f"Seasonality error: {traceback.format_exc()}")

    # ---- Location (HTF analysis) ----
    print(f"\n--- LOCATION + TREND ---")
    if htf in ohlcv:
        htf_df = ohlcv[htf]
        zones = engine.zone_detector.detect_zones(htf_df, symbol, htf)
        print(f"HTF zones detected: {len(zones)}")
        if zones:
            for i, z in enumerate(zones[:3]):
                print(f"  Zone {i}: {z.get('zone_type')}  prox={z.get('proximal'):.2f}  dist={z.get('distal'):.2f}  score={z.get('composite_score', 0):.1f}")
        ht_bias = engine._analyze_htf(htf_df, zones)
        print(f"\nLocation bias: {ht_bias.get('location')}")
        print(f"Trend bias:    {ht_bias.get('trend')}")
        if 'fib_pct' in ht_bias:
            print(f"Fib pct:       {ht_bias.get('fib_pct')}")

    print(f"\n=== END DIAGNOSTIC ===\n")


if __name__ == "__main__":
    main()
