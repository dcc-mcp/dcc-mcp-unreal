---
name: unreal-automation
description: >-
  Domain skill - Unreal Engine native Automation Test and MCP health validation.
  Use to inspect typed plugin readiness, list UE Automation tests, queue native
  test runs, and run a safe self-check against the active MCP server.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read Write
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: validation
    search-hint: "unreal automation tests native test framework mcp smoke ci validation"
    tags: "unreal, automation, tests, smoke, ci, validation"
    tools: tools.yaml
---

# Unreal Automation

Tools for validating the active MCP server and driving Unreal Engine's native
Automation Test framework from an MCP client.

## Plugin capability preflight

Call `preflight_plugins` before workflows that depend on optional engine
plugins. The tool accepts only `static_groom_import`, `usd_import`, or
`movie_render_queue` and returns `required_plugins`, the enabled required
subset, exact `missing_plugins`, `ready`, and one structured `next_action`.
It is read-only: it never edits the project descriptor or enables plugins.

## Scripts

- `preflight_plugins`
- `mcp_self_check`
- `list_automation_tests`
- `queue_automation_tests`
