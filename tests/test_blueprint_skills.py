"""Tests for unreal-blueprints skill scripts.

These tests verify the skill scripts can be loaded and executed correctly.
They mock the unreal module since we're not inside Unreal Engine.
"""

from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _load_module(name: str, path: str):
    """Load a skill script module for testing."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    return module, spec


def test_blueprint_layout_orders_connected_nodes_and_avoids_overlap():
    class Node:
        def __init__(self, guid):
            self.guid = guid
            self.position = {"node_pos_x": 0, "node_pos_y": 0}
            self.outputs = []

        def get_node_guid(self):
            return self.guid

        def get_editor_property(self, name):
            return self.position[name]

        def set_editor_property(self, name, value):
            self.position[name] = value

    class Pin:
        def __init__(self, owner):
            self.owner = owner
            self.links = []

    first, second, loose = Node("first"), Node("second"), Node("loose")
    output_pin, input_pin = Pin(first), Pin(second)
    output_pin.links.append(input_pin)
    first.outputs.append(output_pin)
    graph = SimpleNamespace(get_all_nodes=lambda: [first, second, loose])
    unreal = SimpleNamespace(
        IntPoint=lambda x, y: SimpleNamespace(x=x, y=y),
        BlueprintEditorLibrary=SimpleNamespace(
            list_output_pins=lambda node: node.outputs,
            set_node_pos=lambda node, pos: node.position.update(node_pos_x=pos.x, node_pos_y=pos.y),
        ),
        BlueprintGraphPinLibrary=SimpleNamespace(
            list_connected_pins=lambda pin: pin.links,
            get_owning_node=lambda pin: pin.owner,
        ),
    )

    with patch.dict(sys.modules, {"unreal": unreal}):
        module, spec = _load_module(
            "_blueprint_graph_api",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/_blueprint_graph_api.py",
        )
        spec.loader.exec_module(module)
        result = module.layout_graph(graph)

    positions = {(node.position["node_pos_x"], node.position["node_pos_y"]) for node in (first, second, loose)}
    assert result == {"node_count": 3, "column_count": 2}
    assert second.position["node_pos_x"] > first.position["node_pos_x"]
    assert len(positions) == 3


def test_blueprint_graph_lookup_uses_unreal_58_list_graphs():
    event_graph = SimpleNamespace(get_name=lambda: "EventGraph")
    unreal = SimpleNamespace(BlueprintEditorLibrary=SimpleNamespace(list_graphs=lambda _blueprint: [event_graph]))

    with patch.dict(sys.modules, {"unreal": unreal}):
        module, spec = _load_module(
            "_blueprint_graph_api",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/_blueprint_graph_api.py",
        )
        spec.loader.exec_module(module)
        assert module.get_graph(object()) is event_graph


class TestCreateBlueprintClass:
    """Tests for create_blueprint_class.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_loads_module(self):
        """Verify the script can be imported."""
        module, _ = _load_module(
            "create_blueprint_class",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/create_blueprint_class.py",
        )
        assert module is not None

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_parent_class_not_found(self):
        """Test error when parent class is not found."""
        import unreal

        unreal.load_class.return_value = None

        module, spec = _load_module(
            "create_blueprint_class",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/create_blueprint_class.py",
        )
        spec.loader.exec_module(module)

        result = module.create_blueprint_class(
            blueprint_name="BP_Test",
            parent_class="NonExistent",
        )

        assert result["success"] is False
        assert "Parent class not found" in result["message"]


class TestAddEventNode:
    """Tests for add_event_node.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_blueprint_not_found(self):
        """Test error when Blueprint is not found."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_module(
            "add_event_node",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/add_event_node.py",
        )
        spec.loader.exec_module(module)

        result = module.add_event_node(
            blueprint_name="BP_NotFound",
            event_name="ReceiveBeginPlay",
        )

        assert result["success"] is False
        assert "Blueprint not found" in result["message"]


class TestConnectNodes:
    """Tests for connect_nodes.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_blueprint_not_found(self):
        """Test error when Blueprint is not found."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_module(
            "connect_nodes",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/connect_nodes.py",
        )
        spec.loader.exec_module(module)

        result = module.connect_nodes(
            blueprint_name="BP_NotFound",
            source_node_id="node1",
            source_pin="then",
            target_node_id="node2",
            target_pin="execute",
        )

        assert result["success"] is False
        assert "Blueprint not found" in result["message"]


class TestAddVariable:
    """Tests for add_variable.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_blueprint_not_found(self):
        """Test error when Blueprint is not found."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_module(
            "add_variable",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/add_variable.py",
        )
        spec.loader.exec_module(module)

        result = module.add_variable(
            blueprint_name="BP_NotFound",
            variable_name="MyVar",
            variable_type="Float",
        )

        assert result["success"] is False
        assert "Blueprint not found" in result["message"]


class TestCompileBlueprint:
    """Tests for compile_blueprint.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_blueprint_not_found(self):
        """Test error when Blueprint is not found."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_module(
            "compile_blueprint",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/compile_blueprint.py",
        )
        spec.loader.exec_module(module)

        result = module.compile_blueprint(blueprint_name="BP_NotFound")

        assert result["success"] is False
        assert "Blueprint not found" in result["message"]

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_uses_blueprint_editor_library(self):
        import unreal

        blueprint = object()
        unreal.EditorAssetLibrary.load_asset.return_value = blueprint
        unreal.BlueprintEditorLibrary.compile_blueprint.return_value = True
        module, spec = _load_module(
            "compile_blueprint_success",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/compile_blueprint.py",
        )
        spec.loader.exec_module(module)

        result = module.compile_blueprint(blueprint_name="BP_Test")

        assert result["success"] is True
        unreal.BlueprintEditorLibrary.compile_blueprint.assert_called_once_with(blueprint)


class TestFindNodes:
    """Tests for find_nodes.py."""

    @patch.dict(sys.modules, {"unreal": MagicMock()})
    def test_blueprint_not_found(self):
        """Test error when Blueprint is not found."""
        import unreal

        unreal.EditorAssetLibrary.load_asset.return_value = None

        module, spec = _load_module(
            "find_nodes",
            "src/dcc_mcp_unreal/skills/unreal-blueprints/scripts/find_nodes.py",
        )
        spec.loader.exec_module(module)

        result = module.find_nodes(blueprint_name="BP_NotFound")

        assert result["success"] is False
        assert "Blueprint not found" in result["message"]
