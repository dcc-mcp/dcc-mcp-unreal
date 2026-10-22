"""Closed codecs for two Subdivide Spline settings, not a grammar parser.

No Unreal import, asset access, graph mutation, generation or arbitrary struct
deserialization. Native copies are checked against detached canonical snapshots.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

GRAMMAR_PROPERTIES = frozenset({"grammar_selection", "modules_info"})
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_MAX_MODULES = 128
_MAX_SIZE_CM = 1_000_000_000.0


class GrammarCodecError(ValueError):
    """Unsupported native state or an invalid bounded authoring descriptor."""


def _call(owner: Any, name: str, *args: Any) -> Any:
    method = getattr(owner, name, None)
    if not callable(method):
        raise GrammarCodecError(f"Required grammar API {name} is unavailable")
    try:
        return method(*args)
    except GrammarCodecError:
        raise
    except Exception as exc:
        raise GrammarCodecError(f"Grammar API {name} failed: {str(exc)[:400]}") from exc


def _get(owner: Any, name: str) -> Any:
    return _call(owner, "get_editor_property", name)


def _class(host: Any, name: str) -> type:
    cls = getattr(host, name, None)
    if not isinstance(cls, type):
        raise GrammarCodecError(f"Required native class {name} is unavailable")
    return cls


def _exact(host: Any, value: Any, name: str) -> None:
    if type(value) is not _class(host, name):
        raise GrammarCodecError(f"Expected exact native {name}; subclasses and other aggregate types are unsupported")


def _string(value: Any, limit: int, label: str) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise GrammarCodecError(f"{label} must be a string of at most {limit} characters")
    return value


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise GrammarCodecError(f"{label} must be a boolean")
    return value


def _number(value: Any, limit: float, label: str) -> float:
    if type(value) not in (int, float) or not -limit <= value <= limit or not math.isfinite(value):
        raise GrammarCodecError(f"{label} must be finite and within +/-{limit:g}")
    return float(value)


def _name(value: Any) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value) or value.casefold() == "none":
        raise GrammarCodecError("Symbols and attribute names require 1-64 ASCII letters/digits/underscores, not None")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _export(value: Any, limit: int) -> str:
    # Include native fields not represented by the convenient display projection.
    # Export text is never accepted as input or passed to import_text.
    return _string(_call(value, "export_text"), limit, "Native struct export")


def _items(value: Any) -> list:
    if isinstance(value, (str, bytes, dict)):
        raise GrammarCodecError("modules_info must be a bounded native array")
    try:
        if len(value) > _MAX_MODULES:
            raise GrammarCodecError(f"modules_info exceeds {_MAX_MODULES} modules")
        return list(value)
    except (TypeError, ValueError) as exc:
        raise GrammarCodecError("modules_info is not a bounded native array") from exc


def _observe(host: Any, name: str, value: Any) -> dict:
    if name == "grammar_selection":
        _exact(host, value, "PCGGrammarSelection")
        selector = _get(value, "grammar_attribute")
        _exact(host, selector, "PCGAttributePropertyInputSelector")
        extra = _call(selector, "get_extra_names")
        if len(extra) > 16:
            raise GrammarCodecError("Grammar selector exceeds 16 extra names")
        observed = {
            "grammar_as_attribute": _boolean(_get(value, "grammar_as_attribute"), "grammar_as_attribute"),
            "grammar_string": _string(_get(value, "grammar_string"), 4096, "grammar_string"),
            "grammar_attribute": {
                "name": _string(str(_call(selector, "get_name")), 128, "Selector name"),
                "selection": _string(str(_call(selector, "get_selection")), 128, "Selector selection"),
                "extra_names": [_string(item, 128, "Selector extra name") for item in extra],
            },
        }
        exports = [_export(value, 32768)]
    else:
        observed, exports = [], []
        for item in _items(value):
            _exact(host, item, "PCGSubdivisionSubmodule")
            color = _get(item, "debug_color")
            _exact(host, color, "Vector4")
            observed.append(
                {
                    "symbol": _string(str(_get(item, "symbol")), 128, "Native symbol"),
                    "size": _number(_get(item, "size"), _MAX_SIZE_CM, "Native size in cm"),
                    "scalable": _boolean(_get(item, "scalable"), "scalable"),
                    "debug_color": [_number(_get(color, axis), 1e9, "Native color") for axis in "xyzw"],
                }
            )
            exports.append(_export(item, 4096))
    return {"value": observed, "native_state_fingerprint": hashlib.sha256(_json(exports).encode()).hexdigest()}


def observe_grammar_property(host: Any, settings: Any, name: str, value: Any) -> dict | None:
    """Return a bounded canonical observation, or None for non-codec settings."""
    if name not in GRAMMAR_PROPERTIES or host is None:
        return None
    cls = getattr(host, "PCGSubdivideSplineSettings", None)
    if not isinstance(cls, type) or type(settings) is not cls:
        return None
    return _observe(host, name, value)


def _copy(value: Any) -> Any:
    copied = _call(value, "copy")  # documented StructBase.copy, not UObject duplication
    if copied is value or type(copied) is not type(value):
        raise GrammarCodecError("Native struct copy did not return a detached value of the exact type")
    return copied


class GrammarSnapshot:
    """Detached immutable comparison state plus privately retained native copies.

    A fresh copy is supplied on every application, including recovery. Copies
    are checked against the immutable canonical state; a broken/aliased copy API
    cannot turn changed native wrappers into a falsely successful rollback.
    """

    def __init__(self, host: Any, name: str, value: Any):
        self.host, self.name = host, name
        self.canonical = _json(_observe(host, name, value))
        self._prototype = _copy(value) if name == "grammar_selection" else [_copy(item) for item in _items(value)]
        self.native()  # fail before graph mutation if copying changes any observed field

    def native(self) -> Any:
        value = (
            _copy(self._prototype) if self.name == "grammar_selection" else [_copy(item) for item in self._prototype]
        )
        if _json(_observe(self.host, self.name, value)) != self.canonical:
            raise GrammarCodecError("Detached grammar snapshot changed or native copy was lossy")
        return value

    def matches(self, value: Any) -> bool:
        return _json(_observe(self.host, self.name, value)) == self.canonical


def _validate(name: str, value: Any) -> None:
    if name == "grammar_selection":
        if not isinstance(value, dict):
            raise GrammarCodecError("grammar_selection requires a literal or named-attribute descriptor")
        attribute = _boolean(value.get("grammar_as_attribute"), "grammar_as_attribute")
        key = "grammar_attribute" if attribute else "grammar_string"
        if set(value) != {"grammar_as_attribute", key}:
            raise GrammarCodecError(f"grammar_selection requires exactly grammar_as_attribute and {key}")
        if attribute:
            _name(value[key])
        elif not _string(value[key], 4096, "grammar_string").strip() or "\x00" in value[key]:
            raise GrammarCodecError("grammar_string must be nonempty and contain no NUL; syntax is not parsed")
        return
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_MODULES:
        raise GrammarCodecError(f"modules_info requires 1-{_MAX_MODULES} module descriptors")
    symbols = set()
    for item in value:
        if (
            not isinstance(item, dict)
            or not {"symbol", "size", "scalable"} <= set(item)
            or set(item) - {"symbol", "size", "scalable", "debug_color"}
        ):
            raise GrammarCodecError("Each module requires symbol, size, scalable and optional debug_color only")
        symbol = _name(item["symbol"]).casefold()
        if symbol in symbols:
            raise GrammarCodecError("Module symbols must be unique, ignoring ASCII case")
        symbols.add(symbol)
        if _number(item["size"], _MAX_SIZE_CM, "Module size in cm") <= 0:
            raise GrammarCodecError("Module size must be greater than zero cm")
        _boolean(item["scalable"], "scalable")
        if "debug_color" in item:
            color = item["debug_color"]
            if not isinstance(color, list) or len(color) != 4:
                raise GrammarCodecError("debug_color requires four components")
            if any(_number(component, 1, "Debug color") < 0 for component in color):
                raise GrammarCodecError("debug_color components must be between zero and one")


def prepare_grammar_property(host: Any, settings: Any, name: str, value: Any, changes: dict) -> tuple:
    """Prevalidate and prepare before/after snapshots without touching settings."""
    _exact(host, settings, "PCGSubdivideSplineSettings")
    if name not in GRAMMAR_PROPERTIES:
        raise GrammarCodecError("Unknown grammar property")
    _validate(name, value)
    before = GrammarSnapshot(host, name, _get(settings, name))
    if name == "grammar_selection":
        native = before.native()
        as_attribute = value["grammar_as_attribute"]
        _call(native, "set_editor_property", "grammar_as_attribute", as_attribute)
        if as_attribute:
            selector = _class(host, "PCGAttributePropertyInputSelector")()
            _call(selector, "set_attribute_name", value["grammar_attribute"])
            if str(_call(selector, "get_attribute_name")).casefold() != value["grammar_attribute"].casefold():
                raise GrammarCodecError("Native grammar attribute selector readback differs")
            if len(_call(selector, "get_extra_names")) != 0:
                raise GrammarCodecError("Named grammar attributes cannot have extra selectors")
            _call(native, "set_editor_property", "grammar_attribute", selector)
        else:
            _call(native, "set_editor_property", "grammar_string", value["grammar_string"])
        if _get(native, "grammar_as_attribute") is not as_attribute:
            raise GrammarCodecError("Native grammar mode readback differs")
        if not as_attribute and _get(native, "grammar_string") != value["grammar_string"]:
            raise GrammarCodecError("Native grammar text readback differs")
    else:
        effective_input = changes.get("module_info_as_input", _get(settings, "module_info_as_input"))
        if _boolean(effective_input, "module_info_as_input"):
            raise GrammarCodecError("Fixed modules require module_info_as_input=false in the effective settings")
        native = []
        for item in value:
            module = _class(host, "PCGSubdivisionSubmodule")()
            for field in ("symbol", "size", "scalable", "debug_color"):
                _get(module, field)
            for field in ("symbol", "size", "scalable"):
                requested = float(item[field]) if field == "size" else item[field]
                _call(module, "set_editor_property", field, requested)
                observed = _get(module, field)
                if field == "symbol":
                    observed, requested = str(observed).casefold(), requested.casefold()
                if observed != requested:
                    raise GrammarCodecError(f"Native module {field} readback differs")
            if "debug_color" in item:
                color = _class(host, "Vector4")(*item["debug_color"])
                _call(module, "set_editor_property", "debug_color", color)
                actual = _get(module, "debug_color")
                if [_get(actual, axis) for axis in "xyzw"] != item["debug_color"]:
                    raise GrammarCodecError("Native module debug color readback differs")
            native.append(module)
    after = GrammarSnapshot(host, name, native)
    if not before.matches(_get(settings, name)):
        raise GrammarCodecError("Native copy preparation unexpectedly changed the source settings")
    return before, after
