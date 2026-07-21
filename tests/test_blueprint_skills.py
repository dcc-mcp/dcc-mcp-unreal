"""Tests for unreal-blueprints skill scripts.

These tests verify the skill scripts can be loaded and executed correctly.
They mock the unreal module since we're not inside Unreal Engine.
"""

from __future__ import annotations

import importlib.util
import sys
from unittest.mock import MagicMock, patch


def _load_module(name: str, path: str):
    """Load a skill script module for testing."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    return module, spec


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
