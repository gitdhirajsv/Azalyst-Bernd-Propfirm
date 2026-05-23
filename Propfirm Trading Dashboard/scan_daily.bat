@echo off
cd /d "%~dp0"

REM One-click daily scan (HTF=1d, LTF=60m). Forwards to scan_markets.bat.
call "%~dp0scan_markets.bat" daily
pause
