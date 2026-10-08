"""Read native collision results without relying on Python HitResult properties."""

from __future__ import annotations

import math

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_unreal.hit_result import read_hit_result

CHANNELS = ("visibility", "camera")
MAX_CM = 10_000_000.0
HIT_FIELDS = ("distance_cm", "time", "location", "impact_point", "normal", "impact_normal", "actor", "component")


def _number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _vector(value, name: str) -> dict:
    if not isinstance(value, dict) or set(value) != {"x", "y", "z"}:
        raise ValueError(f"{name} must contain exactly x, y, z")
    if any(not _number(item) or abs(item) > MAX_CM for item in value.values()):
        raise ValueError(f"{name} coordinates must be finite numbers within +/-{MAX_CM:g} cm")
    return value


def _world(unreal, mode: str):
    # Fall back only for a missing API, never for a failed call or a missing world.
    subsystem_type = getattr(unreal, "UnrealEditorSubsystem", None)
    subsystem_getter = getattr(unreal, "get_editor_subsystem", None)
    method_name = "get_game_world" if mode == "pie" else "get_editor_world"
    if subsystem_type is not None and callable(subsystem_getter):
        subsystem = subsystem_getter(subsystem_type)
        if subsystem is None:
            raise RuntimeError("Unreal editor subsystem is unavailable")
        getter = getattr(subsystem, method_name, None)
        if callable(getter):
            return getter()
    getter = getattr(getattr(unreal, "EditorLevelLibrary", None), method_name, None)
    if not callable(getter):
        raise RuntimeError(f"Unreal world API {method_name} is unavailable")
    return getter()


def _validate_result(result: dict, path: str, start: dict, end: dict, channel: str, complex_: bool, ignored: list):
    if result.get("status") not in ("hit", "no_hit"):
        raise ValueError("native result omitted hit/no_hit status")
    if any(type(result.get(key)) is not bool for key in ("blocking_hit", "start_penetrating", "trace_complex")):
        raise ValueError("native hit flags must be booleans")
    if result.get("unit") != "cm" or result.get("coordinate_space") != "world":
        raise ValueError("native result must use world coordinates and cm")
    if not isinstance(result.get("world"), dict) or result["world"].get("path") != path:
        raise ValueError("native result belongs to a different world")
    if any(not isinstance(result["world"].get(key), str) or not result["world"][key] for key in ("name", "type")):
        raise ValueError("native world identity is incomplete")
    length = math.dist(tuple(start[axis] for axis in "xyz"), tuple(end[axis] for axis in "xyz"))
    if not _number(result.get("trace_length_cm")) or not math.isclose(
        result["trace_length_cm"], length, rel_tol=1e-5, abs_tol=0.01
    ):
        raise ValueError("native trace length differs from the requested segment")
    if result.get("start") != start or result.get("end") != end:
        raise ValueError("native result omitted the requested endpoints")
    if (
        result.get("collision_channel") != channel
        or result["trace_complex"] != complex_
        or result.get("ignored_actor_paths") != ignored
    ):
        raise ValueError("native result differs from the requested collision query")
    if any(key not in result for key in HIT_FIELDS):
        raise ValueError("native result omitted hit fields")
    if result["status"] == "no_hit":
        if result["blocking_hit"] or result["start_penetrating"] or any(result[key] is not None for key in HIT_FIELDS):
            raise ValueError("no_hit must have false flags and null hit fields")
        return
    if (
        not result["blocking_hit"]
        or not _number(result["distance_cm"])
        or not 0 <= result["distance_cm"] <= length + 0.01
    ):
        raise ValueError("hit must contain a blocking distance within the segment")
    if not _number(result["time"]) or not 0 <= result["time"] <= 1:
        raise ValueError("hit time must be a fraction within [0, 1]")
    for key in ("location", "impact_point", "normal", "impact_normal"):
        _vector(result[key], key)
    tolerance = max(0.01, length * 1e-6)
    if result["start_penetrating"]:
        if result["distance_cm"] != 0 or result["time"] != 0:
            raise ValueError("initial penetration must have zero distance and hit fraction")
        if (
            math.dist(
                tuple(result["impact_point"][axis] for axis in "xyz"),
                tuple(result["location"][axis] for axis in "xyz"),
            )
            > tolerance
        ):
            raise ValueError("initial penetration must have matching location and impact point")
    else:
        if not math.isclose(result["distance_cm"], result["time"] * length, rel_tol=1e-5, abs_tol=tolerance):
            raise ValueError("native distance and hit fraction are inconsistent")
        expected = {axis: start[axis] + result["time"] * (end[axis] - start[axis]) for axis in "xyz"}
        for key in ("location", "impact_point"):
            if (
                math.dist(tuple(result[key][axis] for axis in "xyz"), tuple(expected[axis] for axis in "xyz"))
                > tolerance
            ):
                raise ValueError("native hit point is inconsistent with the segment")
        for key in ("normal", "impact_normal"):
            if not math.isclose(math.sqrt(sum(item * item for item in result[key].values())), 1.0, abs_tol=1e-3):
                raise ValueError("native hit normal must have unit length")
    for key in ("actor", "component"):
        identity = result[key]
        if identity is not None and (
            not isinstance(identity, dict)
            or any(
                not isinstance(identity.get(field), str) or not identity[field] for field in ("name", "path", "class")
            )
        ):
            raise ValueError(f"native {key} identity is incomplete")


