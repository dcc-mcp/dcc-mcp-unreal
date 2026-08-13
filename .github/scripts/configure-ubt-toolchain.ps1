[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$UEVersion,

    [string]$EnvironmentFile = $env:GITHUB_ENV
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($EnvironmentFile)) {
    throw "GITHUB_ENV or -EnvironmentFile is required"
}

if ($UEVersion -notin @("5.5", "5.6", "5.7", "5.8")) {
    Write-Host "No job-scoped UnrealBuildTool compiler override configured for UE $UEVersion"
    return
}

if ($UEVersion -in @("5.7", "5.8")) {
    # Modern engines load these job-scoped settings after user XML files.
    @(
        "UnrealBuildTool_WindowsPlatform__CompilerVersion=Latest"
        "UnrealBuildTool_BuildConfiguration__bAllowUBAExecutor=false"
        "UnrealBuildTool_BuildConfiguration__MaxParallelActions=1"
    ) | Out-File -FilePath $EnvironmentFile -Encoding utf8 -Append
    Write-Host "Configured UE $UEVersion with bounded local execution"
    return
}

# UE 5.5/5.6 do not consume the environment override contract above. Isolate
# their XML config by switching APPDATA only for the subsequent build step.
if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    throw "RUNNER_TEMP is required for UE $UEVersion"
}
$runId = if ($env:GITHUB_RUN_ID) { $env:GITHUB_RUN_ID } else { "local" }
$attempt = if ($env:GITHUB_RUN_ATTEMPT) { $env:GITHUB_RUN_ATTEMPT } else { "1" }
$appData = Join-Path $env:RUNNER_TEMP "dcc-mcp-unreal-ubt\$runId-$attempt-ue$UEVersion"
$configDir = Join-Path $appData "Unreal Engine\UnrealBuildTool"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$configPath = Join-Path $configDir "BuildConfiguration.xml"
@"
<?xml version="1.0" encoding="utf-8" ?>
<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">
    <BuildConfiguration>
        <bAllowUBAExecutor>false</bAllowUBAExecutor>
        <MaxParallelActions>1</MaxParallelActions>
    </BuildConfiguration>
</Configuration>
"@ | Set-Content $configPath -Encoding utf8
"DCC_MCP_UNREAL_UBT_APPDATA=$appData" | Out-File -FilePath $EnvironmentFile -Encoding utf8 -Append
Write-Host "Configured isolated UE $UEVersion UBT settings: $configPath"
