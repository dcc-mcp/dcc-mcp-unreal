# Windows compiler and SDK contract

Native plugin packaging uses the installed engine's Unreal Build Tool (UBT).
UBT owns compiler compatibility and discovers Visual Studio through Microsoft's
Setup API. Activating a portable MSVC environment alone does not make its
compiler discoverable to UBT.

The current native CI matrix in [build-uplugin.yml](../.github/workflows/build-uplugin.yml)
builds UE 5.5, 5.7, 5.8, 4.18 and 4.26. It does not download msvc-kit, provision
UE 5.2's compiler, or modify Visual Studio installations. Provision compatible
toolsets on the runner before running a job.

## Engine-owned defaults

Without explicit version arguments, packaging lets the engine choose its
compiler and SDK. In particular, the UE 5.7/5.8 CI helper does not force `Latest`.
The engine's `Engine/Config/Windows/Windows_SDK.json` (where present), engine-local
UBT settings and its Windows platform implementation are the compatibility
source. Different engine patches and source forks can have different ranges;
there is no repository-wide "latest MSVC works everywhere" mapping.

The CI helper only limits build concurrency and disables UBA for the applicable
engine versions. It does not establish that a compiler is installed.

## Explicit compiler and SDK selection

```powershell
vx python packaging/build_distributable.py --ue-root F:\UE\UE_5.2 `
  --mode native --vctoolchain-version 14.36 --sdk-version 10.0.22621.0
```

These versions illustrate a caller-selected toolchain, not a universal UE
compatibility promise. Check the installed engine's requirements first.

An explicit compiler must be a numeric version or numeric prefix. Packaging
queries `vswhere` for all Visual Studio editions and custom installation paths
and requires an x64 `cl.exe` for that version. Missing discovery or a missing
compiler fails before UAT; it never silently chooses another compiler. The
version is applied as `-CompilerVersion`, because `-VCToolchainVersion` selects
the MSVC runtime used by a non-MSVC compiler in modern UBT.

An explicit SDK must be a complete version. Packaging applies `-WindowsSdkVersion`.
`BuildPlugin` does not forward arbitrary `-ubtargs`. Where the installed UBT
entrypoint exposes `UBT_EXTRA_ARGS`, packaging uses that subprocess contract;
otherwise it uses the guarded user XML fallback below. Prior environment
arguments are preserved and restored after the build.
Pinned builds retain the combined UAT output at
`dist/_uplugin_work/uat/uat-toolchain.log` and require every reported UBT
compiler/SDK selection to match the request. A successful UAT exit without
selection evidence does not satisfy this contract. MSVC's toolset family is
the VS directory version (for example `14.44.35207`); its compiler binary can
report a newer servicing patch (for example `14.44.35225`). Verification checks
the requested family against UBT's reported directory and records the actual
compiler patch separately.

## Optional msvc-kit diagnostics

[msvc-kit](https://github.com/loonghao/msvc-kit) can provision or diagnose an
isolated toolchain. Install or register it separately with the permissions
appropriate for the runner; packaging never modifies global VS installations.

When an explicitly supplied CLI supports `msvc-kit.doctor.v1`, opt in with:

```powershell
vx python packaging/build_distributable.py --ue-root F:\UE\UE_5.5 `
  --mode native --vctoolchain-version 14.38 --sdk-version 10.0.22621.0 `
  --msvc-kit C:\tools\msvc-kit.exe --msvc-kit-dir C:\tools\compiler
```

This runs JSON `doctor --compile` before UAT and stores
`dist/_uplugin_work/uat/toolchain-diagnostics.json`. A requested missing CLI,
unsupported schema or failed probe fails the build. The doctor verifies the
portable toolchain; VS discovery and UBT log verification separately establish
what the engine can actually use. No unreleased msvc-kit version is installed
by default. The equivalent environment variables are
`DCC_MCP_UNREAL_MSVC_KIT`, `DCC_MCP_UNREAL_MSVC_KIT_DIR` and
`DCC_MCP_UNREAL_SDK_VERSION`.

## Shared user configuration

UE 4 and UE 5.0–5.6 can inherit incompatible cross-version settings from
`%APPDATA%\Unreal Engine\UnrealBuildTool\BuildConfiguration.xml`.
Packaging serializes its UAT subprocesses using an OS process lock. For those
engines, it temporarily clears that file and restores it in `finally`. Explicit
pins use a minimal compiler/SDK XML when no native argument contract is available.
The original backup is beside the configuration, outside disposable build
directories, and the next build recovers it after an interrupted process.
External edits are preserved; the build fails and identifies the original
backup instead of overwriting them.

This lock coordinates this repository's builders. Unrelated UBT launches do
not participate; avoid running them simultaneously with a guarded legacy build.
Engine headers and global Visual Studio configuration remain outside this flow.

## Unreal Engine 4.18

Historical native validation used VS 2017 Build Tools and MSVC 14.16. Check the
installed engine and its SDK prerequisites before reusing that combination.
Legacy engines may require VS 2015/2017 discovery or Windows SDK 8.1; downloading
a current portable MSVC package is not a substitute for those requirements.

## Validation boundaries

Python contract tests exercise discovery, explicit selection, UBT log mismatch,
interprocess exclusion and configuration recovery. Native acceptance additionally
requires a real `BuildPlugin` result for each claimed engine. Runtime acceptance
requires loading the resulting plugin in that engine and is a separate check.
