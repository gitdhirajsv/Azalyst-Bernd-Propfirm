# Propfirm Trading Dashboard — Local Runner

Laptop-runnable copy of the Bernd Skorupinski Blueprint trading-system scanner with Fundingpips-style $100k paper account. **Same code, same rules, same indicators as the cloud-hosted `Azalyst Propfirm/` folder** — just a flat layout for `scan_markets.bat`.

If GitHub Actions / Pages aren't available or you want a private local copy, run from this folder.

## When to use which

| Folder | Runs on | Trigger | Where data lives | Dashboard reachable from |
|--------|---------|---------|-------------------|---------------------------|
| `Azalyst Propfirm/` | GitHub Actions cloud runner | hourly cron + manual | `<repo>/data/*.json` | `https://<user>.github.io/<repo>/` |
| `Propfirm Trading Dashboard/` | Your laptop | `scan_markets.bat` (manual) | flat in this folder | `http://127.0.0.1:8765` |

**Logic, rules, indicators are identical.** The `BP_*.py` files + `BP_config.yaml` + `send_discord.py` are byte-for-byte the same. Only the path conventions and the runner shell differ.

## Quick start

```bat
1. (Optional) edit scan_markets.bat to add your Discord webhook:
       set DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
       set DISCORD_USER_ID=63959528194052118
2. Double-click ONE of:
       scan_daily.bat     -> daily strategy   (HTF=1d,  LTF=60m, log: scanner_daily.log)
       scan_weekly.bat    -> weekly strategy  (HTF=1wk, LTF=1d,  log: scanner_weekly.log)
       scan_monthly.bat   -> monthly strategy (HTF=1mo, LTF=1wk, log: scanner_monthly.log)
       scan_markets.bat   -> defaults to daily; takes optional arg: scan_markets.bat weekly
3. Browser opens http://127.0.0.1:8765 with the dashboard
4. Re-run anytime to do another scan; positions persist via paper_trader_state.json
```

The bat now auto-clears `__pycache__` before each run, so any edits to `BP_*.py` files
are guaranteed to be picked up on the next scan (no stale-bytecode confusion).

First run installs Python deps (`yfinance`, `pandas`, `numpy`, `pyyaml`, `requests`) automatically. Subsequent runs skip that step thanks to the `.deps_installed` marker file.

## Audit harness — `goldtest/`

A gold-standard test harness replays Bernd Skorupinski's published trade calls (extracted from monthly roadmaps + 2023 weekly outlooks + Funded Trader sessions, **160 cases**) against the engine and produces a side-by-side diff.

```bat
python goldtest/run_goldtest.py                  # run all 160 cases
python goldtest/run_goldtest.py --case 5         # run just case #5
python goldtest/run_goldtest.py --asset equities # filter by asset class
```

Then open `goldtest/gold_diff.html` to see the results in a colour-coded table.

Two metrics are reported:

- **Full-signal match**: the system actually emitted a trade signal AND the direction agrees with Bernd. Constrained by zone-arrival + entry-pattern gates.
- **Bias-only match**: the system's directional analysis agrees with Bernd, ignoring whether a real trade would have triggered. This decouples the analytical brain from the trade-execution gates.

Bernd's monthly-roadmap calls are typically directional theses ("buy AAPL because undervalued"), not "execute right now". The full-signal metric will under-count agreement; the bias-only metric is the more representative one.

**Critical metric for prop-firm safety: full-signal false positives must stay at 0.** A false positive is when Bernd said "no trade" but the system fires a directional signal — that's a real trade against Bernd's call, with prop-firm-account-blowing potential. The harness watches this number explicitly.

To diagnose a single divergence:
```bat
python goldtest/diagnose_one.py AAPL 2024-01-02 monthly
```
prints all 5 indicator values + zone detection + bias decision flow for that exact setup.

## Files in this folder

