@echo off
REM ==========================================================================
REM BizPilot AI - reproducible Windows build
REM Run this from the project root on a Windows machine with Python 3.12+.
REM ==========================================================================
setlocal

echo [1/4] Creating virtual environment...
if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo [3/4] Running the test suite...
python -m pytest -q
if errorlevel 1 (
    echo Tests failed - aborting the build.
    exit /b 1
)

echo [4/4] Building the executable with PyInstaller...
python -m PyInstaller deployment\build.spec --noconfirm
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo.
echo Build complete: dist\BizPilotAI\BizPilotAI.exe
echo The database is created on first launch in %%LOCALAPPDATA%%\BizPilotAI
endlocal
