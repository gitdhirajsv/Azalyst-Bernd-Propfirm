@echo off
REM ============================================================
REM  Blueprint 10-Year Walk-Forward Backtest  (DAILY strategy)
REM
REM  Daily strategy = 1d HTF / 1d LTF zones (vs weekly's 1wk/1d).
REM  Zones form 3-5x more often on daily charts -> more signals.
REM
REM  Scan cadence stays weekly (Monday) to keep runtime in the
REM  4-8 hour range. Going to every-weekday scans would push it
REM  past 30 hours with marginal extra benefit.
REM
REM  Expected vs. weekly strategy:
REM    Trades/year:   ~22  -> probably 50-100+ (daily zones much
REM                          more numerous)
REM    Win rate:      ~49% -> may dip slightly (less HTF context)
REM    Avg R:         expect similar magnitude
REM
REM  Output:
REM    backtest_10yr_daily.csv
REM    backtest_10yr_daily.json
REM    backtest_10yr_daily.log
REM ============================================================

setlocal
cd /d "%~dp0"

if exist "__pycache__" rd /s /q "__pycache__"

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"

echo.
echo ============================================================
echo  Blueprint 10-Year Walk-Forward Backtest (DAILY)
echo  Period:   2016-01-01 to today
echo  Symbols:  ~40 (futures + forex + stocks + crypto)
echo  Strategy: daily  (1d HTF, 1d LTF)
echo.
echo  Live output below. KEEP THE WINDOW OPEN.
echo  Each symbol still takes 5-10 minutes (same scan count).
echo ============================================================
echo.

%PYTHON_EXE% -u run_walk_forward_30yr.py ^
    --strategy daily ^
    --start 2016-01-01 ^
    --csv backtest_10yr_daily.csv ^
    --json backtest_10yr_daily.json ^
    2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath backtest_10yr_daily.log"

echo.
echo ============================================================
echo  Backtest complete.  Summary:
echo ============================================================
%PYTHON_EXE% backtest_summary.py backtest_10yr_daily.csv

endlocal
pause
