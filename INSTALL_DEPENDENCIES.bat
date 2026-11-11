@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title djcues Studio - Setup + Abhaengigkeiten
cd /d "%~dp0"

echo ===================================================================
echo       djcues Studio - Setup ^& Abhaengigkeiten pruefen/installieren
echo ===================================================================
echo.

where python >nul 2>nul
if %errorlevel% equ 0 goto :check_venv

echo [WARNUNG] Python wurde im PATH nicht gefunden!
where winget >nul 2>nul
if %errorlevel% neq 0 goto :no_python

set "install_py="
set /p install_py="Moechtest du Python 3.12 jetzt ueber winget installieren? (j/n): "
if /i "!install_py!"=="j" (
    winget install --id Python.Python.3.12 -e --source winget
    echo.
    echo Bitte schliesse dieses Fenster und starte INSTALL_DEPENDENCIES.bat neu.
    pause
    exit /b 0
)

:no_python
echo [FEHLER] Python 3.10+ wird benoetigt. Download: https://www.python.org/downloads/
pause
exit /b 1

:check_venv
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set "PY_VER=%%i"
echo [OK] Gefunden: !PY_VER!

if exist "%~dp0.venv\Scripts\python.exe" goto :check_packages

echo.
echo [SETUP] Erstelle lokale Python-Umgebung (.venv)...
python -m venv "%~dp0.venv"
if %errorlevel% neq 0 (
    echo [FEHLER] Virtuelle Umgebung konnte nicht erstellt werden!
    pause
    exit /b 1
)
echo [OK] .venv erfolgreich erstellt.

:check_packages
"%~dp0.venv\Scripts\python.exe" -c "import pyrekordbox, click, djcues, pytest" >nul 2>nul
if %errorlevel% neq 0 goto :install_packages

echo [OK] Alle benoetigten Abhaengigkeiten (pyrekordbox, click, djcues, pytest) sind installiert.
if "%1"=="--no-pause" goto :done
set "force_update="
set /p force_update="Trotzdem aktualisieren/neu abgleichen? (j/n) [n]: "
if /i not "!force_update!"=="j" goto :done

:install_packages
echo.
echo [INSTALL] Installiere / aktualisiere Abhaengigkeiten in .venv...
call "%~dp0.venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -e . pytest
if %errorlevel% neq 0 (
    echo [FEHLER] Installation der Pakete fehlgeschlagen!
    pause
    exit /b 1
)

:done
echo.
echo ===================================================================
echo   [FERTIG] Alle Abhaengigkeiten sind einsatzbereit!
echo   Starte jetzt DJCUES_STUDIO.bat oder start.bat.
echo ===================================================================
if "%1"=="--no-pause" exit /b 0
pause
exit /b 0
