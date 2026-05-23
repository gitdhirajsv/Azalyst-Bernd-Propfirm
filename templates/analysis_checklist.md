# Pre-Trade Analysis Checklist — 27 Points

> **Instructions**: Run through this checklist for EVERY trade before execution. All MUST PASS items must be YES. Any single MUST PASS = NO means DO NOT TRADE.

---

## SECTION 0: CALENDAR & MARKET GATES (Pre-Step)

| # | Check | Answer | MUST PASS? |
|---|-------|--------|------------|
| 0a | Is today a US holiday or within 2 sessions of one? | YES / NO | If YES → SKIP or reduce to 0.5% |
| 0b | Is this Thanksgiving or Christmas week (stale COT)? | YES / NO | If YES → SKIP new entries |
| 0c | Is there a high-impact event (CPI/NFP/FOMC) today? | YES / NO | If YES → SKIP or wait for post-announcement zone |
| 0d | [For equity stocks only] Is the parent index at a valid zone? | YES / NO | **YES** (required before analysing stock) |
| 0e | [For Nasdaq/tech stocks] Have both AAPL and MSFT passed qualifier scans? | YES / NO | **YES** (required for tech/Nasdaq stocks) |

## SECTION A: HTF ANALYSIS (Steps 1-2)

| # | Check | Answer | MUST PASS? |
|---|-------|--------|------------|
| 1 | Is the instrument on your watchlist with available COT data? | YES / NO | YES |
| 2 | What is the HTF location? (Fib % from demand distal to supply distal) | ___% | — |
| 3 | Is price AWAY from equilibrium (not 40-60% range)? | YES / NO | YES |
| 4 | What is the HTF trend? (ZigZag + 6-pivot method) | Up / Down / Sideways | — |
| 5 | Do location + trend agree on direction? | YES / NO / N/A (sideways) | — |

## SECTION B: VALUATION GATE (Step 3 — Rule #1: Check FIRST)

| # | Check | Answer | MUST PASS? |
|---|-------|--------|------------|
| 6 | Valuation reading? (ROC-based, using correct references per asset class) | ___ (+/- 100 scale) | — |
| 7 | Valuation 4-state? | Strong Bull / Mild Bull / Neutral / Mild Bear / Strong Bear | — |
| 8 | **Does Valuation STRONGLY oppose the proposed trade direction?** | YES / NO | If YES → **VETO TRADE (Rule #1)** |
| 9 | If mild opposition: is COT at 156-week extreme to override? | YES / NO / N/A | If mild opp + no COT extreme → reduce size 50% |

## SECTION C: COT + SEASONALITY (Step 3)

| # | Check | Answer | MUST PASS? |
|---|-------|--------|------------|
| 10 | COT Index level? Which group? What lookback? | ___% [Comm 52w / NonComm 26w / Retail] | — |
| 11 | Is this a fresh extreme (just crossed 80/20 this week)? | YES / NO | — (higher conviction if YES) |
| 12 | COT bias direction? | Bullish / Bearish / Neutral | — |
| 13 | [PMs only] Are Retailers on same side as proposed trade (veto)? | YES / NO | If YES → **VETO for PMs; reduce size for others** |
| 14 | Seasonality slope actively TURNING direction? (not just sustained flat) | YES / NO | — (NEUTRAL if not turning) |
| 15 | **CONSENSUS: 3/5+ biases aligned?** (4/5 for counter-trend) | YES / NO | **YES** (or soft-path: Val + 1 supporter, 0 opposing) |
| 15a | **Trend safety**: am I about to short in an uptrend or long in a downtrend? | YES / NO | If YES → require **4+** same-direction with **0 opposing** — otherwise SKIP |
| 15b | **Equities branch**: is this an individual stock (AAPL/MSFT/GOOG/META/AMZN/NFLX/TSLA/NVDA)? | YES / NO | If YES → Valuation-driven path: long only, never short individual stocks |

Bias tally: Location [_] + Trend [_] + COT [_] + Valuation [_] + Seasonality [_] = __/5
- `uptrend` → bullish vote · `downtrend` → bearish vote · `sideways` → neutral
- For individual stocks, COT vote is automatically neutral (no CFTC report); use Valuation-driven path instead of strict 3/5

## SECTION D: ZONE QUALITY (Step 4)

| # | Check | Answer | MUST PASS? |
|---|-------|--------|------------|
| 16 | Zone type and formation? | Demand/Supply — DBR/RBR/RBD/DBD | — |
| 17 | **Departure: Is leg-out explosive (body >= 70%)?** | YES / NO | **YES** |
| 18 | **Base duration: 6 or fewer candles?** | YES / NO | **YES** |
| 19 | Zone composite score? | ___/10 (minimum 4.0) | — |
| 20 | Does zone direction match consensus? | YES / NO | **YES** |
| 21 | Is zone nested in HTF zone (Big Brother)? | YES / NO | — |
| 22 | Are there blocking speed bumps in path to zone? | YES / NO | — (flag for review if YES) |
| 23 | [US index trades] Are there unfilled daily gaps in path? | YES / NO | — (flag as speed bump if YES) |

## SECTION E: EXECUTION (Steps 5-6)

| # | Check | Answer | MUST PASS? |
|---|-------|--------|------------|
| 24 | Entry method? | E1 / E2 / E3a / E3b / E3c / E4 | — |
| 25 | Stop mode? | LTF pattern (-33% Fib) OR HTF weekly (distal only) | **YES — must decide** |
| 26 | Risk % selected? | 1% (standard) / 0.5% (counter-trend/anticipatory/calendar/mild Valuation opposition) | YES |
| 27 | **R:R ratio >= 1:2?** | YES / NO (___:___) | **YES** |

---

## SUMMARY GATES

| Gate | Status |
|------|--------|
| Calendar clear (#0a-0c) | PASS / SKIP |
| Parent index / AAPL+MSFT gate (#0d-0e) [stocks only] | PASS / FAIL |
| Away from equilibrium (#3) | PASS / FAIL |
| **Valuation hard gate (#8) — Rule #1** | PASS / **VETO** |
| Consensus 3/5 (#15) | PASS / FAIL |
| Trend safety gate (#15a) | PASS / FAIL |
| Equities Valuation-driven path (#15b) [stocks only] | PASS / SKIP |
| Departure explosive (#17) | PASS / FAIL |
| Base <= 6 candles (#18) | PASS / FAIL |
| Zone matches consensus (#20) | PASS / FAIL |
| Stop mode selected (#25) | LTF / HTF |
| R:R >= 1:2 (#27) | PASS / FAIL |

**ALL gates PASS?** → EXECUTE trade with correct risk %
**ANY gate FAIL?** → DO NOT TRADE. Move to next instrument.

---

## QUICK MENTAL CHECKLIST (Memorize This)

Before every trade, ask:
1. **VALUATION?** Does Valuation allow this direction? (Rule #1 — check first)
2. **WHERE** am I? (Cheap or expensive on HTF? Not at equilibrium?)
3. **WHAT** do the fundamentals say? (3/5 aligned? COT fresh extreme?)
4. **HOW** good is this zone? (Explosive departure? Fresh? Score? Speed bumps?)
5. **STOP MODE?** LTF entry (-33% Fib) or HTF weekly (distal only)?
6. **IS** the R:R worth it? (>= 1:2?)
7. **CALENDAR?** Holiday, event, or stale-COT week?

If all seven = YES/PASS → Trade. If any = NO/FAIL → Skip.