| File | Purpose |
|------|---------|
| `scan_markets.bat` | Windows launcher — does the install + scan + Discord post |
| `run_scanner.py` | Orchestrator — fetches data, scans, runs paper trader, serves dashboard |
| `BP_config.yaml` | Watchlist (77 Fundingpips symbols) + prop_firm rules + qualifier weights + per-strategy timeframes |
| `BP_zone_detector.py` | Detects supply/demand zones, scores 6 qualifiers + LOL bonus, BB/SB containment check |
| `BP_rules_engine.py` | 7-step decision pipeline + bias synthesis + cross-asset gates |
| `BP_indicators.py` | COT Index, COT Report, Valuation, Seasonality calculators |
| `BP_patterns.py` | 6 candlestick patterns (Hammer, Engulfing, Shooting Star, etc.) |
| `BP_paper_trader.py` | $100k Fundingpips paper account with $5k/$10k guardrails |
| `BP_roadmap.py` | Presidential cycle + sannial decennial monthly roadmap |
| `BP_calendar.py` | US holiday + CPI/NFP/FOMC blackout windows |
| `BP_data_fetcher.py` | yfinance wrapper + CFTC public-API client |
| `BP_main.py` | Alternate entrypoint for one-off symbol analysis |
| `send_discord.py` | Optional Discord webhook poster — same format as cloud version |
| `dashboard.html` | Local dashboard with Trading Objectives panel |
| `scan_results.json` | Latest scan output |
| `paper_trader_state.json` | Persistent paper-account state (positions, trade history, P&L) |
| `scan_history.json` | Per-scan summaries (long-term log) |

## Fundingpips rules (configured in `BP_config.yaml`)

```yaml
prop_firm:
  enabled: true
  account_size: 100000.0
  max_daily_loss_usd: 5000.0     # 5%
  max_total_loss_usd: 10000.0    # 10%
  daily_reset_hour_utc: 22       # 17:00 NY = 22:00 UTC
```

The paper trader **blocks new trades at submit time** if:
- today's open risk + this trade's risk would exceed $5,000, OR
- total drawdown is already $10,000 (account latched as `breached`), OR
- 3 positions already open

## Watchlist

77 Fundingpips-tradable symbols (forex majors + crosses + exotics, metals, energies, 13 global indices, bonds, 11 crypto, 8 mega-caps for NQ basket). Edit `BP_config.yaml > watchlist:` to add/remove.

## Strategies

Each non-crypto symbol scanned on **both** weekly (HTF=1wk, LTF=1d) and daily (HTF=1d, LTF=60m) passes — captures big swings + intraday-to-day setups. Crypto pinned to daily-only (weekly bars too volatile per audit).

## Discord notifications

Optional. Set in `scan_markets.bat`:
```bat
set DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
set DISCORD_USER_ID=63959528194052118
```

Discord message fires after every scan with the full Trading Objectives + open positions + track record. **@-pings only on NEW SIGNALS** (other updates are silent).

---

## ARCHITECTURE — How a trade decision is made

This section documents every gate the system passes through, with citations to the methodology spec (so a Bernd-trained trader can verify it and so a future AI agent can trace the decision logic).

### Two-stage signal pipeline (CRITICAL to understand)

The engine has two distinct stages and the audit harness measures both:

- **Stage 1 — Directional bias**: `_analyze_htf` + `_analyze_fundamentals` + `_bias_consensus` produce a directional thesis (bullish / bearish / hold). This is the "analytical brain" — it's what Bernd's monthly-roadmap calls express ("buy AAPL because undervalued").
- **Stage 2 — Trade trigger**: bias + zone direction match + decision matrix + zone-arrival check + entry-pattern check → real trade signal. This is execution timing.

Bernd's monthly-roadmap commentary is typically Stage 1 thesis, NOT "execute right now". The system correctly waits at Stage 2 for price to arrive at a zone (rule #4: never anticipate). On the gold-standard test harness (`goldtest/run_goldtest.py`), `bias_match` measures Stage 2 and `bias_only_match` measures Stage 1 — both are reported, and `Full-signal false positives` is the prop-firm-safety metric (must stay at 0).

