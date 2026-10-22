"""Typed entry points for bounded PCG graph inspection and explicit edits."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.pcg_graph import PcgGraphError, graph_operation


def _run(operation: str, asset_path: str, **arguments) -> dict:
    try:
        import unreal  # noqa: PLC0415

        result = graph_operation(unreal, operation, asset_path, **arguments)
    except PcgGraphError as exc:
        return skill_error("PCG graph operation rejected or failed", str(exc), **exc.context)
    except Exception as exc:
        return skill_error(
            "PCG graph operation failed",
            f"{type(exc).__name__}: {exc}"[:1000],
            mutation_state="not_established",
            generation_verified=False,
        )
    return skill_success("PCG graph structural operation completed", **result)


@skill_entry
def inspect_pcg_graph(asset_path: str, settings_names: list | None = None, **kwargs) -> dict:
    """Read complete bounded topology and selected scalar settings; never save."""
    return _run("inspect", asset_path, settings_names=settings_names)
