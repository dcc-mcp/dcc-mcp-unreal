from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-materials"
SCRIPT = SKILL / "scripts" / "connect_material_expression_to_customized_uv.py"
HEADER = ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Public" / "DccMcpAutomationLibrary.h"
IMPLEMENTATION = ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpAutomationLibrary.cpp"


def _load_script():
    spec = importlib.util.spec_from_file_location("test_connect_material_customized_uv", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Material:
    pass


class _Expression:
    def __init__(self, name: str):
        self._name = name

    def get_name(self) -> str:
        return self._name


def _unreal_module(*, connect_result: dict, inspect_result: dict):
    material = _Material()
    expression = _Expression("MaterialExpressionMaterialFunctionCall_0")
    bridge = types.SimpleNamespace(
        connect_material_expression_to_customized_uv=MagicMock(return_value=json.dumps(connect_result)),
        get_material_customized_uv_connection=MagicMock(return_value=json.dumps(inspect_result)),
    )
    unreal = types.ModuleType("unreal")
    unreal.Material = _Material
    unreal.EditorAssetLibrary = types.SimpleNamespace(load_asset=MagicMock(return_value=material))
    unreal.MaterialEditingLibrary = types.SimpleNamespace(get_material_expressions=MagicMock(return_value=[expression]))
    unreal.DccMcpAutomationLibrary = bridge
    return unreal, material, expression, bridge


def test_customized_uv_tool_schema_is_strongly_typed_and_bounded() -> None:
    tools = yaml.safe_load((SKILL / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    tool = next(tool for tool in tools if tool["name"] == "connect_material_expression_to_customized_uv")
    schema = tool["input_schema"]

    assert schema["required"] == ["material_path", "source_expression_name", "customized_uv_index"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["customized_uv_index"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 7,
        "description": "Zero-based Customized UV input index on the material root node.",
    }
    assert schema["properties"]["source_output_index"]["minimum"] == 0
    assert schema["properties"]["source_output_name"]["minLength"] == 1
    assert schema["properties"]["replace_existing"]["default"] is False
    assert schema["oneOf"] == [
        {
            "required": ["source_output_index"],
            "not": {"required": ["source_output_name"]},
        },
        {
            "required": ["source_output_name"],
            "not": {"required": ["source_output_index"]},
        },
    ]


def test_native_bridge_uses_editor_only_customized_uv_and_synchronous_save_verification() -> None:
    header = HEADER.read_text(encoding="utf-8")
    implementation = IMPLEMENTATION.read_text(encoding="utf-8")

    assert "class UMaterial;" in header
    assert "class UMaterialExpression;" in header
    assert "static FString ConnectMaterialExpressionToCustomizedUv(" in header
    assert "static FString GetMaterialCustomizedUvConnection(" in header
    assert "EditorOnlyData->CustomizedUVs[CustomizedUvIndex].Connect" in implementation
    assert "EditorOnlyData->ExpressionCollection.Expressions.Contains(SourceExpression)" in implementation
    assert "FScopedTransaction Transaction" in implementation
    assert "UPackage::SavePackage" in implementation
    assert "Package->IsDirty()" in implementation
    assert "MP_CustomizedUVs" not in implementation


def test_connects_by_output_index_and_verifies_the_saved_connection() -> None:
    native_result = {
        "success": True,
        "changed": True,
        "saved": True,
        "verified": True,
        "customized_uv_index": 1,
        "source_expression_name": "MaterialExpressionMaterialFunctionCall_0",
        "source_output_index": 19,
        "source_output_name": "Position",
        "package_dirty": False,
    }
    unreal, material, expression, bridge = _unreal_module(
        connect_result=native_result,
        inspect_result={**native_result, "connected": True},
    )

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().connect_material_expression_to_customized_uv(
            material_path="/Game/VAT/M_VAT.M_VAT",
            source_expression_name=expression.get_name(),
            source_output_index=19,
            customized_uv_index=1,
        )

    assert result["success"] is True
    assert result["context"]["saved"] is True
    assert result["postcondition"]["verified"] is True
    bridge.connect_material_expression_to_customized_uv.assert_called_once_with(
        material,
        expression,
        19,
        "",
        1,
        False,
    )
    bridge.get_material_customized_uv_connection.assert_called_once_with(material, 1)


def test_output_index_and_name_are_mutually_exclusive_before_native_mutation() -> None:
    unreal, _, expression, bridge = _unreal_module(connect_result={}, inspect_result={})

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().connect_material_expression_to_customized_uv(
            material_path="/Game/VAT/M_VAT.M_VAT",
            source_expression_name=expression.get_name(),
            source_output_index=19,
            source_output_name="Position",
            customized_uv_index=1,
        )

    assert result["success"] is False
    bridge.connect_material_expression_to_customized_uv.assert_not_called()


@pytest.mark.parametrize("customized_uv_index", [True, 1.5, "1", None])
def test_invalid_customized_uv_types_fail_before_loading_or_mutation(customized_uv_index: object) -> None:
    unreal, _, expression, bridge = _unreal_module(connect_result={}, inspect_result={})

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().connect_material_expression_to_customized_uv(
            material_path="/Game/VAT/M_VAT.M_VAT",
            source_expression_name=expression.get_name(),
            source_output_index=19,
            customized_uv_index=customized_uv_index,
        )

    assert result["success"] is False
    assert result["context"]["error_code"] == "invalid_customized_uv_index"
    unreal.EditorAssetLibrary.load_asset.assert_not_called()
    bridge.connect_material_expression_to_customized_uv.assert_not_called()


def test_native_save_failure_is_propagated_without_false_readback() -> None:
    native_result = {
        "success": False,
        "error_code": "material_save_failed",
        "message": "Unreal failed to save the Material package",
        "rollback_completed": True,
    }
    unreal, _, expression, bridge = _unreal_module(connect_result=native_result, inspect_result={})

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().connect_material_expression_to_customized_uv(
            material_path="/Game/VAT/M_VAT.M_VAT",
            source_expression_name=expression.get_name(),
            source_output_name="Position",
            customized_uv_index=1,
        )

    assert result["success"] is False
    assert result["context"]["error_code"] == "material_save_failed"
    assert result["context"]["native_result"]["rollback_completed"] is True
    bridge.get_material_customized_uv_connection.assert_not_called()


def test_post_save_readback_drift_fails_closed() -> None:
    native_result = {
        "success": True,
        "changed": True,
        "saved": True,
        "verified": True,
        "customized_uv_index": 2,
        "source_expression_name": "MaterialExpressionMaterialFunctionCall_0",
        "source_output_index": 20,
        "source_output_name": "Normal",
        "package_dirty": False,
    }
    unreal, _, expression, _ = _unreal_module(
        connect_result=native_result,
        inspect_result={
            **native_result,
            "connected": True,
            "source_output_index": 21,
        },
    )

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().connect_material_expression_to_customized_uv(
            material_path="/Game/VAT/M_VAT.M_VAT",
            source_expression_name=expression.get_name(),
            source_output_name="Normal",
            customized_uv_index=2,
        )

    assert result["success"] is False
    assert result["context"]["error_code"] == "postcondition_not_met"
