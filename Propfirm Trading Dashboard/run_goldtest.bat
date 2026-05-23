@echo off
REM ============================================================
REM Run the FT 121-case goldtest validation against Bernd's calls.
REM Outputs Stage-1 (bias_only) and Stage-2 (full signal) accuracy.
REM Phase 23 (T1 + T2 + T3 + T4 + T5) deployed — expect score change vs Phase 22.
REM ============================================================
setlocal
title Goldtest [Phase 23]

cd /d "%~dp0"

REM Pre-clear any compiled bytecode so freshly edited .py files are picked up.
if exist "__pycache__" rd /s /q "__pycache__"
if exist "goldtest\__pycache__" rd /s /q "goldtest\__pycache__"

echo ============================================
echo   Goldtest run starting at %date% %time%
echo ============================================
echo.

cd goldtest
python run_goldtest.py --cases-file gold_cases_phase8.yaml > phase23_results.log 2>&1
set RC=%ERRORLEVEL%
cd ..

echo.
echo --- Last 80 lines of phase23_results.log ---
powershell -NoProfile -Command "Get-Content 'goldtest\phase23_results.log' -Tail 80"

echo.
echo ============================================
echo   Done. Exit code: %RC%
echo   Full log: goldtest\phase23_results.log
echo ============================================
pause
exit /b %RC%
