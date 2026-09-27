# AGENTS.md — dcc-mcp-unreal

> Navigation map, not a reference manual. Follow the links; don't read
> everything upfront.

dcc-mcp-unreal is the Unreal Engine adapter for the DCC Model Context
Protocol (MCP) ecosystem. It connects Unreal through an embedded Python
server or a native standalone sidecar, both built on `dcc-mcp-core`, and
exposes typed MCP tools over Streamable HTTP.

---

## Repository Contract

**This repository has a `justfile`; run everything through `vx just`.**

| Task | Command |
|------|---------|
| List all recipes | `vx just` (default) |
| Lint | `vx just lint` |
| Test | `vx just test` |
| Validate skill packages | `vx just validate-skills` |
| Lint + test + validate (before a PR) | `vx just check` |
| Environment self-check | `vx just doctor` |
| Package the UE plugin | `vx just package` |
| Install into an engine tree | `vx just install-engine` |
| Deploy into an engine tree | `vx just deploy-engine` |

**Repository layout**

| Path | Role |
|------|------|
| `src/dcc_mcp_unreal/` | Adapter package — server, dispatcher, skills |
| `unreal/` | Unreal Engine plugin payload (`.uplugin`, Content, Python) |
| `docs/` | Documentation site |
| `packaging/` | Distribution packaging (PyOxidizer, standalone sidecar) |
| `scripts/`, `tools/` | Build and dev helper scripts |
| `tests/` | pytest suite |
| `justfile` | Canonical task entrypoint |

**Release flow** — `release-please` on `main` drives `CHANGELOG.md` and the version in
`pyproject.toml` from Conventional Commit subjects. Tagging and
publishing run in CI. Never edit `CHANGELOG.md` or a version string by hand.

**Prohibitions**

- Do not bypass the justfile — no direct `uv run pytest` or `ruff` invocations.
- Do not edit `CHANGELOG.md` or version strings manually.
- Do not add a second agent contract file at the repository root; `AGENTS.md` is the single source.
- Do not commit generated plugin payload produced by `vx just package` / `uplugin` recipes.

---

## Agent Contract Files

`AGENTS.md` is the **only** agent contract file at the repository root. It is the
native instruction file for Codex, OpenCode, Cursor, GitHub Copilot, Windsurf,
Cline, Roo Code, Kiro, Trae, and Augment, and Claude Code falls back to it when
no `CLAUDE.md` exists — so do not add `CLAUDE.md`, `GEMINI.md`, `CURSOR.md`, or
any other vendor-specific variant.

**Gemini CLI exception:** Gemini CLI defaults its context file to `GEMINI.md`. To
make it read `AGENTS.md`, set `context.fileName` once in `~/.gemini/settings.json`:

```json
{
  "context": {
    "fileName": ["AGENTS.md", "GEMINI.md"]
  }
}
```
