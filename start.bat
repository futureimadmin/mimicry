@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo Run scripts\install.ps1 first & pause & exit /b 1 )
.venv\Scripts\python -m mimicry ui
