param(
    [string]$Project = ".",
    [string]$UERoot = "",
    [ValidateSet("native", "python")]
    [string]$Mode = "native"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($UERoot)) {
    $UERoot = $env:UE_ROOT
}
if ([string]::IsNullOrWhiteSpace($UERoot)) {
    $UERoot = "C:\Program Files\Epic Games\UE_5.2"
}

$projectPath = (Resolve-Path $Project).Path
$projectItem = Get-Item -LiteralPath $projectPath
if ($projectItem.PSIsContainer) {
    $uproject = Get-ChildItem -LiteralPath $projectItem.FullName -Filter "*.uproject" | Select-Object -First 1
    if ($null -eq $uproject) {
        throw "No .uproject file found in $($projectItem.FullName)"
    }
    $projectFile = $uproject.FullName
    $projectRoot = $projectItem.FullName
} else {
    if ($projectItem.Extension -ne ".uproject") {
        throw "Project must be a directory or .uproject file: $($projectItem.FullName)"
    }
    $projectFile = $projectItem.FullName
    $projectRoot = $projectItem.DirectoryName
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$scriptPath = Join-Path $repoRoot "tests\ue_smoke.py"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Smoke test script not found: $scriptPath"
}

$editorCmd = Join-Path $UERoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
if (-not (Test-Path -LiteralPath $editorCmd)) {
    throw "UnrealEditor-Cmd.exe not found: $editorCmd"
}

$resultDir = Join-Path $projectRoot "Saved\Automation"
New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
$result = Join-Path $resultDir "dcc_mcp_unreal_smoke.json"
$log = Join-Path $resultDir "ue_smoke_run.log"
$report = Join-Path $resultDir "Reports"
Remove-Item -LiteralPath $result -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $report -Recurse -Force -ErrorAction SilentlyContinue

$env:DCC_MCP_UNREAL_PORT = "0"
$env:DCC_MCP_UNREAL_TEST_RESULT = $result
$env:DCC_MCP_DISABLE_TELEMETRY = "1"
$env:DCC_MCP_DISABLE_JOB_PERSISTENCE = "1"
$env:DCC_MCP_DISABLE_FILE_LOGGING = "1"
$env:DCC_MCP_UNREAL_DISABLE_MENUS = "1"

if ($Mode -eq "native") {
    $ueArgs = @(
        $projectFile,
        "-Unattended",
        "-NoSplash",
        "-NoSound",
        "-NullRHI",
        "-nop4",
        "-stdout",
        "-FullStdOutLogOutput",
        "-TestExit=Automation Test Queue Empty",
        "-ReportExportPath=$report",
        "-ExecCmds=Automation RunTests DccMcp.Smoke; Quit"
    )
} else {
    $ueArgs = @(
        $projectFile,
        "-Unattended",
        "-NoSplash",
        "-NoSound",
        "-NullRHI",
        "-nop4",
        "-stdout",
        "-FullStdOutLogOutput",
        "-ExecutePythonScript=$scriptPath"
    )
}

& $editorCmd @ueArgs *> $log
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Get-Content -Path $log -Tail 120
    exit $exitCode
}

if (-not (Test-Path -LiteralPath $result)) {
    Get-Content -Path $log -Tail 120
    throw "Smoke test did not write result file: $result"
}

$jsonText = Get-Content -Path $result -Raw
$jsonText
$data = $jsonText | ConvertFrom-Json
if (-not $data.success) {
    Get-Content -Path $log -Tail 120
    exit 1
}

Write-Output "[ue-smoke] log: $log"
if ($Mode -eq "native") {
    Write-Output "[ue-smoke] automation report: $report"
}
