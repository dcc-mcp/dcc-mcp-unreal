"""Author one typed key on an AI Blackboard asset (minimal, undoable action)."""

from __future__ import annotations

from _ai_blackboard import AiBlackboardError, author_blackboard_key
from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


@skill_entry
def author_ai_blackboard_key(
    asset_path: str = "",
    key_name: str = "",
    key_type: str = "float",
    create_if_missing: bool = True,
    **_kwargs,
) -> dict:
    """Add a single typed key with readback, scoped transaction and rollback."""
    try:
        import unreal  # noqa: PLC0415

        result = author_blackboard_key(
            unreal,
            asset_path,
            key_name,
            key_type=key_type,
            create_if_missing=create_if_missing,
        )
    except AiBlackboardError as exc:
        return skill_error("AI Blackboard authoring rejected", str(exc), **exc.context)
    except ImportError:
        return skill_error("Unreal Engine not available", "ImportError: unreal module not found")
    except Exception as exc:  # noqa: BLE001
        return skill_error(
            "AI Blackboard authoring failed",
            "{}: {}".format(type(exc).__name__, exc)[:1000],
            mutation_state="not_established",
            readback_verified=False,
        )
    return skill_success(
        "Authored key '{}' ({}) on '{}'".format(result["key_name"], result["key_type"], result["asset_path"]),
        prompt="Re-run inspect_ai_blackboard to confirm the key; saving is current-session only, not disk-reopen proof.",
        **result,
    )
