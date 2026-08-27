---
name: unreal-playtest-agent
description: >-
  Domain skill - run screenshot-light PIE playtest episodes with structured
  entity observations, bounded semantic actions, transition polling, and
  in-memory traces for QA and external policy or RL runners.
license: MIT
compatibility: Unreal Engine 5.0+, Python 3.9+
allowed-tools: Read Bash
metadata:
  dcc-mcp:
    dcc: unreal
    version: "0.1.0"
    layer: domain
    stage: validation
    search-hint: "unreal pie gameplay playtest episode exact session possession actor target identity observation semantic action causal movement centimeters displacement stalled trace qa rl"
    tags: [unreal, pie, playtest, qa, episode, observation, action, rl]
    tools: tools.yaml
    depends: ["unreal-pie"]
---

# Unreal Playtest Agent

Use this skill to drive gameplay QA from Unreal Engine state instead of treating screenshots as the primary observation channel.

## Contract

1. Start an episode with bounded entity selectors and scalar attribute names.
2. Observe the active GameMode, controller, redacted possessed-pawn identity, UMG widgets, and selected runtime entities from the active PIE world.
3. Execute one finite semantic action.
4. Poll the action until it completes, stalls, or times out.
5. Evaluate project-specific rewards and oracles in a project-local Skill.
6. Finish the episode and retain the returned transition trace.

## Transition truth

`runtime.possessed` is `null` unless the player controller directly reports a
possessed pawn. When present, it contains the pawn name, class, whether it is
the observation's player, an opaque hash of the object path, and a process-
stable `sha256:` identity tied to the exact live actor object. The raw path is
not exposed, missing paths never fall back to class and name, and a same-path
replacement receives a different identity.

Every episode binds one exact PIE world, session, player controller, and pawn.
The episode baseline, pre-input observation, native input delivery, and poll
readback must retain that binding. Replacement of any bound object or a
mismatched observation returns a stable non-success instead of using a delta
from another world. Entity navigation also retains the exact selected actor;
polling never re-adopts a same-name or same-path replacement target.

Terminal transitions retain the exact bounded `before` and `after`
observations and report both `player_location_delta` and scalar
`player_displacement`. All displacement fields and `min_displacement` use
Unreal centimeters; durations use seconds. `move_relative` expects movement
by default. Set
`expect_movement=false` only when legacy input-acceptance behavior is intended,
or set `expect_movement=true` with a bounded `min_displacement` for an explicit
effect postcondition. A zero or under-threshold result remains pending for the
bounded `stall_seconds` window, then returns `stalled` with
`reason="movement_below_threshold"`; input delivery alone never satisfies an
expected movement effect.

For `move_relative`, proof is additionally bounded to the exact requested
`direction` and `duration`. The terminal trace preserves both parameters and
reports `expected_direction`, projected `causal_displacement`,
`direction_alignment`, `max_causal_displacement`, and the bounded
`movement_proof_window`. Wrong-direction motion, a late unrelated delta, or a
teleport-like jump is `blocked`, never `completed`. The declared output schemas
machine-check these fields in the execute and poll MCP success envelopes.

PIE loss remains a retryable `pie_session_unavailable` result and does not
rewrite a pending action as completed. Finishing an episode records pending
actions as cancelled, with truthful observation availability.

## Combat Telemetry

Observations include bounded `telemetry` for the player and selected entities.
Built-in property aliases cover common health, maximum-health, magazine,
reserve-ammo, and cooldown names on actors or their components. Projects can
add canonical fields through `telemetry_aliases` without adding game-specific
code to the adapter. Canonical fields ending in `_cooldown_remaining` also
populate `action_availability`.

Completed actions report `telemetry_deltas`. Combat actions additionally
report `combat_feedback` and `damage_events` derived from observed health
changes. These are observation deltas, not engine damage-delegate events; a
target disappearing or taking shield-only damage remains inconclusive unless
the project exposes corresponding telemetry aliases.

## Project Mutation Postconditions

Project-local recovery and mutation tools must not treat successful event
dispatch as a successful gameplay effect. Capture the same bounded scalar
state before and after the operation and return
`dcc_mcp_unreal.verified_effect_result(...)` with explicit `required_fields`.
The helper returns success only when at least one named field changes. An
unchanged state returns `postcondition_not_met` and is not automatically
retryable; a missing observation returns `postcondition_unobservable`.

For asynchronous mutations, expose or use a named polling call and evaluate
the postcondition only after it reaches a terminal state. Never return success
while `verification_required` remains outstanding.

Screenshots and DCC-CUA recordings remain useful as checkpoint evidence and visual fallbacks. They are not required for each decision step.

## Boundaries

- Navigation uses Unreal's navigation system and never teleports the player.
- Actions are limited to restoring the configured playable pawn from an accidental PIE spectator start, navigation to a selected entity or explicit reachable waypoint, facing a selected entity or explicit world point, bounded camera-relative movement, conventional gameplay inputs, stopping movement, and waiting.
- Entity selection and attribute collection are bounded. Only JSON-safe scalar values are returned.
- Hidden actors are excluded by default, and class exclusions can remove debris or other non-actionable matches.
- Active UMG observation is read-only and capped at 32 `UserWidget` instances.
- The skill contains no game-specific class names, objectives, rewards, or private project knowledge.
- Reinforcement-learning trainers and policies stay outside the Unreal process and consume the episode contract.

## Typical loop

```text
playtest_episode_control(action="start", include_pawns=true, ...)
playtest_observe(episode_id=...)
playtest_execute_action(episode_id=..., action="navigate_to_entity", ...)
playtest_execute_action(episode_id=..., action="navigate_to_location", target_location={x, y, z})
playtest_execute_action(episode_id=..., action="move_relative", direction="forward", duration=0.25, expect_movement=true, min_displacement=5)  # seconds, Unreal centimeters
playtest_poll_action(episode_id=..., action_id=...)
playtest_episode_control(action="finish", episode_id=...)
```
