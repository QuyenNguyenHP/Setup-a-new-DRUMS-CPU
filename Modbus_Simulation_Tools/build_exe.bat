@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    py -3 -c "import sys" >nul 2>nul && set "PYTHON_EXE=py -3"
)
if not defined PYTHON_EXE (
    python -c "import sys" >nul 2>nul && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    echo Python was not found. Install Python 3.10 or later first.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    call %PYTHON_EXE% -m venv .venv
    if errorlevel 1 exit /b 1
)

echo Installing runtime dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo Installing PyInstaller...
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 exit /b 1

echo Building executable...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm modbus_slave.spec
if errorlevel 1 exit /b 1

echo.
echo Build complete.
echo EXE output: dist\ModbusSlaveSimulator.exe
endlocal
