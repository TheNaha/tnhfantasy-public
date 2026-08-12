@echo off
REM tnhcomfy-agent launcher for Windows.
REM Starts the standalone Remote Agent executable (no Docker, no Python).
REM
REM   Usage:
REM     agentctl.bat        (foreground)
REM     start "" agentctl.bat   (double-click to minimize / run in background)
REM
REM Edit .env (see .env.example) for your ComfyUI install path, tokens, port.
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "EXEC=%SCRIPT_DIR%tnhcomfy-agent.exe"

REM Defaults (overridable by env or .env).
if "%DATA_DIR%"==""      set "DATA_DIR=%SCRIPT_DIR%data"
if "%PORT%"==""         set "PORT=8001"
if "%HOST%"==""         set "HOST=0.0.0.0"

REM Load .env (if present) without clobbering already-set env vars.
if exist "%SCRIPT_DIR%.env" (
    for /f "usebackq tokens=1,2 delims==" %%A in (%SCRIPT_DIR%.env) do (
        set "key=%%A"
        set "val=%%B"
        REM Strip optional surrounding quotes.
        if "!val:~0,1!"=="\"" set "val=!val:~1,-1!"
        if "!val:~0,1!"=="'" set "val=!val:~1,-1!"
        REM Skip if the variable is already set.
        if not defined !key! (
            set "!key!=!val!"
        )
        set "!key!=!val!"
    )
)

if not exist "%EXEC%" (
    echo error: agent executable not found at %EXEC%
    echo Build it on Windows with: pyinstaller --distpath %SCRIPT_DIR% --specpath %SCRIPT_DIR% tnhcomfy-agent.spec
    exit /b 1
)

"%EXEC%"
