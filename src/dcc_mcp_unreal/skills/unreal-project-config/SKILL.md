---
name: unreal-project-config
description: >-
  Safely inspect, patch, and verify the active Unreal project's allowlisted
  renderer ConsoleVariables, including Lumen, Nanite, virtual shadows, and
  temporal upsampling. Use this before UI Project Settings edits.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read Write Edit
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: project
    search-hint: "unreal project config DefaultEngine.ini renderer settings Lumen Nanite virtual shadow atlas OCIO HDR PCG"
    tags: [unreal, project-config, renderer, lumen, nanite, pcg]
    tools: tools.yaml
---

# Unreal Project Config

Use typed, project-scoped configuration edits instead of clicking Project
Settings or writing arbitrary files. The skill only touches the active
project's `Config/DefaultEngine.ini`, backs up the file before a change, and
reports when an editor restart is required.

Workflow: inspect -> apply an allowlisted setting or preset -> save/restart the
editor when required -> verify disk and runtime values with this skill plus the
official Unreal MCP CVar/log tools.

The first version intentionally scopes writes to renderer ConsoleVariables used
by the Manhattan showcase. Unsupported keys return an actionable error.
