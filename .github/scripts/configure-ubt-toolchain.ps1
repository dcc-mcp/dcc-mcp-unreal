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

# UE5 loads UnrealBuildTool_* environment settings after user XML files. Keep
# peak memory bounded for every supported UE5 build on shared self-hosted runners.
$settings = @(
    "UnrealBuildTool_BuildConfiguration__bAllowUBAExecutor=false"
    "UnrealBuildTool_BuildConfiguration__MaxParallelActions=1"
)
if ($UEVersion -in @("5.7", "5.8")) {
    # Modern engines also need an explicit final override for stale compiler pins.
    $settings = @("UnrealBuildTool_WindowsPlatform__CompilerVersion=Latest") + $settings
}
$settings | Out-File -FilePath $EnvironmentFile -Encoding utf8 -Append
Write-Host "Configured UE $UEVersion with bounded local execution"
