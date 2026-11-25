"""Build the typed Graph contract used by the Hyper3D Canvas workflow."""

from __future__ import annotations

from pathlib import Path

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _node(node_id, tool, inputs, outputs):
    return {
        "id": node_id,
        "kind": "mcp_skill_node",
        "tool": tool,
        "inputs": inputs,
        "outputs": outputs,
    }


@skill_entry
def prepare_hyper3d_canvas_workflow(
    asset_destination_path: str = "/Game/Merlin/Generated",
    include_import_node: bool = True,
    dcc_mcp_skill: str = "unreal-cinematics",
    dcc_mcp_tool: str = "queue_sequence_render",
    include_dcc_mcp_node: bool = True,
    include_render_node: bool = True,
    download_result_path: str = "",
    **kwargs,
) -> dict:
    if not asset_destination_path.startswith("/Game/") or asset_destination_path.endswith("/"):
        return skill_error(
            "Invalid Unreal asset destination",
            "asset_destination_path must start with /Game/ and not end with /",
        )
    if download_result_path and not Path(download_result_path).expanduser().is_absolute():
        return skill_error(
            "Invalid Hyper3D download destination",
            "download_result_path must be an absolute path",
        )

    nodes = [
        _node(
            "image_input",
            "canvas.input.image",
            [],
            [{"name": "images", "type": "image[]", "required": False}],
        ),
        _node(
            "text_input",
            "canvas.input.text",
            [],
            [{"name": "prompt", "type": "text", "required": False}],
        ),
        _node(
            "submit_hyper3d",
            "unreal_canvas__submit_hyper3d_generation",
            [
                {"name": "image_paths", "type": "image[]", "required": False},
                {"name": "prompt", "type": "text", "required": False},
                {"name": "tier", "type": "text", "default": "Gen-2.5-Medium"},
                {"name": "mesh_mode", "type": "text", "default": "Raw"},
                {"name": "quality", "type": "text", "default": "medium"},
                {"name": "geometry_file_format", "type": "text", "default": "glb"},
            ],
            [
                {"name": "task_uuid", "type": "text"},
                {"name": "subscription_key", "type": "text"},
            ],
        ),
        _node(
            "status_hyper3d",
            "unreal_canvas__get_hyper3d_generation_status",
            [{"name": "subscription_key", "type": "text", "required": True}],
            [
                {"name": "states", "type": "text[]"},
                {"name": "all_done", "type": "boolean"},
                {"name": "failed", "type": "boolean"},
            ],
        ),
    ]
    connections = [
        {
            "from": {"node": "image_input", "pin": "images"},
            "to": {"node": "submit_hyper3d", "pin": "image_paths"},
        },
        {"from": {"node": "text_input", "pin": "prompt"}, "to": {"node": "submit_hyper3d", "pin": "prompt"}},
        {
            "from": {"node": "submit_hyper3d", "pin": "subscription_key"},
            "to": {"node": "status_hyper3d", "pin": "subscription_key"},
        },
    ]
    if include_import_node:
        nodes.extend(
            [
                _node(
                    "download_hyper3d",
                    "unreal_canvas__download_hyper3d_result",
                    [
                        {"name": "task_uuid", "type": "text", "required": True},
                        {
                            "name": "result_path",
                            "type": "path",
                            "required": True,
                            "source": "setting",
                            "default": download_result_path,
                            "description": "Absolute local path for the downloaded Hyper3D result.",
                        },
                        {"name": "file_name", "type": "text", "required": False},
                    ],
                    [{"name": "result_path", "type": "path"}],
                ),
                _node(
                    "import_hyper3d",
                    "unreal_canvas__import_hyper3d_asset",
                    [
                        {"name": "source_path", "type": "path", "required": True},
                        {"name": "destination_path", "type": "unreal.asset_folder", "default": asset_destination_path},
                    ],
                    [{"name": "imported_object_paths", "type": "unreal.asset[]"}],
                ),
            ]
        )
        connections.extend(
            [
                {
                    "from": {"node": "submit_hyper3d", "pin": "task_uuid"},
                    "to": {"node": "download_hyper3d", "pin": "task_uuid"},
                },
                {
                    "from": {"node": "download_hyper3d", "pin": "result_path"},
                    "to": {"node": "import_hyper3d", "pin": "source_path"},
                },
            ]
        )
    if include_dcc_mcp_node:
        nodes.append(
            _node(
                "dcc_mcp_action",
                "canvas.dcc_mcp.call",
                [
                    {
                        "name": "endpoint",
                        "type": "dcc_mcp.endpoint",
                        "default": "local",
                        "source": "setting",
                        "description": "Local profile or approved DCC-MCP gateway endpoint.",
                    },
                    {
                        "name": "skill_name",
                        "type": "text",
                        "default": dcc_mcp_skill,
                        "source": "setting",
                        "description": "Marketplace or local DCC-MCP skill slug.",
                    },
                    {
                        "name": "tool_name",
                        "type": "text",
                        "default": dcc_mcp_tool,
                        "source": "setting",
                        "description": "Tool exposed by the selected skill.",
                    },
                    {
                        "name": "arguments",
                        "type": "json",
                        "default": {},
                        "source": "setting",
                        "description": "JSON arguments entered for the selected DCC-MCP tool.",
                    },
                    {"name": "asset_paths", "type": "unreal.asset[]", "required": False},
                ],
                [
                    {"name": "result", "type": "json"},
                    {"name": "sequence_path", "type": "unreal.asset_path", "required": False},
                ],
            )
        )
        if include_import_node:
            connections.append(
                {
                    "from": {"node": "import_hyper3d", "pin": "imported_object_paths"},
                    "to": {"node": "dcc_mcp_action", "pin": "asset_paths"},
                }
            )
    if include_render_node:
        nodes.append(
            _node(
                "render_showcase",
                "unreal_cinematics__queue_sequence_render",
                [
                    {
                        "name": "sequence_path",
                        "type": "unreal.asset_path",
                        "required": True,
                        "source": "setting",
                        "description": "Level Sequence package path for the Showcase render.",
                    },
                    {
                        "name": "output_path",
                        "type": "path",
                        "required": True,
                        "source": "setting",
                        "description": "Absolute output directory for Movie Render Queue frames.",
                    },
                    {"name": "resolution_x", "type": "integer", "default": 1920, "source": "setting"},
                    {"name": "resolution_y", "type": "integer", "default": 1080, "source": "setting"},
                    {"name": "output_format", "type": "text", "default": "png", "source": "setting"},
                    {"name": "temporal_samples", "type": "integer", "default": 8, "source": "setting"},
                ],
                [{"name": "render_job", "type": "unreal.render_job"}],
            )
        )
        if include_dcc_mcp_node:
            connections.append(
                {
                    "from": {"node": "dcc_mcp_action", "pin": "sequence_path"},
                    "to": {"node": "render_showcase", "pin": "sequence_path"},
                }
            )
    if include_dcc_mcp_node or include_render_node:
        output_inputs = []
        if include_import_node:
            output_inputs.append({"name": "imported_object_paths", "type": "unreal.asset[]", "required": False})
        if include_dcc_mcp_node:
            output_inputs.append({"name": "dcc_mcp_result", "type": "json", "required": False})
        if include_render_node:
            output_inputs.append({"name": "render_job", "type": "unreal.render_job", "required": False})
        nodes.append(
            _node(
                "canvas_output",
                "canvas.output.showcase",
                output_inputs,
                [{"name": "showcase_result", "type": "json"}],
            )
        )
        if include_import_node:
            connections.append(
                {
                    "from": {"node": "import_hyper3d", "pin": "imported_object_paths"},
                    "to": {"node": "canvas_output", "pin": "imported_object_paths"},
                }
            )
        if include_dcc_mcp_node:
            connections.append(
                {
                    "from": {"node": "dcc_mcp_action", "pin": "result"},
                    "to": {"node": "canvas_output", "pin": "dcc_mcp_result"},
                }
            )
        if include_render_node:
            connections.append(
                {
                    "from": {"node": "render_showcase", "pin": "render_job"},
                    "to": {"node": "canvas_output", "pin": "render_job"},
                }
            )
    graph = {
        "graph_id": "hyper3d_to_unreal_asset",
        "card_type": "Action",
        "scope": "inside_action_card_graph",
        "provider": "Hyper3D Rodin",
        "node_provider": "dcc-mcp",
        "native_canvas_node_registration": "requires_unreal_canvas_extension_runtime",
        "input_contract": {
            "one_of": ["image[]", "text"],
            "description": "Connect image references or a text description to the submit node.",
        },
        "manual_settings": {
            "dcc_mcp": ["endpoint", "skill_name", "tool_name", "arguments"],
            "download": ["result_path"],
            "render": ["sequence_path", "output_path", "resolution_x", "resolution_y", "output_format", "temporal_samples"],
            "description": "Canvas Subscript settings can be filled manually before running the graph.",
        },
        "nodes": nodes,
        "connections": connections,
        "outer_canvas_connections": [],
        "execution": {
            "poll_until": "all_done == true",
            "stop_when": "failed == true",
            "import_destination": asset_destination_path,
        },
    }
    return skill_success(
        "Prepared a typed Unreal Canvas Action-card Graph contract for Hyper3D.",
        prompt="Place this pipeline inside an Action-card Graph, then connect a Canvas image or text input.",
        graph=graph,
    )
