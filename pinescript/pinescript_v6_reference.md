# Pine Script v6 Compliance Reference

> **Purpose**: Rules and patterns for writing Pine Script v6 code that passes TradingView's compiler. Use this when building or correcting indicators and strategies.

---

## VERSION DECLARATION

Always start with:
```pinescript
//@version=6
indicator("Name", overlay=true)  // or strategy("Name", ...)
```

---

## CRITICAL v6 CHANGES (vs v4/v5)

### 1. Data Requests
```pinescript
// v4 (DEPRECATED — will NOT compile):
security(syminfo.tickerid, "W", close)

// v5:
request.security(syminfo.tickerid, "W", close)

// v6 (CURRENT):
request.security(syminfo.tickerid, "W", close)  // Same as v5 for this
```

### 2. String Constants
```pinescript
// v4 (DEPRECATED):
plot(close, style=line)
hline(50, linestyle=dashed)

// v6:
plot(close, style=plot.style_line)
hline(50, linestyle=hline.style_dashed)
```

### 3. Input Types
```pinescript
// v4 (DEPRECATED):
input(14, title="Length", type=integer)

// v6:
input.int(14, title="Length")
input.float(1.5, title="Multiplier")
input.bool(true, title="Show Zones")
input.string("demand", title="Zone Type", options=["demand", "supply"])
input.color(color.green, title="Zone Color")
input.timeframe("W", title="HTF")
input.source(close, title="Source")
```

### 4. Variable Declarations
```pinescript
// v6 requires explicit type or var:
var float myLevel = na
var int counter = 0
var bool triggered = false
var line myLine = na
var box myBox = na
var label myLabel = na
```

### 5. Drawing Objects
```pinescript
// v6 drawing syntax:
myLine := line.new(bar_index[10], high[10], bar_index, high, 
                    color=color.red, width=2, style=line.style_solid)
                    
myBox := box.new(bar_index[10], high[10], bar_index, low[10],
                  bgcolor=color.new(color.green, 85),
                  border_color=color.green, border_width=1)

myLabel := label.new(bar_index, high, "Zone", 
                      color=color.green, textcolor=color.white,
                      style=label.style_label_down, size=size.small)
```

### 6. Arrays
```pinescript
var float[] myArray = array.new_float(0)
array.push(myArray, close)
array.get(myArray, 0)
array.size(myArray)
array.remove(myArray, 0)

// v6 also supports method syntax:
myArray.push(close)
myArray.get(0)
myArray.size()
```

### 7. Alert Conditions
```pinescript
// Simple alert:
alertcondition(crossover(fast, slow), title="Buy Signal", message="Buy at {{close}}")

// Strategy alerts (auto-generated from strategy orders):
strategy.entry("Long", strategy.long)
strategy.exit("Exit", "Long", stop=stopPrice, limit=targetPrice)
```

---

## COMMON PATTERNS FOR BLUEPRINT SYSTEM

### Candle Classification
```pinescript
body = math.abs(close - open)
range_ = high - low  // Note: 'range' is reserved in some contexts
body_pct = range_ > 0 ? body / range_ : 0

is_indecisive = body_pct <= 0.50
is_decisive = body_pct > 0.50
is_explosive = body_pct >= 0.70

is_bullish = close > open
is_bearish = close < open
```

### Zone Box Drawing
```pinescript
// Draw a demand zone
if demandDetected
    box.new(bar_index[baseStart], proximal, bar_index, distal,
            bgcolor=color.new(color.green, 85),
            border_color=color.green, border_width=1,
            extend=extend.right)
    
    // Add score label
    label.new(bar_index, proximal, 
              "D:" + str.tostring(score, "#.#"),
              color=color.green, textcolor=color.white,
              style=label.style_label_down, size=size.tiny)
```

### Stop Calculation — Two Modes

**IMPORTANT (Audit correction — CW43-Idx)**: Stop mode depends on which timeframe you are entering from.

