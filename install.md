# Install dcc-mcp-unreal

This runbook installs, verifies, upgrades, and removes the DCC-MCP project
plugin for Unreal Engine. The `dcc-mcp-unreal` command is plan-first and writes
only after `--yes` is present.

## Requirements

- **Unreal Engine:** 4.18 or newer and one `.uproject` file.
- **Python:** 3.9 or newer for the adapter runtime. Use the selected engine's
  bundled Python for embedded mode; UE 4.x normally uses the standalone
  sidecar instead.
- **dcc-mcp-core:** 0.20.13 or newer. Install SOP schema export remains
  blocked on `dcc-mcp/dcc-mcp-core#2320`; current adapter tests validate the
  exact reviewed Draft 2020-12 schema fixture until that API is released.
- **Platforms:** the lifecycle command and source project-plugin payload work
  on Windows, macOS, and Linux. Published precompiled uplugin ZIPs are Win64.
  The no-system-Python one-command installer is Windows PowerShell only;
  official release archives also contain macOS and Linux standalone binaries.
- **Permissions:** write access to `<Project>/Plugins`, the `.uproject` file,
  and `<Project>/.dcc-mcp/receipts`.

Install the wheel into the interpreter that will own the adapter runtime:

```bash
python -m pip install "dcc-mcp-unreal>=0.3.1,<1.0.0"
```

The standard lifecycle entry point begins with adapter release 0.3.1. Older
0.3.0 wheels use the legacy installation surfaces in `docs/installation.md`.

Do not use an arbitrary `python` on `PATH` for embedded mode. Resolution order
is `--python`, `DCC_MCP_INSTALL_PYTHON`, then the selected engine's bundled
Python. Host resolution is `--dcc-path`, `UE_ROOT`, then supported platform
install locations.

## Supported versions

| Unreal Engine | Runtime | Python | Plugin package |
|---|---|---|---|
| 4.18-4.26 | Native plugin plus standalone sidecar | External/standalone; internal 3.9+ builds may embed | Matching source build or Win64 release ZIP |
| 4.27 | Native plugin plus standalone sidecar by default | Stock 3.7 is unsupported | Matching source build or Win64 release ZIP |
| 5.0-5.2 | Embedded Python plus native plugin | Engine Python 3.9 | Project source payload or matching Win64 ZIP |
| 5.3-5.6 | Embedded Python plus native plugin | Engine Python 3.11 | Project source payload or matching Win64 ZIP |
| 5.7+ | Embedded Python plus native plugin; optional Epic MCP bridge on 5.8+ | Engine Python 3.12 in tested releases | Project source payload or matching Win64 ZIP |

The installer rejects hosts older than 4.18 and a numeric `.uproject`
`EngineAssociation` that does not match the selected engine's major/minor
version. New Unreal releases remain capability-gated until their native build
is validated.

## Agent quick path

Inspect the shared Core plan first:

```bash
dcc-mcp-cli install --dcc-type unreal
dcc-mcp-cli install --dcc-type unreal --execute --json
```

The adapter-owned vertical slice installs a project plugin and enables it in
the `.uproject` file:

```bash
dcc-mcp-unreal install \
  --dcc-path "/absolute/path/to/UE_5.7" \
  --python "/absolute/path/to/engine/python" \
  --project "/absolute/path/to/Game.uproject" \
  --json --dry-run

dcc-mcp-unreal install \
  --dcc-path "/absolute/path/to/UE_5.7" \
  --python "/absolute/path/to/engine/python" \
  --project "/absolute/path/to/Game.uproject" \
  --json --yes
```

`--dry-run` always wins over `--yes`. Every result follows Install SOP schema
v1 and has exactly one executable recovery step when a safe automatic action
is available. Stable exits are 0 (ok/plan), 10 (preflight), 20 (acquire), 30
(transaction), 40 (verify), and 50 (loaded artifact requires restart).

The receipt is `<Project>/.dcc-mcp/receipts/unreal.json`. It records the exact
editor image and digest, target interpreter and owned module origins,
Core/adapter versions, project registration digest, every owned file,
directory and safe relative link, bootstrap log directory, and the bound typed
readiness identity. It contains no credentials.

## Manual path

1. Install the wheel into the exact target interpreter.
2. Select the engine root and one matching `.uproject` file.
3. Run the JSON dry-run and review every path and step.
4. Run the same command with `--yes`.
5. The installer stages the complete plugin beside the destination, atomically
   replaces only receipted state, and adds `DccMcpUnreal` with `Enabled: true`
   to the project descriptor.
6. Start the selected project if the result returns the exact
   `launch-unreal-editor` command. The installer never drives the editor UI or
   terminates an Unreal process.
7. Copy the exact running instance UUID and run `verify --instance-id <UUID>`
   after the selected editor/plugin is ready.

For UE 4.x or another Pythonless runtime, acquire a specific official release;
never scrape or execute a mutable third-party payload. On Windows, download the
installer script from the same immutable tag and select the same tag:

```powershell
Invoke-WebRequest `
  https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-unreal/v0.3.0/scripts/install-standalone.ps1 `
  -OutFile install-standalone.ps1
.\install-standalone.ps1 -Version v0.3.0
```

