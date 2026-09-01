"""Contracts for UE 5.8 Niagara semantic authoring."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/dcc_mcp_unreal/skills/unreal-niagara/scripts/author_niagara_system.py"
TOOLS = ROOT / "src/dcc_mcp_unreal/skills/unreal-niagara/tools.yaml"
HEADER = ROOT / "unreal/plugin/Source/DccMcpUnreal/Public/DccMcpAutomationLibrary.h"
IMPLEMENTATION = ROOT / "unreal/plugin/Source/DccMcpUnreal/Private/DccMcpAutomationLibrary.cpp"
BUILD_RULES = ROOT / "unreal/plugin/Source/DccMcpUnreal/DccMcpUnreal.Build.cs"
COMMANDLET_PROBE = ROOT / "tests/ue_niagara_commandlet.py"
SMOKE_RUNNER = ROOT / "scripts/run_ue_smoke.ps1"
JUSTFILE = ROOT / "Justfile"


def _load_authoring_script():
    spec = importlib.util.spec_from_file_location("author_niagara_system_contract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _five_stage_chain_spec() -> list[dict]:
    emitters = []
    for stage in range(1, 6):
        for layer in ("core", "plume", "sparks"):
            emitters.append(
                {
                    "name": f"Stage{stage}_{layer}",
                    "modules": [
                        {
                            "name": "SpawnBurst",
                            "script": "emitter_update",
                            "asset_path": "/Niagara/Modules/Emitter/SpawnBurst_Instantaneous.SpawnBurst_Instantaneous",
                            "inputs": {"Spawn Count": {"type": "int", "value": stage * 10}},
                        },
                        {
                            "name": "ShapeLocation",
                            "script": "particle_spawn",
                            "asset_path": "/Niagara/Modules/Spawn/Location/V2/ShapeLocation.ShapeLocation",
                            "inputs": {"Sphere Radius": {"type": "float", "value": 50.0 * stage}},
                        },
                        {
                            "name": "AddVelocity",
                            "script": "particle_spawn",
                            "asset_path": "/Niagara/Modules/Spawn/Velocity/AddVelocity.AddVelocity",
                            "inputs": {"Velocity": {"type": "vector3", "value": [0.0, 0.0, 250.0 * stage]}},
                        },
                        {
                            "name": "GravityForce",
                            "script": "particle_update",
                            "asset_path": "/Niagara/Modules/Update/Forces/GravityForce.GravityForce",
                            "inputs": {"Gravity": {"type": "vector3", "value": [0.0, 0.0, -980.0]}},
                        },
                    ],
                    "renderers": [
                        {
                            "name": "SpriteRenderer",
                            "class_path": "/Script/Niagara.NiagaraSpriteRendererProperties",
                        }
                    ],
                }
            )
    return emitters


def test_authoring_tool_forwards_complete_five_stage_semantics_to_native_bridge() -> None:
    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.EditorLevelLibrary = MagicMock()
    unreal.DccMcpAutomationLibrary = MagicMock()
    unreal.DccMcpAutomationLibrary.author_niagara_system_json.return_value = json.dumps(
        {
            "success": True,
            "system_path": "/Game/VFX/NS_ChainExplosion",
            "emitter_count": 15,
            "module_count": 60,
            "renderer_count": 15,
            "saved": True,
            "verified": True,
        }
    )
    emitters = _five_stage_chain_spec()

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_authoring_script().author_niagara_system(
            system_name="NS_ChainExplosion",
            package_path="/Game/VFX",
            emitters=emitters,
        )

    assert result["success"] is True
    assert result["context"]["emitter_count"] == 15
    payload = json.loads(unreal.DccMcpAutomationLibrary.author_niagara_system_json.call_args.args[0])
    assert payload["asset_name"] == "NS_ChainExplosion"
    assert payload["asset_path"] == "/Game/VFX"
    assert payload["emitters"] == emitters
    assert {emitter["name"].split("_", 1)[0] for emitter in emitters} == {
        "Stage1",
        "Stage2",
        "Stage3",
        "Stage4",
        "Stage5",
    }
    assert all(
        {module["name"] for module in emitter["modules"]}
        >= {
            "SpawnBurst",
            "ShapeLocation",
            "AddVelocity",
            "GravityForce",
        }
        for emitter in emitters
    )
    assert all(emitter["renderers"][0]["name"] == "SpriteRenderer" for emitter in emitters)


def test_authoring_tool_preserves_stable_native_failure_contract() -> None:
    unreal = types.ModuleType("unreal")
    unreal.log = MagicMock()
    unreal.EditorLevelLibrary = MagicMock()
    unreal.DccMcpAutomationLibrary = MagicMock()
    unreal.DccMcpAutomationLibrary.author_niagara_system_json.return_value = json.dumps(
        {
            "success": False,
            "error_code": "niagara_editor_unavailable",
            "message": "Niagara semantic authoring requires a fully loaded interactive Unreal Editor with Slate.",
            "rollback_completed": True,
        }
    )

    with patch.dict(sys.modules, {"unreal": unreal}):
        result = _load_authoring_script().author_niagara_system(
            system_name="NS_Commandlet",
            emitters=_five_stage_chain_spec()[:1],
        )

    assert result["success"] is False
    assert result["context"]["error_code"] == "niagara_editor_unavailable"
    assert result["context"]["rollback_completed"] is True


def test_authoring_tool_schema_expresses_emitters_modules_renderers_and_typed_inputs() -> None:
    tools = yaml.safe_load(TOOLS.read_text(encoding="utf-8"))["tools"]
    tool = next(item for item in tools if item["name"] == "author_niagara_system")
    schema = tool["input_schema"]
    emitter = schema["properties"]["emitters"]["items"]
    module = emitter["properties"]["modules"]["items"]
    renderer = emitter["properties"]["renderers"]["items"]
    input_value = module["properties"]["inputs"]["additionalProperties"]

    assert schema["required"] == ["system_name", "emitters"]
    assert set(module["properties"]["script"]["enum"]) == {
        "emitter_spawn",
        "emitter_update",
        "particle_spawn",
        "particle_update",
    }
    assert set(input_value["properties"]["type"]["enum"]) >= {"float", "int", "vector3", "bool", "enum"}
    assert renderer["properties"]["class_path"]["default"] == "/Script/Niagara.NiagaraSpriteRendererProperties"


def test_native_bridge_guards_external_ue58_api_before_any_editor_mutation() -> None:
    header = HEADER.read_text(encoding="utf-8")
    source = IMPLEMENTATION.read_text(encoding="utf-8")
    rules = BUILD_RULES.read_text(encoding="utf-8")

    assert "AuthorNiagaraSystemJson" in header
    assert "NiagaraExternalSystemEditorUtilities.h" in source
    assert "UNiagaraExternalEditUtilities::CreateNiagaraSystem" in source
    assert "UNiagaraExternalEditUtilities::AddEmitter" in source
    assert "UNiagaraExternalEditUtilities::AddModule" in source
    assert "UNiagaraExternalEditUtilities::AddRenderer" in source
    assert "UNiagaraExternalEditUtilities::SetStackInputData" in source
    assert 'TEXT("niagara_editor_unavailable")' in source
    guard = source.index("NiagaraAuthoringPreflight")
    create = source.index("UNiagaraExternalEditUtilities::CreateNiagaraSystem")
    assert guard < create
    assert "FSlateApplication::IsInitialized()" in source[guard:create]
    assert "IsRunningCommandlet()" in source[guard:create]
    assert "MaxNiagaraSpecificationChars" in source
    assert "MaxNiagaraModules" in source
    assert "MaxNiagaraInputs" in source
    assert "TryGetFiniteFloat" in source
    assert "IsValidLongPackageName(OutAssetPath / OutAssetName)" in source
    assert '"Niagara"' in rules and '"NiagaraEditor"' in rules


def test_commandlet_probe_requires_stable_fail_closed_result_without_asset_mutation() -> None:
    probe = COMMANDLET_PROBE.read_text(encoding="utf-8")
    runner = SMOKE_RUNNER.read_text(encoding="utf-8")
    justfile = JUSTFILE.read_text(encoding="utf-8")

    assert "author_niagara_system_json" in probe
    assert 'error_code == "niagara_editor_unavailable"' in probe
    assert "rollback_completed" in probe
    assert "does_asset_exist" in probe
    assert 'ValidateSet("native", "python", "niagara", "niagara-commandlet")' in runner
    assert "-run=pythonscript" in runner
    assert "ue_niagara_commandlet.py" in runner
    assert "DccMcp.Smoke.NiagaraSemanticAuthoring" in runner
    assert "ue-niagara-smoke" in justfile
    assert "ue-niagara-commandlet" in justfile
