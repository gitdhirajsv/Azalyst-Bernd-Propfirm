@echo off
cd /d "%~dp0"

REM One-click weekly scan (HTF=1wk, LTF=1d). Forwards to scan_markets.bat.
call "%~dp0scan_markets.bat" weekly
pause
