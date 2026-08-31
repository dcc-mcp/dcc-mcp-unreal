"""Connect a material expression output to a root Customized UV input."""

from __future__ import annotations

import json
from typing import Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _native_result(payload: object, operation: str) -> tuple[Optional[dict], Optional[dict]]:
    try:
        value = json.loads(payload) if isinstance(payload, str) else payload
    except (TypeError, ValueError) as exc:
        return None, skill_error(
            f"Native material {operation} returned invalid JSON",
            "invalid_native_result",
            error_code="invalid_native_result",
            detail=str(exc),
        )
    if not isinstance(value, dict):
        return None, skill_error(
            f"Native material {operation} returned an invalid result",
            "invalid_native_result",
            error_code="invalid_native_result",
        )
    return value, None


@skill_entry
def connect_material_expression_to_customized_uv(
    material_path: str = "",
    source_expression_name: str = "",
    source_output_index: Optional[int] = None,
    source_output_name: str = "",
    customized_uv_index: int = -1,
    replace_existing: bool = False,
    **kwargs,
) -> dict:
    """Connect exactly one named material expression output and verify persistence."""
    import unreal  # noqa: PLC0415

    if (
        not isinstance(material_path, str)
        or not material_path.startswith("/Game/")
        or not isinstance(source_expression_name, str)
        or not source_expression_name.strip()
    ):
        return skill_error(
            "Invalid material graph target",
            "invalid_material_target",
            error_code="invalid_material_target",
            detail="material_path must be under /Game and source_expression_name is required",
        )
    if (
        not isinstance(customized_uv_index, int)
        or isinstance(customized_uv_index, bool)
        or not 0 <= customized_uv_index <= 7
    ):
        return skill_error(
            "Invalid Customized UV index",
            "invalid_customized_uv_index",
            error_code="invalid_customized_uv_index",
            detail="customized_uv_index must be an integer from 0 through 7",
        )

    if not isinstance(source_output_name, str) or not isinstance(replace_existing, bool):
        return skill_error(
            "Invalid material graph options",
            "invalid_material_options",
            error_code="invalid_material_options",
            detail="source_output_name must be a string and replace_existing must be a boolean",
        )
    has_output_index = source_output_index is not None
    has_output_name = bool(source_output_name.strip())
    if has_output_index == has_output_name:
        return skill_error(
            "Select exactly one source output",
            "invalid_output_selector",
            error_code="invalid_output_selector",
            detail="Provide source_output_index or source_output_name, but not both",
        )
    if has_output_index and (
        not isinstance(source_output_index, int) or isinstance(source_output_index, bool) or source_output_index < 0
    ):
        return skill_error(
            "Invalid source output index",
            "invalid_output_selector",
            error_code="invalid_output_selector",
            detail="source_output_index must be a non-negative integer",
        )

    material = unreal.EditorAssetLibrary.load_asset(material_path)
    if material is None or not isinstance(material, unreal.Material):
        return skill_error(
            "Material not found",
            "material_not_found",
            error_code="material_not_found",
            material_path=material_path,
        )

    expressions = list(unreal.MaterialEditingLibrary.get_material_expressions(material))
    matches = [expression for expression in expressions if expression.get_name() == source_expression_name]
    if len(matches) != 1:
        return skill_error(
            "Material expression not found uniquely",
            "source_expression_not_found",
            error_code="source_expression_not_found",
            source_expression_name=source_expression_name,
            match_count=len(matches),
        )

    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    connect = getattr(bridge, "connect_material_expression_to_customized_uv", None)
    inspect = getattr(bridge, "get_material_customized_uv_connection", None)
    if not callable(connect) or not callable(inspect):
        return skill_error(
            "Customized UV native bridge is unavailable",
            "native_capability_unavailable",
            error_code="native_capability_unavailable",
            possible_solutions=[
                "Install and restart with a DccMcpUnreal plugin that exposes the material graph bridge"
            ],
        )

    requested_output_index = source_output_index if has_output_index else -1
    native, error = _native_result(
        connect(
            material,
            matches[0],
            requested_output_index,
            source_output_name,
            customized_uv_index,
            replace_existing,
        ),
        "connection",
    )
    if error:
        return error
    assert native is not None
    if not native.get("success"):
        error_code = str(native.get("error_code") or "native_connection_failed")
        return skill_error(
            str(native.get("message") or "Native Customized UV connection failed"),
            error_code,
            error_code=error_code,
            native_result=native,
        )

    readback, error = _native_result(inspect(material, customized_uv_index), "readback")
    if error:
        return error
    assert readback is not None
    expected = {
        "connected": True,
        "customized_uv_index": customized_uv_index,
        "source_expression_name": source_expression_name,
        "source_output_index": native.get("source_output_index"),
        "package_dirty": False,
    }
    actual = {key: readback.get(key) for key in expected}
    if actual != expected or not native.get("saved") or not native.get("verified"):
        return skill_error(
            "Customized UV post-save verification failed",
            "postcondition_not_met",
            error_code="postcondition_not_met",
            expected=expected,
            actual=actual,
            native_result=native,
        )

    return skill_success(
        f"Connected '{source_expression_name}' output {native['source_output_index']} to Customized UV {customized_uv_index}",
        verified=True,
        postcondition={"method": "native_post_save_readback", "expected": expected, "actual": actual},
        material_path=material_path,
        source_expression_name=source_expression_name,
        source_output_index=native["source_output_index"],
        source_output_name=native.get("source_output_name", ""),
        customized_uv_index=customized_uv_index,
        changed=bool(native.get("changed")),
        saved=True,
    )
