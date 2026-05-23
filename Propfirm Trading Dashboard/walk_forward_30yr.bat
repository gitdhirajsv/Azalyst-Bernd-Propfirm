@echo off
REM ============================================================
REM  Blueprint 30-Year Walk-Forward Test
REM  Pulls max available price history + 30yr CFTC COT history
REM  Walks forward from 2020 to today, zero look-ahead
REM
REM  Options passed through to Python:
REM    --fast          20 core symbols only (~1 hr)
REM    --start YYYY-MM-DD   custom start date
REM    --csv file.csv  save results
REM    --symbols GC=F SI=F  specific symbols only
REM    --verbose       print each signal as it fires
REM
REM  Example: walk_forward_30yr.bat --fast --csv results.csv
REM ============================================================

cd /d "%~dp0"

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"

if exist "__pycache__" rd /s /q "__pycache__"

echo.
echo ============================================================
echo  Blueprint 30-Year Walk-Forward Test
echo  COT depth: 30-40 years (full CFTC history)
echo  Price:     max available via Yahoo Finance
echo  Period:    2020-01-01 to today (zero look-ahead)
echo ============================================================
echo.

%PYTHON_EXE% run_walk_forward_30yr.py %*

echo.
echo Done.
pause