The methodology spec files (canonical rule book) live in the parent project at `D:\Azalyst Bernd Skorupinski\methodology\` (or in `Azalyst Propfirm/methodology/` for the cloud version). Files: `01_zone_detection.md`, `02_zone_qualifiers.md`, `03_fundamentals.md`, `04_entry_triggers.md`, `05_trade_management.md`, `06_seven_step_process.md`, `07_asset_class_cheatsheet.md`.

### Data sources (per scan)

| Source | Provides | Used for | Spec |
|--------|----------|----------|------|
| Yahoo Finance (`yfinance`) | OHLCV candles per symbol, multiple timeframes | All TA: zone detection, candle classification, trend pivots, location Fib | — |
| CFTC public dataset | Weekly Commitment of Traders (commercials, non-commercials, retailers; longs+shorts) | COT Index + COT Report | `03_fundamentals.md` — COT |
| yfinance reference symbols | DXY, ZN, ZB, GC, ^TNX (daily OHLCV) | Valuation rate-of-change | `03_fundamentals.md` — Valuation §"Settings by Asset Class" |
| yfinance long history | 15y daily history per symbol | Seasonality 5y/10y/15y backdrop | `03_fundamentals.md` — Seasonality |
| `BP_roadmap.py` static tables | Presidential cycle, sannial decennial bias | Monthly Roadmap timing overlay | `03_fundamentals.md` — Roadmap |
| `BP_calendar.py` | US Federal holidays, CPI/NFP/FOMC dates | Two-session gate, news suppression | `06_seven_step_process.md` — Calendar Gates |

### The 7-step pipeline (per symbol, per strategy pass)

```
                   ┌─────────────────────────────────────────────────┐
                   │  ENTRY POINT: scan_symbol(sym, strategy, htf, ltf) │
                   └──────────────┬──────────────────────────────────┘
                                  ▼
┌─── STEP 1: MARKET SELECTION ───┐
│   Symbol + asset_class read    │   methodology/06 §"STEP 1"
│   from BP_config.yaml watchlist │
└──────────────┬─────────────────┘
               ▼
