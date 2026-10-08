param(
    [Parameter(Mandatory = $true)]
    [string]$UERoot,
    [Parameter(Mandatory = $true)]
    [string]$PythonPayload,
    [string]$OutDir = "",
    [string]$ExpectedCoreVersion = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$engineRoot = (Resolve-Path -LiteralPath $UERoot).Path
$payload = (Resolve-Path -LiteralPath $PythonPayload).Path
$buildFile = Join-Path $engineRoot "Engine\Build\Build.version"
$engineBuild = Get-Content -LiteralPath $buildFile -Raw | ConvertFrom-Json
if ([int]$engineBuild.MajorVersion -ne 5 -or [int]$engineBuild.MinorVersion -notin @(7, 8)) {
    throw "This independent fixture targets UE 5.7 and 5.8 only."
}
if (-not (Test-Path -LiteralPath (Join-Path $payload "dcc_mcp_core\__init__.py"))) {
    throw "PythonPayload must contain the installed fixed dcc-mcp-core wheel: $payload"
}
$editorCmd = Join-Path $engineRoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$scriptPath = Join-Path $repoRoot "tests\ue_spatial_query_smoke.py"
if (-not (Test-Path -LiteralPath $editorCmd)) { throw "Missing UnrealEditor-Cmd.exe: $editorCmd" }
if (-not (Test-Path -LiteralPath $scriptPath)) { throw "Missing spatial fixture: $scriptPath" }
$distRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "dist"))
if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = Join-Path $distRoot "spatial-smoke-ue$($engineBuild.MajorVersion)$($engineBuild.MinorVersion)"
}
if (-not [System.IO.Path]::IsPathRooted($OutDir)) { $OutDir = Join-Path $repoRoot $OutDir }
$output = [System.IO.Path]::GetFullPath($OutDir)
$distPrefix = $distRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($distPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Fixture output must be a dedicated directory inside this checkout's dist/: $output"
}
if (Test-Path -LiteralPath $output) {
    throw "Output already exists; preserve its evidence and choose a fresh -OutDir: $output"
}
New-Item -ItemType Directory -Path $output | Out-Null
New-Item -ItemType Directory -Path (Join-Path $output "Content"), (Join-Path $output "Config") | Out-Null
$projectFile = Join-Path $output "SpatialQuerySmoke.uproject"
@{
    FileVersion = 3
    Description = "Independent transient DCC-MCP spatial collision fixture"
    DisableEnginePluginsByDefault = $true
    Plugins = @(
        @{ Name = "PythonScriptPlugin"; Enabled = $true },
        @{ Name = "EditorScriptingUtilities"; Enabled = $true },
        @{ Name = "DccMcpUnreal"; Enabled = $false },
        @{ Name = "Fab"; Enabled = $false }
    )
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $projectFile -Encoding utf8
@'
[/Script/EngineSettings.GameMapsSettings]
EditorStartupMap=/Engine/Maps/Entry
GameDefaultMap=/Engine/Maps/Entry
'@ | Set-Content -LiteralPath (Join-Path $output "Config\DefaultEngine.ini") -Encoding utf8
$result = Join-Path $output "spatial-result.json"
$log = Join-Path $output "editor.log"
$runnerReceipt = Join-Path $output "runner.json"
$head = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Could not read product Git HEAD" }
$environment = @{
    DCC_MCP_SPATIAL_SOURCE_ROOT = $repoRoot
    DCC_MCP_SPATIAL_PYTHON_PAYLOAD = $payload
    DCC_MCP_SPATIAL_EXPECTED_CORE_VERSION = $ExpectedCoreVersion
    DCC_MCP_SPATIAL_PRODUCT_HEAD = $head
    DCC_MCP_SPATIAL_UE_ROOT = $engineRoot
    DCC_MCP_SPATIAL_RESULT = $result
    DCC_MCP_DISABLE_TELEMETRY = "1"
    DCC_MCP_DISABLE_JOB_PERSISTENCE = "1"
    DCC_MCP_DISABLE_FILE_LOGGING = "1"
    DCC_MCP_UNREAL_DISABLE_MENUS = "1"
    PYTHONPATH = ""
    UE_PYTHONPATH = ""
}
$previousEnvironment = @{}
$ueArgs = @(
    $projectFile, "-ExecutePythonScript=$scriptPath",
    "-unattended", "-NullRHI", "-nosound", "-nop4", "-NoSplash",
    "-stdout", "-FullStdOutLogOutput"
)
$run = @{
    success = $false
    engine_root = $engineRoot
    engine_build = $engineBuild
    product_head = $head
    python_payload = $payload
    expected_core_version = $ExpectedCoreVersion
    command = $editorCmd
    arguments = $ueArgs
    result = $result
    log = $log
    started_at = [DateTime]::UtcNow.ToString("o")
}
try {
    foreach ($key in $environment.Keys) {
        $previousEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, $environment[$key], "Process")
    }
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $editorCmd @ueArgs *> $log
        $run.exit_code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($run.exit_code -ne 0) { throw "Spatial Editor exited with code $($run.exit_code)" }
    if (-not (Test-Path -LiteralPath $result)) { throw "Spatial Editor did not write its JSON receipt" }
    $data = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
    if ($data.success -isnot [bool] -or $data.success -ne $true) {
        throw "Spatial fixture reported failure; inspect $result"
    }
    $run.success = $true
} catch {
    $run.error = $_.Exception.Message
    if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 80 }
    throw
} finally {
    foreach ($key in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($key, $previousEnvironment[$key], "Process")
    }
    $run.finished_at = [DateTime]::UtcNow.ToString("o")
    $run | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runnerReceipt -Encoding utf8
}
Write-Output "Spatial fixture passed: $result"
Write-Output "Editor invocation evidence: $runnerReceipt"
