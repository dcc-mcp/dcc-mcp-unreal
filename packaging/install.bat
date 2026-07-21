@echo off
REM ============================================================
REM  dcc-mcp-unreal — Windows one-click installer
REM
REM  Double-click to install interactively, or pass args:
REM    install.bat                                    (interactive)
REM    install.bat "C:\UE_5.7"                        (drag-drop engine)
REM    install.bat --engine "C:\UE_5.7"               (install to engine)
REM    install.bat --project "C:\MyGame"              (install to project)
REM    install.bat --project "C:\MyGame\MyGame.uproject"
REM
REM  Auto-detects engine root vs project root.
REM ============================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"

REM ── Step 1: Determine plugin source ──────────────────────────
REM Check if we're inside a release package or a source checkout.
set "PLUGIN_SOURCE="
if exist "%SCRIPT_DIR%..\DccMcpUnreal.uplugin" (
    REM Release package: install.bat is inside the extracted DccMcpUnreal/ folder
    set "PLUGIN_SOURCE=%SCRIPT_DIR%.."
) else if exist "%SCRIPT_DIR%..\unreal\plugin\DccMcpUnreal.uplugin" (
    REM Source checkout: install.bat is in packaging/, plugin source in ../unreal/plugin/
    set "PLUGIN_SOURCE=%SCRIPT_DIR%..\unreal\plugin"
)

if "%PLUGIN_SOURCE%"=="" (
    echo ERROR: Cannot find plugin source.
    echo   Expected: DccMcpUnreal.uplugin in parent directory or ..\unreal\plugin\
    echo   Current:  %SCRIPT_DIR%
    exit /b 1
)

REM ── Step 2: Parse arguments ──────────────────────────────────
set "INSTALL_MODE="
set "TARGET_PATH="

if not "%~1"=="" (
    if /i "%~1"=="--engine" (
        set "INSTALL_MODE=engine"
        set "TARGET_PATH=%~2"
    ) else if /i "%~1"=="--project" (
        set "INSTALL_MODE=project"
        set "TARGET_PATH=%~2"
    ) else if /i "%~1"=="-h" (
        goto :show_help
    ) else if /i "%~1"=="--help" (
        goto :show_help
    ) else (
        REM Single argument without flag — auto-detect
        set "TARGET_PATH=%~1"
    )
)

REM ── Step 3: Interactive mode (no args) ───────────────────────
:prompt_target
if "%TARGET_PATH%"=="" (
    echo.
    echo ============================================================
    echo   dcc-mcp-unreal — One-Click Installer
    echo ============================================================
    echo.
    echo   Drag-and-drop an Unreal Engine root folder
    echo   (e.g. C:\Program Files\Epic Games\UE_5.7^)
    echo   — OR —
    echo   Drag-and-drop a project folder
    echo   (e.g. C:\Users\you\MyGame ^)
    echo.
    set /p "TARGET_PATH=  Path: "
    REM Strip quotes and trailing backslash
    set "TARGET_PATH=!TARGET_PATH:"=!"
    if "!TARGET_PATH:~-1!"=="\" set "TARGET_PATH=!TARGET_PATH:~0,-1!"
)

if "%TARGET_PATH%"=="" (
    echo No path provided. Exiting.
    exit /b 0
)

REM ── Step 4: Auto-detect engine vs project ────────────────────
if "%INSTALL_MODE%"=="" (
    REM Check if it's a .uproject file → project mode
    if /i "%TARGET_PATH:~-9%"==".uproject" (
        set "INSTALL_MODE=project"
    ) else if exist "%TARGET_PATH%\Engine\Build\Build.version" (
        set "INSTALL_MODE=engine"
    ) else if exist "%TARGET_PATH%\*.uproject" (
        set "INSTALL_MODE=project"
    ) else (
        echo.
        echo WARNING: Cannot determine if this is an Engine or Project.
        echo   Engine: has Engine\Build\Build.version
        echo   Project: has *.uproject file(s^)
        echo.
        choice /c EP /m "Is this an [E]ngine root or [P]roject root?"
        if errorlevel 2 (set "INSTALL_MODE=project") else (set "INSTALL_MODE=engine")
    )
)

REM ── Step 5: Resolve .uproject for project mode ───────────────
if "%INSTALL_MODE%"=="project" (
    if /i "%TARGET_PATH:~-9%"==".uproject" (
        for %%f in ("%TARGET_PATH%") do set "PROJECT_ROOT=%%~dpf"
        set "UPROJECT_FILE=%TARGET_PATH%"
    ) else (
        set "PROJECT_ROOT=%TARGET_PATH%"
        set "UPROJECT_FOUND=0"
        for %%f in ("%TARGET_PATH%\*.uproject") do (
            set "UPROJECT_FOUND=1"
            set "UPROJECT_FILE=%%f"
        )
        if "!UPROJECT_FOUND!"=="0" (
            echo ERROR: No .uproject file found in %TARGET_PATH%
            set "TARGET_PATH=" & set "INSTALL_MODE=" & goto :prompt_target
        )
    )
)

