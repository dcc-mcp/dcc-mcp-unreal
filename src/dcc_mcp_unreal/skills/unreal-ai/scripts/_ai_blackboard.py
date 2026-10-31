"""Runtime-gated AI Blackboard authoring core for the ``unreal-ai`` skill.

Design
------
This module is intentionally free of any ``unreal`` import at module scope.
The caller injects the ``unreal`` module (or a behavioral double) into every
public function, which keeps the logic verifiable with bounded contract tests
without a live Unreal Editor.  Nothing here assumes that a given engine version
exposes a particular editor API: every method, class and reflected property is
resolved at call time and gated, and a missing surface fails closed with a typed
:class:`AiBlackboardError` carrying a machine-readable ``reason`` and a
``next_action``.  This mirrors the runtime-gating philosophy of
``dcc_mcp_unreal.pcg_graph`` and follows the same preflight-contract style as
``dcc_mcp_unreal.plugin_preflight`` (it calls the shared
``get_enabled_plugin_names`` native bridge directly rather than importing that
module).

The slice deliberately targets AI *Blackboard data*, the smallest high-value AI
authoring primitive.  Behaviour-tree graph node editing, StateTree states and
EQS query authoring are not Python-exposed in many engine versions; they belong
in a follow-up slice backed by the plugin's C++ ``DccMcpAutomationLibrary``
typed native bridge and are documented as a real gap in
``docs/unreal-ai-capability-matrix.md``.  No claim is made that this module
qualifies those capabilities on a live host.

Real host acceptance (a commandlet probe that drives the real editor) is a
separate gate; see ``tests/ue_ai_blackboard_commandlet.py``.  The readback here
is reflected editor state, not proof of disk persistence across an editor
restart, and no automatic generation or save-on-reopen is implied.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Bounded limits and validation patterns
# ---------------------------------------------------------------------------

_MIN_ENGINE = (5, 0)
_MAX_KEYS = 128
_MAX_NAME = 96
_PATH = re.compile(r"/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\Z")
_KEY_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,95}\Z")

# Public key_type tokens mapped to the Unreal BlackboardKeyType class name.
# Only the requested type is gated at action time; requiring every class up
# front would reject hosts that expose a legitimate subset.
_KEY_TYPES: Dict[str, str] = {
    "bool": "BlackboardKeyType_Bool",
    "int": "BlackboardKeyType_Int",
    "float": "BlackboardKeyType_Float",
    "string": "BlackboardKeyType_String",
    "name": "BlackboardKeyType_Name",
    "vector": "BlackboardKeyType_Vector",
    "rotator": "BlackboardKeyType_Rotator",
    "object": "BlackboardKeyType_Object",
    "class": "BlackboardKeyType_Class",
}

# UE 5.5/5.8 do not expose ``BlackboardKeyType_*`` as ``unreal.`` attributes;
# the UCLASSes live in the AIModule script package and are resolved through
# ``unreal.load_class``.  See ``_load_key_type_class``.
_AIMODULE_SCRIPT = "/Script/AIModule."

# Python-exposed API symbols required for any editor mutation.  Each is gated
# in :func:`preflight`; a missing one yields a deterministic next_action.
_REQUIRED_APIS: Tuple[str, ...] = (
    "BlackboardData",
    "BlackboardDataFactory",
    "BlackboardEntry",
    "ScopedEditorTransaction",
    "SystemLibrary",
    "EditorAssetLibrary",
    "AssetToolsHelpers",
)

# Methods that must be callable on the corresponding API object.  Checking the
# symbol alone can report ready=True on a host whose EditorAssetLibrary is a
# stub without the methods the write path needs, so preflight gates these too.
_REQUIRED_API_METHODS: Dict[str, Tuple[str, ...]] = {
    "SystemLibrary": ("get_engine_version",),
    "EditorAssetLibrary": ("does_asset_exist", "load_asset", "save_loaded_asset"),
    "AssetToolsHelpers": ("get_asset_tools",),
}

# Engine-provided callables the write path needs in addition to the class
# symbols above.  ``unreal.new_object`` outers the key-type subobject to the
# asset (H2); gating only its presence is not enough, it must be callable.
_REQUIRED_ENGINE_CALLABLES: Tuple[str, ...] = ("new_object",)


class AiBlackboardError(RuntimeError):
    """A rejected operation or a failure with explicit recovery evidence."""

    def __init__(self, message: str, *, reason: str, **context: Any) -> None:
        super().__init__(message)
        self.reason = reason
        self.context: Dict[str, Any] = dict(context)
        self.context["reason"] = reason


# ---------------------------------------------------------------------------
# Runtime gating helpers
# ---------------------------------------------------------------------------


def _host_api_next_action(api: str) -> Dict[str, Any]:
    """Return one deterministic recovery step for a missing host-surface API.

    The symbols gated here (``unreal.new_object``, ``load_class``, the reflected
    editor classes/methods and the ``BlackboardKeyType_*`` UCLASSes) are exposed
    by the Unreal engine's Python layer, not by the DCC-MCP adapter plugin: the
    adapter only adds its C++ ``DccMcpAutomationLibrary`` functions.  Updating
    the adapter cannot add ``unreal.new_object``, so recommending
    ``update_adapter_plugin`` here would be a dead end that retries into the same
    failure.  ``api`` names the exact engine symbol the host must expose.  The
    ``update_adapter_plugin`` recovery is still emitted by :func:`preflight` as
    its coarse host-not-ready action (and for the adapter's plugin-enumeration
    bridge), where an adapter/plugin update genuinely can help.
    """
    return {
        "action": "enable_engine_python_api",
        "api": api,
        "retry_tool": "unreal_ai__ai_capability_preflight",
    }


def _unsupported_api(api: str, message: str) -> AiBlackboardError:
    """Build a typed host-surface failure carrying one ``next_action``.

    SKILL.md promises that every ``unsupported_api`` failure exposes a typed
    reason and one recovery action. Keep that contract in one place so no
    gating helper can silently omit it.
    """
    return AiBlackboardError(
        message,
        reason="unsupported_api",
        api=api,
        next_action=_host_api_next_action(api),
    )


def _method(owner: Any, name: str) -> Any:
    method = getattr(owner, name, None)
    if not callable(method):
        raise _unsupported_api(name, "Required API {!r} is unavailable on this host".format(name))
    return method


def _symbol(unreal: Any, name: str) -> Any:
    symbol = getattr(unreal, name, None)
    if symbol is None:
        raise _unsupported_api(name, "Required Unreal symbol {!r} is unavailable on this host".format(name))
    return symbol


def _load_key_type_class(unreal: Any, key_cls_name: str) -> Any:
    """Resolve a BlackboardKeyType_* UCLASS on this host (H1).

    On UE 5.5/5.8 these classes are not exposed as ``unreal.<Name>``
    attributes; they are reachable through
    ``unreal.load_class(None, "/Script/AIModule.<Name>")`` (verified on real
    hosts).  Prefer that path, and fall back to a direct attribute for hosts
    / doubles that do expose the symbol.  Raises ``AiBlackboardError`` with
    ``unsupported_api`` when neither path yields the class.
    """
    load_class = getattr(unreal, "load_class", None)
    if callable(load_class):
        try:
            loaded = load_class(None, _AIMODULE_SCRIPT + key_cls_name)
        except Exception:  # noqa: BLE001 - fall through to the attribute path
            loaded = None
        if loaded is not None:
            return loaded
    direct = getattr(unreal, key_cls_name, None)
    if direct is not None:
        return direct
    raise _unsupported_api(
        key_cls_name,
        "Required key type class {!r} is unavailable on this host".format(key_cls_name),
    )


def _new_key_type(unreal: Any, key_cls: Any, asset: Any) -> Any:
    """Construct a key type subobject outered to *asset* (H2 persistence).

    A key type built with a transient outer survives the in-session readback
    but is not serialized with the Blackboard asset, so the key type reads
    back empty after a save/reopen.  Passing *asset* as the outer to
    ``unreal.new_object`` makes it a persistent subobject (verified on UE
    5.5/5.8).  There is deliberately no ``key_cls()`` fallback: a host that
    cannot provide ``new_object`` (or returns no instance) must fail closed
    instead of reporting a saved key whose type is silently lost on reopen.
    """
    new_object = getattr(unreal, "new_object", None)
    if not callable(new_object):
        raise _unsupported_api(
            "new_object",
            "unreal.new_object is required to outer the key type to the Blackboard asset",
        )
    instance = new_object(key_cls, asset)
    if instance is None:
        raise AiBlackboardError(
            "unreal.new_object returned no BlackboardKeyType instance",
            reason="key_type_construction_unavailable",
            next_action=_host_api_next_action("new_object"),
        )
    return instance


def _key_type_resolvable(unreal: Any, key_cls_name: str) -> bool:
    """Return whether *key_cls_name* can be obtained on this host (no raise)."""
    load_class = getattr(unreal, "load_class", None)
    if callable(load_class):
        try:
            if load_class(None, _AIMODULE_SCRIPT + key_cls_name) is not None:
                return True
        except Exception:  # noqa: BLE001 - fall through to the attribute path
            pass
    return getattr(unreal, key_cls_name, None) is not None


def _engine_version(unreal: Any) -> Tuple[str, Optional[Tuple[int, int]]]:
    """Return ``(raw_string, (major, minor) | None)`` via SystemLibrary."""
    system = getattr(unreal, "SystemLibrary", None)
    getter = getattr(system, "get_engine_version", None)
    if not callable(getter):
        return "", None
    raw = str(getter())
    match = re.match(r"\s*(\d+)\.(\d+)", raw)
    if not match:
        return raw, None
    return raw, (int(match.group(1)), int(match.group(2)))


def _enabled_plugins(unreal: Any) -> Optional[List[str]]:
    """List enabled plugins through the adapter's C++ native bridge.

    Reuses ``DccMcpAutomationLibrary.get_enabled_plugin_names`` (the plugin's
    existing typed native bridge) and falls back to ``PluginBlueprintLibrary``
    where available.  Returns ``None`` when no plugin enumeration surface is
    present, so the caller can fail closed.
    """
    library = getattr(unreal, "DccMcpAutomationLibrary", None)
    getter = getattr(library, "get_enabled_plugin_names", None)
    if not callable(getter):
        library = getattr(unreal, "PluginBlueprintLibrary", None)
        getter = getattr(library, "get_enabled_plugin_names", None)
    if not callable(getter):
        return None
    return sorted({str(name) for name in getter()})


def _validated_path(asset_path: str) -> str:
    if not isinstance(asset_path, str) or len(asset_path) > 240 or not _PATH.fullmatch(asset_path):
        raise AiBlackboardError(
            "Use a /Game/Folder/Asset package path with ASCII letters, digits or underscores",
            reason="invalid_asset_path",
        )
    return asset_path


def _validated_key_name(key_name: str) -> str:
    if not isinstance(key_name, str) or not _KEY_NAME.fullmatch(key_name):
        raise AiBlackboardError(
            "key_name must start with a letter and contain at most 96 letters, digits or underscores",
            reason="invalid_key_name",
        )
    return key_name


# ---------------------------------------------------------------------------
# Preflight (version + plugin + API) — read-only, no editor mutation
# ---------------------------------------------------------------------------


def preflight(unreal: Any, capability: str = "ai_blackboard", key_type: Optional[str] = None) -> Dict[str, Any]:
    """Return typed readiness and one deterministic next action.

    This is the ``search/describe`` preflight for the capability: it gates the
    engine version, the Python-exposed API surface, the enabled-plugin
    enumeration and the resolvability of the requested BlackboardKeyType_*
    class before any authoring action is attempted.  It never mutates.
    """
    if capability != "ai_blackboard":
        raise AiBlackboardError(
            "Unknown Unreal AI capability: {}".format(capability),
            reason="unknown_capability",
            capability=capability,
        )

    raw_version, parsed_version = _engine_version(unreal)
    version_supported = parsed_version is not None and parsed_version >= _MIN_ENGINE

    available_apis: List[str] = []
    missing_apis: List[str] = []
    missing_methods: List[str] = []
    for name in _REQUIRED_APIS:
        symbol = getattr(unreal, name, None)
        if symbol is None:
            missing_apis.append(name)
            continue
        required_methods = _REQUIRED_API_METHODS.get(name, ())
        absent = [method for method in required_methods if not callable(getattr(symbol, method, None))]
        if absent:
            missing_methods.extend("{}.{}".format(name, method) for method in absent)
            missing_apis.append(name)
        else:
            available_apis.append(name)

    # Engine-provided callables the write path invokes directly (currently
    # ``unreal.new_object`` for the H2 persistent outer) are core Unreal Python
    # APIs: no adapter plugin can add them, and authoring fails closed without
    # them. Gate callability (not mere presence) so preflight never reports
    # ready=True on a host that would reject at key-type construction time.
    missing_engine_callables = [
        name for name in _REQUIRED_ENGINE_CALLABLES if not callable(getattr(unreal, name, None))
    ]

    # H3: gate the key-type resolution path authoring actually uses.  A host
    # that cannot resolve any BlackboardKeyType_* UCLASS (neither via
    # ``load_class`` from /Script/AIModule nor as a direct attribute) can never
    # author a typed key, so preflight must not report ready=true on it.  Check
    # the requested type when given, otherwise the default "float" type.
    requested_cls = _KEY_TYPES.get(key_type, _KEY_TYPES["float"]) if key_type else _KEY_TYPES["float"]
    key_type_classes = [requested_cls]
    available_key_types = [name for name in key_type_classes if _key_type_resolvable(unreal, name)]
    missing_key_types = [name for name in key_type_classes if name not in available_key_types]
    key_type_available = not missing_key_types

    # AI Blackboard data lives in the always-on AIModule, so no optional plugin
    # is required for this slice.  We still enumerate plugins as preflight
    # evidence and to gate the typed native bridge that deeper AI authoring
    # (StateTree/EQS/BT graph) will require.
    required_plugins: List[str] = []
    plugins = _enabled_plugins(unreal)
    plugin_bridge_available = plugins is not None
    enabled_plugins = plugins or []
    missing_plugins = [name for name in required_plugins if name not in enabled_plugins]

    ready = (
        version_supported
        and not missing_apis
        and not missing_methods
        and not missing_engine_callables
        and plugin_bridge_available
        and not missing_plugins
        and key_type_available
    )

    if not version_supported:
        next_action: Dict[str, Any] = {
            "action": "unsupported_engine_version",
            "requires": ">={}.{}".format(*_MIN_ENGINE),
            "observed": raw_version or "unknown",
            "retry_tool": "unreal_ai__ai_capability_preflight",
        }
    elif missing_engine_callables:
        # Core engine Python callables are not supplied by the adapter plugin;
        # name them so the host enables its Python API rather than retrying an
        # adapter update that cannot add unreal.new_object.
        next_action = {
            "action": "enable_engine_python_api",
            "missing_engine_callables": missing_engine_callables,
            "retry_tool": "unreal_ai__ai_capability_preflight",
        }
    elif missing_apis or missing_methods or missing_key_types or not plugin_bridge_available:
        next_action = {
            "action": "update_adapter_plugin",
            "missing_apis": missing_apis,
            "missing_methods": missing_methods,
            "missing_key_types": missing_key_types,
            "plugin_bridge_available": plugin_bridge_available,
            "retry_tool": "unreal_ai__ai_capability_preflight",
        }
    else:
        next_action = {"action": "proceed", "capability": capability}

    return {
        "capability": capability,
        "engine_version": raw_version or "unknown",
        "min_engine_version": "{}.{}".format(*_MIN_ENGINE),
        "version_supported": version_supported,
        "required_apis": list(_REQUIRED_APIS),
        "available_apis": available_apis,
        "missing_apis": missing_apis,
        "missing_methods": missing_methods,
        "required_engine_callables": list(_REQUIRED_ENGINE_CALLABLES),
        "missing_engine_callables": missing_engine_callables,
        "checked_key_types": key_type_classes,
        "available_key_types": available_key_types,
        "missing_key_types": missing_key_types,
        "key_type_available": key_type_available,
        "required_plugins": required_plugins,
        "enabled_plugins": enabled_plugins,
        "missing_plugins": missing_plugins,
        "plugin_bridge_available": plugin_bridge_available,
        "ready": ready,
        "next_action": next_action,
    }


# ---------------------------------------------------------------------------
# Reflection helpers (bounded real readback)
# ---------------------------------------------------------------------------


def _asset_class(asset: Any) -> str:
    get_class = _method(asset, "get_class")
    cls = get_class()
    get_name = getattr(cls, "get_name", None) or getattr(cls, "get_path_name", None)
    return str(get_name()) if callable(get_name) else str(getattr(cls, "__name__", ""))


def _is_blackboard_data(unreal: Any, asset: Any, cls_name: str) -> bool:
    """Return True only when *asset* is a BlackboardData (or a subclass).

    Prefer the engine's real type relationship (``isinstance`` / ``is_child_of``)
    and fall back to an exact reflected class-name match for hosts/doubles that
    do not expose the type object.  A substring match is deliberately avoided:
    a look-alike name such as ``NotBlackboardDataTable`` must not pass.
    """
    blackboard_data = getattr(unreal, "BlackboardData", None)
    if isinstance(blackboard_data, type):
        try:
            if isinstance(asset, blackboard_data):
                return True
        except TypeError:  # noqa: BLE001 - some reflected types reject isinstance
            pass
    get_class = getattr(asset, "get_class", None)
    cls = get_class() if callable(get_class) else None
    is_child_of = getattr(cls, "is_child_of", None)
    if callable(is_child_of) and blackboard_data is not None:
        try:
            return bool(is_child_of(blackboard_data))
        except Exception:  # noqa: BLE001 - fall through to the exact name check
            pass
    return cls_name == "BlackboardData"


def _field(entry: Any, name: str) -> Any:
    """Read a struct field via get_editor_property then plain attribute."""
    get_property = getattr(entry, "get_editor_property", None)
    if callable(get_property):
        try:
            return get_property(name)
        except Exception:  # noqa: BLE001 - fall back to the plain attribute
            pass
    return getattr(entry, name, None)


def _key_type_name(entry: Any) -> str:
    key_type = _field(entry, "key_type")
    if key_type is None:
        return ""
    get_class = getattr(key_type, "get_class", None)
    if callable(get_class):
        cls = get_class()
        get_name = getattr(cls, "get_name", None)
        if callable(get_name):
            return str(get_name())
    return str(getattr(key_type, "__class__", type(key_type)).__name__)


def _read_keys(asset: Any) -> Tuple[List[Any], List[Dict[str, str]]]:
    """Return ``(raw_entries, parsed_keys)`` through a bounded reflected readback."""
    get_property = _method(asset, "get_editor_property")
    try:
        raw = list(get_property("keys") or [])
    except AiBlackboardError:
        raise
    except Exception as exc:  # noqa: BLE001 - reflected property may be absent
        raise AiBlackboardError(
            "Cannot read Blackboard 'keys' property on this host",
            reason="unsupported_property",
            detail=str(exc),
        ) from exc
    if len(raw) > _MAX_KEYS:
        raise AiBlackboardError(
            "Blackboard key count exceeds the {} inspection limit".format(_MAX_KEYS),
            reason="inspection_limit",
            limit=_MAX_KEYS,
        )
    parsed = [{"name": str(_field(entry, "entry_name") or ""), "key_type": _key_type_name(entry)} for entry in raw]
    return raw, parsed


def _load_asset(unreal: Any, asset_path: str) -> Any:
    library = getattr(unreal, "EditorAssetLibrary", None)
    exists = _method(library, "does_asset_exist")
    load = _method(library, "load_asset")
    if not exists(asset_path):
        return None
    asset = load(asset_path)
    if asset is None:
        # The path is occupied but the engine could not load it.  Treating this
        # as "missing" would let the create branch write over an existing asset,
        # violating the "never overwrites an existing asset" contract.
        raise AiBlackboardError(
            "Asset exists but could not be loaded at {}".format(asset_path),
            reason="asset_load_failed",
            asset_path=asset_path,
        )
    return asset


def _create_asset(unreal: Any, asset_path: str) -> Any:
    factory_class = _symbol(unreal, "BlackboardDataFactory")
    asset_class = _symbol(unreal, "BlackboardData")
    helpers = getattr(unreal, "AssetToolsHelpers", None)
    tools = _method(helpers, "get_asset_tools")()
    create = _method(tools, "create_asset")
    package_path, _, asset_name = asset_path.rpartition("/")
    return create(asset_name, package_path, asset_class, factory_class())


def _delete_created_asset(unreal: Any, asset: Any, asset_path: str) -> List[str]:
    """Best-effort removal of an asset this action just created.

    Returns recovery notes (empty on success).  A failed deletion is surfaced
    to the caller so a "rolled_back" result never hides a leftover empty asset.
    """
    library = getattr(unreal, "EditorAssetLibrary", None)
    notes: List[str] = []
    delete_loaded = getattr(library, "delete_loaded_asset", None)
    if callable(delete_loaded):
        try:
            if delete_loaded(asset):
                return []
            notes.append("delete_loaded_asset returned false for {}".format(asset_path))
        except Exception as exc:  # noqa: BLE001 - surface deletion failure
            notes.append("delete_loaded_asset failed: {}".format(exc))
    else:
        notes.append("delete_loaded_asset API unavailable")
    delete_by_path = getattr(library, "delete_asset", None)
    if callable(delete_by_path):
        try:
            if delete_by_path(asset_path):
                return []
            notes.append("delete_asset returned false for {}".format(asset_path))
        except Exception as exc:  # noqa: BLE001 - surface deletion failure
            notes.append("delete_asset failed: {}".format(exc))
    else:
        notes.append("delete_asset API unavailable")
    return notes


def _build_entry(unreal: Any, entry_cls: Any, key_cls: Any, asset: Any, key_name: str) -> Any:
    """Construct a typed Blackboard entry through the reflected Python surface."""
    try:
        entry = entry_cls()
    except Exception as exc:  # noqa: BLE001 - struct construction may be unsupported
        raise AiBlackboardError(
            "BlackboardEntry construction failed on this host",
            reason="entry_construction_unavailable",
            detail=str(exc),
        ) from exc
    try:
        # H2: outering the key type to the Blackboard asset makes it a
        # persistent subobject, so the type survives a save/reopen.
        key_type = _new_key_type(unreal, key_cls, asset)
    except AiBlackboardError:
        # Preserve typed host-surface failures (e.g. unsupported_api with its
        # next_action) instead of flattening them to a construction error.
        raise
    except Exception as exc:  # noqa: BLE001
        raise AiBlackboardError(
            "BlackboardKeyType construction failed on this host",
            reason="key_type_construction_unavailable",
            detail=str(exc),
        ) from exc
    set_property = getattr(entry, "set_editor_property", None)
    if callable(set_property):
        try:
            set_property("entry_name", key_name)
            set_property("key_type", key_type)
            return entry
        except Exception as exc:  # noqa: BLE001
            raise AiBlackboardError(
                "Cannot set reflected BlackboardEntry fields on this host",
                reason="entry_field_unavailable",
                detail=str(exc),
            ) from exc
    try:
        entry.entry_name = key_name
        entry.key_type = key_type
    except Exception as exc:  # noqa: BLE001
        raise AiBlackboardError(
            "Cannot assign BlackboardEntry fields on this host",
            reason="entry_field_unavailable",
            detail=str(exc),
        ) from exc
    return entry


def _begin_transaction(unreal: Any) -> Any:
    txn_cls = _symbol(unreal, "ScopedEditorTransaction")
    txn = txn_cls("DCC MCP Author AI Blackboard Key")
    enter = getattr(txn, "__enter__", None)
    if callable(enter):
        enter()
    return txn


def _finish_transaction(txn: Any, ok: bool) -> List[str]:
    """Close a transaction; cancel it when *ok* is False. Returns recovery notes."""
    notes: List[str] = []
    if not ok:
        cancel = getattr(txn, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception as exc:  # noqa: BLE001
                notes.append("transaction.cancel failed: {}".format(exc))
    exit_ = getattr(txn, "__exit__", None)
    if callable(exit_):
        try:
            exit_(None, None, None)
        except Exception as exc:  # noqa: BLE001
            notes.append("transaction.__exit__ failed: {}".format(exc))
    return notes


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


def inspect_blackboard(unreal: Any, asset_path: str) -> Dict[str, Any]:
    """Read-only bounded readback of a Blackboard asset (never mutates)."""
    path = _validated_path(asset_path)
    asset = _load_asset(unreal, path)
    if asset is None:
        return {
            "exists": False,
            "asset_path": path,
            "asset_class": "",
            "keys": [],
            "key_count": 0,
            "readback_verified": True,
            "read_only": True,
        }
    cls = _asset_class(asset)
    if not _is_blackboard_data(unreal, asset, cls):
        raise AiBlackboardError(
            "Asset is not a BlackboardData",
            reason="wrong_asset_class",
            asset_class=cls,
            asset_path=path,
        )
    _, parsed = _read_keys(asset)
    return {
        "exists": True,
        "asset_path": path,
        "asset_class": cls,
        "keys": parsed,
        "key_count": len(parsed),
        "readback_verified": True,
        "read_only": True,
    }


def author_blackboard_key(
    unreal: Any,
    asset_path: str,
    key_name: str,
    key_type: str = "float",
    create_if_missing: bool = True,
) -> Dict[str, Any]:
    """Author one typed key on a Blackboard asset (minimal action).

    Ensures the asset (creating it only when explicitly allowed and absent),
    appends a single typed key inside a scoped editor transaction, verifies the
    mutation through a reflected readback, and only then saves.  Any failure or
    readback mismatch cancels the transaction, restores the observed key array
    (undo/cancel semantics) and removes an asset this call created, returning a
    typed error with recovery notes.  Existing assets and existing keys are
    never overwritten or duplicated.
    """
    preflight_result = preflight(unreal, key_type=key_type)
    if not preflight_result["ready"]:
        raise AiBlackboardError(
            "AI Blackboard preflight is not ready",
            reason="preflight_not_ready",
            next_action=preflight_result["next_action"],
            engine_version=preflight_result["engine_version"],
            missing_apis=preflight_result["missing_apis"],
            missing_engine_callables=preflight_result["missing_engine_callables"],
            missing_key_types=preflight_result["missing_key_types"],
        )

    path = _validated_path(asset_path)
    name = _validated_key_name(key_name)
    key_cls_name = _KEY_TYPES.get(key_type)
    if key_cls_name is None:
        raise AiBlackboardError(
            "Unsupported key_type",
            reason="unsupported_key_type",
            key_type=key_type,
            allowed=sorted(_KEY_TYPES),
        )

    # H1: BlackboardKeyType_* classes are not ``unreal.`` attributes on UE
    # 5.5/5.8; resolve them through the AIModule script package instead.
    key_cls = _load_key_type_class(unreal, key_cls_name)
    entry_cls = _symbol(unreal, "BlackboardEntry")

    library = getattr(unreal, "EditorAssetLibrary", None)
    save = _method(library, "save_loaded_asset")

    created = False
    asset = _load_asset(unreal, path)
    if asset is None:
        if not create_if_missing:
            raise AiBlackboardError(
                "Blackboard asset does not exist and create_if_missing is False",
                reason="asset_not_found",
                asset_path=path,
            )
        asset = _create_asset(unreal, path)
        created = asset is not None
    if asset is None:
        raise AiBlackboardError(
            "Engine returned no Blackboard asset",
            reason="asset_unavailable",
            asset_path=path,
            created=created,
        )

    # Every failure after a possible creation is funnelled through this guard:
    # it stamps ``created`` into the error context and, when this call created
    # the asset, removes it so a "rolled_back" result never leaves a new empty
    # asset behind.  This also covers pre-transaction rejections (wrong class,
    # duplicate key, unsupported property, limit) that occur after creation.
    txn = None
    get_property: Any = None
    set_property: Any = None
    raw_before: List[Any] = []
    mutation_state = "not_started"
    recovery_errors: List[str] = []
    try:
        cls = _asset_class(asset)
        if not _is_blackboard_data(unreal, asset, cls):
            raise AiBlackboardError(
                "Existing asset is not a BlackboardData; refusing to overwrite",
                reason="wrong_asset_class",
                asset_class=cls,
                asset_path=path,
            )

        raw_before, parsed_before = _read_keys(asset)
        # FName equality is case-insensitive: a different-case variant is the
        # same key and must be rejected, not authored as a duplicate.
        if any(item["name"].lower() == name.lower() for item in parsed_before):
            raise AiBlackboardError(
                "A key with this name already exists; refusing to duplicate",
                reason="duplicate_key",
                key_name=name,
                asset_path=path,
            )
        if len(parsed_before) >= _MAX_KEYS:
            raise AiBlackboardError(
                "Blackboard key count is at the {} limit".format(_MAX_KEYS),
                reason="limit_exceeded",
                limit=_MAX_KEYS,
            )

        get_property = _method(asset, "get_editor_property")
        set_property = _method(asset, "set_editor_property")
        txn = _begin_transaction(unreal)
        try:
            new_entry = _build_entry(unreal, entry_cls, key_cls, asset, name)
            set_property("keys", list(raw_before) + [new_entry])
            mutation_state = "in_transaction"

            # Real result readback BEFORE any save.
            _, parsed_after = _read_keys(asset)
            # The engine can return the authored key under a different case,
            # so match with the same case-insensitive FName rule as above.
            matched = [item for item in parsed_after if item["name"].lower() == name.lower()]
            expected_type = key_cls_name
            if not matched:
                raise AiBlackboardError(
                    "Readback did not observe the authored key",
                    reason="readback_mismatch",
                    expected_key=name,
                    observed=[item["name"] for item in parsed_after],
                )
            observed_type = matched[0]["key_type"]
            # Fail closed: an empty or unreadable observed type must NOT pass
            # the readback gate.  Only the exact type (or a name that contains
            # it, for derived key types) is accepted before saving.
            if observed_type != expected_type and expected_type not in observed_type:
                raise AiBlackboardError(
                    "Readback observed an unexpected key type",
                    reason="readback_type_mismatch",
                    expected=expected_type,
                    observed=observed_type,
                )

            saved = bool(save(asset))
            if not saved:
                raise AiBlackboardError(
                    "Engine refused to save the Blackboard asset",
                    reason="save_failed",
                )
            mutation_state = "committed"
        except AiBlackboardError as exc:
            recovery_errors.extend(_rollback(asset, set_property, get_property, raw_before))
            recovery_errors.extend(_finish_transaction(txn, ok=False))
            exc.context.update(
                mutation_state="rolled_back",
                recovery_errors=recovery_errors,
            )
            raise
        except Exception as exc:  # noqa: BLE001 - convert to a typed result
            recovery_errors.extend(_rollback(asset, set_property, get_property, raw_before))
            recovery_errors.extend(_finish_transaction(txn, ok=False))
            raise AiBlackboardError(
                "AI Blackboard authoring failed; transaction cancelled",
                reason="unexpected_error",
                detail="{}: {}".format(type(exc).__name__, exc)[:500],
                mutation_state="rolled_back",
                recovery_errors=recovery_errors,
            ) from exc
        else:
            recovery_errors.extend(_finish_transaction(txn, ok=True))

        return {
            "asset_path": path,
            "created": created,
            "key_name": name,
            "key_type": key_type,
            "key_type_class": key_cls_name,
            "key_count_before": len(parsed_before),
            "key_count_after": len(parsed_after),
            "saved": True,
            "readback_verified": True,
            "mutation_state": mutation_state,
            "recovery_errors": recovery_errors,
            "generation_verified": False,
            "reopen_verified": False,
        }
    except AiBlackboardError as exc:
        exc.context["created"] = created
        exc.context.setdefault("asset_path", path)
        if created:
            notes = _delete_created_asset(unreal, asset, path)
            if notes:
                exc.context["recovery_errors"] = list(exc.context.get("recovery_errors") or []) + notes
        raise
    except Exception as exc:  # noqa: BLE001 - defensive: never leak an untyped error
        notes = _delete_created_asset(unreal, asset, path) if created else []
        raise AiBlackboardError(
            "AI Blackboard authoring failed; transaction cancelled",
            reason="unexpected_error",
            detail="{}: {}".format(type(exc).__name__, exc)[:500],
            created=created,
            asset_path=path,
            mutation_state="rolled_back" if txn is not None else "not_started",
            recovery_errors=notes,
        ) from exc


def _rollback(asset: Any, set_property: Any, get_property: Any, raw_before: List[Any]) -> List[str]:
    """Best-effort restoration of the observed key array after a failure."""
    try:
        set_property("keys", list(raw_before))
        current = list(get_property("keys") or [])
        if len(current) != len(raw_before):
            return ["restored key count differs from the observed snapshot"]
    except Exception as exc:  # noqa: BLE001
        return ["rollback failed: {}".format(exc)]
    return []


def capability_matrix() -> List[Dict[str, str]]:
    """Return the concise, evidence-based capability matrix (see docs)."""
    return [
        {"capability": "ai_blackboard", "status": "supported", "via": "unreal-ai (this slice)"},
        {"capability": "behavior_tree_graph", "status": "gap", "via": "needs C++ typed native bridge"},
        {"capability": "state_tree", "status": "gap", "via": "needs StateTree plugin + C++ bridge"},
        {"capability": "eqs", "status": "gap", "via": "needs C++ typed native bridge"},
        {"capability": "ai_perception", "status": "partial", "via": "actor/component tools, no AI editor facade"},
        {"capability": "gameplay_tags", "status": "partial", "via": "config editing, no tag registry tool"},
    ]
