# Runner Admin Setup: UE 5.2 + MSVC 14.44 Compatibility

The `ue-builder` GitHub Actions self-hosted runner runs as `NetworkService`,
which **cannot write** to `C:\Program Files\Epic Games\UE_5.2\`. Since the
runner cannot install MSVC 14.36 **or** patch engine headers at CI runtime,
the UE 5.2 build requires a **one-time manual patch** on the runner machine.

## Apply the patches

On the `ue-builder` machine, **run as Administrator**:

### 1. Patch ConcurrentLinearAllocator.h

File: `C:\Program Files\Epic Games\UE_5.2\Engine\Source\Runtime\Core\Public\Experimental\ConcurrentLinearAllocator.h`

Replace every `#if __has_feature(` with `#if defined(__has_feature) && __has_feature(`.

```powershell
$path = "C:\Program Files\Epic Games\UE_5.2\Engine\Source\Runtime\Core\Public\Experimental\ConcurrentLinearAllocator.h"
$content = Get-Content $path -Raw
$content = $content -replace '#if\s+__has_feature\(', '#if defined(__has_feature) && __has_feature('
Set-Content $path -Value $content -NoNewline
Write-Host "Patched ConcurrentLinearAllocator.h"
```

### 2. Patch WindowsPlatformCompilerSetup.h

File: `C:\Program Files\Epic Games\UE_5.2\Engine\Source\Runtime\Core\Public\Windows\WindowsPlatformCompilerSetup.h`

Replace the `#if _MSC_FULL_VER > ...` block with a comment and create the
marker file so the CI verify step passes.

```powershell
$path = "C:\Program Files\Epic Games\UE_5.2\Engine\Source\Runtime\Core\Public\Windows\WindowsPlatformCompilerSetup.h"
$marker = "C:\Program Files\Epic Games\UE_5.2\Engine\Source\Runtime\Core\Public\Windows\.patched-for-msvc14.44"
$lines = Get-Content $path
$inBlock = $false
$newLines = @()
foreach ($line in $lines) {
  if ($line -match '_MSC_FULL_VER\s*>\s*\d+' -and $line -match '^\s*#\s*if') {
    $inBlock = $true
    $newLines += '// Pre-patched for MSVC 14.44 compatibility by dcc-mcp-unreal runner admin'
    continue
  }
  if ($inBlock) {
    if ($line -match '^\s*#\s*endif') { $inBlock = $false }
    continue
  }
  $newLines += $line
}
$newLines -join "`n" | Set-Content $path -NoNewline
New-Item -ItemType File -Path $marker -Force | Out-Null
Write-Host "Patched WindowsPlatformCompilerSetup.h"
```

### 3. Verify

Re-run the workflow from GitHub Actions UI or push a test commit. The
"Verify UE 5.2 engine headers" step should pass (read-only check).