REM ── Step 6: Determine destination ────────────────────────────
if "%INSTALL_MODE%"=="engine" (
    set "DEST=%TARGET_PATH%\Engine\Plugins\DccMcpUnreal"
    echo.
    echo Installing as Engine plugin...
    echo   Engine: %TARGET_PATH%
    echo   Dest:   !DEST!
) else (
    set "DEST=%PROJECT_ROOT%Plugins\DccMcpUnreal"
    echo.
    echo Installing as Project plugin...
    echo   Project: %UPROJECT_FILE%
    echo   Dest:    !DEST!
)

REM ── Step 7: Copy plugin files ────────────────────────────────
if exist "!DEST!" (
    echo Removing existing installation...
    rmdir /s /q "!DEST!"
)
mkdir "!DEST!" >nul 2>&1
xcopy /e /i /q "%PLUGIN_SOURCE%\*" "!DEST!\" >nul
if errorlevel 1 (
    echo ERROR: Failed to copy plugin files.
    exit /b 1
)
echo Plugin files copied.

REM ── Step 8: Install Python dependencies ──────────────────────
REM Auto-detect UE's bundled Python; fall back to system Python.
set "PYTHON_EXE=python"

REM Try engine mode: use the target engine's bundled Python.
if "%INSTALL_MODE%"=="engine" (
    set "UE_PYTHON=%TARGET_PATH%\Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
    if exist "!UE_PYTHON!" set "PYTHON_EXE=!UE_PYTHON!"
)
REM Try project mode: resolve the engine from the .uproject's EngineAssociation.
if "%INSTALL_MODE%"=="project" (
    REM Simple heuristic: check common install paths for the engine version
    for /f "tokens=*" %%v in ('python -c "import json; d=json.load(open(r'%UPROJECT_FILE:\=\\%','r',encoding='utf-8')); print(d.get('EngineAssociation',''))" 2^>nul') do set "ENGINE_VER=%%v"
    if not "!ENGINE_VER!"=="" (
        if exist "C:\Program Files\Epic Games\UE_!ENGINE_VER!\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" (
            set "PYTHON_EXE=C:\Program Files\Epic Games\UE_!ENGINE_VER!\Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
        )
    )
    REM If we still don't have it, try the engine root from the current UE_ROOT env
    if "!PYTHON_EXE!"=="python" (
        if not "%UE_ROOT%"=="" if exist "%UE_ROOT%\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" (
            set "PYTHON_EXE=%UE_ROOT%\Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
        )
    )
)

echo.
echo Installing Python dependencies (using !PYTHON_EXE!)...
"!PYTHON_EXE!" -m pip install dcc-mcp-unreal --target "!DEST!\python" --quiet 2>&1
if errorlevel 1 (
    echo WARNING: pip install failed. You can install manually later:
    echo   "!PYTHON_EXE!" -m pip install dcc-mcp-unreal --target "!DEST!\python"
) else (
    echo Python dependencies installed.
)

REM ── Step 9: Post-install verification ────────────────────────
echo.
echo Running post-install verification...
python "%SCRIPT_DIR%post_install.py" --plugin-root "!DEST!" 2>&1
if errorlevel 1 (
    echo WARNING: Verification reported issues. See above.
)

REM ── Step 10: Done ────────────────────────────────────────────
echo.
echo ============================================================
echo   Installation complete!
echo.
echo   Plugin: !DEST!
echo.
if "%INSTALL_MODE%"=="project" (
    echo   Next steps:
    echo   1. Open "%UPROJECT_FILE%" in Unreal Editor
    echo   2. Edit ^> Plugins ^> search "DCC MCP Unreal"
    echo   3. Enable the plugin and restart the editor
    echo   4. In the Python console, run:
    echo      import dcc_mcp_unreal
    echo      dcc_mcp_unreal.start_server()
) else (
    echo   Next steps:
    echo   1. Open any project in Unreal Editor
    echo   2. Edit ^> Plugins ^> search "DCC MCP Unreal"
    echo   3. Enable the plugin and restart the editor
)
echo.
echo   Agent connection: http://127.0.0.1:9765/mcp
echo   CLI tools:        dcc-mcp-cli list
echo ============================================================

REM Keep window open for interactive mode
if "%~1"=="" pause
endlocal
exit /b 0

:show_help
echo Usage:
echo   install.bat                         Interactive mode (double-click)
echo   install.bat "C:\UE_5.7"             Auto-detect engine root
echo   install.bat "C:\MyGame"             Auto-detect project root
echo   install.bat --engine "C:\UE_5.7"    Force engine install
echo   install.bat --project "C:\MyGame"   Force project install
echo   uninstall.bat --engine "C:\UE_5.7"  Remove from engine
echo   uninstall.bat --project "C:\MyGame" Remove from project
endlocal
exit /b 0
