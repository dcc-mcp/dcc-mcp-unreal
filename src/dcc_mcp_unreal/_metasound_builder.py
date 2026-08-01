"""Verified Unreal MetaSound Builder API helpers.

This module deliberately uses only reflected APIs exposed by Unreal's Python
plugin.  All Unreal imports are lazy so importing ``dcc_mcp_unreal`` outside
the editor remains safe.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

_MIN_ENGINE_VERSION = (5, 4)
_ASSET_PATH_RE = re.compile(r"^/Game(?:/[A-Za-z0-9_]+)+$")
_NODE_HANDLE_RE = re.compile(r"^\(NodeID=[0-9A-Fa-f]{32}\)$")
_VERTEX_HANDLE_RE = re.compile(r"^\(NodeID=[0-9A-Fa-f]{32},VertexID=[0-9A-Fa-f]{32}\)$")

_LOGGER = logging.getLogger(__name__)


class MetaSoundOperationError(RuntimeError):
    """Raised when an Unreal MetaSound operation cannot be verified."""


@dataclass(frozen=True)
class MetaSoundContext:
    """Loaded MetaSound asset and its official editor builder."""

    unreal: Any
    asset: Any
    builder: Any
    editor_subsystem: Any
    builder_subsystem: Any


def validate_asset_path(asset_path: str) -> Tuple[str, str]:
    """Validate and split a package path into ``(package_path, asset_name)``."""
    if not isinstance(asset_path, str) or not _ASSET_PATH_RE.fullmatch(asset_path):
        raise MetaSoundOperationError(
            "asset_path must be a package path such as '/Game/Audio/MS_Tone' "
            "using only letters, digits, and underscores"
        )
    package_path, asset_name = asset_path.rsplit("/", 1)
    return package_path, asset_name


def _import_unreal() -> Any:
    try:
        import unreal
    except ImportError as exc:  # pragma: no cover - requires a non-Unreal process
        raise MetaSoundOperationError("MetaSound tools must run inside Unreal Editor's Python runtime") from exc
    return unreal


def _engine_version(unreal: Any) -> str:
    try:
        version = str(unreal.SystemLibrary.get_engine_version())
    except Exception as exc:
        raise MetaSoundOperationError("Unable to determine the Unreal Engine version") from exc
    match = re.match(r"^(\d+)\.(\d+)", version)
    if match is None:
        raise MetaSoundOperationError(
            "Unable to parse the Unreal Engine version; refusing an unverified MetaSound call"
        )
    parsed = (int(match.group(1)), int(match.group(2)))
    if parsed < _MIN_ENGINE_VERSION:
        raise MetaSoundOperationError(
            f"Unreal Engine {parsed[0]}.{parsed[1]} is unsupported; MetaSound tools require 5.4 or newer"
        )
    return version


def _required_type(unreal: Any, name: str) -> Any:
    value = getattr(unreal, name, None)
    if value is None:
        raise MetaSoundOperationError(f"Unreal Python does not expose {name}; enable the MetaSound and Python plugins")
    return value


def _succeeded(unreal: Any) -> Any:
    result_type = _required_type(unreal, "MetaSoundBuilderResult")
    succeeded = getattr(result_type, "SUCCEEDED", None)
    if succeeded is None:
        raise MetaSoundOperationError("MetaSoundBuilderResult.SUCCEEDED is unavailable")
    return succeeded


def _expect_tuple_result(
    unreal: Any,
    returned: Any,
    operation: str,
    value_count: int,
) -> Tuple[Any, ...]:
    if not isinstance(returned, tuple) or len(returned) != value_count + 1:
        raise MetaSoundOperationError(f"{operation} returned an unexpected Unreal Python result shape")
    if returned[-1] != _succeeded(unreal):
        raise MetaSoundOperationError(f"{operation} failed with result {returned[-1]!s}")
    return returned[:-1]


def _expect_status(unreal: Any, returned: Any, operation: str) -> None:
    if returned != _succeeded(unreal):
        raise MetaSoundOperationError(f"{operation} failed with result {returned!s}")


def _get_subsystems(unreal: Any) -> Tuple[Any, Any]:
    builder_type = _required_type(unreal, "MetaSoundBuilderSubsystem")
    editor_type = _required_type(unreal, "MetaSoundEditorSubsystem")
    builder_subsystem = unreal.get_engine_subsystem(builder_type)
    editor_subsystem = unreal.get_editor_subsystem(editor_type)
    if builder_subsystem is None or editor_subsystem is None:
        raise MetaSoundOperationError("MetaSound Builder subsystems are unavailable; enable the MetaSound plugin")
    return builder_subsystem, editor_subsystem


def load_context(asset_path: str) -> MetaSoundContext:
    """Load a MetaSound Source and obtain the official editor builder."""
    validate_asset_path(asset_path)
    unreal = _import_unreal()
    _engine_version(unreal)
    builder_subsystem, editor_subsystem = _get_subsystems(unreal)
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if asset is None:
        raise MetaSoundOperationError(f"MetaSound Source not found: {asset_path}")
    source_type = _required_type(unreal, "MetaSoundSource")
    if not isinstance(asset, source_type):
        raise MetaSoundOperationError(f"Asset is not a MetaSound Source: {asset_path}")
    (builder,) = _expect_tuple_result(
        unreal,
        editor_subsystem.find_or_begin_building(asset),
        "FindOrBeginBuilding",
        1,
    )
    if builder is None:
        raise MetaSoundOperationError("FindOrBeginBuilding returned no builder")
    return MetaSoundContext(
        unreal=unreal,
        asset=asset,
        builder=builder,
        editor_subsystem=editor_subsystem,
        builder_subsystem=builder_subsystem,
    )


def _save_asset(context: MetaSoundContext, asset_path: str) -> None:
    saved = context.unreal.EditorAssetLibrary.save_asset(asset_path, False)
    if saved is not True:
        raise MetaSoundOperationError(f"Unreal did not confirm that the MetaSound asset was saved: {asset_path}")


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetaSoundOperationError(f"{field_name} must be a finite number")
    try:
        normalized = float(value)
    except OverflowError as exc:
        raise MetaSoundOperationError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(normalized):
        raise MetaSoundOperationError(f"{field_name} must be a finite number")
    return normalized


def _rollback_mutation(
    context: MetaSoundContext,
    operation: str,
    rollback: Any,
) -> None:
    try:
        returned = rollback()
        _expect_status(context.unreal, returned, f"Rollback{operation}")
    except Exception as rollback_error:
        raise MetaSoundOperationError(
            f"{operation} could not be saved and rollback failed; the graph may contain a partial change"
        ) from rollback_error


def _serialize_handle(handle: Any, operation: str) -> str:
    try:
        token = str(handle.export_text())
    except Exception as exc:
        raise MetaSoundOperationError(f"{operation} returned an unserializable handle") from exc
    if not (_NODE_HANDLE_RE.fullmatch(token) or _VERTEX_HANDLE_RE.fullmatch(token)):
        raise MetaSoundOperationError(f"{operation} returned an invalid handle token")
    return token


def _deserialize_handle(unreal: Any, type_name: str, token: str, pattern: re.Pattern[str]) -> Any:
    if not isinstance(token, str) or pattern.fullmatch(token) is None:
        raise MetaSoundOperationError(f"Invalid {type_name} token")
    handle_type = _required_type(unreal, type_name)
    try:
        handle = handle_type()
        handle.import_text(token)
    except Exception as exc:
        raise MetaSoundOperationError(f"Unable to import {type_name} token") from exc
    if _serialize_handle(handle, type_name).upper() != token.upper():
        raise MetaSoundOperationError(f"{type_name} token did not round-trip")
    return handle


def _node_handle(unreal: Any, token: str) -> Any:
    return _deserialize_handle(unreal, "MetaSoundNodeHandle", token, _NODE_HANDLE_RE)


def _input_handle(unreal: Any, token: str) -> Any:
    return _deserialize_handle(
        unreal,
        "MetaSoundBuilderNodeInputHandle",
        token,
        _VERTEX_HANDLE_RE,
    )


def _output_handle(unreal: Any, token: str) -> Any:
    return _deserialize_handle(
        unreal,
        "MetaSoundBuilderNodeOutputHandle",
        token,
        _VERTEX_HANDLE_RE,
    )


def _pin_data(
    context: MetaSoundContext,
    handle: Any,
    direction: str,
) -> Dict[str, str]:
    if direction == "input":
        method = context.builder.get_node_input_data
    else:
        method = context.builder.get_node_output_data
    name, data_type = _expect_tuple_result(
        context.unreal,
        method(handle),
        f"GetNode{direction.title()}Data",
        2,
    )
    return {
        "name": str(name),
        "data_type": str(data_type),
        "handle": _serialize_handle(handle, f"{direction} pin"),
    }


def _node_pins(context: MetaSoundContext, node: Any) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    (inputs,) = _expect_tuple_result(
        context.unreal,
        context.builder.find_node_inputs(node),
        "FindNodeInputs",
        1,
    )
    (outputs,) = _expect_tuple_result(
        context.unreal,
        context.builder.find_node_outputs(node),
        "FindNodeOutputs",
        1,
    )
    return (
        [_pin_data(context, handle, "input") for handle in inputs],
        [_pin_data(context, handle, "output") for handle in outputs],
    )


def _literal(context: MetaSoundContext, value_type: str, value: Any) -> Tuple[Any, str]:
    factories = {
        "Bool": ("create_bool_meta_sound_literal", bool),
        "Float": ("create_float_meta_sound_literal", float),
        "Int32": ("create_int_meta_sound_literal", int),
        "String": ("create_string_meta_sound_literal", str),
    }
    if value_type not in factories:
        raise MetaSoundOperationError("value_type must be one of Bool, Float, Int32, or String")
    factory_name, expected_type = factories[value_type]
    if expected_type is float:
        normalized = _finite_number(value, "Float value")
    elif expected_type is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise MetaSoundOperationError("Int32 values must be integers")
        if not -(2**31) <= value < 2**31:
            raise MetaSoundOperationError("Int32 value is outside the signed 32-bit range")
        normalized = value
    else:
        if not isinstance(value, expected_type):
            raise MetaSoundOperationError(f"{value_type} value has the wrong type")
        normalized = value
    factory = getattr(context.builder_subsystem, factory_name, None)
    if factory is None:
        raise MetaSoundOperationError(f"Unreal Python does not expose {factory_name}")
    returned = factory(normalized)
    if not isinstance(returned, tuple) or len(returned) != 2:
        raise MetaSoundOperationError(f"{factory_name} returned an unexpected result")
    literal, data_type = returned
    return literal, str(data_type)


def create_source(
    asset_path: str,
    author: str,
    output_format: str,
    is_one_shot: bool,
) -> Dict[str, Any]:
    """Create and save a MetaSound Source through the Builder API."""
    package_path, asset_name = validate_asset_path(asset_path)
    if not isinstance(author, str) or not author.strip():
        raise MetaSoundOperationError("author must be a non-empty string")
    if not isinstance(is_one_shot, bool):
        raise MetaSoundOperationError("is_one_shot must be a boolean")
    unreal = _import_unreal()
    version = _engine_version(unreal)
    builder_subsystem, editor_subsystem = _get_subsystems(unreal)
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        raise MetaSoundOperationError(f"Asset already exists: {asset_path}")
    format_names = {
        "Mono": "MONO",
        "Stereo": "STEREO",
        "Quad": "QUAD",
        "5.1": "FIVE_DOT_ONE",
        "7.1": "SEVEN_DOT_ONE",
    }
    enum_name = format_names.get(output_format)
    format_type = _required_type(unreal, "MetaSoundOutputAudioFormat")
    format_value = getattr(format_type, enum_name, None) if enum_name else None
    if format_value is None:
        raise MetaSoundOperationError("output_format must be one of Mono, Stereo, Quad, 5.1, or 7.1")
    builder_name = f"DccMcp_{asset_name}_{uuid.uuid4().hex[:10]}"
    builder = None
    primary_error: BaseException | None = None
    try:
        (
            builder,
            on_play_output,
            on_finished_input,
            audio_output_inputs,
        ) = _expect_tuple_result(
            unreal,
            builder_subsystem.create_source_builder(
                builder_name,
                format_value,
                is_one_shot,
            ),
            "CreateSourceBuilder",
            4,
        )
        if builder is None:
            raise MetaSoundOperationError("CreateSourceBuilder returned no builder")
        on_play_output_token = _serialize_handle(on_play_output, "On Play output")
        on_finished_input_token = _serialize_handle(on_finished_input, "On Finished input")
        audio_output_input_tokens = [_serialize_handle(handle, "audio output input") for handle in audio_output_inputs]
        (built_asset,) = _expect_tuple_result(
            unreal,
            editor_subsystem.build_to_asset(
                builder,
                author.strip(),
                asset_name,
                package_path,
            ),
            "BuildToAsset",
            1,
        )
        if built_asset is None:
            raise MetaSoundOperationError("BuildToAsset returned no asset")
        context = MetaSoundContext(
            unreal=unreal,
            asset=built_asset,
            builder=builder,
            editor_subsystem=editor_subsystem,
            builder_subsystem=builder_subsystem,
        )
        try:
            _save_asset(context, asset_path)
        except Exception:
            try:
                deleted = unreal.EditorAssetLibrary.delete_asset(asset_path)
                if deleted is not True:
                    raise MetaSoundOperationError("Unreal did not confirm deletion of the unsaved MetaSound asset")
            except Exception as rollback_error:
                raise MetaSoundOperationError(
                    "CreateSource could not be saved and rollback failed; the asset may still exist"
                ) from rollback_error
            raise
        result = {
            "asset_path": asset_path,
            "author": author.strip(),
            "output_format": output_format,
            "is_one_shot": is_one_shot,
            "on_play_output_handle": on_play_output_token,
            "on_finished_input_handle": on_finished_input_token,
            "audio_output_input_handles": audio_output_input_tokens,
            "engine_version": version,
        }
        return result
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if builder is not None:
            try:
                # UE 5.8 creates transient builders in FDocumentBuilderRegistry,
                # while this compatibility API removes only legacy NamedBuilders
                # entries and therefore returns False. Calling it still releases
                # an entry on older supported engine versions where one exists.
                builder_subsystem.unregister_source_builder(builder_name)
            except Exception as cleanup_error:
                if primary_error is None:
                    raise MetaSoundOperationError(
                        f"Failed to unregister source builder {builder_name!r}"
                    ) from cleanup_error
                _LOGGER.error(
                    "Failed to unregister source builder %s while handling another MetaSound error",
                    builder_name,
                    exc_info=cleanup_error,
                )


def add_graph_input(
    asset_path: str,
    input_name: str,
    value_type: str,
    default_value: Any,
) -> Dict[str, Any]:
    """Add a typed graph input and return its official output handle."""
    if not isinstance(input_name, str) or not input_name.strip():
        raise MetaSoundOperationError("input_name must be a non-empty string")
    context = load_context(asset_path)
    (existing,) = _expect_tuple_result(
        context.unreal,
        context.builder.get_graph_input_names(),
        "GetGraphInputNames",
        1,
    )
    if input_name in {str(name) for name in existing}:
        raise MetaSoundOperationError(f"MetaSound input already exists: {input_name}")
    literal, data_type = _literal(context, value_type, default_value)
    (output_handle,) = _expect_tuple_result(
        context.unreal,
        context.builder.add_graph_input_node(
            input_name,
            data_type,
            literal,
            False,
        ),
        "AddGraphInputNode",
        1,
    )
    try:
        output_handle_token = _serialize_handle(output_handle, "graph input output")
        _save_asset(context, asset_path)
    except Exception:
        _rollback_mutation(
            context,
            "AddGraphInput",
            lambda: context.builder.remove_graph_input(input_name),
        )
        raise
    return {
        "asset_path": asset_path,
        "input_name": input_name,
        "value_type": value_type,
        "data_type": data_type,
        "output_handle": output_handle_token,
    }


def add_node(
    asset_path: str,
    namespace: str,
    class_name: str,
    variant: str,
    major_version: int,
    position_x: float,
    position_y: float,
) -> Dict[str, Any]:
    """Add an exact registered MetaSound node class."""
    for field_name, value in (("namespace", namespace), ("class_name", class_name)):
        if not isinstance(value, str) or not value.strip():
            raise MetaSoundOperationError(f"{field_name} must be a non-empty string")
    if not isinstance(variant, str):
        raise MetaSoundOperationError("variant must be a string")
    if isinstance(major_version, bool) or not isinstance(major_version, int) or major_version < 1:
        raise MetaSoundOperationError("major_version must be an integer greater than zero")
    normalized_x = _finite_number(position_x, "position_x")
    normalized_y = _finite_number(position_y, "position_y")
    context = load_context(asset_path)
    class_name_type = _required_type(context.unreal, "MetasoundFrontendClassName")
    exact_class = class_name_type(
        namespace=namespace.strip(),
        name=class_name.strip(),
        variant=variant.strip(),
    )
    (node,) = _expect_tuple_result(
        context.unreal,
        context.builder.add_node_by_class_name(exact_class, major_version),
        "AddNodeByClassName",
        1,
    )
    try:
        _expect_status(
            context.unreal,
            context.editor_subsystem.set_node_location(
                context.builder,
                node,
                context.unreal.Vector2D(normalized_x, normalized_y),
            ),
            "SetNodeLocation",
        )
        inputs, outputs = _node_pins(context, node)
        node_handle_token = _serialize_handle(node, "node")
        _save_asset(context, asset_path)
    except Exception:
        _rollback_mutation(
            context,
            "AddNode",
            lambda: context.builder.remove_node(node),
        )
        raise
    return {
        "asset_path": asset_path,
        "node_handle": node_handle_token,
        "node_class": {
            "namespace": namespace.strip(),
            "name": class_name.strip(),
            "variant": variant.strip(),
            "major_version": major_version,
        },
        "position": {"x": normalized_x, "y": normalized_y},
        "inputs": inputs,
        "outputs": outputs,
    }


def connect_handles(
    asset_path: str,
    output_handle_token: str,
    input_handle_token: str,
) -> Dict[str, Any]:
    """Connect two exact Builder vertex handles."""
    context = load_context(asset_path)
    output_handle = _output_handle(context.unreal, output_handle_token)
    input_handle = _input_handle(context.unreal, input_handle_token)
    if not context.builder.contains_node_output(output_handle):
        raise MetaSoundOperationError("output_handle does not belong to this MetaSound graph")
    if not context.builder.contains_node_input(input_handle):
        raise MetaSoundOperationError("input_handle does not belong to this MetaSound graph")
    if context.builder.nodes_are_connected(output_handle, input_handle):
        return {
            "asset_path": asset_path,
            "output_handle": output_handle_token,
            "input_handle": input_handle_token,
            "changed": False,
        }
    _expect_status(
        context.unreal,
        context.builder.connect_nodes(output_handle, input_handle),
        "ConnectNodes",
    )
    try:
        _save_asset(context, asset_path)
    except Exception:
        _rollback_mutation(
            context,
            "ConnectNodes",
            lambda: context.builder.disconnect_nodes(output_handle, input_handle),
        )
        raise
    return {
        "asset_path": asset_path,
        "output_handle": output_handle_token,
        "input_handle": input_handle_token,
        "changed": True,
    }


def set_graph_input_default(
    asset_path: str,
    input_name: str,
    value: Any,
) -> Dict[str, Any]:
    """Set a graph input default using the input's declared data type."""
    if not isinstance(input_name, str) or not input_name.strip():
        raise MetaSoundOperationError("input_name must be a non-empty string")
    context = load_context(asset_path)
    _, data_type, _ = _expect_tuple_result(
        context.unreal,
        context.builder.find_graph_input_node(input_name),
        "FindGraphInputNode",
        3,
    )
    declared = str(data_type)
    type_map = {
        "Bool": "Bool",
        "Float": "Float",
        "Int32": "Int32",
        "String": "String",
    }
    value_type = type_map.get(declared)
    if value_type is None:
        raise MetaSoundOperationError(f"Setting defaults for MetaSound data type {declared!r} is not supported")
    literal, created_data_type = _literal(context, value_type, value)
    if created_data_type != declared:
        raise MetaSoundOperationError(f"Literal type {created_data_type!r} does not match input type {declared!r}")
    (previous_literal,) = _expect_tuple_result(
        context.unreal,
        context.builder.get_graph_input_default(input_name),
        "GetGraphInputDefault",
        1,
    )
    _expect_status(
        context.unreal,
        context.builder.set_graph_input_default(input_name, literal),
        "SetGraphInputDefault",
    )
    try:
        _save_asset(context, asset_path)
    except Exception:
        _rollback_mutation(
            context,
            "SetGraphInputDefault",
            lambda: context.builder.set_graph_input_default(input_name, previous_literal),
        )
        raise
    return {
        "asset_path": asset_path,
        "input_name": input_name,
        "data_type": declared,
        "value": value,
    }


