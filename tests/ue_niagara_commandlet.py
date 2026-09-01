"""Verify that Niagara semantic authoring fails closed in commandlet mode."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import unreal


def main() -> dict:
    asset_name = f"NS_DccMcpCommandletProbe_{uuid.uuid4().hex[:8]}"
    package_path = "/Game/DccMcpAutomation/Commandlet"
    object_path = f"{package_path}/{asset_name}"
    specification = {
        "asset_name": asset_name,
        "asset_path": package_path,
        "emitters": [
            {
                "name": "Probe",
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

    native_result = json.loads(
        unreal.DccMcpAutomationLibrary.author_niagara_system_json(json.dumps(specification, separators=(",", ":")))
    )
    error_code = native_result.get("error_code")
    asset_exists = unreal.EditorAssetLibrary.does_asset_exist(object_path)
    success = (
        native_result.get("success") is False
        and error_code == "niagara_editor_unavailable"
        and native_result.get("rollback_completed") is True
        and not asset_exists
    )
    result = {
        "success": success,
        "error_code": error_code,
        "rollback_completed": native_result.get("rollback_completed"),
        "asset_exists": asset_exists,
    }

    result_path = os.environ.get("DCC_MCP_UNREAL_TEST_RESULT", "")
    if result_path:
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    unreal.log(f"DCC_MCP_NIAGARA_COMMANDLET_RESULT={json.dumps(result, separators=(',', ':'))}")
    if not success:
        raise RuntimeError(f"Niagara commandlet contract failed: {result}")
    return result


if __name__ == "__main__":
    main()
