@echo off
REM Phase 24 — Wide-window forward test for statistical significance.
REM
REM Default forward test runs ~10 weekly bars (~2 months) which closes ~2-5
REM trades — too few for a meaningful win-rate. This wide invocation uses:
REM   - 2-year window (2024-05 to 2026-05)
REM   - Daily strategy (more signal frequency than weekly)
REM   - Full watchlist (all 66 symbols)
REM
REM Expected output: ~50-100 closed trades, real win-rate signal.

setlocal
cd /d "%~dp0"

REM Clear pycache to make sure latest code is used
if exist "__pycache__" rmdir /S /Q "__pycache__"

REM Run with broader window
uv run --python 3.12 --with pandas --with numpy --with pyyaml --with yfinance --with requests --with curl-cffi run_forward_test.py ^
    --strategy daily ^
    --start 2024-05-01 ^
    --end 2026-05-06 ^
    > forward_test_wide_results.txt 2>&1

echo.
echo Forward test complete. Results written to forward_test_wide_results.txt
echo.
type forward_test_wide_results.txt | more

endlocal
