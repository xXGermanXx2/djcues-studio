@echo off
chcp 65001 >nul
title djcues - Rekordbox Walkthrough Studio
cd /d "%~dp0"

echo ===================================================================
echo             djcues - Rekordbox Genre ^& Cue Studio
echo ===================================================================
echo.

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [SETUP] Virtuelle Umgebung fehlt - starte automatische Einrichtung...
    call "%~dp0INSTALL_DEPENDENCIES.bat" --no-pause
    if %errorlevel% neq 0 exit /b 1
) else (
    "%~dp0.venv\Scripts\python.exe" -c "import pyrekordbox, click, djcues" >nul 2>nul
    if %errorlevel% neq 0 (
        echo [SETUP] Fehlende Abhaengigkeiten erkannt - starte Installation...
        call "%~dp0INSTALL_DEPENDENCIES.bat" --no-pause
        if %errorlevel% neq 0 exit /b 1
    )
)

call "%~dp0.venv\Scripts\activate.bat"
python -m djcues.cli

echo.
echo Studio beendet.
pause
