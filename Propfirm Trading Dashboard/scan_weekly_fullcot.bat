@echo off
REM ============================================================
REM   Weekly scan using 30-YEAR CFTC history (full-cot mode)
REM   Bernd: "pull as much data as you can"
REM   ~1-2 min extra on first run; cached for subsequent symbols.
REM ============================================================
cd /d "%~dp0"
call "%~dp0scan_markets_fullcot.bat" weekly
pause
