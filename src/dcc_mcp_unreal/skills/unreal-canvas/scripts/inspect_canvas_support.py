"""Inspect the installed and project-enabled Unreal Canvas plugins."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

PLUGIN_ALIASES = {
    "unreal_canvas_bridge": ("unrealcanvasbridge",),
    "unreal_canvas_graph": ("unrealcanvasgraph",),
    "unreal_canvas_spatial_annotations": ("unrealcanvasspatialannotations",),
    "unreal_mcp": ("unrealmcp", "modelcontextprotocol"),
    "all_toolsets": ("alltoolsets",),
    "toolset_registry": ("toolsetregistry",),
    "python": ("pythonscriptplugin", "python"),
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _unreal_module() -> Any:
    try:
        from dcc_mcp_unreal.api import get_unreal

        return get_unreal()
    except Exception:
        return None


def _unreal_path(unreal: Any, method_name: str) -> Optional[Path]:
    paths = getattr(unreal, "Paths", None)
    method = getattr(paths, method_name, None)
    if not callable(method):
        return None
    try:
        value = str(method())
    except Exception:
        return None
    return Path(value) if value else None


def _project_path(unreal: Any) -> Optional[Path]:
    project_dir = _unreal_path(unreal, "project_dir") if unreal is not None else None
    if project_dir is not None:
        return project_dir
    configured = os.environ.get("UNREAL_PROJECT_DIR", "").strip()
    if configured:
        return Path(configured)
    return None


def _engine_path(unreal: Any) -> Optional[Path]:
    engine_dir = _unreal_path(unreal, "engine_dir") if unreal is not None else None
    if engine_dir is not None:
        return engine_dir
    configured = os.environ.get("UNREAL_ENGINE_DIR", os.environ.get("UE_ROOT_DIR", "")).strip()
    if configured:
        return Path(configured)
    return None


def _uproject_plugins(project_dir: Optional[Path]) -> Mapping[str, bool]:
    if project_dir is None:
        return {}
    candidates = list(project_dir.glob("*.uproject"))
    if not candidates:
        return {}
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    result = {}
    for item in data.get("Plugins", []):
        if isinstance(item, Mapping) and item.get("Name"):
            result[_normalize(str(item["Name"]))] = bool(item.get("Enabled", False))
    return result


def _runtime_plugins(unreal: Any) -> set[str]:
    library = getattr(unreal, "PluginBlueprintLibrary", None) if unreal is not None else None
    getter = getattr(library, "get_enabled_plugin_names", None)
    if not callable(getter):
        return set()
    try:
        return {_normalize(str(name)) for name in getter()}
    except Exception:
        return set()


def _descriptor_matches(descriptor: Path, aliases: Iterable[str]) -> bool:
    names = {_normalize(descriptor.stem), _normalize(descriptor.parent.name)}
    try:
        data = json.loads(descriptor.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if isinstance(data, Mapping):
        for key in ("Name", "FriendlyName", "DisplayName"):
            if data.get(key):
                names.add(_normalize(str(data[key])))
    return any(alias == name or alias in name for alias in aliases for name in names)


def _descriptor_names(descriptor: Path) -> set[str]:
    names = {_normalize(descriptor.stem), _normalize(descriptor.parent.name)}
    try:
        data = json.loads(descriptor.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if isinstance(data, Mapping):
        for key in ("Name", "FriendlyName", "DisplayName"):
            if data.get(key):
                names.add(_normalize(str(data[key])))
    return names


def _find_descriptors(roots: Iterable[Optional[Path]]) -> Dict[str, list[str]]:
    result = {key: [] for key in PLUGIN_ALIASES}
    seen = set()
    for root in roots:
        if root is None:
            continue
        plugin_root = root / "Plugins"
        if not plugin_root.is_dir():
            plugin_root = root / "Engine" / "Plugins"
        if not plugin_root.is_dir():
            continue
        try:
            descriptors = plugin_root.rglob("*.uplugin")
            for descriptor in descriptors:
                try:
                    resolved = str(descriptor.resolve())
                except OSError:
                    continue
                if resolved in seen:
                    continue
                seen.add(resolved)
                for key, aliases in PLUGIN_ALIASES.items():
                    if _descriptor_matches(descriptor, aliases):
                        result[key].append(resolved)
        except OSError:
            continue
    return result


def _engine_version(unreal: Any) -> str:
    system_library = getattr(unreal, "SystemLibrary", None) if unreal is not None else None
    get_version = getattr(system_library, "get_engine_version", None)
    if callable(get_version):
        try:
            return str(get_version())
        except Exception:
            pass
    return os.environ.get("UNREAL_ENGINE_VERSION", "unknown")


def _supports_native_canvas(engine_version: str) -> Optional[bool]:
    match = re.match(r"\s*(\d+)\.(\d+)", engine_version)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2))) >= (5, 9)


@skill_entry
def inspect_canvas_support(**kwargs) -> dict:
    try:
        unreal = _unreal_module()
        project_dir = _project_path(unreal)
        engine_dir = _engine_path(unreal)
        descriptors = _find_descriptors((project_dir, engine_dir))
        enabled_plugins = _uproject_plugins(project_dir)
        runtime_plugins = _runtime_plugins(unreal)
        plugins = {}
        for name, paths in descriptors.items():
            normalized_names = set().union(*(_descriptor_names(Path(path)) for path in paths)) if paths else set()
            enabled = None
            if normalized_names.intersection(runtime_plugins):
                enabled = True
            else:
                for plugin_name, enabled_value in enabled_plugins.items():
                    if any(plugin_name in candidate or candidate in plugin_name for candidate in normalized_names):
                        enabled = enabled_value
                        break
            plugins[name] = {
                "installed": bool(paths),
                "enabled": enabled,
                "paths": paths,
            }
        engine_version = _engine_version(unreal)
        version_supported = _supports_native_canvas(engine_version)
        bridge_ready = plugins["unreal_canvas_bridge"]["installed"] and plugins["unreal_canvas_bridge"]["enabled"] is not False
        graph_ready = plugins["unreal_canvas_graph"]["installed"] and plugins["unreal_canvas_graph"]["enabled"] is not False
        mcp_ready = plugins["unreal_mcp"]["installed"] and plugins["unreal_mcp"]["enabled"] is not False
        spatial_ready = (
            plugins["unreal_canvas_spatial_annotations"]["installed"]
            and plugins["unreal_canvas_spatial_annotations"]["enabled"] is not False
        )
        native_canvas_available = bool(bridge_ready and graph_ready and mcp_ready and version_supported is not False)
        return skill_success(
            "Unreal Canvas support inspected.",
            engine_version=engine_version,
            unreal_canvas_engine_supported=version_supported,
            project_path=str(project_dir) if project_dir else None,
            engine_path=str(engine_dir) if engine_dir else None,
            python_runtime_available=unreal is not None,
            native_canvas_available=native_canvas_available,
            canvas_bridge_ready=bool(bridge_ready),
            canvas_graph_ready=bool(graph_ready),
            spatial_annotations_ready=bool(spatial_ready),
            official_mcp_available=bool(mcp_ready),
            all_toolsets_available=bool(
                plugins["all_toolsets"]["installed"] and plugins["all_toolsets"]["enabled"] is not False
            ),
            toolset_registry_available=bool(
                plugins["toolset_registry"]["installed"] and plugins["toolset_registry"]["enabled"] is not False
            ),
            plugins=plugins,
            native_capabilities=[
                "viewport_render",
                "viewport_snapshot",
                "sequence_render",
                "spatial_annotations",
                "typed_action_card_graphs",
                "mesh_import",
                "cutout_actor_placement",
            ],
            mcp_canvas_workflow_available=True,
            recommended_action=(
                "Use the native Canvas Bridge after confirming the server, provider, local-model, and agent setup."
                if native_canvas_available
                else "Use the MCP/Action-card workflow, or enable the UE 5.9 Canvas Bridge and its dependencies before using the native surface."
            ),
        )
    except Exception as exc:
        return skill_error("Failed to inspect Unreal Canvas support", type(exc).__name__)
