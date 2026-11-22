"""Create and verify a Niagara Data Channel asset through Unreal Python."""

from __future__ import annotations

import re

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_VERSION_GUID = "026F3C6F492337AD9DB0C5A846F7C0A6"
_ROUTING_CLASSES = {
    "global": "/Script/Niagara.NiagaraDataChannel_Global",
    "islands": "/Script/Niagara.NiagaraDataChannel_Islands",
}


def _validate_fields(fields: list[dict]) -> list[dict]:
    if not isinstance(fields, list) or not 1 <= len(fields) <= 64:
        raise ValueError("fields must contain 1..64 entries")
    names: set[str] = set()
    normalized = []
    for field in fields:
        if not isinstance(field, dict) or set(field) != {"name", "type_registry_index"}:
            raise ValueError("each field requires name and type_registry_index")
        name = field["name"]
        index = field["type_registry_index"]
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("field names must be Unreal-safe identifiers")
        if name.casefold() in names:
            raise ValueError("field names must be unique")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 65535:
            raise ValueError("type_registry_index must be an integer in [0, 65535]")
        names.add(name.casefold())
        normalized.append({"name": name, "type_registry_index": index})
    return normalized


def _field_text(field: dict) -> str:
    return (
        f'(Version={_VERSION_GUID},Name="{field["name"]}",'
        f"TypeDefHandle=(RegisteredTypeIndex={field['type_registry_index']}))"
    )


@skill_entry
def create_niagara_data_channel(
    channel_name: str,
    fields: list[dict],
    package_path: str = "/Game/VFX",
    routing: str = "global",
    keep_previous_frame_data: bool = False,
    **kwargs,
) -> dict:
    """Create an NDC asset and verify its persisted payload and routing."""
    if kwargs:
        return skill_error("Invalid Niagara Data Channel request", "Unknown arguments", error_kind="invalid_input")
    try:
        if not isinstance(channel_name, str) or not _NAME.fullmatch(channel_name):
            raise ValueError("channel_name must be an Unreal-safe identifier")
        if not isinstance(package_path, str) or not package_path.startswith("/Game"):
            raise ValueError("package_path must start with /Game")
        if routing not in _ROUTING_CLASSES:
            raise ValueError("routing must be global or islands")
        normalized = _validate_fields(fields)
    except ValueError as exc:
        return skill_error("Invalid Niagara Data Channel request", str(exc), error_kind="invalid_input")

    try:
        import unreal  # noqa: PLC0415

        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.NiagaraDataChannelAssetFactoryNew()
        asset = asset_tools.create_asset(channel_name, package_path, unreal.NiagaraDataChannelAsset, factory)
        if asset is None:
            raise RuntimeError("NiagaraDataChannelAssetFactoryNew returned no asset")
        channel_class = unreal.load_class(None, _ROUTING_CLASSES[routing])
        if channel_class is None:
            raise RuntimeError(f"NDC routing class is unavailable: {routing}")
        channel = unreal.new_object(channel_class, outer=asset)
        variables = []
        for field in normalized:
            variable = unreal.NiagaraDataChannelVariable()
            variable.import_text(_field_text(field))
            variables.append(variable)
        channel.set_editor_property("channel_variables", variables)
        channel.set_editor_property("keep_previous_frame_data", keep_previous_frame_data)
        asset.set_editor_property("data_channel", channel)
        asset_path = f"{package_path.rstrip('/')}/{channel_name}"
        saved = bool(unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False))
        unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous([package_path], force_rescan=True)
        reopened = unreal.EditorAssetLibrary.load_asset(asset_path)
        reopened_channel = reopened.get_editor_property("data_channel") if reopened else None
        readback = [
            variable.export_text()
            for variable in (reopened_channel.get_editor_property("channel_variables") if reopened_channel else [])
        ]
        payload_verified = all(f'Name="{field["name"]}"' in value for field, value in zip(normalized, readback))
        routing_verified = (
            reopened_channel is not None
            and reopened_channel.get_class().get_name() == f"NiagaraDataChannel_{routing.title()}"
        )
        result = {
            "asset_path": asset_path,
            "engine_version": str(unreal.SystemLibrary.get_engine_version()),
            "routing": routing,
            "routing_verified": routing_verified,
            "fields": normalized,
            "payload_readback": readback,
            "payload_verified": payload_verified,
            "saved": saved,
            "reopened": reopened is not None,
            "lifecycle": "create_save_reopen",
        }
    except (ImportError, RuntimeError, TypeError, ValueError) as exc:
        return skill_error("Niagara Data Channel creation failed", str(exc)[:1000], error_kind="native_unavailable")

    if not saved or not result["reopened"] or not payload_verified or not routing_verified:
        return skill_error(
            "Niagara Data Channel verification failed",
            "Persisted routing or payload readback differs from the request",
            error_kind="postcondition_failed",
            **result,
        )
    return skill_success("Created and verified a Niagara Data Channel asset.", **result)
