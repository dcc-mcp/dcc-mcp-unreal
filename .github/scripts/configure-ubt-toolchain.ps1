[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$UEVersion,

    [string]$EnvironmentFile = $env:GITHUB_ENV,

    [string]$RunnerTemp = $env:RUNNER_TEMP
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($EnvironmentFile)) {
    throw "GITHUB_ENV or -EnvironmentFile is required"
}

if ($UEVersion -eq "4.18") {
    if ([string]::IsNullOrWhiteSpace($RunnerTemp)) {
        throw "RUNNER_TEMP or -RunnerTemp is required for UE 4.18"
    }

    # UE4 reads BuildConfiguration.xml from APPDATA before command-line
    # arguments. Isolate it from stale UE5 schemas on shared service accounts.
    $jobAppData = Join-Path $RunnerTemp "ue418-appdata"
    New-Item -ItemType Directory -Path $jobAppData -Force | Out-Null
    "APPDATA=$jobAppData" | Out-File -FilePath $EnvironmentFile -Encoding utf8 -Append
    Write-Host "Configured UE $UEVersion with isolated APPDATA: $jobAppData"
    return
}

if ($UEVersion -notin @("5.7", "5.8")) {
    Write-Host "No job-scoped UnrealBuildTool compiler override configured for UE $UEVersion"
    return
}

# UE 5.7+ loads UnrealBuildTool_* environment settings after user XML files.
# The final overrides prevent stale compiler pins and keep peak memory bounded
# on shared self-hosted runners.
$compilerVersion = "Latest"
@(
    "UnrealBuildTool_WindowsPlatform__CompilerVersion=$compilerVersion"
    "UnrealBuildTool_BuildConfiguration__bAllowUBAExecutor=false"
    "UnrealBuildTool_BuildConfiguration__MaxParallelActions=1"
) |
    Out-File -FilePath $EnvironmentFile -Encoding utf8 -Append
Write-Host "Configured UE $UEVersion to use MSVC $compilerVersion with bounded local execution"
