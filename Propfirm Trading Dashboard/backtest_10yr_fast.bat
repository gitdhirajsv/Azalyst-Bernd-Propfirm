@echo off
REM ============================================================
REM  Blueprint 10-Year Walk-Forward Backtest  (FAST: 20 symbols)
REM
REM  EXPECT 2-4 HOURS. Each symbol takes 5-10 minutes of compute
REM  with brief "fetched..." lines and one dot per year of scan.
REM  Output streams LIVE to this console.
REM ============================================================

setlocal
cd /d "%~dp0"

if exist "__pycache__" rd /s /q "__pycache__"

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"

echo.
echo ============================================================
echo  Blueprint 10-Year Walk-Forward Backtest (FAST)
echo  Period:   2016-01-01 to today
echo  Symbols:  20 core futures + BTC
echo  Strategy: weekly
echo.
echo  Live output below. KEEP THE WINDOW OPEN.
echo  A dot per ~1 year of scan, then [N signals] when each symbol
echo  finishes.
echo ============================================================
echo.

%PYTHON_EXE% -u run_walk_forward_30yr.py ^
    --strategy weekly ^
    --fast ^
    --start 2016-01-01 ^
    --csv backtest_10yr_fast.csv ^
    --json backtest_10yr_fast.json ^
    2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath backtest_10yr_fast.log"

echo.
echo ============================================================
echo  Backtest complete.  Summary:
echo ============================================================
%PYTHON_EXE% backtest_summary.py backtest_10yr_fast.csv

endlocal
pause
