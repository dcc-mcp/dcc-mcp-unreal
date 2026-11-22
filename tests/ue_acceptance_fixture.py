"""Create, save, reopen, and verify the smallest native Niagara fixture."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import unreal


def _write_result(result: dict) -> None:
    result_path = os.environ.get("DCC_MCP_UNREAL_TEST_RESULT", "")
    if result_path:
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    unreal.log("DCC_MCP_ACCEPTANCE_FIXTURE=" + json.dumps(result, separators=(",", ":")))


def main() -> dict:
    result: dict = {"fixture": "synthetic-channel-contract", "success": False}
    try:
        engine_version = str(unreal.SystemLibrary.get_engine_version())
        result["engine_version"] = engine_version
        if not engine_version.startswith("5.8"):
            raise RuntimeError(f"The fixture is qualified for UE 5.8, got {engine_version}")
        bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
        author = getattr(bridge, "author_niagara_system_json", None)
        if not callable(author):
            raise RuntimeError("DccMcpUnreal native Niagara bridge is unavailable")

        asset_name = "NS_DccMcpAcceptance_" + uuid.uuid4().hex[:8]
        package_path = "/Game/Acceptance"
        asset_path = f"{package_path}/{asset_name}"
        specification = {
            "asset_name": asset_name,
            "asset_path": package_path,
            "emitters": [
                {
                    "name": "AcceptanceEmitter",
                    "modules": [],
                    "renderers": [
                        {
                            "name": "SpriteRenderer",
                            "class_path": "/Script/Niagara.NiagaraSpriteRendererProperties",
                        }
                    ],
                }
            ],
        }
        native = json.loads(author(json.dumps(specification, separators=(",", ":"))))
        reopened = unreal.EditorAssetLibrary.load_asset(asset_path)
        ndc_name = "NDC_DccMcpAcceptance_" + uuid.uuid4().hex[:8]
        ndc_path = f"/Game/Acceptance/{ndc_name}"
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        ndc_factory = unreal.NiagaraDataChannelAssetFactoryNew()
        ndc_asset = asset_tools.create_asset(
            ndc_name,
            "/Game/Acceptance",
            unreal.NiagaraDataChannelAsset,
            ndc_factory,
        )
        global_class = unreal.load_class(None, "/Script/Niagara.NiagaraDataChannel_Global")
        if ndc_asset is None or global_class is None:
            raise RuntimeError("Niagara Global Data Channel classes are unavailable")
        channel = unreal.new_object(global_class, outer=ndc_asset)
        channel_variable = unreal.NiagaraDataChannelVariable()
        # The native type registry index is recorded in the fixture evidence.
        # Index 0 is the first stable scalar type exposed by the UE 5.8 host.
        channel_variable.import_text(
            '(Version=026F3C6F492337AD9DB0C5A846F7C0A6,Name="Position",TypeDefHandle=(RegisteredTypeIndex=0))'
        )
        channel.set_editor_property("channel_variables", [channel_variable])
        channel.set_editor_property("keep_previous_frame_data", False)
        ndc_asset.set_editor_property("data_channel", channel)
        ndc_saved = bool(unreal.EditorAssetLibrary.save_asset(ndc_path, only_if_is_dirty=False))
        unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(["/Game/Acceptance"], force_rescan=True)
        reopened_ndc = unreal.EditorAssetLibrary.load_asset(ndc_path)
        reopened_channel = reopened_ndc.get_editor_property("data_channel") if reopened_ndc else None
        reopened_variables = reopened_channel.get_editor_property("channel_variables") if reopened_channel else []
        ndc_readback = [variable.export_text() for variable in reopened_variables]
        result.update(
            {
                "asset_path": asset_path,
                "native": native,
                "saved": native.get("saved") is True,
                "native_verified": native.get("verified") is True,
                "reopened": reopened is not None and isinstance(reopened, unreal.NiagaraSystem),
                "exists_after_reopen": unreal.EditorAssetLibrary.does_asset_exist(asset_path),
                "ndc_asset_path": ndc_path,
                "ndc_saved": ndc_saved,
                "ndc_reopened": reopened_ndc is not None,
                "ndc_global_routing": reopened_channel is not None
                and reopened_channel.get_class().get_name() == "NiagaraDataChannel_Global",
                "ndc_payload_readback": any('Name="Position"' in value for value in ndc_readback),
                "ndc_lifecycle": "create_save_reopen",
            }
        )
        result["success"] = all(
            (
                result["saved"],
                result["native_verified"],
                result["reopened"],
                result["exists_after_reopen"],
                result["ndc_saved"],
                result["ndc_reopened"],
                result["ndc_global_routing"],
                result["ndc_payload_readback"],
            )
        )
        if not result["success"]:
            raise RuntimeError("Native Niagara fixture postconditions were not satisfied")
        return result
    except Exception as exc:
        result["error"] = str(exc)[:1000]
        raise
    finally:
        _write_result(result)
        unreal.SystemLibrary.quit_editor()


if __name__ == "__main__":
    main()
