@echo off
setlocal enabledelayedexpansion

REM Subcommands: start (default), run. The README documented `agentctl.bat start`
REM and the script took no argument at all, so any argument was silently ignored.
REM `stop` is rejected rather than starting an agent at someone who meant to shut
REM one down. There is no pidfile and no daemonisation here, so nothing can stop
REM what this did not start - close the window, or use Task Manager.

set "SUBCOMMAND=%~1"
if not defined SUBCOMMAND set "SUBCOMMAND=start"
if /I not "%SUBCOMMAND%"=="start" if /I not "%SUBCOMMAND%"=="run" (
    if /I "%SUBCOMMAND%"=="-h" goto :usage
    if /I "%SUBCOMMAND%"=="--help" goto :usage
    if /I "%SUBCOMMAND%"=="help" goto :usage
    echo error: unknown subcommand "%SUBCOMMAND%"
    echo.
    echo Run `agentctl.bat --help` for usage.
    exit /b 2
)

set "SCRIPT_DIR=%~dp0"
set "EXEC=%SCRIPT_DIR%tnhfantasy-agent.exe"

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
    echo Build it on Windows with: pyinstaller --distpath "%SCRIPT_DIR%" --specpath "%SCRIPT_DIR%" tnhfantasy-agent.spec
    exit /b 1
)

"%EXEC%"
exit /b %ERRORLEVEL%

:usage
echo usage: agentctl.bat [start^|run]
echo.
echo   start   run the agent in the foreground ^(default when no argument is given^)
echo   run     identical to ^start^
echo.
echo There is no ^stop^ subcommand: this script does not daemonise and does not
echo track a pidfile, so it cannot stop anything it did not start. Close the
echo window instead.
exit /b 0