```pinescript
// Mode 1: LTF / Pattern entries (default) — -33% Fibonacci extension
// For demand zone long entries via pattern or LTF zone refinement:
fib_stop_long = distal - 0.33 * (proximal - distal)

// For supply zone short entries via pattern or LTF zone refinement:
fib_stop_short = distal + 0.33 * (proximal - distal)

// Mode 2: HTF weekly income entries — DISTAL LINE ONLY (no extension)
// When entering directly at the weekly/monthly HTF zone proximal:
htf_stop_long = distal    // exactly at distal — achieves 4:1 R:R on weekly zones
htf_stop_short = distal   // exactly at distal

// Dynamic selection based on entry timeframe:
isHTFWeeklyEntry = timeframe.isequal(timeframe.period, "W") or 
                   timeframe.isequal(timeframe.period, "M")
stop_price = isHTFWeeklyEntry ? distal : 
             (direction_long ? fib_stop_long : fib_stop_short)
```

### R-Multiple Targets
```pinescript
risk = math.abs(entry - stop)
t1 = entry + risk       // 1R — breakeven trigger
t2 = entry + 2 * risk   // 2R — partial profit
t3 = entry + 3 * risk   // 3R — trail/close

// For shorts: subtract instead of add
```

### Multi-Timeframe Request
```pinescript
htf_close = request.security(syminfo.tickerid, "W", close)
htf_high = request.security(syminfo.tickerid, "W", high)
htf_low = request.security(syminfo.tickerid, "W", low)

// IMPORTANT: request.security returns ONE value per bar
// For arrays/complex data, use tuples:
[htf_h, htf_l, htf_c] = request.security(syminfo.tickerid, "W", [high, low, close])
```

### COT Data Access
```pinescript
// COT data requires CFTC symbols — cannot use regular ticker
// Use the TradingView COT indicator or fetch via:
cot_ticker = "CFTC:6E_F_L_ALL"  // Euro FX, Futures, Long, All
cot_data = request.security(cot_ticker, "W", close)
```

### Valuation References by Asset Class (Audit-Corrected)
```pinescript
// IMPORTANT: Equity indices DO include DXY (corrected from prior "NO Dollar" rule)
// Source: CampusValuationTool_V2 confirmed @$XY for AAPL, YMN, NQ

// Forex valuation:
val_dxy = request.security("DXY", timeframe.period, ta.roc(close, 10))

// Equity indices valuation (ROC 13, THREE references including DXY):
val_zn  = request.security("ZN1!", timeframe.period, ta.roc(close, 13))  // 10yr Notes
val_zb  = request.security("ZB1!", timeframe.period, ta.roc(close, 13))  // 30yr Bonds  
val_dxy_eq = request.security("DXY", timeframe.period, ta.roc(close, 13)) // Dollar — YES for equities
equity_val_score = asset_roc - (val_zn + val_zb + val_dxy_eq) / 3

// Commodities valuation (all three):
val_gc  = request.security("GC1!", timeframe.period, ta.roc(close, 10))  // Gold
val_zb2 = request.security("ZB1!", timeframe.period, ta.roc(close, 10))  // Bonds
val_dxy2 = request.security("DXY", timeframe.period, ta.roc(close, 10))  // Dollar
commodity_val_score = asset_roc - (val_dxy2 + val_gc + val_zb2) / 3

// Platinum (exception — DXY + Gold only, no Bonds):
platinum_val_score = asset_roc - (val_dxy2 + val_gc) / 2

// Silver (Bonds ticker = @VD, not @US):
val_vd = request.security("@VD", timeframe.period, ta.roc(close, 10))  // VD = correct bonds for Silver
silver_val_score = asset_roc - (val_dxy2 + val_vd + val_gc) / 3

// Valuation signal thresholds (4-state model):
val_strong_bull = val_score <= -75  // STRONG BULLISH — look for demand zones
val_mild_bull   = val_score < 0 and val_score > -75  // mild bullish lean
val_mild_bear   = val_score > 0 and val_score < 75   // mild bearish caution
val_strong_bear = val_score >= 75   // STRONG BEARISH — look for supply zones

// Hard gate check — veto the trade if Valuation strongly opposes direction:
valuation_vetoes_long  = val_strong_bear  // strongly overvalued → refuse long
valuation_vetoes_short = val_strong_bull  // strongly undervalued → refuse short
```

