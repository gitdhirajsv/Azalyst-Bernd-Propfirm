@echo off
:: scan_all.bat — Run BOTH weekly + daily strategies in one pass
:: Use this for local TradingView idea generation (covers all timeframes).
:: Output: scan_results.json with signals from weekly AND daily passes.
cd /d "%~dp0"
rd /s /q __pycache__ 2>nul
python run_scanner.py --all-strategies
pause
