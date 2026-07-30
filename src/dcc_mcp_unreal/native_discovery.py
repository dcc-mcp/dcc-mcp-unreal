"""Discovery metadata for the native Unreal bridge.

The UE4 native bridge executes tools in C++.  This module exposes only that
implemented subset to the shared gateway so agents can discover schemas before
the Rust sidecar dispatches calls back to the editor.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from typing import Any, Dict, Iterator, Tuple

from .__version__ import __version__

_EMPTY_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
_ACTOR_NAME_SCHEMA = {
    "type": "object",
    "required": ["actor_name"],
    "properties": {"actor_name": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}
_BLUEPRINT_NAME_SCHEMA = {
    "type": "object",
    "required": ["blueprint_name"],
    "properties": {"blueprint_name": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}

NATIVE_TOOL_SPECS: Tuple[Dict[str, Any], ...] = (
    {
        "name": "unreal_actors__list_actors",
        "description": "List actors in the current editor level, optionally filtered by class name.",
        "schema": {
            "type": "object",
            "properties": {"actor_class_filter": {"type": "string", "default": ""}},
            "additionalProperties": False,
        },
        "read_only": True,
        "destructive": False,
    },
    {
        "name": "unreal_actors__spawn_actor",
        "description": "Spawn an actor from a class path at a world-space location.",
        "schema": {
            "type": "object",
            "properties": {
                "actor_class": {"type": "string", "default": "/Script/Engine.StaticMeshActor"},
                "location_x": {"type": "number", "default": 0.0},
                "location_y": {"type": "number", "default": 0.0},
                "location_z": {"type": "number", "default": 0.0},
                "label": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "read_only": False,
        "destructive": False,
    },
    {
        "name": "unreal_actors__delete_actor",
        "description": "Delete an actor by its exact object name.",
        "schema": _ACTOR_NAME_SCHEMA,
        "read_only": False,
        "destructive": True,
    },
    {
        "name": "unreal_actors__get_actor_transform",
        "description": "Read the world transform of an actor by exact object name.",
        "schema": _ACTOR_NAME_SCHEMA,
        "read_only": True,
        "destructive": False,
    },
    {
        "name": "unreal_actors__set_actor_transform",
        "description": "Update selected world-transform components for an actor.",
        "schema": {
            "type": "object",
            "required": ["actor_name"],
            "properties": {
                "actor_name": {"type": "string", "minLength": 1},
                "location_x": {"type": "number"},
                "location_y": {"type": "number"},
                "location_z": {"type": "number"},
                "rotation_pitch": {"type": "number"},
                "rotation_yaw": {"type": "number"},
                "rotation_roll": {"type": "number"},
                "scale_x": {"type": "number"},
                "scale_y": {"type": "number"},
                "scale_z": {"type": "number"},
            },
            "additionalProperties": False,
        },
        "read_only": False,
        "destructive": False,
    },
    {
        "name": "unreal_level__get_level_info",
        "description": "Read the active level name and Unreal Engine version.",
        "schema": _EMPTY_SCHEMA,
        "read_only": True,
        "destructive": False,
    },
    {
        "name": "unreal_level__save_level",
        "description": "Save the current level or all dirty content packages.",
        "schema": {
            "type": "object",
            "properties": {"save_all_dirty": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
        "read_only": False,
        "destructive": False,
    },
    {
        "name": "unreal_assets__list_assets",
        "description": "List Content Browser assets below a package directory.",
        "schema": {
            "type": "object",
            "properties": {
                "directory_path": {"type": "string", "default": "/Game"},
                "recursive": {"type": "boolean", "default": True},
                "asset_class_filter": {"type": "string", "default": ""},
            },
            "additionalProperties": False,
        },
        "read_only": True,
        "destructive": False,
    },
    {
        "name": "unreal_assets__create_blueprint",
        "description": "Create and compile a Blueprint asset from a parent class.",
        "schema": {
            "type": "object",
            "required": ["blueprint_name"],
            "properties": {
                "blueprint_name": {"type": "string", "minLength": 1},
                "destination_path": {"type": "string", "default": "/Game/Blueprints"},
                "parent_class_path": {"type": "string", "default": "Actor"},
            },
            "additionalProperties": False,
        },
        "read_only": False,
        "destructive": False,
    },
    {
        "name": "unreal_blueprints__create_blueprint_class",
        "description": "Create and compile a Blueprint class from a parent class.",
        "schema": {
            "type": "object",
            "required": ["blueprint_name"],
            "properties": {
                "blueprint_name": {"type": "string", "minLength": 1},
                "package_path": {"type": "string", "default": "/Game/Blueprints"},
                "parent_class": {"type": "string", "default": "Actor"},
            },
            "additionalProperties": False,
        },
        "read_only": False,
        "destructive": False,
    },
    {
        "name": "unreal_blueprints__add_component_to_blueprint",
        "description": "Add a component node to an existing Blueprint class and compile it.",
        "schema": {
            "type": "object",
            "required": ["blueprint_name", "component_type", "component_name"],
            "properties": {
                "blueprint_name": {"type": "string", "minLength": 1},
                "component_type": {"type": "string", "minLength": 1},
                "component_name": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        },
        "read_only": False,
        "destructive": False,
    },
    {
        "name": "unreal_blueprints__compile_blueprint",
        "description": "Compile and save an existing Blueprint class.",
        "schema": _BLUEPRINT_NAME_SCHEMA,
        "read_only": False,
        "destructive": False,
    },
)


@contextmanager
def native_discovery_server() -> Iterator[str]:
    """Run an isolated MCP endpoint that advertises native bridge schemas."""
    from .server import UnrealMcpServer  # noqa: PLC0415

    with TemporaryDirectory(prefix="dcc-mcp-unreal-native-") as registry_dir:
        server = UnrealMcpServer(
            port=None,
            server_name="unreal-native-discovery",
            server_version=__version__,
            gateway_port=0,
            registry_dir=registry_dir,
            enable_file_logging=False,
            enable_job_persistence=False,
            enable_telemetry=False,
        )
        for spec in NATIVE_TOOL_SPECS:
            tags = ["native", "read-only" if spec["read_only"] else "write"]
            if spec["destructive"]:
                tags.append("destructive")
            server.registry.register(
                name=spec["name"],
                description=spec["description"],
                category="native",
                tags=tags,
                dcc="unreal",
                version=__version__,
                input_schema=json.dumps(spec["schema"]),
                source_file="",
                execution="sync",
                timeout_hint_secs=120,
                thread_affinity="main",
                enforce_thread_affinity=True,
            )

        handle = server.start()
        try:
            yield handle.mcp_url()
        finally:
            server.stop()
