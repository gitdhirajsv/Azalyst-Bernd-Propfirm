@echo off
REM ============================================================
REM  Blueprint 10-Year Walk-Forward Backtest  (FULL watchlist)
REM
REM  EXPECT THIS TO TAKE 4-8 HOURS.
REM  Each symbol fetches ~15 data files then runs 541 weekly scans.
REM  Roughly 5-10 minutes per symbol x 40 symbols.
REM
REM  Output streams LIVE to this console AND saves to log file.
REM  DO NOT close the window unless you actually want to stop it.
REM
REM  A "dot" prints every ~1 year of walk-forward per symbol, so
REM  you should see ~10 dots per symbol before it moves to the next.
REM
REM  Output files:
REM    backtest_10yr_full.csv    one row per trade
REM    backtest_10yr_full.json   same data, JSON
REM    backtest_10yr_full.log    full console output saved
REM ============================================================

setlocal
cd /d "%~dp0"

if exist "__pycache__" rd /s /q "__pycache__"

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"

echo.
echo ============================================================
echo  Blueprint 10-Year Walk-Forward Backtest (FULL)
echo  Period:   2016-01-01 to today
echo  Symbols:  ~40 (futures + forex + stocks + crypto)
echo  Strategy: weekly
echo.
echo  Live output below. Each symbol takes 5-10 min.
echo  KEEP THE WINDOW OPEN.
echo ============================================================
echo.

REM -u = unbuffered Python output so progress appears immediately.
REM Tee-Object echoes to console AND writes to log in real time.
%PYTHON_EXE% -u run_walk_forward_30yr.py ^
    --strategy weekly ^
    --start 2016-01-01 ^
    --csv backtest_10yr_full.csv ^
    --json backtest_10yr_full.json ^
    2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath backtest_10yr_full.log"

echo.
echo ============================================================
echo  Backtest complete.  Summary:
echo ============================================================
%PYTHON_EXE% backtest_summary.py backtest_10yr_full.csv

endlocal
pause
