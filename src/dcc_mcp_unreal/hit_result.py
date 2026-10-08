"""Decode Unreal's public native-break binding without reflected property guesses.

NativeBreak functions are intentionally absent from GameplayStatics in Python.
StructBase.to_tuple() invokes that same native break function. Supported Unreal
layouts have a common 11-field prefix and trace endpoints as their last fields;
bone/element fields added between them do not change the measurements we use.
"""

from __future__ import annotations

import math


def _vector(value) -> dict:
    values = {axis: getattr(value, axis) for axis in "xyz"}
    if any(type(item) not in (int, float) or not math.isfinite(item) for item in values.values()):
        raise ValueError("Native hit vector contains non-finite coordinates")
    return values


def _identity(value):
    if value is None:
        return None
    identity = {"name": value.get_name(), "path": value.get_path_name(), "class": value.get_class().get_path_name()}
    if any(not isinstance(item, str) or not item for item in identity.values()):
        raise ValueError("Native hit object identity is incomplete")
    return identity


def read_hit_result(hit) -> dict:
    """Read native BreakHitResult values; None is the trace API's no-blocking-hit result.

    This must run on the Unreal game thread, like the collision query itself.
    No text export, bounds, guessed properties or raw memory are consumed.
    """
    fields = ("distance_cm", "time", "location", "impact_point", "normal", "impact_normal", "actor", "component")
    if hit is None:
        return {"status": "no_hit", "blocking_hit": False, "start_penetrating": False, **dict.fromkeys(fields)}
    reader = getattr(hit, "to_tuple", None)
    if not callable(reader):
        raise RuntimeError("HitResult.to_tuple native-break binding is unavailable")
    values = reader()
    if not isinstance(values, tuple) or len(values) not in (16, 17, 18):
        raise ValueError("Unsupported native BreakHitResult tuple layout")
    blocking, initial, time, distance, location, impact, normal, impact_normal, _material, actor, component = values[
        :11
    ]
    if type(blocking) is not bool or type(initial) is not bool:
        raise ValueError("Native hit flags must be booleans")
    if any(type(item) not in (int, float) or not math.isfinite(item) for item in (time, distance)):
        raise ValueError("Native hit time and distance must be finite numbers")
    if not 0 <= time <= 1 or distance < 0:
        raise ValueError("Native hit time or distance is out of range")
    if not blocking:
        raise ValueError("A non-None single blocking trace result must be blocking")
    # These vectors also validate that the decoded tail is the trace endpoint pair.
    start, end = (_vector(value) for value in values[-2:])
    return {
        "status": "hit",
        "blocking_hit": blocking,
        "start_penetrating": initial,
        "distance_cm": distance,
        "time": time,
        "location": _vector(location),
        "impact_point": _vector(impact),
        "normal": _vector(normal),
        "impact_normal": _vector(impact_normal),
        "actor": _identity(actor),
        "component": _identity(component),
        "start": start,
        "end": end,
    }


__all__ = ["read_hit_result"]
