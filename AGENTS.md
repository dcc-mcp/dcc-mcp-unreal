# AGENTS.md — dcc-mcp-unreal

> Unreal Engine adapter for the DCC Model Context Protocol — an MCP server that
> runs inside Unreal (embedded Python) or beside it (native standalone sidecar).
> Navigation map for AI agents, not a reference manual. Follow the links; do not
> read everything up front.

## Build & test

```bash
vx just doctor    # print the UE / toolchain paths packaging will use
vx just test      # run the pytest suite
vx just check     # everything CI gates on: lint + test + validate-skills
```

The task runner is the capitalised `Justfile`; list every recipe with
`vx just`. Verified recipes: `lint` (`lint_skills.py` + `ruff check .`),
`validate-skills`, `uplugin` (distributable `.uplugin` zip), `uplugin-source`,
`uplugin-python-only`, `download-core-wheel`,
`install-engine` / `install-project <project>`, `ue-smoke`,
`ue-smoke-python`, `ue-niagara-smoke`, `ue-niagara-commandlet`.

Packaging is driven by environment variables, not by editing the `Justfile`:

| Variable | Default | Role |
|---|---|---|
| `UE_VERSION` | `5.7` | Selects `UE_ROOT` when that is unset |
| `UE_ROOT` | `C:\Program Files\Epic Games\UE_<UE_VERSION>` | Engine to package against |
| `DCC_MCP_UNREAL_PACKAGE_MODE` | `native` | `native` / `source` / `python-only` |
| `DCC_MCP_CORE_WHEEL` / `_URL` | empty | Reuse a built core wheel instead of a source build |
| `DCC_MCP_UNREAL_PYTHON_PLUGIN` | `PythonScriptPlugin` | Python plugin name (override on internal forks) |

`vx.toml` also pins `UE_5_ROOT`, `UE_5_2_ROOT`, `UE_4_ROOT`, `UE_4_26_ROOT` and
exposes `build-ue5.7` / `build-ue5.2` /
`build-ue4.18` / `build-ue4.26` scripts over `packaging/build_distributable.py`.

## Agent control path

AI agents drive Unreal through the shared gateway using the `dcc-mcp` skill and
`dcc-mcp-cli` REST commands:

```bash
dcc-mcp-cli list                                       # live sessions
dcc-mcp-cli dcc-types                                  # release-catalog support
dcc-mcp-cli search --query "<task>" --dcc-type unreal
dcc-mcp-cli describe <tool-slug>
dcc-mcp-cli call <tool-slug> --json '{"key":"value"}'
```

If a tool belongs to an inactive progressive skill, load it first:
`dcc-mcp-cli load-skill <skill-name> --dcc-type unreal`.

If `dcc-mcp-cli` is missing, obtain user consent before running the official
install commands in the README Agent workflow. Keep an official build current
with `dcc-mcp-cli update check` / `dcc-mcp-cli update apply` — `update apply`
stages the CLI for the next launch and does not update a running
`dcc-mcp-server`.

IDE users may configure the gateway MCP endpoint instead; adapter-local Python
start APIs are for host bootstrap and tests.

## Runtime chain

```
Agent (Claude / Cursor / Codex)
    │  dcc-mcp-cli or MCP
    ▼
Shared gateway  →  Unreal MCP instance  ←  SkillCatalog
    │
    ▼
Embedded Python | native sidecar | optional Epic MCP bridge
    │
    ▼
Unreal main thread  →  Unreal Editor API / Toolset Registry
```

Each skill is a standalone Python file that uses Unreal's `unreal` module.
Scripts are discovered from `SKILL.md` plus a sibling `tools.yaml` and exposed
as MCP tools automatically — prefer typed skills over raw scripting.

## Repo layout

| Path | Role |
|---|---|
| `src/dcc_mcp_unreal/` | Python package — server, install CLI, capability and compatibility layers |
| `src/dcc_mcp_unreal/skills/` | One directory per skill (`SKILL.md` + `tools.yaml` + scripts) |
| `tests/` | pytest suite; `tests/native/` holds the C++ shim and native cases |
| `packaging/` | `build_distributable.py`, `build_plugin.py`, install/uninstall scripts |
| `unreal/plugin/` | The `DccMcpUnreal` Unreal plugin (`Config`, `Content`, `Source`, `.uplugin`) |
| `tools/` | `lint_skills.py`, `build_binary.py` |
| `scripts/` | `run_ue_smoke.ps1`, `install-standalone.ps1`, `scripts/ci/` digest check |
| `docs/` | `installation.md`, `unreal-version-compatibility.md`, `msvc-kit-guide.md`, PRD |

## Release

- release-please drives versioning from Conventional Commits on `main`.
- `feat:` → minor, `fix:` → patch, `chore:`/`docs:`/`ci:` → **no release**.
- The version is mirrored into `pyproject.toml`,
  `src/dcc_mcp_unreal/__version__.py`, and
  `unreal/plugin/DccMcpUnreal.uplugin` (`$.VersionName`); do not edit those by
  hand.
- Use `chore:`/`docs:` for config and doc work so release-please does not cut a
  valueless version.

## Do / Don't

- **Do** single-source agent instructions here — this is the only agent contract
  file at the repo root. Rebase onto `main` before merging (no merge commits);
  CI must pass before review.
- **Do** target Python `>=3.9`; CI runs the suite on 3.9–3.12 across
  Linux, Windows, and macOS, plus a `core-latest` compatibility job against the
  newest published `dcc-mcp-core`.
- **Don't** add `CLAUDE.md` / `GEMINI.md` / `CURSOR.md` / `ANTHROPIC.md` /
  `OPENAI.md` / `COPILOT.md` / `CODEBUDDY.md` / `.cursorrules` / `.clinerules` /
  `.windsurfrules` at the root. Vendor-specific notes live under
  `docs/integrations/`, linked from here.
- **Don't** hardcode an exact version in tests (`assert __version__ == "X.Y.Z"`)
  — release-please bumps will break it. Use `>=` or read package metadata.
- **Don't** commit build artifacts to the repo root (`dist/`, `build/`,
  `coverage.json`); `dist/` is where packaging and `download-core-wheel` write.
- **Don't** add AI-attribution footers to PR bodies or commit messages.
