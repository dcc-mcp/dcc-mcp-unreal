"""Process-scoped runtime for structured PIE playtest episodes."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections import Counter
from typing import Any

import dcc_mcp_unreal as _adapter_package
from dcc_mcp_unreal.pie_session import require_pie_context
from dcc_mcp_unreal.playtest_telemetry import (
    COMBAT_ACTIONS,
    build_action_availability,
    combat_feedback,
    normalize_telemetry_aliases,
    read_actor_telemetry,
    telemetry_deltas,
)

if not hasattr(_adapter_package, "_playtest_episode_registry"):
    _adapter_package._playtest_episode_registry = {}  # type: ignore[attr-defined]
_EPISODES: dict[str, dict[str, Any]] = _adapter_package._playtest_episode_registry  # type: ignore[attr-defined]


_ACTION_KEYS = {
    "interact": "F",
    "attack_primary": "LeftMouseButton",
    "attack_secondary": "RightMouseButton",
    "melee": "V",
    "explosive": "Q",
    "skill": "E",
    "reload": "R",
    "jump": "SpaceBar",
}
_MOVE_KEYS = {
    "forward": "W",
    "backward": "S",
    "left": "A",
    "right": "D",
}
_TARGET_ACTIONS = {
    "navigate_to_entity",
    "face_entity",
    "attack_primary_entity",
    "attack_secondary_entity",
    "melee_entity",
    "explosive_entity",
    "skill_entity",
}
_NAVIGATION_ACTIONS = {"navigate_to_entity", "navigate_to_location"}


def _unreal():
    import unreal  # noqa: PLC0415

    return unreal


def _pie_context():
    context = require_pie_context(_unreal())
    return context.unreal, context.world, context.controller, context.pawn


def _class_name(value: Any) -> str:
    unreal_class = value.get_class() if value is not None else None
    return str(unreal_class.get_name()) if unreal_class is not None else ""


def _actor_name(actor: Any) -> str:
    return str(actor.get_name())


def _vector(value: Any) -> dict[str, float]:
    return {"x": float(value.x), "y": float(value.y), "z": float(value.z)}


def _rotator(value: Any) -> dict[str, float]:
    return {"pitch": float(value.pitch), "yaw": float(value.yaw), "roll": float(value.roll)}


def _distance(left: Any, right: Any) -> float:
    delta = left - right
    return float(math.sqrt(float(delta.x) ** 2 + float(delta.y) ** 2 + float(delta.z) ** 2))


def _target_location(unreal: Any, value: Any):
    if not isinstance(value, dict) or any(axis not in value for axis in ("x", "y", "z")):
        raise ValueError("target_location must explicitly provide x, y, and z")
    try:
        coordinates = [float(value[axis]) for axis in ("x", "y", "z")]
    except (TypeError, ValueError) as exc:
        raise ValueError("target_location coordinates must be numbers") from exc
    if any(not math.isfinite(item) or abs(item) > 1_000_000.0 for item in coordinates):
        raise ValueError("target_location coordinates must be finite and within world bounds")
    return unreal.Vector(*coordinates)


def _actor_tags(actor: Any) -> list[str]:
    try:
        return [str(tag) for tag in actor.get_editor_property("tags")]
    except Exception:
        return []


def _actor_hidden(actor: Any) -> bool:
    method = getattr(actor, "is_hidden", None)
    if callable(method):
        try:
            return bool(method())
        except Exception:
            pass
    for property_name in ("bHidden", "hidden"):
        try:
            return bool(actor.get_editor_property(property_name))
        except Exception:
            continue
    return False


def _json_scalar(value: Any):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return _vector(value)
    if hasattr(value, "pitch") and hasattr(value, "yaw") and hasattr(value, "roll"):
        return _rotator(value)
    return None


def _attributes(actor: Any, names: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names[:24]:
        if not name or not str(name).replace("_", "").isalnum():
            continue
        try:
            value = actor.get_editor_property(str(name))
        except Exception:
            continue
        encoded = _json_scalar(value)
        if encoded is not None:
            result[str(name)] = encoded
    return result


def _components(unreal: Any, actor: Any, attribute_names: list[str]) -> list[dict[str, Any]]:
    component_class = getattr(unreal, "ActorComponent", None)
    getter = getattr(actor, "get_components_by_class", None)
    if component_class is None or not callable(getter):
        return []
    try:
        components = list(getter(component_class))
    except Exception:
        return []
    return [
        {
            "name": _actor_name(component),
            "class": _class_name(component),
            "attributes": _attributes(component, attribute_names),
        }
        for component in components[:24]
        if component is not None
    ]


def _entity(
    unreal: Any,
    actor: Any,
    player_location: Any,
    attribute_names: list[str],
    telemetry_aliases: dict[str, list[str]],
    *,
    include_components: bool = False,
) -> dict[str, Any]:
    location = actor.get_actor_location()
    velocity = None
    velocity_getter = getattr(actor, "get_velocity", None)
    if callable(velocity_getter):
        try:
            velocity = _vector(velocity_getter())
        except Exception:
            velocity = None
    result = {
        "name": _actor_name(actor),
        "class": _class_name(actor),
        "hidden": _actor_hidden(actor),
        "location": _vector(location),
        "rotation": _rotator(actor.get_actor_rotation()),
        "velocity": velocity,
        "distance_to_player": _distance(location, player_location),
        "tags": _actor_tags(actor),
        "attributes": _attributes(actor, attribute_names),
        "telemetry": read_actor_telemetry(unreal, actor, telemetry_aliases),
    }
    if include_components:
        result["components"] = _components(unreal, actor, attribute_names)
    return result


def _line_of_sight(controller: Any, actor: Any):
    method = getattr(controller, "line_of_sight_to", None)
    if not callable(method):
        return None
    try:
        return bool(method(actor))
    except Exception:
        return None


def _line_of_fire(unreal: Any, controller: Any, player: Any, actor: Any):
    trace = getattr(getattr(unreal, "SystemLibrary", None), "line_trace_single", None)
    view_point = getattr(controller, "get_player_view_point", None)
    if not callable(trace) or not callable(view_point):
        return None
    try:
        start, _rotation = view_point()
        end = actor.get_actor_location()
        hit = trace(
            player,
            start,
            end,
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            True,
            [player],
            unreal.DrawDebugTrace.NONE,
            True,
        )
        if hit is None:
            return True
        blocking = bool(hit.get_editor_property("blocking_hit"))
        hit_actor = hit.get_editor_property("hit_actor")
        return not blocking or hit_actor is actor or _actor_name(hit_actor) == _actor_name(actor)
    except Exception:
        return None


def _contains_any(value: str, needles: list[str]) -> bool:
    folded = value.casefold()
    return any(str(needle).casefold() in folded for needle in needles if needle)


def _matches(actor: Any, selectors: dict[str, Any], pawn_ids: set[int]) -> bool:
    if _actor_hidden(actor) and not selectors.get("include_hidden", False):
        return False
    class_name = _class_name(actor)
    if _contains_any(class_name, selectors.get("exclude_class_contains", [])):
        return False
    if selectors.get("include_pawns", True) and id(actor) in pawn_ids:
        return True
    actor_name = _actor_name(actor)
    if _contains_any(actor_name, selectors.get("name_contains", [])):
        return True
    if _contains_any(class_name, selectors.get("class_contains", [])):
        return True
    requested_tags = {str(item).casefold() for item in selectors.get("tags", []) if item}
    actor_tags = {item.casefold() for item in _actor_tags(actor)}
    return bool(requested_tags and requested_tags.intersection(actor_tags))


def _call_bool(value: Any, method_name: str):
    method = getattr(value, method_name, None)
    if not callable(method):
        return None
    try:
        return bool(method())
    except Exception:
        return None


def _runtime_state(unreal: Any, world: Any, controller: Any, player: Any) -> dict[str, Any]:
    game_mode = None
    get_game_mode = getattr(unreal.GameplayStatics, "get_game_mode", None)
    if callable(get_game_mode):
        try:
            game_mode = get_game_mode(world)
        except Exception:
            game_mode = None

    default_pawn_class = ""
    if game_mode is not None:
        try:
            configured_pawn_class = game_mode.get_editor_property("default_pawn_class")
            get_name = getattr(configured_pawn_class, "get_name", None)
            default_pawn_class = str(get_name()) if callable(get_name) else str(configured_pawn_class or "")
        except Exception:
            default_pawn_class = ""

    player_start_count = None
    player_start_class = getattr(unreal, "PlayerStart", None)
    if player_start_class is not None:
        try:
            player_start_count = len(unreal.GameplayStatics.get_all_actors_of_class(world, player_start_class))
        except Exception:
            player_start_count = None

    possessed_pawn = None
    get_pawn = getattr(controller, "get_pawn", None)
    if callable(get_pawn):
        try:
            possessed_pawn = get_pawn()
        except Exception:
            possessed_pawn = None

    widgets = []
    widget_library = getattr(unreal, "WidgetBlueprintLibrary", None)
    user_widget_class = getattr(unreal, "UserWidget", None)
    get_widgets = getattr(widget_library, "get_all_widgets_of_class", None)
    if callable(get_widgets) and user_widget_class is not None:
        try:
            active_widgets = list(get_widgets(world, user_widget_class, False))
        except Exception:
            active_widgets = []
        for widget in active_widgets[:32]:
            if widget is None:
                continue
            visibility = None
            get_visibility = getattr(widget, "get_visibility", None)
            if callable(get_visibility):
                try:
                    visibility = str(get_visibility())
                except Exception:
                    visibility = None
            widgets.append(
                {
                    "name": _actor_name(widget),
                    "class": _class_name(widget),
                    "visibility": visibility,
                    "in_viewport": _call_bool(widget, "is_in_viewport"),
                    "enabled": _call_bool(widget, "get_is_enabled"),
                }
            )
        widgets.sort(key=lambda item: (item["class"], item["name"]))

    player_class = _class_name(player)
    return {
        "game_mode_class": _class_name(game_mode),
        "default_pawn_class": default_pawn_class,
        "player_start_count": player_start_count,
        "controller_class": _class_name(controller),
        "pawn_class": player_class,
        "possessed": possessed_pawn is player if possessed_pawn is not None else None,
        "spectating": "spectator" in player_class.casefold(),
        "active_widget_count": len(widgets),
        "active_widgets": widgets,
    }


def _observation_hash(observation: dict[str, Any]) -> str:
    payload = json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def observe(selectors: dict[str, Any]) -> dict[str, Any]:
    unreal, world, controller, player = _pie_context()
    player_location = player.get_actor_location()
    pawns = list(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn))
    pawn_ids = {id(item) for item in pawns if item is not player}
    candidates = list(pawns)
    if selectors.get("class_contains") or selectors.get("name_contains") or selectors.get("tags"):
        candidates.extend(unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor))

    unique: dict[str, Any] = {}
    for actor in candidates:
        if actor is None or actor is player or not _matches(actor, selectors, pawn_ids):
            continue
        unique.setdefault(_actor_name(actor), actor)

    max_distance = float(selectors.get("max_distance", 0) or 0)
    attribute_names = list(selectors.get("attribute_names", []))[:24]
    telemetry_aliases = normalize_telemetry_aliases(selectors.get("telemetry_aliases"))
    include_components = bool(selectors.get("include_components", False))
    entities = []
    for actor in unique.values():
        item = _entity(
            unreal,
            actor,
            player_location,
            attribute_names,
            telemetry_aliases,
            include_components=include_components,
        )
        item["line_of_sight"] = _line_of_sight(controller, actor)
        item["line_of_fire"] = _line_of_fire(unreal, controller, player, actor)
        entities.append(item)
    if max_distance > 0:
        entities = [item for item in entities if item["distance_to_player"] <= max_distance]
    entities.sort(key=lambda item: (item["distance_to_player"], item["name"]))
    entities = entities[: int(selectors.get("max_entities", 64))]

    player_state = _entity(
        unreal,
        player,
        player_location,
        attribute_names,
        telemetry_aliases,
        include_components=include_components,
    )
    rotation_getter = getattr(controller, "get_control_rotation", None)
    if callable(rotation_getter):
        player_state["control_rotation"] = _rotator(rotation_getter())

    action_availability = build_action_availability(player_state["telemetry"])

    observation = {
        "schema": "dcc-mcp-playtest-observation-v1",
        "world": str(world.get_name()),
        "time_seconds": float(unreal.GameplayStatics.get_time_seconds(world)),
        "runtime": _runtime_state(unreal, world, controller, player),
        "player": player_state,
        "action_availability": action_availability,
        "entity_count": len(entities),
        "entity_classes": dict(sorted(Counter(item["class"] for item in entities).items())),
        "entities": entities,
    }
    observation["observation_hash"] = _observation_hash(observation)
    return observation


def _selector_config(**kwargs) -> dict[str, Any]:
    project_telemetry_aliases = kwargs.get("telemetry_aliases")
    normalize_telemetry_aliases(project_telemetry_aliases)
    project_telemetry_aliases = {
        str(key): [str(name) for name in names] for key, names in (project_telemetry_aliases or {}).items()
    }
    return {
        "include_pawns": bool(kwargs.get("include_pawns", True)),
        "include_hidden": bool(kwargs.get("include_hidden", False)),
        "include_components": bool(kwargs.get("include_components", False)),
        "class_contains": [str(item) for item in kwargs.get("class_contains", [])][:16],
        "exclude_class_contains": [str(item) for item in kwargs.get("exclude_class_contains", [])][:16],
        "name_contains": [str(item) for item in kwargs.get("name_contains", [])][:16],
        "tags": [str(item) for item in kwargs.get("tags", [])][:16],
        "attribute_names": [str(item) for item in kwargs.get("attribute_names", [])][:24],
        "telemetry_aliases": project_telemetry_aliases,
        "max_entities": max(1, min(int(kwargs.get("max_entities", 64)), 128)),
        "max_distance": max(0.0, min(float(kwargs.get("max_distance", 0)), 1_000_000.0)),
    }


def start_episode(**kwargs) -> dict[str, Any]:
    selectors = _selector_config(**kwargs)
    baseline = observe(selectors)
    episode_id = "pie_episode_{}_{}".format(time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:8])
    _EPISODES[episode_id] = {
        "episode_id": episode_id,
        "started_at": time.time(),
        "selectors": selectors,
        "baseline_hash": baseline["observation_hash"],
        "actions": {},
        "trace": [],
    }
    return {"episode_id": episode_id, "selectors": selectors, "observation": baseline}


def get_episode(episode_id: str) -> dict[str, Any]:
    episode = _EPISODES.get(str(episode_id))
    if episode is None:
        raise KeyError("Unknown playtest episode_id: {}".format(episode_id))
    return episode


def episode_summary(episode: dict[str, Any], include_trace: bool = False) -> dict[str, Any]:
    result = {
        "episode_id": episode["episode_id"],
        "started_at": episode["started_at"],
        "elapsed_seconds": max(0.0, time.time() - episode["started_at"]),
        "selectors": episode["selectors"],
        "baseline_hash": episode["baseline_hash"],
        "action_count": len(episode["actions"]),
        "transition_count": len(episode["trace"]),
        "pending_action_ids": [
            item["action_id"] for item in episode["actions"].values() if item["status"] == "pending"
        ],
    }
    if include_trace:
        result["trace"] = list(episode["trace"])
    return result


def finish_episode(episode_id: str) -> dict[str, Any]:
    episode = get_episode(episode_id)
    try:
        unreal, _world, _controller, _player = _pie_context()
        _stop_navigation(unreal)
    except Exception:
        pass
    for action in episode["actions"].values():
        if action["status"] == "pending":
            action["status"] = "cancelled"
    result = episode_summary(episode, include_trace=True)
    _EPISODES.pop(episode_id, None)
    return result


def _resolve_target(world: Any, player: Any, selector: dict[str, Any]):
    unreal = _unreal()
    requested_tags = {str(item).casefold() for item in selector.get("target_tags", []) if item}
    exact = str(selector.get("target_name", "")).casefold()
    name_contains = str(selector.get("target_name_contains", "")).casefold()
    class_contains = str(selector.get("target_class_contains", "")).casefold()
    exclude_class_contains = [str(item) for item in selector.get("target_exclude_class_contains", [])][:16]
    include_hidden = bool(selector.get("target_include_hidden", False))
    matches = []
    player_location = player.get_actor_location()
    for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        if actor is None or actor is player:
            continue
        name = _actor_name(actor)
        class_name = _class_name(actor)
        tags = {item.casefold() for item in _actor_tags(actor)}
        if _actor_hidden(actor) and not include_hidden:
            continue
        if _contains_any(class_name, exclude_class_contains):
            continue
        if exact and name.casefold() != exact:
            continue
        if name_contains and name_contains not in name.casefold():
            continue
        if class_contains and class_contains not in class_name.casefold():
            continue
        if requested_tags and not requested_tags.intersection(tags):
            continue
        matches.append((_distance(actor.get_actor_location(), player_location), name, actor))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1]))
    return matches[0][2]


def _tap_key(unreal: Any, key: str, duration: float) -> None:
    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    inject = getattr(bridge, "inject_pie_key", None) if bridge is not None else None
    if not callable(inject) or not inject(key, True):
        raise RuntimeError("The native PIE input bridge could not press {}".format(key))
    hold_seconds = max(0.0, min(float(duration), 5.0))
    if hold_seconds <= 0:
        if not inject(key, False):
            raise RuntimeError("The native PIE input bridge could not release {}".format(key))
        return

    register = getattr(unreal, "register_slate_post_tick_callback", None)
    unregister = getattr(unreal, "unregister_slate_post_tick_callback", None)
    if not callable(register) or not callable(unregister):
        inject(key, False)
        raise RuntimeError("Slate tick callbacks are unavailable for bounded PIE input")
    release_at = time.monotonic() + hold_seconds
    holder: dict[str, Any] = {}

    def release_on_tick(_delta_seconds: float = 0.0) -> None:
        if time.monotonic() < release_at:
            return
        try:
            inject(key, False)
        finally:
            unregister(holder["handle"])

    holder["handle"] = register(release_on_tick)


def _set_key(unreal: Any, key: str, pressed: bool) -> None:
    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    inject = getattr(bridge, "inject_pie_key", None) if bridge is not None else None
    if not callable(inject) or not inject(key, pressed):
        verb = "press" if pressed else "release"
        raise RuntimeError("The native PIE input bridge could not {} {}".format(verb, key))


def _stop_navigation(unreal: Any, *, release_forward: bool = True) -> list[str]:
    errors = []
    if release_forward:
        try:
            _set_key(unreal, "W", False)
        except Exception as exc:
            errors.append(str(exc))
    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    stop = getattr(bridge, "stop_pie_navigation", None) if bridge is not None else None
    if not callable(stop) or not stop():
        errors.append("The native PIE navigation bridge could not stop movement")
    return errors


def _face_location(
    unreal: Any, controller: Any, player: Any, target_location: Any, *, include_pitch: bool = True
) -> None:
    start = player.get_actor_location()
    view_point = getattr(controller, "get_player_view_point", None)
    if callable(view_point):
        try:
            start, _rotation = view_point()
        except Exception:
            pass
    delta = target_location - start
    yaw = math.degrees(math.atan2(float(delta.y), float(delta.x)))
    horizontal = math.sqrt(float(delta.x) ** 2 + float(delta.y) ** 2)
    pitch = math.degrees(math.atan2(float(delta.z), horizontal)) if include_pitch else 0.0
    controller.set_control_rotation(unreal.Rotator(roll=0.0, pitch=pitch, yaw=yaw))


def _target_aim_location(target: Any) -> Any:
    get_bounds = getattr(target, "get_actor_bounds", None)
    if callable(get_bounds):
        for arguments in ((False, True), (False, False), ()):
            try:
                origin, extent = get_bounds(*arguments)
            except Exception:
                continue
            values = (
                float(origin.x),
                float(origin.y),
                float(origin.z),
                float(extent.x),
                float(extent.y),
                float(extent.z),
            )
            if all(math.isfinite(value) for value in values) and any(value > 0.0 for value in values[3:]):
                return origin
    return target.get_actor_location()


def _face_target(unreal: Any, controller: Any, player: Any, target: Any, *, include_pitch: bool = True) -> None:
    _face_location(
        unreal,
        controller,
        player,
        _target_aim_location(target),
        include_pitch=include_pitch,
    )


def _start_input_steering(unreal: Any, controller: Any, player: Any, target: Any) -> str:
    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    start = getattr(bridge, "start_pie_input_steering", None) if bridge is not None else None
    if callable(start) and start(_actor_name(target)):
        return "native_pawn_movement"
    _face_target(unreal, controller, player, target, include_pitch=False)
    _set_key(unreal, "W", True)
    return "legacy_key"


def _start_input_steering_to_location(unreal: Any, controller: Any, player: Any, target_location: Any) -> str:
    bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
    start = getattr(bridge, "start_pie_input_steering_to_location", None) if bridge is not None else None
    if callable(start) and start(target_location):
        return "native_pawn_movement"
    _face_location(unreal, controller, player, target_location, include_pitch=False)
    _set_key(unreal, "W", True)
    return "legacy_key"


def execute_action(episode_id: str, action_name: str, **kwargs) -> dict[str, Any]:
    episode = get_episode(episode_id)
    unreal, world, controller, player = _pie_context()
    action_name = str(action_name)
    before = observe(episode["selectors"])
    target = None
    location_target = None
    selector = {
        "target_name": kwargs.get("target_name", ""),
        "target_name_contains": kwargs.get("target_name_contains", ""),
        "target_class_contains": kwargs.get("target_class_contains", ""),
        "target_exclude_class_contains": kwargs.get("target_exclude_class_contains", []),
        "target_include_hidden": kwargs.get("target_include_hidden", False),
        "target_tags": kwargs.get("target_tags", []),
    }
    if action_name in _TARGET_ACTIONS:
        if not any(
            (
                selector["target_name"],
                selector["target_name_contains"],
                selector["target_class_contains"],
                selector["target_tags"],
            )
        ):
            raise ValueError("A bounded target selector is required for {}".format(action_name))
        target = _resolve_target(world, player, selector)
        if target is None:
            raise RuntimeError("No PIE entity matched the bounded target selector")
    elif action_name in {"navigate_to_location", "face_location"}:
        location_target = _target_location(unreal, kwargs.get("target_location"))

    if action_name == "ensure_player_control":
        runtime_state = before["runtime"]
        if not runtime_state["spectating"]:
            raise RuntimeError("The PIE controller already owns a playable pawn")
        default_pawn_class = str(runtime_state.get("default_pawn_class", ""))
        if not default_pawn_class or "spectator" in default_pawn_class.casefold():
            raise RuntimeError("The active GameMode does not define a non-spectator default pawn")
        game_mode = unreal.GameplayStatics.get_game_mode(world)
        restart_player = getattr(game_mode, "restart_player", None) if game_mode is not None else None
        if not callable(restart_player):
            raise RuntimeError("The active GameMode cannot restart the PIE player")
        restart_player(controller)
    elif action_name == "navigate_to_entity":
        bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
        navigate = getattr(bridge, "navigate_pie_to_actor", None) if bridge is not None else None
        if not callable(navigate) or not navigate(_actor_name(target)):
            raise RuntimeError("The native PIE navigation bridge could not start navigation")
    elif action_name == "navigate_to_location":
        bridge = getattr(unreal, "DccMcpAutomationLibrary", None)
        navigate = getattr(bridge, "navigate_pie_to_location", None) if bridge is not None else None
        if not callable(navigate) or not navigate(location_target):
            raise RuntimeError("The native PIE navigation bridge could not start location navigation")
    elif action_name == "face_entity":
        _face_target(unreal, controller, player, target)
    elif action_name == "face_location":
        _face_location(unreal, controller, player, location_target)
    elif action_name == "attack_primary_entity":
        visibility = _line_of_fire(unreal, controller, player, target)
        if visibility is None:
            visibility = _line_of_sight(controller, target)
        if kwargs.get("require_line_of_sight", True) and visibility is False:
            raise RuntimeError("The target is occluded from the PIE player")
        _face_target(unreal, controller, player, target)
        _tap_key(unreal, _ACTION_KEYS["attack_primary"], float(kwargs.get("duration", 0.05)))
    elif action_name == "attack_secondary_entity":
        visibility = _line_of_fire(unreal, controller, player, target)
        if visibility is None:
            visibility = _line_of_sight(controller, target)
        if kwargs.get("require_line_of_sight", True) and visibility is False:
            raise RuntimeError("The target is occluded from the PIE player")
        _face_target(unreal, controller, player, target)
        _tap_key(unreal, _ACTION_KEYS["attack_secondary"], float(kwargs.get("duration", 0.05)))
    elif action_name in {"melee_entity", "explosive_entity", "skill_entity"}:
        _face_target(unreal, controller, player, target)
        semantic_action = action_name.removesuffix("_entity")
        _tap_key(unreal, _ACTION_KEYS[semantic_action], float(kwargs.get("duration", 0.05)))
    elif action_name == "stop_navigation":
        cleanup_errors = _stop_navigation(unreal)
        if cleanup_errors:
            raise RuntimeError("; ".join(cleanup_errors))
    elif action_name == "move_relative":
        direction = str(kwargs.get("direction", "")).casefold()
        key = _MOVE_KEYS.get(direction)
        if key is None:
            raise ValueError("move_relative direction must be one of: {}".format(", ".join(_MOVE_KEYS)))
        _tap_key(unreal, key, float(kwargs.get("duration", 0.05)))
    elif action_name in _ACTION_KEYS:
        _tap_key(unreal, _ACTION_KEYS[action_name], float(kwargs.get("duration", 0.05)))
    elif action_name == "wait":
        pass
    else:
        raise ValueError("Unsupported semantic playtest action: {}".format(action_name))

    now = time.time()
    target_summary = None
    target_distance = None
    if target is not None:
        target_distance = _distance(target.get_actor_location(), player.get_actor_location())
        target_summary = {
            "name": _actor_name(target),
            "class": _class_name(target),
            "location": _vector(target.get_actor_location()),
            "distance_to_player": target_distance,
        }
    elif location_target is not None:
        target_distance = _distance(location_target, player.get_actor_location())
        target_summary = {
            "name": "world_waypoint",
            "class": "Waypoint",
            "location": _vector(location_target),
            "distance_to_player": target_distance,
        }
    action_id = "pie_action_{}".format(uuid.uuid4().hex[:10])
    record = {
        "action_id": action_id,
        "action": action_name,
        "status": "pending",
        "started_at": now,
        "timeout_seconds": max(0.1, min(float(kwargs.get("timeout_seconds", 30)), 120.0)),
        "stall_seconds": max(0.5, min(float(kwargs.get("stall_seconds", 4)), 30.0)),
        "acceptance_radius": max(10.0, min(float(kwargs.get("acceptance_radius", 125)), 10000.0)),
        "wait_duration": max(0.0, min(float(kwargs.get("duration", 0.05)), 5.0)),
        "target": target_summary,
        "last_distance": target_distance,
        "last_progress_at": now,
        "navigation_driver": "native_pathfinding" if action_name in _NAVIGATION_ACTIONS else None,
        "native_grace_seconds": min(
            1.0,
            max(0.25, max(0.5, min(float(kwargs.get("stall_seconds", 4)), 30.0)) * 0.25),
        ),
        "steering_fallback_started_at": None,
        "steering_backend": None,
        "before": before,
        "transition": None,
    }
    episode["actions"][action_id] = record
    return {
        "episode_id": episode_id,
        "action_id": action_id,
        "status": "pending",
        "action": action_name,
        "navigation_driver": record["navigation_driver"],
        "target": target_summary,
        "before_hash": before["observation_hash"],
        **({"direction": str(kwargs.get("direction", "")).casefold()} if action_name == "move_relative" else {}),
    }


def _location_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    left = before["player"]["location"]
    right = after["player"]["location"]
    return {axis: float(right[axis]) - float(left[axis]) for axis in ("x", "y", "z")}


def _finalize(episode: dict[str, Any], action: dict[str, Any], status: str, after: dict[str, Any], **extra):
    if action["action"] in _NAVIGATION_ACTIONS:
        cleanup_errors = _stop_navigation(_unreal(), release_forward=action["steering_backend"] in (None, "legacy_key"))
        extra.setdefault("navigation_driver", action["navigation_driver"])
        extra.setdefault("steering_fallback_used", action["steering_fallback_started_at"] is not None)
        extra.setdefault("steering_backend", action["steering_backend"])
        if cleanup_errors:
            extra["cleanup_errors"] = cleanup_errors
    action["status"] = status
    observed_deltas = telemetry_deltas(action["before"], after)
    if action["action"] in COMBAT_ACTIONS:
        extra.update(combat_feedback(action, after, observed_deltas))
    transition = {
        "action_id": action["action_id"],
        "action": action["action"],
        "status": status,
        "elapsed_seconds": max(0.0, time.time() - action["started_at"]),
        "target": action["target"],
        "before_hash": action["before"]["observation_hash"],
        "after_hash": after["observation_hash"],
        "player_location_delta": _location_delta(action["before"], after),
        "entity_count_delta": int(after["entity_count"]) - int(action["before"]["entity_count"]),
        "telemetry_deltas": observed_deltas,
        "after": after,
        **extra,
    }
    action["transition"] = transition
    episode["trace"].append({key: value for key, value in transition.items() if key != "after"})
    return transition


def poll_action(episode_id: str, action_id: str) -> dict[str, Any]:
    episode = get_episode(episode_id)
    action = episode["actions"].get(str(action_id))
    if action is None:
        raise KeyError("Unknown playtest action_id: {}".format(action_id))
    if action["transition"] is not None:
        return action["transition"]

    unreal, world, controller, player = _pie_context()
    after = observe(episode["selectors"])
    elapsed = max(0.0, time.time() - action["started_at"])
    if elapsed >= action["timeout_seconds"]:
        return _finalize(episode, action, "timed_out", after)

    if action["action"] in _NAVIGATION_ACTIONS:
        target = None
        if action["action"] == "navigate_to_entity":
            target_name = action["target"]["name"] if action["target"] else ""
            target = _resolve_target(world, player, {"target_name": target_name})
            if target is None:
                return _finalize(episode, action, "blocked", after, blocked_reason="target_unavailable")
            target_location = target.get_actor_location()
        else:
            target_location = _target_location(unreal, action["target"]["location"])
        distance = _distance(target_location, player.get_actor_location())
        if distance <= action["acceptance_radius"]:
            return _finalize(episode, action, "completed", after, distance_to_target=distance)
        now = time.time()
        if action["last_distance"] is None or distance < float(action["last_distance"]) - 5.0:
            action["last_distance"] = distance
            action["last_progress_at"] = now
        elif (
            action["navigation_driver"] == "native_pathfinding"
            and now - float(action["started_at"]) >= action["native_grace_seconds"]
        ):
            action["steering_backend"] = (
                _start_input_steering(unreal, controller, player, target)
                if target is not None
                else _start_input_steering_to_location(unreal, controller, player, target_location)
            )
            action["navigation_driver"] = "input_steering"
            action["steering_fallback_started_at"] = now
            action["last_progress_at"] = now
        elif now - float(action["last_progress_at"]) >= action["stall_seconds"]:
            return _finalize(
                episode,
                action,
                "blocked",
                after,
                blocked_reason="navigation_stalled",
                distance_to_target=distance,
            )
        if action["navigation_driver"] == "input_steering":
            if target is not None:
                _face_target(unreal, controller, player, target, include_pitch=False)
            else:
                _face_location(unreal, controller, player, target_location, include_pitch=False)
        return {
            "action_id": action_id,
            "action": action["action"],
            "status": "pending",
            "elapsed_seconds": elapsed,
            "distance_to_target": distance,
            "navigation_driver": action["navigation_driver"],
            "steering_fallback_used": action["steering_fallback_started_at"] is not None,
            "steering_backend": action["steering_backend"],
            "observation": after,
        }

    completion_delay = action["wait_duration"] if action["action"] == "wait" else max(0.1, action["wait_duration"])
    if elapsed >= completion_delay:
        return _finalize(episode, action, "completed", after)
    return {
        "action_id": action_id,
        "action": action["action"],
        "status": "pending",
        "elapsed_seconds": elapsed,
        "observation": after,
    }
