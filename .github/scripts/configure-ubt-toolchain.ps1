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

# UE 5.5/5.6 read this native, process-scoped contract at the UBT entrypoint.
"UBT_EXTRA_ARGS=-NoUBA -MaxParallelActions=1" |
    Out-File -FilePath $EnvironmentFile -Encoding utf8 -Append
Write-Host "Configured UE $UEVersion with bounded UBT command-line arguments"
