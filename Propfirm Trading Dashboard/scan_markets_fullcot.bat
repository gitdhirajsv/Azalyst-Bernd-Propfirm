@echo off
REM ============================================================
REM   Azalyst Propfirm - Scanner with 30-YEAR COT HISTORY
REM ============================================================
REM   Same as scan_markets.bat but adds --full-cot flag so
REM   ALL COT normalization runs against the complete CFTC
REM   dataset (~30-40 years for major contracts).
REM
REM   Usage:
REM     scan_markets_fullcot.bat               -> daily (default)
REM     scan_markets_fullcot.bat weekly        -> HTF=1wk, LTF=1d
REM     scan_markets_fullcot.bat monthly       -> HTF=1mo, LTF=1wk
REM
REM   What changes vs normal scan:
REM     - COT extreme signals measured vs 30-40 yr history, not 5 yr
REM     - 156w extreme overlay still present but within full dataset
REM     - All-time extreme band active (comm_net_alltime column)
REM     - Signals that were "neutral" on 5yr may become STRONG on 30yr
REM
REM   Extra time: ~1-2 sec per symbol on first run (paginated API);
REM               instant on subsequent symbols (in-process cache).
REM ============================================================

setlocal

set STRATEGY=%~1
if "%STRATEGY%"=="" set STRATEGY=daily

if /I not "%STRATEGY%"=="weekly" if /I not "%STRATEGY%"=="monthly" if /I not "%STRATEGY%"=="daily" if /I not "%STRATEGY%"=="intraday" (
    echo ERROR: Unknown strategy "%STRATEGY%". Use: weekly ^| monthly ^| daily ^| intraday
    pause
    exit /b 2
)

title Azalyst Propfirm Scanner FULL-COT [%STRATEGY%]

echo ============================================
echo   Azalyst Propfirm - Full-History COT Scan
echo   Strategy:  %STRATEGY%
echo   COT depth: 30-40 YEARS (all available CFTC data)
echo   Account:   $100k / $5k daily / $10k total
echo ============================================
echo.
echo Starting scan at %date% %time%
echo.

cd /d "%~dp0"

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"
    echo Using virtual environment...
)

%PYTHON_EXE% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    pause
    exit /b 1
)

REM Discord webhook is loaded from .secrets.bat (gitignored). See scan_markets.bat.
if exist ".secrets.bat" call ".secrets.bat"

if exist "__pycache__" rd /s /q "__pycache__"

set PER_STRAT_LOG=scanner_%STRATEGY%_fullcot.log
echo Per-strategy log: %PER_STRAT_LOG%
echo.

%PYTHON_EXE% run_scanner.py --strategy %STRATEGY% --full-cot
set SCAN_EXIT=%ERRORLEVEL%

echo.
echo --- Last 60 progress lines of %PER_STRAT_LOG% ---
powershell -NoProfile -Command "Get-Content 'scanner_%STRATEGY%.log' | Select-String '\[\d+/\d+\]|SIGNAL|ERROR|Scan complete|signals_found|SCAN COMPLETE' | Select-Object -Last 60"
echo.
echo ============================================
echo   Full-COT scan complete (%STRATEGY%).
echo   Dashboard at http://127.0.0.1:8765
echo   Full log: scanner_%STRATEGY%.log
echo ============================================
pause
exit /b %SCAN_EXIT%
