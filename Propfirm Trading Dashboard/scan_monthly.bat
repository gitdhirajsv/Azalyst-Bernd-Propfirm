@echo off
cd /d "%~dp0"

REM One-click monthly scan (HTF=1mo, LTF=1wk). Forwards to scan_markets.bat.
call "%~dp0scan_markets.bat" monthly
pause
