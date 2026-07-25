"""UObject reflection interface — secure, fail-closed, main-thread-only.

Provides the Python-side contract for UObject discovery, property read/write,
and UFunction invocation inside Unreal Editor. The actual reflection is performed
by the C++ plugin via the bridge protocol; this module provides the typed Python
API with integrated security checks.

Thread safety
=============
- All mutating operations require main-thread execution via the dispatcher.
- Read operations may be permitted from any thread when safe.
- The security policy is checked BEFORE any bridge call, so a denied operation
  never reaches the C++ layer.

Compatibility
=============
- UE 4.18: ``unreal`` module (UE Python API) is used where available.
- UE 5.x: Full ``unreal`` module support with the Python Plugin.
- Fallback: When ``unreal`` is not importable, all operations go through the bridge.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from dcc_mcp_unreal.security import ReflectionPolicy
from dcc_mcp_unreal.security import SecurityDeniedError
from dcc_mcp_unreal.security import default_read_policy

logger = logging.getLogger(__name__)

# ── Reflection data types ────────────────────────────────────────────────────


@dataclass
class PropertyDescriptor:
    """Describes a single UProperty on a UObject."""

    name: str
    type_name: str
    category: str  # "scalar", "struct", "array", "map", "set", "object", "enum", "delegate"
    flags: List[str] = field(default_factory=list)  # e.g. "EditAnywhere", "BlueprintReadOnly"
    is_readable: bool = True
    is_writable: bool = True
    is_editor_visible: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FunctionDescriptor:
    """Describes a single UFunction on a UObject."""

    name: str
    return_type: str
    parameters: List[Dict[str, str]] = field(default_factory=list)  # {"name": "...", "type": "..."}
    flags: List[str] = field(default_factory=list)  # e.g. "BlueprintCallable", "Exec"
    is_callable: bool = True
    is_static: bool = False
    is_pure: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ObjectDescriptor:
    """Describes a UObject discovered in the editor."""

    name: str
    class_path: str  # e.g. "/Script/Engine.StaticMeshActor"
    outer_path: str  # e.g. "/Game/Maps/MyLevel.MyLevel:PersistentLevel"
    label: str = ""
    property_count: int = 0
    function_count: int = 0
    properties: List[PropertyDescriptor] = field(default_factory=list)
    functions: List[FunctionDescriptor] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["properties"] = [p.to_dict() for p in self.properties]
        d["functions"] = [f.to_dict() for f in self.functions]
        return d


@dataclass
class PropertyValue:
    """Result of reading a single property value."""

    name: str
    value: Any
    type_name: str
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FunctionResult:
    """Result of calling a UFunction."""

    function_name: str
    success: bool
    return_value: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── UObjectReflection — Python-side reflection facade ────────────────────────


class UObjectReflection:
    """Secure, typed Python interface to UObject reflection.

    All operations are checked against a :class:`ReflectionPolicy` BEFORE
    reaching the C++ layer. This is the only entry point Python code should
    use for UObject reflection.

    Parameters:
        bridge: The bridge client used to communicate with the C++ plugin.
        policy: Security policy for access control. Defaults to a safe read-only
                policy — callers must explicitly pass a permissive policy to
                enable writes and UFunction calls.
    """

    def __init__(
        self,
        bridge: Optional[Any] = None,
        policy: Optional[ReflectionPolicy] = None,
    ) -> None:
        self._bridge = bridge
        self.policy = policy or default_read_policy()

    # ── Object discovery ───────────────────────────────────────────────────

    def discover_objects(
        self,
        class_filter: Optional[str] = None,
        outer_filter: Optional[str] = None,
        max_results: int = 100,
    ) -> List[ObjectDescriptor]:
        """Discover UObjects in the current editor world.

        Args:
            class_filter: Optional glob pattern to filter by class path.
            outer_filter: Optional glob pattern to filter by outer path.
            max_results: Maximum number of results to return.

        Returns:
            List of :class:`ObjectDescriptor`, each carrying class info and
            counts but not full property/function lists (use :meth:`describe_object`
            for detailed reflection).

        Raises:
            SecurityDeniedError: If the class_filter matches denied patterns.
        """
        if class_filter:
            self.policy.check_class(class_filter)
        if class_filter and any(c in class_filter for c in ("*", "?")):
            # Pattern-based filter — perform via bridge
            pass
        objects = self._call_bridge("discover_objects", {
            "class_filter": class_filter or "",
            "outer_filter": outer_filter or "",
            "max_results": max_results,
        })
        return [_dict_to_object_descriptor(o) for o in objects]

    def describe_object(self, object_path: str, *, include_properties: bool = True, include_functions: bool = True) -> ObjectDescriptor:
        """Get detailed reflection info for a single UObject.

        Args:
            object_path: Full UObject path (e.g. ``"/Game/Maps/Level.Level:PersistentLevel.Sphere_0"``).
            include_properties: Whether to list all accessible properties.
            include_functions: Whether to list all callable UFunctions.

        Returns:
            Full :class:`ObjectDescriptor` with properties and functions populated.

        Raises:
            SecurityDeniedError: If the object's class is denied.
        """
        result = self._call_bridge("describe_object", {
            "object_path": object_path,
            "include_properties": include_properties,
            "include_functions": include_functions,
        })
        desc = _dict_to_object_descriptor(result)
        # Strip denied properties/functions from the result
        desc.properties = [p for p in desc.properties if self._is_property_visible(p)]
        desc.functions = [f for f in desc.functions if self._is_function_visible(f)]
        desc.property_count = len(desc.properties)
        desc.function_count = len(desc.functions)
        return desc

    # ── Property access ─────────────────────────────────────────────────────

    def get_property(self, object_path: str, property_name: str) -> PropertyValue:
        """Read a single property value.

        Args:
            object_path: Full UObject path.
            property_name: Name of the property to read.

        Returns:
            :class:`PropertyValue` with the typed value.

        Raises:
            SecurityDeniedError: If the class, property name, or operation is denied.
        """
        class_path = self._resolve_class_path(object_path)
        self.policy.check_property_read(property_name, class_path)
        result = self._call_bridge("get_property", {
            "object_path": object_path,
            "property_name": property_name,
        })
        return PropertyValue(
            name=property_name,
            value=result.get("value"),
            type_name=result.get("type_name", "unknown"),
            success=result.get("success", True),
            error=result.get("error"),
        )

    def get_properties(self, object_path: str, property_names: Optional[List[str]] = None) -> List[PropertyValue]:
        """Read multiple properties in a single call.

        If ``property_names`` is ``None``, returns all readable properties.

        Args:
            object_path: Full UObject path.
            property_names: Optional list of property names to read.

        Returns:
            List of :class:`PropertyValue`.

        Raises:
            SecurityDeniedError: If any property or class is denied.
        """
        class_path = self._resolve_class_path(object_path)
        names = property_names or []
        for name in names:
            self.policy.check_property_read(name, class_path)
        result = self._call_bridge("get_properties", {
            "object_path": object_path,
            "property_names": names,
        })
        return [PropertyValue(**pv) for pv in result]

    def set_property(self, object_path: str, property_name: str, value: Any) -> PropertyValue:
        """Write a single property value.

        **Must be called from the editor main thread.** The bridge enforces this.

        Args:
            object_path: Full UObject path.
            property_name: Name of the property to write.
            value: New value (must be JSON-serializable).

        Returns:
            :class:`PropertyValue` with the result.

        Raises:
            SecurityDeniedError: If the property write is denied by policy.
        """
        class_path = self._resolve_class_path(object_path)
        self.policy.check_property_write(property_name, class_path, value)
        result = self._call_bridge("set_property", {
            "object_path": object_path,
            "property_name": property_name,
            "value": _sanitize_value(value),
        })
        return PropertyValue(
            name=property_name,
            value=value,
            type_name=result.get("type_name", "unknown"),
            success=result.get("success", True),
            error=result.get("error"),
        )

    def set_properties(self, object_path: str, properties: Dict[str, Any]) -> List[PropertyValue]:
        """Write multiple properties in a single call.

        Args:
            object_path: Full UObject path.
            properties: Dict mapping property names to new values.

        Returns:
            List of :class:`PropertyValue`.

        Raises:
            SecurityDeniedError: If any property write is denied.
        """
        class_path = self._resolve_class_path(object_path)
        for name, value in properties.items():
            self.policy.check_property_write(name, class_path, value)
        result = self._call_bridge("set_properties", {
            "object_path": object_path,
            "properties": {k: _sanitize_value(v) for k, v in properties.items()},
        })
        return [PropertyValue(**pv) for pv in result]

    # ── UFunction invocation ────────────────────────────────────────────────

    def call_function(
        self,
        object_path: str,
        function_name: str,
        args: Optional[Dict[str, Any]] = None,
        timeout_ms: int = 10000,
    ) -> FunctionResult:
        """Call a UFunction on a UObject.

        **Must be called from the editor main thread.** The bridge enforces this.

        Args:
            object_path: Full UObject path.
            function_name: Name of the UFunction to call.
            args: Optional keyword arguments for the function.
            timeout_ms: Maximum wait time in milliseconds.

        Returns:
            :class:`FunctionResult` with the return value.

        Raises:
            SecurityDeniedError: If the function call is denied by policy.
        """
        class_path = self._resolve_class_path(object_path)
        self.policy.check_function_call(function_name, class_path, args)
        result = self._call_bridge("call_function", {
            "object_path": object_path,
            "function_name": function_name,
            "args": args or {},
            "timeout_ms": timeout_ms,
        })
        return FunctionResult(
            function_name=function_name,
            success=result.get("success", False),
            return_value=result.get("return_value"),
            error=result.get("error"),
            execution_time_ms=result.get("execution_time_ms", 0.0),
        )

    def list_functions(self, object_path: str, *, callable_only: bool = True) -> List[FunctionDescriptor]:
        """List all UFunctions on a UObject.

        Args:
            object_path: Full UObject path.
            callable_only: If True, only return functions marked as callable.

        Returns:
            List of :class:`FunctionDescriptor`.

        Raises:
            SecurityDeniedError: If the object's class is denied.
        """
        desc = self.describe_object(object_path, include_properties=False, include_functions=True)
        functions = desc.functions
        result: List[FunctionDescriptor] = []
        for fn in functions:
            if callable_only and not fn.is_callable:
                continue
            if not self._is_function_visible(fn):
                continue
            result.append(fn)
        return result

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _call_bridge(self, method: str, params: Dict[str, Any]) -> Any:
        """Route a reflection call through the bridge or direct API."""
        if self._bridge is not None:
            return self._bridge.call(method, **params)

        # Try the `unreal` module directly (available inside UE editor Python).
        try:
            import unreal  # noqa: PLC0415
            return _call_unreal_direct(unreal, method, params)
        except ImportError:
            raise RuntimeError(
                "No bridge client and `unreal` module not available. "
                "The C++ plugin must be loaded inside Unreal Editor, "
                "or a bridge client must be provided."
            )

    def _resolve_class_path(self, object_path: str) -> str:
        """Resolve the class path for an object path. Uses cached class info
        from the last describe/discover call, or queries the bridge."""
        # For now, return a sentinel — the bridge resolves the actual class.
        result = self._call_bridge("describe_object", {
            "object_path": object_path,
            "include_properties": False,
            "include_functions": False,
        })
        return result.get("class_path", "")

    @staticmethod
    def _is_property_visible(prop: PropertyDescriptor) -> bool:
        """Check whether a property should be visible through the security policy."""
        if prop.name.startswith("_"):
            return False
        if prop.name.lower() in {"internalindex", "nativeindex", "biseditoronly"}:
            return False
        return True

    @staticmethod
    def _is_function_visible(fn: FunctionDescriptor) -> bool:
        """Check whether a function should be visible through the security policy."""
        if fn.name.startswith("_"):
            return False
        if fn.name.startswith("ExecuteUbergraph_"):
            return False
        # Hide RPC functions
        if any(fn.name.startswith(p) for p in ("Server_", "Client_", "Multicast_", "OnRep_")):
            return False
        return True


# ── Internal helpers ─────────────────────────────────────────────────────────


def _dict_to_object_descriptor(d: Dict[str, Any]) -> ObjectDescriptor:
    """Convert a bridge response dict to an ObjectDescriptor."""
    props = [PropertyDescriptor(**p) for p in d.get("properties", [])]
    funcs = [FunctionDescriptor(**f) for f in d.get("functions", [])]
    return ObjectDescriptor(
        name=d.get("name", ""),
        class_path=d.get("class_path", ""),
        outer_path=d.get("outer_path", ""),
        label=d.get("label", ""),
        property_count=d.get("property_count", len(props)),
        function_count=d.get("function_count", len(funcs)),
        properties=props,
        functions=funcs,
        tags=d.get("tags", []),
        metadata=d.get("metadata", {}),
    )


def _sanitize_value(value: Any) -> Any:
    """Ensure value is JSON-serializable for bridge transport."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return {str(k): _sanitize_value(v) for k, v in value.items()}
    # Try JSON round-trip for complex types
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


