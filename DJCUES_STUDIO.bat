@echo off
chcp 65001 >nul
title djcues — Rekordbox Walkthrough Studio
cd /d "%~dp0"

echo ===================================================================
echo             djcues — Rekordbox Genre & Cue Studio
echo ===================================================================
echo.

:: 1. Virtuelle Umgebung prüfen und aktivieren
if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
) else (
    echo [HINWEIS] Keine .venv gefunden. Verwende globales Python...
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        echo [FEHLER] Python wurde nicht gefunden! Bitte installiere Python 3.10+.
        pause
        exit /b 1
    )
)

:: 2. CLI mit Walkthrough starten
python -m djcues.cli

echo.
echo Studio beendet.
pause