@skill_entry
def line_trace(
    start: dict,
    end: dict,
    world: str,
    collision_channel: str = "visibility",
    trace_complex: bool = False,
    ignored_actor_paths: list = None,
    expected_world_path: str = "",
    **kwargs,
) -> dict:
    """Query the first blocking collision along an explicit world-space segment in cm."""
    try:
        _vector(start, "start")
        _vector(end, "end")
        length = math.dist(tuple(start[axis] for axis in "xyz"), tuple(end[axis] for axis in "xyz"))
        if not 0 < length <= MAX_CM:
            raise ValueError("trace length must be positive and at most 10000000 cm")
        if world not in ("editor", "pie") or collision_channel not in CHANNELS:
            raise ValueError("world or collision_channel is unsupported")
        if type(trace_complex) is not bool or not isinstance(expected_world_path, str):
            raise ValueError("trace_complex must be boolean and expected_world_path must be a string")
        ignored = [] if ignored_actor_paths is None else ignored_actor_paths
        if (
            not isinstance(ignored, list)
            or len(ignored) > 64
            or any(not isinstance(item, str) or not item.strip() for item in ignored)
        ):
            raise ValueError("ignored_actor_paths must contain at most 64 exact nonempty actor paths")
        if len(set(ignored)) != len(ignored):
            raise ValueError("ignored_actor_paths must be unique")
    except (ValueError, TypeError, OverflowError) as exc:
        return skill_error("Invalid line trace parameters", str(exc), reason="invalid_parameters")

    import unreal  # noqa: PLC0415

    trace = getattr(getattr(unreal, "SystemLibrary", None), "line_trace_single", None)
    reader = getattr(getattr(unreal, "HitResult", None), "to_tuple", None)
    if not callable(trace) or not callable(reader):
        return skill_error(
            "Native collision query unavailable",
            "The host must expose SystemLibrary.line_trace_single and HitResult.to_tuple",
            reason="native_bridge_unavailable",
        )
    try:
        native_start = unreal.Vector(**start)
        native_end = unreal.Vector(**end)
        # Legacy FVector uses float32. Measure and echo the actual sampled
        # coordinates rather than comparing its rounded values to Python doubles.
        start = _vector({axis: getattr(native_start, axis) for axis in "xyz"}, "native start")
        end = _vector({axis: getattr(native_end, axis) for axis in "xyz"}, "native end")
        length = math.dist(tuple(start[axis] for axis in "xyz"), tuple(end[axis] for axis in "xyz"))
        if not 0 < length <= MAX_CM:
            return skill_error(
                "Invalid native line trace segment",
                "The endpoints must remain distinct and within the length limit at native vector precision",
                reason="invalid_parameters",
            )
        selected = _world(unreal, world)
        if selected is None:
            return skill_error("Selected world unavailable", f"No {world} world is active", reason="world_unavailable")
        path = selected.get_path_name()
        if expected_world_path and expected_world_path != path:
            return skill_error(
                "World identity changed",
                "expected_world_path does not match the selected world",
                reason="world_mismatch",
                actual_world_path=path,
            )
        ignored_actors = []
        if ignored:
            actors = unreal.GameplayStatics.get_all_actors_of_class(selected, unreal.Actor)
            by_path = {actor.get_path_name(): actor for actor in actors if actor is not None}
            if any(item not in by_path for item in ignored):
                return skill_error(
                    "Ignored actor unavailable",
                    "An ignored actor path does not belong to the selected world",
                    reason="ignored_actor_not_found",
                )
            ignored_actors = [by_path[item] for item in ignored]
        channel_index = CHANNELS.index(collision_channel)
        channel = unreal.TraceTypeQuery.cast(channel_index)
        if channel.value != channel_index:
            raise RuntimeError("Unreal returned a different trace channel")
        hit = trace(
            selected,
            native_start,
            native_end,
            channel,
            trace_complex,
            ignored_actors,
            unreal.DrawDebugTrace.NONE,
            False,
        )
        result = read_hit_result(hit)
        result = {
            "success": True,
            "trace_length_cm": length,
            "start": start,
            "end": end,
            "unit": "cm",
            "coordinate_space": "world",
            "collision_channel": collision_channel,
            "trace_complex": trace_complex,
            "ignored_actor_paths": ignored,
            "world": {"name": selected.get_name(), "path": path, "type": world},
            **result,
        }
    except Exception as exc:
        return skill_error("Native collision query failed", str(exc), reason="native_call_failed")
    try:
        _validate_result(result, path, start, end, collision_channel, trace_complex, ignored)
    except (ValueError, TypeError, OverflowError) as exc:
        return skill_error(
            "Invalid native collision result", str(exc), reason="native_invalid_result", native_result=result
        )
    return skill_success(
        "Read native collision result",
        **{key: value for key, value in result.items() if key not in ("success", "message")},
    )
