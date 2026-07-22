[CmdletBinding()]
param(
    [string]$Version = "latest",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "dcc-mcp-unreal\standalone"),
    [string]$ArchivePath = "",
    [switch]$NoPersistEnvironment
)

$ErrorActionPreference = "Stop"
$repo = "dcc-mcp/dcc-mcp-unreal"
$install = [IO.Path]::GetFullPath($InstallDir)
$parent = Split-Path -Parent $install
if (-not $parent) { throw "InstallDir must have a parent directory: $install" }

$work = Join-Path ([IO.Path]::GetTempPath()) ("dcc-mcp-unreal-install-" + [guid]::NewGuid().ToString("N"))
$download = Join-Path $work "standalone.zip"
$staging = Join-Path $parent (".dcc-mcp-unreal-staging-" + [guid]::NewGuid().ToString("N"))
$backup = Join-Path $parent (".dcc-mcp-unreal-backup-" + [guid]::NewGuid().ToString("N"))

try {
    New-Item -ItemType Directory -Path $work, $staging -Force | Out-Null
    if ($ArchivePath) {
        Copy-Item -LiteralPath ([IO.Path]::GetFullPath($ArchivePath)) -Destination $download
    } else {
        $releaseUri = if ($Version -eq "latest") { "https://api.github.com/repos/$repo/releases/latest" } else { "https://api.github.com/repos/$repo/releases/tags/$Version" }
        $release = Invoke-RestMethod -Uri $releaseUri -Headers @{ Accept = "application/vnd.github+json" }
        $asset = @($release.assets) | Where-Object { $_.name -match '^dcc-mcp-unreal-v?.+-windows-X64\.zip$' } | Select-Object -First 1
        if (-not $asset) { throw "Windows standalone asset was not found in release $($release.tag_name)" }
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $download -UseBasicParsing
    }

    Expand-Archive -LiteralPath $download -DestinationPath $staging
    $manifest = Join-Path $staging "SHA256SUMS"
    $launcher = Join-Path $staging "dcc-mcp-unreal.exe"
    $server = Join-Path $staging "dcc-mcp-server.exe"
    foreach ($required in $manifest, $launcher, $server) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Archive is missing $(Split-Path -Leaf $required)" }
    }

    $verified = @{}
    foreach ($line in Get-Content -LiteralPath $manifest) {
        if (-not $line.Trim()) { continue }
        if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') { throw "Invalid SHA256SUMS line: $line" }
        $expected = $Matches[1]
        $relative = $Matches[2] -replace '/', '\'
        $candidate = [IO.Path]::GetFullPath((Join-Path $staging $relative))
        if (-not $candidate.StartsWith($staging + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "SHA256SUMS path escapes the archive: $relative" }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Manifest file is missing: $relative" }
        if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash -ne $expected) { throw "SHA-256 mismatch: $relative" }
        $verified[$relative.ToLowerInvariant()] = $true
    }
    foreach ($requiredName in "dcc-mcp-unreal.exe", "dcc-mcp-server.exe") {
        if (-not $verified.ContainsKey($requiredName)) { throw "SHA256SUMS does not cover $requiredName" }
    }

    & $launcher --version | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Standalone launcher smoke test failed with exit code $LASTEXITCODE" }

    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    if (Test-Path -LiteralPath $install) { Move-Item -LiteralPath $install -Destination $backup }
    Move-Item -LiteralPath $staging -Destination $install
    if (-not $NoPersistEnvironment) {
        [Environment]::SetEnvironmentVariable("DCC_MCP_SERVER_EXECUTABLE", (Join-Path $install "dcc-mcp-unreal.exe"), "User")
    }
    $env:DCC_MCP_SERVER_EXECUTABLE = Join-Path $install "dcc-mcp-unreal.exe"
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
    Write-Host "Installed standalone sidecar: $env:DCC_MCP_SERVER_EXECUTABLE"
} catch {
    if ((Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $install)) { Move-Item -LiteralPath $backup -Destination $install }
    throw
} finally {
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}
