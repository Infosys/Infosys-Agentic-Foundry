@echo off
:: Start AgentOS server detached (no console), logs to logs\server.out.log
:: Alternative to start_detached.ps1 for machines with PowerShell execution policy restrictions.

setlocal

set "STUDIO_DIR=%~dp0"
:: Strip trailing backslash
if "%STUDIO_DIR:~-1%"=="\" set "STUDIO_DIR=%STUDIO_DIR:~0,-1%"

:: Repo root is one level up
for %%I in ("%STUDIO_DIR%") do set "REPO_ROOT=%%~dpI"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

:: Find pythonw.exe in .venv or venv
set "PYTHONW="
if exist "%REPO_ROOT%\.venv\Scripts\pythonw.exe" set "PYTHONW=%REPO_ROOT%\.venv\Scripts\pythonw.exe"
if not defined PYTHONW (
    if exist "%REPO_ROOT%\venv\Scripts\pythonw.exe" set "PYTHONW=%REPO_ROOT%\venv\Scripts\pythonw.exe"
)
if not defined PYTHONW (
    echo ERROR: pythonw.exe not found under %REPO_ROOT%\.venv or %REPO_ROOT%\venv
    echo        Create/activate the venv first.
    pause
    exit /b 1
)

:: Create logs dir
if not exist "%STUDIO_DIR%\logs" mkdir "%STUDIO_DIR%\logs"

:: Kill any existing server.py instances
taskkill /F /FI "IMAGENAME eq pythonw.exe" /FI "WINDOWTITLE eq *server*" >nul 2>&1
taskkill /F /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *server*" >nul 2>&1
timeout /t 1 /nobreak >nul

:: Start detached, hidden, stdout/stderr to log files
start "" /b "%PYTHONW%" "%STUDIO_DIR%\server.py" ^
    > "%STUDIO_DIR%\logs\server.out.log" ^
    2> "%STUDIO_DIR%\logs\server.err.log"

echo.
echo AgentOS server started.
echo Interpreter: %PYTHONW%
echo Logs:        %STUDIO_DIR%\logs\server.out.log
echo Health:      curl http://localhost:8081/api/health
echo Stop:        taskkill /F /IM pythonw.exe
