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
def edit_pcg_graph(
    operation: str,
    asset_path: str,
    node_id: str = "",
    settings_class: str = "",
    position: list | None = None,
    settings: dict | None = None,
    edge: dict | None = None,
    settings_names: list | None = None,
    **kwargs,
) -> dict:
    """Perform one explicit graph edit or save; generation is not requested."""
    return _run(
        operation,
        asset_path,
        node_id=node_id,
        settings_class=settings_class,
        position=position,
        settings=settings,
        edge=edge,
        settings_names=settings_names,
    )
