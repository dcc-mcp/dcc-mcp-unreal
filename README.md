# dcc-mcp-unreal

> **Status**: Pre-Alpha — placeholder / scaffold. Core skill authoring API is
> functional; full Unreal Engine integration requires iterative testing inside UE5.

<!-- Badges (fill in once CI is configured) -->
<!-- ![PyPI](https://img.shields.io/pypi/v/dcc-mcp-unreal) -->
<!-- ![Python](https://img.shields.io/pypi/pyversions/dcc-mcp-unreal) -->
<!-- ![License](https://img.shields.io/github/license/loonghao/dcc-mcp-unreal) -->

Unreal Engine plugin for the **DCC Model Context Protocol (MCP)** ecosystem.
Embeds a standards-compliant MCP Streamable HTTP server (2025-03-26 spec)
directly inside Unreal Engine using the current
[dcc-mcp-core](https://github.com/loonghao/dcc-mcp-core).

MCP-compatible agents (Claude Desktop, Cursor, OpenClaw, …) can call Unreal
Editor operations as **tools** — list actors, spawn blueprints, batch-process
assets, run Python scripts — all through a single HTTP endpoint.

---

## Overview

`dcc-mcp-unreal` follows the same architecture as
[dcc-mcp-maya](https://github.com/loonghao/dcc-mcp-maya):

```
Agent (Claude / Cursor)
    │  MCP tools/call  (HTTP POST /mcp)
    ▼
UnrealMcpServer  ←  dcc-mcp-core DccServerBase  ←  SkillCatalog
    │
    ▼  in-process HostExecutionBridge
Python skill scripts  →  Unreal main-thread dispatcher  →  Unreal Editor API
```

Each skill script is a standalone Python file that uses Unreal Engine's
`unreal` Python module. Scripts are discovered from `SKILL.md` plus sibling
`tools.yaml` metadata and exposed as MCP tools automatically.

---

## Features

- **Skills-First workflow** — drop a `SKILL.md` + `scripts/` directory anywhere
  and it becomes MCP tools automatically
- **Zero boilerplate** — use `@skill_entry`, `unreal_success()`, `unreal_error()`
  helpers identical in spirit to `dcc-mcp-maya`'s `@with_maya`, `maya_success()`
- **Hot-reload** — `SkillWatcher` detects `SKILL.md` changes without restart
  (future iteration)
- **Thread-safe singleton** — `start_server()` / `stop_server()` module helpers
  for easy use from Unreal's Python console
- **Configurable port** — default 8765, fully configurable
- **Built-in actor skill** — `unreal-actors` ships out of the box (list, spawn,
  delete, transform actors)

---

## Requirements

| Requirement | Version |
|-------------|---------|
| Unreal Engine | 5.0+ |
| Unreal Python Editor Script Plugin | must be **enabled** |
| Python (embedded in UE) | 3.9+ (UE 5.0 ships Python 3.9) |
| dcc-mcp-core | >= 0.17.20 |

### Enable the Python Plugin

1. Open your Unreal Engine project
2. **Edit → Plugins → search "Python"**
3. Enable **"Python Editor Script Plugin"**
4. Restart the editor

---

## Installation

### Inside Unreal Engine (recommended)

Copy or install `dcc-mcp-unreal` into Unreal's Python site-packages:

```bash
# Using pip with Unreal's bundled Python
"C:/Program Files/Epic Games/UE_5.4/Engine/Binaries/ThirdParty/Python3/Win64/python.exe" \
    -m pip install dcc-mcp-unreal
```

Or add it to the project's `Plugins/PythonScriptPlugin/Content/Python/` folder.

### Development install

```bash
git clone https://github.com/loonghao/dcc-mcp-unreal
cd dcc-mcp-unreal
pip install -e ".[dev]"
```

### Build a deployable UE 5.2 plugin package

The repo includes `vx just` recipes. By default they use
`C:\Program Files\Epic Games\UE_5.2` and install `dcc-mcp-core` from a
prebuilt wheel, which keeps CI/release packaging deterministic.

```bash
vx just package
```

Outputs use the standard Unreal project-plugin layout:

- `dist/DccMcpUnreal/DccMcpUnreal.uplugin`
- `dist/DccMcpUnreal/Content/Python/init_unreal.py`
- `dist/DccMcpUnreal/python/` — vendored Python package dependencies
- `dist/DccMcpUnreal-<version>-ue5.2.zip` — zipped plugin package

Deploy directly into a project:

```bash
vx just deploy "C:\Path\To\MyUnrealProject"
```

Run the packaged plugin inside a local UE project with `UnrealEditor-Cmd.exe`:

```bash
vx just ue-smoke "C:\Path\To\MyUnrealProject"
```

The smoke test runs the native Unreal Automation Test
`DccMcp.Smoke.ServerStarts`, verifies HTTP readiness, and confirms the built-in
Unreal tools are registered. It writes UE Automation reports under
`Saved/Automation/Reports`.

For direct Python-script debugging, bypass the native Automation layer:

```bash
vx just ue-smoke-python "C:\Path\To\MyUnrealProject"
```

Override paths when needed:

```bash
set UE_ROOT=C:\Program Files\Epic Games\UE_5.7
vx just package
```

To test an unpublished local core checkout, use the source-build path
explicitly:

```bash
set DCC_MCP_CORE_ROOT=G:\PycharmProjects\github\dcc-mcp-core
vx just package-local-core
```

---

## Quick Start

Open Unreal Engine's **Output Log** → **Python** console (or use the Python
Script Plugin terminal):

```python
import dcc_mcp_unreal

# Start the MCP server on port 8765
handle = dcc_mcp_unreal.start_server(port=8765)
print(handle.mcp_url())  # http://127.0.0.1:8765/mcp

# Connect your MCP agent to the URL above.
# When done:
handle.shutdown()
```

Point your MCP host at `http://127.0.0.1:8765/mcp`.

### Available tools (built-in)

| Tool name | Description |
|-----------|-------------|
| `unreal_actors__list_actors` | List all actors in the current level |
| `unreal_actors__spawn_actor` | Spawn an actor by class at a world position |
| `unreal_automation__mcp_self_check` | Validate the active MCP server without restarting it |
| `unreal_automation__list_automation_tests` | List native Unreal Automation tests |
| `unreal_automation__queue_automation_tests` | Queue native Unreal Automation tests from MCP |

---

## Skill Authoring Guide

Skills are directories containing a `SKILL.md` metadata file and a `scripts/`
subdirectory with Python files.

### Directory layout

```
my-unreal-skill/
├── SKILL.md
└── scripts/
    ├── my_tool.py
    └── another_tool.py
```

### SKILL.md format

```yaml
---
name: my-unreal-skill
description: "What this skill does"
license: "MIT"
allowed-tools: Bash Read
metadata:
  dcc-mcp:
    dcc: unreal
    version: "1.0.0"
    layer: domain
    tags: "unreal, my-tag"
    tools: tools.yaml
---
```

Declare MCP tools in a sibling `tools.yaml`:

```yaml
tools:
  - name: my_tool
    description: Do something in the Unreal Editor.
    source_file: scripts/my_tool.py
    execution: sync
    affinity: main
    enforce_thread_affinity: false
    read_only: false
    destructive: false
    idempotent: false
    input_schema:
      type: object
      properties:
        param:
          type: string
```

### Script pattern (recommended)

```python
"""Short description of what this script does."""
from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success


@skill_entry
def my_tool(param: str = "default", **kwargs) -> dict:
    """Do something in Unreal Engine.

    Args:
        param: Description of param.
    """
    import unreal  # imported inside — @skill_entry catches ImportError automatically

    # ... do work using unreal module ...
    result_value = f"processed {param}"

    return skill_success(
        f"Completed: {result_value}",
        prompt="Verify the result in the Unreal Editor viewport.",
        result=result_value,
    )


def main(**kwargs) -> dict:
    """Entry point; delegates to my_tool."""
    return my_tool(**kwargs)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main
    run_main(main)
```

### Error handling

```python
from dcc_mcp_unreal.api import unreal_success, unreal_error, unreal_from_exception

def risky_operation(asset_path: str = "/Game/MyAsset", **kwargs) -> dict:
    try:
        import unreal
        asset = unreal.load_asset(asset_path)
        if asset is None:
            return unreal_error(
                f"Asset not found: {asset_path}",
                f"unreal.load_asset returned None for '{asset_path}'",
                prompt="Check the asset path in the Content Browser.",
                possible_solutions=[
                    "Verify the asset exists at the given path",
                    "Use the Content Browser to find the correct path",
                ],
            )
        # ... process asset ...
        return unreal_success("Asset processed", asset_path=asset_path)
    except ImportError:
        return unreal_error("Unreal Engine not available", "ImportError: unreal module not found")
    except Exception as exc:
        return unreal_from_exception(exc, f"Failed to process {asset_path}")
```

### Loading custom skills

```python
import dcc_mcp_unreal

handle = dcc_mcp_unreal.start_server(
    port=8765,
    extra_skill_paths=["/my/studio/unreal-skills", "/shared/pipeline/skills"],
)
```

Or use the environment variable:

```bash
set DCC_MCP_UNREAL_SKILL_PATHS=C:\my\studio\unreal-skills;C:\shared\skills
```

---

## Architecture Overview

```
dcc-mcp-unreal
├── src/dcc_mcp_unreal/
│   ├── __init__.py          ← Public API: start_server, stop_server, helpers
│   ├── server.py            ← DccServerBase adapter, dispatcher, start/stop
│   ├── api.py               ← unreal_success/error/from_exception, with_unreal
│   └── skills/              ← Built-in skill packages
│       └── unreal-actors/
│           ├── SKILL.md
│           ├── tools.yaml
│           └── scripts/
│               ├── list_actors.py
│               └── spawn_actor.py
└── tests/
    └── test_server.py       ← Unit tests (no real UE required)
```

### Layered architecture

```
dcc-mcp-unreal          (this package)
    └── dcc-mcp-core    (Rust core: HTTP server, skill discovery, dispatch)
            └── unreal  (Unreal Engine Python API — only available inside UE)
```

`dcc-mcp-core` handles all MCP protocol plumbing. `dcc-mcp-unreal` only
provides:
1. Unreal-specific path resolution for the skills directory
2. Unreal main-thread dispatch for in-process skill execution
3. Convenience helpers (`unreal_success`, `@with_unreal`, etc.)
4. Built-in skills for common Unreal operations

---

## Roadmap

### v0.1.0 — Scaffold (current)
- [x] Project structure mirroring `dcc-mcp-maya`
- [x] `unreal_success` / `unreal_error` / `unreal_from_exception` helpers
- [x] `@with_unreal` decorator
- [x] `UnrealMcpServer` adapter built on `DccServerBase`
- [x] `unreal-actors` skill (list, spawn)
- [x] Unit tests (no real UE required)

### v0.2.0 — Core skills
- [ ] `unreal-assets` — Content Browser operations (import, export, list)
- [ ] `unreal-materials` — Material instance management
- [ ] `unreal-blueprints` — Blueprint variable get/set
- [ ] `unreal-level` — Level streaming, world settings
- [ ] `unreal-rendering` — Movie Render Queue integration

### v0.3.0 — Editor integration
- [ ] Unreal Editor toolbar button to start/stop MCP server
- [ ] UE5 plugin wrapper (`.uplugin`) for one-click installation
- [ ] Auto-start on editor startup via `EditorStartupScript`
- [ ] Level Sequence / Sequencer tools

### v1.0.0 — Production ready
- [ ] Full test suite with `unreal` mock
- [ ] CI via GitHub Actions (headless UE testing)
- [ ] PyPI release
- [ ] Comprehensive documentation

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-skill`
3. Add your skill under `src/dcc_mcp_unreal/skills/`
4. Add tests under `tests/`
5. Run `ruff check . && pytest`
6. Open a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

## Related Projects

| Project | Description |
|---------|-------------|
| [dcc-mcp-core](https://github.com/loonghao/dcc-mcp-core) | Core MCP infrastructure (Rust + PyO3) |
| [dcc-mcp-maya](https://github.com/loonghao/dcc-mcp-maya) | Maya MCP adapter |
| [dcc-mcp-photoshop](https://github.com/loonghao/dcc-mcp-photoshop) | Photoshop MCP adapter (bridge) |
| [dcc-mcp-zbrush](https://github.com/loonghao/dcc-mcp-zbrush) | ZBrush MCP adapter (HTTP bridge) |
