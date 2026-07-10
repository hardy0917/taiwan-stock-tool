@echo off
cd /d "%~dp0"

echo Starting Taiwan Stock Tool server...
start "Taiwan Stock Tool - Server (closing this window stops the app)" cmd /k python server.py

timeout /t 2 /nobreak >nul
start "" "http://localhost:8787/"