That existing installer verifies every `SHA256SUMS` entry, rejects manifest
path escapes, runs the launcher `--version` self-check, and tests the native
`sidecar --help` handoff before replacing the standalone cache. The adapter
lifecycle command does not duplicate or weaken that acquisition boundary.

macOS/Linux users must manually select the versioned official standalone
archive and validate its bundled `SHA256SUMS`, or build the sidecar/plugin from
source with the matching Unreal toolchain. There is no automatic macOS/Linux
standalone provisioning in this repository.

## Verify

```bash
dcc-mcp-unreal verify \
  --dcc-path "/absolute/path/to/UE_5.7" \
  --python "/absolute/path/to/engine/python" \
  --project "/absolute/path/to/Game.uproject" \
  --instance-id "<exact-running-instance-uuid>" \
  --json
```

Verification checks the receipt, every plugin digest, the target-interpreter
adapter/Core imports and versions, `.uproject` enablement, captured bootstrap
errors, and finally Core's bounded readiness probe
`unreal_automation__mcp_self_check`. A copied plugin, running gateway, or
transport row alone is not `directly_usable: true`. The probe must bind the
selected instance UUID, PID, process-start token, editor image, project,
mounted plugin, engine version, and adapter/Core module origins.

Without a live licensed Unreal Editor, static install checks can succeed but
verification truthfully exits 40 with `failure_stage: readiness`. CI exercises
that boundary and does not claim a live-host result.

For a non-mutating state summary:

```bash
dcc-mcp-unreal status --dcc-path "/path/to/UE" --python "/path/to/python" --project "/path/to/Game.uproject" --json
```

## Upgrade

Stop work and save the project before changing a loaded native plugin. Upgrade
the wheel in the same target interpreter, review the plan, then execute:

```bash
python -m pip install --upgrade "dcc-mcp-unreal>=0.3.1,<1.0.0"
dcc-mcp-unreal upgrade --dcc-path "/path/to/UE" --python "/path/to/python" --project "/path/to/Game.uproject" --json --dry-run
dcc-mcp-unreal upgrade --dcc-path "/path/to/UE" --python "/path/to/python" --project "/path/to/Game.uproject" --json --yes
```

The transaction moves the prior receipted plugin to a same-volume backup and
keeps the complete prior plugin, project descriptor, and receipt until an
exact-instance verify succeeds. A mismatched typed probe restores that prior
state. A real Windows file lock returns exit 50; close the reported editor and
repeat the command.

## Uninstall

```bash
dcc-mcp-unreal uninstall --dcc-path "/path/to/UE" --python "/path/to/python" --project "/path/to/Game.uproject" --json --dry-run
dcc-mcp-unreal uninstall --dcc-path "/path/to/UE" --python "/path/to/python" --project "/path/to/Game.uproject" --json --yes
python -m pip uninstall dcc-mcp-unreal
```

Uninstall consumes the receipt, restores the project's previous plugin entry,
and removes only the receipted plugin root. A complete recovery copy remains
available until deletion succeeds, so a partial delete failure restores every
owned byte. It refuses an unreceipted/partial install or a project entry
changed after installation. Repeating uninstall is safe and reports `absent`.

For the standalone cache, use `uninstall.bat` or `uninstall.sh` from the exact
downloaded release archive. Remove
`%LOCALAPPDATA%\dcc-mcp-unreal\standalone` only after the standalone process is
stopped; on macOS/Linux remove only the versioned directory you installed.

## Troubleshooting

| Result | Diagnosis | Action |
|---|---|---|
| Exit 10, host | No `Build.version`, Unreal older than 4.18, or project association mismatch | Pass the exact `--dcc-path` and matching `.uproject`. |
| Exit 10, Python/Core | Target import failed or Core is below 0.20.13 | Install the wheel/Core into the exact `--python` interpreter. |
| Exit 10, partial | Plugin and receipt disagree or ownership is unknown | Preserve the reported paths; do not delete unknown project content. |
| Exit 20 | Wheel plugin payload is absent or staged payload is invalid | Reinstall the official wheel from the pinned catalog digest. |
| Exit 30 | Staging, project registration, receipt commit, rollback, or uninstall failed | Preserve the JSON result and prior receipt; retry only its bounded command. |
| Exit 40, artifact | A receipted file is missing or its SHA-256 changed | Run a reviewed `install --yes` repair transaction. |
| Exit 40, bootstrap | The startup hook captured an early exception | Inspect `<Project>/.dcc-mcp/bootstrap-errors/dcc-mcp-unreal.*.host-errors.log`. |
| Exit 40, readiness | No exact-instance typed self-check succeeded | Execute the returned editor launch command, obtain that instance UUID, then rerun `verify --instance-id <UUID>`. |
| Exit 50 | Unreal has a native artifact loaded/locked | Save work, close only the reported Unreal Editor, and repeat the same command. |

Shared diagnosis remains read-only:

```bash
dcc-mcp-cli doctor
dcc-mcp-cli list
```

The Core-owned catalog still needs to change its `instructions_url` to:

```text
https://raw.githubusercontent.com/dcc-mcp/dcc-mcp-unreal/main/install.md
```
