"""Read-only AI capability preflight (version + plugin + API gating)."""

from __future__ import annotations

from _ai_blackboard import AiBlackboardError, preflight
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def ai_capability_preflight(capability: str = "ai_blackboard", **_kwargs) -> dict:
    """Report typed readiness and one deterministic next action, without mutating."""
    try:
        import unreal  # noqa: PLC0415

        result = preflight(unreal, capability)
    except AiBlackboardError as exc:
        return skill_error("AI capability preflight rejected", str(exc), **exc.context)
    except ImportError:
        return skill_error("Unreal Engine not available", "ImportError: unreal module not found")
    except Exception as exc:  # noqa: BLE001
        return skill_error(
            "AI capability preflight failed",
            "{}: {}".format(type(exc).__name__, exc)[:1000],
            ready=False,
        )
    message = "AI capability is ready on this host" if result["ready"] else "AI capability is not ready on this host"
    return skill_success(
        message,
        prompt="Proceed to author_ai_blackboard_key only when ready is true, else follow next_action.",
        **result,
    )
