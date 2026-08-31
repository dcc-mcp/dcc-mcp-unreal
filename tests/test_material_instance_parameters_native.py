from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "src" / "dcc_mcp_unreal" / "skills" / "unreal-materials"
SCRIPT = SKILL / "scripts" / "set_material_instance_parameters.py"
HEADER = ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Public" / "DccMcpAutomationLibrary.h"
IMPLEMENTATION = (
    ROOT / "unreal" / "plugin" / "Source" / "DccMcpUnreal" / "Private" / "DccMcpAutomationLibrary.cpp"
)


def _load_script():
    spec = importlib.util.spec_from_file_location("test_set_material_instance_parameters", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_material_instance_bridge_is_transactional_saved_and_verified() -> None:
    header = HEADER.read_text(encoding="utf-8")
    implementation = IMPLEMENTATION.read_text(encoding="utf-8")

    assert "static FString ConfigureMaterialInstanceParameters(" in header
    assert "Instance->SetScalarParameterValueEditorOnly" in implementation
    assert "Instance->SetVectorParameterValueEditorOnly" in implementation
    assert "Instance->SetTextureParameterValueEditorOnly" in implementation
    assert "PreviousScalarParameters" in implementation
    assert "PreviousVectorParameters" in implementation
    assert "PreviousTextureParameters" in implementation
    assert "SaveAssetPackage(Instance, Filename)" in implementation
    assert 'Root->SetBoolField(TEXT("verified"), true)' in implementation
    assert "Transaction.Cancel()" in implementation
    assert "#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION <= 18" in implementation
    assert "MaterialInstanceParameterName(Value)" in implementation
    assert "ScalarArraysEqual" in implementation
    assert "VectorArraysEqual" in implementation
    assert "TextureArraysEqual" in implementation


def test_python_tool_routes_all_parameter_types_through_native_bridge() -> None:
    class MaterialInstanceConstant:
        pass

    class Texture:
        pass

    instance = MaterialInstanceConstant()
    texture = Texture()
    vector = object()
    bridge = types.SimpleNamespace(
        configure_material_instance_parameters=MagicMock(
            return_value=json.dumps(
                {
                    "success": True,
                    "changed": True,
                    "saved": True,
                    "verified": True,
                    "package_dirty": False,
                }
            )
        )
    )
    unreal = types.ModuleType("unreal")
    unreal.MaterialInstanceConstant = MaterialInstanceConstant
    unreal.Texture = Texture
    unreal.LinearColor = MagicMock(return_value=vector)
    unreal.EditorAssetLibrary = types.SimpleNamespace(
        load_asset=MagicMock(side_effect=lambda path: instance if path == "/Game/MI" else texture)
    )
    unreal.DccMcpAutomationLibrary = bridge

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().set_material_instance_parameters(
            instance_path="/Game/MI",
            scalar_parameters={"speed": 30},
            vector_parameters={"tint": [1, 0.5, 0.25]},
            texture_parameters={"position": "/Game/T_Position"},
        )

    assert result["success"] is True
    assert result["context"]["native_verified"] is True
    bridge.configure_material_instance_parameters.assert_called_once_with(
        instance,
        {"speed": 30.0},
        {"tint": vector},
        {"position": texture},
    )


def test_invalid_vector_components_fail_before_native_mutation() -> None:
    class MaterialInstanceConstant:
        pass

    instance = MaterialInstanceConstant()
    bridge = types.SimpleNamespace(configure_material_instance_parameters=MagicMock())
    unreal = types.ModuleType("unreal")
    unreal.MaterialInstanceConstant = MaterialInstanceConstant
    unreal.EditorAssetLibrary = types.SimpleNamespace(load_asset=MagicMock(return_value=instance))
    unreal.DccMcpAutomationLibrary = bridge

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_script().set_material_instance_parameters(
            instance_path="/Game/MI",
            vector_parameters={"tint": ["invalid", 0.5, 0.25]},
        )

    assert result["success"] is False
    bridge.configure_material_instance_parameters.assert_not_called()
