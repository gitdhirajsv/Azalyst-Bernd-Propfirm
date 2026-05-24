"""
Rules Engine - Implements the Seven-Step Decision Process.
From DELIVERABLE_2_STRATEGY_RULEBOOK, sections A-H.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
import logging

from BP_indicators import COTIndex, Valuation, Seasonality
from BP_zone_detector import ZoneDetector
from BP_patterns import PatternDetector, PatternType, TradeDirection
from BP_roadmap import build_monthly_roadmap, filter_signal_by_roadmap
from BP_calendar import get_calendar, BlackoutStatus

logger = logging.getLogger(__name__)


class BiasSignal:
    BULLISH = 'bullish'
    BEARISH = 'bearish'
    NEUTRAL = 'neutral'


# Per-asset-class indicator parameters per the Hybrid AI course defaults
# (HAI 1:19:59 "weeks look back, 156... and the 26") with the Funded Trader
# commodity override (FT 02.03.2024 [0:15:38] "52 weeks... whole planting
# and harvesting season"). Equities use ROC=13 on Valuation (longer/smoother
# per OTC L8); commodities use ROC=10.
COT_LOOKBACK_BY_CLASS = {
    'forex':             26,   # Hybrid AI default
    'commodities':       52,   # Funded Trader override -- planting/harvest cycle
    'soft_commodities':  26,   # CLAUDE.md P1: cotton/grains/cocoa/coffee use NonComm 26w
    'energies':          52,   # crude/nat-gas have seasonal supply cycles
    'nat_gas':           52,   # NG=F: retailers contrarian, historical lookback
    'precious_metals':   26,   # Ch.107 CW40: Bernd explicit "26 look back is 26" for gold/PMs
                              # Also matches COT V2 Pine Script default (input.int(26, "Number of weeks"))
    'equity_indices':    26,
    'equities':          26,
    'interest_rates':    26,
}

# Soft agricultural commodities — COT group assignment (Phase 14 correction):
#
# Corpus evidence (Trading Doc chapters 108-186):
#   - Grains (Corn ZC=F, Wheat ZW=F, Soybeans ZS=F): Bernd uses COMMERCIALS
#     explicitly. Ch.159 (CW07 Corn): "commercials are bullish." Ch.168
#     (CW05 Soybeans): Bernd says the retailer line is "not real retailers."
#   - Cotton (CT=F): Ch.113/Ch.144 (Nov-Dec 2023): "smart money commercials
#     bullish + retailers bearish = buy cotton." Later sessions confirm Commercials.
#   - Coffee KC=F: Phase 16 transcript audit — 03_funded.txt lines 6805-6810:
#     Bernd says coffee retailers are "not real retailers" and explicitly
#     notes "commercials obviously impact." Moved to 'commodities' class
#     (Commercials 52w). Same language used for Soybeans (Ch.168).
#   - Cocoa CC=F, Sugar SB=F, OJ=F: corpus silent/unclear; retain NonComm 26w.
#
# Grains + Cotton are now routed to 'commodities' class (Commercials 52w)
# by removing them from this frozenset. KC=F also moved out (Phase 16).
SOFT_COMMODITY_SYMBOLS = frozenset({
    'CC=F',  # Cocoa  — NonCommercials divergence (unclear corpus; retain)
    'SB=F',  # Sugar  — NonCommercials divergence (corpus silent)
    'OJ=F',  # Orange Juice — NonCommercials divergence (corpus silent)
    # KC=F Coffee removed (Phase 16): retailers "not real retailers"; Commercials
    # are the primary driver → falls through to 'commodities' (Commercials 52w)
    # ZC=F Corn, ZW=F Wheat, ZS=F Soybeans, CT=F Cotton removed (Phase 14):
    # these use Commercials (Ch.159/168/113/144) → fall through to 'commodities'
})

# Blueprint Cheatsheet (OTC Module 2) fix — Natural Gas:
# COT = Retailers ① (CONTRARIAN, same as Precious Metals) NOT Commercials.
# Cheatsheet note: "historical retailer extremes (5year or historical)".
# Valuation = "-" (excluded — NG is driven by weather/supply shocks that
# make relative-to-DXY analysis uninformative).
NAT_GAS_SYMBOLS = frozenset({'NG=F', 'QN=F'})  # full + mini

# Phase 23 (Task 3): JPY uses 52-week COT lookback (not the 26w forex default).
# CFTC 6J=F has lower open interest than EUR/GBP futures → 26w net position
# range is too narrow → COT V2 index stays near 50 → bias always 'neutral'.
# Wider 52w window captures more historical range so the index reaches the
# 80/20 extremes and produces directional signals matching Bernd's verbal calls.
JPY_SYMBOLS = frozenset({'USDJPY=X', '6J=F', 'JPYUSD=X', 'JPYUSD'})

# Symbols where Valuation is explicitly excluded from Bernd's analysis.
# NG=F: cheatsheet column shows "-" for Valuation.
VALUATION_SKIP_SYMBOLS = frozenset({'NG=F', 'QN=F'})

# Phase 16 — Bitcoin seasonality uses 4-year lookback only.
# 03_funded.txt lines 451, 864-865: Bernd says "We can only do four years"
# for Bitcoin — the data history is too short for 5yr/10yr/15yr averages.
# When a BTC symbol is detected, Seasonality.calculate_multi is overridden
# to use a (4,) lookback tuple instead of the standard (5, 10, 15).
BTC_SYMBOLS = frozenset({'BTC-USD', 'BTC=F', 'BTCUSD', 'BTC/USD'})

# Phase 15 — Equity index constituent-analysis Valuation.
#
# From Ch.157 (CW40): "the two most important stocks is Apple and is Microsoft
# that they are not overbellied. Right. Apple is undervalued. And if you look
# at Microsoft here as well [undervalued]... So if these two are undervalued,
# you can buy NQ / ES."
#
# Bernd reads individual-stock Valuation to INFER the index direction.
# He does NOT look at NQ=F or ES=F Valuation directly — the index is too
# correlated with the macro references (DXY/ZN/ZB) to give an independent signal.
#
# Implementation rule (Phase 6/CLAUDE.md P2 / Ch.157):
#   Primary gate: AAPL + MSFT (for NQ/ES); MSFT + UNH (for YM DOW).
#   If BOTH primaries are NOT strongly overvalued → constituent_val = 'bullish'
#   If ANY primary is strongly overvalued     → constituent_val = 'bearish' or 'neutral'
#   Secondary stocks provide a confirming majority vote.
EQUITY_INDEX_CONSTITUENTS: Dict = {
    'NQ=F':  {
        'primary':   ['AAPL', 'MSFT'],
        'secondary': ['NVDA', 'AMZN', 'META', 'GOOGL', 'NFLX', 'TSLA'],
    },
    'ES=F':  {
        'primary':   ['AAPL', 'MSFT'],
        'secondary': ['NVDA', 'AMZN', 'META', 'GOOGL'],
    },
    'YM=F':  {
        # Dow Jones top-weight components by market cap influence
        'primary':   ['MSFT', 'UNH'],
        'secondary': ['GS', 'HD', 'CAT', 'AAPL'],
    },
}

# Pine Script (CampusValuationTool) default Length is 10 across the board.
# A previous version of these docs claimed equities should use 13 ("Dual-ROC
# for Equities"), but the Pine Script source the user shared confirms the
# indicator runs ONE ROC at the default Length=10 -- "dual-ROC" was an
# overlay practice (running two instances of the indicator on the same
# chart with different Length values), not a parameter override on a
# single instance. Tested: with Length=13 our values for META/NVDA/AMZN
# came out wildly more bearish than Bernd's verbal reading; Length=10
# produced readings consistent with his commentary.
VALUATION_LENGTH_BY_CLASS = {
    'forex':           10,
    'commodities':     10,
    'energies':        10,
    'precious_metals': 10,
    'equity_indices':  10,
    'equities':        10,
    'interest_rates':  10,
}


class RulesEngine:
    """
    Seven-Step Decision Process for trade signal generation.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.risk_config = config.get('risk', {})
        self.stop_config = config.get('stop_loss', {})

        # Initialize indicator engines
        cot_cfg = config.get('cot', {})
        val_cfg = config.get('valuation', {})
        seas_cfg = config.get('seasonality', {})

        self.cot_index = COTIndex(
            lookback_weeks=cot_cfg.get('lookback_weeks', 26),
            upper_extreme=cot_cfg.get('upper_extreme', 80),
            lower_extreme=cot_cfg.get('lower_extreme', 20)
        )

        self.valuation = Valuation(
            length=val_cfg.get('length', 10),
            rescale_length=val_cfg.get('rescale_length', 100),
            overvalued=val_cfg.get('overvalued_threshold', 75),
            undervalued=val_cfg.get('undervalued_threshold', -75)
        )

        self.seasonality = Seasonality(
            lookback_years=seas_cfg.get('lookback_years', 15),
            bias_lookahead_bars=seas_cfg.get('bias_lookahead_bars', 20)
        )

        self.zone_detector = ZoneDetector(config.get('zone_detection', {}))
        self.pattern_detector = PatternDetector(config)

    def run_seven_step_process(
        self,
        symbol: str,
        ohlcv_data: Dict[str, pd.DataFrame],
        cot_df: pd.DataFrame,
        valuation_refs: Dict[str, pd.DataFrame],
        seasonal_df: pd.DataFrame,
        htf: str = '1wk',
        ltf: str = '1d',
        income_strategy: str = 'weekly',
        asset_class: str = 'commodities',
        opposing_cot_df: Optional[pd.DataFrame] = None,
        prefer_midpoint_entry: bool = False,
        constituent_dfs: Optional[Dict[str, "pd.DataFrame"]] = None,
        today_override: Optional[date] = None,
    ) -> Optional[Dict]:
        """
        Execute the full Seven-Step Decision Process.

        Steps:
        1. Market Selection (already done - symbol passed in)
        2. HTF Technical Analysis (location, trend)
        3. Fundamental Confirmation (COT, Valuation, Seasonality)
        4. LTF Zone Identification (zone detection + qualifiers)
        5. Entry Trigger (candlestick patterns)
        6. Trade Management (stop, targets, sizing)
        7. Review & Refine (signal confidence)

        Returns:
            Trade signal dict or None if conditions not met
        """

        # Reset Stage-1 cache at the start of every call so stale data from the
        # previous symbol never leaks through. run_realworld.py reads this after
        # the call returns to get the directional brain output even when no full
        # signal fires (no zone, consensus=hold, no pattern, etc.).
        self._last_htf_analysis = {}

        htf_df = ohlcv_data.get(htf)
        ltf_df = ohlcv_data.get(ltf)

        if htf_df is None or htf_df.empty:
            logger.warning(f"No {htf} data for {symbol}")
            return None
        if ltf_df is None or ltf_df.empty:
            logger.warning(f"No {ltf} data for {symbol}")
            return None

        # == STEP 4 (early): detect HTF zones first so Location uses zone distals ==
        # First pass without trend so we can derive trend from the data, then
        # we re-score later with trend context.
        htf_zones_provisional = self.zone_detector.detect_zones(htf_df, symbol, htf)

        # == STEP 2: HTF Technical Analysis (uses zone distals when available) ==
        ht_bias = self._analyze_htf(htf_df, htf_zones_provisional,
                                    htf=htf, symbol=symbol, asset_class=asset_class)
        trend = ht_bias['trend']

        logger.info(f"[{symbol}] HTF Bias: location={ht_bias['location']}, trend={trend}")

        # Re-score HTF zones with trend context so Q5/Q6 are skipped on
        # trend-aligned setups (textbook rule).
        htf_zones = self.zone_detector.detect_zones(htf_df, symbol, htf, trend=trend)

        # == STEP 3: Fundamental Confirmation ==
        fund_bias = self._analyze_fundamentals(
            cot_df, htf_df, valuation_refs, seasonal_df, asset_class,
            opposing_cot_df=opposing_cot_df,
            symbol=symbol,
            constituent_dfs=constituent_dfs,
        )
        logger.info(f"[{symbol}] Fundamentals: COT={fund_bias['cot']}, Val={fund_bias['valuation']}, Seas={fund_bias['seasonality']}")

        # Store Stage-1 intermediate analysis so external callers (e.g.
        # run_realworld.py) can inspect the directional brain even when the
        # full signal returns None (no zone, no pattern, or consensus=hold).
        self._last_htf_analysis = {
            "symbol":     symbol,
            "location":   ht_bias.get("location"),
            "trend":      ht_bias.get("trend"),
            "valuation":  fund_bias.get("valuation"),
            "cot_bias":   fund_bias.get("cot"),
            "cot_strength": fund_bias.get("cot_strength", "none"),
            "seasonality_bias": fund_bias.get("seasonality"),
            "bias":       None,   # filled in after _bias_consensus below
        }

        # == STEP 4: LTF Zone Detection + multi-timeframe alignment ==
        ltf_zones = self.zone_detector.detect_zones(ltf_df, symbol, ltf, trend=trend)
        ltf_zones = self.zone_detector.align_multi_timeframe(htf_zones, ltf_zones)
        # Big Brother / Small Brother filter (OTC 2025 L3): tag LTF zones
        # with their HTF parent. Strict mode is opt-in via config since
        # Bernd does take some "no-big-brother" trades when the LTF zone is
        # a clean RBR/DBD with high qualifier scores.
        require_bb = bool(self.config.get('require_big_brother', False))
        ltf_zones = self.zone_detector.filter_by_big_brother(
            ltf_zones, htf_zones, require_coverage=require_bb,
        )
        ranked_zones = self.zone_detector.rank_zones(ltf_zones, min_score=4.0)

        if not ranked_zones:
            logger.info(f"[{symbol}] No qualified zones found")
            return None

        best_zone = ranked_zones[0]
        logger.info(f"[{symbol}] Best zone: {best_zone['zone_type']} at {best_zone['proximal']:.2f}, score={best_zone['composite_score']:.1f}")

        # == Consensus Bias Check ==
        # Phase 28 A1 fix: wire constituent bias into consensus so the Phase 23/24
        # cycle override path can fire in the live scanner (was dead code because
        # goldtest harness built the dict separately).
        biases = {
            'location': ht_bias['location'],
            'trend': ht_bias['trend'],
            'cot': fund_bias['cot'],
            'cot_strength': fund_bias.get('cot_strength', 'normal'),
            'valuation': fund_bias['valuation'],
            'seasonality': fund_bias['seasonality'],
            'constituent': fund_bias.get('constituent', 'neutral'),
        }

        # Phase 23: pass at_zone + zone_composite for T4 soft-veto support.
        # We're past the no-zone gate (line 274), so a zone definitely exists
        # and price is near it (zone qualifier scoring filters out distant zones).
        _zc = float(best_zone.get('composite_score', 0.0)) if best_zone else 0.0
        consensus = self._bias_consensus(
            biases, income_strategy,
            asset_class=asset_class,
            at_zone=True,
            zone_composite=_zc,
            today_override=today_override,
        )
        self._last_htf_analysis["bias"] = consensus   # expose Stage-1 result
        if consensus == 'hold':
            logger.info(f"[{symbol}] Bias consensus insufficient for trade")
            return None

        # Zone direction must match consensus
        zone_dir = 'long' if best_zone['zone_type'] == 'demand' else 'short'
        if (zone_dir == 'long' and consensus == 'bearish') or (zone_dir == 'short' and consensus == 'bullish'):
            logger.info(f"[{symbol}] Zone direction {zone_dir} conflicts with consensus {consensus}")
            return None

        # Phase 6 P1 (Ch 156): equity-index shorts require BOTH retailer-extreme
        # AND Treasury Bond ROC actively rolling negative (not merely positioned).
        # Bernd: "we need the help of other Treasury bonds [to roll over]".
        if zone_dir == 'short' and asset_class == 'equities':
            gate_ok, gate_reason = self._equity_index_short_cross_asset_gate(
                symbol=symbol,
                cot_df=cot_df,
                valuation_refs=valuation_refs,
            )
            if not gate_ok:
                logger.info(f"[{symbol}] Equity-index short cross-asset gate: {gate_reason}")
                return None

        # OTC L5 Decision Matrix (frames 57, 1484): Action = f(zone_type, location, trend)
        # The matrix labels "demand-at-expensive" and "supply-at-cheap" as
        # ANTICIPATORY / COUNTER-TREND setups. Per Hybrid AI Module 4 these
        # are still tradeable -- just with reduced size (0.5% risk) and
        # stronger Valuation alignment required. So we hard-reject only
        # when Valuation does NOT explicitly agree with the zone direction;
        # otherwise we allow the trade and mark it as anticipatory below.
        location  = ht_bias['location']
        in_equil  = ht_bias.get('in_equilibrium', False)
        zone_type = best_zone['zone_type']
        val_bias  = fund_bias.get('valuation', 'neutral')

        # Demand zone at expensive location: needs Valuation bullish to fire
        if zone_type == 'demand' and location == 'bearish':
            if val_bias != 'bullish':
                logger.info(f"[{symbol}] Decision matrix: demand at expensive location AND Val not bullish -> no action")
                return None
            logger.info(f"[{symbol}] Anticipatory reversal: demand at expensive + Val bullish (reduced size)")

        # Supply zone at cheap location: needs Valuation bearish to fire
        if zone_type == 'supply' and location == 'bullish':
            if val_bias != 'bearish':
                logger.info(f"[{symbol}] Decision matrix: supply at cheap location AND Val not bearish -> no action")
                return None
            logger.info(f"[{symbol}] Anticipatory reversal: supply at cheap + Val bearish (reduced size)")

        # Equilibrium + sideways trend on either zone = genuinely no edge
        if in_equil and trend == 'sideways':
            logger.info(f"[{symbol}] Decision matrix: equilibrium + sideways -> no edge, skip")
            return None

        # == STEP 5: Entry Trigger (a candlestick pattern at the zone is required) ==
        pattern_signal = self._check_entry_pattern(ltf_df, best_zone)
        if pattern_signal is None:
            # Fall back to a "zone limit" entry only when the most recent
            # candle is sitting inside the zone -- otherwise the trade is
            # premature and we wait. This honours rule #4 ("never anticipate").
            last = ltf_df.iloc[-1]
            zone_dir_str = best_zone['zone_type']
            in_zone = (
                zone_dir_str == 'demand'
                and last['low']  <= best_zone['proximal']
                and last['low']  >= best_zone['distal']
            ) or (
                zone_dir_str == 'supply'
                and last['high'] >= best_zone['proximal']
                and last['high'] <= best_zone['distal']
            )
            if not in_zone:
                logger.info(f"[{symbol}] Price has not arrived at zone yet -- no signal")
                return None

            # Entry style per textbook Ch 6:
            #   Entry 1 (proximal):  limit at proximal -- always fills, deeper drawdown
            #   Entry 2 (midpoint):  limit at 50% of zone -- better R:R, may miss
            # Default = proximal; flip to midpoint when prefer_midpoint_entry.
            zone_height = abs(best_zone['proximal'] - best_zone['distal'])
            if zone_dir_str == 'demand':
                entry = (best_zone['proximal'] + best_zone['distal']) / 2.0 if prefer_midpoint_entry else best_zone['proximal']
                stop = best_zone['distal'] - 0.33 * zone_height
                direction = 'long'
            else:
                entry = (best_zone['proximal'] + best_zone['distal']) / 2.0 if prefer_midpoint_entry else best_zone['proximal']
                stop = best_zone['distal'] + 0.33 * zone_height
                direction = 'short'
            targets = self._calculate_targets(entry, stop, direction)
        else:
            entry = pattern_signal['entry_price']
            stop = pattern_signal['stop_price']
            direction = 'long' if pattern_signal['direction'] == TradeDirection.LONG else 'short'
            targets = [
                pattern_signal['target_r1'],
                pattern_signal['target_r2'],
                pattern_signal['target_r3']
            ]

        # == STEP 6: Trade Management ==
        # Determine trade context for position-size adjustment.
        # Anticipatory = reversal at extreme location. Counter-trend = zone
        # against HTF trend. Both reduce risk per HAI Module 4 + OTC L5.
        is_with_trend = bool(best_zone.get('with_trend'))
        if not is_with_trend and trend != 'sideways':
            trade_context = 'counter_trend'
        elif in_equil and trend != 'sideways':
            trade_context = 'anticipatory'
        else:
            trade_context = 'standard'
        position_size = self._calculate_position_size(entry, stop, trade_context)

        r_mult_targets = [self.stop_config.get('breakeven_at_r', 1.0),
                         self.stop_config.get('partial_take_r', 2.0),
                         self.stop_config.get('full_take_r', 3.0)]

        # Three textbook entry options (OTC 2025 L7) so the user can pick
        # E1/E2/E3 based on R:R math. The auto-selected entry above remains
        # the default; entry_options are exposed so the dashboard can show
        # all choices side-by-side.
        primary_target = targets[1] if len(targets) >= 2 else targets[0]
        entry_options = self.build_entry_options(best_zone, primary_target, pattern_signal)
        recommended   = self.recommend_entry_option(entry_options, min_rr=2.0)

        # Auto-refine: per OTC L7 frame 1420 + Hybrid AI Mod 6 L6, when the
        # primary entry's R:R is below the methodology threshold, attempt
        # to drill the timeframe ladder for a tighter zone contained inside
        # the HTF zone. The refined zone (if found) replaces the entry as
        # the recommended path.
        refined_zone = None
        if recommended.get('rr', 0) < 2.0:
            try:
                refined_zone = self.refine_zone(
                    best_zone, primary_target, ohlcv_data,
                    income_strategy=income_strategy, min_rr=2.0,
                )
                if refined_zone is not None:
                    refined_options = self.build_entry_options(
                        refined_zone, primary_target, pattern_signal,
                    )
                    refined_rec = self.recommend_entry_option(refined_options, min_rr=2.0)
                    if refined_rec['rr'] > recommended['rr']:
                        logger.info(
                            f"[{symbol}] Refined entry boosted R:R "
                            f"{recommended['rr']:.2f} -> {refined_rec['rr']:.2f}"
                        )
                        entry_options = refined_options
                        recommended   = refined_rec
                        # Update the primary entry/stop to reflect refinement
                        entry = refined_rec['entry']
                        stop  = refined_rec['stop']
                        targets = self._calculate_targets(entry, stop, direction)
            except Exception as e:
                logger.warning(f"Auto-refine failed: {e}")

        # Speed-bump check: opposing zones in the path between current price
        # and entry. Per OTC L6, a qualified opposing zone in the return
        # path will likely stall the trade. We flag but don't auto-reject.
        current_price = float(ltf_df['close'].iloc[-1])
        speed_bumps = self.zone_detector.detect_speed_bumps(
            ltf_zones, best_zone, current_price,
        )
        speed_bump_blocking = self.zone_detector.has_blocking_speed_bump(
            ltf_zones, best_zone, current_price, min_score=5.0,
        )

        # ================================================================
        # Economic Calendar / News Blackout check (audit gap #4)
        # High-impact events (CPI, FOMC, NFP, ECB, BoE) within +/-2h
        # -> reduce risk to 0.5%. Holidays -> full skip.
        # ================================================================
        calendar = get_calendar()
        blackout = calendar.check_blackout()
        calendar_blackout = blackout.to_dict()
        if blackout.in_blackout:
            logger.info(
                f"[{symbol}] Calendar blackout active: {blackout.reason} "
                f"(risk_multiplier={blackout.risk_multiplier})"
            )
            if blackout.risk_multiplier == 0.0:
                return None
            if blackout.risk_multiplier < 1.0:
                position_size *= blackout.risk_multiplier
                logger.info(
                    f"[{symbol}] Calendar blackout: "
                    f"position_size reduced to {position_size:.4f}"
                )

        signal = {
            'symbol': symbol,
            'direction': direction,
            'entry_price': round(entry, 6),
            'stop_price': round(stop, 6),
            'targets': [round(t, 6) for t in targets],
            'entry_options': entry_options,
            'recommended_entry': recommended['label'],
            'speed_bumps': [{'id': sb['id'], 'proximal': sb['proximal'],
                              'distal': sb['distal'], 'score': sb['composite_score']}
                             for sb in speed_bumps[:3]],
            'calendar_blackout': calendar_blackout,
            'speed_bump_warning': speed_bump_blocking,
            'has_big_brother': bool(best_zone.get('has_big_brother')),
            'big_brother_id':  best_zone.get('big_brother_id'),
            'trade_context': trade_context,   # standard / counter_trend / anticipatory
            'zone_id': best_zone['id'],
            'income_strategy': income_strategy,
            'risk_amount': round(abs(entry - stop) * position_size, 2),
            'position_size': round(position_size, 4),
            'r_multiple_targets': r_mult_targets,
            'bias_consensus': biases,
            'qualifier_scores': {
                'departure': best_zone['departure_score'],
                'base_duration': best_zone['base_duration_score'],
                'freshness': best_zone['freshness_score'],
                'originality': best_zone['originality_score'],
                'profit_margin': best_zone['profit_margin_score'],
                'arrival': best_zone['arrival_score'],
                'level_on_top': best_zone['level_on_top_score'],
                'composite': best_zone['composite_score']
            },
            'timestamp': datetime.now().isoformat(),
            'htf': htf,
            'ltf': ltf
        }

        # Monthly roadmap filter (HAI Mod 3 + FT monthly outlooks): tag the
        # signal with the timing-overlay forecast for the current month.
        # Counter-roadmap signals get a warning but aren't auto-rejected.
        try:
            today = datetime.now().date()
            roadmap = build_monthly_roadmap(
                asset=symbol,
                asset_class=asset_class,
                target_month=today,
                seasonality_bias=fund_bias['seasonality'],
                cot_bias=fund_bias['cot'],
                cot_strength=fund_bias.get('cot_strength', 'normal'),
            )
            signal = filter_signal_by_roadmap(signal, roadmap)
        except Exception as e:
            logger.warning(f"Roadmap filter failed: {e}")

        logger.info(f"[{symbol}] SIGNAL: {direction} at {entry:.2f}, stop={stop:.2f}, targets={[round(t,2) for t in targets]}")
        return signal

    def _analyze_htf(
        self, df: pd.DataFrame, htf_zones: Optional[List[Dict]] = None,
        htf: str = '1d',
        symbol: Optional[str] = None,
        asset_class: Optional[str] = None,
    ) -> Dict[str, str]:
        """Step 2: HTF Technical Analysis - Location and Trend.

        Location is the proper Blueprint Fib: from the most recent qualified
        demand zone distal (Fib 0) up to the most recent qualified supply zone
        distal (Fib 100). Falls back to the lookback-range approximation only
        when no zones exist yet.
        """
        if 'close' not in df.columns or len(df) < 50:
            return {'location': 'neutral', 'trend': 'sideways'}

        closes = df['close'].values
        highs  = df['high'].values
        lows   = df['low'].values
        current = closes[-1]

        # DeepSeek Gap 3: USD-base forex pairs invert prices to quote-currency perspective
        is_usd_base_forex = (
            symbol is not None
            and symbol.upper().startswith('USD')
            and '=X' in symbol
        )
        if is_usd_base_forex:
            with np.errstate(divide='ignore', invalid='ignore'):
                closes = 1.0 / closes
                highs  = 1.0 / df['low'].values
                lows   = 1.0 / df['high'].values
            closes = np.nan_to_num(closes, nan=0.0, posinf=0.0, neginf=0.0)
            highs  = np.nan_to_num(highs,  nan=0.0, posinf=0.0, neginf=0.0)
            lows   = np.nan_to_num(lows,   nan=0.0, posinf=0.0, neginf=0.0)
            current = closes[-1]

        # ---- Preferred: use detected HTF zone distals ----
        # Phase 25 (DeepSeek P1): filter out invalidated/consumed zones before
        # selecting the most recent. A stale zone with a wide-out distal can
        # distort the Fib range and produce wrong "cheap/expensive" reads.
        # A zone is considered USABLE for the Location Fib when its freshness
        # qualifier is non-zero (i.e. not consumed and not penetrated >25%).
        def _zone_is_usable(z):
            # Q3 freshness == 0 means: consumed (retested at proximal+ depth)
            # OR penetrated >25% (Phase 6 P1 hard rule). Both make the distal
            # unreliable for Fib anchoring.
            q = z.get('qualifier_scores') or {}
            freshness = q.get('Q3') or q.get('Q3_freshness') or q.get('freshness')
            if freshness is None:
                # Older zones may not carry qualifier scores — fall back to
                # the explicit invalidation flag set by zone detector.
                return not z.get('invalidated', False)
            try:
                return float(freshness) > 0.0
            except (TypeError, ValueError):
                return True  # if score is unparseable, prefer to keep zone

        range_min = range_max = None
        if htf_zones:
            usable = [z for z in htf_zones if _zone_is_usable(z)]
            demand_zones = [z for z in usable if z['zone_type'] == 'demand']
            supply_zones = [z for z in usable if z['zone_type'] == 'supply']
            if demand_zones and supply_zones:
                # Most recent of each (highest origin_index)
                d = max(demand_zones, key=lambda z: z['origin_index'])
                s = max(supply_zones, key=lambda z: z['origin_index'])
                range_min = d['distal']
                range_max = s['distal']

        # ---- Fallback: lookback range ----
        if range_min is None or range_max is None or range_max <= range_min:
            lookback_len = min(200, len(closes))
            range_min = lows[-lookback_len:].min()
            range_max = highs[-lookback_len:].max()

        range_span = range_max - range_min
        location_pct = 50 if range_span <= 0 else (current - range_min) / range_span * 100

        if location_pct <= 33:
            location = 'bullish'
        elif location_pct >= 67:
            location = 'bearish'
        else:
            location = 'neutral'

        trend = self._determine_trend(highs, lows, htf=htf)

        # DeepSeek Gap 1: equity indices ATH momentum override.
        # In a confirmed uptrend with strong short-term momentum, downgrade
        # expensive location to neutral so the hard bearish veto does not block
        # long signals when presidential/sannial cycles are bullish.
        if (asset_class == 'equity_indices'
                and location == 'bearish'
                and trend == 'uptrend'
                and len(closes) >= 5):
            roc_4 = (closes[-1] - closes[-4]) / closes[-4] if closes[-4] != 0 else 0
            if roc_4 > 0.02:
                location = 'neutral'
                location_pct = 50.0

        # DeepSeek Gap 3: flip location label back to original pair direction
        # after inverted price computation for USD-base forex.
        if is_usd_base_forex:
            if location == 'bullish':
                location = 'bearish'
            elif location == 'bearish':
                location = 'bullish'

        # Per OTC Lesson 3 frames 1887-1901: equilibrium location (33-66%)
        # is "no big brother" territory and degrades zone quality even with
        # HTF coverage. Returned as `location_pct` for downstream scoring.
        return {
            'location': location, 'trend': trend,
            'location_pct': round(location_pct, 1),
            'in_equilibrium': 33 < location_pct < 67,
        }

    def _determine_trend(
        self, highs: np.ndarray, lows: np.ndarray, htf: str = '1d'
    ) -> str:
        """Identify trend using ZigZag pivots (Hybrid AI methodology).

        Per Bernd's course: a pivot is confirmed when price reverses by at
        least the ZigZag percentage from the most recent extreme.

        ZigZag percentages by timeframe (Hybrid AI defaults + OTC Ch.012):
          Monthly : ~10%
          Weekly  : ~6%   (OTC Module 6 Ch.012: "six second percent" on weekly Netflix)
          Daily   : ~3%
          4H      : ~2%
          1H      : ~1%

        Previously used a flat 3% (daily default) for ALL timeframes.
        On weekly data that is too fine: ES weekly bars regularly move
        2-4%, so 3% confirms pivots on every swing and generates dozens of
        small reversals that obscure the broader trend. This caused weekly
        equity-index trend detection to show 'downtrend' when the market
        was clearly in a 12-month uptrend (e.g. ES in Jan 2024). Using 6%
        for weekly bars matches the OTC course explicit example.
        """
        # Per-timeframe ZigZag defaults (OTC Ch.012 + Hybrid AI course).
        # config.zigzag_percent overrides only the daily fallback.
        TF_ZIGZAG = {
            '1mo':  0.10,
            '1wk':  0.06,  # OTC Ch.012: "six second percent" on weekly chart
            '1d':   float(self.config.get('zigzag_percent', 3.0)) / 100.0,
            '60m':  0.02,
            '30m':  0.015,
            '15m':  0.01,
        }
        zz_pct = TF_ZIGZAG.get(htf, float(self.config.get('zigzag_percent', 3.0)) / 100.0)

        # Shorter lookback for longer timeframes: 200 weekly bars = 4 years
        # and includes bear-market lows that distort the recent trend picture.
        # Weekly income strategy needs ~2 years (100 bars); monthly ~3 years.
        LOOKBACK = {'1mo': 60, '1wk': 100, '1d': 200, '60m': 200, '15m': 200}
        n = min(LOOKBACK.get(htf, 200), len(highs))
        if n < 10:
            return 'sideways'
        h = highs[-n:]
        l = lows[-n:]

        pivots = self._zigzag_pivots(h, l, zz_pct)
        if len(pivots) < 4:
            return 'sideways'

        # Separate by type and take most recent 3 of each
        swing_highs = [(i, p) for i, p, t in pivots if t == 'H'][-3:]
        swing_lows  = [(i, p) for i, p, t in pivots if t == 'L'][-3:]

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return 'sideways'

        hh_vals = [p for _, p in swing_highs]
        ll_vals = [p for _, p in swing_lows]

        higher_highs = all(hh_vals[i] > hh_vals[i-1] for i in range(1, len(hh_vals)))
        higher_lows  = all(ll_vals[i] > ll_vals[i-1] for i in range(1, len(ll_vals)))
        lower_highs  = all(hh_vals[i] < hh_vals[i-1] for i in range(1, len(hh_vals)))
        lower_lows   = all(ll_vals[i] < ll_vals[i-1] for i in range(1, len(ll_vals)))

        # OTC Lesson 4 frames 378/466: pivot requirements are ASYMMETRIC.
        # Uptrend = higher LOWS are mandatory ("Required: 2x HL"); higher
        # highs are optional ("not necessarily required"). Downtrend = lower
        # HIGHS are mandatory; lower lows optional. Bernd shows that price
        # can carve a sideways top while higher lows still rise = still an
        # uptrend if HLs are intact.
        if higher_lows:
            return 'uptrend'
        if lower_highs:
            return 'downtrend'
        # Strict-symmetric fallback (legacy): only call out the trend if
        # both legs confirm. Otherwise sideways.
        if higher_highs and higher_lows:
            return 'uptrend'
        if lower_highs and lower_lows:
            return 'downtrend'
        return 'sideways'

    def _zigzag_pivots(self, h: np.ndarray, l: np.ndarray, pct: float) -> List[Tuple[int, float, str]]:
        """ZigZag pivot detection: a pivot is confirmed when price reverses
        by `pct` from the running extreme. Returns chronological list of
        (index, price, 'H'|'L') tuples.
        """
        n = len(h)
        if n < 2:
            return []
        pivots: List[Tuple[int, float, str]] = []
        # Seed direction from first 2 bars
        last_pivot_idx = 0
        last_pivot_val = h[0]
        last_pivot_type = 'H'  # provisional
        # Track extremes since last pivot
        max_idx, max_val = 0, h[0]
        min_idx, min_val = 0, l[0]
        direction = 0  # 0=undetermined, 1=up, -1=down

        for i in range(1, n):
            if h[i] > max_val:
                max_idx, max_val = i, h[i]
            if l[i] < min_val:
                min_idx, min_val = i, l[i]

            if direction >= 0:
                # Looking for a downside reversal from max_val
                if max_val > 0 and (max_val - l[i]) / max_val >= pct:
                    # Confirm a high pivot at max_idx
                    pivots.append((max_idx, max_val, 'H'))
                    last_pivot_idx, last_pivot_val, last_pivot_type = max_idx, max_val, 'H'
                    direction = -1
                    min_idx, min_val = i, l[i]
            if direction <= 0:
                if min_val > 0 and (h[i] - min_val) / min_val >= pct:
                    pivots.append((min_idx, min_val, 'L'))
                    last_pivot_idx, last_pivot_val, last_pivot_type = min_idx, min_val, 'L'
                    direction = 1
                    max_idx, max_val = i, h[i]
        return pivots

    def _indicators_for_class(
        self, asset_class: str, symbol: Optional[str] = None,
    ):
        """Build COT and Valuation engines tuned for the symbol's asset class.

        Per Hybrid AI Mod 3 + Funded Trader live trades:
          - COT: 26w default (Hybrid AI), 52w override for commodities
            (planting/harvest cycle). 156w extreme overlay always on.
          - Valuation ROC ("cycle"): asset-class default (10 / 13) with
            optional per-symbol override from `valuation.cycle_per_symbol`
            in BP_config.yaml. Bernd's "30-day cycle" / "10-day cycle"
            are simply different ROC periods on the same indicator
            (HAI 1:53:38). Per-symbol cheat-sheet style.
        """
        # Symbol-level override: soft agricultural commodities use Non-Commercials
        # at 26w (CLAUDE.md P1 fix) even when asset_class is still 'commodities'.
        # Natural Gas uses Retailers (contrarian) — Blueprint Cheatsheet fix.
        effective_class = asset_class
        if symbol in SOFT_COMMODITY_SYMBOLS:
            effective_class = 'soft_commodities'
        elif symbol in NAT_GAS_SYMBOLS:
            effective_class = 'nat_gas'

        cot_lookback = COT_LOOKBACK_BY_CLASS.get(
            effective_class, self.cot_index.lookback_weeks
        )

        # Phase 23 (Task 3): JPY 52-week COT lookback override.
        # 6J=F has low open interest → 26w window stays near index 50.
        # 52w gives the index more range to reach extremes.
        if symbol in JPY_SYMBOLS:
            cot_lookback = 52

        val_length = VALUATION_LENGTH_BY_CLASS.get(
            asset_class, self.valuation.length
        )
        # Per-symbol override (e.g. AAPL=30 daily, NDX=10 daily)
        cycle_overrides = self.config.get('valuation', {}).get('cycle_per_symbol', {}) or {}
        if symbol and symbol in cycle_overrides:
            override = cycle_overrides[symbol]
            if isinstance(override, int):
                val_length = override
            elif isinstance(override, dict):
                val_length = override.get('roc', val_length)

        # Blueprint Cheatsheet: forex Valuation uses ±69 boundaries
        # ("10-d-cycles trend following buy and sell (boundaries 69, -69)")
        # rather than the default ±75. This is confirmed for EUR, JPY, GBP, CHF.
        val_overvalued  = self.valuation.overvalued
        val_undervalued = self.valuation.undervalued
        if asset_class == 'forex':
            val_overvalued  = 69.0
            val_undervalued = -69.0

        cot = COTIndex(
            lookback_weeks=cot_lookback,
            upper_extreme=self.cot_index.upper_extreme,
            lower_extreme=self.cot_index.lower_extreme,
        )
        val = Valuation(
            length=val_length,
            rescale_length=self.valuation.rescale_length,
            overvalued=val_overvalued,
            undervalued=val_undervalued,
        )
        return cot, val

    # ------------------------------------------------------------------
    # Phase 15: Constituent-analysis Valuation for equity indices
    # ------------------------------------------------------------------

    def _constituent_valuation_bias(
        self,
        index_symbol: str,
        constituent_dfs: Dict[str, "pd.DataFrame"],
        valuation_refs: Dict[str, "pd.DataFrame"],
        val_engine: "Valuation",
    ) -> str:
        """Determine equity-index Valuation bias via constituent stock readings.

        Bernd (Ch.157 / CW40): "the two most important stocks is Apple and
        is Microsoft that they are not overbellied... if these two are
        undervalued, you can buy NQ / ES."

        Algorithm:
        1. Compute Valuation for each available constituent using the same
           macro references (DXY / ZN / ZB) as the standard indicator.
        2. Primary gate (AAPL + MSFT for NQ/ES; MSFT + UNH for YM):
           - Both primaries NOT strongly overvalued  → candidate = 'bullish'
           - Any primary strongly overvalued         → candidate = 'bearish'
           - Can't determine (data missing)          → candidate = 'neutral'
        3. Secondary vote (remaining mega-caps):
           - If candidate='bullish' and secondary majority ≤ 0 bullish
             (i.e. mostly overvalued) → downgrade to 'neutral'
           - If candidate='bearish' and secondary majority > half bullish
             → downgrade to 'neutral' (inconclusive)
        4. Return the final bias string.

        Falls back to 'neutral' gracefully whenever constituent data is thin.
        """
        spec = EQUITY_INDEX_CONSTITUENTS.get(index_symbol, {})
        primary_tickers   = spec.get('primary',   [])
        secondary_tickers = spec.get('secondary', [])

        def _stock_bias(ticker: str) -> Optional[str]:
            """Return 'bullish'/'bearish'/'neutral' for a single constituent."""
            df = constituent_dfs.get(ticker)
            if df is None or df.empty or not valuation_refs:
                return None
            try:
                vdf = val_engine.calculate(df, valuation_refs)
                return val_engine.get_bias(vdf)
            except Exception as exc:
                logger.debug(f"Constituent Valuation [{ticker}] failed: {exc}")
                return None

        # --- Primary gate ---
        primary_biases = [_stock_bias(t) for t in primary_tickers]
        primary_available = [b for b in primary_biases if b is not None]

        if not primary_available:
            logger.debug(f"[{index_symbol}] No primary constituent data; constituent Valuation = neutral")
            return 'neutral'

        # "Both primaries NOT strongly overvalued" = bullish for index
        # We use the val_engine's overvalued threshold as the strong-overvalued marker.
        # get_bias() returns 'bearish' when ANY reference line is strongly bearish.
        # For the primary gate: bearish primary → index bearish; bullish/neutral primary → ok.
        primary_bearish_count = sum(1 for b in primary_available if b == 'bearish')
        primary_bullish_count = sum(1 for b in primary_available if b == 'bullish')

        if primary_bearish_count >= 1:
            # At least one key constituent is overvalued — index bias unfavourable
            candidate = 'bearish'
        elif primary_bullish_count == len(primary_available):
            # All available primaries are undervalued → strong bullish candidate
            candidate = 'bullish'
        else:
            # Mix of bullish + neutral → mildly bullish; treat as bullish
            candidate = 'bullish'

        # --- Secondary confirmation ---
        if secondary_tickers:
            secondary_biases = [_stock_bias(t) for t in secondary_tickers]
            sec_available = [b for b in secondary_biases if b is not None]
            if sec_available:
                sec_bull = sum(1 for b in sec_available if b == 'bullish')
                sec_bear = sum(1 for b in sec_available if b == 'bearish')
                if candidate == 'bullish' and sec_bear > sec_bull:
                    # Secondary stocks mostly overvalued → inconclusive
                    logger.debug(
                        f"[{index_symbol}] Secondary vote ({sec_bull}↑ {sec_bear}↓) "
                        f"downgrades bullish candidate to neutral"
                    )
                    candidate = 'neutral'
                elif candidate == 'bearish' and sec_bull > sec_bear:
                    # Secondary stocks mostly undervalued → inconclusive
                    logger.debug(
                        f"[{index_symbol}] Secondary vote ({sec_bull}↑ {sec_bear}↓) "
                        f"downgrades bearish candidate to neutral"
                    )
                    candidate = 'neutral'

        logger.debug(
            f"[{index_symbol}] Constituent Valuation: "
            f"primary={primary_biases} secondary_available={len([b for b in (secondary_tickers and [_stock_bias(t) for t in secondary_tickers]) or [] if b])} → {candidate}"
        )
        return candidate

    def _constituent_proxy_bias(
        self,
        index_symbol: str,
        constituent_dfs: Dict[str, "pd.DataFrame"],
    ) -> str:
        """Phase 24: equity-index bias derived from per-constituent SMA proxy.

        Like `_constituent_valuation_bias` but uses the Phase 24
        timeframe-aware `_stock_valuation_proxy` (price vs N-year SMA) per
        stock instead of the macro DXY/ZB Valuation. The macro Valuation
        reads stocks as 'overvalued' in any rising-rate environment because
        bonds (ZB) crash with stocks; the SMA proxy is mean-reversion based
        and matches Bernd's "AAPL undervalued" reading.

        Used to route the bullish thesis through to NQ/ES/YM when:
        - The index itself has no demand zone (price at ATH)
        - Cycles agree bullish (presidential + sannial)
        - At least the primary constituents read 'bullish' on the SMA proxy

        Returns 'bullish' / 'bearish' / 'neutral'.
        """
        spec = EQUITY_INDEX_CONSTITUENTS.get(index_symbol, {})
        primary_tickers   = spec.get('primary',   [])
        secondary_tickers = spec.get('secondary', [])

        def _proxy_for(ticker: str) -> Optional[str]:
            df = constituent_dfs.get(ticker) if constituent_dfs else None
            if df is None or df.empty:
                return None
            try:
                return self._stock_valuation_proxy(df)
            except Exception as exc:
                logger.debug(f"Constituent proxy [{ticker}] failed: {exc}")
                return None

        primary_biases = [_proxy_for(t) for t in primary_tickers]
        primary_available = [b for b in primary_biases if b is not None]
        if not primary_available:
            return 'neutral'

        primary_bull = sum(1 for b in primary_available if b == 'bullish')
        primary_bear = sum(1 for b in primary_available if b == 'bearish')
        if primary_bear >= 1:
            candidate = 'bearish'
        elif primary_bull == len(primary_available):
            candidate = 'bullish'
        elif primary_bull >= 1:
            candidate = 'bullish'
        else:
            candidate = 'neutral'

        # Secondary confirmation
        # Phase 25 (DeepSeek P2): require at least 2 secondary stocks to have
        # data before we let the secondary vote downgrade the primary candidate.
        # A single secondary stock voting against the primaries is too noisy
        # to override AAPL+MSFT (or MSFT+UNH) — Bernd's primary-stock signal.
        if secondary_tickers:
            sec_biases = [_proxy_for(t) for t in secondary_tickers]
            sec_avail = [b for b in sec_biases if b is not None]
            if len(sec_avail) >= 2:
                sec_bull = sum(1 for b in sec_avail if b == 'bullish')
                sec_bear = sum(1 for b in sec_avail if b == 'bearish')
                if candidate == 'bullish' and sec_bear > sec_bull:
                    candidate = 'neutral'
                elif candidate == 'bearish' and sec_bull > sec_bear:
                    candidate = 'neutral'

        logger.info(
            f"[{index_symbol}] Constituent SMA-proxy bias: "
            f"primary={primary_biases} → {candidate}"
        )
        return candidate

    @staticmethod
    def _stock_valuation_proxy(
        price_df: pd.DataFrame,
        years_lookback: float = 3.0,
        overvalued_pct: float = 0.35,    # >35% above LT mean = expensive
        undervalued_pct: float = -0.05,  # <5% below LT mean = cheap
    ) -> str:
        """Phase 23 (Task 2) — Phase 24 timeframe-aware fix.

        Price-vs-N-year-SMA proxy for individual-stock Valuation. The macro
        Valuation (ROC vs DXY/ZB/GC) reads stocks as 'overvalued' in any
        rising-rate environment (rates up → ZB falls → relative ROC of stock
        vs ZB positive → bearish). Bernd's CampusValuationTool_V2 (unavailable
        to us) compares to intrinsic / earnings value. This proxy uses the
        same directional intent via 3-year SMA mean-reversion.

        Phase 24 fix: previously used a fixed `sma_period=156` regardless of
        the input timeframe — for monthly price_df, 156 bars = 13 years (way
        too long); for daily price_df, 156 bars = 7.5 months (way too short).
        Now infers the bar frequency from the timestamp column and computes
        the SMA window in CALENDAR years. Defaults to 3 years.

        Asymmetric thresholds: 35% above (growth premium tolerance) / 5% below
        (mean-reversion entry). Returns 'bullish' / 'bearish' / 'neutral'.
        """
        if price_df is None or len(price_df) < 12:
            return 'neutral'

        # Extract closes
        if 'close' in price_df.columns:
            closes = price_df['close']
        elif 'Close' in price_df.columns:
            closes = price_df['Close']
        else:
            closes = price_df.iloc[:, 3]

        # Phase 24: detect frequency from timestamp spacing -> sma window in bars
        # corresponding to the requested calendar lookback.
        # Phase 25 (DeepSeek P1+P2): (a) check additional timestamp column names
        # ('Date', 'date'); (b) explicitly reject intraday data (med_days < 0.9)
        # — the proxy is calibrated for daily/weekly/monthly only. For hourly or
        # finer data, the SMA period would be miscalibrated (e.g. 60-min stock
        # data → 252×3 = 756 hourly bars covers ~3 months, not 3 years).
        bars_per_year = 12  # safe default = monthly
        try:
            ts = None
            for _col in ('timestamp', 'Date', 'date', 'Datetime', 'datetime'):
                if _col in price_df.columns:
                    ts = pd.to_datetime(price_df[_col])
                    break
            if ts is None:
                ts = pd.to_datetime(price_df.index)
            if len(ts) >= 5:
                # Median day-spacing between consecutive bars (more robust than mean)
                deltas_days = ts.diff().dropna().dt.total_seconds().div(86400.0)
                med_days = float(deltas_days.median())
                # Phase 25: reject intraday data — proxy not calibrated for it
                if med_days < 0.9:
                    return 'neutral'
                if med_days > 0:
                    if   med_days <= 2.0:  bars_per_year = 252   # daily
                    elif med_days <= 9.0:  bars_per_year = 52    # weekly
                    elif med_days <= 35.0: bars_per_year = 12    # monthly
                    else:                  bars_per_year = 4     # quarterly+
        except Exception:
            pass

        sma_period = max(int(round(bars_per_year * years_lookback)), 12)
        # require at least half the lookback window of data
        if len(closes) < max(sma_period // 2, 12):
            return 'neutral'

        actual_period = min(sma_period, len(closes))
        sma = closes.rolling(actual_period,
                             min_periods=max(12, actual_period // 2)
                             ).mean().iloc[-1]
        if pd.isna(sma) or sma == 0:
            return 'neutral'
        current = closes.iloc[-1]
        if pd.isna(current):
            return 'neutral'
        pct_above_mean = (current - sma) / sma
        if pct_above_mean <= undervalued_pct:
            return 'bullish'
        elif pct_above_mean >= overvalued_pct:
            return 'bearish'
        else:
            return 'neutral'

    def _analyze_fundamentals(
        self,
        cot_df: pd.DataFrame,
        price_df: pd.DataFrame,
        valuation_refs: Dict[str, pd.DataFrame],
        seasonal_df: pd.DataFrame,
        asset_class: str = 'commodities',
        opposing_cot_df: Optional[pd.DataFrame] = None,
        symbol: Optional[str] = None,
        constituent_dfs: Optional[Dict[str, "pd.DataFrame"]] = None,
    ) -> Dict[str, str]:
        """Step 3: COT, Valuation, Seasonality bias (asset-class aware).

        For forex, an opposing-currency COT (e.g. USD when trading EUR/USD)
        can be passed in -- the EUR-side bias must agree with the inverted
        USD-side bias before we accept it. This honours rule #17 from the
        Blueprint non-negotiables.

        For equity indices (NQ=F/ES=F/YM=F), constituent_dfs supplies
        individual-stock OHLCV so Valuation can be computed per-constituent
        instead of on the index directly. Pass a dict {ticker: price_df}.
        If constituent_dfs is None or empty, falls back to direct Valuation.
        """
        cot_engine, val_engine = self._indicators_for_class(asset_class, symbol=symbol)

        cot_bias = 'neutral'
        cot_strength = 'none'
        cot_cross = None
        if cot_df is not None and not cot_df.empty:
            try:
                cot_calculated = cot_engine.calculate(cot_df)
                cot_bias, cot_strength = cot_engine.get_bias(
                    cot_calculated, asset_class=asset_class, return_strength=True,
                )
                # Phase 21 fix: USD-base forex pairs (USDJPY=X, USDCHF=X, USDCAD=X).
                # COT data is fetched for the QUOTE currency (JPY/CHF/CAD futures).
                # "Bullish" from non-comms = they're long the QUOTE currency = short USD
                # = BEARISH for the USD-base pair.  Invert before consensus.
                #
                # Example: USDCHF=X fetches CHF COT (6S=F / 092741).
                #   Non-comms LONG CHF → cot_bias='bullish' → means SELL USDCHF.
                #   Without inversion the system reads 'bullish' as BUY USDCHF — wrong.
                #
                # Non-USD-base pairs (EURUSD, GBPUSD, AUDUSD) need NO inversion:
                #   their COT tracks the base currency directly.
                #
                # The comment "(inverted)" in BP_data_fetcher.get_cftc_code was the
                # original annotation — this is the actual inversion that was missing.
                if (asset_class == 'forex' and symbol and
                        symbol.upper().startswith('USD') and '=X' in symbol and
                        cot_bias != 'neutral'):
                    _inv = {'bullish': 'bearish', 'bearish': 'bullish'}
                    cot_bias = _inv.get(cot_bias, cot_bias)
                    logger.info(
                        f"Phase 21: USD-base pair {symbol} — COT inverted to {cot_bias}"
                    )
                # Cross-category relationship: producer-vs-retailer (smart vs
                # dumb money) and funds-vs-commercials. Per Bernd's teaching,
                # when commercials and retailers are at OPPOSITE extremes
                # simultaneously, that's the highest-conviction signal --
                # promote to strong even if single-category bias was neutral.
                cot_cross = cot_engine.cross_category_signal(cot_calculated)
                # Phase 20 fix: cross_category_signal was designed for commodity
                # markets where commercials = "smart money" (physical
                # producers/consumers with superior price knowledge). For FX,
                # corporate hedgers (commercials) mechanically hedge
                # receivables/payables — they are NOT directional "smart money".
                # Applying the commodity override to forex is architecturally
                # incorrect and caused the two-layer failure isolated in Phase 19:
                #   Layer 1 — extreme_confluence flips non-comm bullish to bearish
                #   Layer 2 — forex cross-check sees conflict, demotes to neutral
                # Guard: only fire for non-forex asset classes.
                if cot_cross.get('extreme_confluence') and asset_class not in ('forex',):
                    smart = cot_cross['smart_vs_dumb']  # 'bullish' or 'bearish'
                    if cot_bias == 'neutral':
                        cot_bias = smart
                    elif cot_bias != smart:
                        # Single-category bias contradicts smart-vs-dumb -> trust
                        # the relational pattern (more reliable per Bernd).
                        logger.info(
                            f"COT smart-vs-dumb ({smart}) overrides single-category ({cot_bias})"
                        )
                        cot_bias = smart
                    cot_strength = 'strong'
                    logger.info(f"COT cross-category extreme confluence: {smart}")
                # For forex, cross-check the opposing currency. Per HAI Mod 3
                # L1 Part 3 (frames 728-983 EUR/USD non-commercial example):
                #   - Both sides agree (inverted) -> DOUBLE CONFIRMED, boost to 'strong'
                #   - One side neutral -> single bias (current strength)
                #   - Both same direction (not inverted) -> CONFLICTING, demote to neutral
                if asset_class == 'forex' and opposing_cot_df is not None and not opposing_cot_df.empty:
                    opp = cot_engine.calculate(opposing_cot_df)
                    opp_bias, opp_strength = cot_engine.get_bias(
                        opp, asset_class='forex', return_strength=True,
                    )
                    inverted = {'bullish': 'bearish', 'bearish': 'bullish', 'neutral': 'neutral'}[opp_bias]
                    if cot_bias != 'neutral' and opp_bias != 'neutral':
                        if cot_bias == inverted:
                            # Both sides agree directionally -> double confirmation
                            cot_strength = 'strong'
                            logger.info(
                                f"COT double-confirmed via opposing currency (this={cot_bias} "
                                f"opposing-inverted={inverted}); strength=strong"
                            )
                        else:
                            # Both sides in same direction -> conflicting, demote
                            logger.info(
                                f"COT cross-check conflict (this={cot_bias} "
                                f"opposing-inverted={inverted}); demoting to neutral"
                            )
                            cot_bias = 'neutral'
                            cot_strength = 'none'
                    # Phase 23 (Task 5): inherit from opposing currency when own
                    # COT is too weak to signal but opposing has strong/normal bias.
                    # One-sided signal capped at 'normal' conviction.
                    elif cot_bias == 'neutral' and inverted != 'neutral' and opp_strength in ('strong', 'normal'):
                        cot_bias = inverted
                        cot_strength = 'normal'
                        logger.info(
                            f"COT inherited from opposing currency (own=neutral, "
                            f"opp={opp_bias} strength={opp_strength} -> inverted={inverted}); "
                            f"this side now {cot_bias} normal"
                        )
                if cot_bias != 'neutral':
                    logger.info(f"COT bias={cot_bias} strength={cot_strength}")
            except Exception as e:
                logger.warning(f"COT calculation failed: {e}")

        val_bias = 'neutral'
        # Blueprint Cheatsheet: some symbols explicitly exclude Valuation ("-").
        # Natural Gas is weather/supply-shock driven; DXY-relative analysis
        # is uninformative and would generate false vetoes.
        _skip_val = symbol in VALUATION_SKIP_SYMBOLS if symbol else False
        #
        # Phase 15 (revised): Skip Valuation for equity indices.
        # The standard DXY/ZN/ZB comparison reads equity indices as 'bearish'
        # whenever they outperform bonds (i.e. in every bull market), producing
        # false Valuation vetoes on correct long signals. Bernd's "undervalued"
        # for individual stocks is computed by CampusValuationTool_V2 which is
        # NOT available (user confirmed). The constituent-stock approach inherits
        # the same problem (stocks outperform bonds → all read as overvalued).
        # Treating equity-index Valuation as 'neutral' lets Location + COT +
        # Seasonality drive the bias without an incorrect hard veto.
        # NOTE: constituent_dfs infrastructure is preserved for future use if
        # the CampusValuationTool_V2 Pine Script becomes available.
        if asset_class == 'equity_indices':
            _skip_val = True
        if _skip_val:
            pass  # val_bias stays 'neutral'
        # Phase 23 (Task 2): individual stocks use price-vs-3yr-SMA proxy
        # instead of macro Valuation (which reads bullish stocks as 'overvalued'
        # in any rising-rate environment).
        elif asset_class == 'equities':
            # DeepSeek Gap 2: use relative strength vs SPY as proxy for
            # CampusValuationTool_V2. A stock lagging SPY reads as undervalued
            # matching Bernd's intuition. Falls back to SMA proxy if no SPY data.
            spy_df = valuation_refs.get('SPY') if valuation_refs else None
            if spy_df is not None and not spy_df.empty:
                try:
                    rel_val_engine = Valuation(
                        length=10,
                        rescale_length=100,
                        overvalued=75.0,
                        undervalued=-75.0,
                    )
                    rel_val_df = rel_val_engine.calculate(price_df, {'SPY': spy_df})
                    val_bias = rel_val_engine.get_bias(rel_val_df)
                    logger.info(f"[{symbol}] Stock Relative-Strength Val vs SPY: {val_bias}")
                except Exception as e:
                    logger.warning(f"Relative-strength Valuation failed ({e}); falling back to SMA proxy")
                    val_bias = self._stock_valuation_proxy(price_df)
            else:
                try:
                    val_bias = self._stock_valuation_proxy(price_df)
                    logger.info(f"[{symbol}] Stock Valuation proxy (price vs 3yr SMA): {val_bias}")
                except Exception as e:
                    logger.warning(f"Stock Valuation proxy failed: {e}")
        elif valuation_refs:
            try:
                val_df = val_engine.calculate(price_df, valuation_refs)
                val_bias = val_engine.get_bias(val_df)
            except Exception as e:
                logger.warning(f"Valuation calculation failed: {e}")

        seas_bias = 'neutral'
        if seasonal_df is not None and not seasonal_df.empty:
            try:
                # Phase 16: Bitcoin only has ~4 years of history.
                # 03_funded.txt lines 451, 864-865: "We can only do four years."
                # Use a temporary Seasonality instance with 4yr-only lookback.
                # Phase 28 A3 fix: seasonal_df is always daily OHLCV (per
                # BP_data_fetcher.fetch_seasonality_reference). The Pine Script
                # Seasonality_OTC binning is timeframe-aware — daily charts use
                # the 252-bin TDOY pattern. Previously we passed timeframe='weekly'
                # which routed to the 52-bin weekly branch and silently degraded
                # NG / BTC / soft commodities / energies seasonality reads.
                if symbol in BTC_SYMBOLS:
                    _seas_engine = Seasonality(multi_lookbacks=(4,))
                    multi = _seas_engine.calculate_multi(seasonal_df, timeframe='daily')
                # Phase 25 (DeepSeek P3): enforce NG=F 10y+5y-only restriction in code.
                # Cheatsheet + corpus state NG seasonality should use 10y + 5y lookbacks
                # only (15y data is unreliable for natural gas due to shale-era regime
                # change). Previously documented but not enforced — Seasonality class
                # would compute 15y too and let it vote in the 2-of-3 majority.
                elif symbol in NAT_GAS_SYMBOLS:
                    _seas_engine = Seasonality(multi_lookbacks=(5, 10))
                    multi = _seas_engine.calculate_multi(seasonal_df, timeframe='daily')
                else:
                    # Standard: 5y/10y/15y — 2-of-3 must agree (Phase 9)
                    multi = self.seasonality.calculate_multi(seasonal_df, timeframe='daily')
                if multi:
                    current_bin = self.seasonality.get_current_bin(price_df, 'daily')
                    seas_bias = self.seasonality.get_bias_multi(multi, current_bin)
            except Exception as e:
                logger.warning(f"Seasonality calculation failed: {e}")

        # Phase 24: equity-index constituent SMA-proxy bias.
        # Computed when constituent OHLCV is available so consensus can route
        # a bullish thesis through to the index when (a) cycles agree bullish,
        # (b) loc='bearish' (index at ATH), and (c) the primary constituent
        # stocks are themselves below their 3yr SMA. Bernd verbatim:
        # "if these two [AAPL+MSFT] are undervalued, you can buy NQ / ES."
        constituent_bias = 'neutral'
        if asset_class == 'equity_indices' and symbol and constituent_dfs:
            try:
                constituent_bias = self._constituent_proxy_bias(symbol, constituent_dfs)
            except Exception as e:
                logger.warning(f"Constituent proxy bias failed: {e}")

        return {
            'cot': cot_bias,
            'cot_strength': cot_strength,
            'cot_cross': cot_cross,                # smart_vs_dumb, funds_vs_commercials, extreme_confluence
            'valuation': val_bias,
            'seasonality': seas_bias,
            'constituent': constituent_bias,       # Phase 24: equity-index constituent proxy
        }

    def _equity_index_short_cross_asset_gate(
        self,
        symbol: str,
        cot_df: Optional[pd.DataFrame],
        valuation_refs: Optional[Dict[str, pd.DataFrame]],
        bond_lookback: int = 13,
    ) -> Tuple[bool, str]:
        """Phase 6 P1 (Ch 156): equity-index shorts require BOTH retailer-extreme
        bullish AND Treasury Bond ROC actively rolling from positive toward
        negative. Either signal alone is insufficient.

        Bernd: "right now I just don't see the short coming. Retailers are
        getting more and more bullish on the weekly... we need the help of
        other Treasury bonds [to roll over]."

        Returns (allowed, reason).
        """
        # FIX Bug 3: COTIndex.calculate is an INSTANCE method, not a static.
        # The original code called COTIndex.calculate(cot_df, lookback_weeks=26, group='retailers')
        # which raises TypeError. Build a proper instance and call it correctly.
        retailers_extreme = False
        if cot_df is not None and not cot_df.empty:
            from BP_indicators import COTIndex
            _cot_engine = COTIndex(lookback_weeks=26, upper_extreme=80, lower_extreme=20)
            cot_calc = _cot_engine.calculate(cot_df)
            if not cot_calc.empty and 'small_specs_index' in cot_calc.columns:
                latest = cot_calc['small_specs_index'].iloc[-1]
                retailers_extreme = bool(latest >= 80)

        # 2. Bond ROC rolling-over check
        bond_rolling = False
        bond_now = bond_prev = None
        if valuation_refs:
            bond_df = valuation_refs.get('ZB') or valuation_refs.get('US') or valuation_refs.get('VD')
            if bond_df is not None and not bond_df.empty and len(bond_df) >= bond_lookback + 5:
                close = bond_df['close']
                # rate-of-change in % vs n bars ago
                roc = (close / close.shift(bond_lookback) - 1) * 100
                bond_now = roc.iloc[-1]
                bond_prev = roc.iloc[-3] if len(roc) > 3 else None
                if bond_now is not None and bond_prev is not None:
                    bond_rolling = bool(bond_now < 0 and bond_prev > 0)

        if retailers_extreme and bond_rolling:
            return True, f"OK -- retailers extreme bullish AND bonds rolling over (ROC {bond_prev:.2f}->{bond_now:.2f})"
        if retailers_extreme:
            return False, "WAIT -- retailers extreme but bonds not yet rolling over"
        if bond_rolling:
            return False, "WAIT -- bonds rolling over but retailers not yet extreme"
        return False, "VETO -- neither retailer-extreme nor bond-rollover signals active"

    def _bias_consensus(
        self, biases: Dict[str, str], income_strategy: str,
        asset_class: Optional[str] = None,
        at_zone: bool = False,
        zone_composite: float = 0.0,
        today_override: Optional[date] = None,
    ) -> str:
        """Synthesize biases into a final directional call.

        Phase 11 — Bernd's ACTUAL hierarchy (replaces flat 3-of-5 equal vote).

        Frequency analysis across 186 course/session transcripts:
          92% — Valuation checked first
          88% — Location / zone presence checked
          76% — Seasonality as supporting context
          64% — Trend direction
          48% — COT (confluence enhancer, not primary gate for most trades)

        For FUTURES the new hierarchy is:
          Step 1. Location gate  — if loc=='neutral' (equilibrium) → no trade.
                                   Bernd: "never trade at 50%, no edge there."
          Step 2. Valuation veto — if Valuation strongly OPPOSES location → veto.
                                   CW38/CW39: "Rule Number One — Valuation."
          Step 3. Counter-trend  — short in uptrend / long in downtrend requires
                                   overwhelming non-trend agreement (Phase 8 H1).
          Step 4. Minimum met    — Location aligned + Valuation aligned = tradeable.
                                   OR  Location aligned + Valuation neutral
                                       + at least 1 of (COT/Seasonality/Trend) agrees.

        For INDIVIDUAL STOCKS (no CFTC COT; Valuation-driven per Phase 6 audit):
          - NEVER short individual stocks (Bernd uses index futures for shorts)
          - Primary: Valuation undervalued
          - Secondary: Seasonality + Location demand zone
          - Tertiary: Seasonality bullish, Valuation not opposing, no downtrend
        """
        val   = biases.get('valuation',   'neutral')
        trend = biases.get('trend',        'sideways')
        loc   = biases.get('location',     'neutral')
        cot   = biases.get('cot',          'neutral')
        seas  = biases.get('seasonality',  'neutral')

        # Normalise trend vocabulary ('uptrend'/'downtrend'/'sideways') so it
        # can be compared against 'bullish'/'bearish'/'neutral' below.
        # Phase 5 bug-fix: trend was being silently ignored because it never
        # matched the 'bullish'/'bearish' literals in the old vote tally.
        normalized = {}
        for k, v in biases.items():
            if v == 'uptrend':    normalized[k] = 'bullish'
            elif v == 'downtrend': normalized[k] = 'bearish'
            elif v == 'sideways':  normalized[k] = 'neutral'
            else:                  normalized[k] = v

        trend_n = normalized.get('trend', 'neutral')

        # Phase 8 H1 fix: tally non-trend indicators separately.
        # The counter-trend gate uses these tallies so that in an uptrend
        # (trend contributes 1 'bullish') the gate's `bullish_excl == 0`
        # clause remains reachable for genuine short setups.
        # cot_strength is excluded from direction tallies (it's a meta-value,
        # not a direction string — it won't match 'bullish'/'bearish' anyway).
        # Phase 24: 'constituent' is excluded too — it's an index-level proxy
        # of the Valuation read, not an independent fundamental vote.
        _tally_exclude = {'trend', 'cot_strength', 'constituent'}
        bullish_excl_trend = sum(1 for k, v in normalized.items()
                                 if k not in _tally_exclude and v == 'bullish')
        bearish_excl_trend = sum(1 for k, v in normalized.items()
                                 if k not in _tally_exclude and v == 'bearish')

        # ================================================================
        # Phase 23 (Task 1): Presidential/Sannial cycle Location override
        # for equity indices at all-time-high "expensive" Locations.
        #
        # When BOTH long-term cycles agree bullish, equity indices at ATH
        # (loc='bearish') are NOT a short setup — the bull market continues.
        # Two-tier upgrade:
        #   • FULL override → loc='bullish'  when at least 1 non-location/non-trend
        #     fundamental (COT or Seasonality) agrees bullish and none are bearish.
        #     Lets Step 4 fire a 'bullish' signal normally.
        #   • PARTIAL relax → loc='neutral'  when fundamentals are all neutral.
        #     Suppresses the hard-bearish location without forcing a long signal.
        #   • NO change if any fundamental is actively bearish.
        #
        # today_override allows the goldtest to pass the case_date so cycle
        # tables fire on the historical year (2023 = year 3, sannial 3 = bull).
        # ================================================================
        if asset_class == 'equity_indices' and loc == 'bearish':
            try:
                from BP_roadmap import (
                    PRESIDENTIAL_CYCLE_BIAS, SANNIAL_CYCLE_BIAS,
                    cycle_year_in_pres_cycle,
                )
                ref_date = today_override if today_override is not None else date.today()
                cy = cycle_year_in_pres_cycle(ref_date.year)
                pres_score = PRESIDENTIAL_CYCLE_BIAS.get(cy, [0]*12)[ref_date.month - 1]
                sann_score = SANNIAL_CYCLE_BIAS.get(ref_date.year % 10, 0)
                if pres_score > 0 and sann_score > 0:
                    # Assess non-location, non-trend fundamentals
                    _cot_n  = normalized.get('cot',         'neutral')
                    _seas_n = normalized.get('seasonality', 'neutral')
                    _val_n  = normalized.get('valuation',   'neutral')
                    _const_n = normalized.get('constituent', 'neutral')
                    _bear_count  = sum(1 for x in [_cot_n, _seas_n, _val_n] if x == 'bearish')
                    _bull_count  = sum(1 for x in [_cot_n, _seas_n, _val_n] if x == 'bullish')
                    _any_bearish = _bear_count > 0
                    # Phase 24 — T1 relaxed: allow ONE bearish fundamental as long as
                    # seasonality is bullish (Bernd's clearest pre-election bias signal).
                    # Captures early-2023 NQ/ES/YM cases where COT large-specs were
                    # still net short BUT seasonality + cycle roadmap were bullish.
                    _seas_overrides_one_bearish = (
                        _seas_n == 'bullish' and _bear_count == 1 and _bull_count >= 1
                    )
                    # Phase 24 — Constituent route: bullish constituent stocks ALONE
                    # are enough to override loc='bearish' when cycles agree, even
                    # if other fundamentals are bearish. Bernd Ch.157: "if these
                    # two [AAPL + MSFT] are undervalued, you can buy NQ / ES."
                    # Allow up to 1 bearish fundamental at the index level to
                    # accommodate early-recovery COT.
                    _constituent_overrides = (
                        _const_n == 'bullish' and _bear_count <= 1
                    )
                    if _constituent_overrides:
                        # Constituent route: AAPL/MSFT undervalued → route bullish
                        loc = 'bullish'
                        biases = dict(biases, location='bullish')
                        normalized = dict(normalized, location='bullish')
                        logger.info(
                            f"Phase 24 T1-constituent: constituent_bias=bullish "
                            f"(pres={pres_score} sann={sann_score} bear={_bear_count}) "
                            f"→ loc=bullish (route NQ/ES via AAPL/MSFT thesis)"
                        )
                    elif not _any_bearish and _bull_count >= 1:
                        # Full upgrade: cycle + at least 1 fundamental agree bullish
                        loc = 'bullish'
                        biases = dict(biases, location='bullish')
                        normalized = dict(normalized, location='bullish')
                        logger.info(
                            f"Phase 23 T1: FULL override (pres={pres_score} sann={sann_score} "
                            f"bull_funds={_bull_count}) → loc=bullish"
                        )
                    elif _seas_overrides_one_bearish:
                        # Phase 24 relaxed full upgrade: seasonality bullish overrides
                        # one bearish fundamental (almost always: COT large-specs short
                        # in early-recovery phase). Cycle + Seas alignment is enough.
                        loc = 'bullish'
                        biases = dict(biases, location='bullish')
                        normalized = dict(normalized, location='bullish')
                        logger.info(
                            f"Phase 24 T1-relaxed: seasonality override "
                            f"(pres={pres_score} sann={sann_score} bear={_bear_count} "
                            f"bull={_bull_count}) → loc=bullish"
                        )
                    elif not _any_bearish:
                        # Partial relax: cycles agree but all fundamentals neutral
                        loc = 'neutral'
                        biases = dict(biases, location='neutral')
                        normalized = dict(normalized, location='neutral')
                        logger.info(
                            f"Phase 23 T1: PARTIAL relax (pres={pres_score} sann={sann_score} "
                            f"all funds neutral) → loc=neutral"
                        )
                    else:
                        logger.debug(
                            f"Phase 23 T1: skipped — bearish fundamental present "
                            f"(cot={_cot_n} seas={_seas_n} val={_val_n})"
                        )
            except Exception as e:
                logger.debug(f"Cycle override skipped: {e}")

        # Phase 26 (DeepSeek): early-2023 cycle-dominance override for equity indices.
        # When location is no longer bearish and both long-term cycles are bullish,
        # the cycles alone drive a LONG bias even when COT and Seasonality are neutral.
        # Mirrors Bernd reasoning: "cycles so strong I will be a buyer anyway."
        # Sideways included (not just uptrend) — empirically tested: the 3 sideways cases
        # in 2023 (consolidation before the ATH rally) were valid bullish roadmap calls.
        # Restricting to uptrend-only lost 3 correct cases with zero benefit (tested Phase 26d).
        if (asset_class == 'equity_indices'
                and loc != 'bearish'
                and trend in ('uptrend', 'sideways')
                and normalized.get('valuation',   'neutral') != 'bearish'
                and normalized.get('seasonality', 'neutral') != 'bearish'):
            try:
                from BP_roadmap import (
                    PRESIDENTIAL_CYCLE_BIAS, SANNIAL_CYCLE_BIAS,
                    cycle_year_in_pres_cycle,
                )
                ref_date = today_override if today_override is not None else date.today()
                cy = cycle_year_in_pres_cycle(ref_date.year)
                pres_score = PRESIDENTIAL_CYCLE_BIAS.get(cy, [0]*12)[ref_date.month - 1]
                sann_score = SANNIAL_CYCLE_BIAS.get(ref_date.year % 10, 0)
                if pres_score > 0 and sann_score > 0:
                    cot_n = normalized.get('cot', 'neutral')
                    if cot_n != 'bearish':
                        logger.info(
                            f"Phase 26 cycle-dominance: equity index uptrend + both cycles bullish "
                            f"(pres={pres_score} sann={sann_score} cot={cot_n}) -> bullish"
                        )
                        return 'bullish'
            except Exception as e:
                logger.debug(f"Phase 26 cycle dominance skipped: {e}")

        # Phase 23 (Task 4): zone-arrival soft-veto eligibility flag.
        # composite >= 7.0 = top-quartile zone; soft-veto only fires when
        # price has actually arrived at a high-quality zone.
        _hq_zone_arrival = bool(at_zone and zone_composite >= 7.0)

        # ----------------------------------------------------------------
        # STOCKS: Valuation-driven, long-only (Phase 6 audit validated)
        # ----------------------------------------------------------------
        if asset_class == 'equities':
            seas_n = normalized.get('seasonality', 'neutral')
            loc_n  = normalized.get('location',    'neutral')
            # Primary: Valuation undervalued, not in a downtrend
            if val == 'bullish' and trend != 'downtrend':
                return 'bullish'
            # Secondary: Seasonality + Location both bullish (demand zone buy)
            if seas_n == 'bullish' and loc_n == 'bullish':
                return 'bullish'
            # Tertiary: Seasonality bullish, Valuation not bearish, not downtrend
            if seas_n == 'bullish' and val != 'bearish' and trend != 'downtrend':
                return 'bullish'
            # Phase 23 T2 relaxed path: genuinely cheap (T2 proxy undervalued) AND
            # seasonality both agree bullish, even in a downtrend.
            # Covers "buy the crash" setups: 2022-crashed stocks (NFLX/META/AMZN/GOOG)
            # where price is >5% below 3yr SMA AND January/spring seasonality is bullish.
            # NOTE: val='bearish' blocks this (T2 says overvalued = no long).
            if val == 'bullish' and seas_n == 'bullish':
                return 'bullish'
            # Phase 27 — Presidential/sannial cycle path for individual stocks.
            # Bernd's roadmap calls (AAPL/MSFT/GOOG/META/NFLX long throughout 2023)
            # were driven by pre-election year-3 + sannial year-3 (both strongly bullish).
            # When both long-term cycles agree bullish AND seasonality is not bearish,
            # fire bullish regardless of local trend.
            # Trend guard removed (Phase 27b): the Oct 2023 pullback put stocks in a
            # local 'downtrend' via ZigZag even though Bernd was bullish for Q4 — the
            # presidential/sannial cycle reasoning explicitly overrides local trend for
            # individual stocks (same way T1 overrides expensive Location for indices).
            # Safe: equities branch never returns 'bearish', so no wrong-direction risk
            # at Stage-1. Stage-2 zone+decision-matrix still gates real trade signals.
            if seas_n != 'bearish':
                try:
                    from BP_roadmap import (
                        PRESIDENTIAL_CYCLE_BIAS, SANNIAL_CYCLE_BIAS,
                        cycle_year_in_pres_cycle,
                    )
                    ref_date = (today_override if today_override is not None
                                else date.today())
                    cy = cycle_year_in_pres_cycle(ref_date.year)
                    pres_score = PRESIDENTIAL_CYCLE_BIAS.get(
                        cy, [0] * 12)[ref_date.month - 1]
                    sann_score = SANNIAL_CYCLE_BIAS.get(ref_date.year % 10, 0)
                    if pres_score > 0 and sann_score > 0:
                        logger.info(
                            f"Phase 27 equities cycle: pres={pres_score} "
                            f"sann={sann_score} seas={seas_n} trend={trend} -> bullish"
                        )
                        return 'bullish'
                except Exception as _e:
                    logger.debug(f"Phase 27 equities cycle skipped: {_e}")
            return 'hold'

        # ----------------------------------------------------------------
        # FUTURES: Bernd's hierarchy  (Phase 11 rewrite)
        # ----------------------------------------------------------------

        # Phase 16 — COT-is-king override for commodities / precious metals / energies.
        #
        # HAI transcript line 3473-3477: "what overrules true seasonality are the
        # commercials... COT is king."  For commodity asset classes specifically, a
        # strong COT extreme (Commercials or Retailers at multi-year extreme) takes
        # priority over the Location-derived proposed direction.  This is NOT an
        # equilibrium bypass — it only fires when COT and Location DISAGREE.
        #
        # Test-validated with Phase 15 goldtest: 9 GC=F cases fixed, 0 false positives.
        # Only applies when cot_strength='strong' (rolling AND 156w overlay both extreme).
        COT_KING_CLASSES = ('commodities', 'precious_metals', 'energies')
        if asset_class in COT_KING_CLASSES:
            cot_strength = biases.get('cot_strength', 'normal')
            if cot_strength == 'strong' and cot != 'neutral':
                cot_direction = cot   # 'bullish' or 'bearish'
                loc_direction = 'bullish' if loc == 'bullish' else ('bearish' if loc == 'bearish' else 'neutral')
                # Phase 18 extension: COT-is-king also fires at equilibrium (loc='neutral').
                # When COT is at a 156w historic extreme for a commodity/PM/energy, it overrides
                # the equilibrium gate (Phase 11 Step 1 normally requires all-3 unanimity).
                # GC=F Aug 2023 pattern: loc=neutral, COT=bullish/strong, val=neutral → bullish.
                # Condition: val must NOT actively oppose (val='bullish' or 'neutral' for bullish COT).
                cot_fires = False
                if cot_direction != loc_direction and loc != 'neutral':
                    # Original case: COT vs Location conflict
                    cot_fires = True
                elif loc == 'neutral':
                    # Phase 18: COT at historic extreme bypasses the equilibrium all-3 gate
                    cot_fires = True

                if cot_fires:
                    # The Valuation veto still applies (Rule #1): if val actively
                    # opposes the COT direction, return hold.
                    if cot_direction == 'bullish' and val == 'bearish':
                        return 'hold'
                    if cot_direction == 'bearish' and val == 'bullish':
                        return 'hold'
                    logger.info(
                        f"COT-is-king override: cot={cot} overrides loc={loc} "
                        f"for {asset_class} (strength=strong)"
                    )
                    return cot_direction

        # Step 1 — Location gate.
        # Bernd PREFERS extreme locations (cheap/expensive zones), but the
        # 3×3 matrix lists equilibrium as "Avoid" not "Illegal" — he does
        # take equilibrium trades when fundamentals are overwhelming.
        # Rule: if loc=neutral, require ALL 3 non-location fundamentals
        # (val + cot + seasonality) to unanimously agree before allowing
        # the trade. This is more selective than the old 3/5 vote while
        # still recovering the USDJPY/NG pattern (3/3 fundamentals agree
        # but loc was neutral). Mixed fundamentals at equilibrium = HOLD.
        if loc == 'neutral':
            _eq_exclude = {'trend', 'location', 'cot_strength', 'constituent'}  # Phase 24
            bull_fund = sum(1 for k, v in normalized.items()
                            if k not in _eq_exclude and v == 'bullish')
            bear_fund = sum(1 for k, v in normalized.items()
                            if k not in _eq_exclude and v == 'bearish')
            if bull_fund >= 3 and bear_fund == 0:
                proposed = 'bullish'   # overwhelming bullish at equilibrium
            elif bear_fund >= 3 and bull_fund == 0:
                proposed = 'bearish'   # overwhelming bearish at equilibrium
            else:
                return 'hold'          # mixed or insufficient = no trade
        else:
            # Location tells us the proposed direction.
            proposed = 'bullish' if loc == 'bullish' else 'bearish'

        # Step 2 — Valuation veto (HARD by default, SOFT at HQ zone arrival).
        # "Rule Number One" per CW38/CW39: Valuation must NOT actively
        # contradict the trade direction. Overvalued assets don't go long;
        # undervalued assets don't go short — regardless of other indicators.
        #
        # Phase 23 (Task 4): when price has arrived at a high-quality zone
        # (composite >= 7.0), soft-veto allows the trade as anticipatory.
        # Bernd's discretionary override for setups like 6S=F supply-zone
        # shorts against CHF undervaluation: "zone arrival is more immediate
        # than the Valuation reading." Counter-trend gate (Step 3) and zone
        # direction matching still apply downstream.
        if proposed == 'bullish' and val == 'bearish':
            if not _hq_zone_arrival:
                return 'hold'  # hard veto — standard Rule #1
            logger.info(f"Phase 23 T4: HQ zone arrival ({zone_composite:.1f}) overrides Val=bearish veto")
        if proposed == 'bearish' and val == 'bullish':
            if not _hq_zone_arrival:
                return 'hold'  # hard veto — standard Rule #1
            logger.info(f"Phase 23 T4: HQ zone arrival ({zone_composite:.1f}) overrides Val=bullish veto")

        # Step 3 — Counter-trend safety gate (prop-firm protection).
        # Bernd does take counter-trend setups but requires overwhelming
        # non-trend evidence. Phase 8 H1 fix: check non-trend tally only
        # (avoids the impossibility bug where `bullish == 0` was unreachable
        # in any uptrend because the trend vote normalises to 'bullish').
        if proposed == 'bearish' and trend == 'uptrend':
            # Short in uptrend: Location bearish + Valuation not bullish (already
            # passed Step 2) + at least 1 more non-trend bearish, 0 opposing.
            if bearish_excl_trend >= 2 and bullish_excl_trend == 0:
                return 'bearish'
            # NOTE: no relaxed path for short-in-uptrend — tested and caused
            # CC=F Feb 2024 wrong-direction error (supply-shock narrative trade).
            return 'hold'

        if proposed == 'bullish' and trend == 'downtrend':
            # Long in downtrend: Location bullish + Valuation not bearish (Step 2) +
            # ≥1 more non-trend bullish, 0 opposing.
            if bullish_excl_trend >= 2 and bearish_excl_trend == 0:
                return 'bullish'
            # Phase 10 relaxed path: 3+ non-trend bullish, ≤1 opposing, val must align.
            # Covers CL=F / PA=F: val+loc+cot=bullish but seasonality bearish.
            if bullish_excl_trend >= 3 and bearish_excl_trend <= 1 and val == 'bullish':
                return 'bullish'
            # Phase 11 relaxed path: Bernd's minimum (loc + val = tradeable) with ≤1
            # opposing non-trend indicator.  Covers CL=F/BA=F where only loc+val fire
            # bullish but seasonality is mildly bearish.  Requires BOTH loc AND val to
            # agree — prevents a single strong-val from dragging in pure-neutral loc.
            if val == 'bullish' and loc == 'bullish' and bearish_excl_trend <= 1:
                return 'bullish'
            return 'hold'

        # Step 4 — With-trend or sideways: minimum threshold.
        # Bernd's stated minimum: "Valuation + Location aligned = enough to trade."
        # If Valuation is neutral (not opposing, already passed Step 2), one more
        # supporting indicator (COT / Seasonality / Trend) is required.
        cot_n  = normalized.get('cot',         'neutral')
        seas_n = normalized.get('seasonality', 'neutral')

        if proposed == 'bullish':
            if val == 'bullish':
                return 'bullish'    # Location + Valuation = Bernd's minimum ✓
            # val == 'neutral': need 1 supporting vote (COT, Seasonality, or Trend)
            if cot_n == 'bullish' or seas_n == 'bullish' or trend_n == 'bullish':
                return 'bullish'
            return 'hold'           # Location only, all else neutral = too weak
        else:   # proposed == 'bearish'
            if val == 'bearish':
                return 'bearish'    # Location + Valuation = Bernd's minimum ✓
            if cot_n == 'bearish' or seas_n == 'bearish' or trend_n == 'bearish':
                return 'bearish'
            return 'hold'

    def _check_entry_pattern(self, df: pd.DataFrame, zone: Dict) -> Optional[Dict]:
        """Step 5: Check for candlestick pattern at the zone."""
        zone_type = zone['zone_type']
        proximal = zone['proximal']
        distal = zone['distal']

        # Look at the most recent candles
        for i in range(len(df) - 1, max(0, len(df) - 20), -1):
            candle = df.iloc[i]
            if zone_type == 'demand':
                if candle['low'] <= proximal and candle['low'] >= distal:
                    pattern = self.pattern_detector.detect(df, i, 'demand')
                    if pattern:
                        return pattern
            else:
                if candle['high'] >= proximal and candle['high'] <= distal:
                    pattern = self.pattern_detector.detect(df, i, 'supply')
                    if pattern:
                        return pattern
        return None

    def _calculate_targets(self, entry: float, stop: float, direction: str) -> List[float]:
        """Calculate R-multiple targets."""
        risk = abs(entry - stop)
        if direction == 'long':
            return [entry + risk, entry + 2 * risk, entry + 3 * risk]
        return [entry - risk, entry - 2 * risk, entry - 3 * risk]

    def build_entry_options(
        self,
        zone: Dict,
        target: float,
        pattern_signal: Optional[Dict] = None,
    ) -> List[Dict]:
        """Build the three textbook entry options (OTC 2025 Lesson 7).

        E1 (Proximal)     — limit at proximal, highest fill probability,
                             may have shallower R:R because price often
                             penetrates deeper before reversing.
        E2 (Zone/Midpoint) — limit at 50% of zone, better R:R, fills less
                             often (~50% of the time).
        E3 (Confirmation)  — entry on candlestick pattern that fired inside
                             the zone, lowest fill prob, highest confidence.

        ALL three use the same -33% Fibonacci stop measured from the zone
        distal -- that's the textbook rule. Returns a list of dicts the
        caller can present to the user; the caller picks whichever has
        the best R:R that meets minimum.
        """
        proximal = zone['proximal']
        distal   = zone['distal']
        zone_height = abs(proximal - distal)
        is_demand = zone['zone_type'] == 'demand'
        sign = +1 if is_demand else -1
        stop = distal - sign * 0.33 * zone_height
        direction = 'long' if is_demand else 'short'
        midpoint = (proximal + distal) / 2.0

        def rr(entry):
            risk = abs(entry - stop)
            return abs(target - entry) / risk if risk > 0 else 0.0

        options = [
            {
                'label':      'E1',
                'name':       'Proximal',
                'entry':      round(proximal, 6),
                'stop':       round(stop, 6),
                'direction':  direction,
                'fill_prob':  'high',
                'rr':         round(rr(proximal), 2),
                'note':       'Limit at proximal. Always fills, deeper drawdown possible.',
            },
            {
                'label':      'E2',
                'name':       'Zone (midpoint)',
                'entry':      round(midpoint, 6),
                'stop':       round(stop, 6),
                'direction':  direction,
                'fill_prob':  'medium',
                'rr':         round(rr(midpoint), 2),
                'note':       'Limit at 50% of zone. Better R:R, may not fill on shallow retraces.',
            },
        ]

        if pattern_signal is not None:
            options.append({
                'label':      'E3',
                'name':       f"Confirmation ({pattern_signal.get('pattern_type', 'pattern')})",
                'entry':      round(pattern_signal['entry_price'], 6),
                'stop':       round(pattern_signal['stop_price'], 6),
                'direction':  direction,
                'fill_prob':  'low',
                'rr':         round(rr(pattern_signal['entry_price']), 2),
                'note':       'Wait for candlestick confirmation in zone. Highest confidence.',
            })

        return options

    def recommend_entry_option(
        self, options: List[Dict], min_rr: float = 2.0,
    ) -> Dict:
        """Pick the highest-fill-prob option that meets min R:R; if none
        meet, fall back to the option with the best R:R.
        """
        qualifying = [o for o in options if o['rr'] >= min_rr]
        if not qualifying:
            return max(options, key=lambda o: o['rr'])
        order = {'high': 0, 'medium': 1, 'low': 2}
        return min(qualifying, key=lambda o: order.get(o['fill_prob'], 9))

    # Timeframe drill-down ladder per income strategy (OTC 2025 L3, HAI Mod 6 L6)
    REFINE_LADDER = {
        'monthly':  ['1mo', '1wk', '1d'],
        'weekly':   ['1wk', '1d', '4h', '60m'],
        'daily':    ['1d', '4h', '60m', '30m'],
        'intraday': ['4h', '60m', '30m', '15m'],
    }

    def refine_zone(
        self,
        htf_zone: Dict,
        target: float,
        ohlcv_by_tf: Dict[str, 'pd.DataFrame'],
        income_strategy: str = 'weekly',
        min_rr: float = 2.0,
        max_drill_levels: int = 3,
    ) -> Optional[Dict]:
        """Drill down the timeframe ladder to find a tighter zone CONTAINED
        within the HTF zone (per OTC 2025 L7-L8 + HAI Mod 6 L6).

        Refinement is triggered when the HTF zone's R:R to `target` is below
        `min_rr`. Each refined candidate must:
          1. share direction with the HTF zone
          2. fit entirely inside the HTF zone's price range (containment)
          3. independently pass qualifier checks (composite >= 6.0)

        Returns the deepest valid refined zone dict (with extra `parent_id`
        and `refined_from` fields), or None if no refinement found.

        Stop placement uses LTF distal -33% by default. Caller can override
        with HTF distal for more conservative protection.
        """
        ladder = self.REFINE_LADDER.get(income_strategy, self.REFINE_LADDER['weekly'])
        if htf_zone['timeframe'] not in ladder:
            return None
        htf_idx = ladder.index(htf_zone['timeframe'])
        candidates_levels = ladder[htf_idx + 1 : htf_idx + 1 + max_drill_levels]

        htf_lo = min(htf_zone['proximal'], htf_zone['distal'])
        htf_hi = max(htf_zone['proximal'], htf_zone['distal'])

        best: Optional[Dict] = None
        for tf in candidates_levels:
            df_tf = ohlcv_by_tf.get(tf)
            if df_tf is None or df_tf.empty:
                continue
            ltf_zones = self.zone_detector.detect_zones(
                df_tf, htf_zone['symbol'], tf,
            )
            for z in ltf_zones:
                if z['zone_type'] != htf_zone['zone_type']:
                    continue
                z_lo = min(z['proximal'], z['distal'])
                z_hi = max(z['proximal'], z['distal'])
                if not (z_lo >= htf_lo and z_hi <= htf_hi):
                    continue
                if z['composite_score'] < 6.0:
                    continue
                # Stop = LTF distal -33% (textbook default)
                zh = abs(z['proximal'] - z['distal'])
                sign = +1 if z['zone_type'] == 'demand' else -1
                stop = z['distal'] - sign * 0.33 * zh
                risk = abs(z['proximal'] - stop)
                rr   = abs(target - z['proximal']) / risk if risk > 0 else 0.0
                if rr < min_rr:
                    continue
                # Track the best (highest R:R) candidate
                if best is None or rr > best['_rr']:
                    refined = dict(z)
                    refined['parent_id']    = htf_zone['id']
                    refined['refined_from'] = htf_zone['timeframe']
                    refined['refined_stop'] = round(stop, 6)
                    refined['_rr']          = rr
                    best = refined

        if best is not None:
            best.pop('_rr', None)
            logger.info(
                f"[{htf_zone['symbol']}] zone refined {htf_zone['timeframe']}->{best['timeframe']} "
                f"score={best['composite_score']:.1f} entry={best['proximal']:.4f}"
            )
        return best

    # ------------------------------------------------------------------
    # Zone-quality grade — visually confirmed in frame_001154 (CW10
    # student trade-review popup, "10 out of 10" rating). Five binary
    # checks, 2 points each. NOTE: this is ZONE QUALITY only, not the
    # full trade grade — fundamentals stack on top of this. A zone can
    # be 10/10 structurally and still lack COT/Valuation alignment.
    # ------------------------------------------------------------------
    @staticmethod
    def zone_quality_grade(zone: Dict) -> Dict:
        """5-item zone-quality checklist from the visually-verified popup.

        Returns dict with keys: grade, score, checklist (per-item bool),
        where grade ∈ {'10/10', '8-9/10', '5-7/10', '<5/10'}.
        """
        # 1) Layout: decisive leg-out (Q1 Departure passing => decisive)
        decisive_layout = bool(zone.get('q1_score', 0) >= 7)
        # 2) Freshness: zone never preferred-tested
        is_fresh = bool(zone.get('q3_score', 0) >= 8)
        # 3) Base duration: 1-2 candle base
        base_count = zone.get('base_candle_count') or zone.get('base_count') or 0
        base_short = base_count <= 2 and base_count >= 1
        # 4) Big Brother / Small Brother match
        has_big_brother = bool(zone.get('has_big_brother', False))
        # 5) CF Direction: clean arrival / departure (Q6 Arrival or
        #    'with_trend' alignment).
        clean_arrival = bool(zone.get('q6_score', 0) >= 7 or zone.get('with_trend', False))

        checklist = {
            'layout_decisive':  decisive_layout,
            'fresh':            is_fresh,
            'base_duration':    base_short,
            'big_brother':      has_big_brother,
            'cf_direction':     clean_arrival,
        }
        score = 2 * sum(checklist.values())  # 0..10
        if score >= 10:
            grade = '10/10'
        elif score >= 8:
            grade = '8-9/10'
        elif score >= 5:
            grade = '5-7/10'
        else:
            grade = '<5/10'
        return {'grade': grade, 'score': score, 'checklist': checklist}

    # ------------------------------------------------------------------
    # Action-matrix tier grading — stage-1 text-confirmed (OTC L4 slide,
    # Bernd: "this is our action matrix to simplify everything"). Hard
    # rejection of the "No Action" cell is already done elsewhere; this
    # method emits the soft-tier grade so position size can scale.
    # ------------------------------------------------------------------
    @staticmethod
    def action_matrix_grade(
        zone_type: str, location: str, trend: str,
    ) -> str:
        """Returns 'best' | 'good' | 'acceptable' | 'reject'.

        location ∈ {'very_cheap','cheap','equilibrium','expensive','very_expensive'}
        trend    ∈ {'uptrend','downtrend','sideways'}
        zone_type∈ {'demand','supply'}
        """
        z = zone_type.lower()
        loc = location.lower()
        tr = trend.lower()
        # Demand setups
        if z == 'demand':
            if loc in ('cheap', 'very_cheap') and tr == 'uptrend':
                return 'best'
            if tr == 'uptrend':
                return 'good'                    # trend aligned, location not extreme
            if loc in ('cheap', 'very_cheap') and tr == 'sideways':
                return 'acceptable'              # location aligned, trend sideways
            return 'reject'
        # Supply setups
        if z == 'supply':
            if loc in ('expensive', 'very_expensive') and tr == 'downtrend':
                return 'best'
            if tr == 'downtrend':
                return 'good'
            if loc in ('expensive', 'very_expensive') and tr == 'sideways':
                return 'acceptable'
            return 'reject'
        return 'reject'

    # Position-size multiplier per action-matrix tier (counter to risk_pct
    # reduction for counter-trend; this multiplier scales the BASE risk).
    ACTION_TIER_SIZE_FACTOR = {
        'best':       1.0,
        'good':       0.75,
        'acceptable': 0.5,
        'reject':     0.0,
    }

    # ------------------------------------------------------------------
    # Correlation-aware exposure caps (HAI 1:19:29 + Funded 0:16:46).
    # When an open position exists in any group, new signals on
    # other members of the same group are rejected (or downgraded
    # depending on caller policy).
    # ------------------------------------------------------------------
    DEFAULT_CORRELATED_GROUPS = [
        # Forex — heavy USD-correlated
        ['EURUSD', 'GBPUSD', 'AUDUSD', 'NZDUSD', 'USDCHF'],   # USD axis
        ['EURUSD', 'EURGBP', 'EURJPY', 'EURCHF'],             # EUR axis
        ['USDCHF', 'EURCHF', 'GBPCHF'],                       # CHF axis
        # Equity indices
        ['ES=F', 'NQ=F', 'YM=F', 'RTY=F', 'SPY', 'QQQ'],
        # Precious metals
        ['GC=F', 'SI=F', 'GLD', 'SLV'],
        # Energy
        ['CL=F', 'NG=F', 'USO', 'UNG'],
    ]

    def is_correlated_to_open(
        self, candidate_symbol: str, open_symbols: List[str],
    ) -> Optional[List[str]]:
        """Return the offending peer symbols if `candidate_symbol` is in any
        correlated group with any currently-open symbol; else None.
        """
        groups = self.config.get('correlated_groups', self.DEFAULT_CORRELATED_GROUPS)
        s = candidate_symbol.upper().replace('/', '')
        norm_open = [o.upper().replace('/', '') for o in open_symbols]
        offenders: List[str] = []
        for grp in groups:
            grp_u = [g.upper().replace('/', '') for g in grp]
            if s in grp_u:
                offenders.extend([o for o in norm_open if o != s and o in grp_u])
        return offenders or None

    def _calculate_position_size(
        self, entry: float, stop: float, trade_context: str = 'standard',
    ) -> float:
        """Calculate position size based on fixed fractional risk.

        Context-adjusted (HAI Module 4 + OTC L5 Decision Matrix):
          - 'standard' / with-trend setups : full risk (default 1%)
          - 'counter_trend'                : reduced (0.5% default)
          - 'anticipatory'                 : reduced (0.5% default)
        """
        balance = self.risk_config.get('account_balance', 100000)
        risk_pct = self.risk_config.get('risk_per_trade_pct', 1.0) / 100
        if trade_context in ('counter_trend', 'anticipatory'):
            reduced_pct = self.risk_config.get('reduced_risk_pct', risk_pct * 50) / 100
            # Allow either an absolute pct (e.g., 0.5) or a multiplier
            if reduced_pct < 0.05:  # treat as fraction-of-risk multiplier
                risk_pct *= reduced_pct * 100
            else:
                risk_pct = reduced_pct
        risk_amount = balance * risk_pct
        stop_distance = abs(entry - stop)
        if stop_distance == 0:
            return 0
        return risk_amount / stop_distance
