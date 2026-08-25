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
    search-hint: "unreal pie gameplay playtest episode observation semantic action transition trace qa rl"
    tags: [unreal, pie, playtest, qa, episode, observation, action, rl]
    tools: tools.yaml
    depends: ["unreal-pie"]
---

# Unreal Playtest Agent

Use this skill to drive gameplay QA from Unreal Engine state instead of treating screenshots as the primary observation channel.

## Contract

1. Start an episode with bounded entity selectors and scalar attribute names.
2. Observe the active GameMode, controller, possessed pawn, UMG widgets, and selected runtime entities from the active PIE world.
3. Execute one finite semantic action.
4. Poll the action until it completes, stalls, or times out.
5. Evaluate project-specific rewards and oracles in a project-local Skill.
6. Finish the episode and retain the returned transition trace.

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
playtest_poll_action(episode_id=..., action_id=...)
playtest_episode_control(action="finish", episode_id=...)
```
