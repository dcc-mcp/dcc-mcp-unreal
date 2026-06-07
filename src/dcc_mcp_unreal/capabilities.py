"""Unreal Engine DCC capabilities declaration using dcc-mcp-core's DccCapabilities.

This module provides a single factory function :func:`unreal_capabilities` that
returns a ``DccCapabilities`` instance declaring what this Unreal Engine integration
supports.  The result exposes attribute access for all capability flags.

Supported capability flags:

- ``scene_manager``      — ``load_level``, ``save_level``, ``get_level_info``
- ``transform``          — actor location / rotation / scale via EditorLevelLibrary
- ``hierarchy``          — ``False`` — Unreal uses Outliner folders, not DAG hierarchy
- ``selection``          — ``EditorLevelLibrary.get_selected_level_actors`` / ``set_selected_level_actors``
- ``render_capture``     — ``AutomationLibrary.take_high_res_screenshot``
- ``snapshot``           — ``EditorLevelLibrary.take_high_res_screenshot`` viewport capture
- ``undo_redo``          — ``unreal.SystemLibrary`` undo / redo support
- ``file_operations``    — ``AssetTools`` FBX / glTF / OBJ import & export
- ``has_embedded_python``— Unreal ships its own CPython via the Python Editor Script Plugin
- ``progress_reporting`` — ``False`` — Unreal Python lacks a ``progressWindow`` equivalent
- ``scene_info``         — ``EditorLevelLibrary.get_all_level_actors`` world queries
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = ["unreal_capabilities", "UNREAL_CAPABILITIES_DICT"]


def unreal_capabilities():
    """Return a ``DccCapabilities`` instance for the Unreal Engine integration.

    All flags reflect capabilities available in Unreal Engine 5.0+ with the
    Python Editor Script Plugin enabled.  Renderer-specific flags
    (``render_capture``, ``snapshot``) require a running Unreal session; the
    flags are declared ``True`` because the code paths exist — callers may
    receive a skill_error at runtime if Unreal is running in headless mode.

    Returns:
        ``dcc_mcp_core.DccCapabilities`` instance.

    Example::

        caps = unreal_capabilities()
        print(caps.transform)     # True
        print(caps.hierarchy)     # False
        print(UNREAL_CAPABILITIES_DICT)  # {...}
    """
    from dcc_mcp_core import DccCapabilities  # noqa: PLC0415

    return DccCapabilities(
        scene_manager=True,
        transform=True,
        hierarchy=False,
        selection=True,
        render_capture=True,
        snapshot=True,
        undo_redo=True,
        file_operations=True,
        has_embedded_python=True,
        progress_reporting=False,
        scene_info=True,
    )


# Pre-computed plain dict — available without importing dcc_mcp_core at import
# time.  Useful for fast serialisation or when dcc_mcp_core is unavailable.
UNREAL_CAPABILITIES_DICT = {
    "scene_manager": True,
    "transform": True,
    "hierarchy": False,
    "selection": True,
    "render_capture": True,
    "snapshot": True,
    "undo_redo": True,
    "file_operations": True,
    "has_embedded_python": True,
    "progress_reporting": False,
    "scene_info": True,
}