### COT Lookback by Asset Class (Audit-Corrected)
```pinescript
// CORRECTED: Forex uses 26w (not 52w as previously documented)
// Hybrid AI default is 26w; 52w is commodity-specific (planting cycle)

var int COT_LOOKBACK_FOREX      = 26   // Non-Commercials, 26w
var int COT_LOOKBACK_EQUITIES   = 26   // Non-Commercials, 26w
var int COT_LOOKBACK_COMMODITIES = 52  // Commercials, 52w (planting cycle)
var int COT_LOOKBACK_PM         = 52   // Commercials + Retailers, 52w
var int COT_LOOKBACK_SOFT_AGS   = 26   // Non-Commercials (NOT Commercials!), 26w

// COT index formula (same for all, different lookbacks):
cot_index(netPos, netHistory, lookback) =>
    history = array.slice(netHistory, math.max(0, array.size(netHistory) - lookback), array.size(netHistory))
    lowest = array.min(history)
    highest = array.max(history)
    highest == lowest ? 50.0 : 100.0 * (netPos - lowest) / (highest - lowest)
```

---

## STRATEGY-SPECIFIC RULES

### Strategy Declaration
```pinescript
//@version=6
strategy("Blueprint SD Strategy", overlay=true,
         default_qty_type=strategy.percent_of_equity,
         default_qty_value=1,  // 1% risk
         initial_capital=100000,
         commission_type=strategy.commission.percent,
         commission_value=0.01,
         slippage=1)
```

### Entry/Exit Orders
```pinescript
// Entry at zone proximal:
if longCondition
    strategy.entry("Long", strategy.long, limit=proximal)
    strategy.exit("SL/TP", "Long", 
                  stop=fib_stop, 
                  limit=t3,
                  qty_percent=100)

// Partial at T2:
if strategy.position_size > 0 and high >= t2 and not partialTaken
    strategy.close("Long", qty_percent=50, comment="Partial T2")
    partialTaken := true
    
// Breakeven at T1:
if strategy.position_size > 0 and high >= t1 and not beTriggered
    strategy.exit("BE", "Long", stop=entry)
    beTriggered := true
```

### Backtesting Settings
```pinescript
// Use realistic settings:
// - Commission: 0.01% (or broker-specific)
// - Slippage: 1 tick
// - Initial capital: match your funded account size
// - Date range: minimum 2 years
// - HIDE FUTURE DATA (non-negotiable for honest backtest)
```

---

## PERFORMANCE OPTIMIZATION

### Limit Drawing Objects
```pinescript
// TradingView limits: ~500 drawing objects max
// Delete old zones:
if array.size(zoneBoxes) > 50
    box.delete(array.shift(zoneBoxes))
```

### Avoid Repainting
```pinescript
// NEVER use future data:
// BAD: if close[0] > close[-1]  // -1 = future bar!
// GOOD: if close > close[1]     // [1] = previous bar

// NEVER reference barstate.isrealtime for entry logic
// ALWAYS use confirmed (closed) candle data for signals
```

### Memory Management
```pinescript
// Use var for persistent variables (saves memory):
var float lastZoneProximal = na
var int lastZoneBar = na
var bool inPosition = false
```

---

## COMMON ERRORS AND FIXES

| Error | Cause | Fix |
|-------|-------|-----|
| `Cannot call 'security'` | Using v4 function | Use `request.security()` |
| `Cannot use 'input' with type` | v4 input syntax | Use `input.int()`, `input.float()` etc. |
| `Undeclared identifier` | Missing var/type declaration | Add `var float x = na` |
| `The function 'X' is deprecated` | Using old function name | Check v6 equivalent |
| `Too many drawings` | >500 boxes/lines/labels | Delete old ones with array management |
| `Script takes too long` | Heavy loops | Reduce lookback, optimize logic |
| `Cannot modify global variable` | Trying to modify in local scope | Use `var` or `:=` correctly |

---

## INDICATOR vs STRATEGY

| Feature | indicator() | strategy() |
|---------|------------|------------|
| Backtesting | No | Yes |
| Order execution | No | Yes (simulated) |
| Performance report | No | Yes |
| Alert conditions | alertcondition() | Auto from orders |
| Drawing limit | ~500 | ~500 |
| Use case | Visual analysis | Automated testing |

For Blueprint system: Build as **indicator** first (visual zone detection + scoring), then convert winning logic to **strategy** for backtesting.