def inspect_node(asset_path: str, node_handle_token: str) -> Dict[str, Any]:
    """Inspect one exact MetaSound node through public Builder methods."""
    context = load_context(asset_path)
    node = _node_handle(context.unreal, node_handle_token)
    if not context.builder.contains_node(node):
        raise MetaSoundOperationError("node_handle does not belong to this MetaSound graph")
    (version,) = _expect_tuple_result(
        context.unreal,
        context.builder.find_node_class_version(node),
        "FindNodeClassVersion",
        1,
    )
    inputs, outputs = _node_pins(context, node)
    return {
        "asset_path": asset_path,
        "node_handle": node_handle_token,
        "class_version": str(version.export_text()),
        "inputs": inputs,
        "outputs": outputs,
    }


def _interface_names(context: MetaSoundContext) -> Tuple[List[str], List[str]]:
    (inputs,) = _expect_tuple_result(
        context.unreal,
        context.builder.get_graph_input_names(),
        "GetGraphInputNames",
        1,
    )
    (outputs,) = _expect_tuple_result(
        context.unreal,
        context.builder.get_graph_output_names(),
        "GetGraphOutputNames",
        1,
    )
    return [str(value) for value in inputs], [str(value) for value in outputs]


def validate_graph(asset_path: str) -> Dict[str, Any]:
    """Run Unreal's registered asset validators and fail closed if none run."""
    context = load_context(asset_path)
    validator_type = _required_type(context.unreal, "EditorValidatorSubsystem")
    validator = context.unreal.get_editor_subsystem(validator_type)
    if validator is None:
        raise MetaSoundOperationError("EditorValidatorSubsystem is unavailable; enable the Data Validation plugin")
    usecase_type = _required_type(context.unreal, "DataValidationUsecase")
    usecase = getattr(usecase_type, "SCRIPT", None)
    if usecase is None:
        raise MetaSoundOperationError("DataValidationUsecase.SCRIPT is unavailable")
    returned = validator.is_object_valid(context.asset, usecase)
    if not isinstance(returned, tuple) or len(returned) != 3:
        raise MetaSoundOperationError("IsObjectValid returned an unexpected result shape")
    validation_result, errors, warnings = returned
    result_type = _required_type(context.unreal, "DataValidationResult")
    known_results = {
        "VALID": getattr(result_type, "VALID", None),
        "INVALID": getattr(result_type, "INVALID", None),
        "NOT_VALIDATED": getattr(result_type, "NOT_VALIDATED", None),
    }
    result_name = next(
        (
            name
            for name, enum_value in known_results.items()
            if enum_value is not None and validation_result == enum_value
        ),
        None,
    )
    if result_name is None:
        raise MetaSoundOperationError(f"IsObjectValid returned an unknown validation result: {validation_result!r}")
    error_strings = [str(value) for value in errors]
    warning_strings = [str(value) for value in warnings]
    inputs, outputs = _interface_names(context)
    if result_name == "NOT_VALIDATED":
        raise MetaSoundOperationError("Unreal did not run any validator for this MetaSound; validation is inconclusive")
    return {
        "asset_path": asset_path,
        "valid": result_name == "VALID",
        "validation_result": result_name,
        "errors": error_strings,
        "warnings": warning_strings,
        "graph_inputs": inputs,
        "graph_outputs": outputs,
    }


def build_graph(asset_path: str) -> Dict[str, Any]:
    """Overwrite, validate, and save a MetaSound asset with its current builder."""
    context = load_context(asset_path)
    context.builder.build_and_overwrite_meta_sound(context.asset, False)
    _save_asset(context, asset_path)
    validation = validate_graph(asset_path)
    if not validation["valid"]:
        details = "; ".join(validation["errors"]) or validation["validation_result"]
        raise MetaSoundOperationError(f"MetaSound validation failed after build: {details}")
    return validation
