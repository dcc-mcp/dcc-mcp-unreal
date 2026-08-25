---
name: unreal-pie
description: >-
  Domain skill - Unreal Engine Play-In-Editor (PIE) closed-loop verification.
  Provides PIE lifecycle control (enter/pause/resume/exit), controlled input
  injection (no OS dependency), viewport screenshot capture, output log
  snapshot, performance sampling, and Automation Test execution with async
  job polling. Use for reproducible, agent-driven playtest workflows.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Bash Read
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: validation
    search-hint: "unreal pie play-in-editor verification input screenshot log perf automation test polling job"
    tags: "unreal, pie, playtest, input, screenshot, log, perf, automation, test"
    tools: tools.yaml
---

# Unreal PIE — Play-In-Editor Closed-Loop Verification

Agent-driven PIE session control with controlled input, screenshot capture,
log sampling, performance monitoring, and async Automation Test job execution.

## Design Principles

- **No broad OS input** — all input injection uses Unreal Engine's internal
  systems, never `pyautogui`, `SendInput`, or similar OS-level APIs.
- **Persistent jobs** — Automation Test runs return a `job_id` that can be
  polled for status and cancelled.
- **Reproducible evidence** — screenshots, log snapshots, and performance
  samples are timestamped and self-contained.

## Scripts

- `pie_control` — Enter, pause, resume, or exit PIE.
- `pie_inject_input` — Inject keyboard, pointer, scroll, or deterministic
  possessed-controller look input into PIE.
- `pie_capture_screenshot` — Capture the active viewport to a file.
- `pie_snapshot_log` — Snapshot the Output Log buffer.
- `pie_get_status` — Query PIE state and performance counters.
- `pie_run_test` — Queue an Automation Test run; returns a `job_id`.
- `pie_poll_test` — Poll a previously queued Automation Test job for results.
- `pie_cancel_job` — Cancel a running or queued job.

## Usage Examples

### Full PIE playtest loop

```python
# 1. Enter PIE
# MCP tool call: unreal_pie__control
# params: {"action": "enter"}

# 2. Inject a few controlled inputs
# MCP tool call: unreal_pie__inject_input
# params: {"input_type": "key_press", "key": "W"}

# 3. Capture screenshot
# MCP tool call: unreal_pie__capture_screenshot
# params: {"filepath": "C:/playtest/frame_001.png"}

# 4. Check status + perf
# MCP tool call: unreal_pie__get_status
# params: {}

# 5. Snapshot logs
# MCP tool call: unreal_pie__snapshot_log
# params: {"max_lines": 200}

# 6. Exit PIE
# MCP tool call: unreal_pie__control
# params: {"action": "exit"}
```

### Async Automation Test workflow

```python
# 1. Queue a test
# MCP tool call: unreal_pie__run_test
# params: {"filter": "DccMcp.Smoke"}
# Returns: {"job_id": "pie_test_20260725_120000_abc123"}

# 2. Poll until complete
# MCP tool call: unreal_pie__poll_test
# params: {"job_id": "pie_test_20260725_120000_abc123"}
# Returns status: "running" | "completed" | "failed" | "cancelled"

# 3. Cancel if needed
# MCP tool call: unreal_pie__cancel_job
# params: {"job_id": "pie_test_20260725_120000_abc123"}
```
