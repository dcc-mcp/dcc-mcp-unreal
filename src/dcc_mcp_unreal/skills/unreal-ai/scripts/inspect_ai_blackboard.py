"""Read-only bounded readback of an AI Blackboard asset."""

from __future__ import annotations

from _ai_blackboard import AiBlackboardError, inspect_blackboard
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def inspect_ai_blackboard(asset_path: str = "", **_kwargs) -> dict:
    """Read a Blackboard asset's typed keys through a reflected, bounded readback."""
    try:
        import unreal  # noqa: PLC0415

        result = inspect_blackboard(unreal, asset_path)
    except AiBlackboardError as exc:
        return skill_error("AI Blackboard inspection rejected", str(exc), **exc.context)
    except ImportError:
        return skill_error("Unreal Engine not available", "ImportError: unreal module not found")
    except Exception as exc:  # noqa: BLE001
        return skill_error(
            "AI Blackboard inspection failed",
            "{}: {}".format(type(exc).__name__, exc)[:1000],
        )
    message = (
        "Blackboard asset has {} key(s)".format(result["key_count"])
        if result["exists"]
        else "Blackboard asset does not exist"
    )
    return skill_success(
        message,
        prompt="Use author_ai_blackboard_key to add one typed key, then re-run this inspection to verify.",
        **result,
    )
