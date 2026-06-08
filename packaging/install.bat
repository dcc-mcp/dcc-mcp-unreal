@echo off
REM ============================================================
REM  dcc-mcp-unreal — Windows installer
REM
REM  Installs the plugin into the current Unreal Engine project
REM  or as an Engine plugin (if --engine is passed).
REM
REM  Usage:
REM    install.bat                         (install into project)
REM    install.bat --engine "C:\UE5"      (install into engine)
REM    install.bat --project "C:\MyGame"  (specify project root)
REM ============================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PLUGIN_DIR=%SCRIPT_DIR%..\unreal\plugin"
set "INSTALL_MODE=project"
set "ENGINE_ROOT="
set "PROJECT_ROOT=%CD%"

REM Parse arguments
:parse_args
if "%~1"=="" goto :done_args
if /i "%~1"=="--engine" (
    set "INSTALL_MODE=engine"
    set "ENGINE_ROOT=%~2"
    shift
    shift
    goto :parse_args
)
if /i "%~1"=="--project" (
    set "PROJECT_ROOT=%~2"
    shift
    shift
    goto :parse_args
)
shift
goto :parse_args
:done_args

REM Read version from plugin descriptor
set "VERSION=0.1.0"
for %%p in ("%PLUGIN_DIR%\*.uplugin") do set "UPLUGIN=%%~fp"
for /f "tokens=2 delims=:, " %%v in ('findstr /i "VersionName" "%UPLUGIN%"') do (
    set "VERSION=%%~v"
    goto :got_version
)
:got_version
echo [dcc-mcp-unreal] Installing version %VERSION%

REM Determine destination
if "%INSTALL_MODE%"=="engine" (
    if "%ENGINE_ROOT%"=="" (
        echo ERROR: --engine requires a path, e.g. --engine "C:\Program Files\Epic Games\UE_5.4"
        exit /b 1
    )
    set "DEST=%ENGINE_ROOT%\Engine\Plugins\DccMcpUnreal"
    echo Installing as Engine plugin to: !DEST!
) else (
    REM Check .uproject exists
    set "UPROJECT_FOUND=0"
    for %%f in ("%PROJECT_ROOT%\*.uproject") do set "UPROJECT_FOUND=1"
    if "!UPROJECT_FOUND!"=="0" (
        echo WARNING: No .uproject found in %PROJECT_ROOT%
        echo          Specify the project root with --project "C:\MyGame"
    )
    set "DEST=%PROJECT_ROOT%\Plugins\DccMcpUnreal"
    echo Installing as Project plugin to: !DEST!
)

REM Create destination and copy plugin files
if exist "!DEST!" (
    echo Removing existing installation at !DEST!
    rmdir /s /q "!DEST!"
)
mkdir "!DEST!"
xcopy /e /i /q "%PLUGIN_DIR%\*" "!DEST!\" >nul
echo Plugin files copied.

REM Install Python package into the plugin's python/ directory
echo Installing dcc-mcp-unreal Python package...
python -m pip install dcc-mcp-unreal --target "!DEST!\python" --quiet
if errorlevel 1 (
    echo WARNING: pip install failed. You can install manually:
    echo   pip install dcc-mcp-unreal --target "!DEST!\python"
)

REM Run post-install verification
echo.
echo Running post-install verification...
python "%SCRIPT_DIR%post_install.py" --plugin-root "!DEST!"
if errorlevel 1 (
    echo WARNING: Post-install verification reported issues. Check output above.
)

echo.
echo ============================================================
echo  Installation complete!
echo.
echo  To enable in Unreal Engine:
echo  1. Open your project in Unreal Editor
echo  2. Edit ^> Plugins ^> search "DCC MCP Unreal"
echo  3. Enable the plugin and restart the editor
echo  4. The MCP server starts automatically at port 8765
echo.
echo  To configure port:
echo    set DCC_MCP_UNREAL_PORT=9000
echo  To configure server name:
echo    set DCC_MCP_UNREAL_SERVER_NAME=my-unreal-mcp
echo ============================================================
endlocal
