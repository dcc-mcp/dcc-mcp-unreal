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

if ($UEVersion -ne "5.7") {
    Write-Host "No job-scoped UnrealBuildTool compiler override configured for UE $UEVersion"
    return
}

# UE 5.7 loads UnrealBuildTool_* environment settings after user XML files.
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
