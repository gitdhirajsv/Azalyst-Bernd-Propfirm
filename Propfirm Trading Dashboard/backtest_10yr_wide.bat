@echo off
REM ============================================================
REM  Blueprint 10-Year Walk-Forward Backtest  (WIDE: 77 symbols)
REM
REM  Uses the full live-trading watchlist from BP_config.yaml
REM  (vs. the 40-symbol hardcoded list used by backtest_10yr.bat).
REM
REM  Extra symbols vs. the FULL bat:
REM    Forex crosses (EURGBP, EURJPY, GBPAUD, EURCHF, etc.)
REM    More mega-caps + futures depending on YAML contents
REM
REM  Expected vs. backtest_10yr.bat:
REM    Trades/year:   ~22  ->  ~35-40  (more symbols, same edge)
REM    Win rate:      ~49% ->  similar
REM    Max DD:        may be larger in absolute R, similar %
REM
REM  RUNTIME: 8-14 hours.  Leave overnight.
REM
REM  Output:
REM    backtest_10yr_wide.csv
REM    backtest_10yr_wide.json
REM    backtest_10yr_wide.log
REM ============================================================

setlocal
cd /d "%~dp0"

if exist "__pycache__" rd /s /q "__pycache__"

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"

echo.
echo ============================================================
echo  Blueprint 10-Year Walk-Forward Backtest (WIDE)
echo  Period:   2016-01-01 to today
echo  Symbols:  ~77 (full BP_config.yaml live watchlist)
echo  Strategy: weekly
echo.
echo  Live output below. KEEP THE WINDOW OPEN.
echo  Each symbol takes 5-10 min, so ~8-14 hours total.
echo ============================================================
echo.

%PYTHON_EXE% -u run_walk_forward_30yr.py ^
    --strategy weekly ^
    --config-watchlist ^
    --start 2016-01-01 ^
    --csv backtest_10yr_wide.csv ^
    --json backtest_10yr_wide.json ^
    2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath backtest_10yr_wide.log"

echo.
echo ============================================================
echo  Backtest complete.  Summary:
echo ============================================================
%PYTHON_EXE% backtest_summary.py backtest_10yr_wide.csv

endlocal
pause
