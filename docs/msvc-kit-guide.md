# MSVC-Kit Guide for dcc-mcp-unreal CI

[msvc-kit](https://github.com/loonghao/msvc-kit) is a portable MSVC Build Tools
installer and manager for Windows. In the `dcc-mcp-unreal` CI pipeline
(`build-uplugin.yml`), it provides the MSVC 14.36 toolchain required by
UE 5.2's Unreal Build Tool (UBT) for native C++ plugin compilation.

---

## Why msvc-kit in UE CI?

UBT discovers compilers through the **Visual Studio Setup API**, not through
`PATH` or environment variables. On the `ue-builder` self-hosted runner:

- VS 2022 BuildTools ships with **MSVC 14.44**, which is incompatible with
  UE 5.2 engine headers (`ConcurrentLinearAllocator.h` fails with C4668
  `__has_feature`).
- UE 5.2 expects **MSVC 14.36** (specified via `vctoolchain_version: "14.36"`
  in the workflow matrix).
- msvc-kit downloads the correct 14.36 toolchain and registers it with VS so
  UBT can discover and use it.

---

## Installation

### Winget (Recommended)

```powershell
winget install loonghao.msvc-kit
```

### PowerShell One-Liner

```powershell
irm https://github.com/loonghao/msvc-kit/releases/latest/download/install.ps1 | iex
```

### Pre-built Binary (CI Pattern)

The CI workflow downloads a specific version directly:

```powershell
$msvcKitVersion = "v0.2.13"
$msvcKitExe = "C:\msvc-kit\bin\msvc-kit.exe"
$exeUrl = "https://github.com/loonghao/msvc-kit/releases/download/$msvcKitVersion/msvc-kit-x86_64-windows.exe"

New-Item -ItemType Directory -Force -Path "C:\msvc-kit\bin" | Out-Null
Invoke-WebRequest -Uri $exeUrl -OutFile $msvcKitExe -UseBasicParsing
```

### Cargo

```bash
cargo install msvc-kit
```

---

## Core Commands

### `download` — Fetch MSVC toolchain

```powershell
# Download MSVC 14.36 for x64 (skip Windows SDK)
msvc-kit download --msvc-version 14.36 --no-sdk --dir C:\msvc-kit\14.36 --arch x64

# Download latest (MSVC + SDK) to default location
msvc-kit download
```

### `setup` — Generate environment activation script

```powershell
# PowerShell: generate script and execute in one step
$envScript = & msvc-kit setup --script --shell powershell --dir C:\msvc-kit\14.36
if ($LASTEXITCODE -ne 0) { throw "msvc-kit setup failed (exit code $LASTEXITCODE)" }
Invoke-Expression ($envScript -join "`n")   # ← CRITICAL: use -join for array output

# CMD
msvc-kit setup --script --shell cmd --dir C:\msvc-kit\14.36 > setup.bat && setup.bat

# Bash/WSL
eval "$(msvc-kit setup --script --shell bash --dir C:\msvc-kit\14.36)"
```

### `list` — Show installed/available versions

```powershell
msvc-kit list              # Installed versions
msvc-kit list --available  # Available from Microsoft
```

### `install-into-vs` — Register toolchain with Visual Studio (future)

> **Status: planned feature.** Currently under development in msvc-kit.

```powershell
# Check VS-registered MSVC versions
msvc-kit install-into-vs --check

# Install a downloaded toolchain into VS (requires admin)
msvc-kit install-into-vs --dir C:\msvc-kit\14.36

# Auto-find latest downloaded version and install
msvc-kit install-into-vs --auto
```

This is the definitive solution for UBT discovery: the command copies the
msvc-kit-downloaded toolchain into `%VS_PATH%\VC\Tools\MSVC\<version>\`,
making it visible to UBT through the VS Setup API. Requires administrator
privileges (one-time only).

Until this feature ships, the CI workflow uses one of the fallback strategies
described below.

---

## CI Workflow Integration Pattern

The full msvc-kit integration in `build-uplugin.yml` follows a three-tier
fallback strategy to make MSVC 14.36 available to UBT:

### Tier 1: VS Installer (native component)

```powershell
$vsInstaller = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vs_installer.exe"
if (Test-Path $vsInstaller) {
    & $vsInstaller modify --installPath "$vsToolsRoot" `
        --add "Microsoft.VisualStudio.Component.VC.14.36.17.6.x86.x64" `
        --passive --norestart --wait
}
```

### Tier 2: Directory Junction / Copy

```powershell
# Register msvc-kit toolchain with VS via directory junction
$kitToolchainRoot = "$msvcTargetDir\VC\Tools\MSVC"
$vsToolchainRoot = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC"

Get-ChildItem $kitToolchainRoot | ForEach-Object {
    $target = Join-Path $vsToolchainRoot $_.Name
    if (-not (Test-Path $target)) {
        try {
            # Prefer junction — no copy overhead
            New-Item -ItemType Junction -Path $target -Target $_.FullName -Force -ErrorAction Stop | Out-Null
        } catch {
            # Fallback to copy
            Copy-Item -Path $_.FullName -Destination $target -Recurse -Force
        }
    }
}
```

### Tier 3: Environment Activation (job-scoped)

After the toolchain is registered, activate it in the current job:

```powershell
$envScript = & $msvcKitExe setup --script --shell powershell --dir $msvcTargetDir
if ($LASTEXITCODE -ne 0) { throw "msvc-kit setup failed (exit code $LASTEXITCODE)" }
Invoke-Expression ($envScript -join "`n")
```

### End-to-End CI Step

The workflow step `"Ensure MSVC 14.36 toolchain (UE 5.2)"` in
`.github/workflows/build-uplugin.yml` combines all three tiers. It:

1. Checks if MSVC 14.36 is already registered with VS (fast path)
2. Attempts VS installer component install (admin-required, persistent)
3. Falls back to msvc-kit download + junction/copy registration
4. Activates the environment for the current job

---

## Critical Gotcha: `Invoke-Expression` and Array Output

### The Problem

`msvc-kit setup --script --shell powershell` outputs multiple lines.
PowerShell captures multi-line stdout as a `System.Object[]` array:

```powershell
# WRONG — $envScript is array, Invoke-Expression expects string
$envScript = & msvc-kit setup --script --shell powershell --dir C:\msvc-kit\14.36
Invoke-Expression $envScript   # ❌ Cannot convert System.Object[] to String
```

### The Fix

Join array elements with newlines before passing to `Invoke-Expression`:

```powershell
# CORRECT
$envScript = & msvc-kit setup --script --shell powershell --dir C:\msvc-kit\14.36
if ($LASTEXITCODE -ne 0) { throw "msvc-kit setup failed (exit code $LASTEXITCODE)" }
Invoke-Expression ($envScript -join "`n")   # ✅
```

This fix has been applied to `build-uplugin.yml` as of commit `7af130e`.

---

## Matrix Configuration Reference

The `build-uplugin` workflow uses a matrix to build for multiple UE versions.
MSVC 14.36 is only needed for UE 5.2:

```yaml
strategy:
  matrix:
    include:
      # UE 5.7: uses VS-default MSVC 14.44 — no msvc-kit needed
      - ue_version: "5.7"
        ue_root: C:\Program Files\Epic Games\UE_5.7
        package_mode: native
        artifact_suffix: win64

      # UE 5.2: requires MSVC 14.36 — msvc-kit download + register
      - ue_version: "5.2"
        ue_root: C:\Program Files\Epic Games\UE_5.2
        package_mode: native
        artifact_suffix: win64
        vctoolchain_version: "14.36"

      # UE 4.18: python-only — no C++ compilation needed
      - ue_version: "4.18"
        ue_root: C:\Program Files\Epic Games\UE_4.18
        package_mode: python-only
        artifact_suffix: python-only
```

The `Ensure MSVC 14.36 toolchain` step is gated by
`if: matrix.vctoolchain_version != ''`, so it only runs for UE 5.2.

---

## Troubleshooting

### C4668 `__has_feature` is undefined

```
ConcurrentLinearAllocator.h(31): error C4668: '__has_feature' is not defined
```

**Root cause**: UBT selected MSVC 14.44 (from VS 2022 BuildTools) to compile
UE 5.2 engine headers. 14.44 enforces C4668 as an error under `/WX`.

**Solutions** (in priority order):

1. **Install VC 14.36 component** (one-time admin):
   ```powershell
   & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vs_installer.exe" `
       modify --installPath "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools" `
       --add Microsoft.VisualStudio.Component.VC.14.36.17.6.x86.x64 `
       --passive --norestart --wait
   ```

2. **`install-into-vs`** (when available):
   ```powershell
   msvc-kit install-into-vs --dir C:\msvc-kit\14.36
   ```

3. **Junction registration** (what CI does today):
   See Tier 2 above — creates a directory junction from msvc-kit's toolchain
   into VS's `VC\Tools\MSVC\` directory.

### msvc-kit download fails

- Ensure the runner can reach `github.com` (release assets)
- Check available disk space on `C:` (~2 GB needed)
- Set `RUST_LOG=debug` for detailed download logs
- Clear cache: `msvc-kit clean --all --cache`

### msvc-kit setup exit code 2

Older msvc-kit versions used `--target` instead of `--dir`. Ensure `v0.2.13+`
is used and the flag is `--dir`:

```powershell
# v0.2.13+ (correct)
msvc-kit setup --script --shell powershell --dir C:\msvc-kit\14.36

# older versions (removed)
msvc-kit setup --script --shell powershell --target C:\msvc-kit\14.36
```

### Permission denied on junction / copy

The runner account (NetworkService) may not have write access to
`C:\Program Files (x86)\Microsoft Visual Studio\`. Either:

- Grant the runner account write permission to `VC\Tools\MSVC\`
- Use `install-into-vs` (elevated, one-time)
- Install the VC 14.36 component via VS installer (elevated, one-time)

---

## Version Pinning

The CI workflow hardcodes `msvc-kit v0.2.13`. When upgrading:

1. Check the [releases page](https://github.com/loonghao/msvc-kit/releases)
   for the latest version
2. Update `$msvcKitVersion` in the workflow
3. Verify the `--help` output for any flag changes (e.g. `--target` → `--dir`)
4. Trigger a `workflow_dispatch` build to validate

Consider setting up [Renovate](https://github.com/renovatebot/renovate) to
automate version bump PRs (the repo already has `renovate.json`).

---

## Related Resources

- [msvc-kit GitHub](https://github.com/loonghao/msvc-kit) — source, releases, issues
- [msvc-kit crates.io](https://crates.io/crates/msvc-kit) — Rust library API
- [build-uplugin.yml](../.github/workflows/build-uplugin.yml) — CI workflow using msvc-kit
- [UE 5.2 Release Notes](https://docs.unrealengine.com/5.2/) — supported toolchains
- [MSVC Version Reference](https://learn.microsoft.com/en-us/visualstudio/releases/2022/compatibility) — VS 2022 component IDs
