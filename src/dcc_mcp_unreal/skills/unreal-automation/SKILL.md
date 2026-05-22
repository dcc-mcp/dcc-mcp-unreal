---
name: unreal-automation
description: >-
  Domain skill - Unreal Engine native Automation Test and MCP health validation.
  Use to list UE Automation tests, queue native test runs, and run a safe
  self-check against the active MCP server.
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

## Scripts

- `mcp_self_check`
- `list_automation_tests`
- `queue_automation_tests`
