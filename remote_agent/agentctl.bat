@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "EXEC=%SCRIPT_DIR%tnhcomfy-agent.exe"

if exist "%SCRIPT_DIR%.env" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%SCRIPT_DIR%.env") do (
        set "key=%%A"
        set "val=%%B"
        if /I "!key:~0,7!"=="export " set "key=!key:~8!"
        set "key=!key: =!"
        if "!val:~0,1!"=="\"" set "val=!val:~1,-1!"
        if "!val:~0,1!"=="'" set "val=!val:~1,-1!"
        if defined key if not defined !key! set "!key!=!val!"
    )
)

if not defined DATA_DIR set "DATA_DIR=%SCRIPT_DIR%data"
if not defined PORT set "PORT=8001"
if not defined HOST set "HOST=0.0.0.0"

if not exist "%EXEC%" (
    echo error: agent executable not found at %EXEC%
    echo Build it on Windows with: pyinstaller --distpath "%SCRIPT_DIR%" --specpath "%SCRIPT_DIR%" tnhcomfy-agent.spec
    exit /b 1
)

"%EXEC%"
