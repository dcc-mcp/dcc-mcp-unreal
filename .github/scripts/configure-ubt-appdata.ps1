[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$UEVersion,

    [string]$EnvironmentFile = $env:GITHUB_ENV
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw "RUNNER_TEMP is required"
}
if ([string]::IsNullOrWhiteSpace($EnvironmentFile)) {
    throw "GITHUB_ENV or -EnvironmentFile is required"
}

$runId = if ($env:GITHUB_RUN_ID) { $env:GITHUB_RUN_ID } else { "local" }
$attempt = if ($env:GITHUB_RUN_ATTEMPT) { $env:GITHUB_RUN_ATTEMPT } else { "1" }
$appData = Join-Path $env:RUNNER_TEMP "dcc-mcp-unreal-ubt\$runId-$attempt-ue$UEVersion"
$configDir = Join-Path $appData "Unreal Engine\UnrealBuildTool"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

if ($UEVersion -eq "5.2") {
    $configPath = Join-Path $configDir "BuildConfiguration.xml"
    @"
<?xml version="1.0" encoding="utf-8" ?>
<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">
    <WindowsPlatform>
        <CompilerVersion>14.36.32532</CompilerVersion>
    </WindowsPlatform>
</Configuration>
"@ | Set-Content $configPath -Encoding utf8
    Write-Host "Pinned UE 5.2 to MSVC 14.36 in isolated UBT config: $configPath"
}

"DCC_MCP_UNREAL_UBT_APPDATA=$appData" | Out-File -FilePath $EnvironmentFile -Encoding utf8 -Append
Write-Host "Isolated UBT APPDATA: $appData"
