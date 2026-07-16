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
# This final override prevents a stale per-user compiler pin from winning.
$compilerVersion = "Latest"
"UnrealBuildTool_WindowsPlatform__CompilerVersion=$compilerVersion" |
    Out-File -FilePath $EnvironmentFile -Encoding utf8 -Append
Write-Host "Configured UE $UEVersion to use MSVC toolchain $compilerVersion"