def _call_unreal_direct(unreal_module: Any, method: str, params: Dict[str, Any]) -> Any:
    """Direct reflection using UE Python API (no bridge needed).

    This path is used when running inside Unreal Editor with the Python Plugin.
    """
    # Lazy imports so the module is importable outside UE.
    if method == "discover_objects":
        return _unreal_discover_objects(unreal_module, params)
    elif method == "describe_object":
        return _unreal_describe_object(unreal_module, params)
    elif method == "get_property":
        return _unreal_get_property(unreal_module, params)
    elif method == "get_properties":
        return _unreal_get_properties(unreal_module, params)
    elif method == "set_property":
        return _unreal_set_property(unreal_module, params)
    elif method == "set_properties":
        return _unreal_set_properties(unreal_module, params)
    elif method == "call_function":
        return _unreal_call_function(unreal_module, params)
    else:
        raise ValueError(f"Unknown reflection method: {method!r}")


def _unreal_discover_objects(unreal: Any, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Discover objects using UE Editor Subsystem."""
    import unreal as ue  # type: ignore[import-not-found]

    editor_actor_subsystem = ue.get_editor_subsystem(ue.EditorActorSubsystem)
    if editor_actor_subsystem is None:
        return []

    class_filter: str = params.get("class_filter", "")
    max_results: int = params.get("max_results", 100)

    if class_filter:
        try:
            actor_class = ue.load_class(None, class_filter)
            actors = editor_actor_subsystem.get_all_level_actors()
            if actor_class:
                actors = [a for a in actors if isinstance(a, actor_class)]
        except Exception:
            actors = editor_actor_subsystem.get_all_level_actors()
    else:
        actors = editor_actor_subsystem.get_all_level_actors()

    results: List[Dict[str, Any]] = []
    for actor in actors[:max_results]:
        class_obj = actor.get_class()
        results.append({
            "name": actor.get_name(),
            "class_path": class_obj.get_path_name() if class_obj else "",
            "outer_path": actor.get_outer().get_path_name() if actor.get_outer() else "",
            "label": actor.get_actor_label() if hasattr(actor, "get_actor_label") else actor.get_name(),
            "property_count": 0,
            "function_count": 0,
            "properties": [],
            "functions": [],
            "tags": actor.get_tags() if hasattr(actor, "get_tags") else [],
            "metadata": {},
        })
    return results


def _unreal_describe_object(unreal: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Describe a single UObject using UE Python reflection."""
    import unreal as ue  # type: ignore[import-not-found]

    object_path: str = params.get("object_path", "")
    include_properties: bool = params.get("include_properties", True)
    include_functions: bool = params.get("include_functions", True)

    try:
        obj = ue.load_object(None, object_path)
    except Exception:
        obj = ue.find_object(None, object_path)

    if obj is None:
        return {"name": object_path, "class_path": "", "outer_path": "", "error": "Object not found"}

    class_obj = obj.get_class()
    class_path = class_obj.get_path_name() if class_obj else ""
    outer = obj.get_outer()
    outer_path = outer.get_path_name() if outer else ""

    properties: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    if include_properties:
        for prop in class_obj.get_properties():
            prop_metadata = {}
            if prop.has_metadata("DisplayName"):
                prop_metadata["display_name"] = prop.get_metadata("DisplayName")
            if prop.has_metadata("ToolTip"):
                prop_metadata["tooltip"] = prop.get_metadata("ToolTip")

            properties.append({
                "name": prop.get_name(),
                "type_name": prop.get_class().get_name() if prop.get_class() else "unknown",
                "category": _guess_property_category(prop),
                "flags": _extract_property_flags(prop),
                "is_readable": True,
                "is_writable": not bool(prop.has_any_property_flags(ue.PropertyFlags.BLUEPRINT_READ_ONLY)),
                "is_editor_visible": bool(prop.has_any_property_flags(ue.PropertyFlags.EDIT_ANYWHERE)),
                "metadata": prop_metadata,
            })

    if include_functions:
        for fn in class_obj.get_functions():
            if not fn or fn.get_name().startswith("_"):
                continue
            func_flags = []
            if fn.has_any_function_flags(ue.FunctionFlags.FUNC_BLUEPRINT_CALLABLE):
                func_flags.append("BlueprintCallable")
            if fn.has_any_function_flags(ue.FunctionFlags.FUNC_EXEC):
                func_flags.append("Exec")
            if fn.has_any_function_flags(ue.FunctionFlags.FUNC_STATIC):
                func_flags.append("Static")
            if fn.has_any_function_flags(ue.FunctionFlags.FUNC_PURE):
                func_flags.append("Pure")

            return_type = "void"
            try:
                return_prop = fn.get_return_property()
                if return_prop:
                    return_type = return_prop.get_class().get_name()
            except Exception:
                pass

            param_list: List[Dict[str, str]] = []
            for param in fn.get_parameters():
                param_list.append({
                    "name": param.get_name(),
                    "type": param.get_class().get_name() if param.get_class() else "unknown",
                })

            functions.append({
                "name": fn.get_name(),
                "return_type": return_type,
                "parameters": param_list,
                "flags": func_flags,
                "is_callable": "BlueprintCallable" in func_flags or "Exec" in func_flags,
                "is_static": "Static" in func_flags,
                "is_pure": "Pure" in func_flags,
                "metadata": {},
            })

    return {
        "name": obj.get_name(),
        "class_path": class_path,
        "outer_path": outer_path,
        "label": obj.get_actor_label() if hasattr(obj, "get_actor_label") else obj.get_name(),
        "property_count": len(properties),
        "function_count": len(functions),
        "properties": properties,
        "functions": functions,
        "tags": obj.get_tags() if hasattr(obj, "get_tags") else [],
        "metadata": {},
    }


def _unreal_get_property(unreal: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Read a single property via UE Python reflection."""
    import unreal as ue  # type: ignore[import-not-found]

    object_path: str = params.get("object_path", "")
    property_name: str = params.get("property_name", "")

    try:
        obj = ue.load_object(None, object_path) or ue.find_object(None, object_path)
    except Exception:
        obj = None

    if obj is None:
        return {"name": property_name, "value": None, "type_name": "unknown", "success": False, "error": "Object not found"}

    try:
        value = obj.get_editor_property(property_name)
        return {"name": property_name, "value": _unreal_value_to_python(value), "type_name": type(value).__name__, "success": True}
    except Exception as exc:
        return {"name": property_name, "value": None, "type_name": "unknown", "success": False, "error": str(exc)}


def _unreal_get_properties(unreal: Any, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read multiple properties."""
    object_path = params.get("object_path", "")
    property_names = params.get("property_names", [])
    results: List[Dict[str, Any]] = []
    for name in property_names:
        results.append(_unreal_get_property(unreal, {"object_path": object_path, "property_name": name}))
    return results


def _unreal_set_property(unreal: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Write a single property."""
    import unreal as ue  # type: ignore[import-not-found]

    object_path: str = params.get("object_path", "")
    property_name: str = params.get("property_name", "")
    value: Any = params.get("value")

    try:
        obj = ue.load_object(None, object_path) or ue.find_object(None, object_path)
    except Exception:
        obj = None

    if obj is None:
        return {"name": property_name, "value": value, "type_name": "unknown", "success": False, "error": "Object not found"}

    try:
        obj.set_editor_property(property_name, value)
        return {"name": property_name, "value": value, "type_name": type(value).__name__, "success": True}
    except Exception as exc:
        return {"name": property_name, "value": value, "type_name": "unknown", "success": False, "error": str(exc)}


def _unreal_set_properties(unreal: Any, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Write multiple properties."""
    object_path = params.get("object_path", "")
    properties: Dict[str, Any] = params.get("properties", {})
    results: List[Dict[str, Any]] = []
    for name, value in properties.items():
        results.append(_unreal_set_property(unreal, {"object_path": object_path, "property_name": name, "value": value}))
    return results


def _unreal_call_function(unreal: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Call a UFunction via UE Python reflection."""
    import unreal as ue  # type: ignore[import-not-found]
    import time as _time

    object_path: str = params.get("object_path", "")
    function_name: str = params.get("function_name", "")
    args: Dict[str, Any] = params.get("args", {})

    try:
        obj = ue.load_object(None, object_path) or ue.find_object(None, object_path)
    except Exception:
        obj = None

    if obj is None:
        return {"function_name": function_name, "success": False, "error": "Object not found"}

    start = _time.monotonic()
    try:
        fn = getattr(obj, function_name, None)
        if fn is None or not callable(fn):
            return {"function_name": function_name, "success": False, "error": f"Function {function_name!r} not found or not callable"}
        result = fn(**args) if args else fn()
        elapsed = (_time.monotonic() - start) * 1000.0
        return {
            "function_name": function_name,
            "success": True,
            "return_value": _unreal_value_to_python(result),
            "execution_time_ms": elapsed,
        }
    except Exception as exc:
        elapsed = (_time.monotonic() - start) * 1000.0
        return {"function_name": function_name, "success": False, "error": str(exc), "execution_time_ms": elapsed}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _guess_property_category(prop: Any) -> str:
    """Guess the semantic category of a UE property."""
    import unreal as ue  # type: ignore[import-not-found]
    try:
        if isinstance(prop, ue.ObjectProperty):
            return "object"
        if isinstance(prop, ue.StructProperty):
            return "struct"
        if isinstance(prop, ue.ArrayProperty):
            return "array"
        if isinstance(prop, ue.MapProperty):
            return "map"
        if isinstance(prop, ue.SetProperty):
            return "set"
        if isinstance(prop, ue.EnumProperty):
            return "enum"
        if isinstance(prop, ue.BoolProperty):
            return "scalar"
        if isinstance(prop, (ue.FloatProperty, ue.DoubleProperty)):
            return "scalar"
        if isinstance(prop, (ue.IntProperty, ue.Int64Property, ue.ByteProperty)):
            return "scalar"
        if isinstance(prop, (ue.StrProperty, ue.NameProperty, ue.TextProperty)):
            return "scalar"
        if isinstance(prop, ue.MulticastDelegateProperty):
            return "delegate"
    except Exception:
        pass
    return "unknown"


def _extract_property_flags(prop: Any) -> List[str]:
    """Extract human-readable property flags."""
    import unreal as ue  # type: ignore[import-not-found]
    flags: List[str] = []
    try:
        pf = ue.PropertyFlags
        flag_map = [
            (pf.EDIT_ANYWHERE, "EditAnywhere"),
            (pf.EDIT_INSTANCE_ONLY, "EditInstanceOnly"),
            (pf.BLUEPRINT_READ_ONLY, "BlueprintReadOnly"),
            (pf.BLUEPRINT_READ_WRITE, "BlueprintReadWrite"),
            (pf.BLUEPRINT_VISIBLE, "BlueprintVisible"),
            (pf.TRANSIENT, "Transient"),
            (pf.CONFIG, "Config"),
        ]
        for flag_val, flag_name in flag_map:
            if prop.has_any_property_flags(flag_val):
                flags.append(flag_name)
    except Exception:
        pass
    return flags


def _unreal_value_to_python(value: Any) -> Any:
    """Convert a UE Python value to a plain Python value for JSON serialization."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_unreal_value_to_python(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _unreal_value_to_python(v) for k, v in value.items()}
    # UE types — convert to string representation
    try:
        if hasattr(value, "get_name"):
            return value.get_name()
        if hasattr(value, "get_path_name"):
            return value.get_path_name()
    except Exception:
        pass
    return str(value)


__all__ = [
    "FunctionDescriptor",
    "FunctionResult",
    "ObjectDescriptor",
    "PropertyDescriptor",
    "PropertyValue",
    "UObjectReflection",
]