┌─── STEP 2: HTF TECHNICAL ANALYSIS ─────────────────────────────────────┐
│  (a) Detect HTF zones (provisional, no trend yet)                       │
│  (b) Compute Location % via Fib 33/66 across HTF zones                  │
│      ≤33% → bullish · 33-67% → equilibrium · ≥67% → bearish             │
│  (c) Compute Trend via ZigZag % pivots (3 swing high + 3 swing low,     │
│      RIGHT-to-LEFT). Phase 6: pivot-break flips trend label.            │
│  (d) Re-detect HTF zones WITH trend context (so Q5/Q6 fire only on      │
│      counter-trend setups).                                             │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
┌─── STEP 3: FUNDAMENTAL CONFIRMATION ──────────────────────────────────┐
│  (a) COT Index per asset-class lookback (26w / 52w) + 156w extreme    │
│      Group focus per class:                                            │
│        Forex/Equities    : Non-Commercials divergence                  │
│        Commodities/Energ.: Commercials WITH (≥80 bullish, ≤20 bear)    │
│        Precious Metals   : Commercials WITH (Phase 17 correction —     │
│                            was Retailers CONTRARIAN; cheatsheet +      │
│                            Ch.107 confirm Commercials ① primary)       │
│        Natural Gas (NG=F): Retailers CONTRARIAN (historical extremes)  │
│        Soft Tropical (CC/KC/SB/OJ): Non-Commercials 26w               │
│        Grains/Cotton (ZC/ZW/ZS/CT): Commercials 52w (Phase 14 fix)    │
│      156w approaching-extreme trigger (Phase 18): when 26w ≥60 bull/  │
│        ≤35 bear AND 156w already at extreme → fire bias. COT-king      │
│        classes only (PM/commodities/energies). Not forex/eq-indices.   │
│  (b) Cross-category COT (smart-vs-dumb confluence boosts to 'strong'; │
│      commercial regime-flip detector ≥40pt in ≤3 weeks — Phase 6)     │
│  (c) Forex: opposing-currency DXY cross-check                          │
│  (d) Valuation per-asset references (Phase 4+5 P1 corrected):          │
│        Forex            : DXY only                                     │
│        Equity Indices   : SKIP Valuation (Phase 15 — DXY/ZN/ZB        │
│                           comparison creates false bearish veto in      │
│                           bull mkts; loc+cot+seas drive bias instead)  │
│        Equities (stocks): ZN + ZB + GC (Phase 16 — DXY removed;        │
│                           OTC L3: "unselect reference symbol 3/dollar")│
│        Commodities      : DXY + Gold + ZB                              │
│        Precious Metals  : DXY + Gold + ZB (default)                    │
│        Platinum         : DXY + Gold ONLY (no Bonds)                   │
│        Energies         : DXY + Gold + ZB                              │
│        Crypto           : DXY only                                     │
│      ROC: 10 across ALL asset classes (Pine Script default,            │
│           Phase 7 correction; "Dual-ROC for Equities" is an OVERLAY    │
│           practice on the chart, NOT a parameter override)             │
│      REFS FETCHED AT HTF interval (Phase 7 critical fix — was at LTF   │
│           which made date intersection too small for ROC, indicator    │
│           returned NaN for every symbol)                               │
│      Bias = read 3 INDIVIDUAL lines per Pine Script source, NOT a      │
│           composite average (Phase 7 fix). 4-state per line:           │
│           ≥+75 strong bearish · ≥+10 mild bearish ·                    │
│           ≤-10 mild bullish · ≤-75 strong bullish · else neutral       │
│      Aggregate: all 3 agree → that direction (strong if any extreme); │
│           2-of-3 with 0 opposing → that direction (mild); else neutral │
│  (e) Seasonality multi-lookback 5y/10y/15y:                            │
│      All three must AGREE. Slope must actively TURN (not just be       │
│      positive). Strength tier: strong/moderate/none.                   │
│  (f) Monthly Roadmap (Presidential × Sannial cycle)                    │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
┌─── BIAS SYNTHESIS RULE (HARD GATES) ──────────────────────────────────┐
│  (1) Valuation HARD PREREQUISITE GATE ("Rule Number One"):            │
│      strongly opposing direction → VETO                                │
│  (2) Trend vocabulary normalised (Phase 7 fix — was silently ignored):│
│      uptrend → bullish · downtrend → bearish · sideways → neutral     │
│  (3) Asset-class branch (Phase 7):                                    │
│      asset_class == 'equities' (individual stocks):                   │
│        - No CFTC COT data → COT vote unavailable                      │
│        - Valuation-driven path: long when Val=bullish AND             │
│          trend != downtrend; NEVER short individual stocks            │
│          (Bernd shorts indices via futures, not single names)         │
│  (4) BERND'S HIERARCHY (Phase 11 — replaces old 3/5 equal vote):     │
│      Step 1 — Location gate:                                          │
│        loc=neutral → hold (unless val+cot+seas ALL 3 agree)          │
│        loc=bullish/bearish → proposed direction set                   │
│      Step 2 — Valuation veto:                                         │
│        val strongly opposes proposed → hold (Rule #1)                 │
│      Step 3 — Minimum threshold:                                      │
│        loc+val both aligned → TRADEABLE (Bernd's stated minimum)     │
│        loc aligned + val neutral + 1 of (cot/seas/trend) → TRADEABLE │
│        loc only, all else neutral → hold                              │
│      Step 4 — Counter-trend safety gate (Phase 8 H1):                │
│        bearish in uptrend / bullish in downtrend:                    │
│        requires ≥2 non-trend same direction + 0 opposing             │
│      Reason: fighting the prevailing trend is the fastest way to blow │
│      a $5k daily-loss limit. Counter-trend setups need extreme        │
│      conviction.                                                      │
│  (7) Class-conditional retailer veto:                                 │
│      PMs: hard veto if retailers same side as proposed trade          │
│      others: reduce size 25-50%                                       │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
┌─── STEP 4: LTF ZONE DETECTION ────────────────────────────────────────┐
│  (a) Detect LTF zones (DBR, RBR, RBD, DBD)                             │
│  (b) Score 6 qualifiers + LOL bonus (each 0-10):                       │
│       Q1 Departure (30%) — leg-out body ≥70% else INVALID              │
│       Q2 Base Duration (10%) — 1-2 best, 7+ INVALID                    │
│       Q3 Freshness (15%) — wider/preferred split                       │
│            >25% PENETRATION → Q3=0, INVALIDATED (Phase 6 P1)           │
│       Q4 Originality (15%) — original=10, non-original=5, FLIP=12      │
│       Q5 Profit Margin (10%) — counter-trend gate; skipped on trend    │
│       Q6 Arrival (10%) — counter-trend gate; skipped on trend          │
│       LOL (10%, max +5) — HTF+LTF zone stacking                        │
│       Composite weighted, ≥4.0 to keep                                 │
│  (c) BB/SB containment filter (Big Brother / Small Brother):           │
│      LTF zone must fit INSIDE same-direction HTF zone.                 │
│      CONTAINMENT, NOT multi-TF stacking (Phase 6 P1 clarification).    │
│  (d) Speed-bump detection (opposing zones in path)                     │
│  (e) Rank by composite, take BEST zone                                 │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
┌─── DECISION MATRIX (Phase 7 — softened from hard-reject) ─────────────┐
│  Zone direction must MATCH bias consensus (still hard)                 │
│  demand@expensive:                                                     │
│    if Valuation=bullish → ALLOW as anticipatory reversal               │
│      (reduced 0.5% risk; trade_context='counter_trend')                │
│    else → NO ACTION (Val doesn't support the counter-trend thesis)     │
│  supply@cheap:                                                         │
│    if Valuation=bearish → ALLOW as anticipatory reversal               │
│    else → NO ACTION                                                    │
│  equilibrium + sideways trend → NO ACTION (genuinely no edge)          │
│  (Phase 6 P2: equilibrium permits LTF level-to-level swing trades      │
│   with reduced size + T2 cap)                                          │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
┌─── EQUITY-INDEX SHORT CROSS-ASSET GATE (Phase 6 P1) ──────────────────┐
│  if asset_class=='equities' AND direction=='short':                    │
│    REQUIRE BOTH:                                                       │
│      (a) retailers extreme bullish (COT)                              │
│      (b) bond ROC actively turning negative                            │
│    fail either → VETO                                                  │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
┌─── STEP 5: ENTRY TRIGGER ─────────────────────────────────────────────┐
│  Candlestick pattern at zone (one of 6):                               │
│    Hammer / Bullish Engulfing (demand)                                 │
│    Shooting Star / Hanging Man / Bearish Engulfing (supply)            │
│    Head & Shoulders / Inverse H&S                                      │
│  Pattern requires at_swing_low/high (trend-context guard).             │
│  No pattern → only allow if current candle is INSIDE the zone.         │
│  Otherwise WAIT (rule #4: never anticipate).                           │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
┌─── STEP 6: TRADE MANAGEMENT ──────────────────────────────────────────┐
│  Entry options (E1-E4) — recommend best R:R that fills:                │
│    E1 proximal limit / E2 midpoint / E3a LTF zone / E3b stop-buy /     │
│    E3c throwback strap / E4 trendline break                            │
│  Stop:                                                                 │
│    Mode 1 (LTF/pattern): distal -33% Fib                               │
│    Mode 2 (HTF weekly income): distal-only, no -33% extension          │
│    Liquidity-aware override: above ATH if shorting near ATH (Phase 6)  │
│  Targets: T1=1R, T2=2R, T3=3R + price-action zones (Phase 6)           │
│  Position size:                                                        │
│    risk_amount = 1% × $100k = $1,000 (standard)                        │
│    risk_amount = 0.5% = $500 (counter-trend / anticipatory)            │
│    equity basket: 3% total across NQ/ES/YM aligned                     │
│  R:R minimum 1:2; if entry yields <1:2 → slide entry toward midpoint   │
│    (capped at E2)                                                      │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
┌─── STEP 7: ROADMAP + CALENDAR FILTERS ────────────────────────────────┐
│  Monthly roadmap match (presidential + sannial)                        │
│  US Federal holiday: 2-session gate                                    │
│  Thanksgiving/Christmas: COT freshness suppressed                      │
│  CPI/NFP/FOMC same day: reduce size to 0.5% or wait                    │
│  Counter-roadmap: warning, not auto-rejected                           │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
┌─── PROP-FIRM GUARDRAIL (LAST GATE) ───────────────────────────────────┐
│  PaperTrader.submit_signal() final checks:                             │
│    today's loss + this trade's risk > $5,000     → REJECT              │
│    total loss already ≥ $10,000 (account_blown)  → REJECT              │
│    open positions ≥ 3                            → REJECT              │
│    breach detected                               → REJECT              │
│  All pass → open paper trade with computed entry/stop/targets          │
└──────────────┬──────────────────────────────────────────────────────────┘
               ▼
       ┌──────────────────────┐
       │  SIGNAL FIRES        │
       │  → Discord (with @ping)
       │  → scan_results.json │
       │  → dashboard         │
       └──────────────────────┘
```

### After a signal fires (every subsequent scan tick)

```
PaperTrader.update_positions() runs:

  For each open position:
    if hit half-T1 (default) or T1: move stop to BREAKEVEN
    if hit T2 (2R):                 close 50%, begin trailing
    if hit T3 (3R):                 close remainder (with-trend)
                                     full close (counter-trend HARD CEILING)
    if stop hit:                    close at stop
    apply zone-based trailing where possible; fallback 1R-step
    daily reset rolls today_starting_equity at 22:00 UTC
```

### Rule-by-rule verification table

| Rule from Bernd's videos | Code location | Status |
|--------------------------|---------------|--------|
| Indecisive base (body ≤ 50%) | `BP_zone_detector._is_indecisive` | ✅ |
| Explosive leg-out (body ≥ 70%) OR gap | `_find_leg_out` (Phase 6 gap) | ✅ |
| 4 formations (DBR, RBR, RBD, DBD) + flip = 12 | `_score_zone` originality | ✅ |
| Proximal at body extremes / distal at wick extremes | `_score_zone` | ✅ |
| 6 qualifiers + LOL composite weighted | `_score_zone` qualifier_weights | ✅ |
| Q1 hard-fail if leg-out indecisive | `_find_leg_out` returns None | ✅ |
| Q3 25% penetration HARD invalidates | `_is_zone_invalidated_25pct` | ✅ Phase 6 |
| BB/SB containment NOT stacking | `has_big_brother_coverage` | ✅ Phase 6 |
| Speed-bump detection | `detect_speed_bumps` | ✅ |
| ZigZag % trend (R→L pivots) | `_zigzag_pivots` | ✅ |
| Pivot-break flips trend | `detect_trend_reversal` | ✅ Phase 6 |
| Location Fib 33/66 across HTF zones | `_analyze_htf` | ✅ |
| COT 26w / 52w by asset class | `COT_LOOKBACK_BY_CLASS` | ✅ |
| 156w extreme overlay | `COTIndex.extreme_lookback` | ✅ |
| 156w approaching-extreme trigger (Phase 18): 26w ≥60 AND 156w at extreme → bias | `get_bias` secondary trigger | ✅ Phase 18 |
| COT-is-king at equilibrium (Phase 18): strong COT overrides all-3 unanimity gate | `_bias_consensus` COT-king block | ✅ Phase 18 |
| Commercials (non-contrarian) for PMs; Retailers contrarian for NG only | `get_bias` asset-class branch | ✅ Phase 17 |
| Forex DXY opposing-currency cross-check | `_analyze_fundamentals` | ✅ |
| Valuation refs per asset class | `VALUATION_REFS` map | ✅ Phase 4+5 P1 corrected |
| Valuation as HARD prerequisite gate | `valuation_passes_gate` | ✅ Phase 4+5 |
| Dual-ROC for equities | `cycle_per_symbol` config | ✅ |
| Seasonality 5y/10y/15y must agree | `Seasonality.calculate_multi` | ✅ |
| Slope must actively TURN | `seasonality_bias` w/ prior_slopes | ✅ |
| Bias hierarchy (Phase 11): loc gate → val veto → loc+val minimum | `_bias_consensus` | ✅ |
| Counter-trend: ≥2 non-trend agree, 0 oppose (Phase 8 H1 fix) | `_bias_consensus` | ✅ |
| -33% Fib stop (LTF) / distal-only (HTF weekly) | two-mode in `build_entry_options` | ✅ |
| Half-target breakeven | `breakeven_at_half_target` | ✅ |
| 2R partial 50%, 3R close-or-trail | `update_positions` | ✅ |
| Counter-trend hard close at T2 | direction-aware exit | ✅ Phase 4+5 |
| Equity basket 3% aggregate | basket-mode sizing | ✅ |
| Bond rollover + retailer extreme for equity shorts | `_equity_index_short_cross_asset_gate` | ✅ Phase 6 |
| Set-and-forget (no stop touch <1R) | `update_positions` early-tighten guard | ✅ |
| Holiday two-session gate | `BP_calendar.py` | ✅ |
| Mega-cap basket scan for NQ bias | spec'd, ready to wire | 🟡 |
| Stock dual-TF Valuation gate | spec'd, ready to wire | 🟡 |
| Liquidity-aware stop above ATH | helper documented, not auto-applied | 🟡 |
| Multi-bar pattern repetition | helper documented, not auto-applied | 🟡 |
| Bullish-Seasonality blocks Val-overvalued shorts | spec'd, not yet wired | 🟡 |
| Wait-for-N-COT-updates (defer pre-extreme) | spec'd, not yet wired | 🟡 |
| Commercial regime-flip detector | spec'd, not yet wired | 🟡 |

### What's specifically NOT enforced (P3 deferred — manual judgment)

These are visual/qualitative rules from the videos where Bernd doesn't quantify a deterministic threshold:

- Wick-over-wick big-brother substitute (no quantified threshold)
- Per-metal ranking (Pt > Au ≈ Ag > Pd) — visual ordering only
- Gold net-long zero-line crossing — visual rule, no number
- Retail contrarian threshold for non-PM classes — qualitative
- Volume confirmation for energy zones — "no volume = not institutional" but no threshold
- Adjusted vs unadjusted chart preference — directional, no rule
- Trap-area / institutional trap zones at HTF highs — qualitative
- Position-size splitting across E1+E2+E3 — visual demo, no exact ratio

These remain manual chart-reading decisions on top of the automated signal.

### Audit traceability

Every audit-derived rule has a `Phase 4+5` or `Phase 6` marker in the code/spec citing the corpus chapter where Bernd states it. Run this from the parent project:

```bash
grep -rn "Phase 4+5\|Phase 6\|Phase 11" "../methodology/"
```

Full audit reports live in `../_audit/skill_audit/`:
- `FINAL_REPORT.md` — 156-PDF audit (HAI + OTC + FT 2023)
- `phase6/FINDINGS.md` — 21-chapter audit (2024 sessions)
- `GAPS_MASTER_LOG.md` — all P1/P2/P3 items with priorities

---

## Sync between this folder and `Azalyst Propfirm/`

These 11 files are kept byte-identical with the cloud version:

```
BP_calendar.py    BP_data_fetcher.py  BP_indicators.py    BP_main.py
BP_paper_trader.py  BP_patterns.py    BP_roadmap.py       BP_rules_engine.py
BP_zone_detector.py  BP_config.yaml   send_discord.py
```

**Single codebase**: `Propfirm Trading Dashboard/` is the only Python location. The `Azalyst Propfirm/scanner/` path no longer exists — all edits are made here only.

## Methodology source of truth

The methodology spec files in the parent project's `methodology/` folder are the canonical rule book. The Python code here is the **executable interpretation** of that spec. If you find a deviation, update both — the spec wins on disputes.
