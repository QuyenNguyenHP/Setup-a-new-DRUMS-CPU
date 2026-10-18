@echo off
cd /d "%~dp0"
set "PYTHON_CMD="
if exist ".venv\Scripts\python.exe" set "PYTHON_CMD=.venv\Scripts\python.exe"
if not defined PYTHON_CMD (
    if exist "%LocalAppData%\Programs\Python\Launcher\py.exe" (
        set "PYTHON_CMD=%LocalAppData%\Programs\Python\Launcher\py.exe -3"
    ) else if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
        set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python312\python.exe"
    ) else if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
        set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python311\python.exe"
    ) else if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
        set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python310\python.exe"
    ) else (
        py -3 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3"
        if not defined PYTHON_CMD python -c "import sys" >nul 2>nul && set "PYTHON_CMD=python"
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python environment...
    call %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :no_python
    set "PYTHON_CMD=.venv\Scripts\python.exe"
)
echo Installing/checking dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :install_error
".venv\Scripts\pythonw.exe" app.py
exit /b 0

:no_python
echo.
echo Python was not found. Install Python 3.10 or later from https://python.org
pause
exit /b 1

:install_error
echo.
echo Unable to install dependencies. Check your Internet connection and try again.
pause
exit /b 1
